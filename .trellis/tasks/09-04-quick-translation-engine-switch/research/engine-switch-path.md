# Engine switch path

## Evidence

- `SelectionTranslatePopupWnd` owns the popup engine, backend, selection snapshot,
  state, and request ID in `src/SelectionTranslate.cpp:1420-1460`.
- `Start()` assigns a new global request ID before every asynchronous launch;
  completion accepts only the matching live popup and request ID
  (`src/SelectionTranslate.cpp:1773-1811`). A switch can reuse this stale-result
  boundary without cancelling the old process.
- `EngineIsAI()` and `IsEngineAvailable()` already define the runnable quick-engine
  set. `gAllEngines` provides stable display ordering
  (`src/SelectionTranslate.cpp:739-807`).
- `MaybeSaveTranslatePrefs()` persists engine and language preferences through
  `ScheduleSaveSettings()` (`src/SelectionTranslate.cpp:308-330`). A narrow engine
  update should reuse the same normalization and scheduled-save path.
- The annotation editor already anchors a checked `TrackPopupMenu` to a virtual
  control and returns a local item index (`src/AnnotEditToolbar.cpp:1007-1025`,
  `src/AnnotEditToolbar.cpp:1269`). The quick popup can follow this pattern without
  adding a UI framework abstraction.
- The existing debug-control probe injects loading, result, and stale completion
  states without invoking a live provider (`src/SelectionTranslate.cpp:1904-1970`).
  It can be extended to exercise the engine transition deterministically.

## Recommended Shape

1. Replace the passive provider portion of the header with a themed virtual
   button. Keep the target language as adjacent read-only text.
2. Build a local menu from engines for which both `EngineIsAI()` and
   `IsEngineAvailable()` are true. Check the active engine, then add a separator
   and `Configure...` item that opens the full dialog.
3. Ignore menu cancellation and selection of the current engine.
4. Before switching, require `IsCurrentTranslatePopup()` and re-read the current
   selected text. Then update engine/backend, persist the engine, and call the
   existing request start path. Its new request ID rejects the old completion.
5. Keep the footer Configure action for the invalid-engine state. If no runnable
   AI CLI exists, the menu still provides `Configure...` as the recovery path.
6. Extend the debug-control state with engine/switch information and a test-only
   switch action that uses the same state transition without launching a real CLI.

## Risks

- `TrackPopupMenu` is synchronous. The popup object must remain live throughout
  menu selection and must use stable local IDs rather than generated command IDs.
- Reusing `MaybeSaveTranslatePrefs()` may rewrite unchanged language values. A
  narrow engine-save helper avoids coupling the switch to language persistence.
- A switch during Loading creates two live external processes. This is accepted:
  cancellation remains out of scope, and request-ID validation discards the old
  output.
- Automated tests must not depend on which CLIs happen to be installed on the
  developer or CI machine.
