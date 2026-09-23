# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "selfFix": {"allowedPaths": ["src/TranslationConfig.cpp", "src/SelectionTranslate.cpp", "tests/translation-config.ts", "tests/selection-translate-popup.ts", "docs/md/Customize-search-translation-services.md"], "allowedIssueClasses": ["scope", "format", "targeted-test"], "maxRounds": 2},
  "paired": {"maxTier": "T2", "commands": [{"id":"build","argv":["bun","cmd/build.ts","-debug"],"tier":"T2","invalidatedBy":["src/**"],"maxRuns":2},{"id":"config-test","argv":["bun","tests/translation-config.ts","--no-build"],"tier":"T1","invalidatedBy":["src/**","tests/**"],"maxRuns":3},{"id":"popup-test","argv":["bun","tests/selection-translate-popup.ts","--no-build"],"tier":"T1","invalidatedBy":["src/**","tests/**"],"maxRuns":2},{"id":"diff-check","argv":["git","diff","--check"],"tier":"T1","invalidatedBy":["src/**","tests/**","docs/**"],"maxRuns":2}]},
  "finalGate": {"maxTier": "T1", "commands": [{"id":"config-test","argv":["bun","tests/translation-config.ts","--no-build"],"tier":"T1","invalidatedBy":["src/**","tests/**"],"maxRuns":1},{"id":"popup-test","argv":["bun","tests/selection-translate-popup.ts","--no-build"],"tier":"T1","invalidatedBy":["src/**","tests/**"],"maxRuns":1}]}
}
```

## Audit Matrix

Verify labels, persistence compatibility, popup lifecycle preservation, and documentation scope.

## Paired Check Procedure

Run paired commands, fix only owned-path issues, and record exact branch/parent heads.

## Final Gate Procedure

Confirm all acceptance criteria and no changes outside the child contract.
