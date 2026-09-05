# Technical Design

## Architecture

Retain `SelectionTranslatePopupWnd` as the selection lifecycle owner. Replace its
engine/backend fields with provider ID/config snapshot and call only
`TranslationService` from its worker. Popup code receives normalized results and
does not construct URLs, headers, prompts, or parse JSON.

## Lifecycle and State

Keep one popup per main window and the existing request/tab/selection identity
guards. Provider switch and Retry explicitly authorize resending the unchanged
selection and invalidate the old request. Configure closes or leaves the popup
in an error state consistently, then opens the independent configuration window.

Custom visual timers/auxiliary shadow resources belong to the popup lifetime and
must stop before HWND destruction. Unsupported DWM/custom polish falls back to
the existing opaque bordered popup.

Land the provider and command migration as a coherent functional unit before
adding optional visual resources. This keeps the checked HTTP path usable if a
visual fallback or rollback is needed.

## Compatibility and Ownership

This child depends on checked API core and the configuration child's shared UI
contract, not on completion of the configuration window. It owns popup runtime,
focused tests, and the popup spec. The parent integration unit owns command
generation, dispatch cleanup, command docs, and next-version history.
