# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "selfFix": {"allowedPaths": [".trellis/spec/backend/translation-service.md", ".trellis/spec/frontend/selection-translation-popup.md"], "allowedIssueClasses": ["spec-compliance", "format", "scope"], "maxRounds": 2},
  "paired": {"maxTier": "T1", "commands": [{"id":"diff-check","argv":["git","diff","--check"],"tier":"T1","invalidatedBy":[".trellis/spec/**"],"maxRuns":2}]},
  "finalGate": {"maxTier": "T1", "commands": [{"id":"diff-check","argv":["git","diff","--check"],"tier":"T1","invalidatedBy":[".trellis/spec/**"],"maxRuns":1}]}
}
```

## Audit Matrix

Verify the specs describe shipped IDs, names, endpoint boundaries, UI visibility, and focused test contracts.

## Paired Check Procedure

Run diff check and repair only owned spec paths.

## Final Gate Procedure

Confirm no unrelated spec or source paths changed.
