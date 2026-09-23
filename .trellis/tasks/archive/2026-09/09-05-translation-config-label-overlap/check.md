# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "protectedBaseline": "baseline.json",
  "selfFix": {
    "allowedPaths": ["src/gui/VirtCtrl.cpp"],
    "allowedIssueClasses": ["spec-compliance", "compile-error", "formatting", "targeted-test-failure", "ui-lifecycle"],
    "maxRounds": 2
  },
  "paired": {
    "maxTier": "T2",
    "commands": [
      {"id":"format","argv":["clang-format.exe","-i","src/gui/VirtCtrl.cpp"],"tier":"T1","invalidatedBy":["src/gui/VirtCtrl.cpp"],"maxRuns":2},
      {"id":"build","argv":["bun","cmd/build.ts","-debug"],"tier":"T2","invalidatedBy":["src/gui/VirtCtrl.cpp"],"maxRuns":4},
      {"id":"app-unit-tests","argv":["out/dbg64/SumatraPDF.exe","-unit-tests"],"tier":"T1","invalidatedBy":["src/gui/VirtCtrl.cpp"],"maxRuns":2},
      {"id":"config-test","argv":["bun","tests/translation-config.ts","--no-build"],"tier":"T1","invalidatedBy":["src/gui/VirtCtrl.cpp"],"maxRuns":3},
      {"id":"diff-check","argv":["git","diff","--check"],"tier":"T1","invalidatedBy":["src/gui/VirtCtrl.cpp"],"maxRuns":2}
    ]
  },
  "finalGate": {"maxTier": "T0", "commands": []}
}
```

## Audit Matrix

| Requirement | Evidence |
| --- | --- |
| AC1, AC3 | Colocated `CollectVirtCtrls_Test()` regression assertion |
| AC2, AC4 | Debug build and translation configuration test |
| AC5 | Shared traversal review plus existing DPI/RTL configuration coverage |

## Paired Check Procedure

Review the traversal boundary and test effectiveness, fix in-scope findings,
then run only the paired commands above.

## Final Gate Procedure

Freeze the checked candidate and perform a read-only contract/evidence review.
