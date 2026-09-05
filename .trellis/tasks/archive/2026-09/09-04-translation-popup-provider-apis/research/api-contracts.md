# Research: Translation API contracts

- Date: 2026-09-04
- Scope: OpenAI-compatible Chat Completions, Google Cloud Translation Basic,
  and Microsoft Translator v3.

## Provider contracts

- OpenAI-compatible: append `/chat/completions` to the configured base URL;
  send a non-streaming chat request with the configured model and translation
  instructions. Parse assistant message content. Official reference:
  https://developers.openai.com/api/reference/cli/resources/chat/subresources/completions
- Google Cloud Translation Basic: POST
  `https://translation.googleapis.com/language/translate/v2`; send `q`, `target`,
  optional `source`, and `format=text`; authenticate with an API key; parse
  `data.translations[0].translatedText`. Official reference:
  https://docs.cloud.google.com/translate/docs/reference/rest/v2/translate
- Microsoft Translator: POST `{Endpoint}/translate?api-version=3.0&to=...`,
  optionally adding `from`; send a JSON array containing `Text`; authenticate
  with `Ocp-Apim-Subscription-Key`. Add
  `Ocp-Apim-Subscription-Region` for regional or multi-service resources; parse
  `[0].translations[0].text`. Official references:
  https://learn.microsoft.com/en-us/rest/api/translator/translator/translate?view=rest-translator-v3.0
  and
  https://learn.microsoft.com/en-us/azure/ai-services/translator/text-translation/reference/authentication

## Local implementation evidence

- `src/base/Http.h:24` and `src/base/Http_win.cpp:364` already provide a
  blocking WinHTTP POST with explicit content type, headers, status, Win32
  error, response body, proxy support, and a 1 MiB response guard. Call it only
  from a worker.
- `src/base/JsonParser.h` provides the project JSON parser. Provider adapters
  should own request construction and response extraction; popup code should
  consume one normalized result contract.
- No provider SDK is needed. Adding one would conflict with the project's small
  native dependency surface without supplying required UI/lifecycle behavior.

## Planning consequences

- Provider completeness differs: OpenAI-compatible needs base URL, model, and
  key; Google needs key; Microsoft needs endpoint and key, with region required
  for regional or multi-service resources.
- Tests should use a local HTTP server and fixed JSON/error responses. They must
  not call live services or record keys, selected text, prompts, or responses in
  ordinary logs.
- Provider error bodies may echo request details. Parse only a bounded,
  redacted user-facing message and retain status/Win32 metadata for diagnostics.
