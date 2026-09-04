# Native Translation Service

## Scenario: Provider-neutral HTTP translation

### 1. Scope / Trigger

- `TranslationService` is the native boundary for selection-translation and
  provider-configuration consumers. UI code passes domain input; it does not
  construct provider URLs, headers, JSON, or parse provider responses.
- Supported IDs are `OpenAICompatible`, `GoogleCloud`, and `Microsoft`.
  `None`, unknown names, and incomplete settings send no request.
- `TranslationProviderFromName()` trims and compares the persisted names
  case-insensitively: `OpenAI-compatible`, `Google Cloud Translation`, and
  `Microsoft Translator`.

### 2. Signatures

```cpp
void TranslationSettingsFromGlobal(TranslationSettings* settingsOut);
bool TranslationProviderIsConfigured(const TranslationSettings& settings);
TempStr TranslationConfigErrorTemp(const TranslationSettings& settings);
TempStr TranslationLanguageCodeTemp(TranslationProviderId provider, Str language);
TempStr NormalizeOpenAIBaseUrlTemp(Str url);
void TranslateText(const TranslationSettings& settings, const TranslationRequest& request,
                   TranslationResult* resultOut, const TranslationRequestOptions& options = {});
```

- `TranslationRequest` carries `sourceLanguage`, `targetLanguage`, and `text`.
- `TranslationResult` carries `ok`, `errorKind`, owned translated `text` or
  redacted `error`, plus `httpStatusCode` and `winError`.
- `TranslationRequestOptions` defaults to a 15-second timeout and a 32 KiB
  response limit. `TranslateText()` is synchronous and must be called only
  from an existing worker boundary. It copies its settings and request before
  starting I/O.
- `HttpPostUrl()` stays synchronous to its caller. `TranslationService` calls
  it only from that worker boundary, with `HttpPostOptions` carrying the
  request deadline and response limit.

### 3. Contracts

- `TranslationSettingsFromGlobal()` reads `TranslationProvider`,
  `TranslationOpenAIBaseUrl`, `TranslationOpenAIModel`,
  `TranslationOpenAIKey`, `TranslationGoogleKey`,
  `TranslationMicrosoftEndpoint`, `TranslationMicrosoftKey`, and optional
  `TranslationMicrosoftRegion`. Keys are persisted in plain text by design;
  none may enter logs or diagnostic summaries.
- Completeness ignores surrounding whitespace: OpenAI-compatible needs base
  URL, model, and key; Google needs key; Microsoft needs endpoint and key.
  Microsoft region is sent only when non-empty and is not required by the
  service.
- Input text must be non-whitespace and at most `32 * 1024` bytes. Empty or
  blank source means `Auto`; a non-auto source and every target must be a
  supported language label. Google receives its language code, Microsoft its
  code (for example `zh-Hans`), and OpenAI receives the original label in its
  fixed prompt.
- OpenAI-compatible URLs are trimmed, trailing slashes are removed, and one
  terminal `/chat/completions` suffix is removed before appending exactly one
  `/chat/completions`. The production Google URL is
  `https://translation.googleapis.com/language/translate/v2?key=...`; Microsoft
  trims trailing endpoint slashes, posts to
  `<endpoint>/translate?api-version=3.0&to=...`, and adds `from` only for an
  explicit source.
- Each adapter uses `HttpPostUrl()` with JSON content. OpenAI is non-streaming
  with `Authorization: Bearer`; Google sends `q`, `target`, optional `source`,
  and `format=text`; Microsoft sends `[{"Text":...}]`, subscription key, and
  optional region header. It parses only the documented translation field.
- `HttpPostUrl()` creates an isolated asynchronous WinHTTP session with
  automatic proxy selection. Status callbacks advance send, headers, reads,
  and request errors; the caller waits on its completion event until the
  supplied deadline. When the deadline expires, it marks `ERROR_TIMEOUT`,
  closes the outstanding request to cancel it, and waits for the handle-closing
  callback before releasing request state. No separate fixed response-header
  timeout is part of this contract.
