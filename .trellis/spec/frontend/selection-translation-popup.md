# Selection Translation UI

## Scenario: Quick Selection Translation

### 1. Scope / Trigger

- `CmdTranslateSelection` and `CmdTranslateSelectionQuick` are compatibility
  aliases: each translates the current fixed-page text selection in the same
  non-modal popup. The default selection toolbar uses the quick command.
- The popup requires a current selection, `Perm::CopySelection`, and
  `Perm::InternetAccess`. Without Internet access it creates no popup and
  leaves the toolbar, request ID, and stored provider unchanged.
- `CmdConfigureTranslation` is separate and opens the configuration window
  without a selection. Selection translation never launches a browser or an AI
  CLI; existing AI Chat behavior is outside this boundary.

### 2. Signatures

```cpp
void ShowSelectionTranslatePopup(WindowTab* tab);
bool HasSelectionTranslatePopup(MainWindow* win);
void UpdateSelectionTranslatePopup(MainWindow* win);
void RepositionTranslatePopup(MainWindow* win);
void OnTranslateSelectionChanged(MainWindow* win);
void CloseTranslatePopupForTab(WindowTab* tab);
TempStr SelectionTranslatePopupTestTemp(Str action, Str value, int* exitCode);
```

- `CmdTranslateSelection` and `CmdTranslateSelectionQuick` both dispatch to
  `ShowSelectionTranslatePopup()`. `CmdConfigureTranslation` dispatches to
  `ShowTranslationConfig()` and is not selection-gated.

### 3. Contracts

- `ShowSelectionTranslatePopup()` snapshots the saved source/target languages,
  `TranslationSettingsFromGlobal()`, the tab, and the selection. It delegates
  provider completeness, request construction, response parsing, and language
  codes to `TranslationService`.
- States are `Hidden`, `Loading`, `Result`, and `Error`. Every visible state
  has a compact provider button followed by a read-only `-> <target language>`
  label. Result text is a selectable, scrollable, read-only native edit and
  Copy copies the whole result.
- The provider menu enumerates `TranslationProviders()` in service order. The
  active provider is checked; incomplete providers are disabled and suffixed
  `Not configured`; a separator and `Configure...` end the menu. Dismissing the
  menu or choosing the active provider changes nothing and sends no text.
- Choosing another configured provider rechecks the current tab, selection,
  selected text, Copy permission, and Internet permission; persists its
  canonical provider name; then starts one new request. Retry performs the
  same checks with the active provider. Configure closes the popup without
  restoring the toolbar, then opens configuration.
- `TranslateText()` runs only in the popup worker. The task owns duplicated
  settings, languages, and selected text. Completion contains `HWND` and
  request ID and is accepted only for a live popup with that ID, current tab,
  and unchanged selection. Closing clears the ID and removes the live popup.
- The owner-associated `WS_POPUP | WS_EX_TOOLWINDOW` is first shown with
  `SWP_NOACTIVATE`, preserving document focus. It must not be permanently
  no-activate because clicking the result edit or a native control may focus it.
  Theme, DPI, and RTL updates relayout the native controls; rounded corners,
  shadow, icon, dividers, and the loading timer degrade to the opaque baseline.
- `GetVisibleSelectionBounds(MainWindow*, Rect&)` is the only anchor geometry.
  Place above the selection, below if needed, then clamp to the monitor work
  area. Frame movement and selection updates reposition it. If selection
  fragments leave view, hide the window without discarding state.
- Close and Escape restore the toolbar only when the original selection is
  still current. New selection, tab change, and document close leave it hidden.
- `SelectionTranslatePopupTestTemp()` exposes state, controls, placement,
  provider status, request ID, and result length. A production completion never
  exposes result text; `result=<text>` is permitted only after the explicit
  deterministic test-result injection. No popup diagnostic or probe may expose
  keys, selected text, request data, raw provider bodies, or production results.

### 4. Validation & Error Matrix

| Condition                                                | Required behavior                                                                       |
| -------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| No selection, blank selected text, or no Copy permission | Do not create a popup or start a provider.                                              |
| No Internet permission                                   | Do not create, hide the toolbar, allocate an ID, persist a provider, or start a worker. |
| Saved provider is missing, legacy, or incomplete         | Show Error with Configure; send no text.                                                |
| Complete saved provider                                  | Show Loading, hide the toolbar, and start one worker request.                           |
| Provider menu opens                                      | Show all service providers and configuration status; send no text.                      |
| Configured provider chosen                               | Persist canonical name and replace the request for the unchanged selection.             |
| Active/incomplete provider chosen, or menu canceled      | Keep state, request ID, and preference unchanged.                                       |
| Provider failure or timeout                              | Show a redacted Error with Retry and Configure.                                         |
| Visible selection bounds unavailable                     | Hide the window and retain state.                                                       |
| Selection, tab, or document changes                      | Close, invalidate completion, and do not restore the old toolbar.                       |
| Completion has another `HWND`, ID, tab, or selection     | Drop it without changing state.                                                         |

