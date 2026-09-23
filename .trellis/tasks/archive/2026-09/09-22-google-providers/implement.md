# Implementation Plan

## Contract

```json
{"schemaVersion":1,"coordinationExclusions":[".agents/**",".codex/**",".trellis/**"],"forbiddenVerification":["test","lint","typecheck","build"],"units":[{"id":"google-providers","dependsOn":[],"ownedPaths":["src/TranslationService.cpp","src/TranslationService.h","src/SumatraControl.cpp","src/base/Http.h","src/base/Http_win.cpp","tests/translation-api.ts"],"forbiddenPaths":["ext/**"],"allowedGenerators":[],"actions":["Implement Google and GoogleAPI request/token/parse adapters, bounded redacted GET transport, and local fixture coverage."],"acceptanceCriteria":["AC1","AC2","AC3","AC4"],"stopConditions":["Popup lifecycle or vendored code changes are required."]}]}
```

## Unit 1

Implement the service adapters and focused fixture tests in the owned paths.

## Validation Plan

Run the paired checker’s targeted translation API test and `git diff --check`.
