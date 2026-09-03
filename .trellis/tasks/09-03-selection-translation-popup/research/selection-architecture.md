# Research: selection architecture

- Query: Can selection completion expose a translate action and anchor a translation popup?
- Scope: internal
- Date: 2026-09-03

## Findings

### Existing user path

- This is not a greenfield feature. The fixed-page canvas already shows a delayed,
  focus-preserving floating selection toolbar. Its built-in buttons include
  `CmdTranslateSelection` with the translate SVG at `src/SelectionToolbar.cpp:80-89`.
- The command dispatcher calls `ShowSelectionTranslateDialog(tab,
TranslateEngine::Default)` at `src/SumatraPDF.cpp:12439-12441`. The toolbar posts
  its button command to the frame at `src/SelectionToolbar.cpp:498-521`.
- `ShowSelectionTranslateDialog()` extracts selected text, opens one modal dialog,
  and disables the document owner at `src/SelectionTranslate.cpp:1346-1391`.
  It already displays an async AI result in a read-only edit at
  `src/SelectionTranslate.cpp:1020-1041, 1043-1115`; Google and DeepL instead open
  their browser translators at `src/SelectionTranslate.cpp:1054-1065`.

### Selection lifecycle and text extraction

1. Canvas input decides whether a press starts a text selection or drag. It calls
   `OnSelectionStart()` only for the fixed-page view at
   `src/Canvas.cpp:2380-2462`.
2. `OnSelectionStart()` clears the old selection, converts canvas coordinates to
   page coordinates, then starts `DisplayModel::textSelection` at the nearest glyph
   (`src/Selection.cpp:924-954`; `src/TextSelection.cpp:337-355`).
3. Mouse movement updates the free glyph endpoint. `UpdateTextSelection()` converts
   the current canvas point to the target page, calls `SelectUpTo()`, materializes
   `SelectionOnPage` rectangles, and raises the UI Automation selection event
   (`src/Selection.cpp:580-607`).
4. On left-button release, Canvas calls `OnSelectionStop()` at
   `src/Canvas.cpp:2539-2545`. It finalizes text selection, schedules repaint, then
   schedules the selection toolbar (`src/Selection.cpp:957-1014`). This is the
   direct selection-complete hook.
5. `GetSelectedTextTemp()` is the shared extraction API. For a true text selection
   it delegates to `TextSelection::ExtractText()`; a rectangular selection extracts
   per-region text; image collections yield no text (`src/Selection.cpp:611-656`,
   `src/TextSelection.cpp:649-667`). It returns temp-arena storage, so an async
   request must duplicate the `Str` before returning to the message loop.

### Coordinates and anchor placement

- `DisplayModel::CvtFromScreen()` and `CvtToScreen()` transform between canvas
  pixels and page coordinates while accounting for page position, zoom, and rotation
  (`src/DisplayModel.cpp:1686-1813`; declarations `src/DisplayModel.h:198-202`).
- `SelectionOnPage` rectangles are document/page-space and become canvas rectangles
  through `sel.GetRect(dm)` (`src/Selection.cpp:167-201`).
- `GetSelectionScreenRect()` already unions selection rectangles and maps the
  canvas top-left to desktop coordinates, exactly matching an external popup-anchor
  contract (`src/Selection.cpp:167-201`).
- The current toolbar has an internal equivalent for visible fragments: intersects
  its union with `win->canvasRc`, places above then below, clamps to canvas, and
  maps via `HwndClientToScreen()` (`src/SelectionToolbar.cpp:569-650`). It repositions
  during canvas paint, frame moves, zoom, and scrolling (`src/Canvas.cpp:3881-3887`,
  `src/SelectionToolbar.cpp:750-806`).

### View and engine boundaries

- The selection pipeline is fixed-page only: `OnSelectionStart()`, painting, toolbar
  display, text extraction, and popup bounds all require `AsFixed()`
  (`src/Selection.cpp:503-607, 611-656, 924-954`; `src/SelectionToolbar.cpp:665-684`).
- `WindowTab` exposes separate `AsFixed()`, `AsChm()`, and `AsMarkdown()` views
  (`src/WindowTab.h:143-152`, `src/WindowTab.cpp:146-156`). CHM/Markdown implement
  their own Select All route, not this selection representation
  (`src/Selection.cpp:798-805`).
- Thus PDF/XPS/CBZ/e-book formats rendered by a fixed `DisplayModel` can share this
  path when their engine exposes glyph text. Image collections cannot translate from
  a selection without OCR because extraction returns empty (`src/Selection.cpp:623-625`).
- Translation also requires `Perm::CopySelection` (`src/SelectionTranslate.cpp:1346-1351`).
  Google/DeepL require `Perm::InternetAccess`; AI engines require the selected local
  backend to be installed (`src/SelectionTranslate.cpp:762-793`).

### Candidate extension points

1. Recommended MVP: retain `OnSelectionStop()` and the existing toolbar; the
   translate button is already present by default. Evolve
   `ShowSelectionTranslateDialog()` into a non-modal, selection-anchored result
   window, or introduce a sibling `SelectionTranslatePopup` used by the existing
   command. This preserves keyboard/context-menu/command-palette invocation and
   avoids duplicate completion handling.
2. Reuse toolbar placement mechanics or extract a shared internal helper. The
   translation popup needs the same visible-selection bounds, above/below fallback,
   clamp, `HwndClientToScreen`, and frame-move/paint reposition behavior. It should
   not depend only on the mouse-up point, which becomes stale after scrolling.
3. Keep the selection alive while a translation runs. The toolbar currently keeps
   selection for normal commands (`src/SelectionToolbar.cpp:498-514`), while
   `DeleteOldSelectionInfo()` hides it and resets text state
   (`src/Selection.cpp:110-124`). The popup needs a selection/tab identity check
   before applying an async result, similar to the existing HWND validation at
   `src/SelectionTranslate.cpp:1090-1100`.

### Existing verification support

- Tests already drive the dialog command in `tests/issue-5934.ts:107-115` and the
  toolbar layout/click protocol in `tests/issue-6048.ts:32-54` and
  `tests/selection-toolbar-stays.ts:124-128`.
- `SelectionToolbarLayoutDumpTemp()` and `SelectionToolbarClickTemp()` provide
  `-dbg-control` hooks (`src/SelectionToolbar.cpp:616-663`), but there is no
  equivalent translation-popup state/result probe found in this exploration.

## Caveats / Not Found

- The current translation dialog is explicitly modal (`EnableWindow(hwndOwner,
FALSE)`), fixed-size-to-content/resizable, and globally singleton. Replacing it
  with an anchored popup changes focus, close, and concurrent-request semantics;
  this needs a product decision.
- A single union bounding box can be large or span pages. The toolbar intentionally
  uses only visible fragments; the translation popup should follow that policy or
  define a different anchor for multi-page selections.
- No built-in HTTP translation-result provider was found for Google/DeepL: those
  engines launch a browser. Inline results therefore require an installed AI backend,
  a new network-backed provider, or a clearly scoped fallback UX.
- No selection translation path was found for CHM or Markdown/WebView2 content.
