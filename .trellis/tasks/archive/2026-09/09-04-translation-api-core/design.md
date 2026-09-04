# Technical Design

## Architecture

Add a `TranslationService` boundary between UI and `base/Http`. It owns provider
IDs, configuration views, completeness checks, language mapping, provider
request builders, response parsers, and normalized redacted errors. The UI
passes domain input and never constructs headers or reads provider JSON.

Use the existing project JSON parser and WinHTTP implementation; add no provider
SDK. Extend the HTTP request options only as needed for explicit time and size
limits, keeping existing callers source-compatible.

## Lifecycle and State

The public service call is blocking and must be invoked from an existing worker
boundary. It copies configuration and input before I/O, returns one owned result,
and retains no credentials. Connection testing uses the same adapters with a
fixed short string. No automatic cross-provider fallback occurs.

## Compatibility and Ownership

Generate settings from `cmd/gen-settings.ts`. Replace the obsolete translation
engine preference with an HTTP provider preference; an old value is invalid and
sends nothing. Keep `AIChatCommon` and provider files untouched. Update
`base/Http` only if required by timeout/size contracts and preserve MSVC/MinGW.
