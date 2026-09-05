// Native translation adapters use local HTTP fixtures. The debug-control
// summary deliberately contains no key, source text, request body, or result.

import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { ControlCommand, withControlledSumatra } from "./control.ts";
import { EXE, runStandalone, tmpPath } from "./util.ts";

type RequestRecord = {
  body: string;
  headers: Headers;
  method: string;
  path: string;
  search: string;
};

const SECRET = "translation-test-secret";
const TEXT = "document text must stay private";
const TRANSLATION = "texte traduit";
const TIMEOUT_MS = 1_000;
const TIMEOUT_DELAY_MS = TIMEOUT_MS * 2;

function fail(msg: string): never {
  throw new Error(`translation-api: ${msg}`);
}

function writeAppData(name: string, settings: string[]): string {
  const dir = tmpPath(name);
  rmSync(dir, { recursive: true, force: true });
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "SumatraPDF-settings.txt"), `${settings.join("\n")}\n`);
  return dir;
}

function assertSafe(summary: string): void {
  for (const value of [SECRET, TEXT, TRANSLATION]) {
    if (summary.includes(value)) {
      fail(`debug-control exposed private data: ${value}`);
    }
  }
}

function expectMatch(value: string, re: RegExp, what: string): void {
  if (!re.test(value)) {
    fail(`${what}: ${value}`);
  }
}

async function runTranslation(
  appData: string,
  endpoint: string,
  timeoutMs = 1000,
  sourceLanguage = "English",
  targetLanguage = "French",
): Promise<string> {
  return await withControlledSumatra(
    EXE,
    async (client) => {
      const res = await client.request(ControlCommand.TestTranslationApi, [
        endpoint,
        sourceLanguage,
        targetLanguage,
        TEXT,
        timeoutMs,
      ]);
      if (res[0] !== 0) {
        fail(`control request failed: ${String(res[1] ?? res[0])}`);
      }
      const summary = String(res[1] ?? "");
      assertSafe(summary);
      return summary;
    },
    ["-appdata", appData],
  );
}

function settingsBase(): string[] {
  return ["RestoreSession = false", "CheckForUpdates = false", "TranslateFromLang = Auto", "TranslateToLang = French"];
}

