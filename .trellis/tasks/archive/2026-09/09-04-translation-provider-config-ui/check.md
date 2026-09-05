# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "protectedBaseline": "baseline.json",
  "selfFix": {
    "allowedPaths": [
      "premake5.files.lua",
      "cmd/helper/mingw-build.ts",
      "cmd/gen-commands.ts",
      "src/Commands.h",
      "src/Commands.cpp",
      "src/CommandAvailability.cpp",
      "src/TranslationConfig.h",
      "src/TranslationConfig.cpp",
      "src/TranslationService.h",
      "src/TranslationService.cpp",
      "src/SumatraPDF.cpp",
      "src/SumatraControl.cpp",
      "tests/control.ts",
      "tests/translation-config.ts",
      "tests/translation-api.ts",
      ".trellis/spec/frontend/selection-translation-popup.md",
      "vs2022/SumatraPDF.vcxproj",
      "vs2022/SumatraPDF.vcxproj.filters",
      "vs2022/SumatraPDF-static.vcxproj",
      "vs2022/SumatraPDF-static.vcxproj.filters",
      ".trellis/spec/backend/translation-service.md",
      "docs/md/Commands.md"
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
        "invalidatedBy": ["cmd/**", "src/**", "tests/**"],
        "maxRuns": 2
      },
      {
        "id": "build",
        "argv": ["bun", "cmd/build.ts", "-debug"],
        "tier": "T2",
        "invalidatedBy": ["cmd/gen-commands.ts", "src/**"],
        "maxRuns": 2
      },
      {
        "id": "api-test",
        "argv": ["bun", "tests/translation-api.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/TranslationService.h", "src/TranslationService.cpp", "tests/translation-api.ts"],
        "maxRuns": 2
      },
      {
        "id": "config-test",
        "argv": ["bun", "tests/translation-config.ts", "--no-build"],
        "tier": "T1",
        "invalidatedBy": ["src/**", "tests/translation-config.ts", "tests/control.ts"],
        "maxRuns": 3
      },
      {
        "id": "diff-check",
        "argv": ["git", "diff", "--check"],
        "tier": "T1",
        "invalidatedBy": ["cmd/**", "src/**", "tests/**", "docs/**", ".trellis/spec/**"],
        "maxRuns": 2
      }
    ]
  },
  "finalGate": { "maxTier": "T0", "commands": [] }
}
```

## Audit Matrix

| Requirements  | Evidence                                                  |
| ------------- | --------------------------------------------------------- |
| AC1, AC2      | Command availability and provider-switch control test     |
| AC3, AC4, AC5 | Masking, validation, Save/Cancel, and settings assertions |
| AC4a          | Service catalog test and dropdown assertions              |
| AC6           | Injected Test Connection lifecycle and redaction cases    |
| AC7           | Standalone focused test plus native visual review         |

## Paired Check Procedure

Review every configuration state and owned path, fix in-scope issues, format,
build once, and run the API and configuration focused tests. Inspect keyboard,
DPI, theme, masking, and stale completion behavior without live provider calls.

## Final Gate Procedure

Freeze the checked candidate and perform a read-only artifact, ownership,
accessibility, privacy, and evidence review. Run no additional commands.
