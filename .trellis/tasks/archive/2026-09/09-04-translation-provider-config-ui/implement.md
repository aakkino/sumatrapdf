# Implementation Plan

## Contract

```json
{
  "schemaVersion": 1,
  "forbiddenVerification": ["test", "lint", "typecheck", "build"],
  "units": [
    {
      "id": "shared-ui-contract",
      "dependsOn": [],
      "ownedPaths": [
        "src/TranslationService.h",
        "src/TranslationService.cpp",
        "src/TranslationConfig.h",
        "tests/translation-api.ts",
        ".trellis/spec/backend/translation-service.md"
      ],
      "actions": [
        "Expose the existing canonical language labels through one read-only service accessor.",
        "Freeze the public configuration-window entry point used by command and popup code.",
        "Add focused service coverage without changing transport, adapters, parsing, or redaction."
      ],
      "forbiddenPaths": ["ext/**", "src/AIChat*.cpp", "src/AIChat*.h", "src/base/Http*", "src/SelectionTranslate.*"],
      "allowedGenerators": ["bun cmd/format.ts", "clang-format.exe"],
      "acceptanceCriteria": ["AC4a"],
      "stopConditions": [
        "The change requires modifying provider HTTP behavior or adding a second language table.",
        "The public configuration entry point cannot remain UI-only."
      ]
    },
    {
      "id": "config-ui",
      "dependsOn": ["shared-ui-contract"],
      "ownedPaths": [
        "premake5.files.lua",
        "cmd/helper/mingw-build.ts",
        "cmd/gen-commands.ts",
        "src/Commands.h",
        "src/Commands.cpp",
        "src/CommandAvailability.cpp",
        "src/TranslationConfig.h",
        "src/TranslationConfig.cpp",
        "src/SumatraPDF.cpp",
        "src/SumatraControl.cpp",
        "tests/control.ts",
        "tests/translation-config.ts",
        "vs2022/SumatraPDF.vcxproj",
        "vs2022/SumatraPDF.vcxproj.filters",
        "vs2022/SumatraPDF-static.vcxproj",
        "vs2022/SumatraPDF-static.vcxproj.filters",
        "docs/md/Commands.md"
      ],
      "actions": [
        "Add and generate CmdConfigureTranslation and its selection-independent dispatch.",
        "Build the native configuration window with local edit state, provider fields, and language controls.",
        "Implement selected-provider validation, Save, Cancel, key masking, warning, and asynchronous Test Connection.",
        "Register the new source module and add deterministic configuration-window coverage."
      ],
      "forbiddenPaths": ["ext/**", "src/AIChat*.cpp", "src/AIChat*.h", "src/base/Http*", "src/SelectionTranslate.*"],
      "allowedGenerators": ["bun cmd/gen-commands.ts", "bun cmd/format.ts", "bun cmd/premake.ts", "clang-format.exe"],
      "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4", "AC5", "AC6", "AC7"],
      "stopConditions": [
        "The shared UI contract has not passed its paired check.",
        "The UI requires credential encryption, manual translation, or advanced translucent UI."
      ]
    },
    {
      "id": "config-focus-stability",
      "dependsOn": ["config-ui"],
      "ownedPaths": [
        "src/TranslationConfig.cpp",
        "tests/translation-config.ts"
      ],
      "actions": [
        "Extend the focused test to cover provider focus on singleton reopen.",
        "Use the window-level forced-focus helper after foreground activation on both open paths."
      ],
      "forbiddenPaths": ["src/gui/win/DropDown.cpp", "src/base/Win.cpp", "ext/**", "src/AIChat*.cpp", "src/AIChat*.h"],
      "allowedGenerators": ["bun cmd/format.ts", "clang-format.exe"],
      "acceptanceCriteria": ["AC1", "AC7", "AC8"],
      "stopConditions": [
        "The fix requires changing global dropdown or foreground-window behavior."
      ]
    },
    {
      "id": "focus-collapse-spec-sync",
      "dependsOn": ["config-focus-stability"],
      "ownedPaths": [".trellis/spec/frontend/selection-translation-popup.md"],
      "actions": [
        "Document collapsed virtual-layout subtree pruning and forced provider focus after foreground activation.",
        "Keep the configuration scenario's validation, tests, and wrong-versus-correct examples executable."
      ],
      "forbiddenPaths": ["src/**", "cmd/**", "tests/**", "docs/**", "ext/**"],
      "allowedGenerators": [],
      "acceptanceCriteria": ["AC1", "AC7", "AC8"],
      "stopConditions": [
        "The checked implementation disagrees with the existing configuration contract."
      ]
    },
    {
      "id": "config-dpi-and-internet-guard",
      "dependsOn": ["focus-collapse-spec-sync"],
      "ownedPaths": [
        "src/TranslationConfig.cpp",
        "tests/translation-config.ts",
        "*.trellis/**",
        "cmd/**",
        "docs/**",
        "premake5.files.lua",
        "src/**",
        "tests/**",
        "vs2022/**"
      ],
      "actions": [
        "Add deterministic failing coverage for updating every provider label and heading at a changed DPI, including previously collapsed forms.",
        "Add deterministic failing coverage that Test Connection is unavailable and cannot start a worker without Perm::InternetAccess.",
        "Update stored row-label and heading fonts directly during DPI changes, and gate both Test Connection state and its start boundary while leaving offline configuration available."
      ],
      "forbiddenPaths": ["src/gui/VirtCtrl.cpp", "src/gui/win/WindowBase.cpp", "src/SelectionTranslate.cpp", "src/TranslationService.cpp", "src/TranslationService.h", "cmd/**", "ext/**"],
      "allowedGenerators": ["bun cmd/format.ts", "clang-format.exe"],
      "acceptanceCriteria": ["AC6", "AC7", "AC9", "AC10"],
      "stopConditions": [
        "The test can inspect only the selected provider or cannot prove a blocked worker start.",
        "The change requires hiding CmdConfigureTranslation or changing provider transport."
      ]
    },
    {
      "id": "postfix-evidence-closure",
      "dependsOn": ["config-dpi-and-internet-guard"],
      "ownedPaths": [
        "*.trellis/**",
        "cmd/**",
        "docs/**",
        "premake5.files.lua",
        "src/**",
        "tests/**",
        "vs2022/**"
      ],
      "actions": ["Record final composite evidence after all child repairs."],
      "forbiddenPaths": [".codex/**", "ext/**"],
      "allowedGenerators": [],
      "acceptanceCriteria": ["AC7"],
      "stopConditions": ["A dirty path falls outside the translation task scope."]
    }
  ]
}
```

