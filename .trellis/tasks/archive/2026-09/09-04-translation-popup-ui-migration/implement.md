# Implementation Plan

## Contract

```json
{
  "schemaVersion": 1,
  "forbiddenVerification": ["test", "lint", "typecheck", "build"],
  "units": [
    {
      "id": "popup-functional",
      "dependsOn": [],
      "ownedPaths": [
        "src/SelectionTranslate.cpp",
        "src/SelectionTranslate.h",
        "src/SelectionToolbar.cpp",
        "tests/selection-translate-popup.ts",
        "tests/issue-5934.ts",
        ".trellis/spec/frontend/selection-translation-popup.md"
      ],
      "actions": [
        "Update focused tests for HTTP providers, configuration routing, and retained lifecycle behavior.",
        "Replace browser and AI CLI translation execution with TranslationService workers.",
        "Make both existing generic translation entry points show the quick popup.",
        "Leave command definition removal and documentation cleanup to the parent integration unit."
      ],
      "forbiddenPaths": [
        "ext/**",
        "cmd/gen-commands.ts",
        "src/Commands.*",
        "src/CommandAvailability.cpp",
        "src/SumatraPDF.cpp",
        "src/SumatraControl.cpp",
        "src/TranslationConfig.*",
        "src/TranslationService.cpp",
        "src/AIChat*.cpp",
        "src/AIChat*.h",
        "tests/control.ts",
        "docs/md/Commands.md",
        "docs/md/Version-history.md"
      ],
      "allowedGenerators": ["bun cmd/format.ts", "clang-format.exe"],
      "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4", "AC6", "AC7"],
      "stopConditions": [
        "The shared UI contract has not passed its paired check.",
        "The functional migration requires changing provider transport or AI Chat behavior."
      ]
    },
    {
      "id": "popup-polish",
      "dependsOn": ["popup-functional"],
      "ownedPaths": ["src/SelectionTranslate.cpp", "src/SelectionTranslate.h", "tests/selection-translate-popup.ts"],
      "actions": [
        "Remove the deferred TranslateEngine compatibility shim after parent command integration removes its generated aliases.",
        "Remove the obsolete CLI debug shim and keep popup test dumps from exposing production translation results.",
        "Add small corners, dividers, repository-owned icons, a lightweight shadow, and a timer-driven loading indicator.",
        "Keep every effect lifetime-safe and independently fallback-safe."
      ],
      "forbiddenPaths": [
        "ext/**",
        "cmd/gen-commands.ts",
        "src/Commands.*",
        "src/CommandAvailability.cpp",
        "src/SumatraPDF.cpp",
        "src/SumatraControl.cpp",
        "src/TranslationConfig.*",
        "src/TranslationService.cpp",
        "src/AIChat*.cpp",
        "src/AIChat*.h",
        "tests/control.ts",
        "docs/**"
      ],
      "allowedGenerators": ["bun cmd/format.ts", "clang-format.exe"],
      "acceptanceCriteria": ["AC3", "AC5", "AC7"],
      "stopConditions": [
        "The popup functional unit has not passed its paired check.",
        "The visual work requires deferred translucent or general UI Automation infrastructure."
      ]
    },
    {
      "id": "popup-internet-permission",
      "dependsOn": ["popup-polish"],
      "ownedPaths": ["src/SelectionTranslate.cpp", "tests/selection-translate-popup.ts"],
      "actions": [
        "Add failing focused coverage for missing Perm::InternetAccess across popup creation and direct Start/SwitchProvider test transitions.",
        "Require InternetAccess at the popup execution boundary before allocating a request ID, hiding the toolbar, or starting a worker."
      ],
      "forbiddenPaths": ["src/TranslationConfig.cpp", "src/TranslationService.cpp", "src/TranslationService.h", "src/CommandAvailability.cpp", "cmd/**", "ext/**"],
      "allowedGenerators": ["bun cmd/format.ts", "clang-format.exe"],
      "acceptanceCriteria": ["AC7", "AC8"],
      "stopConditions": [
        "The test cannot control InternetAccess permissions without changing global test infrastructure.",
        "The fix requires hiding CmdConfigureTranslation or changing provider transport."
      ]
    },
    {
      "id": "postfix-evidence-closure",
      "dependsOn": ["popup-internet-permission"],
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

## Unit 1: Functional provider migration

1. Update focused tests first for provider states, switching, Retry, Configure,
   generic aliases, and stale completion.
2. Replace engine/backend state with provider and settings snapshots.
3. Invoke `TranslateText()` only from a worker and apply normalized results only
   after HWND, request, tab, and selection identity checks.
4. Use the frozen `ShowTranslationConfig()` entry point without modifying the
   concurrently owned configuration or command files.
5. Remove the old manual dialog and browser/CLI execution from
   `SelectionTranslate.cpp`; parent integration removes obsolete commands.
6. Update the executable popup specification.

After this unit passes its paired check, the parent command-integration unit may
run in parallel with Unit 2.

## Unit 2: Native visual polish

1. Add small corners and dividers without changing native control semantics.
2. Add repository-owned icons, a lifetime-bound shadow, and timer-driven loading.
3. Verify each effect degrades independently to the opaque native baseline.
4. Capture light/dark and normal/high-DPI evidence and recheck focus, placement,
   selection, keyboard, dismissal, and stale completion.

## Validation Plan

- Each unit runs `bun cmd/format.ts`, `bun cmd/build.ts -debug`, the focused
  popup test, and `git diff --check` after its final source edits.
- Unit 1 also runs `bun tests/issue-5934.ts --no-build`.
- Review logging paths and use no live provider accounts or broad test suites.
- Unit 3 reruns the focused popup test after a Debug build.
