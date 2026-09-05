# Implementation Plan

## Contract

```json
{
  "schemaVersion": 1,
  "forbiddenVerification": ["test", "lint", "typecheck", "build"],
  "units": [
    {
      "id": "collapsed-virtctrl-paint",
      "dependsOn": [],
      "ownedPaths": ["src/gui/VirtCtrl.cpp"],
      "actions": [
        "Add a failing CollectVirtCtrls unit test for a collapsed layout subtree.",
        "Stop traversal at collapsed layout nodes without changing visible-tree collection."
      ],
      "forbiddenPaths": ["src/TranslationConfig.*", "src/gui/Layout.*", "tests/**", "ext/**"],
      "allowedGenerators": ["clang-format.exe"],
      "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4", "AC5"],
      "stopConditions": [
        "The fix requires provider-specific visibility bookkeeping or a public API change."
      ]
    },
    {
      "id": "postfix-evidence-closure",
      "dependsOn": ["collapsed-virtctrl-paint"],
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

## Unit 1: Collapsed virtual-control paint

Extend the existing colocated `CollectVirtCtrls_Test()` before changing the
traversal. Then skip collapsed nodes and their descendants.

## Validation Plan

- `clang-format.exe -i src/gui/VirtCtrl.cpp`
- `bun cmd/build.ts -debug`
- `out/dbg64/SumatraPDF.exe -unit-tests`
- `bun tests/translation-config.ts --no-build`
- `git diff --check`
