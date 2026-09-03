# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "protectedBaseline": "baseline.json",
  "selfFix": {
    "allowedPaths": [
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
      "docs/md/Version-history.md",
      "src/base/Win.cpp",
      "src/base/Http_win.cpp",
      "[.]trellis/spec/frontend/index.md",
      "[.]trellis/spec/frontend/selection-translation-popup.md",
      "[.]trellis/spec/backend/index.md",
      "[.]trellis/spec/backend/windows-build.md"
    ],
    "allowedIssueClasses": [
      "spec-compliance",
      "compile-error",
      "formatting",
      "targeted-test-failure",
      "lifecycle-safety",
      "privacy-regression",
      "documentation-drift"
    ],
    "maxRounds": 2
  },
  "paired": {
    "maxTier": "T2",
    "commands": [
      {
        "id": "format-ts",
        "argv": ["bun", "cmd/format.ts", "-ts"],
        "tier": "T1",
        "invalidatedBy": ["cmd/**/*.ts", "tests/**/*.ts"],
        "maxRuns": 5
      },
      {
        "id": "format-cpp",
        "argv": [
          "clang-format.exe",
          "-i",
          "-style=file",
          "src/Commands.cpp",
          "src/Commands.h",
          "src/CommandAvailability.cpp",
          "src/Selection.cpp",
          "src/Selection.h",
          "src/SelectionToolbar.cpp",
          "src/SelectionTranslate.cpp",
          "src/SelectionTranslate.h",
          "src/SumatraControl.cpp",
          "src/SumatraPDF.cpp"
        ],
        "tier": "T1",
        "invalidatedBy": ["src/Commands.cpp", "src/Commands.h", "src/CommandAvailability.cpp", "src/Selection.cpp", "src/Selection.h", "src/SelectionToolbar.cpp", "src/SelectionTranslate.cpp", "src/SelectionTranslate.h", "src/SumatraControl.cpp", "src/SumatraPDF.cpp"],
        "maxRuns": 3
      },
      {
        "id": "format-toolchain-cpp",
        "argv": ["clang-format.exe", "-i", "-style=file", "src/base/Win.cpp", "src/base/Http_win.cpp"],
        "tier": "T1",
        "invalidatedBy": ["src/base/Win.cpp", "src/base/Http_win.cpp"],
        "maxRuns": 2
      },
      {
        "id": "build-base-debug",
        "argv": ["msbuild.exe", "vs2022/base.vcxproj", "/t:Build", "/p:Configuration=Debug", "/p:Platform=x64"],
        "tier": "T2",
        "invalidatedBy": ["src/base/Win.cpp", "src/base/Http_win.cpp"],
        "maxRuns": 2
      },
      {
        "id": "format-spec",
        "argv": ["bunx", "prettier", "--write", ".trellis/spec/frontend/index.md", ".trellis/spec/frontend/selection-translation-popup.md", ".trellis/spec/backend/index.md", ".trellis/spec/backend/windows-build.md"],
        "tier": "T1",
        "invalidatedBy": [".trellis/spec/frontend/index.md", ".trellis/spec/frontend/selection-translation-popup.md", ".trellis/spec/backend/index.md", ".trellis/spec/backend/windows-build.md"],
        "maxRuns": 2
      },
      {
        "id": "build-debug",
        "argv": ["bun", "cmd/build.ts", "-debug"],
        "tier": "T2",
        "invalidatedBy": ["cmd/gen-commands.ts", "src/**"],
        "maxRuns": 6
      },
      {
        "id": "popup-test",
        "argv": ["bun", "tests/selection-translate-popup.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/**", "tests/selection-translate-popup.ts", "tests/control.ts"],
        "maxRuns": 5
      },
      {
        "id": "dialog-regression",
        "argv": ["bun", "tests/issue-5934.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/SelectionTranslate.cpp", "src/SelectionTranslate.h", "src/SumatraPDF.cpp"],
        "maxRuns": 4
      },
      {
        "id": "toolbar-layout-regression",
        "argv": ["bun", "tests/issue-6048.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/SelectionToolbar.cpp", "tests/issue-6048.ts"],
        "maxRuns": 4
      },
      {
        "id": "toolbar-stays-regression",
        "argv": ["bun", "tests/selection-toolbar-stays.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/Selection.cpp", "src/SelectionToolbar.cpp", "src/SelectionTranslate.cpp"],
        "maxRuns": 4
      },
      {
        "id": "toolbar-move-regression",
        "argv": ["bun", "tests/selection-toolbar-move.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/Selection.cpp", "src/SelectionToolbar.cpp", "src/SelectionTranslate.cpp", "tests/selection-toolbar-move.ts"],
        "maxRuns": 4
      }
    ]
  },
  "finalGate": { "maxTier": "T0", "commands": [] }
}
```

## Audit Matrix

| Requirements | Evidence                                            |
| ------------ | --------------------------------------------------- |
| AC1-AC4      | Generated-command inspection and popup focused test |
| AC5-AC10     | Popup focused test plus file:line lifecycle review  |
| AC11         | Translation logging call-site review                |
| AC12         | Four existing targeted regression tests             |

## Paired Check Procedure

Review every acceptance criterion and owned diff. Fix all in-scope findings,
format, build once after the last source edit, then run only the listed targeted
tests. Record exact command results and file:line evidence for lifecycle and logging
claims. Do not run a broad suite.

## Final Gate Procedure

After paired checks and spec review, freeze the candidate and perform a read-only
artifact, ownership, and evidence audit. Run no additional commands.
