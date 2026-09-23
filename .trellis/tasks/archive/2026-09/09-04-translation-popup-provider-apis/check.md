# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "protectedBaseline": "baseline.json",
  "selfFix": {
    "allowedPaths": [
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
      ".trellis/spec/backend/translation-service.md",
      ".trellis/spec/frontend/selection-translation-popup.md",
      ".trellis/tasks/09-04-translation-popup-provider-apis/baseline.json",
      ".trellis/tasks/09-04-translation-popup-provider-apis/evidence.jsonl",
      ".trellis/tasks/09-04-translation-popup-ui-migration/baseline.json",
      ".trellis/tasks/09-04-translation-popup-ui-migration/evidence.jsonl",
      ".trellis/tasks/09-04-translation-provider-config-ui/baseline.json",
      ".trellis/tasks/09-04-translation-provider-config-ui/evidence.jsonl",
      "docs/md/Commands.md",
      "docs/md/Customize-search-translation-services.md",
      "docs/md/Version-history.md"
    ],
    "allowedIssueClasses": [
      "spec-compliance",
      "compile-error",
      "formatting",
      "targeted-test-failure",
      "cross-layer-contract",
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
        "invalidatedBy": ["cmd/**", "src/**", "tests/**"],
        "maxRuns": 2
      },
      {
        "id": "build",
        "argv": ["bun", "cmd/build.ts", "-debug"],
        "tier": "T2",
        "invalidatedBy": ["cmd/**", "src/**"],
        "maxRuns": 2
      },
      {
        "id": "api-test",
        "argv": ["bun", "tests/translation-api.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/**", "tests/translation-api.ts", "tests/control.ts"],
        "maxRuns": 2
      },
      {
        "id": "config-test",
        "argv": ["bun", "tests/translation-config.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/**", "tests/translation-config.ts", "tests/control.ts"],
        "maxRuns": 4
      },
      {
        "id": "popup-test",
        "argv": ["bun", "tests/selection-translate-popup.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/**", "tests/selection-translate-popup.ts", "tests/control.ts"],
        "maxRuns": 2
      },
      {
        "id": "diff-check",
        "argv": ["git", "diff", "--check"],
        "tier": "T1",
        "invalidatedBy": ["cmd/**", "src/**", "tests/**", "docs/**", ".trellis/spec/**"],
        "maxRuns": 3
      }
    ]
  },
  "finalGate": { "maxTier": "T0", "commands": [] }
}
```

## Audit Matrix

| Requirements | Evidence                                                          |
| ------------ | ----------------------------------------------------------------- |
| AC1-AC5a     | Child focused tests and cross-layer provider-flow review          |
| AC6-AC8a     | Redaction audit, local-server tests, and Test Connection evidence |
| AC9-AC13     | Generated-command/docs diff and AI Chat non-regression review     |

## Paired Check Procedure

After all child checks close, review the integrated diff and every parent
acceptance criterion. Fix only in-scope integration issues, format once, build
once, and run the three focused tests. Do not run broad suites or live APIs.

## Final Gate Procedure

Freeze the integrated candidate and perform a read-only task-tree, ownership,
contract, privacy, lifecycle, and evidence audit. Run no additional commands.
