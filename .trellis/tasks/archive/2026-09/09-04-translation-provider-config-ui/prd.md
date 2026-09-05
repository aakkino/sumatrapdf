# Build translation provider configuration

## Goal

Give users a dedicated native window to configure and test the three selection
translation HTTP providers without requiring a document selection.

## Requirements

- R1: Add `CmdConfigureTranslation`, available without a selection.
- R2: Add a configuration-only window with no source text, Translate action, or
  result pane. The popup child removes the old manual dialog implementation and
  the parent integration unit completes generic command aliasing.
- R3: Use a resizable native layout with provider selection on the left and the
  selected provider's fields on the right, plus source/target language settings.
- R3a: Populate language controls from one read-only TranslationService catalog;
  source includes `Auto`, destination does not, and both persist canonical
  labels accepted by the service.
- R4: Provide Base URL/Model/API Key for OpenAI-compatible, API Key for Google,
  and Endpoint/Region/API Key for Microsoft.
- R5: Mask keys while editing, store them in plain text, and show a concise
  warning about local files, backup, and sync exposure.
- R6: Save validates the selected provider and both language choices, persists
  all edited provider fields plus the active provider and languages, and allows
  inactive providers to remain incomplete. Cancel leaves settings unchanged.
- R7: Test Connection warns about possible cost, sends fixed non-sensitive text
  asynchronously, and shows a redacted status without closing the window.
- R8: Follow native theme, DPI, RTL, keyboard, focus, and accessibility behavior.
- R9: Opening a new or existing configuration window focuses the provider
  selector even when Windows rejects foreground activation.
- R10: A DPI change updates labels and headings for every provider form,
  including forms currently collapsed by the provider selector.
- R11: Configuration remains available without Internet access, but Test
  Connection is disabled and cannot start provider I/O in that state.

## Acceptance Criteria

- AC1: The command opens without a document or selection and focuses a usable
  native configuration window.
- AC2: Provider switching shows only relevant fields and preserves unsaved edits
  during the current dialog session.
- AC3: Keys are masked, never echoed in status or probes, and the plain-text
  storage warning is visible.
- AC4: Invalid required fields prevent Save/Test and identify the field; valid
  Save persists all provider and language settings.
- AC4a: Provider and language controls use the service's stable provider order
  and canonical language labels without maintaining a second language table.
- AC5: Cancel and window close persist nothing.
- AC6: Test Connection uses the service contract, displays working/success/error
  states, ignores stale completion, and sends no selected document text.
- AC7: Focused deterministic tests cover provider switching, validation,
  Save/Cancel, masking, and injected connection-test completion.
- AC8: Initial open and singleton reopen both restore focus to the provider
  selector under cross-process test activation.
- AC9: After a DPI update, switching to any provider shows labels and headings
  using the current app font.
- AC10: Without `Perm::InternetAccess`, Test Connection is unavailable and a
  direct test seam cannot start an HTTP worker.

## Out of Scope

- Manual translation, translation result display, credential encryption, live
  provider tests, custom prompts, OAuth, and advanced translucent UI.
- Popup implementation, obsolete command removal, generic command aliasing, and
  AI Chat behavior.
