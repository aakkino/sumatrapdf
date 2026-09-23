# Technical Design

## Architecture

Treat `Visibility::Collapse` as a subtree boundary when collecting top-level
virtual controls. Keep the behavior in shared `VirtCtrl` traversal rather than
adding provider-specific label visibility state.

## Lifecycle and State

Collection is rebuilt after layout changes. A collapsed node and all of its
descendants must remain absent until the node becomes visible again.

## Compatibility and Ownership

Change only `src/gui/VirtCtrl.cpp`, including its colocated unit tests. Preserve
existing traversal behavior for visible layouts and nested `VirtCtrl` roots.