export async function testit(): Promise<void> {
  const requests: RequestRecord[] = [];
  const server = Bun.serve({
    hostname: "127.0.0.1",
    port: 0,
    async fetch(request) {
      const url = new URL(request.url);
      requests.push({
        body: await request.text(),
        headers: request.headers,
        method: request.method,
        path: url.pathname,
        search: url.search,
      });
      if (url.pathname.includes("malformed")) {
        return new Response("not json", { status: 200 });
      }
      if (url.pathname.includes("error")) {
        return new Response(`provider error ${SECRET} ${TEXT}`, { status: 401 });
      }
      if (url.pathname.includes("oversize")) {
        return new Response("x".repeat(64 * 1024), { status: 200 });
      }
      if (url.pathname.includes("timeout")) {
        await Bun.sleep(TIMEOUT_DELAY_MS);
      }
      if (url.pathname.includes("google")) {
        return Response.json({ data: { translations: [{ translatedText: TRANSLATION }] } });
      }
      if (url.pathname.includes("microsoft")) {
        return Response.json([{ translations: [{ text: TRANSLATION }] }]);
      }
      return Response.json({ choices: [{ message: { content: TRANSLATION } }] });
    },
  });
  const baseUrl = `http://127.0.0.1:${server.port}`;

  try {
    const openAI = writeAppData("translation-api-openai", [
      ...settingsBase(),
      "TranslationProvider = OpenAI-compatible",
      `TranslationOpenAIBaseUrl = ${baseUrl}/openai/v1/chat/completions///`,
      "TranslationOpenAIModel = test-model",
      `TranslationOpenAIKey = ${SECRET}`,
    ]);
    const openAISummary = await runTranslation(openAI, "", 1000);
    expectMatch(openAISummary, /^ok=1 http=200 resultBytes=13$/, "OpenAI result");
    const openAIRequest = requests.pop();
    if (!openAIRequest) fail("OpenAI request missing");
    expectMatch(openAIRequest.method, /^POST$/, "OpenAI method");
    expectMatch(openAIRequest.path, /^\/openai\/v1\/chat\/completions$/, "OpenAI URL normalization");
    expectMatch(
      openAIRequest.headers.get("authorization") ?? "",
      new RegExp(`^Bearer ${SECRET}$`),
      "OpenAI authorization",
    );
    expectMatch(openAIRequest.body, /"model":"test-model"/, "OpenAI model");
    expectMatch(openAIRequest.body, /"content":"document text must stay private"/, "OpenAI body");

    const google = writeAppData("translation-api-google", [
      ...settingsBase(),
      "TranslationProvider = Google Cloud Translation",
      `TranslationGoogleKey = ${SECRET}`,
    ]);
    const googleSummary = await runTranslation(google, `${baseUrl}/google/v2`);
    expectMatch(googleSummary, /^ok=1 http=200 resultBytes=13$/, "Google result");
    const googleRequest = requests.pop();
    if (!googleRequest) fail("Google request missing");
    expectMatch(googleRequest.path, /^\/google\/v2$/, "Google URL");
    expectMatch(googleRequest.search, new RegExp(`^\\?key=${SECRET}$`), "Google API key");
    expectMatch(googleRequest.body, /"source":"en"/, "Google source code");
    expectMatch(googleRequest.body, /"target":"fr"/, "Google target code");
    expectMatch(googleRequest.body, /"format":"text"/, "Google text format");

    const microsoft = writeAppData("translation-api-microsoft", [
      ...settingsBase(),
      "TranslationProvider = Microsoft Translator",
      `TranslationMicrosoftEndpoint = ${baseUrl}/microsoft/`,
      `TranslationMicrosoftKey = ${SECRET}`,
      "TranslationMicrosoftRegion = test-region",
    ]);
    const microsoftSummary = await runTranslation(microsoft, "");
    expectMatch(microsoftSummary, /^ok=1 http=200 resultBytes=13$/, "Microsoft result");
    const microsoftRequest = requests.pop();
    if (!microsoftRequest) fail("Microsoft request missing");
    expectMatch(microsoftRequest.path, /^\/microsoft\/translate$/, "Microsoft URL");
    expectMatch(microsoftRequest.search, /^\?api-version=3\.0&to=fr&from=en$/, "Microsoft query");
    expectMatch(
      microsoftRequest.headers.get("ocp-apim-subscription-key") ?? "",
      new RegExp(`^${SECRET}$`),
      "Microsoft API key",
    );
    expectMatch(
      microsoftRequest.headers.get("ocp-apim-subscription-region") ?? "",
      /^test-region$/,
      "Microsoft region",
    );
    expectMatch(microsoftRequest.body, /^\[\{"Text":"document text must stay private"\}\]$/, "Microsoft body");

    const autoGoogle = writeAppData("translation-api-google-auto", [
      ...settingsBase(),
      "TranslationProvider = Google Cloud Translation",
      "TranslateFromLang = Auto",
      `TranslationGoogleKey = ${SECRET}`,
    ]);
    const autoSummary = await runTranslation(autoGoogle, `${baseUrl}/google/v2`, 1000, "Auto");
    expectMatch(autoSummary, /^ok=1 http=200 resultBytes=13$/, "Google Auto result");
    const autoRequest = requests.pop();
    if (!autoRequest) fail("Google Auto request missing");
    if (autoRequest.body.includes('"source"')) fail(`Google Auto sent source: ${autoRequest.body}`);

    const canonicalLanguage = writeAppData("translation-api-canonical-language", [
      ...settingsBase(),
      "TranslationProvider = Google Cloud Translation",
      `TranslationGoogleKey = ${SECRET}`,
    ]);
    const canonicalSummary = await runTranslation(
      canonicalLanguage,
      `${baseUrl}/google/v2`,
      TIMEOUT_MS,
      "Auto",
      "Chinese (Simplified)",
    );
    expectMatch(canonicalSummary, /^ok=1 http=200 resultBytes=13$/, "canonical language result");
    const canonicalRequest = requests.pop();
    if (!canonicalRequest) fail("canonical language request missing");
    expectMatch(canonicalRequest.body, /"target":"zh-CN"/, "canonical language code");

    const malformed = writeAppData("translation-api-malformed", [
      ...settingsBase(),
      "TranslationProvider = OpenAI-compatible",
      `TranslationOpenAIBaseUrl = ${baseUrl}/malformed/v1`,
      "TranslationOpenAIModel = test-model",
      `TranslationOpenAIKey = ${SECRET}`,
    ]);
    const malformedSummary = await runTranslation(malformed, "");
    expectMatch(malformedSummary, /^ok=0 http=200 error=invalid-response$/, "malformed response");

    const rejected = writeAppData("translation-api-rejected", [
      ...settingsBase(),
      "TranslationProvider = OpenAI-compatible",
      `TranslationOpenAIBaseUrl = ${baseUrl}/error/v1`,
      "TranslationOpenAIModel = test-model",
      `TranslationOpenAIKey = ${SECRET}`,
    ]);
    const rejectedSummary = await runTranslation(rejected, "");
    expectMatch(rejectedSummary, /^ok=0 http=401 error=http-status$/, "HTTP rejection");

    const oversized = writeAppData("translation-api-oversize", [
      ...settingsBase(),
      "TranslationProvider = OpenAI-compatible",
      `TranslationOpenAIBaseUrl = ${baseUrl}/oversize/v1`,
      "TranslationOpenAIModel = test-model",
      `TranslationOpenAIKey = ${SECRET}`,
    ]);
    const oversizedSummary = await runTranslation(oversized, "", 1000);
    expectMatch(oversizedSummary, /^ok=0 http=200 error=response-too-large$/, "oversized response");

    const timedOut = writeAppData("translation-api-timeout", [
      ...settingsBase(),
      "TranslationProvider = OpenAI-compatible",
      `TranslationOpenAIBaseUrl = ${baseUrl}/timeout/v1`,
      "TranslationOpenAIModel = test-model",
      `TranslationOpenAIKey = ${SECRET}`,
    ]);
    const timeoutSummary = await runTranslation(timedOut, "", TIMEOUT_MS);
    const timeoutRequest = requests.pop();
    if (!timeoutRequest) fail("timeout request missing");
    expectMatch(timeoutRequest.path, /^\/timeout\/v1\/chat\/completions$/, "timeout URL");
    expectMatch(timeoutSummary, /^ok=0 http=-1 error=transport$/, "timeout");

    const incomplete = writeAppData("translation-api-incomplete", [
      ...settingsBase(),
      "TranslationProvider = OpenAI-compatible",
      `TranslationOpenAIBaseUrl = ${baseUrl}/openai/v1`,
      "TranslationOpenAIModel = test-model",
    ]);
    const countBefore = requests.length;
    const incompleteSummary = await runTranslation(incomplete, "");
    expectMatch(incompleteSummary, /^ok=0 http=-1 error=incomplete-config$/, "incomplete config");
    if (requests.length !== countBefore) fail("incomplete config sent a request");
  } finally {
    server.stop(true);
  }
}

if (import.meta.main) {
  await runStandalone(testit);
}
