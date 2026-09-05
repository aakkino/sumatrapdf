# Research: UI history and visual specification

- Query: Recover prior popup research and external visual references; identify
  which concrete visual and interaction ideas remain usable after replacing
  translation AI CLIs with HTTP API providers and turning the full dialog into
  configuration only.
- Scope: internal
- Date: 2026-09-04

## Evidence Inventory

| Source                       | Evidence                                                                                                     | Authority now                                                   |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| Archived 09-03 task          | `archive/2026-09/09-03-selection-translation-popup/`                                                         | Historical implementation and lifecycle contract                |
| Archived 09-04 task          | `archive/2026-09/09-04-quick-translation-engine-switch/`                                                     | Historical AI-CLI switcher decision only                        |
| Current popup implementation | `src/SelectionTranslate.cpp:1404-2034`                                                                       | Current native capability baseline                              |
| Current full dialog          | `src/SelectionTranslate.cpp:1184-1352`                                                                       | Configuration-surface migration baseline                        |
| Current toolbar              | `src/SelectionToolbar.cpp:79-120,719-801`                                                                    | Current quick-action placement and routing                      |
| Existing popup spec          | `.trellis/spec/frontend/selection-translation-popup.md:1-99`                                                 | Must be revised before implementation; it still mandates AI CLI |
| External v2 prototype        | `D:/desktop_directory/selection-translation-popup/`                                                          | Visual reference only; no production-code authority             |
| Current task                 | `prd.md:34-105`                                                                                              | New product requirements and acceptance authority               |
| Session memory               | `trellis mem` session `01a065ab-9ad6-7780-9ad4-f90028f8e331`; session `01a06b27-6e2b-7480-9b0f-0f66a9e0ef94` | Confirms the evolution and the new product decisions            |

## History and Decisions

1. The 09-03 task introduced a non-modal popup adjacent to a fixed-page text
   selection. Its approved states were Loading, Result, and Error, with Copy,
   Close, Configure, selection-relative placement, DPI adaptation, and stale
   completion rejection. See archived `prd.md` and `design.md`, and the current
   implementation at `src/SelectionTranslate.cpp:1618-1698,1782-1901`.
2. The v1 external prototype used a static provider-to-target header. The 09-03
   external-reference review approved only compact header/body/footer hierarchy,
   restrained border/shadow, and error action priority; it explicitly rejected
   the web shell, Tailwind, remote fonts/icons, blur, the Source/Result switch,
   hard-coded Google identity, and duplicate Close controls. See
   `archive/2026-09/09-03-selection-translation-popup/research/external-ui-reference.md`.
3. The 09-04 follow-up made the header provider label an AI-CLI switcher. The
   v2 prototype declares that evolution at
   `D:/desktop_directory/selection-translation-popup/README.md:34-46`; its
   corresponding archived research maps that intent to `VirtButton` and
   `TrackPopupMenu`.
4. The current product decision supersedes the AI-CLI design: selection
   translation must call only configured HTTP providers (OpenAI-compatible,
   Google Cloud Translation, Microsoft Translator), must not launch an AI CLI,
   and the full dialog becomes configuration-only. See current `prd.md:40-66`.
   AI Chat retains its CLI behavior.

## Current Native Capability

The core popup hierarchy is already native and close to the intended compact
layout:

```text
WS_POPUP
  header: provider button | -> target language
  body:   status OR read-only, scrollable result edit
  footer: Copy | Configure (when required) | Close
```

- `SelectionTranslatePopupWnd` owns this state and controls at
  `src/SelectionTranslate.cpp:1436-1474`.
- `SetState()` updates provider/target, status/result visibility, Copy, and
  Configure at `src/SelectionTranslate.cpp:1661-1698`.
- `Create()` constructs the `HBox` header, multiline native result control, and
  themed footer at `src/SelectionTranslate.cpp:1816-1869`.
- The current provider menu is a real checked `TrackPopupMenu`, anchored to the
  provider button, at `src/SelectionTranslate.cpp:1706-1753`. It already
  destroys the menu and consumes its dismissing click.
- Placement above/below the selection, monitor clamping, no-activate initial
  show, and re-layout are already implemented at
  `src/SelectionTranslate.cpp:1626-1659`. Selection-toolbar update/move paths
  call the popup repositioning hooks at `src/SelectionToolbar.cpp:719-801`.
- The full dialog already has a Win32 `WindowBase` with vertical rows, native
  edits/drop-downs, themed buttons, keyboard focus, resizable layout, and theme
  update. Its existing structure is at `src/SelectionTranslate.cpp:1184-1352`.

## Concrete Prototype Elements

