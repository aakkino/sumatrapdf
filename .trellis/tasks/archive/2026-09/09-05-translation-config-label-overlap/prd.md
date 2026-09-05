# Fix translation provider label overlap

## Goal

Prevent collapsed provider groups from painting overlapping virtual labels in the translation configuration window.

## Requirements

- R1: A collapsed virtual-layout subtree must not paint any descendant virtual
  controls.
- R2: Switching translation providers must show only the selected provider's
  title, labels, and native fields.
- R3: Repeated provider switching must not retain stale text or bounds.
- R4: Preserve existing layout sizing, native control visibility, DPI scaling,
  RTL ordering, focus, and keyboard behavior.
- R5: Add the regression test before the fix and confirm it fails without the
  fix.

## Acceptance Criteria

- AC1: A focused test proves descendants of a collapsed layout container are
  absent from the virtual paint list.
- AC2: OpenAI-compatible, Google, and Microsoft can be switched repeatedly
  without overlapping titles or labels.
- AC3: The focused test fails when the fix is reverted and passes with it.
- AC4: The debug build and relevant translation configuration test pass.
- AC5: Normal/high DPI and LTR/RTL behavior remain correct.

## Out of Scope

- Provider-specific label hiding in `TranslationConfig`.
- Translation transport, settings, popup behavior, and unrelated virtual
  control refactoring.

## Evidence

- Repro screenshot: parent task `20260905-110348.png`.
- Investigation found collapsed groups are skipped by layout but their
  descendants are still collected for virtual painting.
