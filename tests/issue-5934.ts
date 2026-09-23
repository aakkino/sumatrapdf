// Issue #5934: close the translate popup with Esc / Ctrl+W.
//
// Esc is exercised with posted WM_KEYDOWN (no modifiers). Ctrl+W needs
// GetKeyState(VK_CONTROL) which posted messages do not set, so that path is
// covered by code review / manual check rather than this script.

import { writeFileSync } from "node:fs";
import { cmdId, tmpPath } from "./util";
import { ControlCommand } from "./control";
import { launchControlled, killAndWait } from "./win-automation";
import {
  enumWindows,
  getWindowPid,
  getWindowText,
  isWindowVisible,
  postMessage,
  sendMessage,
  sleep,
  VK_ESCAPE,
  WM_COMMAND,
  WM_KEYDOWN,
  WM_KEYUP,
} from "./winapi";

function makeTextPdf(): Buffer {
  const line = "hello translation window";
  const content = `BT /F1 24 Tf 72 720 Td (${line}) Tj ET`;
  const objs = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
  ];
  let pdf = "%PDF-1.5\n";
  const offsets: number[] = [];
  for (let i = 0; i < objs.length; i++) {
    offsets.push(Buffer.byteLength(pdf, "latin1"));
    pdf += `${i + 1} 0 obj\n${objs[i]}\nendobj\n`;
  }
  const xrefPos = Buffer.byteLength(pdf, "latin1");
  pdf += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n`;
  for (const off of offsets) {
    pdf += off.toString().padStart(10, "0") + " 00000 n \n";
  }
  pdf += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${xrefPos}\n%%EOF\n`;
  return Buffer.from(pdf, "latin1");
}

function pressEscape(hwnd: number): void {
  postMessage(hwnd, WM_KEYDOWN, VK_ESCAPE, 0);
  postMessage(hwnd, WM_KEYUP, VK_ESCAPE, 0);
}

function findTranslatePopup(pid: number, frame: number): number {
  let popup = 0;
  enumWindows((hwnd) => {
    if (
      hwnd !== frame &&
      getWindowPid(hwnd) === pid &&
      isWindowVisible(hwnd) &&
      getWindowText(hwnd).toLowerCase() === "translate"
    ) {
      popup = hwnd;
      return false;
    }
    return true;
  });
  return popup;
}

async function waitForPopup(
  client: Awaited<ReturnType<typeof launchControlled>>["client"],
  timeoutMs: number,
): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const response = await client.request(ControlCommand.TestSelectionTranslatePopup, ["dump", ""]);
    const dump = String(response[1] ?? "");
    if (/^visible=1$/m.test(dump)) {
      return dump;
    }
    await sleep(30);
  }
  return "";
}

async function testTranslateEscCloses(): Promise<void> {
  const pdf = tmpPath("issue-5934-translate.pdf");
  writeFileSync(pdf, makeTextPdf());

  const { proc, client, frame } = await launchControlled([pdf]);
  try {
    await client.waitForRenderIdle();

    // select some text so CmdTranslateSelection has something to show
    sendMessage(frame, WM_COMMAND, BigInt(cmdId("CmdSelectTextViaKeyboard")), 0n);
    for (let i = 0; i < 5; i++) {
      sendMessage(frame, WM_COMMAND, BigInt(cmdId("CmdExtendSelectionWordRight")), 0n);
    }

    for (const command of ["CmdTranslateSelection", "CmdTranslateSelectionQuick"]) {
      sendMessage(frame, WM_COMMAND, BigInt(cmdId(command)), 0n);
      const shown = await waitForPopup(client, 4000);
      if (!shown) {
        throw new Error(`${command}: popup did not appear (selection empty?)`);
      }

      const popup = findTranslatePopup(proc.pid!, frame);
      if (!popup) {
        throw new Error(`${command}: popup window was not found`);
      }
      pressEscape(popup);
      const deadline = Date.now() + 3000;
      while (Date.now() < deadline) {
        const response = await client.request(ControlCommand.TestSelectionTranslatePopup, ["dump", ""]);
        if (/^state=Hidden$/m.test(String(response[1] ?? ""))) {
          break;
        }
        await sleep(30);
      }
      const response = await client.request(ControlCommand.TestSelectionTranslatePopup, ["dump", ""]);
      if (!/^state=Hidden$/m.test(String(response[1] ?? ""))) {
        throw new Error(`${command}: Esc did not close the translate popup`);
      }
    }
    console.log("  translate: both generic commands use an Esc-closeable popup");
  } finally {
    client.close();
    await killAndWait(proc);
  }
}

export async function testit(): Promise<void> {
  await testTranslateEscCloses();
}

if (import.meta.main) {
  const { runStandalone } = await import("./util");
  await runStandalone(testit);
}