| Element                                                               | Exact reference                                                                                  | Prior status                                                | New-scope disposition                                                                                                                                                             |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Selection toolbar leading to a popup                                  | `screen-toolbar.html:43-85`; v2 README                                                           | Accepted, and implemented                                   | Keep. Change command semantics per `prd.md:59-66`; no toolbar visual redesign is required.                                                                                        |
| Compact header: provider control then `-> target language`            | `screen-result.html:73-115`; `screen-menu.html:88-155`                                           | Accepted and implemented                                    | Keep. Rename its meaning from AI engine to API provider. Current native HBox already matches it.                                                                                  |
| Provider chooser menu                                                 | `screen-result.html:83-110`; `screen-menu.html:100-150`                                          | Accepted only as a checked native menu                      | Keep the menu mechanism, but list configured HTTP providers only. Remove AI-only heading/list, CLI names, provider glyphs, and “installed” condition.                             |
| Checked current provider and same-provider no-op                      | `screen-result.html:178-212`; `screen-menu.html:134-141,169-170`                                 | Accepted for AI CLI                                         | Keep interaction semantics. The check indicates active configured provider; selecting it must not resubmit text.                                                                  |
| Switcher remains available in Loading, Result, and Error              | `screen-loading.html:67-96`; `screen-error.html:66-85`                                           | Accepted and implemented                                    | Keep, subject to missing-provider policy. A picker may offer only configured and complete providers; Configure remains the recovery route.                                        |
| Loading state                                                         | `screen-loading.html:89-107`                                                                     | State accepted; web spinner/status annotations not accepted | Keep clear native status. A real native progress control is available in `src/gui/win/Progress.cpp:26`, but current popup uses status text. Animated CSS spinner is not reusable. |
| Scrollable selectable result area                                     | `screen-result.html:122-133`; baseline image                                                     | Accepted and implemented                                    | Keep. Current read-only multiline Edit provides selection and scrolling at `src/SelectionTranslate.cpp:1835-1847`.                                                                |
| Copy and Close footer                                                 | `screen-result.html:135-143`; baseline image                                                     | Accepted and implemented                                    | Keep as Copy and Close. Do not replace Close with ambiguous “Done” unless product behavior changes.                                                                               |
| Error hierarchy: heading, brief explanation, primary Configure        | `screen-error.html:88-115`                                                                       | Error state/action priority accepted                        | Keep the hierarchy, rewritten for incomplete HTTP provider configuration. Do not mention missing AI CLIs or auto-submission.                                                      |
| Configure entry in chooser menu                                       | `screen-result.html:105-109`; `screen-menu.html:143-148`                                         | Accepted in v2                                              | Keep, but route to `CmdConfigureTranslation` / configuration-only surface.                                                                                                        |
| Top-right close icon                                                  | `screen-menu.html:157-159`; `screen-loading.html:82-85`; `screen-error.html:81-85`               | Rejected by 09-03 external review                           | Do not adopt. It duplicates the tested footer Close and expands focus/accessibility work without a product need.                                                                  |
| Source/Result switching                                               | v1 reference, rejected in archived `external-ui-reference.md`                                    | Rejected                                                    | Do not adopt. New configuration-only dialog must never render selected source text (`prd.md:75-77`).                                                                              |
| “Persisted”, “Saved & updated”, `SWP_NOACTIVATE`, AC labels           | `screen-result.html:117-119,204-212`; `screen-loading.html:98-107`; `screen-error.html:103-105`  | Prototype annotations only                                  | Do not ship. They reveal implementation details or duplicate feedback the popup state already conveys.                                                                            |
| Rounded translucent card, acrylic blur, web shadow, fixed CSS widths  | `screen-result.html:71`; `screen-menu.html:86`; `screen-loading.html:65`; `screen-error.html:64` | Explicitly rejected as implementation target                | Do not copy. Use existing themed, opaque native popup and DPI/content sizing.                                                                                                     |
| Full document-reader web shell, Tailwind, Google/Material fonts/icons | Every prototype HTML page, e.g. `screen-result.html:1-70`                                        | Explicitly rejected                                         | Cannot be reused in the Win32 app. It is unrelated to the popup and adds remote/runtime dependencies.                                                                             |

## Feasibility Matrix

