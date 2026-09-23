# Add Zotero-style Google engines to selection translation popup

## Goal

Extend the already implemented SumatraPDF selection-translation popup so its
provider menu can use the same two Google translation engines exposed by the
`windingwind/zotero-pdf-translate` plugin: `Google` and `GoogleAPI`.

## Confirmed Facts

- SumatraPDF already has a provider-neutral asynchronous translation service
  and selection-anchored popup (`src/TranslationService.cpp`,
  `src/SelectionTranslate.cpp`).
- The current built-in Google provider is `Google Cloud Translation`. It sends
  JSON POST requests to `https://translation.googleapis.com/language/translate/v2`
  with an API key and parses `data.translations[0].translatedText`.
- The Zotero PDF Translate plugin defines two services in one adapter:
  `Google` uses `https://translate.google.com`; `GoogleAPI` uses
  `https://translate.googleapis.com`.
- Both Zotero services call the GET endpoint `/translate_a/single?client=gtx...`
  with a calculated `tk` token and concatenate segmented response text. The
  plugin source does not use the Google Cloud Translation v2 JSON contract for
  these two services.
- SumatraPDF's HTTP service, worker execution, request-id validation, popup
  lifecycle, redacted diagnostics and local-fixture API tests already provide
  the correct integration boundary.

## Requirements

- Add provider identities for Zotero-style `Google` and `GoogleAPI` without
  breaking the existing official `Google Cloud Translation` provider.
- Implement request construction and response parsing inside
  `TranslationService`, never in popup/UI code.
- Preserve source-language auto-detection, target-language mapping, bounded
  input/response sizes, timeouts, permission checks and stale-completion
  rejection.
- Expose the two new providers in the existing configuration/provider switcher
  with clear credential requirements and canonical persisted names.
- Add deterministic local HTTP fixture coverage for URL/query construction,
  `tk` calculation, language mapping, segmented response parsing, non-200 and
  malformed responses, long input and redaction behavior.
- Document that these endpoints are Google web translation endpoints rather than
  the official Cloud Translation v2 API, and that availability/rate limits may
  change.

## Out of Scope

- Google web search or Google Search APIs.
- Embedding the Zotero JavaScript runtime or Zotero translators.
- Copying unrelated Zotero plugin UI, dictionary services, caching, audio, or
  sentence-context logic.
- Replacing or removing the existing Google Cloud Translation provider.

## Acceptance Criteria

- [ ] The popup provider menu can select `Google`, `GoogleAPI`, and the existing
  `Google Cloud Translation` independently.
- [ ] Selecting either Zotero-style provider sends the expected GET request and
  renders concatenated translated segments in the existing popup.
- [ ] Auto source and supported target languages produce the correct Google
  language parameters; unsupported mappings fail before network I/O.
- [ ] API/network errors, malformed JSON, oversized responses, timeouts and
  stale popup completions produce the existing bounded error behavior.
- [ ] Existing providers and popup lifecycle tests remain passing.
- [ ] Documentation and settings names distinguish unofficial Google endpoint
  providers from Google Cloud Translation.

## Key Decision

Add both Zotero-compatible providers. `GoogleAPI` follows the plugin exactly:
`translate.googleapis.com/translate_a/single` with the `tk` query token and no
Google Cloud API key. Keep the existing official `Google Cloud Translation`
provider as a separate option.

## Delivery Workflow

This task uses the `stax-stacked` Trellis workflow. Implementation is planned
as a linear two-layer stack: provider/service changes first, then UI and docs.
Each layer will use an exclusive Stax branch/worktree binding and exact-head
admission evidence. Draft PR publication is coordinator-owned; ready-for-review,
merge and cleanup require an explicit human decision.
