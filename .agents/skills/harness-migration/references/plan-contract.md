# Plan Contract

Run the source template runner with explicit roots:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" plan --template $template --target $target --format json --output $plan
```

For a fresh target, add `--developer <name>`. Do not add `--developer` for an
existing Trellis target. A target with only `.codex/`, or with a malformed
`.trellis/` footprint, is `unsupported_partial`, not fresh. Treat the CLI's
`targetState` as authoritative and stop if it differs from the requested flow.
Planning is non-mutating apart from the explicitly requested plan file.
The `plan` command accepts optional `--profile <name>`. Omitting it selects the
manifest-owned `complete` profile. Use another profile only when its narrower
scope matches the reviewed migration request; unknown profile names are
rejected.

`agent-workflow` is a closed literal-file profile for an existing Trellis
target. Its applicability requires `existing_trellis` plus semantic capability
`codex-dispatch-workflow-v1`. A successful plan uses schema 6 and adds closed,
digest-bound `prerequisiteEvidence` for the checked files, four persisted
dispatch lanes, hooks, and role definitions. Apply rebuilds that evidence from
live target files during canonical replay before creating a backup or mutating
the target. Admission failures are structured and point to the broader
`dispatch-only` remediation profile.

The profile does not select `.trellis/.template-hashes.json`, and apply does not
rewrite it. Its literal actions do not consume Copier answers, render Jinja,
depend on Git template tags, or execute template tasks or migrations.

For the narrow direct-adoption flow, invoke the same normal planner with the
only permitted partial-state opt-in:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" plan --template $template --target $target --profile complete --adopt-partial --format json --output $plan
```

This requires exactly `unsupported_partial`; it rejects fresh, existing,
unsafe, linked, non-Git, dirty, or session-active targets before backup or a
target write. `--profile complete` must be supplied explicitly for adoption,
even though an ordinary plan defaults to `complete`. It has no baseline
argument and never reads historical backups.

The JSON plan is an integrity-checked document. Its top-level fields are
`schemaVersion`, `templateVersion`, `templateRoot`, `targetRoot`,
`targetState`, `developer`, `manifestDigest`, `profile`, `actions`, `blockers`,
`conflicts`, `decisions`, `verificationCommands`, `sourceAdmission`, and
`planDigest`. `sourceAdmission` is canonical release provenance, `unproven`,
or the explicit `development-only` exception; it is part of the digest and
normal apply requires validated release provenance. A schema-2 direct-adoption
plan additionally has the required boolean `adoptPartial`.
Do not
hand-edit it: `resolve` validates and re-digests it. The selected `profile` is
part of `planDigest`, and `apply` rebuilds that same profile canonically before
any target write; `adoptPartial`, the partial input state, and `complete`
profile are included in that replay.

Each action has `path`, `kind`, `operation`, `reason`, `sourceDigest`,
`targetDigest`, `destination`, `destinationDigest`, and `decisionId`.
`destination`, `destinationDigest`, and `decisionId` are `null` when not
applicable. Valid kinds are `replaceable_managed`, `merge_required`,
`preserve`, `runtime_excluded`, `fresh_only_skeleton`, and `support_only`.
A sidecar destination is incoming content that requires a manual merge, not a
completed merge.

Each decision has `id`, `paths`, `reason`, `allowedChoices`, and `selection`.
Offer only the choices listed in that particular plan. Common choices have
these effects:

- `install`, `replace`, or `snapshot`: install incoming content; `snapshot`
  adopts the paired official `.trellis/.version` and template-hash baseline.
- `sidecar`: write incoming content as `<path>.harness-new`, preserving the
  target file for manual reconciliation.
- `keep`, `preserve`, or `skip`: retain target content or leave the incoming
  content uninstalled.

The official-baseline decision is paired: preserving the target baseline is
the conservative existing-project choice; selecting `snapshot` requires the
CLI's snapshot-parity validation. Security settings in `.codex/config.toml`,
existing hooks, target instructions, specs, and package configuration need a
user decision rather than a default migration choice.

Resolve only user-selected plan entries:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" resolve --plan $plan --decision '<id>=<choice>' --output $resolvedPlan
```

Repeat `--decision` only for distinct IDs from that plan. Re-run planning if
the CLI reports a stale or invalid plan.

## Unsupported Partial Recovery

Recovery is a separate, baseline-bound transaction:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" recover-plan --template $template --target $target --baseline $baseline --format json --output $recoveryPlan
python "$template/.trellis/scripts/harness_migrate.py" recover-resolve --plan $recoveryPlan --decision '<id>=<choice>' --output $resolvedRecoveryPlan
python "$template/.trellis/scripts/harness_migrate.py" recover-apply --plan $resolvedRecoveryPlan --approve --backup $recoveryBackup --format json
```

`recover-plan` accepts only the CLI-classified `unsupported_partial` state and
only an explicitly named direct `.trellis/.backup-*` directory. It validates
the baseline tree shape, version, `.trellis/.template-hashes.json` contents,
developer compatibility, and canonical containment. The closed recovery plan
fields are `schemaVersion`, `transactionType`, `templateVersion`,
`templateRoot`, `targetRoot`, `targetState`, `baselineRoot`,
`baselineVersion`, `baselineDigest`, `baselineAudit`,
`quarantinedTargetStates`, `manifestDigest`, `actions`, `blockers`, `conflicts`,
`decisions`, `verificationCommands`, and `planDigest`.

`baselineAudit.hashStatus` is `verified` with an empty `quarantinedPaths`
array when all recorded hashes match. An exact normalized mismatch whose
most-specific current complete-manifest rule is `merge_required` instead uses
`verified_with_quarantined_merge_required` and records the path, expected and
actual `sha256:` digests, `merge_required`, and fixed reason
`baseline_digest_mismatch_merge_required`. Every other mismatch blocks.
`quarantinedTargetStates` binds the same sorted path set with equal pre/post
digests (including `missing`). Both structures are closed and plan-digested.

Recovery considers only files present in both the baseline and current
manifest-owned `complete` export. It excludes support-only, runtime, preserve,
fresh-skeleton, project spec, task, workspace, developer, current-task, and
runtime paths. It also removes quarantined paths before building actions or
decisions, so their baseline bytes cannot be staged, sidecarred, journaled, or
restored. Existing collisions expose only `sidecar`, `keep`, and `replace`.
Apply canonically rebuilds the same recovery plan and audit, and proves each
quarantined live path still equals its recorded pre/post state before creating
an external backup or writing the target.

Use normal `verify --receipt ...` and separately authorized `rollback
--receipt ... --approve` with a recovery receipt. After successful recovery,
discard every pre-recovery normal plan and generate a fresh normal plan; the
recovery transaction does not authorize that plan or its apply. The recovery
receipt repeats `baselineAudit` and `quarantinedTargetStates`; verification
checks those actionless paths before and after commands. Rollback refuses a
changed quarantined target and never restores quarantined baseline bytes.
