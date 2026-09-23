# Implementation Plan

## Contract

```json
{
  "schemaVersion": 1,
  "forbiddenVerification": ["test", "lint", "typecheck", "build"],
  "units": [
    {
      "id": "quick-translation-popup",
      "dependsOn": ["toolchain-source-compatibility"],
      "ownedPaths": [
        "cmd/gen-commands.ts",
        "src/Commands.cpp",
        "src/Commands.h",
        "src/CommandAvailability.cpp",
        "src/Selection.cpp",
        "src/Selection.h",
        "src/SelectionToolbar.cpp",
        "src/SelectionTranslate.cpp",
        "src/SelectionTranslate.h",
        "src/SumatraPDF.cpp",
        "src/SumatraControl.cpp",
        "tests/control.ts",
        "tests/selection-translate-popup.ts",
        "tests/selection-toolbar-move.ts",
        "tests/issue-6048.ts",
        "tests/run-almost-all.ts",
        "docs/md/Commands.md",
        "docs/md/Version-history.md"
      ],
      "actions": [
        "Add and generate the dedicated quick-translation command.",
        "Keep the quick command toolbar-only and aligned with Copy permission.",
        "Share visible-selection geometry and route the toolbar to the quick command.",
        "Implement the popup state, placement, focus, lifecycle, and safe async completion.",
        "Restrict quick provider resolution and remove sensitive translation payload logging.",
        "Add deterministic debug-control coverage and update focused tests and docs."
      ],
      "forbiddenPaths": ["ext/**", "src/mac/**", "src/linux/**"],
      "allowedGenerators": ["bun cmd/gen-code.ts", "bun cmd/format.ts"],
      "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4", "AC5", "AC6", "AC7", "AC8", "AC9", "AC10", "AC11", "AC12"],
      "stopConditions": [
        "A product decision is missing or the approved popup behavior must change.",
        "Implementation requires a direct HTTP provider, credential storage, OCR, or a new document selection model.",
        "A required edit falls outside ownedPaths."
      ]
    },
    {
      "id": "toolchain-source-compatibility",
      "dependsOn": [],
      "ownedPaths": [
        "src/base/Win.cpp",
        "src/base/Http_win.cpp"
      ],
      "actions": [
        "Include the MSVC intrinsic declarations used by x86/x64 CPU detection.",
        "Reuse the narrow WinHTTP declaration block on MSVC to avoid the SDK WinINet/WinHTTP type collision.",
        "Preserve the existing MSVC WinHTTP link directive and MinGW behavior.",
        "Format only the two owned C++ files."
      ],
      "forbiddenPaths": ["ext/**", "src/mac/**", "src/linux/**"],
      "allowedGenerators": [],
      "acceptanceCriteria": ["TC1", "TC2", "TC3"],
      "stopConditions": [
        "The fix requires changing Base.h, project files, SDK selection, or public HTTP behavior.",
        "A required edit falls outside ownedPaths."
      ]
    },
    {
      "id": "spec-sync",
      "dependsOn": ["quick-translation-popup", "toolchain-source-compatibility"],
      "ownedPaths": [
        "[.]trellis/spec/frontend/index.md",
        "[.]trellis/spec/frontend/selection-translation-popup.md",
        "[.]trellis/spec/backend/index.md",
        "[.]trellis/spec/backend/windows-build.md"
      ],
      "actions": [
        "Document the quick-translation command, popup lifecycle, privacy, and debug-control contracts.",
        "Document the MSVC intrinsic, WinINet/WinHTTP, and Windows SDK 22621 build contracts.",
        "Link both executable specs from their layer indexes and format the touched Markdown."
      ],
      "forbiddenPaths": ["src/**", "tests/**", "ext/**"],
      "allowedGenerators": ["bunx prettier --write"],
      "acceptanceCriteria": ["SC1", "SC2"],
      "stopConditions": [
        "The spec requires changing product behavior or an unrelated project convention.",
        "A required edit falls outside ownedPaths."
      ]
    }
  ]
}
```

## Unit 1

Implement the feature as one hard, cross-boundary unit because command generation,
selection geometry, popup lifetime, async translation, debug control, tests, and
documentation share one user-visible contract and overlapping source paths.

1. Add `CmdTranslateSelectionQuick` at the end of the generated command list and
   regenerate command sources.
2. Write or extend the focused test first so it fails without the new command and
   popup behavior.
3. Share visible-selection bounds, map the built-in toolbar action to the quick
   command, and preserve the full-dialog command entries.
4. Implement provider validation, popup states, no-activate presentation, click
   activation, placement, lifecycle hooks, toolbar restoration, and stale-result
   rejection.
5. Remove sensitive payload logging from the shared CLI translation path.
6. Add deterministic debug-control state/result injection, finish the focused test,
   and update command and release documentation.
7. Run the approved generators and formatters before handing off to the checker.

## Unit 2

Restore baseline compatibility with the installed MSVC and Windows SDK without
changing popup or HTTP behavior.

1. Add the compiler-owned intrinsic header for the existing MSVC `__cpuid` calls.
2. Apply the existing narrow WinHTTP declaration block to MSVC and retain its
   import-library directive.
3. Format only `src/base/Win.cpp` and `src/base/Http_win.cpp`.

Acceptance criteria:

- TC1: MSVC resolves every existing `__cpuid` call from `intrin.h`.
- TC2: `Http_win.cpp` no longer includes conflicting WinHTTP SDK types after
  `Base.h` includes WinINet.
- TC3: The base project and normal debug build compile without changing HTTP or
  selection-popup behavior.

## Unit 3

Capture the reusable feature and Windows build contracts in executable specs.

1. Add a frontend spec for command routing, provider validation, popup states,
   focus, lifecycle, privacy, and debug-control assertions.
2. Add a backend spec for MSVC intrinsics, the WinINet/WinHTTP include boundary,
   SDK 22621 selection, and focused build validation.
3. Link both specs from their layer indexes and format only the four owned files.

Acceptance criteria:

- SC1: The feature spec contains all seven code-spec sections required by
  `trellis-update-spec` with concrete signatures and assertion points.
- SC2: The build spec records the verified SDK/component/env contract and the
  narrow source compatibility rules without duplicating task history.

## Validation Plan

- Inspect generated command output and search all `CmdTranslateSelection` mappings.
- Format changed TypeScript and C/C++ sources with the repository formatter.
- Build the debug executable.
- Run `tests/selection-translate-popup.ts` for command routing, invalid-provider,
  state, focus, placement, dismissal, toolbar restoration, and stale completion.
- Run `tests/issue-5934.ts`, `tests/issue-6048.ts`,
  `tests/selection-toolbar-stays.ts`, and `tests/selection-toolbar-move.ts` without
  rebuilding to protect the existing dialog and toolbar behavior.
- Inspect logging call sites to confirm no selected text, prompt, raw CLI output,
  or translated result reaches ordinary diagnostics.
- Build `vs2022/base.vcxproj` for Debug/x64 after the compatibility unit, then
  retry the blocked normal debug build and popup regression evidence.
