# Technical Design

## Architecture

Keep engine switching inside `SelectionTranslate.cpp`, where provider discovery,
popup state, preference persistence, and asynchronous completion already live.

```text
provider button
  -> checked menu of runnable AI CLIs
  -> validate live popup and unchanged selection
  -> persist selected engine
  -> assign engine/backend
  -> Start(current selected text)
  -> new request ID invalidates old completion
```

No command, settings schema, document engine, provider protocol, or public header
change is required.

## UI Contract

- Replace the passive provider label with an `HBox` containing a themed
  `VirtButton` named `btnEngine` and a read-only target-language label. Both are
  relaid out and receive DPI font updates independently.
- The button text is the active provider, or a localized choose-engine label when
  the saved engine is invalid. It remains visible in every popup state.
- Clicking it opens a native menu anchored to the button's screen rectangle. The
  menu lists only runnable AI CLI engines in existing `gAllEngines` order, checks
  the active engine, then adds a separator and `Configure...`. Let Windows choose
  the safe opening direction rather than assuming the menu fits below.
- Menu cancellation and choosing the current engine change nothing.
- Keep Copy, Close, and the conditional footer Configure action. The menu's
  `Configure...` and the footer action both open the full dialog for language
  changes, installation recovery, and broader setup.
- Initial popup display remains non-activating. Once the user activates the popup,
  the provider button and native menu support normal keyboard and mouse operation.

## Lifecycle and State

- Add one transition owner for engine changes. It first validates the popup/tab/
  selection identity and obtains the still-current selected text.
- On a different valid engine, update `engine` and `backend`, persist only the
  engine preference through the existing scheduled settings-save mechanism, and
  invoke the existing start path.
- `Start()` assigns a monotonically increasing request ID and sets Loading before
  launching. Any prior completion fails the existing HWND/request/selection checks.
- If the selection became invalid, close the popup without starting or saving a
  provider request.
- If no runnable AI CLI is present, show no provider menu item and retain the
  invalid-engine Configure state; the menu still offers `Configure...`. Never fall
  back to Google or DeepL.
- Assign local menu IDs to a temporary engine vector instead of using generated
  command IDs. Destroy the native menu on every return path.
- `TrackPopupMenu` runs a nested message loop. After it closes, consume only the
  dismissing click that landed on `btnEngine`, following the existing annotation
  chip precedent, so the menu does not immediately reopen.

## Test Contract

- Extend `SelectionTranslatePopupTestTemp()` rather than automating a live menu or
  provider process. The probe must expose `switcher`, active `engine`, provider
  label, target language, and request identity.
- Add a deterministic switch action that drives the same transition boundary in a
  no-provider-run test mode, allowing assertions for persistence, Loading state,
  request replacement, same-engine no-op, and stale-result rejection.
- Keep the test appdata isolated under `tests/tmp/`; do not depend on globally
  installed CLIs or modify user settings.
- Replace existing passive `header=` assertions. Inspect menu filtering and
  Configure dispatch in code because installed-engine contents are intentionally
  machine-dependent.

## Compatibility and Ownership

- Existing saved `TranslateEngine` values remain valid and no migration is needed.
- The full translation dialog and custom toolbar command semantics do not change.
- Update `.trellis/spec/frontend/selection-translation-popup.md` to replace the old
  prohibition on popup provider editing with this narrow AI-only switch contract.
- Use `research/ui-design-reference.md` as the visual source of truth for the
  provider-control hierarchy and states. Adapt it to native theme, font, DPI,
  placement, and accessibility; do not copy its HTML/CSS, web icons, animation,
  fixed pixel widths, top-right close glyph, or extra footer status.
- Rollback removes the provider button/menu and test probe additions, restores the
  passive header, and reverts the spec section. No settings data must be removed.
