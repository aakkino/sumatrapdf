# Implementation Plan

## Contract

```json
{
  "schemaVersion": 1,
  "forbiddenVerification": ["test", "lint", "typecheck", "build"],
  "units": [
    {
      "id": "translation-api-core",
      "dependsOn": [],
      "ownedPaths": [
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
      "actions": [
        "Add deterministic provider contract tests.",
        "Implement settings, provider adapters, response parsing, and redacted errors.",
        "Add explicit HTTP timeout and size bounds where required."
      ],
      "forbiddenPaths": ["ext/**", "src/AIChat*.cpp", "src/AIChat*.h", "src/SelectionTranslate.cpp"],
      "allowedGenerators": ["bun cmd/gen-settings.ts", "bun cmd/format.ts", "clang-format.exe"],
      "acceptanceCriteria": ["AC1", "AC2", "AC3", "AC4", "AC5", "AC6"],
      "stopConditions": [
        "A provider requires OAuth, a provider SDK, streaming, or user-configurable prompts.",
        "A required edit falls outside ownedPaths."
      ]
    }
  ]
}
```

## Unit 1: Translation API core

1. Add focused local-server tests for provider request/response, failures,
   redaction, settings completeness, and URL normalization.
2. Add provider-neutral service types and the three adapters.
3. Add generated provider settings and regenerate settings/docs.
4. Add explicit HTTP bounds with focused base coverage if the existing API must
   change.
5. Re-run the focused tests and inspect logs for forbidden content.

## Validation Plan

- Run `bun cmd/format.ts -ts`, clang-format touched `src/` files, and regenerate
  settings through the established generator.
- Run the new translation API test and `bun cmd/run-unit-tests.ts -dbg` only when
  `src/base/Http*` changes.
- Run `bun cmd/build.ts -debug` after final source edits.
