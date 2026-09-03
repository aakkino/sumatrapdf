# Selection Translation Popup

## Scenario: Quick Selection Translation

### 1. Scope / Trigger

- Trigger: `CmdTranslateSelectionQuick` translates a fixed-page text selection
  from the default selection toolbar.
- `CmdTranslateSelection` remains the full, modal configuration dialog for the
  context menu, command palette, and explicit custom toolbar layouts.
- The quick path sends no text until its command runs. It requires a current
  selection, `Perm::CopySelection`, and a remembered installed AI CLI.

### 2. Signatures

```cpp
void ShowSelectionTranslatePopup(WindowTab* tab);
bool HasSelectionTranslatePopup(MainWindow* win);
void UpdateSelectionTranslatePopup(MainWindow* win);
void RepositionTranslatePopup(MainWindow* win);
void OnTranslateSelectionChanged(MainWindow* win);
void CloseTranslatePopupForTab(WindowTab* tab);
TempStr SelectionTranslatePopupTestTemp(Str action, Str value, int* exitCode);
static TranslateEngine ResolveQuickTranslateEngine();
```

- `CmdTranslateSelectionQuick` is generated from `cmd/gen-commands.ts`; do not
  hand-edit `Commands.h` or `Commands.cpp`.
- Its availability follows selected-text and Copy-permission rules, and it is
  hidden from the command palette. The default toolbar maps to quick; an
  explicit `CmdTranslateSelection` layout entry means full dialog.

### 3. Contracts

- `ShowSelectionTranslatePopup()` reads only the saved source/target languages
  and saved engine. `ResolveQuickTranslateEngine()` accepts it only when
  `EngineIsAI(engine)` and `IsEngineAvailable(engine)`; it never falls back to
  Google, DeepL, or another CLI.
- States are `Hidden`, `Loading`, `Result`, and `Error`. The read-only header
  is `<provider> -> <target language>`. Result text is selectable, scrollable,
  and copied as a whole; provider and languages are edited only in the dialog.
- The popup is owner-associated `WS_POPUP | WS_EX_TOOLWINDOW`. Initial placement
  uses `SWP_NOACTIVATE`, so document focus remains. It must not get permanent
  `WS_EX_NOACTIVATE`: a click activates native result text and controls.
- `GetVisibleSelectionBounds(MainWindow*, Rect&)` is the sole anchor geometry.
  Canvas paint/scroll and frame movement reposition it above selection, below
  when needed, then clamp it to the monitor work area. Hide it, without closing
  state, when selection fragments leave view.
- The worker duplicates text and language values. Completion carries `HWND` and
  `requestId`; UI handling requires a live popup, matching ID, current tab, and
  unchanged selection. Otherwise it drops the result. Closing does not kill the
  CLI process.
- Close and Escape restore the toolbar only when the original selection is
  current. New selection, tab change, and document close leave it hidden.
  Ordinary document clicks do not close the popup.
- `RunTranslation()` diagnostics must exclude selected text, prompt, raw CLI
  output, parsed result, and provider error bodies.
- Debug control `TestSelectionTranslatePopup` (currently `81`) accepts string
  `action` and optional string `value`. `dump` returns `state`, `visible`,
  `configure`, `copy`, `placed`, `header`, and, only in `Result`, `result`.
  `close` closes; `start` creates deterministic Codex/Auto/English loading;
  `result` injects success; `stale` injects `requestId - 1`, which is ignored.
  `dump` and `close` work without a selection; `start`, `result`, and `stale`
  return a non-zero error without one. Unknown actions also return an error.

### 4. Validation & Error Matrix

| Condition                                        | Required behavior                                   |
| ------------------------------------------------ | --------------------------------------------------- |
| No selection, empty text, or no Copy permission  | Do not create popup or start provider.              |
| Saved engine unset, non-AI, or unavailable       | Show `Error` with Configure; send no text.          |
| Valid installed AI engine                        | Show `Loading`, then use only that engine.          |
| CLI failure or timeout                           | Show actionable `Error`; retain non-modal document. |
| Hidden visible fragments                         | Hide window; retain state for later placement.      |
| New selection, tab change, document close        | Close popup and invalidate completion.              |
| Mismatched `HWND`, request ID, tab, or selection | Drop completion without state change.               |

### 5. Good / Base / Bad Cases

- Good: toolbar click with saved Codex shows `Loading`, keeps document focus,
  then shows `Result` beside the current selection.
- Base: `CmdTranslateSelection` still opens its modal dialog and owns provider
  and language editing.
- Bad: saved Google or missing CLI opens Configure error and sends no selection
  text; a late result cannot revive a closed popup.

### 6. Tests Required

- `tests/selection-translate-popup.ts`: assert default toolbar uses quick;
  invalid Google setting produces visible Configure error and preserves focus;
  close restores toolbar; `start`, `result`, and `stale` prove loading, result,
  Copy visibility, placement following frame movement, and stale rejection;
  a changed selection closes the popup.
- `tests/issue-5934.ts`: assert the original dialog still opens and Escape
  closes it. `tests/issue-6048.ts`, `tests/selection-toolbar-stays.ts`, and
  `tests/selection-toolbar-move.ts` protect toolbar layout, restoration, and
  movement.
- Review `RunTranslation()` logging call sites: no ordinary diagnostic receives
  source, prompt, raw output, result, or provider body.

### 7. Wrong vs Correct

#### Wrong

```cpp
TranslateEngine engine = ResolveEngine(TranslateEngine::Default);
```

This resolver can select browser engines or another available provider.

#### Correct

```cpp
TranslateEngine engine = ResolveQuickTranslateEngine();
if (engine == TranslateEngine::Default) {
    popup->SetState(SelectionTranslatePopupState::Error, message, PopupAction::Configure);
}
```

Only the remembered installed AI CLI may receive quick-selection text.
