# Quick translation engine switch

## Goal

Make the AI engine used by quick selection translation discoverable and fast to
change without editing Advanced Settings by hand.

## Background

- Follow-up feedback was extracted from Codex session
  `01a065ab-9ad6-7780-9ad4-f90028f8e331`, which produced archived task
  `09-03-selection-translation-popup`.
- The current v2 UI reference at
  `D:\desktop_directory\selection-translation-popup` was reviewed across its
  Result, Menu, Toolbar, Loading, and Error states. Its native adaptation is
  recorded in `research/ui-design-reference.md`.
- Near the end of that development session, the user asked how to switch the AI
  CLI configuration, reported that the translation window had no quick-switch
  button, and asked how to configure the engine in Advanced Settings.
- The shipped quick popup intentionally reads the remembered `TranslateEngine`
  and exposes no engine or language editor. Its `Configure` action appears only
  when the saved engine is invalid or unavailable
  (`src/SelectionTranslate.cpp:1623`, `src/SelectionTranslate.cpp:1650`,
  `src/SelectionTranslate.cpp:1821`).
- The full translation dialog already lists available engines and persists the
  selected engine (`src/SelectionTranslate.cpp:320`,
  `src/SelectionTranslate.cpp:810`, `src/SelectionTranslate.cpp:1043`).
- `TranslateEngine` is an internal advanced setting generated from
  `cmd/gen-settings.ts:1618` and documented in
  `docs/md/Advanced-options-settings.md:709`. Requiring users to edit it is not
  a discoverable switching workflow.
- The existing popup contract permits only the remembered installed AI CLI and
  deliberately excludes provider editing inside the popup
  (`.trellis/spec/frontend/selection-translation-popup.md`). This task must
  revise that contract rather than silently contradict it.

## Requirements

- R1: Provide an in-product, discoverable way to change the AI CLI used by quick
  selection translation.
- R2: Offer only installed AI CLI engines. Do not offer Google, DeepL, or an
  unavailable CLI on the quick path.
- R3: Keep selection translation opt-in. Opening the engine menu sends no text;
  explicitly choosing a different engine authorizes retransmission of the
  unchanged current selection.
- R4: Persist an explicitly chosen engine through the existing
  `TranslateEngine` preference so later quick translations use it.
- R5: Clearly identify the active provider and target language before and after
  switching.
- R6: Preserve popup placement, non-modal document interaction, keyboard access,
  selection/tab/document dismissal, stale-result rejection, Copy permission,
  and sensitive-payload logging protections.
- R7: Keep source- and target-language editing in the full translation dialog
  unless later feedback explicitly expands this task.
- R8: End the engine menu with a separator and `Configure...` item that opens the
  full translation dialog for language changes and broader configuration.
- R9: Present the active provider name as the switch control. When no valid
  engine is selected, present a clear choose-engine label instead.
- R10: Selecting the already active engine is a no-op. Selecting another engine
  invalidates the previous request and immediately retranslates the unchanged
  current selection.
- R11: In every state, show a compact provider control followed by a read-only
  target-language label. Use a clear choose-engine label when the saved engine
  is invalid.

## Acceptance Criteria

- AC1: A user can identify and change the quick-translation AI engine from an
  ordinary valid popup state without opening Advanced Settings.
- AC2: The switcher contains only installed Grok Build, Claude Code, OpenAI Codex,
  or Antigravity engines.
- AC3: Choosing another engine persists the exact engine name and translates the
  current selection with that engine only after the choice.
- AC4: The popup immediately reflects the chosen provider and exposes loading,
  result, failure, and timeout states without blocking the document.
- AC5: A missing or unavailable saved engine remains recoverable through a clear
  configuration path and sends no selected text automatically.
- AC6: Keyboard and mouse users can reach, operate, and dismiss the switcher; the
  popup remains inside the monitor work area at supported DPI values.
- AC7: Late output from the previous engine cannot replace the result from the
  newly selected engine or revive a closed popup.
- AC8: Existing focused tests for the full dialog, toolbar, popup lifecycle,
  privacy, and command routing remain valid; new deterministic coverage verifies
  switch visibility, filtering, persistence, restart, and stale completion.
- AC9: The switch control is visible in loading, result, error, and invalid-engine
  states; choosing the active engine starts no duplicate request.
- AC10: The engine menu ends with a separated `Configure...` item that opens the
  existing full dialog without changing provider or sending text.

## Out of Scope

- Adding, installing, authenticating, or configuring AI CLI executables.
- Direct HTTP translation providers or credential storage.
- Source- or target-language switching in the quick popup.
- Automatic engine fallback or automatic translation on selection.
- OCR and non-fixed-page selection models.
- Changing the external AI CLI invocation protocols.

## Key Decisions

- The provider name in the popup header is a compact menu button.
- The menu lists only currently installed and permitted AI CLI engines and marks
  the active engine.
- The menu always provides `Configure...` after a separator; the invalid-engine
  footer action remains as an additional recovery path.
- Choosing another engine persists it, invalidates the previous request, and
  immediately retranslates the unchanged current selection.
- The full dialog remains the place for language changes and broader
  configuration.
