# Native Translation Service

## Scenario: Provider-neutral HTTP translation

### 1. Scope / Trigger

- `TranslationService` is the native boundary for selection-translation and
  provider-configuration consumers. UI code passes domain input; it does not
  construct provider URLs, headers, JSON, language codes, or parse responses.
- Service-order IDs are `OpenAICompatible`, `GoogleCloud`, `Google`,
  `GoogleAPI`, and `Microsoft`, with canonical names `OpenAI-compatible`,
  `Google Cloud Translation`, `Google`, `GoogleAPI`, and `Microsoft Translator`.
  `None`, unknown or legacy persisted names, and incomplete settings send no
  request. `Google` and `GoogleAPI` are explicit unofficial web-provider paths;
  selection translation does not use DeepL browser paths or AI CLI providers.

### 2. Signatures

```cpp
const TranslationProviderInfo* TranslationProviders();
TranslationProviderId TranslationProviderFromName(Str name);
Str TranslationProviderName(TranslationProviderId provider);
void TranslationSettingsFromGlobal(TranslationSettings* settingsOut);
bool TranslationProviderIsConfigured(const TranslationSettings& settings);
TempStr TranslationConfigErrorTemp(const TranslationSettings& settings);
Str TranslationLanguageLabel(int index);
bool TranslationSourceIsAuto(Str language);
TempStr TranslationLanguageCodeTemp(TranslationProviderId provider, Str language);
TempStr NormalizeOpenAIBaseUrlTemp(Str url);
void TranslateText(const TranslationSettings& settings, const TranslationRequest& request,
                   TranslationResult* resultOut, const TranslationRequestOptions& options = {});
void TranslationSetTestEndpoint(TranslationProviderId provider, Str endpoint);
```

- `TranslationRequest` carries `sourceLanguage`, `targetLanguage`, and `text`.
  `TranslationResult` carries `ok`, `errorKind`, owned translated `text` or
  redacted `error`, `httpStatusCode`, and `winError`.
- `TranslationProviders()` and `TranslationLanguageLabel()` are the shared UI
  catalog. Labels use zero-based lookup and return empty after the final label;
  provider code mappings remain service-private.
- `TranslationRequestOptions` defaults to a 15-second deadline and 32 KiB
  response limit. `TranslationSetTestEndpoint()` overrides a Google-family URL
  for the debug-control local fixture; it is not a user configuration path.

### 3. Contracts

- `TranslationProviderFromName()` trims and compares canonical saved names
  case-insensitively. `TranslationSettingsFromGlobal()` reads the selected
  provider and all provider fields. Keys are deliberately plain-text settings,
  but must not enter logs, diagnostics, errors, or probes.
- Completeness ignores surrounding whitespace: OpenAI-compatible needs base
  URL, model, and key; Google Cloud needs a key; Google and GoogleAPI need no
  key; Microsoft needs endpoint and key. Microsoft region is optional and is
  emitted only when non-empty.
- Text must be non-whitespace and at most 32 KiB. Blank/`Auto` source omits
  Google `source` and Microsoft `from`; target must resolve through the shared
  catalog. OpenAI receives canonical labels in its fixed prompt; provider code
  values stay internal.
- OpenAI-compatible normalizes its base URL, removes one terminal
  `/chat/completions`, then appends exactly one. Google Cloud posts to its v2
  URL with `q`, `target`, optional `source`, and `format=text`, authenticated by
  `?key=`; it parses only `data.translations[0].translatedText`.
- Unofficial `Google` defaults to `https://translate.google.com` and
  `GoogleAPI` to `https://translate.googleapis.com`. Both trim endpoint
  slashes and GET `/translate_a/single` with `client=gtx`, `sl`, `tl`, `hl=en`,
  the fixed `dt` fields, `source=bh`, `ssel=0`, `tsel=0`, `kc=1`, `tk`, and
  URL-encoded `q`; Auto uses `sl=auto`. `tk` is the current UTF-8 token
  transform and must not be cached or exposed. Their response is a segmented
  array; concatenate each segment's first string in order and reject malformed
  or blank output. URL-encoded text is bounded by `kMaxUrlEncodedLen` (8192).
