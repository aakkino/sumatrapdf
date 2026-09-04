# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "protectedBaseline": "baseline.json",
  "selfFix": {
    "allowedPaths": [
      "src/SelectionTranslate.cpp",
      "tests/selection-translate-popup.ts",
      ".trellis/spec/frontend/selection-translation-popup.md"
    ],
    "allowedIssueClasses": [
      "spec-compliance",
      "compile-error",
      "formatting",
      "targeted-test-failure",
      "lifecycle-safety",
      "privacy-regression"
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
        "invalidatedBy": ["tests/selection-translate-popup.ts"],
        "maxRuns": 2
      },
      {
        "id": "format-cpp",
        "argv": ["clang-format.exe", "-i", "-style=file", "src/SelectionTranslate.cpp"],
        "tier": "T1",
        "invalidatedBy": ["src/SelectionTranslate.cpp"],
        "maxRuns": 2
      },
      {
        "id": "format-spec",
        "argv": ["bunx", "prettier", "--write", ".trellis/spec/frontend/selection-translation-popup.md"],
        "tier": "T1",
        "invalidatedBy": [".trellis/spec/frontend/selection-translation-popup.md"],
        "maxRuns": 2
      },
      {
        "id": "build-debug",
        "argv": ["bun", "cmd/build.ts", "-debug"],
        "tier": "T2",
        "invalidatedBy": ["src/SelectionTranslate.cpp"],
        "maxRuns": 2
      },
      {
        "id": "popup-test",
        "argv": ["bun", "tests/selection-translate-popup.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/SelectionTranslate.cpp", "tests/selection-translate-popup.ts"],
        "maxRuns": 3
      },
      {
        "id": "diff-check",
        "argv": ["git", "diff", "--check"],
        "tier": "T1",
        "invalidatedBy": [
          "src/SelectionTranslate.cpp",
          "tests/selection-translate-popup.ts",
          ".trellis/spec/frontend/selection-translation-popup.md"
        ],
        "maxRuns": 2
      }
    ]
  },
  "finalGate": { "maxTier": "T0", "commands": [] }
}
```

## Audit Matrix

| Requirements | Evidence                                                        |
| ------------ | --------------------------------------------------------------- |
| AC1-AC3, AC9 | Focused popup test and menu/helper review                       |
| AC4-AC7      | Focused popup test and lifecycle/request-ID review              |
| AC8          | Targeted test result, spec review, and privacy call-site review |
| AC10         | Menu separator, Configure dispatch, and no-send review          |

## Paired Check Procedure

Review the owned diff and every acceptance criterion. Fix in-scope findings,
format, build once after the final source edit, and run only the targeted popup
test. Inspect menu filtering, local ID mapping, cleanup, dismiss-click handling,
and Configure dispatch. Do not run broad suites. The final gate is read-only and
runs no commands.

## Final Gate Procedure

After the paired check and spec review, freeze the candidate and perform a
read-only artifact, ownership, and evidence audit. Run no additional commands.
