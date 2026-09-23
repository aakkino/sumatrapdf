# Implementation Plan

## Contract

```json
{"schemaVersion":1,"coordinationExclusions":[".agents/**",".codex/**",".trellis/**"],"forbiddenVerification":["test","lint","typecheck","build"],"units":[{"id":"spec-sync","dependsOn":[],"ownedPaths":[".trellis/spec/backend/translation-service.md",".trellis/spec/frontend/selection-translation-popup.md"],"forbiddenPaths":["ext/**"],"allowedGenerators":[],"actions":["Synchronize executable provider and configuration contracts."],"acceptanceCriteria":["AC1","AC2"],"stopConditions":["Spec text would contradict shipped code."]}]}
```

## Unit 1

Update only the two owned specs with concrete provider, UI, validation, and test contracts.

## Validation Plan

Run `git diff --check` and the paired spec review.
