# Extend translation popup providers

## Goal

Improve the selection-translation popup's visual presentation and let users
translate selected text through a configured OpenAI-compatible API, Google Cloud
Translation, or Microsoft Translator without leaving the document.

## Background

- The popup is implemented in `src/SelectionTranslate.cpp` and already supports
  loading, result, error, Copy, Close, Configure, engine switching, focus-safe
  placement, and stale-request rejection.
- Google and DeepL currently open browser URLs. They do not call translation
  APIs or return results inside the popup, and both browser engines will be
  removed by this task.
- Grok Build, Claude Code, OpenAI Codex, and Antigravity currently run through
  installed local CLIs. Quick translation currently accepts only an installed
  remembered AI CLI, but the new translation path will bypass AI CLIs and call
  the configured OpenAI-compatible base directly.
- Source language, target language, and engine are persisted in generated
  settings. No translation API credential model exists.
- Generic selection handlers already support configurable POST headers, but
  store them in plain text and explicitly warn that API keys are exposed. The
  repository has no OS-backed credential storage wrapper.
- Selected text, prompts, provider output, and translated results must not enter
  ordinary diagnostic logs.
- The prior popup and engine-switch tasks established non-modal lifecycle,
  placement, privacy, keyboard, toolbar-restoration, and request-generation
  contracts. This work must preserve them.
- Prior visual research and the external v2 prototype support a compact
  header/body/footer hierarchy, native provider menu, target-language label,
  selectable result, and clear error recovery. They explicitly do not establish
  HTML/CSS pixel parity, acrylic blur, remote fonts/icons, or web animation as a
  native requirement. The external prototype contains no configuration screen.
- The API-core child is complete at `f0b651e16`. It provides the synchronous
  provider-neutral `TranslationService`, generated provider settings, bounded
  WinHTTP transport, normalized redacted results, and local-server coverage.
  Remaining UI work must call it from worker threads and must not duplicate
  provider request or response handling.

## Requirements

- R1: Refresh the popup styling while preserving native Win32 theme, DPI,
  accessibility, focus, selection anchoring, and monitor-work-area behavior.
- R1a: Replace the full Translate Selection dialog with a dedicated provider
  configuration window that is visually consistent with the popup.
- R1b: Make that window configuration-only. Remove its source editor, manual
  Translate action, and result viewer.
- R1c: Include the directly supported native presentation and bounded custom
  work identified by UI research: compact provider/target header, state-specific
  body and actions, selectable result, native theme/DPI/RTL/keyboard behavior,
  provider configuration form, small popup corners, dividers, repository-owned
  icons, a lightweight shadow, and a timer-driven loading indicator.
- R2: Add a configurable OpenAI-compatible HTTP API with Base URL, Model, and API
  Key. Normalize the base URL, call its standard `/chat/completions` endpoint,
  and render its translation result inside the popup.
- R2b: Use an application-owned, non-configurable translation prompt that
  incorporates source language, target language, and selected text. Do not add
  custom prompt settings in this task.
- R3: Add Google Cloud Translation and Microsoft Translator APIs and render
  their results inside the popup instead of requiring a browser round-trip.
- R4: Replace AI CLI choices in translation with configured HTTP API providers;
  no translation request may launch an AI CLI.
- R4a: The popup provider picker always lists OpenAI-compatible, Google Cloud
  Translation, and Microsoft Translator in stable order. Incomplete providers
  remain visible but disabled and are labeled `Not configured`; Configure opens
  the provider configuration surface.
- R5: Keep network execution asynchronous. Closing, switching provider, changing
  selection or tab, and document teardown must invalidate late responses.
- R6: Store credentials without exposing secrets in logs, errors, debug-control
  output, status text, or popup content.
- R6a: Persist API keys in plain text with the other provider settings. Warn
  users that local readers, backups, and synchronization tools can read them.
- R6b: Configure provider, endpoint, model, API key, and language preferences in
  the dedicated configuration window. Keep the popup free of credential and
  endpoint editing.
- R7: Remove Google and DeepL browser engines and disable AI CLI integration
  only for selection translation. Preserve the existing AI Chat sidebars,
  commands, settings, and provider implementations.
- R8: Add deterministic focused tests that require no live paid account.
- R8a: Test Connection sends a real provider request with a fixed,
  non-sensitive short string and never selected document text. Warn before the
  action that the request may incur a small provider charge.
- R9: Add `CmdConfigureTranslation`, available without a selection, to open the
  provider configuration surface.
- R10: Keep `CmdTranslateSelection` as a compatibility alias that invokes the
  same quick popup as `CmdTranslateSelectionQuick` so saved toolbar layouts and
  shortcuts continue to translate.
- R11: Remove the Google, DeepL, Grok Build, Claude Code, OpenAI Codex, and
  Antigravity provider-specific translation commands. This does not affect AI
  Chat commands.

