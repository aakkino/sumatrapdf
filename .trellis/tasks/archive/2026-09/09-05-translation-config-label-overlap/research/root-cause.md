# Root Cause

- `TranslationConfigWnd::ProviderChanged()` collapses inactive provider group
  containers and separately hides their native Edit controls.
- Layout skips collapsed groups, but `CollectVirtCtrls()` recursively visits
  every layout child without checking collapsed visibility.
- Inactive `VirtText` descendants retain old bounds and remain in the host's
  paint list, overlapping the active provider labels.
- The existing configuration test verifies logical/native visibility but not
  virtual paint-list membership.
