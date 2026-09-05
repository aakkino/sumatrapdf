# Implementation Plan

## Contract

```json
{
  "schemaVersion": 1,
  "forbiddenVerification": ["test", "lint", "typecheck", "build"],
  "units": [
    {
      "id": "command-integration",
      "dependsOn": [],
      "ownedPaths": [
        "cmd/gen-commands.ts",
        "src/Commands.h",
        "src/Commands.cpp",
        "src/CommandAvailability.cpp",
        "src/Menu.cpp",
        "src/SumatraPDF.cpp",
        "src/SumatraControl.cpp",
        "tests/control.ts",
        "tests/ad-hoc-selection-translate.ts",
        "tests/run-almost-all.ts",
        "docs/md/Commands.md",
        "docs/md/Customize-search-translation-services.md",
        "docs/md/Version-history.md"
      ],
      "actions": [
        "Remove provider-specific translation commands and their dispatch and availability entries.",
        "Keep CmdTranslateSelection and CmdTranslateSelectionQuick as quick-popup aliases.",
        "Integrate the configuration command, remove obsolete CLI debug-control coverage, register focused tests, and update user-visible command documentation."
      ],
      "forbiddenPaths": ["ext/**", "src/AIChat*.cpp", "src/AIChat*.h", "src/SelectionTranslate.*"],
      "allowedGenerators": [
        "bun cmd/gen-commands.ts",
        "bun cmd/format.ts",
        "clang-format.exe",
        "bunx prettier --write"
      ],
      "acceptanceCriteria": ["AC7", "AC9", "AC10", "AC11", "AC12", "AC13"],
      "stopConditions": [
        "The configuration child or popup functional unit has not passed its paired check.",
        "The integration requires changing AI Chat behavior or provider transport."
      ]
    },
    {
      "id": "spec-sync",
      "dependsOn": ["command-integration"],
      "ownedPaths": [
        ".trellis/spec/backend/translation-service.md",
        ".trellis/spec/frontend/selection-translation-popup.md"
      ],
      "actions": [
        "Synchronize the final provider service, configuration window, popup, command, test-seam, and privacy contracts.",
        "Keep each cross-layer scenario executable with signatures, validation matrices, cases, required tests, and wrong-versus-correct examples."
      ],
      "forbiddenPaths": ["src/**", "cmd/**", "tests/**", "ext/**"],
      "allowedGenerators": [],
      "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4", "AC5", "AC5a", "AC6", "AC7", "AC8", "AC8a", "AC9", "AC10", "AC11", "AC12", "AC13"],
      "stopConditions": [
        "The implementation and checked behavior disagree in a way that requires product-code changes."
      ]
    },
    {
      "id": "evidence-closure",
      "dependsOn": ["spec-sync"],
      "ownedPaths": [
        ".trellis/tasks/09-04-translation-popup-provider-apis/baseline.json",
        ".trellis/tasks/09-04-translation-popup-provider-apis/evidence.jsonl",
        ".trellis/tasks/09-04-translation-popup-ui-migration/baseline.json",
        ".trellis/tasks/09-04-translation-popup-ui-migration/evidence.jsonl",
        ".trellis/tasks/09-04-translation-provider-config-ui/baseline.json",
        ".trellis/tasks/09-04-translation-provider-config-ui/evidence.jsonl"
      ],
      "actions": [
        "Reconcile parent/child baselines that incorrectly protected task-tree and checked dependency artifacts while retaining unrelated user-edit protection.",
        "Persist the successful paired-check results already produced by the dispatched check stages."
      ],
      "forbiddenPaths": ["src/**", "cmd/**", "tests/**", "docs/**", "ext/**", ".trellis/spec/**"],
      "allowedGenerators": [],
      "acceptanceCriteria": ["AC7"],
      "stopConditions": [
        "A required successful check result cannot be traced to a completed checker report."
      ]
    },
    {
      "id": "postfix-evidence-closure",
      "dependsOn": ["evidence-closure"],
      "ownedPaths": [
        "*.trellis/spec/backend/translation-service.md",
        "*.trellis/spec/frontend/selection-translation-popup.md",
        "*.trellis/tasks/09-04-translation-popup-provider-apis/**",
        "*.trellis/tasks/09-04-translation-popup-ui-migration/**",
        "*.trellis/tasks/09-04-translation-provider-config-ui/**",
        "*.trellis/tasks/09-05-translation-config-edit-redraw/**",
        "*.trellis/tasks/09-05-translation-config-label-overlap/**",
        "cmd/gen-commands.ts",
        "cmd/helper/mingw-build.ts",
        "docs/md/Commands.md",
        "docs/md/Customize-search-translation-services.md",
        "docs/md/Version-history.md",
        "premake5.files.lua",
        "src/CommandAvailability.cpp",
        "src/Commands.cpp",
        "src/Commands.h",
        "src/Menu.cpp",
        "src/SelectionToolbar.cpp",
        "src/SelectionTranslate.cpp",
        "src/SelectionTranslate.h",
        "src/SumatraControl.cpp",
        "src/SumatraPDF.cpp",
        "src/TranslationConfig.cpp",
        "src/TranslationConfig.h",
        "src/TranslationService.cpp",
        "src/TranslationService.h",
        "src/gui/VirtCtrl.cpp",
        "src/gui/win/WindowBase.cpp",
        "tests/ad-hoc-selection-translate.ts",
        "tests/ad-hoc-translation-config-edit-redraw.ts",
        "tests/control.ts",
        "tests/issue-5934.ts",
        "tests/run-almost-all.ts",
        "tests/selection-translate-popup.ts",
        "tests/translation-api.ts",
        "tests/translation-config.ts",
        "vs2022/SumatraPDF-static.vcxproj",
        "vs2022/SumatraPDF-static.vcxproj.filters",
        "vs2022/SumatraPDF.vcxproj",
        "vs2022/SumatraPDF.vcxproj.filters"
      ],
      "actions": [
        "Record the final parent diff evidence after child repairs without treating any task-owned path as unrelated shared-worktree drift."
      ],
      "forbiddenPaths": [".codex/**", "ext/**"],
      "allowedGenerators": [],
      "acceptanceCriteria": ["AC7"],
      "stopConditions": [
        "A dirty path falls outside the parent task tree or listed product scope."
      ]
    }
  ]
}
```

