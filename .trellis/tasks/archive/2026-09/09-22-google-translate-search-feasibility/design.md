# Technical Design

## Architecture

Keep the popup provider-neutral. Add two adapters to `TranslationService` and
reuse its worker, HTTP, JSON and normalized-result boundaries. Keep
`GoogleCloud` separate from the Zotero-compatible adapters.

## Lifecycle and State

The popup snapshots selection, language and provider, starts one worker, and
accepts completion only for the live HWND/request ID. Provider switching and
retry create a new request ID. Errors remain bounded and redacted.

## Compatibility and Ownership

`TranslationService` owns provider IDs, token generation, query construction,
language mapping and response parsing. `SelectionTranslate` owns popup state
only. `TranslationConfig` owns provider selection and persistence only. Existing
Google Cloud, OpenAI-compatible and Microsoft behavior remains unchanged.

The new endpoints are undocumented Google web translation endpoints. Isolate
them behind provider IDs so they can be disabled or replaced independently.

## Stax Topology

Use one linear stack with two reviewable layers: `google-providers` above
`master`, then `ui-docs` above `google-providers`. The coordinator creates and
owns the branches/worktrees and records exact parent object IDs. Each layer has
exclusive owned paths and receives a fresh read-only admission before both
implementation and paired-check dispatch. Draft publication happens only after
the layer's exact-head evidence passes; ready-for-review, merge and cleanup are
human-authorized operations.
