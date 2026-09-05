# Technical Design

## Architecture

Keep UI and transport separated by one translation service boundary:

```text
Popup / Configuration Window
  -> TranslationService provider-neutral request
  -> OpenAI / Google / Microsoft adapter
  -> base/Http WinHTTP POST
  -> normalized result or redacted error
  -> UI-thread completion guarded by request identity
```

- The API-core child owns settings and provider adapters. It must not know popup
  HWNDs, tabs, selections, or visual state.
- The configuration child may add one read-only language-catalog accessor to
  the checked service contract so both UIs use the same accepted labels. It may
  not change transport, provider request construction, parsing, or redaction.
- The configuration child first freezes the language catalog and configuration
  entry point, then consumes provider metadata and validation through the
  service boundary. It owns no raw HTTP or provider JSON parsing.
- The popup child consumes configured-provider status and asynchronous results.
  It owns selection lifecycle and visual state, not credentials or protocols.
- Existing AI Chat CLI providers remain isolated in `AIChat*` and are not called
  or modified by selection translation.

## Lifecycle and State

- Saving configuration validates local field completeness, persists plain-text
  values, and updates provider availability. Cancel changes nothing.
- Test Connection explicitly sends a fixed non-sensitive string on a worker,
  warns of possible cost, and posts a redacted result to the live dialog.
- Quick translation snapshots the selected text, provider, languages, tab,
  selection identity, and a globally unique request ID. Switching provider or
  Retry creates a new ID. Late results are dropped.
- Missing or legacy provider preferences send nothing and show an actionable
  configuration error. No provider fallback is allowed.
- HTTP requests use explicit time and response-size bounds. UI close invalidates
  completion; process-wide network cancellation is deferred.

## Compatibility and Ownership

- The configuration child adds `CmdConfigureTranslation` without selection
  gating. The parent integration unit removes translation-specific Google,
  DeepL, and AI CLI commands and keeps `CmdTranslateSelection` plus
  `CmdTranslateSelectionQuick` as quick-popup aliases. Preserve all AI Chat
  commands, settings, sidebars, and provider implementations.
- Replace the remembered translation engine with an HTTP provider preference.
  Old Google/DeepL/CLI values do not migrate to a provider and cannot send text.
- Generate settings and commands through their TypeScript generators. Update
  command, settings, and version-history documentation through established
  generated/documented paths.
- API core is complete at `f0b651e16`. Run the configuration child's shared
  contract unit next. Its remaining UI unit and the popup functional unit then
  use disjoint ownership and may run concurrently. After both pass, the parent
  command integration and popup visual unit may run concurrently.
- Rollback can stop after any child: API core is dormant until UI integration;
  configuration can exist before popup migration; popup migration is the final
  user-visible switch.
