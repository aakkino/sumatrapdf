# Research: UI design reference

- Query: How should `D:\desktop_directory\selection-translation-popup` refine the
  quick translation engine-switch task for the native Win32 popup?
- Scope: internal
- Date: 2026-09-04

## Files Inspected

| File                                                                                                | Finding                                                                                                                                                                                                                                                                     |
| --------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `D:\desktop_directory\selection-translation-popup\README.md`                                        | Declares v2.0 as the active prototype and describes the provider button, filtered AI menu, checkmark, restart, and all-state visibility.                                                                                                                                    |
| `D:\desktop_directory\selection-translation-popup\prd.md`                                           | Mirrors the current 09-04 task requirements and acceptance criteria.                                                                                                                                                                                                        |
| `D:\desktop_directory\selection-translation-popup\design.md`                                        | Mirrors the current 09-04 technical design, including native `TrackPopupMenu`.                                                                                                                                                                                              |
| `D:\desktop_directory\selection-translation-popup\implement.md`                                     | Mirrors the current implementation unit and test-first plan.                                                                                                                                                                                                                |
| `D:\desktop_directory\selection-translation-popup\index.html`                                       | Portal identifies Result, Menu, Toolbar, Loading, and Error as the active v2.0 review states; its side-by-side comparison calls for a compact header control and native checked menu (`index.html:61-78`, `105-148`).                                                       |
| `D:\desktop_directory\selection-translation-popup\screen-toolbar.html`                              | Keeps the existing selection toolbar and makes only the quick-translate icon visually active (`screen-toolbar.html:43-51`).                                                                                                                                                 |
| `D:\desktop_directory\selection-translation-popup\screen-loading.html`                              | Shows the same provider switcher in Loading, source-target label, and no result Copy action (`screen-loading.html:64-107`).                                                                                                                                                 |
| `D:\desktop_directory\selection-translation-popup\screen-menu.html`                                 | Shows a provider button anchored to a checked, AI-only menu and a Configure action after a separator (`screen-menu.html:86-150`).                                                                                                                                           |
| `D:\desktop_directory\selection-translation-popup\screen-result.html`                               | Supplies the clearest target: provider control then target language in the header, editable-result-style body, and footer Copy/Done actions (`screen-result.html:70-143`). Its script models a selection as persistence plus a loading overlay (`screen-result.html:149+`). |
| `D:\desktop_directory\selection-translation-popup\screen-error.html`                                | Shows the explicit `Choose Engine` header state and an error body that does not imply automatic text submission (`screen-error.html:63-115`).                                                                                                                               |
| `D:\desktop_directory\selection-translation-popup\screen-result.png`                                | Viewed. The rendered target uses a compact white popup over the selected document text, with a provider drop-down at header left, target language beside it, a close affordance at header right, result body, and small persistence/copy/done footer.                       |
| `D:\desktop_directory\selection-translation-popup\assets\baseline\real-win32-popup-result.png`      | Viewed. It is the current native baseline: border-only rectangular popup, a passive header, scrollable result edit, and Copy/Close footer.                                                                                                                                  |
| `D:\desktop_directory\selection-translation-popup\assets\baseline\real-win32-selection-toolbar.png` | Viewed. It confirms the existing compact toolbar geometry and does not require a toolbar layout change.                                                                                                                                                                     |

`archive/v1-09-03-selection-translation-popup` was not used as the source of
current intent. The design README explicitly labels it historical.

## Confirmed Native Baseline

- The popup currently has a single passive `VirtText` header, then status/result,
  then Copy, Configure, and Close controls. It begins at 360 x 180 DPI-scaled
  units and uses content sizing (`src/SelectionTranslate.cpp:1722-1765`).
- The header is recomputed as `<provider> -> <target>` for every state; invalid
  engine uses the generic `Translation` provider (`src/SelectionTranslate.cpp:1621-1655`).
- Valid quick translation is intentionally restricted to installed AI engines;
  saved Google, DeepL, unset, or unavailable values show Configure without
  submitting text (`src/SelectionTranslate.cpp:1821-1861`).
- `Start()` creates a new request ID before Loading and the completion handler
  requires matching HWND, request ID, tab, and unchanged selection
  (`src/SelectionTranslate.cpp:1773-1819`).
- The existing frontend contract still says the header is read-only and that
  provider editing belongs only in the full dialog; it must change
  (`.trellis/spec/frontend/selection-translation-popup.md:35-41`).
- `VirtButton` provides mouse and keyboard activation, and the project already
  has themed button construction (`src/gui/VirtCtrl.h:673-690`,
  `src/Theme.cpp:31-40`).
- Native checked popup menus are an established local pattern. `PopupPick()`
  builds `CreatePopupMenu`, checks the current item, calls `TrackPopupMenu` with
  `TPM_RETURNCMD`, then eats the dismiss click over the originating chip
  (`src/AnnotEditToolbar.cpp:973-1024`).

## State-by-State Mapping

