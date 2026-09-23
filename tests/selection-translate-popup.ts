// The quick translation popup keeps the document interactive and ignores a
// completion for a request that was closed or superseded.

import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ControlClient, ControlCommand } from "./control.ts";
import { cmdId, runStandalone, SLOW_BUILD_FACTOR, tmpPath } from "./util.ts";
import { killAndWait, launchControlled, pressKey, sendCommandSync } from "./win-automation.ts";
import {
  getFocusedHwnd,
  getWindowRect,
  postMessage,
  setProcessDpiAware,
  setWindowPos,
  sleep,
  SWP_NOACTIVATE,
  SWP_NOZORDER,
  VK_RIGHT,
  WM_CHAR,
  WM_KEYDOWN,
  WM_KEYUP,
} from "./winapi.ts";

const VK_END = 0x23;
const VK_HOME = 0x24;
const LINE = "The quick brown fox jumps over the lazy dog";

function makeTextPdf(): Buffer {
  const enc = (s: string) => Buffer.from(s, "latin1");
  const body: Record<number, Buffer> = {};
  body[1] = enc("<< /Type /Catalog /Pages 2 0 R >>");
  body[2] = enc("<< /Type /Pages /Kids [3 0 R] /Count 1 >>");
  body[6] = enc("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>");
  const stream = `BT /F1 18 Tf 72 700 Td (${LINE}) Tj ET`;
  body[10] = enc(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
  body[3] = enc(
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] ` +
      `/Resources << /Font << /F1 6 0 R >> >> /Contents 10 0 R >>`,
  );
  const maxN = 12;
  const parts: Buffer[] = [enc("%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")];
  const offsets: Record<number, number> = {};
  let pos = parts[0]!.length;
  for (let n = 1; n <= maxN; n++) {
    offsets[n] = pos;
    const obj = Buffer.concat([enc(`${n} 0 obj\n`), body[n] ?? enc("null"), enc("\nendobj\n")]);
    parts.push(obj);
    pos += obj.length;
  }
  let xref = `xref\n0 ${maxN + 1}\n0000000000 65535 f \n`;
  for (let n = 1; n <= maxN; n++) {
    xref += `${String(offsets[n]).padStart(10, "0")} 00000 n \n`;
  }
  parts.push(enc(`${xref}trailer\n<< /Size ${maxN + 1} /Root 1 0 R >>\nstartxref\n${pos}\n%%EOF\n`));
  return Buffer.concat(parts);
}

function writeAppData(dir: string): void {
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, "SumatraPDF-settings.txt"),
    [
      "RestoreSession = false",
      "CheckForUpdates = false",
      "ShowToc = false",
      "SelectionToolbar = true",
      "TranslateEngine = Google",
      "TranslateFromLang = Auto",
      "TranslateToLang = English",
      "",
    ].join("\n"),
  );
}

function pressVKey(hwnd: number, vk: number): void {
  postMessage(hwnd, WM_KEYDOWN, vk, 0);
  postMessage(hwnd, WM_KEYUP, vk, 0);
}

async function toolbarDump(client: ControlClient): Promise<string> {
  return String((await client.request(ControlCommand.TestSelectionToolbar, []))[1] ?? "");
}

async function waitForToolbar(client: ControlClient): Promise<string> {
  const deadline = Date.now() + 4000 * SLOW_BUILD_FACTOR;
  let raw = "";
  while (Date.now() < deadline) {
    raw = await toolbarDump(client);
    if (/^visible=1$/m.test(raw)) {
      return raw;
    }
    await sleep(25);
  }
  throw new Error(`selection-translate-popup: toolbar did not appear\n${raw}`);
}

async function popup(client: ControlClient, action: string, value = ""): Promise<string> {
  const res = await client.request(ControlCommand.TestSelectionTranslatePopup, [action, value]);
  if (res[0] !== 0) {
    throw new Error(`selection-translate-popup: ${action} failed: ${String(res[1] ?? res[0])}`);
  }
  return String(res[1] ?? "");
}

function expectState(raw: string, state: string): void {
  if (!new RegExp(`^state=${state}$`, "m").test(raw)) {
    throw new Error(`selection-translate-popup: expected ${state}\n${raw}`);
  }
}

function parsePlaced(raw: string): { x: number; y: number; dx: number; dy: number } {
  const match = /^placed=(-?\d+),(-?\d+),(\d+),(\d+)$/m.exec(raw);
  if (!match || Number(match[3]) <= 0 || Number(match[4]) <= 0) {
    throw new Error(`selection-translate-popup: popup has no placement\n${raw}`);
  }
  return { x: Number(match[1]), y: Number(match[2]), dx: Number(match[3]), dy: Number(match[4]) };
}

export async function testit(): Promise<void> {
  setProcessDpiAware();

  const pdf = tmpPath("selection-translate-popup.pdf");
  const appdata = tmpPath("selection-translate-popup-appdata");
  writeFileSync(pdf, makeTextPdf());
  writeAppData(appdata);

  const { proc, client, frame } = await launchControlled(["-appdata", appdata, pdf]);
  try {
    await client.waitForRenderIdle();
    await client.setNotificationsEnabled(false);

    sendCommandSync(frame, cmdId("CmdSelectTextViaKeyboard"));
    postMessage(frame, WM_CHAR, "v".charCodeAt(0), 0);
    pressVKey(frame, VK_END);
    const toolbar = await waitForToolbar(client);
    if (!new RegExp(`^cmd=${cmdId("CmdTranslateSelectionQuick")}$`, "m").test(toolbar)) {
      throw new Error(`selection-translate-popup: default toolbar missed quick command\n${toolbar}`);
    }

    const focusedBefore = getFocusedHwnd(frame);
    const click = await client.request(ControlCommand.TestSelectionToolbar, ["CmdTranslateSelectionQuick"]);
    if (click[0] !== 0) {
      throw new Error(`selection-translate-popup: quick toolbar action failed: ${String(click[1] ?? click[0])}`);
    }
    const invalid = await popup(client, "dump");
    expectState(invalid, "Error");
    if (!/^configure=1$/m.test(invalid) || !/^visible=1$/m.test(invalid)) {
      throw new Error(`selection-translate-popup: invalid engine did not show configure error\n${invalid}`);
    }
    if (!/^header=Translation -> English$/m.test(invalid)) {
      throw new Error(`selection-translate-popup: provider/language header missing\n${invalid}`);
    }
    if (getFocusedHwnd(frame) !== focusedBefore) {
      throw new Error("selection-translate-popup: showing the popup stole keyboard focus");
    }
    if (/^visible=1$/m.test(await toolbarDump(client))) {
      throw new Error("selection-translate-popup: toolbar stayed visible behind popup");
    }

    expectState(await popup(client, "close"), "Hidden");
    await waitForToolbar(client);

    const loading = await popup(client, "start");
    expectState(loading, "Loading");
    if (!/^header=OpenAI Codex -> English$/m.test(loading)) {
      throw new Error(`selection-translate-popup: provider/language header missing\n${loading}`);
    }
    const popup0 = parsePlaced(loading);
    const frame0 = getWindowRect(frame);
    const frameWidth = frame0.right - frame0.left;
    const frameHeight = frame0.bottom - frame0.top;
    if (
      !setWindowPos(frame, frame0.left + 24, frame0.top + 16, frameWidth, frameHeight, SWP_NOZORDER | SWP_NOACTIVATE)
    ) {
      throw new Error("selection-translate-popup: failed to move frame");
    }
    const movedRaw = await popup(client, "dump");
    const moved = parsePlaced(movedRaw);
    const frameMoved = getWindowRect(frame);
    if (moved.x - popup0.x !== frameMoved.left - frame0.left || moved.y - popup0.y !== frameMoved.top - frame0.top) {
      throw new Error(`selection-translate-popup: popup did not follow frame\n${movedRaw}`);
    }
    const result = await popup(client, "result", "translated result");
    expectState(result, "Result");
    if (!/^result=translated result$/m.test(result) || !/^copy=1$/m.test(result)) {
      throw new Error(`selection-translate-popup: result controls missing\n${result}`);
    }

    expectState(await popup(client, "close"), "Hidden");
    expectState(await popup(client, "start"), "Loading");
    expectState(await popup(client, "stale", "late result"), "Loading");
    expectState(await popup(client, "close"), "Hidden");
    await waitForToolbar(client);

    expectState(await popup(client, "start"), "Loading");
    await pressKey(frame, VK_HOME, 0);
    await pressKey(frame, VK_RIGHT, 100 * SLOW_BUILD_FACTOR);
    expectState(await popup(client, "dump"), "Hidden");
  } finally {
    client.close();
    await killAndWait(proc);
  }
}

if (import.meta.main) {
  await runStandalone(testit);
}
