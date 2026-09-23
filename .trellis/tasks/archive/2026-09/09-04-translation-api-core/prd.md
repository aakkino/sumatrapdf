# Build translation API core

## Goal

Provide one provider-neutral native service for selection translation through
OpenAI-compatible, Google Cloud Translation, and Microsoft Translator HTTP APIs.

## Requirements

- R1: Add generated settings for the remembered provider and each provider's
  required configuration. API keys are intentionally stored in plain text.
- R2: Define provider metadata, completeness validation, request input, and a
  normalized success/error result outside the UI layer.
- R3: Implement non-streaming OpenAI-compatible `/chat/completions` with a fixed
  application translation prompt and configured base URL, model, and API key.
- R4: Implement Google Cloud Translation Basic v2 with API-key authentication.
- R5: Implement Microsoft Translator v3 with configurable endpoint, key, and
  optional region.
- R6: Use `base/Http` on worker threads with explicit timeout and response-size
  bounds. Never log keys, selected text, prompt bodies, raw responses, or results.
- R7: Preserve the separate AI Chat CLI implementation without calling it.
- R8: Support deterministic local-server tests without live credentials.

## Acceptance Criteria

- AC1: Each adapter emits the documented URL, headers, and JSON body and parses a
  representative success response.
- AC2: Missing fields, malformed JSON, transport errors, non-2xx responses,
  oversized responses, and timeouts return bounded redacted errors.
- AC3: OpenAI base URLs are normalized without duplicate slashes or path suffixes.
- AC4: Auto source language omits provider source parameters; explicit source and
  destination names map to provider language codes.
- AC5: Generated settings round-trip all non-secret and plain-text key fields,
  while diagnostics and test probes expose no secret or translation payload.
- AC6: Focused tests use a local HTTP server and pass without network accounts.

## Out of Scope

- Popup, configuration-window, and command UI.
- Streaming, retries after provider failure, OAuth, service accounts, Entra ID,
  custom prompts, conversation state, and providers outside the three named APIs.
- Changes to AI Chat CLI providers.
