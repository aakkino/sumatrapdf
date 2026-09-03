# Seven-Role Routing And Dispatch Contract

## 1. Scope / Trigger

Use this contract whenever the main session selects a Trellis role or splits a
task into more than one work unit. Role selection is behavioral policy, not a
separate scheduler or task identity.

Micro work uses the built-in Codex bounded worker unless the main session is
already running the resolved micro model/effort. Research, implementation, and
checking use the Trellis-managed native roles. Debug, review, audit, and
release use the project-local Codex profiles under `.codex/agents/`.

Codex implementation and checking additionally trigger persistent lane
resolution. Classify each unit as `default` or `hard`, then resolve the matching
lane immediately before its native spawn. A previously injected lane summary is
visibility only and is never dispatch authority.

## 2. Signatures

Every direct or Channel dispatch starts with this brief:

```text
Active task: <repository-relative task path>
Role: <research|implement|check|debug|review|audit|release>
Route: <model route from the route table>
Owned paths: <repository-relative paths, or read-only>
Depends on: <work-unit identifiers, or none>
Expected artifacts: <files or decision report>
Proof: <commands or inspectable evidence>
```

For Channel, the equivalent execution signature is:

```powershell
trellis channel spawn --agent <role> --file <path> --jsonl <manifest>
```

The main session supplies only applicable `--file` and `--jsonl` arguments and
includes the active-task line in the worker message.

Persistent Codex lane resolution uses these Python boundaries:

```python
resolve_dispatch_lane(root: Path | str,
                      role: str,
                      lane: str) -> DispatchRoute
resolve_all_dispatch_lanes(root: Path | str) -> tuple[DispatchRoute, ...]

DispatchRoute(role: str, lane: str, route: str, model: str, effort: str)
DispatchRouteResolutionError(role: str, lane: str, reason: str)
```

The supported `role` values are exactly `implement` and `check`; the supported
`lane` values are exactly `default` and `hard`. Unsupported values fail with
`DispatchRouteResolutionError` rather than widening the route catalog.
`DispatchRoute.scope` is `dispatch:<role>:<lane>`. The native spawn receives
`DispatchRoute.model` as `model` and `DispatchRoute.effort` as
`reasoning_effort`.

## 3. Contracts

### Role contract

| Need | Role | Model route | Write boundary | Context family | Required proof |
| --- | --- | --- | --- | --- | --- |
| Persist missing evidence | `trellis-research` | `exploration` | Active task `research/` | Native research | Source-indexed report |
| Implement reviewed work | `trellis-implement` | `bounded_worker` or `hard_implementation` | Assigned paths | Implementation | Artifacts and focused checks |
| Verify and self-fix | `trellis-check` | `checking_sol_medium` by default; legacy `checking` alternative; `hard_checking` for hard work | Task scope | Check | Findings and validation results |
| Reproduce and fix a failure | `trellis-debug` | `debugging` | Assigned failure scope | Implementation | Reproduction, root cause, regression proof |
| Independent correctness review | `trellis-review` | `review` | Read-only | Check | Severity-ordered file:line findings |
| Requirement/risk/evidence trace | `trellis-audit` | `audit` | Read-only | Check | Requirement/risk/evidence trace |
| Release-readiness decision | `trellis-release` | `release` | Read-only | Check plus operator evidence | `ready` or `blocked` |

### Model route contract

| Route | Model | Effort | Intent |
| --- | --- | --- | --- |
| `micro` | `gpt-5.3-codex-spark`; fallback `gpt-5.6-terra` | `medium`; fallback `low` | Tiny mechanical work |
| `exploration` | `gpt-5.6-terra` | `medium` | Exploration |
| `bounded_worker` | `gpt-5.6-terra` | `high` | Default bounded worker |
| `checking_sol_medium` | `gpt-5.6-sol` | `medium` | Default-lane verification and self-fix |
| `checking` | `gpt-5.6-terra` | `max` | Legacy default-lane verification alternative |
| `hard_checking` | `gpt-5.6-sol` | `xhigh` | Check difficult or cross-boundary implementation |
| `coordination` | `gpt-5.6-sol` | `medium` | Main-session coordination |
| `debugging` | `gpt-5.6-sol` | `low` | Debugging without default max |
| `planning` | `gpt-5.6-sol` | `medium` | Planning |
| `hard_implementation` | `gpt-5.6-sol` | `medium` | Difficult implementation |
| `review` / `audit` / `release` | `gpt-5.6-sol` | `high` | Assurance gates |
| `memory_worker` | `gpt-5.6-terra` | `medium` | Memory search and extraction |
| `curator` | `gpt-5.6-sol` | `medium` | Memory synthesis and curation |

