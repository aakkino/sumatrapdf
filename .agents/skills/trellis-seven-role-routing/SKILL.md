---
name: trellis-seven-role-routing
description: "Use when classifying or dispatching this project's Trellis research, implementation, checking, debugging, review, audit, or release-readiness work."
---

# Trellis Seven-Role Routing

Use Trellis's native roles for the standard path:

- `trellis-research` for persisted evidence gathering.
- `trellis-implement` for a reviewed implementation unit.
- `trellis-check` for specification checks, all in-scope fixes, and validation
  in one post-implementation stage. Its fixes do not route back to implement.
- `trellis-final-check` for the read-only frozen-candidate readiness decision
  after all paired checks and any spec update.

Use the project-local Codex roles only when their trigger is present:

- `trellis-debug` for a reproducible failure or failed prior fix.
- `trellis-review` for independent correctness judgment after mechanical checks.
- `trellis-audit` for high-risk requirement, policy, and evidence traceability.
- `trellis-release` for a read-only release-readiness decision.

The main session owns requirements, task trees, route selection, dispatch,
dependency ordering, result integration, commits, and finish-work. A dispatched
role must never spawn another Trellis role.

Only a completed implementation unit triggers its one paired check. The
checker owns in-scope fixes and contract-authorized evidence in that same
stage; its edits do not trigger another implement or check dispatch. Retry a
failed or terminated checker as the same stage. After paired-check closure,
the read-only final gate uses only the check.md finalGate budget. Missing
decisions, new authority, or out-of-scope work return to the main session.

Before dispatching, read [the role contract](references/role-contract.md) and
[the model routing contract](references/model-routing.md). Every dispatch
prompt starts with `Active task: <task-path>` and declares the route, owned
paths, dependencies, expected artifacts, and proof. Run at most three
independent units concurrently; overlapping ownership requires explicit
ordering.

Use a direct platform sub-agent for one isolated result. Load the bundled
`trellis-channel` skill only when the work needs durable multi-round messages,
progress inspection, interruption, or cross-provider collaboration.
