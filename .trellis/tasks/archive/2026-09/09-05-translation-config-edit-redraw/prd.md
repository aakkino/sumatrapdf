# Fix native edit redraw on provider switch

## Goal

Restore native Edit frames after provider switching in the translation configuration window.

## Requirements

- R1: Switching Google -> OpenAI-compatible and OpenAI-compatible -> Microsoft
  must show every selected provider Edit control with its complete painted
  frame, not merely leave its HWND visible.
- R2: Restore the native child-control show/hide lifecycle at the shared
  `ControlBase` boundary. Do not add provider-specific redraw calls.
- R3: Add a deterministic ad-hoc visual regression check that fails when
  current provider Edit frames are absent after either switch.
- R4: Preserve native visibility, layout, focus, and theme behavior for other
  controls.

## Acceptance Criteria

- [ ] AC1: The selected provider's Edit HWNDs are visible and their four frame
      edges are painted after both provider-switch transitions.
- [ ] AC2: The visual assertion fails against the pre-fix visibility path.
- [ ] AC3: The fix is generic to child `ControlBase` visibility and leaves
      `TranslationConfigWnd::ProviderChanged()` provider-neutral.
- [ ] AC4: The focused ad-hoc frame test passes repeatedly after a Debug
      build, with no key or request content captured in test output.

## Notes

- The prior visibility-only test is insufficient: the failure is missing
  `WM_NCPAINT` frame rendering while HWND state and bounds are correct.