The project Codex config sets the main default to Sol/medium and the spawned
agent default to Terra/high. The native implement and check profiles stay
unpinned so explicit spawns can select the persisted lane. A profile pin has
higher precedence than the explicit spawn override and would silently shadow
this contract. Research pins
Terra/medium, and debug/review/audit/release profiles pin their invariant model
routes.

### Persistent implement/check lanes

`.codex/trellis-dispatch.toml` is the Harness-managed source of truth:

| Scope / table | Named route | Model / effort |
| --- | --- | --- |
| `dispatch:implement:default` / `[implement.default]` | `bounded_worker` | `gpt-5.6-terra` / `high` |
| `dispatch:implement:hard` / `[implement.hard]` | `hard_implementation` | `gpt-5.6-sol` / `medium` |
| `dispatch:check:default` / `[check.default]` | `checking_sol_medium` | `gpt-5.6-sol` / `medium` |
| `dispatch:check:hard` / `[check.hard]` | `hard_checking` | `gpt-5.6-sol` / `xhigh` |

`checking` remains an approved named alternative for `dispatch:check:default`.
A route-only migration may select a named route or an explicit custom
model/effort pair. Each table requires the string fields `model` and
`model_reasoning_effort`. The migration `ROUTE_CATALOG` is the sole authority
for allowed named pairs; the runtime resolver imports it rather than carrying a
second catalog. The four lanes are independent: one invalid lane blocks only a
spawn that consumes that lane, while the workflow hook reports every lane as
resolved or `BLOCKED` without failing unrelated prompt handling.

Runtime resolution is fail-closed for structure and safety. Missing/unsafe
files, malformed or non-UTF-8 TOML, missing/invalid tables, and absent or
non-string fields raise
`DispatchRouteResolutionError`. Its message identifies
`.codex/trellis-dispatch.toml`, the exact scope, and a machine-readable reason.
There is no fallback to workflow prose, inherited sub-agent defaults, or a
cached `<trellis-dispatch>` value.

The closed reason vocabulary is `unsupported_role`, `unsupported_lane`,
`invalid_root`, `unsafe_path`, `path_parent_not_directory`, `unreadable_path`,
`missing_file`, `not_regular_file`, `non_utf8_toml`, `unreadable_file`,
`malformed_toml`, `missing_table`, `invalid_table`,
`missing_model_and_effort`, `missing_model`, `missing_effort`,
`model_not_string`, `effort_not_string`, `model_empty`, `effort_empty`, and
`unsupported_scope`. A pair that
does not match the selected scope's named catalog resolves successfully with
route label `custom`; the exact persisted model and effort are passed to the
native spawn.

Spark is availability-gated. The main session checks both the current Codex
model catalog and spawn surface before selecting it and falls back once to
Terra/low when either does not expose it. It must not loop retries or silently
substitute another model.

Planning and coordination describe the main session, not additional Trellis
roles. A project skill cannot hot-switch an already-running main thread, so
planning selects Sol/medium through the app/CLI model control or a new planning
thread. Micro and memory routes may use built-in bounded workers and do not
expand the seven-role set.

### Main-session ownership

The Sol/medium main session is coordination-only. It may select roles,
dispatch work, coordinate dependencies, verify evidence, integrate results,
commit, or run finish-work, but it must not directly modify implementation,
configuration, test, documentation, or spec files for an active task. Every
independent implementation unit is dispatched to `trellis-implement` and then
to `trellis-check`; dispatch `trellis-research` when evidence is missing.
A child role performs its assigned work directly and must not spawn another
Trellis role.

The check is a single post-implementation stage, not the start of a role loop.
Only completion of an implementation unit triggers its paired check. That
checker must fix every finding inside its assigned task/path authority and
rerun validation itself. Its edits trigger neither another `trellis-implement`
nor another `trellis-check`. A missing product decision, new authority, or an
out-of-scope path is a reported blocker; it does not automatically bounce the
work back to implement.
A failed or terminated checker is retried as the same paired stage. The
read-only `trellis-final-check` follows paired-check closure and may execute
only the explicit finalGate commands in check.md.