| Proposal                                                                                         | Feasible in this task                               | Evidence and limits                                                                                                                                                                                                                                                                    |
| ------------------------------------------------------------------------------------------------ | --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Native compact popup with a provider selector, target label, result, and footer                  | Yes                                                 | Mostly exists today at `src/SelectionTranslate.cpp:1816-1869`. Replace the AI-engine data source and strings only after adding provider configuration.                                                                                                                                 |
| Native checked provider menu with Configure                                                      | Yes                                                 | Existing `TrackPopupMenu` implementation at `src/SelectionTranslate.cpp:1706-1753`; adapt item mapping to HTTP provider IDs and configuration completeness.                                                                                                                            |
| Asynchronous Loading/Result/Error style and stale-response protection                            | Yes                                                 | State transitions exist at `src/SelectionTranslate.cpp:1661-1698,1876-1950`; HTTP completion must use the same request/tab/selection validation.                                                                                                                                       |
| Provider menu selection that persists and retranslates unchanged selection                       | Yes                                                 | Existing switch path proves this behavior. The implementation must not reuse `TranslateEngine` or call `RunTranslation()` because both are AI-CLI-centric.                                                                                                                             |
| Light/dark theme, high DPI, keyboard, selectable/scrollable result                               | Yes                                                 | Existing `UpdateTheme`, DPI path, `VirtButton`, and native Edit supply them at `src/SelectionTranslate.cpp:1765-1779,1835-1847`; verify all new controls are included in DPI/theme updates.                                                                                            |
| Configuration-only window with provider list and provider-specific fields                        | Yes, but it needs a new native layout specification | Current dialog already has rows of `DropDown`, `Edit`, `HBox`, `VBox`, and themed buttons at `src/SelectionTranslate.cpp:1202-1348`. No external prototype defines this configuration view, so “left provider list / right fields” is a new product design, not a recovered reference. |
| Web prototype reproduced pixel-for-pixel                                                         | No, not within the native implementation contract   | CSS blur, remote fonts/icons, browser shell, responsive canvas, and CSS animation are not Win32 controls. Recreating it would require a separate custom-drawing/composition project and would conflict with native theme/DPI/accessibility requirements.                               |
| AI-CLI provider names, “Installed AI CLIs” menu header, CLI error wording, and CLI retranslation | No                                                  | Directly conflicts with `prd.md:44-45,55-57,97-100`; these belong to retained AI Chat only.                                                                                                                                                                                            |
| Google/DeepL browser links or their visual identity                                              | No                                                  | Google/DeepL browser engines are explicitly removed by `prd.md:14-16,55-56,95-96`. Google Cloud is a distinct configured API provider, not the old browser integration.                                                                                                                |
| Error/Configure content that displays a secret or raw provider response                          | No                                                  | Violates `prd.md:48-53,86-90`. Use a general actionable configuration failure and never echo API key, endpoint credentials, or raw response bodies.                                                                                                                                    |
| Manual source text editing, manual Translate, or result pane in configuration window             | No                                                  | Violates configuration-only requirement `prd.md:36-39,75-77`.                                                                                                                                                                                                                          |

## Recommended Native Visual Contract

For the popup, retain the baseline's dense rectangle and native controls rather
than the mock's card treatment. The visible hierarchy should be:

```text
[ Provider v ]  -> Target language

[ Translated result, or loading/error message             ]

                          [Copy] [Configure] [Close]
```

`Configure` is conditional for incomplete configuration or can remain in the
provider menu. In all cases it opens the separate configuration-only command.
The provider button lists only configured, complete API providers in stable
product order: OpenAI-compatible, Google Cloud Translation, Microsoft
Translator. Whether incomplete providers appear as disabled rows or are omitted
is still a user-owned UX decision; the old “installed CLI” rule cannot answer
it.

For the configuration window, a native two-column configuration layout is
implementable and appropriate: left provider selector; right provider-specific
fields; source/target language settings; a plain-text secret warning; Save and
Cancel. Keep it a conventional Win32 dialog, without selected document text,
translation result, or a network “Translate” action. There is no concrete
external configuration-screen design to replicate, so this is a newly required
design artifact before planning can converge.

## Caveats / Not Found

- The external project has no configuration-only screen. It cannot settle the
  required configuration-window visual target.
- The v2 prototype is internally inconsistent with the new direction: it uses
  four AI CLI names, `TranslateEngine` persistence, and CLI-specific loading and
  errors. Its layout hierarchy is reusable; its provider semantics are not.
- `screen-loading.html` is a visual mock only. The archived 09-03 review found
  malformed anchor markup in an earlier version and none of the HTML proves
  native focus, keyboard, monitor clamping, long-result scrolling, or stale
  completion behavior.
- The current frontend spec is stale for this task: it requires an installed AI
  CLI and forbids popup provider editing at
  `.trellis/spec/frontend/selection-translation-popup.md:10-47`. It must be
  updated as part of implementation planning, after the new provider-picker
  behavior is chosen.
