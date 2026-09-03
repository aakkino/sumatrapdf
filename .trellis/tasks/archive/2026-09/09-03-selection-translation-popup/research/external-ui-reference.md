# External UI reference review

- Source: `D:/desktop_directory/selection-translation-popup`
- Reviewed: `screen-toolbar.html`, `screen-loading.html`, `screen-result.html`,
  `screen-error.html`, and rendered 1440x900 screenshots
- Date: 2026-09-03

## Usable reference

- Treat the prototype as visual intent, not reusable frontend code. The target is
  native Win32 and the HTML depends on Tailwind CDN, Google Fonts, Material Symbols,
  web backdrop blur, and a fictional DocTranslate application shell.
- The result state's compact 360 CSS-pixel composition is a useful hierarchy:
  provider/language header, bounded result body, and footer actions. Translate the
  dimensions to DPI-scaled native constraints rather than copying CSS values.
- The 320 CSS-pixel error state clearly separates the error heading, short message,
  secondary Close action, and primary Configure action. Reuse this information
  priority with SumatraPDF theme colors and controls.
- The toolbar state confirms the intended spatial sequence from selection to action
  to result. Keep SumatraPDF's existing toolbar geometry, icons, theme, and command
  layout rather than reproducing the mock toolbar.

## Do not carry into implementation

- Do not embed HTML, Tailwind, remote fonts/icons, the web application shell, or its
  branding.
- Do not add the result state's `Source / Result` switch. It conflicts with the
  approved lightweight popup scope and exposes source text without adding a needed
  action.
- Do not hard-code the loading state's `Google Translate` label. Quick translation
  accepts only the remembered installed AI CLI.
- Do not require acrylic blur. Use the existing SumatraPDF light/dark theme and a
  normal native popup surface; transparency must not reduce text contrast.
- Do not duplicate Close in both the header and footer. Use one clear Close control
  plus Escape.
- Do not treat the HTML buttons as interaction evidence. They have no event logic,
  keyboard contract, ARIA annotations, focus behavior, scrolling proof, or async
  lifecycle.

## Defects observed

- `screen-loading.html` did not render its popup in the captured viewport even
  though the markup contains one; its anchor markup is malformed around a paragraph.
- State pages use inconsistent providers: Antigravity in result and Google in
  loading.
- The four files repeat a large, unrelated document-reader shell and token block,
  making cross-state visual drift likely.
- The prototype does not demonstrate dark mode, high DPI, monitor clamping, long
  result scrolling, selection changes, tab changes, or late completion.

## Implementation guidance

Use the prototype only for header/body/footer proportions, restrained border and
shadow, action priority, and loading/result/error visual distinction. The PRD and
native SumatraPDF patterns remain authoritative for behavior, accessibility,
theming, provider identity, focus, placement, sizing, and lifecycle.
