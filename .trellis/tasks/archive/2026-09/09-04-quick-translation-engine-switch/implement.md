# Implementation Plan

## Contract

```json
{
  "schemaVersion": 1,
  "forbiddenVerification": ["test", "lint", "typecheck", "build"],
  "units": [
    {
      "id": "quick-translation-engine-switch",
      "dependsOn": [],
      "ownedPaths": [
        "src/SelectionTranslate.cpp",
        "tests/selection-translate-popup.ts",
        "[.]trellis/spec/frontend/selection-translation-popup.md"
      ],
      "actions": [
        "Add deterministic failing coverage before implementation.",
        "Adapt the approved v2 UI hierarchy to the native popup.",
        "Add the AI-only provider menu, Configure item, and engine-switch state transition.",
        "Persist the chosen engine and reject superseded completions.",
        "Update the focused test and executable frontend spec."
      ],
      "forbiddenPaths": ["ext/**", "cmd/gen-settings.ts", "src/Settings.h"],
      "allowedGenerators": ["bun cmd/format.ts -ts", "clang-format.exe", "bunx prettier --write"],
      "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4", "AC5", "AC6", "AC7", "AC8", "AC9", "AC10"],
      "stopConditions": [
        "The change requires new settings, command IDs, provider protocols, CLI installation, or language switching.",
        "A required edit falls outside ownedPaths."
      ]
    }
  ]
}
```

## Scope

One implementation unit owns the popup behavior, its deterministic test, and the
matching executable spec:

- `src/SelectionTranslate.cpp`
- `tests/selection-translate-popup.ts`
- `.trellis/spec/frontend/selection-translation-popup.md`

Stop if the change requires new settings, command IDs, provider protocols, CLI
installation, language switching, or edits outside this scope.

## Steps

1. Read `research/ui-design-reference.md` and use the current root-level v2
   reference, especially `screen-menu.html`, `screen-result.html`, and
   `screen-result.png`, as visual intent rather than reusable web code.
2. Extend `tests/selection-translate-popup.ts` and the debug-control expectations
   first; run it against the unchanged implementation and record the expected
   failure.
3. Reuse the existing AI-engine availability and display-name helpers to collect
   menu candidates; do not duplicate provider rules.
4. Replace the passive provider header with the approved `btnEngine` plus
   target-language hierarchy and anchor a checked native menu to the button. Add a
   separated `Configure...` item, local ID mapping, menu cleanup, and dismiss-click
   handling.
5. Add the single engine-switch transition: validate current selection, ignore the
   active engine, persist a different engine, update backend, and restart with a
   new request ID.
6. Extend the debug-control probe with deterministic switch visibility, engine,
   persistence, same-engine, restart, and stale-completion evidence without a live
   AI call. Replace the obsolete passive-header assertions.
7. Update the frontend popup spec to document the revised UI, menu recovery,
   filtering, persistence, retransmission, and request invalidation contracts.
8. Format the touched C++/TypeScript/Markdown files, build once, and run only the
   targeted popup test.

## Validation Plan

Run `bun cmd/format.ts -ts`, format `src/SelectionTranslate.cpp` with
`clang-format.exe -i -style=file`, and format the changed spec with Prettier.
Then run `bun cmd/build.ts -debug`,
`bun tests/selection-translate-popup.ts --no-build`, and `git diff --check`.

Review `RunTranslation()` logging and the popup completion guard after the diff;
the change must not weaken privacy or stale-result handling. Inspect native menu
filtering, local ID mapping, cleanup, dismiss-click behavior, and Configure
dispatch because automated tests do not depend on installed CLIs.

## Rollback Points

- The provider-button layout and menu are one reversible UI block.
- The transition reuses existing request IDs; do not add process cancellation.
- The debug-control extension and test must land together.
- The spec update must land with the code because it reverses an existing explicit
  prohibition.
