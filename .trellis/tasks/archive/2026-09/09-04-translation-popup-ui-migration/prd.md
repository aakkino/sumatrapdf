# Migrate translation popup UI

## Goal

Make quick selection translation use the configured HTTP providers and deliver
the approved native visual refresh without regressing popup lifecycle behavior.

## Requirements

- R1: Replace translation AI CLI and browser-engine dispatch with the checked
  TranslationService; retain AI Chat CLI behavior outside translation.
- R2: Always list the three HTTP providers in the picker. Disable and mark
  incomplete providers `Not configured`; route Configure to the new command.
- R3: Preserve Loading/Result/Error, provider switching, Retry, Copy, Close,
  selection anchoring, focus, toolbar restoration, and stale-result rejection.
- R4: Apply compact native styling with small corners, dividers, repository-owned
  icons, lightweight shadow, and timer-driven loading indication, all with clean
  fallback.
- R5: Make both existing generic translation entry points invoke the quick
  popup. The parent integration unit owns generated command removal and final
  dispatch cleanup.
- R6: Remove Google/DeepL browser execution and translation references to AI CLI
  providers from `SelectionTranslate`; leave menus, generated commands, and
  documentation to parent integration.
- R7: Never expose keys, source text, prompts, raw provider bodies, or results in
  logs or test probes.
- R8: The popup's execution boundary requires `Perm::InternetAccess` for
  creation, switching, and retry. It must not start provider I/O when network
  access is unavailable, even through direct dispatch.

## Acceptance Criteria

- AC1: Both generic translation commands open the same popup for a valid
  selection; configuration opens independently through its command.
- AC2: A complete chosen provider sends one asynchronous request and displays its
  normalized result; no complete provider sends nothing and shows Configure.
- AC3: Switching provider and Retry create new request IDs; stale responses,
  changed selections, tab changes, and closed windows cannot update the popup.
- AC4: The picker exposes all three providers, correctly disables incomplete
  entries, checks the active provider, and treats the active choice as a no-op.
- AC5: Visual polish works in light/dark and normal/high DPI without changing
  focus, keyboard, RTL, placement, scrolling, selection, or dismissal behavior.
- AC6: Google/DeepL URL execution, manual-dialog translation, and four AI CLI
  execution paths are absent from `SelectionTranslate`; AI Chat code remains
  unchanged.
- AC7: Focused popup and compatibility tests pass without live providers.
- AC8: Without `Perm::InternetAccess`, no popup worker request can start and
  the selection toolbar remains unchanged.

## Out of Scope

- API adapters/settings, configuration UI, command generation and documentation,
  AI Chat changes, advanced translucent UI, general animation/UIA frameworks,
  and live-account tests.
