// The translation configuration window keeps edits local until Save and never
// exposes API keys through its deterministic debug-control summary.

import { copyFileSync, existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { ControlClient, ControlCommand, withControlledSumatra } from "./control.ts";
import { EXE, cmdId, runStandalone, tmpPath } from "./util.ts";
import { sendCommandSync, waitForFrame } from "./win-automation.ts";

const SECRET = "config-test-secret";
const SAVED_GOOGLE_KEY = "saved-google-key";
const UNSAVED_GOOGLE_KEY = "unsaved-google-key";
const MICROSOFT_ENDPOINT = "https://example.test";
const MICROSOFT_REGION = "westus";
const MICROSOFT_KEY = "unsaved-ms-key";
const KEYS = [SECRET, SAVED_GOOGLE_KEY, UNSAVED_GOOGLE_KEY, MICROSOFT_KEY];
const PROVIDERS = ["OpenAI-compatible", "Google Cloud Translation", "Google", "GoogleAPI", "Microsoft Translator"];
const TEST_DPI = 144;
const SIDE_BY_SIDE_DLLS = ["libsumatrapdf.dll", "clang_rt.asan_dynamic-x86_64.dll"].map((name) =>
  join(dirname(EXE), name),
);

function fail(msg: string, raw = ""): never {
  throw new Error(`translation-config: ${msg}${raw ? `\n${raw}` : ""}`);
}

function expect(raw: string, line: string): void {
  if (!new RegExp(`^${line}$`, "m").test(raw)) {
    fail(`missing ${line}`, raw);
  }
  for (const key of KEYS) {
    if (raw.includes(key)) {
      fail("debug-control exposed an API key", raw);
    }
  }
}

async function config(client: ControlClient, action: string, value = ""): Promise<string> {
  const res = await client.request(ControlCommand.TestTranslationConfig, [action, value]);
  if (res[0] !== 0) {
    fail(`${action} failed: ${String(res[1] ?? res[0])}`);
  }
  return String(res[1] ?? "");
}

function writeAppData(): string {
  const dir = tmpPath("translation-config-appdata");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  writeFileSync(
    join(dir, "SumatraPDF-settings.txt"),
    [
      "RestoreSession = false",
      "CheckForUpdates = false",
      "TranslationProvider = Google Cloud Translation",
      `TranslationGoogleKey = ${SAVED_GOOGLE_KEY}`,
      "TranslateFromLang = Auto",
      "TranslateToLang = English",
      "",
    ].join("\n"),
  );
  return dir;
}

function writeNoInternetApp(): string {
  const dir = tmpPath("translation-config-no-internet");
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });

  const exe = join(dir, "SumatraPDF.exe");
  copyFileSync(EXE, exe);
  for (const dll of SIDE_BY_SIDE_DLLS) {
    if (existsSync(dll)) {
      copyFileSync(dll, join(dir, basename(dll)));
    }
  }
  writeFileSync(join(dir, "sumatrapdfrestrict.ini"), "[Policies]\nDiskAccess = 1\nSavePreferences = 1\n");
  return exe;
}

async function testNoInternet(): Promise<void> {
  const exe = writeNoInternetApp();
  await withControlledSumatra(
    exe,
    async (client) => {
      const policies = await client.request(ControlCommand.TestGetPolicies);
      if (policies[0] !== 0) {
        fail(`policy dump failed: ${String(policies[1] ?? policies[0])}`);
      }
      expect(String(policies[1] ?? ""), "internet=0");

      await config(client, "open");
      let raw = await config(client, "dump");
      expect(raw, "open=1");
      expect(raw, "valid=1");
      expect(raw, "testEnabled=0");
      expect(raw, "saveEnabled=1");
      expect(raw, "working=0");
      expect(raw, "request=0");

      raw = await config(client, "test");
      expect(raw, "testEnabled=0");
      expect(raw, "working=0");
      expect(raw, "request=0");
    },
    ["-appdata", writeAppData()],
    { cwd: dirname(exe) },
  );
}