At most three independent units may run concurrently. Concurrent units must
not have overlapping ownership. Reusing a path is allowed only when dependency
ordering prevents simultaneous writes. Completion messages are not proof; the
main session verifies artifacts and commands before integration.

For every dispatch, record the selected route. Codex model resolution follows:
agent-profile pin, explicit spawn override, project `[agents]` default, then
parent session. For implement/check, the coordinator invokes
`resolve_dispatch_lane(root, role, lane)` afresh immediately before native
spawn and passes the exact returned pair. The corresponding check uses the same
lane classification as its implementation. Because a profile pin wins, both
native profiles must remain unpinned.

### Context families

- Implementation: `implement.jsonl`, every real referenced file, `prd.md`,
  optional `design.md`, and optional `implement.md`. Debug uses this family.
- Check: `check.jsonl`, every real referenced file, `prd.md`, `design.md`,
  `implement.md`, `check.md`, baseline, and evidence. Review, audit, and
  release use this family. Final-check also reads the frozen candidate digest.
- Native roles keep their Trellis-managed context behavior. Custom roles pull
  only from the exact task path in the first prompt line.

### Optional Channel adapter

Use direct platform sub-agents for isolated work. Use `trellis channel` only
for durable multi-round messages, progress inspection, interruption, or
cross-provider collaboration. Channel loads `.trellis/agents/<name>.md`; it
does not inherit `.codex/agents/` profiles or direct-agent hook context.

Bundled `implement` and `check` cards remain Trellis-managed. Research, debug,
review, audit, and release cards are project-local adapters. A read-only
Channel card is an instruction boundary, not an enforced Codex sandbox.

Channel supports a model override but no reasoning-effort flag. Use the direct
Codex path whenever the exact model/effort pair is required. Never report a
Channel effort as enforced without provider-level evidence.

### Permission boundaries

- Research writes only under the active task's `research/` directory.
- Implement writes only inside assigned ownership.
- Check must fix all findings inside its assigned task/path authority and
  revalidate them in the same stage; it must not hand them back to implement.
- Debug is workspace-write, reproduces first, applies the narrowest fix, and
  adds regression proof.
- Review, audit, release, and final-check use read-only Codex sandboxes.
- Release never tags, publishes, deploys, contacts an external system, or
  treats readiness as authorization.

## 4. Validation & Error Matrix

| Condition | Required behavior |
| --- | --- |
| `Active task:` is missing or invalid | Stop and ask the main session; do not infer another task |
| Manifest is missing or contains a nonexistent file | Stop and report the exact missing path |
| Two concurrent units own the same path | Serialize them with an explicit dependency |
| A child attempts another dispatch | Refuse; return control to the main session |
| A read-only role needs a fix | Report the finding; do not edit |
| Release evidence is incomplete | Return `blocked` with exact blockers |
| Channel requires enforced filesystem read-only | Use the direct Codex role instead |
| Proof command fails | Report failure; do not claim completion |
| Spark is absent from the current model catalog | Select Terra/low once; do not retry Spark |
| A route requires an exact effort through Channel | Use direct Codex or report the unenforced boundary |
| Routine implement becomes ambiguous or cross-boundary | Reclassify to `hard_implementation` before dispatch |
| Role or lane selector is unsupported | Block with `unsupported_role` or `unsupported_lane` |
| Root or dispatch path is invalid, unsafe, unreadable, or non-regular | Block with the matching closed path reason; do not read through a link or fallback |
| Dispatch file, selected table, or required field is missing/invalid | Block that implement/check spawn with the matching closed file/table/field reason; do not fall back |
| Selected pair is valid TOML but does not match the scope's named catalog | Resolve it as `custom` and pass the exact pair |
| Workflow hook cannot resolve one lane | Emit that lane as `BLOCKED`; continue the unrelated prompt and show other lane results |
| Implement/check profile gains a model pin | Reject the configuration because profile precedence shadows persisted lanes |
| Check finds an issue inside assigned scope | Fix it directly and rerun validation in the same check stage; do not dispatch implement or another checker |
| Check needs a missing product decision, new authority, or an out-of-scope path | Report an exact blocker to the coordinator; do not start a role loop |

## 5. Good / Base / Bad Cases

