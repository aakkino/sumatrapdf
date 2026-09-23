# Zotero-style Google translation research

Date: 2026-09-22

## Repository evidence

SumatraPDF already has the required architecture: `TranslationService` owns
provider request construction and parsing, `SelectionTranslate` owns the
worker-backed popup, and `tests/translation-api.ts` covers local HTTP fixtures.
The existing `Google Cloud Translation` provider is an official v2 JSON POST
adapter and must remain separate.

## Zotero PDF Translate implementation

The plugin's `src/modules/services/google.ts` exports `Google` and `GoogleAPI`.
Both use a shared adapter:

- `Google`: `https://translate.google.com`
- `GoogleAPI`: `https://translate.googleapis.com`
- path: `/translate_a/single`
- query includes `client=gtx`, `sl`, `tl`, many `dt` fields, `tk`, and URL-encoded
  `q`
- `tk` is computed locally from UTF-8 code points using the copied Google token
  algorithm
- response is an array; the adapter concatenates each non-empty
  `response[0][i][0]` segment

This is not the Google Cloud Translation v2 JSON API. The plugin calls the same
Google web translation protocol for both IDs and does not require a Cloud API
key in the shown adapter. The endpoint is unofficial/undocumented and can
change or rate-limit clients.

## Recommendation

Add two provider adapters behind the existing C++ service boundary, copy only
the protocol algorithm and response contract (not the JavaScript runtime), and
label the providers clearly as Zotero-compatible Google endpoints. Keep the
official Google Cloud provider as a separate option. Use local fixtures and do
not call Google in automated tests.
