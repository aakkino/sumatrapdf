# Google translation providers

## Goal

Add Zotero-compatible `Google` and `GoogleAPI` adapters to `TranslationService`.

## Requirements

- Keep `Google Cloud Translation` unchanged and provider-neutral popup APIs intact.
- Build bounded GET requests with language mapping and the Zotero `tk` token.
- Parse segmented responses, reject malformed/non-200/oversized responses, and redact diagnostics.
- Add deterministic local-fixture coverage for request, token, parsing, and failure behavior.

## Acceptance Criteria

- [ ] Both providers produce the expected local-fixture request and concatenated translation.
- [ ] Auto source and supported target languages map correctly; unsupported mappings fail before I/O.
- [ ] Existing providers and stale-request behavior remain unchanged.