- Microsoft trims endpoint slashes and posts to `/translate?api-version=3.0&to=...`,
  optional `from`, subscription key, optional region, and `[ {"Text": ...} ]`
  JSON. Adapters parse only their documented translation field.
- `TranslateText()` is synchronous only to its caller and must run under an
  existing worker boundary. It copies settings/request before I/O; it never
  retries or falls back. `HttpGetUrl()` and `HttpPostUrl()` have the same
  worker-only boundary, an explicit deadline and response limit, automatic
  proxy, asynchronous callback flow, completion-event waiting, timeout
  cancellation, and request-close drain. Query strings are not logged because
  web-provider queries carry document text and a token.
- `Http_win.cpp` keeps narrow WinHTTP declarations because `Base.h` already
  includes WinINet. Do not include `winhttp.h` there.
- Production debug-control summaries contain outcome metadata only: success is
  `ok`, HTTP status, and result byte length; failure is `ok`, HTTP status, and
  error category. They never contain keys, selected text, prompts, request
  bodies, raw responses, redacted error text, or translated text.

### 4. Validation & Error Matrix

| Condition | Result |
| --- | --- |
| No provider, legacy/unknown provider, or missing required value | `IncompleteConfig`; return before I/O with a configuration message. |
| Blank/oversized text, unsupported language, unusable normalized URL, or web URL text beyond 8192 encoded bytes | `InvalidInput` with a bounded generic message. |
| Invalid timeout/response limit, URL, WinHTTP, or callback failure | `Transport`; preserve metadata, never raw failure data. |
| Worker exceeds supplied deadline | `Transport` with `ERROR_TIMEOUT`; cancel and drain the request. |
| Non-2xx HTTP response | `HttpStatus`; preserve status, never expose body. |
| Response exceeds limit | `ResponseTooLarge` from `ERROR_FILE_TOO_LARGE`. |
| 2xx body is malformed or has no non-blank translation | `InvalidResponse`. |
| Expected non-blank field parses | `ok=true`, owned `text`, `errorKind=None`. |

### 5. Good / Base / Bad Cases

- Good: a worker sends keyless Google English-to-French; the local fixture
  observes a GET with `sl`, `tl`, `tk`, and encoded `q`, then segment parsing
  returns only success metadata plus result length.
- Base: Auto source omits Google `source` and Microsoft `from`; a delayed local
  fixture returns a redacted transport error after deadline cancellation.
- Bad: a UI thread calls `TranslateText()`, code creates raw provider requests
  outside the service, a request falls back to another provider, or a log/probe
  emits a key, selected text, request body, provider body, or translation.

### 6. Tests Required

- `tests/translation-api.ts` uses `Bun.serve` local fixtures only. Assert all
  five canonical providers and configuration rules; each POST URL,
  authentication, JSON, success parsing, OpenAI URL normalization,
  catalog-derived language codes, and Auto source omission; and both Google
  web GET paths, query fields, deterministic `tk`, encoded `q`, segment
  concatenation, and no-key configuration.
- Assert malformed 2xx JSON/segment arrays, non-2xx, oversized response,
  deadline timeout, invalid language/URL bounds, and incomplete configuration.
  For every summary, assert keys, source text, request body, token, raw
  response, and result text are absent; successful summaries expose byte count
  only and failed summaries expose error category only.
- When `HttpGetUrl()` or `HttpPostUrl()` changes, inspect its WinHTTP boundary for automatic
  proxy, asynchronous callbacks, completion-event deadline, close-drain, and
  narrow declarations. Required source-change checks are `bun cmd/format.ts`,
  `bun cmd/build.ts -debug`, `bun tests/translation-api.ts --no-build`, and
  `git diff --check`; when `src/base/Http*` changes also run
  `bun cmd/run-unit-tests.ts -dbg`.

### 7. Wrong vs Correct

#### Wrong

```cpp
HttpPostUrl(url, headers, body, &response);
logf("translation: %s", response);
```

This duplicates provider transport at the caller and exposes text-bearing data.

#### Correct

```cpp
RunAsync(MkFunc0(TranslationWorker, task), StrL("Translation"));
// The worker calls TranslateText(); UI receives normalized metadata/result only.
```

Keep provider construction, parsing, timeout cleanup, and redaction inside
`TranslationService`.
