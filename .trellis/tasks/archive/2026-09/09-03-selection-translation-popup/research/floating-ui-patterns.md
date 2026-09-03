# Research: floating UI patterns

- Query: Which existing Win32 UI primitives can implement a contextual translate
  action and a dismissible translation-result surface near document text?
- Scope: internal
- Date: 2026-09-03

## Findings

### Current feature inventory

The repository already contains the requested interaction's two major pieces.
`SelectionToolbar.cpp` registers `CmdTranslateSelection` as an icon action
alongside copy/read-aloud/markup (`src/SelectionToolbar.cpp:78-89`). The toolbar
is shown after a finished selection (`src/Selection.cpp:1004-1014`), waits 500
ms for it to settle (`src/Canvas.h:44-45`, `src/SelectionToolbar.cpp:705-733`),
and only appears for an on-screen non-empty fixed-page text selection
(`src/SelectionToolbar.cpp:664-701`). Its command posts through the ordinary
frame command path (`src/SelectionToolbar.cpp:375-397`).

`ShowSelectionTranslateDialog()` reads the selected text and opens a window;
it guards for selection and Copy permission (`src/SelectionTranslate.cpp:1346-
1366`). It supports ordinary text and rectangular-region extraction through
`GetSelectedTextTemp()` (`src/Selection.cpp:611-649`), but image collections
return no text (`src/Selection.cpp:623-625`). Translation commands are disabled
without selection and removed when Copy permission is unavailable
(`src/CommandAvailability.cpp:99-115`, `src/CommandAvailability.cpp:166-184`).

### Candidate action surface: existing SelectionToolbar (recommended)

`SelectionToolbar` is the correct contextual action primitive. It is a cached
`VirtHost` `WS_POPUP`, placed in screen coordinates above the selection with a
below-selection fallback and canvas clamping (`src/SelectionToolbar.cpp:516-
550`). It has `WS_EX_NOACTIVATE` and returns `MA_NOACTIVATE`, retaining canvas
focus and keyboard shortcuts while receiving mouse clicks (`src/SelectionToolbar.cpp:552-
576`, `src/gui/VirtHost_win.cpp:86-100`, `src/gui/VirtHost_win.cpp:154-182`).
Buttons use theme colors and tooltips (`src/SelectionToolbar.cpp:401-456`) and
are configurable through `SelectionToolbarLayout` (`src/SelectionToolbar.cpp:103-
151`, `docs/md/Advanced-options-settings.md:360-370`).

It survives scrolling/tab/frame movement correctly: it hides while a drag is in
progress, hides when its selection leaves view or changes tab, repositions on
paint and on frame moves, and clears hover/pressed state when hidden
(`src/SelectionToolbar.cpp:747-850`). Existing focused tests cover the layout
and translation action presence (`tests/issue-6048.ts:28-75`), selection
persistence after Copy (`tests/selection-toolbar-stays.ts:111-188`), and popup
movement with the frame (`tests/selection-toolbar-move.ts:81-176`).

### Candidate result surface: current SelectionTranslateWnd

The existing result surface is a custom, resizable top-level dialog. It is
created as `WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_THICKFRAME`, starts
hidden, lays itself out and centers on the owner (`src/SelectionTranslate.cpp:
1175-1189`, `src/SelectionTranslate.cpp:973-989`). The window has source text,
engine and language controls, a result edit control, Close and Translate
buttons (`src/SelectionTranslate.cpp:1197-1338`). Result/error content is made
visible in the same window (`src/SelectionTranslate.cpp:1020-1035`,
`src/SelectionTranslate.cpp:1110-1118`).

This is the best existing starting point when language/provider editing is in
scope, but it is not a lightweight floating result: it disables the owner and
restores/focuses it when closed (`src/SelectionTranslate.cpp:1149-1160`,
`src/SelectionTranslate.cpp:1368-1391`). It is centered, rather than anchored
to the selected range. Escape and Ctrl+W are enabled for dismissal
(`src/SelectionTranslate.cpp:1371-1382`); the reusable WindowBase message path
also handles mixed native/virtual focus, close, and DPI notifications
(`src/gui/win/WindowBase.cpp:987-1008`, `src/gui/win/WindowBase.cpp:1093-1106`,
`src/gui/win/WindowBase.cpp:1397-1418`). `tests/issue-5934.ts:94-133` verifies
that Escape closes this dialog.