## Unit 1: Shared UI contract

1. Add the language-catalog test first.
2. Expose the service's existing stable language labels without duplicating
   mapping data.
3. Declare the configuration-window entry point consumed by the popup and
   command dispatcher.
4. Format, build, run the translation API test, and complete the paired check.

The popup child may start `popup-functional` after this unit passes. It does not
wait for the complete configuration window.

## Unit 2: Provider configuration UI

1. Add focused configuration-window tests and debug-control seams.
2. Add `CmdConfigureTranslation` at the generator's required position and
   regenerate command sources.
3. Implement the standalone resizable native window in `TranslationConfig.cpp`.
4. Keep edits local until Save; persist all fields while requiring only the
   selected provider and languages to be valid.
5. Run Test Connection on a worker with fixed non-sensitive text and reject
   stale completion by HWND and request ID.
6. Register the new files and update command documentation.

## Validation Plan

- Unit 1: `bun cmd/format.ts`, `bun cmd/build.ts -debug`,
  `bun tests/translation-api.ts --no-build`, and `git diff --check`.
- Unit 2: `bun cmd/format.ts`, `bun cmd/build.ts -debug`,
  `bun tests/translation-config.ts --no-build`, and `git diff --check`.
- Unit 3: `bun cmd/format.ts`, `bun cmd/build.ts -debug`, run
  `bun tests/translation-config.ts --no-build` three times, and
  `git diff --check`.
- Unit 4: `git diff --check`.
- Unit 5: `bun cmd/format.ts`, `bun cmd/build.ts -debug`,
  `bun tests/translation-config.ts --no-build`, and `git diff --check`.
- Inspect light/dark, normal/high DPI, keyboard traversal, resizing, key
  masking, warnings, and stale Test Connection completion.
