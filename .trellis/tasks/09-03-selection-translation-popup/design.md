# Technical Design

## Architecture

Keep the feature inside the existing selection and translation boundary:

```text
SelectionToolbar
  -> CmdTranslateSelectionQuick
  -> ShowSelectionTranslatePopup(tab)
  -> validate selection, permission, saved AI engine, languages
  -> snapshot text and selection identity
  -> show popup in Loading state
  -> existing AI CLI runner on worker thread
  -> UI-thread completion keyed by HWND and request generation
  -> Result or Error state
```

- Add `CmdTranslateSelectionQuick` at the required end of `cmd/gen-commands.ts`
  and regenerate `Commands.h` and `Commands.cpp`. Only the built-in toolbar uses
  it. Register it with command availability so the command palette hides it and
  Copy permission gates it. Existing translation commands keep their meanings.
- Implement the popup and quick orchestration in `SelectionTranslate.cpp`, exposed
  through terse lifecycle functions in `SelectionTranslate.h`. Reuse the existing
  translation runner, language defaults, error formatting, themed controls, and
  UI-task completion pattern rather than creating a second provider layer.
- Extract the toolbar's visible-selection bounds calculation into the selection
  layer so toolbar and popup share one geometry source. The UI layer converts that
  canvas rectangle to screen coordinates and applies monitor-aware placement.
- Use an owner-associated `WindowBase` popup with `WS_POPUP | WS_EX_TOOLWINDOW`.
  Show it without activation; omit permanent `WS_EX_NOACTIVATE` so a click can
  activate native read-only text and controls. Use the existing mixed native/
  virtual focus and DPI handling.
- Keep one popup per main window. Store its tab and selection generation so a
  different tab or selection cannot receive a stale completion.
- Add a narrow `-dbg-control` popup probe for deterministic state injection and
  inspection. Production translation remains behind the existing high-level
  runner; tests must not require a live AI account.

## Lifecycle and State

The popup has four explicit states: `Hidden`, `Loading`, `Result`, and `Error`.
State transitions have one owner.

```text
Hidden --quick click, valid engine--> Loading --success--> Result
  |                |                    |--failure-------> Error
  |                +--invalid engine--------------------> Error
  +<--Close/Esc/new selection/tab or document close-----+
```

- Quick invocation validates the current fixed-page selection and Copy permission,
  resolves only the saved AI engine, and duplicates selected text before returning
  to the message loop. It never uses the existing fallback-to-Google resolver.
- The popup appears in `Loading` before starting work. Its header is a read-only
  `provider -> target language` label. Long results use a read-only multiline edit
  with scrolling and text selection. Copy copies the complete result.
- The worker owns duplicated input. Completion carries the target HWND and request
  generation. The UI callback first validates the live popup, generation, tab, and
  selection identity; otherwise it frees the result and returns.
- Closing does not attempt to kill the CLI process. Explicit Close or Escape may
  reshow the toolbar when the saved selection identity still matches. New selection,
  tab change, and document teardown close without restoring stale UI.
- Canvas paint/scroll and frame-move hooks reposition the popup from shared visible
  selection bounds. If no fragment is visible, hide the window without discarding
  state; show it again when the same selection becomes visible. A tab or selection
  mismatch destroys the state.
- Invoking quick translation hides the toolbar. The popup occupies the preferred
  above-selection position, falls below when needed, and clamps to monitor work
  area. Dimensions are DPI-scaled and bounded; long text scrolls instead of growing
  beyond the work area.
- Showing and asynchronous completion use no-activate positioning. Mouse activation
  is allowed. Escape closes from either popup focus or the existing selection-clear
  path in the frame.
- Replace payload logging in the shared translation runner with metadata-only
  diagnostics. Do not log source text, prompt, raw stdout, parsed result, or
  provider error bodies that may echo input.

## Compatibility and Ownership

- Use `research/external-ui-reference.md` for the popup's compact header/body/footer
  hierarchy and action priority. Adapt it to native SumatraPDF controls, theme, DPI,
  and accessibility. Exclude its web shell, remote dependencies, branding,
  `Source / Result` switch, hard-coded Google label, acrylic requirement, and
  duplicate Close action.
- Existing modal `CmdTranslateSelection` and provider-specific commands remain
  compatible. Their dialog continues to own provider/language editing and saved
  preferences.
- Map the generated default toolbar layout to the quick command. Explicit legacy
  layouts containing `CmdTranslateSelection` retain their documented full-dialog
  meaning; document the new quick command for users who customize the layout.
- No settings schema, network API, credential store, vendored dependency, or
  document-engine boundary changes.
- Generated command sources are changed only through `cmd/gen-commands.ts` and
  `bun cmd/gen-code.ts`.
- New user-visible command behavior is documented in `docs/md/Commands.md` and the
  next release's **New commands** list in `docs/md/Version-history.md`.
- Rollback consists of removing the quick command and popup/probe code, restoring
  the toolbar command mapping, regenerating commands, and removing the focused test
  and docs entries. The existing full dialog remains intact throughout.
