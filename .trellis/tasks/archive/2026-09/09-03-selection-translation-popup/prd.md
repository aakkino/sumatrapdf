# Selection translation popup

## Goal

Let users translate selected document text and read the result beside the
selection without leaving or blocking the document.

## Background

- The fixed-page selection toolbar already exposes `CmdTranslateSelection`
  (`src/SelectionToolbar.cpp:82`, `src/Selection.cpp:1004`).
- `CmdTranslateSelection` opens a centered modal dialog with source, provider,
  language, loading, result, and error controls (`src/SumatraPDF.cpp:12439`,
  `src/SelectionTranslate.cpp:1020`, `src/SelectionTranslate.cpp:1175`).
- Google and DeepL open a browser. Installed Grok, Claude, Codex, and Antigravity
  CLIs return results asynchronously inside SumatraPDF.
- `GetSelectionScreenRect()` provides a selection anchor
  (`src/Selection.cpp:168`). The toolbar already follows visible selection
  fragments during scrolling and frame movement.
- This selection path is limited to fixed-page documents with extractable text.
  CHM and Markdown use separate selection models; image-only content needs OCR.

## Requirements

- R1: Add a dedicated quick-translation command to the existing selection
  toolbar. Keep `CmdTranslateSelection` opening the full dialog from the context
  menu and command palette.
- R2: Start quick translation only after the user clicks the toolbar action.
  Preserve Copy-permission checks and send no text before that click.
- R3: Use only the remembered, currently installed AI CLI and remembered source
  and target languages. Do not silently select another provider or use
  Google/DeepL.
- R4: When no valid AI CLI is configured, send no text and show an error with a
  Configure action that opens the existing full dialog.
- R5: Show a lightweight, non-modal popup anchored to the visible selection. Its
  only content is a read-only provider-to-target-language header, loading/result/
  error content, Copy, Close, and the conditional Configure action.
- R6: Show and complete the popup without taking document focus. Let a user click
  it to activate, scroll, select text, use the keyboard, and reach accessible
  controls.
- R7: Reposition the popup while the document scrolls or the frame moves. Constrain
  it to the current monitor work area.
- R8: Dismiss the popup on Close, Escape, a new selection, tab change, or document
  close. Ignore late asynchronous results. Ordinary document clicks do not dismiss
  it.
- R9: Hide the selection toolbar while the popup is visible. After the popup closes,
  restore the toolbar when the original selection is still current.
- R10: Do not write selected text, generated prompts, CLI output, or translated
  text to ordinary diagnostic logs.
- R11: Support fixed-page documents with extractable selected text and Copy
  permission. Preserve all other selection behavior.

## Acceptance Criteria

- AC1: The selection toolbar invokes a new quick command; existing context-menu and
  command-palette `CmdTranslateSelection` entries still open the full dialog.
- AC2: One click opens a loading popup and starts translation with the remembered AI
  CLI and language settings; selection alone sends nothing.
- AC3: An unset, non-AI, or unavailable remembered engine starts no provider and
  shows an error whose Configure action opens the full dialog.
- AC4: The popup header identifies the AI provider and target language and exposes
  no editable source, engine, or language fields.
- AC5: Success shows selectable, scrollable text with Copy and Close controls;
  failure and timeout show an actionable error without blocking the document.
- AC6: Showing and completing the popup preserves document focus. Clicking the
  popup activates its keyboard, scrolling, selection, and accessible controls.
- AC7: Scrolling and frame movement keep the popup beside the visible selection and
  inside the monitor work area.
- AC8: Close, Escape, a new selection, tab change, and document close dismiss the
  popup; late completions do not revive or mutate it.
- AC9: Ordinary document clicks leave the popup open.
- AC10: The toolbar is hidden while the popup is visible and returns after an
  explicit popup close when the original selection remains valid.
- AC11: Ordinary diagnostics contain no source text, prompt, CLI output, or result.
- AC12: Existing full-dialog, toolbar-layout, toolbar-persistence, and toolbar-move
  focused tests continue to pass.

## Out of Scope

- Direct HTTP translation APIs, API-key storage, and new credential management.
- Automatic translation when selection settles.
- Silent provider fallback.
- OCR and selection support for CHM, Markdown, or image-only content.
- Provider or language editing inside the quick popup.
- Cancellation of the external CLI process; closed or stale requests are ignored.

## Technical Notes

- AI CLI translation may send selected text to the provider's cloud service. It is
  not offline translation.
- Research is recorded under `research/selection-architecture.md`,
  `research/floating-ui-patterns.md`, and `research/translation-integration.md`.
