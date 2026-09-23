# Implementation Plan

## Contract

```json
{
  "schemaVersion": 1,
  "forbiddenVerification": ["test", "lint", "typecheck", "build"],
  "units": [
    {
      "id": "native-edit-frame-redraw",
      "dependsOn": [],
      "ownedPaths": [
        "src/gui/win/WindowBase.cpp",
        "tests/ad-hoc-translation-config-edit-redraw.ts",
        "tests/winapi.ts"
      ],
      "actions": [
        "Write a standalone ad-hoc configuration-window visual regression assertion first for Google-to-OpenAI-compatible and OpenAI-compatible-to-Microsoft transitions.",
        "Make native child visibility use the complete Win32 show/hide lifecycle at ControlBase::SetVisibility().",
        "Use an existing capture/pixel helper; extend tests/winapi.ts only when required to inspect all four frame edges."
      ],
      "forbiddenPaths": [
        "src/TranslationConfig.cpp",
        "src/gui/win/Edit.cpp",
        "src/gui/Layout.cpp",
        "src/TranslationService.cpp",
        "src/TranslationService.h",
        "cmd/**",
        "ext/**"
      ],
      "allowedGenerators": ["bun cmd/format.ts", "clang-format.exe"],
      "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4"],
      "stopConditions": [
        "The test can prove only HWND visibility or bounds, not painted frame edges.",
        "The generic visibility fix requires changes outside the owned paths."
      ]
    },
    {
      "id": "native-visibility-spec-sync",
      "dependsOn": ["native-edit-frame-redraw"],
      "ownedPaths": [".trellis/spec/frontend/selection-translation-popup.md"],
      "actions": [
        "Document the shared child-control show/hide lifecycle and its non-client-frame requirement in the Translation Provider Configuration scenario.",
        "Keep the seven-section scenario executable: add the visual validation state, Good/Base/Bad case, required ad-hoc frame test, and concise wrong-versus-correct example."
      ],
      "forbiddenPaths": ["src/**", "cmd/**", "tests/**", "docs/**", "ext/**"],
      "allowedGenerators": [],
      "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4"],
      "stopConditions": [
        "The checked implementation does not establish the shared show/hide lifecycle described by the update."
      ]
    },
    {
      "id": "postfix-evidence-closure",
      "dependsOn": ["native-visibility-spec-sync"],
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
      "acceptanceCriteria": ["AC1"],
      "stopConditions": ["A dirty path falls outside the translation task scope."]
    }
  ]
}
```

## Unit 1: Native Edit frame redraw

1. Add the visual assertion first and observe it fail with the current
   visibility implementation.
2. Change only the generic native child-control visibility path.
3. Keep provider switching free of repaint special cases.
4. Format, build, run the focused test repeatedly, and complete the paired
   check.

## Validation Plan

- `bun cmd/format.ts`
- `bun cmd/build.ts -debug`
- `bun tests/ad-hoc-translation-config-edit-redraw.ts --no-build` three times
- `git diff --check`

For Unit 2, run `git diff --check` after the paired spec review.