## Progress

1. `09-04-translation-api-core` is complete and archived at `f0b651e16`.
2. `09-04-translation-provider-config-ui` and
   `09-04-translation-popup-ui-migration` remain in planning.

## Parallel Execution

1. Run the configuration child's `shared-ui-contract` unit and paired check.
2. In parallel:
   - continue the configuration child's `config-ui` unit;
   - run the popup child's `popup-functional` unit.
3. After `config-ui` and `popup-functional` pass their paired checks, run in
   parallel:
   - this parent's `command-integration` unit;
   - the popup child's `popup-polish` unit.
4. Wait for both branches of the second parallel window, then run the parent
   integration and final gates.

Parallel stages must use the ownership lists in their task contracts. A stage
must not edit a path owned by the concurrent stage.

## Validation Plan

- Run `bun cmd/format.ts` after all source and test edits are integrated.
- Run `bun cmd/build.ts -debug` once after the final source change.
- Run only:
  - `bun tests/translation-api.ts --no-build`
  - `bun tests/translation-config.ts --no-build`
  - `bun tests/selection-translate-popup.ts --no-build`
  - `bun tests/issue-5934.ts --no-build`
- Run `git diff --check`.
- Review normal/high DPI and light/dark captures without pixel baselines.
- Audit that AI Chat commands and providers are unchanged and that logs, errors,
  probes, and popup content expose no credentials or translation payloads.
