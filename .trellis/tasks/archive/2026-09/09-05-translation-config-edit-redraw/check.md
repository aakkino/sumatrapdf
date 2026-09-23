# Check Contract

## Machine Contract

```json
{
  "schemaVersion": 1,
  "protectedBaseline": "baseline.json",
  "selfFix": {
    "allowedPaths": ["src/gui/win/WindowBase.cpp", "tests/ad-hoc-translation-config-edit-redraw.ts", "tests/winapi.ts", ".trellis/spec/frontend/selection-translation-popup.md"],
    "allowedIssueClasses": ["spec-compliance", "compile-error", "formatting", "targeted-test-failure", "ui-lifecycle"],
    "maxRounds": 2
  },
  "paired": {
    "maxTier": "T2",
    "commands": [
      {"id":"format","argv":["bun","cmd/format.ts"],"tier":"T1","invalidatedBy":["src/gui/win/WindowBase.cpp","tests/ad-hoc-translation-config-edit-redraw.ts","tests/winapi.ts"],"maxRuns":2},
      {"id":"build","argv":["bun","cmd/build.ts","-debug"],"tier":"T2","invalidatedBy":["src/gui/win/WindowBase.cpp"],"maxRuns":2},
      {"id":"frame-test","argv":["bun","tests/ad-hoc-translation-config-edit-redraw.ts","--no-build"],"tier":"T1","invalidatedBy":["src/gui/win/WindowBase.cpp","tests/ad-hoc-translation-config-edit-redraw.ts","tests/winapi.ts"],"maxRuns":3},
      {"id":"diff-check","argv":["git","diff","--check"],"tier":"T1","invalidatedBy":["src/gui/win/WindowBase.cpp","tests/ad-hoc-translation-config-edit-redraw.ts","tests/winapi.ts",".trellis/spec/frontend/selection-translation-popup.md"],"maxRuns":2}
    ]
  },
  "finalGate": {"maxTier": "T0", "commands": []}
}
```

## Audit Matrix

| Requirement | Evidence |
| --- | --- |
| AC1, AC2 | Screenshot/pixel assertion over both provider transitions |
| AC3 | Shared `ControlBase::SetVisibility()` diff review |
| AC4 | Debug build and three focused configuration-test passes |

## Paired Check Procedure

Verify the test observes painted Edit frame edges rather than visibility flags,
review generic child-control show/hide semantics, fix in-scope defects, then
run only the paired commands above.

## Final Gate Procedure

Freeze the checked candidate and perform a read-only contract/evidence review.