export async function testit(): Promise<void> {
  await withControlledSumatra(
    EXE,
    async (client, proc) => {
      const frame = await waitForFrame(proc.pid!);
      sendCommandSync(frame, cmdId("CmdConfigureTranslation"));
      let raw = await config(client, "dump");
      expect(raw, "open=1");
      expect(raw, "provider=Google Cloud Translation");
      expect(raw, "openAIVisible=0");
      expect(raw, "googleVisible=1");
      expect(raw, "microsoftVisible=0");
      expect(raw, "providerCount=5");
      expect(raw, "sourceCount=33");
      expect(raw, "targetCount=32");
      expect(raw, "focused=1");
      expect(raw, "valid=1");
      expect(raw, "keyMasked=1");
      expect(raw, "warning=1");
      expect(raw, "costWarning=1");
      expect(raw, "testEnabled=1");
      expect(raw, "saveEnabled=1");

      await config(client, "dpi", String(TEST_DPI));
      for (const provider of PROVIDERS) {
        await config(client, "provider", provider);
        raw = await config(client, "dump");
        expect(raw, `provider=${provider}`);
        expect(raw, `fontDpi=${TEST_DPI}`);
        expect(raw, "rowLabelFonts=9/9");
        expect(raw, "headingFonts=4/4");
      }

      await config(client, "provider", "OpenAI-compatible");
      await config(client, "base", "https://example.test/v1");
      await config(client, "model", "test-model");
      await config(client, "key", SECRET);
      raw = await config(client, "dump");
      expect(raw, "provider=OpenAI-compatible");
      expect(raw, "openAIVisible=1");
      expect(raw, "googleVisible=0");
      expect(raw, "openAIBaseUrlBytes=23");
      expect(raw, "openAIModelBytes=10");
      expect(raw, `openAIKeyBytes=${SECRET.length}`);
      expect(raw, "valid=1");

      sendCommandSync(frame, cmdId("CmdConfigureTranslation"));
      raw = await config(client, "dump");
      expect(raw, "open=1");
      expect(raw, "provider=OpenAI-compatible");
      expect(raw, "openAIBaseUrlBytes=23");
      expect(raw, "openAIModelBytes=10");
      expect(raw, `openAIKeyBytes=${SECRET.length}`);
      expect(raw, "focused=1");
      expect(raw, "persistedProvider=Google Cloud Translation");

      await config(client, "provider", "Google Cloud Translation");
      await config(client, "key", UNSAVED_GOOGLE_KEY);
      await config(client, "provider", "OpenAI-compatible");
      raw = await config(client, "dump");
      expect(raw, "openAIModelBytes=10");
      expect(raw, `openAIKeyBytes=${SECRET.length}`);

      await config(client, "key", "");
      raw = await config(client, "dump");
      expect(raw, "valid=0");
      expect(raw, "status=OpenAI-compatible requires an API key.");
      raw = await config(client, "test");
      expect(raw, "working=0");
      expect(raw, "request=0");
      raw = await config(client, "save");
      expect(raw, "open=1");
      expect(raw, "persistedProvider=Google Cloud Translation");
      await config(client, "key", SECRET);

      await config(client, "target", "Not a language");
      raw = await config(client, "dump");
      expect(raw, "valid=0");
      expect(raw, "status=Choose a target language.");
      await config(client, "target", "English");

      raw = await config(client, "test");
      expect(raw, "working=1");
      const request = Number(/^request=(\d+)$/m.exec(raw)?.[1] ?? 0);
      if (request < 1) fail("test did not allocate a request", raw);
      raw = await config(client, "stale", "late failure");
      expect(raw, "working=1");
      expect(raw, `request=${request}`);
      raw = await config(client, "result", "ok");
      expect(raw, "working=0");
      expect(raw, "status=Connection succeeded.");
      raw = await config(client, "test");
      expect(raw, "working=1");
      raw = await config(client, "result", "failure");
      expect(raw, "working=0");
      expect(raw, "status=Connection failed.");

      await config(client, "provider", "Microsoft Translator");
      await config(client, "endpoint", MICROSOFT_ENDPOINT);
      await config(client, "region", MICROSOFT_REGION);
      await config(client, "key", MICROSOFT_KEY);
      raw = await config(client, "dump");
      expect(raw, "microsoftVisible=1");
      expect(raw, "valid=1");
      await config(client, "provider", "OpenAI-compatible");

      await config(client, "source", "French");
      await config(client, "target", "German");
      raw = await config(client, "save");
      expect(raw, "open=0");
      expect(raw, "persistedProvider=OpenAI-compatible");
      expect(raw, "persistedSource=French");
      expect(raw, "persistedTarget=German");
      expect(raw, "persistedOpenAIBaseUrlBytes=23");
      expect(raw, "persistedOpenAIModelBytes=10");
      expect(raw, `persistedOpenAIKeyBytes=${SECRET.length}`);
      expect(raw, "persistedGoogleKeyBytes=18");
      expect(raw, `persistedMicrosoftEndpointBytes=${MICROSOFT_ENDPOINT.length}`);
      expect(raw, `persistedMicrosoftRegionBytes=${MICROSOFT_REGION.length}`);
      expect(raw, `persistedMicrosoftKeyBytes=${MICROSOFT_KEY.length}`);

      await config(client, "open");
      await config(client, "provider", "Microsoft Translator");
      await config(client, "cancel");
      raw = await config(client, "dump");
      expect(raw, "open=0");
      expect(raw, "persistedProvider=OpenAI-compatible");
    },
    ["-appdata", writeAppData()],
  );

  await testNoInternet();
}

if (import.meta.main) {
  await runStandalone(testit);
}