## Acceptance Criteria

- AC1: The refreshed popup has testable loading, success, error, configuration,
  and provider-selection states at supported DPI and light/dark themes.
- AC1a: The refreshed full dialog presents API provider configuration with
  consistent native styling, keyboard navigation, DPI behavior, and light/dark
  theme support.
- AC1b: Opening the configuration surface shows no selected source text and
  cannot initiate a translation; translation occurs only through the quick
  popup after an explicit toolbar or command action.
- AC1c: Rounded corners, dividers, icons, shadow, and loading animation degrade
  cleanly when unsupported and do not change popup focus, placement, text
  selection, theme, DPI, or dismissal behavior.
- AC2: A configured OpenAI-compatible base URL and model translate a selection
  asynchronously and display the result in the popup.
- AC3: Google Cloud Translation and Microsoft Translator each translate a
  selection asynchronously and display the result in the popup.
- AC4: Missing or invalid provider configuration produces an actionable error
  and sends no request with incomplete credentials.
- AC5: Provider switching persists the chosen provider and starts a new request
  for the unchanged selection; the old response cannot mutate the popup.
- AC5a: The picker exposes all three supported providers even when none is
  configured, prevents selection of incomplete providers, and retains a visible
  configuration route.
- AC6: Secrets and translation payloads are absent from ordinary logs,
  user-visible raw error bodies, and deterministic debug probes.
- AC6a: Configuration documentation and UI disclose that API keys are stored in
  plain text; saved keys are never echoed back in full outside the settings
  file.
- AC7: Existing popup lifecycle, placement, focus, toolbar restoration, and AI
  Chat CLI coverage continue to pass; former manual-dialog coverage is replaced
  by configuration-window tests.
- AC8: HTTP behavior is covered with deterministic mocks or a local test server;
  validation does not depend on external provider availability.
- AC8a: Test Connection verifies endpoint, authentication, model where
  applicable, and response parsing; its progress and redacted result are shown
  asynchronously without blocking the window.
- AC9: Google and DeepL browser engines no longer appear in translation commands,
  dialogs, popup menus, settings documentation, or runtime dispatch.
- AC10: Translation never launches Grok Build, Claude Code, OpenAI Codex, or
  Antigravity CLI processes; it uses only configured HTTP APIs.
- AC11: Existing AI Chat sidebars continue to discover and launch their CLI
  providers with unchanged commands and settings.
- AC12: `CmdConfigureTranslation` opens configuration without a selection;
  `CmdTranslateSelection` and `CmdTranslateSelectionQuick` both open quick
  translation when a valid selection exists.
- AC13: Removed provider-specific translation commands are absent from generated
  command definitions, menus, command documentation, and dispatch.

## Out of Scope

- Automatic translation before an explicit user action.
- OCR or new selection support for CHM, Markdown, or image-only documents.
- Streaming responses, conversation history, or general-purpose LLM chat.
- Silent fallback to a different provider after a failed request.
- Live-account integration tests in the regular test suite.
- DeepL, Baidu, Youdao, Tencent, and other translation APIs outside Google Cloud
  Translation and Microsoft Translator.
- Acrylic or backdrop blur, translucent card composition, remote fonts or icon
  dependencies, CSS-style transitions, pixel-identical HTML reproduction, and
  new general UI Automation infrastructure for virtual controls. These belong
  to a later native UI infrastructure task.

## Risks and Deferred Items

- API keys are intentionally stored in plain text. The UI and documentation must
  state this, and all logs/probes/errors must remain redacted.
- OpenAI-compatible servers vary despite sharing the Chat Completions shape.
  This task supports the agreed base URL plus `/chat/completions` contract only.
- Provider APIs can change independently. Adapters and deterministic fixtures
  isolate those changes from popup/configuration code.
- Shadow and animation work can expose repaint, DPI, capture, and lifetime bugs.
  Each effect must degrade to the opaque native baseline and can be removed
  without changing functional acceptance.
- Native acrylic, translucent composition, CSS-like transitions, and general
  virtual-control UI Automation are deferred to a separate UI foundation task.

## Delivery Map

- `09-04-translation-api-core`: settings, provider adapters, HTTP contracts,
  normalized results, redaction, and deterministic provider tests. Completed
  and archived at `f0b651e16`.
- `09-04-translation-provider-config-ui`: configuration command and pure native
  provider configuration window, including the minimal shared language catalog
  contract and Test Connection.
- `09-04-translation-popup-ui-migration`: HTTP-provider popup integration,
  native visual refresh, removal of the old manual dialog/runtime paths, and
  focused lifecycle coverage.
- Parent integration unit: removal of obsolete provider-specific commands,
  generic command aliasing, generated command sources, dispatch, debug-control
  integration, and final documentation.
