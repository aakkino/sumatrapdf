# Technical Design

## Architecture

`ControlBase::SetVisibility()` owns native child-window visibility. Its
implementation must use the Win32 show/hide lifecycle so controls that paint a
non-client frame receive the appropriate redraw. The translation configuration
window continues to express only which provider fields are visible.

## Lifecycle and State

Provider switching updates visibility, then relayouts. Re-showing an Edit must
paint both its client area and its hand-drawn non-client frame. The regression
test drives both affected transitions and samples the captured configuration
window rather than trusting wrapper visibility state.

## Compatibility and Ownership

Own `src/gui/win/WindowBase.cpp`; do not change provider data, field selection,
or Edit-specific paint code. The test is a new standalone ad-hoc configuration
capture test; extend `tests/winapi.ts` only if an existing capture helper cannot
inspect frame pixels. The change must remain compatible with native controls and
ordinary window layout.