It handles an in-flight request safely: the background task keeps only HWND,
posts completion to the UI task queue, and ignores a completion whose dialog
has been closed (`src/SelectionTranslate.cpp:145-168`, `src/SelectionTranslate.cpp:
1125-1147`). This lifetime pattern must be retained by any replacement popup.

### Alternative result surface: non-activating VirtHost popup

`VirtHost` is the appropriate low-chrome implementation if the desired result
must remain beside the selection while the document stays interactive. It can
be a `WS_POPUP | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`, uses `SWP_NOACTIVATE`,
and can carry virtual controls (`src/gui/VirtHost_win.cpp:154-187`,
`src/gui/VirtHost_win.cpp:259-275`). The selection toolbar demonstrates
placement, theme integration, and reuse. A translation result with selectable
or editable text cannot remain purely non-activating: text selection, keyboard
navigation, language controls, and accessible focus require an explicit focus/
activation decision. Thus this option fits a read-only result with Copy/Close
buttons, not the current editable/provider configuration dialog.

`RefHoverPopup` demonstrates another anchored `WS_POPUP` placement algorithm:
it bounds against the target monitor work area, chooses above/below based on
space, clamps dimensions, and shows without activation (`src/RefHoverPopup.cpp:
133-145`, `src/RefHoverPopup.cpp:148-219`). It is custom-painted and does not
provide keyboard focus, theming, automatic DPI-message handling, or a general
dismissal policy, so it should not be copied as the full translation UI.

### Notifications are not suitable as the primary result UI

Notifications have close buttons, timeout/group ownership, theme-aware
virtual content, and tab-aware hiding (`src/Notifications.cpp:479-602`,
`src/Notifications.cpp:787-819`, `src/Notifications.cpp:901-940`). They are
anchored to the parent rather than the selection and are intended for transient
status; use them only for a brief launch/error status, not translation text.
Server-provided translation text must use the plain-text route to prevent rich
command-link injection (`src/Notifications.cpp:859-884`).

### DPI, theme, accessibility, and RTL

The action toolbar scales every placement/padding dimension through `DpiScale`
and regenerates icons/layout (`src/SelectionToolbar.cpp:401-415`,
`src/SelectionToolbar.cpp:516-548`). The dialog receives `WM_DPICHANGED`,
applies Windows' suggested rectangle, updates fonts, relayouts, and repaints
(`src/SelectionTranslate.cpp:931-970`). The dialog creates RTL-aware text and
drop-down controls (`src/SelectionTranslate.cpp:1175-1177`, `src/SelectionTranslate.cpp:
1275-1315`); VirtHost also supports `WS_EX_LAYOUTRTL` (`src/gui/VirtHost_win.cpp:
164-171`). Existing toolbar icon buttons provide tooltips, but no repository
evidence in these paths establishes UI Automation exposure for a custom
translation popup; this needs a dedicated accessibility review and test.

## Recommendation

Keep `CmdTranslateSelection` in the existing selection toolbar as the action
surface. Decide between two distinct result contracts before implementation:

1. Preserve the current modal `SelectionTranslateWnd` when editing source,
   target, provider, and input text is part of the MVP. It already satisfies
   dismiss, DPI, theme, request lifetime, permission, and error-display needs,
   but deliberately interrupts reading and is not selection-anchored.
2. Build a new owner-associated `VirtHost` result popup only if the MVP requires
   an inline, non-modal reading flow. Give it a snapshot of selected text, a
   Close control, Copy result, an explicit outside-click/tab-change/selection-
   change dismissal policy, monitor/canvas-clamped placement, and safe
   cancellation-or-ignore behavior for an in-flight result. Do not disable the
   owner. Defer editable language/provider fields to the existing dialog or an
   explicit Settings path.

The first option is mostly an inventory/UX decision because the repository
already implements it. The second is a new product surface, not a small change
to a dialog's coordinates.

## Caveats / Not Found

- The current source tree already contains `SelectionTranslate.cpp`,
  `SelectionToolbar.cpp`, generated commands, settings, and tests that closely
  match the requested feature. This research does not determine whether those
  changes are released, intentionally staged, or local work in progress.
- No focused test was found for an inline translation-result popup, outside-
  click dismissal, tab/selection change during a translation request, monitor-
  boundary placement, keyboard traversal, screen-reader exposure, or high-DPI
  migration of the translate dialog.
- Provider/privacy/network behavior belongs to the provider research and must
  be decided independently of UI choice.
