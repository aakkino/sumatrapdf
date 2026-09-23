# Check Contract

## Machine Contract

```json
{"schemaVersion":1,"selfFix":{"allowedPaths":["src/TranslationService.cpp","src/TranslationService.h","src/TranslationConfig.cpp","src/SelectionTranslate.cpp","tests/translation-api.ts","docs/md/Customize-search-translation-services.md"],"allowedIssueClasses":["spec-compliance","compile-error","formatting","targeted-test-failure","cross-layer-contract","privacy-regression"],"maxRounds":2},"paired":{"maxTier":"T2","commands":[{"id":"format","argv":["bun","cmd/format.ts"],"tier":"T1","invalidatedBy":["src/**","tests/**","cmd/**"],"maxRuns":2},{"id":"api-test","argv":["bun","tests/translation-api.ts","--no-build"],"tier":"T1","invalidatedBy":["src/**","tests/translation-api.ts"],"maxRuns":2},{"id":"build","argv":["bun","cmd/build.ts","-debug"],"tier":"T2","invalidatedBy":["src/**","cmd/**"],"maxRuns":2},{"id":"diff-check","argv":["git","diff","--check"],"tier":"T1","invalidatedBy":["src/**","tests/**","docs/**"],"maxRuns":2}]},"finalGate":{"maxTier":"T0","commands":[]}}
```

## Audit Matrix

| Requirement | Evidence |
| --- | --- |
| AC1-AC4 | Provider fixture tests and service review |
| AC5-AC6 | Popup/configuration regression tests and documentation review |

## Paired Check Procedure

Review the diff, run the listed focused checks, and verify no key, selected text,
token or provider response is logged.

## Final Gate Procedure

Perform a read-only ownership, contract, privacy and acceptance audit after the
focused checks pass.