### 5. Good / Base / Bad Cases

- Good: a selected document string with a complete provider opens Loading beside
  the selection without stealing document focus; switching to another complete
  provider persists it and only the replacement result can complete.
- Base: an incomplete saved provider shows Configure, keeps all three providers
  visible in the menu, and sends no selected text.
- Bad: dispatching one generic command to a dialog and the other to a popup,
  falling back to a browser or AI CLI, accepting a stale result, or emitting a
  production translation in a debug dump.

### 6. Tests Required

- `tests/selection-translate-popup.ts` asserts the default toolbar command,
  incomplete-provider Configure state, non-stolen focus, all provider statuses,
  active/incomplete no-ops, switching and canonical persistence, request
  replacement on Retry, placement after frame movement, result/Copy state,
  production-result redaction, toolbar restoration, changed-selection close,
  and stale-result rejection. A restricted copied executable verifies that
  creation, Start, switching, and Retry leave no toolbar, request, or
  persistence side effect without Internet permission. It uses no-worker test
  transitions and no live provider.
- `tests/issue-5934.ts` asserts both generic commands open the popup and Escape
  closes it. Review normal/high DPI, light/dark, and RTL UI captures to assert
  the popup remains placed, legible, and keyboard-reachable without focus drift.
- Provider transport belongs in `tests/translation-api.ts`; its assertions do
  not substitute for popup lifecycle coverage.

### 7. Wrong vs Correct

#### Wrong

```cpp
TranslateText(settings, request, &result);
popup->OnDone(result.ok, result.text);
```

The UI thread blocks, and a closed or superseded popup can receive the result.

#### Correct

```cpp
RunAsync(MkFunc0(SelectionTranslatePopupThread, task), StrL("SelectionTranslatePopup"));
// UI completion verifies HWND, request ID, tab, and selection before SetState().
```

Keep provider transport and text-bearing values out of the UI thread and probe
output.

## Scenario: Translation Provider Configuration

### 1. Scope / Trigger

- `CmdConfigureTranslation` calls `ShowTranslationConfig()` with or without a
  document selection. The singleton native window configures providers and
  language preferences; it is not a manual translation dialog.
- The window consumes shared provider metadata and language labels from
  `TranslationService`. It does not duplicate provider request formats,
  provider code mappings, or HTTP handling.
- Configuration remains available without `Perm::InternetAccess`; only Test
  Connection is disabled and it must not allocate a request or start a worker.

### 2. Signatures

```cpp
void ShowTranslationConfig();
TempStr TranslationConfigTestTemp(Str action, Str value, int* exitCode);
void CollectVirtCtrls(ILayout* root, Vec<VirtCtrl*>& out);
```

- `CmdConfigureTranslation` must stay available without `Perm::CopySelection`.
  The quick-popup `Configure...` route calls the same entry point.
- Both `ShowTranslationConfig()` paths call `HwndToForeground(hwnd)` before
  `WindowBase::SetFocusTo(dropProvider)`. The native provider selector needs
  the latter forced-focus call after foreground activation.

### 3. Contracts

- There is one configuration window. Both creation and singleton reopen bring
  it to foreground, then force focus with
  `WindowBase::SetFocusTo(dropProvider)` in that order; foreground activation
  may otherwise replace the intended keyboard focus.
- The selector uses `TranslationProviders()`; only the selected provider's
  fields are visible. Changing provider retains unsaved values for every
  provider. Source offers `Auto` plus `TranslationLanguageLabel()` entries;
  target offers only the shared labels.
- `ControlBase::SetVisibility()` shows and hides native child controls with
  `ShowWindow(SW_SHOW/SW_HIDE)`. The full Win32 lifecycle lets native Edit
  controls paint their `WM_NCPAINT` non-client frames; provider switching only
  selects fields and must not add provider-specific redraws.
- `CollectVirtCtrls()` is the virtual paint collection boundary. It stops at a
  `Visibility::Collapse` layout node and returns none of that subtree's virtual
  controls. Provider switching therefore cannot paint hidden titles or labels;
  visible layouts and nested virtual roots keep their existing traversal.
- Save requires a valid selected provider, source language, and target language,
  then commits the canonical provider name, every provider field, and
  source/target values.
  It writes settings when `Perm::SavePreferences` allows it. Cancel, Escape,
  Ctrl+W, or closing the window discards unsaved edits. API keys remain
  plain-text settings and are visibly warned as readable by local files,
  backups, and sync services.
- Test Connection is explicit, warns about possible provider charges, validates
  before I/O, and sends only the fixed `Hello.` probe from a worker. It owns a
  copied settings/request snapshot and returns only `Connection succeeded.` or
  `Connection failed.` to a live window with the matching request ID and HWND.
  It never sends selected document text.