| Design state                 | Preserve from reference                                                                                                             | Native implementation mapping                                                                                                                                                                                                                 |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Toolbar                      | Quick Translate remains a compact toolbar action.                                                                                   | No toolbar rearrangement. Existing command routing and toolbar tests remain authoritative.                                                                                                                                                    |
| Result                       | Header order is `provider control -> target language`; provider is compact, immediately recognizable, and visible above the result. | Replace `header` with an `HBox`: engine `VirtButton`, read-only arrow/target `VirtText`, and retain existing result `Edit` and footer. Recompute the engine control text in every `SetState()`.                                               |
| Open menu                    | List only installed AI CLIs, place a native check on the active item, and use a separator before Configure.                         | Enumerate `gAllEngines` in existing order, filter with `EngineIsAI()` and `IsEngineAvailable()` (`src/SelectionTranslate.cpp:739-782`), use `MF_CHECKED`, and return an internal item ID. Do not use the HTML per-provider icons or headings. |
| Loading                      | Keep the provider control enabled while the replacement request is running; show which provider is being used.                      | Keep the header button visible/enabled. The ordinary status text is the native loading indication; after selection, call the existing `Start()` path to make the stale completion guard effective.                                            |
| Error / invalid saved engine | Use the `Choose Engine` label and retain a recovery route.                                                                          | The button remains enabled. If runnable engines exist, choosing one persists and starts the current selection. If none exist, the menu has no provider choices and Configure remains available.                                               |

## Native Adaptation Guidance

1. Adopt the reference's hierarchy, not its web rendering: a compact labeled
   provider button, target language text, native checked menu, explicit
   `Choose Engine` state, and persistent switcher visibility in all states.
2. Use the current theme, `GetAppFont()`, DPI-scaled layout, `VirtButton`, and
   `TrackPopupMenu`. Do not copy Tailwind, CDN fonts, Material Symbols, CSS
   blur/transparency, fixed CSS pixel widths, rounded web cards, or HTML loading
   overlays. The baseline popup is intentionally a compact system-styled window.
3. Keep the popup's content-driven dimensions and current selection-relative
   placement. The reference's 380/390/450 CSS widths are illustrative and must
   not become native fixed geometry; `Place()` already clamps to the work area
   (`src/SelectionTranslate.cpp:1586-1619`).
4. Use the local `PopupPick()` behavior as the menu interaction precedent.
   `TrackPopupMenu` runs a nested loop and its dismissing mouse click can reopen
   the control unless the originating-button click is consumed. The switcher
   needs equivalent containment, but should not globally suppress a click on a
   different control.
5. A real system menu cannot display the reference's inline disabled result body
   or custom provider glyphs while open. Menu cancellation remains a no-op;
   engine selection returns to the popup, updates it to Loading, and starts the
   replacement request.
6. Preserve the existing footer Copy/Close behavior unless the parent task
   explicitly changes it. The reference's top-right close glyph and `Done`
   footer are not supported by the current plan and are less important than the
   provider-switch interaction. Adding them would expand focus, accessibility,
   and test scope without helping engine selection.

## Conflicts and Required Plan Changes

### Product contract

- `prd.md` R3 currently says an engine change "must not send text until the
  user explicitly chooses an engine for the current translation," while R10 and
  AC3 require a different-engine selection to immediately retransmit. Revise R3
  to state: initial quick translation remains opt-in; choosing a different menu
  item is the explicit authorization to retransmit the unchanged current
  selection. This removes a real contradiction.
- Add an explicit requirement or acceptance criterion for the design's full
  menu recovery path: a separator plus `Configure...` item opens the existing
  full dialog for language changes and broader setup. The current design calls
  for conditional footer Configure only, while both `screen-result.html:105-109`
  and `screen-menu.html:143-148` show it in the switcher menu.
- Add a visual acceptance condition: compact provider control then read-only
  target label in every state, and `Choose Engine` when the saved value is
  invalid. This pins the observable design rather than merely requiring an
  unspecified menu.

### Technical design

- Replace the vague "themed `VirtButton`" statement with an `HBox` header
  ownership description: `btnEngine`, target label, and any existing close
  behavior must be independently relaid out and DPI-font updated. The current
  DPI list only contains `header`, status, and footer controls
  (`src/SelectionTranslate.cpp:1674-1685`).
- Specify an internal menu-item ID mapping rather than command IDs. No command
  generator update is needed.
- Add the `TrackPopupMenu` dismiss-click rule and menu destruction to the
  lifecycle section. This is a native correctness requirement absent from the
  original plan.
- Resolve the placement anchor from the engine button rectangle in screen
  coordinates, but let the system menu choose a safe opening direction. Do not
  assume it always fits below the button as the HTML does.

### Implementation and check plan

- Insert a test-first assertion that `dump` exposes `switcher=1`, current
  `engine`, and a `Choose Engine` label for invalid saved settings. Extend the
  deterministic control action with `switch <display-name>` that invokes the
  production transition boundary without starting a live CLI process.
- Test a distinct choice for persisted exact engine, incremented request ID,
  Loading state, and rejection of the old completion; test same-engine and menu
  cancellation as no-ops. Do not automate `TrackPopupMenu` or assert that all
  four engines exist on a developer machine.
- Add a focused inspection of menu filtering and Configure dispatch to the
  check matrix. The existing test's `header=` expectation needs replacement;
  it currently expects the old passive string
  (`tests/selection-translate-popup.ts:146-168`).
- Keep provider availability deterministic in the test harness. Production menu
  contents must reflect installed CLIs; the test must not depend on any locally
  installed executable.

## Risks and Caveats

- The reference contains mixed English and Chinese explanatory labels. Only
  product strings should be added through the project's translation mechanism;
  prototype annotations such as `AC9`, `Persisted`, and `SWP_NOACTIVATE` are not
  end-user copy.
- The reference calls the behavior "silent" persistence/retranslation. Native
  implementation should still visibly enter Loading and must retain no sensitive
  selection text in logs.
- The HTML's iconography, top-right close control, active-row color strip,
  animations, and extra footer status are presentation concepts, not a native
  implementation specification. Native theme compatibility and keyboard behavior
  take priority.
- No external research was needed. The entire evidence set is local and current
  as of the date above.