- Because `Base.h` has already included WinINet, `Http_win.cpp` keeps a narrow
  WinHTTP declaration block. It declares only the asynchronous callback and
  option APIs actually used: `WinHttpSetStatusCallback`, `WinHttpSetOption`,
  `WinHttpSetTimeouts`, their callback type/statuses, and their context and
  receive-timeout options. It must not include `winhttp.h`.
- Settings and request data are copied before I/O and released after the call.
  Calls never retry or fall back to another provider. Do not log API keys,
  selected text, prompts, request bodies, raw responses, or translated text.

### 4. Validation & Error Matrix

| Condition                                                                 | Result                                                             |
| ------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| No provider or missing required value                                     | `IncompleteConfig`; return before I/O with a configuration message |
| Blank or oversized text; unknown language; unusable normalized OpenAI URL | `InvalidInput` with a bounded generic message                      |
| Non-positive HTTP timeout or response limit                               | `Transport`; preserve Win32 metadata, never raw failure data       |
| URL, WinHTTP, or callback request failure                                 | `Transport`; preserve Win32 metadata, never raw failure data       |
| Worker request exceeds its supplied event deadline                        | `Transport` with `ERROR_TIMEOUT`; cancel and drain the request     |
| Non-2xx HTTP response                                                     | `HttpStatus`; preserve status, never expose response body          |
| Response exceeds `maxResponseBytes` (32 KiB by default)                   | `ResponseTooLarge` from `ERROR_FILE_TOO_LARGE`                     |
| 2xx body is malformed or lacks non-blank provider translation             | `InvalidResponse`                                                  |
| 2xx body has the expected translation field                               | `ok=true`, owned `text`, `errorKind=None`                          |

### 5. Good / Base / Bad Cases

- Good: a worker sends a complete Google configuration with source `English`
  and target `French`; the body has `source=en`, `target=fr`, and
  `format=text`.
- Base: source `Auto` (or blank) omits Google `source` and Microsoft `from`;
  OpenAI uses the detect-language form of the fixed prompt. A local fixture
  that delays past the supplied deadline returns a redacted transport error
  after request cancellation.
- Bad: a UI thread calls `TranslateText()`, code assumes WinHTTP per-operation
  settings alone bound the whole request, a callback can outlive its request
  state, a caller retries through another provider, or an error surface
  includes a key, request text, raw body, or translation result.

### 6. Tests Required

- `tests/translation-api.ts` must use a local `Bun.serve` fixture only. It
  asserts each provider's POST URL, authentication headers, JSON fields,
  success parsing, OpenAI URL normalization, and auto-source omission.
- The fixture must cover malformed 2xx JSON, non-2xx response, a response over
  32 KiB, a delayed response beyond the supplied deadline, and incomplete
  OpenAI configuration. Its debug-control summary is either status plus result
  byte count, or status plus error category; it must never contain the test
  key, source text, request body, or result.
- When `HttpPostUrl()` changes, inspect the WinHTTP boundary as well as running
  the focused test: it must retain automatic proxy, the asynchronous callback
  flow, completion-event deadline, request-close drain, and only the narrow
  declarations required by those calls.
- Required source-change validation commands are `bun cmd/format.ts`,
  `bun cmd/build.ts -debug`, `bun tests/translation-api.ts --no-build`, and
  `git diff --check`. When `src/base/Http*` changes, also run
  `bun cmd/run-unit-tests.ts -dbg`. These are required checks, not recorded
  passing evidence in this specification. A current VS-2026 environment
  blockage leaves the affected command required and unverified; it is neither
  product-code evidence nor a passing result.

### 7. Wrong vs Correct

#### Wrong

```cpp
// UI thread blocks, and an unfinished callback could outlive request state.
TranslateText(settings, request, &result);
```

#### Correct

```cpp
// A worker owns the blocking call; it receives one result after request cleanup.
RunAsync(MkFunc0(TranslateTextOnWorker, &data), StrL("Translation"));
```

Keep configuration completeness, provider construction, response parsing, and
redaction inside `TranslationService`.