- Good: The main session sends `trellis-debug` one owned failure scope, a real
  task path, the `debugging` route, implementation context, and a reproduction
  command. Debug runs Sol/low, fixes the cause, and returns a regression test
  plus rerun output.
- Good: Immediately before a hard implementation spawn, the coordinator resolves
  `dispatch:implement:hard`, passes its exact Sol/medium pair, then resolves
  `dispatch:check:hard` afresh and passes the returned checking pair. The
  checker fixes its in-scope findings and reruns verification without another
  role dispatch.
- Base: Outside an active Trellis implementation task, a small direct edit may
  stay in the main session and use normal check/finish gates. Within an active
  task, a default implementation is dispatched through `implement.default`;
  its checker consumes `check.default`.
- Base: A legacy target without `.codex/trellis-dispatch.toml` can still handle
  unrelated prompts and inspect routes, but its implement/check spawn is blocked
  until migration, route-only creation, or manual repair installs a valid lane.
- Bad: A review role guesses the current task, edits the defect it finds, or
  uses the Terra default instead of its pinned Sol/high assurance route.
- Bad: The coordinator trusts an earlier injected lane summary, inherits the
  project sub-agent default, or pins the implement/check profile. Any of these
  makes persisted state non-authoritative.

## 6. Tests Required

- Assert Trellis-managed hashes include only the native three Codex profiles
  and bundled Channel implement/check cards.
- Parse every custom TOML profile and assert sandbox, context family, no-spawn
  boundary, and pinned model route.
- Parse project Codex config and assert Sol/medium main and Terra/high
  sub-agent defaults, a non-empty string model/effort research pin, and
  unpinned implement and check profiles that accept explicit route overrides.
- Assert workflow, project instructions, native/Channel check cards, and hook
  prelude all require one post-implementation check stage, direct in-scope
  fixes, self-revalidation, and no check-to-implement/check dispatch.
- Assert every orchestration surface preserves same-stage retry, then exposes
  a read-only final-check whose commands are limited by check.md finalGate.
- Parse `.codex/trellis-dispatch.toml` and assert the four tables and exact
  default pairs. Assert the export manifest ships the file, resolver, and route
  catalog dependency in both complete export and `dispatch-only` migration.
- Unit-test `resolve_dispatch_lane` for all four happy paths and exact
  `DispatchRoute` fields. Assert every closed reason name documented above,
  including selection, root/path, file/TOML, table, field, and
  `unsupported_scope`, fails closed with file, scope, and reason. Assert
  uncatalogued and cross-catalog string pairs resolve with route `custom` and
  retain the exact model and effort.
- Test workflow injection with all lanes valid and with mixed valid/invalid
  lanes. Assert stable implement-default, implement-hard, check-default,
  check-hard order; per-lane `BLOCKED` diagnostics; and normal prompt output
  even when resolver import or configuration parsing fails.
- Static-contract tests must assert workflow and project instructions require
  a fresh `resolve_dispatch_lane(root, role, lane)` call immediately before
  spawn and pass exact `model` / `reasoning_effort`; injected context must be
  described as visibility rather than cached authority.
- Assert the route table covers micro fallback, exploration, bounded work,
  coordination, debugging, planning, hard implementation, assurance, and
  memory routes.
- Assert the native Codex hook matcher remains limited to
  research/implement/check.
- Assert the project skill and Channel cards represent all seven roles.
- Assert legacy plugin entry points and live contract references are absent.
- Run `trellis update --dry-run` and verify custom role files are not reported
  as Trellis-managed conflicts.

## 7. Wrong vs Correct

Wrong:

```text
Please review the current task and fix anything you find.
```

Also wrong for Codex implement/check dispatch:

```python
# Stale injected context or inherited defaults are not dispatch authority.
spawn_agent(agent_type="trellis-implement")
```

Correct:

```text
Active task: .trellis/tasks/08-05-example
Role: review
Route: review
Owned paths: read-only
Depends on: check-1
Expected artifacts: severity-ordered findings with file:line evidence
Proof: inspect check.jsonl entries and recorded validation output
```

Correct pre-spawn resolution:

```python
resolved = resolve_dispatch_lane(root, "implement", lane)
spawn_agent(
    agent_type="trellis-implement",
    model=resolved.model,
    reasoning_effort=resolved.effort,
    message=brief,
)
```

The correct brief selects an exact context, preserves the role's permission
boundary, and gives the main session evidence it can independently verify.
