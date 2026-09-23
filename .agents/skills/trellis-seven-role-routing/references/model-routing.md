# Trellis Seven-Role Model Routing Contract

## Route Table

| Route | Model | Effort | Intent |
| --- | --- | --- | --- |
| `micro` | `gpt-5.3-codex-spark`; fallback `gpt-5.6-terra` | Spark `medium`; fallback Terra `low` | Tiny mechanical work |
| `exploration` | `gpt-5.6-terra` | `medium` | Evidence and codebase exploration |
| `bounded_worker` | `gpt-5.6-terra` | `high` | Default bounded worker |
| `checking_sol_medium` | `gpt-5.6-sol` | `medium` | Default-lane verification and self-fix |
| `checking` | `gpt-5.6-terra` | `max` | Legacy default-lane verification alternative |
| `hard_checking` | `gpt-5.6-sol` | `xhigh` | Verification after difficult or cross-boundary implementation |
| `coordination` | `gpt-5.6-sol` | `medium` | Main-session coordination |
| `debugging` | `gpt-5.6-sol` | `low` | Reproduction-first debugging |
| `planning` | `gpt-5.6-sol` | `medium` | Requirements and implementation planning |
| `hard_implementation` | `gpt-5.6-sol` | `medium` | Difficult implementation |
| `review` / `audit` / `release` | `gpt-5.6-sol` | `high` | Correctness, traceability, and readiness gates |
| `final_gate` | `gpt-5.6-sol` | `high` | Read-only frozen-candidate readiness decision |
| `memory_worker` | `gpt-5.6-terra` | `medium` | Memory search and extraction |
| `curator` | `gpt-5.6-sol` | `medium` | Memory synthesis and durable curation |

## Seven-Role Mapping

- `trellis-research` uses `exploration`.
- `trellis-implement` classifies work as `default` or `hard`; its persisted
  `dispatch:implement:default` and `dispatch:implement:hard` lanes resolve to
  `bounded_worker` and `hard_implementation` respectively. Use `hard` only
  when work is ambiguous, cross-boundary, or requires difficult multi-step
  judgment.
- `trellis-check` uses the matching persisted `dispatch:check:default` or
  `dispatch:check:hard` lane. The default lane resolves to
  `checking_sol_medium` unless explicitly migrated to the approved legacy
  `checking` alternative; the hard lane resolves to `hard_checking`.
- `trellis-debug` uses `debugging`.
- `trellis-review`, `trellis-audit`, and `trellis-release` use their matching
  high-effort Sol routes.
- `trellis-final-check` uses the project-local pinned `final_gate` route.

The main session uses `coordination` as a pure coordinator for active
implementation tasks: it dispatches every substantive implementation,
configuration, test, documentation, and spec change, but does not perform
those changes itself. Before doing substantive Trellis planning, select
`planning`; this is a main-session model choice, not an eighth Trellis role.
Micro uses Codex's built-in bounded worker unless the main session is
already running the resolved micro model/effort. Memory routes likewise use a
built-in bounded worker or the main session, not a new Trellis role.

A skill cannot silently change the model of an already-running main thread.
Use the app/CLI model control before planning, or start a planning thread with
Sol/medium. Do not claim the planning route was applied when the active thread
still uses the coordination default.

## Resolution Rules

Codex resolves custom-agent model settings independently. A model or effort in
the agent profile wins. Otherwise an explicit spawn override wins, then the
project `[agents]` default, then the parent session.

The project sets the main default to Sol/medium and the sub-agent default to
Terra/high. Immediately before every native Codex implement/check spawn,
resolve the classified lane from `.codex/trellis-dispatch.toml` with
`resolve_dispatch_lane(root, role, lane)` and pass the returned exact `model`
and `effort` as the spawn override. The per-turn `<trellis-dispatch>` list is
visibility, not cached authority; invoke the resolver again immediately before
the native spawn. The resolver accepts only the catalogued
pair for that lane; missing files/tables/fields, malformed TOML, non-string
values, custom pairs, and cross-family pairs block the spawn without fallback.
The native implement and check profiles remain unpinned so profile precedence
cannot shadow those explicit overrides. Research is pinned to Terra/medium;
debug and the three read-only assurance roles are pinned in their
project-owned profiles.

Lane resolution does not create a role loop. Only a completed implementation
unit triggers its one paired check; checker fixes and revalidation remain in
that same stage and trigger neither another implement nor another check. Retry
a failed or terminated checker as the same stage. The read-only final gate is
separate and may use only its explicit finalGate command budget.

## Spark Fallback

Before selecting `micro`, inspect the current Codex model catalog and spawn
surface. Use `gpt-5.3-codex-spark` at medium only when both expose it for the
current account. Otherwise use `gpt-5.6-terra` at low. Do not retry an
unavailable Spark route in a loop. As of the 2026-08-05 verification, Spark is
absent from this account's catalog, so the effective micro route is Terra/low.

## Channel Boundary

This contract is enforced by direct Codex profiles and spawn overrides.
`trellis channel spawn` accepts `--model` but has no reasoning-effort flag, and
Channel role cards do not inherit direct-agent profiles. Use direct Codex when
the exact model/effort pair is required. A Channel dispatch must state any
model override explicitly and must not claim effort enforcement it cannot
prove.
