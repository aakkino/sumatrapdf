# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "selfFix": {"allowedPaths": ["src/TranslationService.cpp", "src/TranslationService.h", "src/SumatraControl.cpp", "src/base/Http.h", "src/base/Http_win.cpp", "tests/translation-api.ts"], "allowedIssueClasses": ["scope", "format", "targeted-test"], "maxRounds": 2},
  "paired": {"maxTier": "T2", "commands": [{"id":"build","argv":["bun","cmd/build.ts","-debug"],"tier":"T2","invalidatedBy":["src/**"],"maxRuns":2},{"id":"api-test","argv":["bun","tests/translation-api.ts","--no-build"],"tier":"T1","invalidatedBy":["src/**","tests/**"],"maxRuns":2},{"id":"unit-tests","argv":["bun","cmd/run-unit-tests.ts","-dbg"],"tier":"T2","invalidatedBy":["src/**"],"maxRuns":2},{"id":"diff-check","argv":["git","diff","--check"],"tier":"T1","invalidatedBy":["src/**","tests/**"],"maxRuns":2}]},
  "finalGate": {"maxTier": "T1", "commands": [{"id":"api-test","argv":["bun","tests/translation-api.ts","--no-build"],"tier":"T1","invalidatedBy":["src/**","tests/**"],"maxRuns":1}]}
}
```

## Audit Matrix

Verify ownership, request/token construction, response bounds, redaction, and regression coverage.

## Paired Check Procedure

Run the paired commands, fix only in-scope findings, and record exact branch/parent heads.

## Final Gate Procedure

Confirm all acceptance criteria and no out-of-scope paths changed.
