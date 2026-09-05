// Provider switches must redraw each custom Edit non-client frame.

import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ControlClient, ControlCommand, withControlledSumatra } from "./control.ts";
import { EXE, runStandalone, tmpPath } from "./util.ts";
import {
  captureWindowDCRegionPixels,
  enumChildWindows,
  enumWindows,
  getClassName,
  getWindowPid,
  getWindowRect,
  getWindowText,
  isWindowVisible,
  setProcessDpiAware,
  sleep,
} from "./winapi.ts";

const CONFIG_TITLE = "Translation Providers";
const OPENAI_PROVIDER = "OpenAI-compatible";
const MICROSOFT_PROVIDER = "Microsoft Translator";
const EDIT_CLASS = "Edit";
const EXPECTED_PROVIDER_EDITS = 3;
const FRAME_THICKNESS = 1;
const FRAME_SAMPLE_INSET = 3;
const FRAME_WAIT_MS = 3000;
const FRAME_POLL_MS = 40;

function writeAppData(): string {
  const dir = tmpPath("translation-config-edit-redraw-appdata");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, "SumatraPDF-settings.txt"),
    [
      "UiLanguage = en",
      "RestoreSession = false",
      "CheckForUpdates = false",
      "TranslationProvider = Google Cloud Translation",
      "TranslateFromLang = Auto",
      "TranslateToLang = English",
      "",
    ].join("\n"),
  );
  return dir;
}

async function config(client: ControlClient, action: string, value = ""): Promise<void> {
  const res = await client.request(ControlCommand.TestTranslationConfig, [action, value]);
  if (res[0] !== 0) {
    throw new Error(`translation-config-edit-redraw: ${action} failed`);
  }
}

function findConfigWindow(pid: number): number {
  let hwnd = 0;
  enumWindows((candidate) => {
    if (getWindowPid(candidate) === pid && getWindowText(candidate) === CONFIG_TITLE) {
      hwnd = candidate;
      return false;
    }
    return true;
  });
  return hwnd;
}

async function waitForConfigWindow(pid: number): Promise<number> {
  const deadline = Date.now() + FRAME_WAIT_MS;
  while (Date.now() < deadline) {
    const hwnd = findConfigWindow(pid);
    if (hwnd) {
      return hwnd;
    }
    await sleep(FRAME_POLL_MS);
  }
  throw new Error("translation-config-edit-redraw: configuration window did not open");
}

function visibleEdits(hwnd: number): number[] {
  const edits: number[] = [];
  enumChildWindows(hwnd, (child) => {
    if (getClassName(child) === EDIT_CLASS && isWindowVisible(child)) {
      edits.push(child);
    }
    return true;
  });
  return edits;
}

function colorAt(data: Uint8Array, width: number, x: number, y: number): number {
  const i = (y * width + x) * 4;
  return data[i]! | (data[i + 1]! << 8) | (data[i + 2]! << 16);
}

function frameProblem(hwnd: number): string {
  const rect = getWindowRect(hwnd);
  const width = rect.right - rect.left;
  const height = rect.bottom - rect.top;
  if (width <= FRAME_SAMPLE_INSET * 2 || height <= FRAME_SAMPLE_INSET * 2) {
    return `invalid Edit size ${width}x${height}`;
  }
  const data = captureWindowDCRegionPixels(hwnd, 0, 0, width, height);
  if (!data) {
    return "could not capture Edit pixels";
  }

  const xs = [FRAME_SAMPLE_INSET, Math.floor(width / 2), width - FRAME_SAMPLE_INSET - FRAME_THICKNESS];
  const ys = [FRAME_SAMPLE_INSET, Math.floor(height / 2), height - FRAME_SAMPLE_INSET - FRAME_THICKNESS];
  const border = colorAt(data, width, xs[0]!, 0);
  const edgeSamples = [
    ...xs.map((x) => colorAt(data, width, x, 0)),
    ...xs.map((x) => colorAt(data, width, x, height - FRAME_THICKNESS)),
    ...ys.map((y) => colorAt(data, width, 0, y)),
    ...ys.map((y) => colorAt(data, width, width - FRAME_THICKNESS, y)),
  ];
  if (edgeSamples.some((color) => color !== border)) {
    return "Edit frame edges are not fully painted";
  }
  return "";
}

async function assertEditFrames(hwnd: number, transition: string): Promise<void> {
  const deadline = Date.now() + FRAME_WAIT_MS;
  let problem = "";
  while (Date.now() < deadline) {
    const edits = visibleEdits(hwnd);
    if (edits.length !== EXPECTED_PROVIDER_EDITS) {
      problem = `expected ${EXPECTED_PROVIDER_EDITS} visible provider Edits, got ${edits.length}`;
    } else {
      problem = edits.map(frameProblem).find((value) => value) ?? "";
    }
    if (!problem) {
      return;
    }
    await sleep(FRAME_POLL_MS);
  }
  throw new Error(`translation-config-edit-redraw: ${transition}: ${problem}`);
}

export async function testit(): Promise<void> {
  setProcessDpiAware();
  await withControlledSumatra(
    EXE,
    async (client, proc) => {
      await config(client, "open");
      const configWindow = await waitForConfigWindow(proc.pid!);

      await config(client, "provider", OPENAI_PROVIDER);
      await assertEditFrames(configWindow, "Google to OpenAI-compatible");

      await config(client, "provider", MICROSOFT_PROVIDER);
      await assertEditFrames(configWindow, "OpenAI-compatible to Microsoft");
    },
    ["-appdata", writeAppData()],
  );
}

if (import.meta.main) {
  await runStandalone(testit);
}
