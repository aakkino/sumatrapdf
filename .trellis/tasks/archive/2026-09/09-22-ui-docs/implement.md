# Implementation Plan

## Contract

```json
{"schemaVersion":1,"coordinationExclusions":[".agents/**",".codex/**",".trellis/**"],"forbiddenVerification":["test","lint","typecheck","build"],"units":[{"id":"ui-docs","dependsOn":[],"ownedPaths":["src/TranslationConfig.cpp","src/SelectionTranslate.cpp","tests/translation-config.ts","tests/selection-translate-popup.ts","docs/md/Customize-search-translation-services.md"],"forbiddenPaths":["ext/**"],"allowedGenerators":[],"actions":["Expose canonical provider labels/configuration, synchronize affected provider-menu tests, and document endpoint behavior."],"acceptanceCriteria":["AC1","AC5","AC6"],"stopConditions":["Replacing Google Cloud provider is required."]}]}
```

## Unit 1

Update provider configuration, popup-facing labels if needed, and documentation.

## Validation Plan

Run provider configuration and popup tests, then `git diff --check`.
