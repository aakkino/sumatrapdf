# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "protectedBaseline": "baseline.json",
  "selfFix": {
    "allowedPaths": [
      "src/SelectionTranslate.cpp",
      "src/SelectionTranslate.h",
      "src/SelectionToolbar.cpp",
      "tests/selection-translate-popup.ts",
      "tests/issue-5934.ts",
      ".trellis/spec/frontend/selection-translation-popup.md"
    ],
    "allowedIssueClasses": [
      "spec-compliance",
      "compile-error",
      "formatting",
      "targeted-test-failure",
      "ui-lifecycle",
      "privacy-regression"
    ],
    "maxRounds": 2
  },
  "paired": {
    "maxTier": "T2",
    "commands": [
      {
        "id": "format",
        "argv": ["bun", "cmd/format.ts"],
        "tier": "T1",
        "invalidatedBy": [
          "src/SelectionTranslate.cpp",
          "src/SelectionTranslate.h",
          "src/SelectionToolbar.cpp",
          "tests/**"
        ],
        "maxRuns": 2
      },
      {
        "id": "build",
        "argv": ["bun", "cmd/build.ts", "-debug"],
        "tier": "T2",
        "invalidatedBy": ["src/SelectionTranslate.cpp", "src/SelectionTranslate.h", "src/SelectionToolbar.cpp"],
        "maxRuns": 2
      },
      {
        "id": "popup-test",
        "argv": ["bun", "tests/selection-translate-popup.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": [
          "src/SelectionTranslate.cpp",
          "src/SelectionTranslate.h",
          "src/SelectionToolbar.cpp",
          "tests/selection-translate-popup.ts"
        ],
        "maxRuns": 4
      },
      {
        "id": "dialog-test",
        "argv": ["bun", "tests/issue-5934.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/**", "tests/issue-5934.ts"],
        "maxRuns": 2
      },
      {
        "id": "diff-check",
        "argv": ["git", "diff", "--check"],
        "tier": "T1",
        "invalidatedBy": [
          "src/SelectionTranslate.cpp",
          "src/SelectionTranslate.h",
          "src/SelectionToolbar.cpp",
          "tests/**",
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

| Requirements | Evidence                                                         |
| ------------ | ---------------------------------------------------------------- |
| AC1-AC4      | Focused popup state, provider menu, retry, and stale-result test |
| AC5          | Theme/DPI screenshots and keyboard/focus review                  |
| AC6          | Runtime-path diff and AI Chat non-regression review              |
| AC7          | Focused popup and compatibility test results                     |

## Paired Check Procedure

Review the popup and spec diff; fix in-scope issues; format and build once; run
only the listed focused tests. Inspect custom visual resource
lifetime and fallback behavior. Do not run broad suites or live providers.

## Final Gate Procedure

Freeze the checked candidate and perform a read-only artifact, ownership,
lifecycle, privacy, and evidence review. Run no additional commands.