- The resizable native window follows app theme, DPI, and RTL layout. DPI
  changes update fonts, dimensions, and layout. `UpdateDpi()` updates the
  stored provider row labels and headings directly because `CollectVirtCtrls()`
  intentionally omits collapsed provider layouts. RTL reverses provider and
  form rows while retaining logical tab navigation.
- `TranslationConfigTestTemp()` is deterministic: it may drive local edits and
  completions and reports selected provider/source/target labels, counts,
  visibility, focus, validation, bounded status, request ID, and byte lengths.
  It must mask keys and never return key values, request bodies, selected text,
  or provider responses.

### 4. Validation & Error Matrix

| Condition                                               | Required behavior                                                                                                                                                |
| ------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Configuration command without a selection               | Open the configuration window; do not translate.                                                                                                                 |
| New or existing configuration window                    | Call `HwndToForeground()` then `WindowBase::SetFocusTo(dropProvider)`; retain one window and provider focus.                                                     |
| Provider form is collapsed                              | Prune its whole virtual subtree from `CollectVirtCtrls()`; paint no hidden title or label.                                                                       |
| Provider form becomes visible                           | Show its native children through `ControlBase::SetVisibility()` so every visible Edit paints its non-client frame; HWND visibility and bounds alone do not pass. |
| Required field, source, or target missing               | Show bounded validation message; disable Save/Test and send no request.                                                                                          |
| Test Connection while valid and idle                    | Allocate a new ID, show progress, and start one worker with `Hello.`.                                                                                            |
| Test Connection without Internet permission             | Keep configuration and Save available; disable Test and allocate no ID or worker.                                                                                |
| Test Connection while working or invalid                | Leave the active request unchanged; show validation where applicable.                                                                                            |
| Late, closed-window, wrong-ID, or wrong-HWND completion | Drop it without changing status.                                                                                                                                 |
| Save valid edits                                        | Commit all provider settings and languages, write when allowed, then close.                                                                                      |
| Cancel/Escape/Ctrl+W/close                              | Close without persisting local edits.                                                                                                                            |

### 5. Good / Base / Bad Cases

- Good: configuration opens or reopens with the provider selector focused,
  masks a stored key, switches fields without losing an edit or painting a
  collapsed provider form, and after Google -> OpenAI-compatible -> Microsoft
  every selected Edit has four captured painted frame edges. It validates
  locally, tests `Hello.` on a worker, and saves all provider values only after
  Save.
- Base: an invalid OpenAI-compatible key blocks Test and Save while its error
  is shown; Cancel leaves the previously saved provider intact.
- Bad: displaying selection source text, translating from this window without
  Test Connection, focusing before foreground activation, collecting a
  collapsed form's virtual labels, flipping only `WS_VISIBLE` and leaving an
  Edit frame unpainted, or exposing a key in the deterministic dump.

### 6. Tests Required

- `tests/translation-config.ts` asserts command opening without a selection,
  provider and shared-language counts, provider focus after both first open and
  singleton reopen, masked-key and storage/cost warnings, provider-specific
  field visibility, local validation, preservation of unsaved provider fields,
  stale Test Connection rejection, redacted success/failure status, Save
  persistence, and Cancel non-persistence. It changes DPI while cycling every
  provider and verifies all stored labels/headings use the current font; a
  restricted executable keeps configuration and Save available while Test
  Connection produces no request or worker.
- `VirtCtrl_UnitTests()` asserts `CollectVirtCtrls()` omits every descendant of
  a collapsed layout node, restores them when visible again, and leaves visible
  layout traversal unchanged. Repeated configuration provider switching must
  show only the selected provider's titles and labels.
- `tests/ad-hoc-translation-config-edit-redraw.ts` starts with Google, then
  asserts Google -> OpenAI-compatible and OpenAI-compatible -> Microsoft. For
  each transition, it captures every selected native Edit and samples all four
  frame edges; a visible HWND or correct bounds without painted edge pixels
  fails.
- Review light/dark, high-DPI, and RTL layouts: assert labels/controls remain
  visible, field rows mirror correctly, the minimum size prevents clipping, and
  returning to an existing window leaves the provider selector focused.
- `tests/translation-api.ts` separately verifies provider transport with local
  fixture data. The configuration test uses deterministic no-worker transitions;
  source review verifies its production worker sends fixed `Hello.` and no
  document text.

### 7. Wrong vs Correct

#### Wrong

```cpp
HwndSetWindowStyle(hwnd, WS_VISIBLE, toBOOL(isVisible));
```

Changing the style leaves an Edit HWND visible but can skip the non-client
paint lifecycle, so its frame pixels are absent.

#### Correct

```cpp
::ShowWindow(hwnd, isVisible ? SW_SHOW : SW_HIDE);
```

`ControlBase` owns the generic lifecycle; provider switching only changes which
fields are visible.
