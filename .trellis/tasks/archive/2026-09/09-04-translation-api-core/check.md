# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "protectedBaseline": "baseline.json",
  "selfFix": {
    "allowedPaths": [
      "cmd/gen-settings.ts",
      "src/Settings.h",
      "src/base/Http.h",
      "src/base/Http_win.cpp",
      "src/TranslationService.h",
      "src/TranslationService.cpp",
      "src/SumatraControl.cpp",
      "tests/control.ts",
      "tests/translation-api.ts",
      "docs/md/Advanced-options-settings.md"
    ],
    "allowedIssueClasses": [
      "spec-compliance",
      "compile-error",
      "formatting",
      "targeted-test-failure",
      "provider-contract",
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
        "invalidatedBy": ["cmd/gen-settings.ts", "src/**"],
        "maxRuns": 2
      },
      {
        "id": "api-test",
        "argv": ["bun", "tests/translation-api.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/**", "tests/translation-api.ts", "tests/control.ts"],
        "maxRuns": 3
      },
      {
        "id": "diff-check",
        "argv": ["git", "diff", "--check"],
        "tier": "T1",
        "invalidatedBy": ["cmd/**", "src/**", "tests/**", "docs/**"],
        "maxRuns": 2
      }
    ]
  },
  "finalGate": { "maxTier": "T0", "commands": [] }
}
```

## Audit Matrix

| Requirements  | Evidence                                           |
| ------------- | -------------------------------------------------- |
| AC1, AC3, AC4 | Local-server request capture and response fixtures |
| AC2           | Failure, timeout, size-limit, and redaction cases  |
| AC5           | Generated-settings inspection and diagnostic audit |
| AC6           | Standalone focused test result                     |

## Paired Check Procedure

Review the owned diff, run formatting once after edits, build once, and run only
the provider test. If `base/Http` changes, also run the debug unit tests. Fix
in-scope failures and revalidate without broad suites or live provider calls.

## Final Gate Procedure

Freeze the checked candidate and perform a read-only ownership, contract,
redaction, and evidence review. Run no additional commands.
