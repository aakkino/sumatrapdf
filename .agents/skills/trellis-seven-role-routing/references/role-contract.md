# Trellis Seven-Role Contract

| Role | Default route | Trigger | Write boundary | Context | Proof |
| --- | --- | --- | --- | --- | --- |
| research | `exploration` | Missing repository or external evidence | Active task `research/` only | Native research context | Persisted source-indexed report |
| implement | `bounded_worker`; `hard_implementation` when classified hard | Reviewed implementation unit | Assigned paths | Implementation family | Artifacts and focused checks |
| check | `checking_sol_medium`; `checking` as a legacy default-lane alternative; `hard_checking` after hard implementation | Completed implementation needs verification | Task scope; must fix all in-scope findings and revalidate without an implement handoff | Check family | Fixed findings, blockers, and validation results |
| final-check | `final_gate` | All paired checks and spec update are complete | Read-only | Check family plus baseline and evidence | `ready` or `blocked` |
| debug | `debugging` | Reproducible failure or failed prior fix | Assigned failure scope | Implementation family | Reproduction, root cause, regression proof |
| review | `review` | Independent judgment after checks | Read-only | Check family | Severity-ordered file:line findings |
| audit | `audit` | High-risk or cross-boundary traceability | Read-only | Check family | Requirement/risk/evidence trace |
| release | `release` | Release-readiness decision | Read-only | Check family plus operator evidence | `ready` or `blocked` only |

## Dispatch Contract

The main session must include:

1. `Active task: <task-path>` as the first line.
2. The exact role, model route, and bounded responsibility.
3. Repository-relative owned paths.
4. Dependencies that must complete first.
5. Expected artifacts.
6. Executable or inspectable proof.

Completion text is not proof. The main session verifies artifacts and commands
before integration. No child role may commit, push, merge, archive a task, or
spawn another Trellis role.

Only a completed implementation unit triggers its one paired check stage. The checker owns its
in-scope fix-and-revalidate loop; checker edits never trigger another implement
or check dispatch. Only a missing product decision, new authority, or an
out-of-scope path is reported as a blocker.
A failed or terminated checker is retried as the same stage. The separate
final-check role follows paired-check closure, uses only check.md finalGate
commands, and never edits or creates a role loop.

## Context Families

- Implementation family: `implement.jsonl`, every real referenced spec or
  research file, `prd.md`, optional `design.md`, optional `implement.md`.
- Check family: `check.jsonl`, every real referenced spec or research file,
  `prd.md`, `design.md`, `implement.md`, `check.md`, baseline, and evidence.
- Final-check family: Check family plus the frozen candidate digest.
- Custom roles read the exact task path from the dispatch prompt. If it is
  missing or invalid, they stop and ask the main session. They never guess or
  borrow another session's active task.

## Channel Adapter

Channel roles use `.trellis/agents/<role>.md` and are separate from platform
profiles. The main session supplies the active task plus explicit `--file` or
`--jsonl` context. Prefer direct Codex read-only roles when the filesystem
boundary must be enforced; Channel read-only cards are instruction boundaries.
