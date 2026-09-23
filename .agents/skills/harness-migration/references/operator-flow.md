# Operator Flow

## Preflight

Use the source template runner throughout this operator flow; a fresh target
needs it at least until apply completes, before it contains the installed
runner. Pass both roots explicitly on every plan invocation. The CLI refuses
unsafe root relationships, non-Git targets, dirty worktrees at apply time,
active Trellis/Codex session state, malformed plans, and unresolved decisions.
There is no force mode.

Before authoring a source-template change, use `trellis platforms --json`, then
the source-only Harness `inspect --template <root> [--profile
agent-workflow] --format json`, then the relevant `trellis-meta` references and
actual local files. This authoring inspection is not target planning. For
distribution, start a fresh target plan and keep all target mutations inside
the transaction below.

`resolve` and `apply` take the saved plan rather than root arguments; `verify`
and `rollback` take the receipt. Do not add `--template` or `--target` to
those commands.

The target must have no worktree changes before apply. End active Trellis or
Codex sessions first. The CLI creates an external backup and receipt before it
modifies a migration-owned path; retain that backup until the migration has
been accepted.

For a reviewed `unsupported_partial` target, use the normal direct-adoption
plan. It is complete-profile-only, requires an explicit `--profile complete`,
and does not take or consult a baseline:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" plan --template $template --target $target --profile complete --adopt-partial --format json --output $plan
```

Review every normal decision and the full action matrix, then resolve and seek
explicit apply authorization for that exact resolved plan, backup path, and
receipt path. Stop on any blocker or failed/incomplete verification. The
separate historical recovery command family is optional and never a prerequisite
for direct adoption.

## Apply And Verify

After every decision has a valid selection and the user explicitly authorizes
the destructive operation, apply the resolved plan:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" apply --plan $resolvedPlan --approve --format json
```

Record the returned `receiptPath`, then verify it:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" verify --receipt $receipt --format json
```

Verification checks installed and preserved digests and runs the receipt's
Trellis context/task, test, and `trellis update --dry-run` commands. `success`
is the only completed status. `incomplete` means the target has unresolved
`.harness-new` sidecars; review and reconcile them as manual work. `failed`
means preserve the receipt and stop for investigation.

For new direct-adoption receipts, verification also checks filtered digests of
project-owned state before and after commands. Exact receipt-journal
destinations are excluded because their installed post-images have their own
checks; target-only project state and sidecar-retained originals remain
protected.

## Ownership And Compatibility

The migration policy preserves target task history, workspace journals,
developer identity, current-task state, and runtime sessions. It treats
`AGENTS.md`, project specs, skills, configuration, hooks registration, and
Codex sandbox/approval settings as merge decisions. It never installs source
runtime sessions or support-only export files into a business project.

The migrator does not run a mutating official update and never synthesizes
template hashes. Verification captures `trellis update --dry-run` so official
Trellis-managed differences remain visible for review.

For `agent-workflow`, the target `.trellis/.template-hashes.json` is outside the
selected action set and remains byte-identical through apply, verify, and
rollback. Project-local distributed files may legitimately have no official
hash entry. Do not replace this provenance boundary with Copier answers,
Jinja-rendered state, Git template versions, or executable template tasks or
migrations; those are outside the literal Harness transaction.

## Rollback

Rollback restores only the paths journaled in the receipt and refuses to
overwrite post-migration edits. Ask for explicit authorization immediately
before this command:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" rollback --receipt $receipt --approve --format json
```

When rollback refuses or verification fails, keep the external backup and
receipt intact. Do not attempt a manual restoration through the Skill.
