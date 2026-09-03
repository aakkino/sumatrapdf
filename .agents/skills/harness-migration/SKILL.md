---
name: harness-migration
description: "Migrate or refresh this Trellis Codex Harness in a separate Git project through its deterministic CLI; use for fresh installs or existing Trellis upgrades, not ordinary official trellis updates."
---

# Harness Migration

Use this skill when a user wants to install, migrate, refresh, or upgrade this
Harness in another project. Keep normal `trellis update` requests outside this
skill unless they are part of migration verification.

The migration CLI is the sole filesystem authority. Use the source template's
`.trellis/scripts/harness_migrate.py` throughout the migration. `plan`
establishes the explicit `--template` and `--target` roots; `resolve` and
`apply` consume its saved plan, while `verify` and `rollback` consume its
receipt. Do not append root arguments to commands that do not accept them, or
perform copying, deletion, ownership classification, backup creation, or
rollback outside that CLI.

For template authoring, compose native Trellis discovery, Harness inspection,
and existing meta guidance in this order:

```powershell
trellis platforms --json
python "$template/.trellis/scripts/harness_migrate.py" inspect --template $template --format json
```

Use `--profile agent-workflow` when the requested authoring scope is the exact
workflow distribution closure. `inspect` is source-only: it accepts no target,
does not build a plan or run admission, and performs no write or network
operation. Read its manifest-owned path/profile records, then consult the
relevant `trellis-meta` platform and customization references, inspect the
actual local files, and edit the template directly with focused tests. Do not
put Harness-private rules into the bundled `trellis-meta` skill.

The report uses `.trellis/.template-hashes.json` only as read-only provenance.
A tracked source is `official_unchanged`, `official_modified`, or
`official_missing`; an exported source without a hash entry is valid
`project_local` content. The manifest, not the hash map or meta prose, owns
profile membership.

`inspect` is structural, not a semantic cleanliness decision. Author journals,
tasks, research, runtime state, and caches may be valid authoring-root content
but must not be copied or archived as a reusable template. Build a separate,
deterministic release root with the release command family. It has its own
external backup and receipt, which is distinct from a business-target migration
backup: the release projection is versionable distribution content, while a
migration backup preserves one target's pre-migration bytes.

```powershell
python "$template/.trellis/scripts/harness_migrate.py" release-plan --authoring-template $template --release $release --format json --output $releasePlan
python "$template/.trellis/scripts/harness_migrate.py" release-apply --plan $releasePlan --approve --backup $releaseBackup --format json
python "$template/.trellis/scripts/harness_migrate.py" release-verify --receipt $releaseReceipt --format json
python "$template/.trellis/scripts/harness_migrate.py" release-rollback --receipt $releaseReceipt --approve --format json
```

Review the release plan before `release-apply`, request explicit authorization
for that destructive refresh, and retain its receipt until release verification
succeeds. These commands write only the declared release root and their external
backup/receipt; they never write the authoring root or a business target. A
normal business-target `apply` requires release provenance. For deliberate
development use, `plan --development-template` records the explicit exception
in the plan instead of allowing an apply-time bypass.

To inspect the configured routes without changing a target, run the target-only
read-only command. It does not require apply authorization:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" inspect-routes --target $target --format json
```

For a reviewed named route change, add one or more `--route <scope>=<route>`
values to `plan`. For an arbitrary model/effort combination, use repeatable
`--route-pair <scope>=<model>,<effort>` values together with `--route-only`.
When the request is limited to route-owned configuration, use `--route-only`
with at least one `--route` or `--route-pair`. It applies only to an
`existing_trellis` target and cannot be combined with an explicit `--profile`,
`--developer`, or `--adopt-partial`. It remains the same reviewed
plan -> resolve -> explicitly authorized apply -> verify transaction; never
edit the target route file directly.

For reviewed distribution of the workflow/check closure, use
`plan --profile agent-workflow` only as a separate target transaction. It
admits an `existing_trellis` target with capability
`codex-dispatch-workflow-v1`, binds its checked prerequisite evidence into a
canonical schema-6 plan, and preserves whole-file conflict decisions. The
profile excludes `.trellis/.template-hashes.json`; apply and rollback never
rewrite that target official baseline.

The profile copies literal bytes through existing Harness actions. It does not
read Copier answers, render Jinja, require Git template tags or smart-diff
lifecycle state, or execute template tasks or migrations. Do not introduce an
external template runtime, command, or network path while operating it.

The persistent Codex dispatch lanes accept these named mappings:

- `dispatch:implement:default=bounded_worker`
- `dispatch:implement:hard=hard_implementation`
- `dispatch:check:default=checking_sol_medium` (template default)
- `dispatch:check:default=checking` (approved legacy alternative)
- `dispatch:check:hard=hard_checking`

For example, plan a routine implement-lane update without selecting unrelated
migration content:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" plan --template $template --target $target --route-only --route dispatch:implement:default=bounded_worker --format json --output $plan
```

For example, select Terra/xhigh for research without adding a catalog name:

```powershell
python "$template/.trellis/scripts/harness_migrate.py" plan --template $template --target $target --route-only --route-pair role:research=gpt-5.6-terra,xhigh --format json --output $plan
```

For a deliberately reviewed partial target, use normal `plan --adopt-partial
--profile complete`. The profile flag is explicit for this flow even though
ordinary plans default to `complete`. It accepts only the CLI-classified `unsupported_partial`
state and uses only the current template and manifest export. It never takes a
baseline or reads a historical backup. Historical `recover-*` commands remain
a separate, optional workflow; they do not gate direct adoption.

1. Confirm the template and target roots. A target must be a Git worktree.
   Let `plan` report the target state; do not classify it from directory names.
   For an explicitly fresh migration, request the developer name; do not supply
   one for an existing Trellis target. If the reported state differs from the
   requested flow, or is unsafe, stop rather than guessing. For the explicit
   direct-adoption flow, use only `--adopt-partial --profile complete`.
2. Run `plan --format json --output <plan.json>` before discussing changes.
   Use `--profile <name>` only when the requested migration scope maps to a
   manifest-owned profile; omitting it preserves the default complete migration.
   Read [the plan contract](references/plan-contract.md) to interpret its
   structured output.
3. Stop when `blockers` is non-empty. Present `conflicts` and every unresolved
   `decisions` entry, then obtain a choice from that entry's `allowedChoices`.
   Never invent a decision ID or choice. Use `resolve --plan <plan.json>
   --decision <id>=<choice> --output <resolved-plan.json>`; it does not modify
   the target.
4. Read [the operator flow](references/operator-flow.md) before apply,
   verification, or rollback. Treat security-sensitive Codex configuration,
   project instructions, specs, skills, and the official baseline as semantic
   decisions requiring user direction.
5. Immediately before `apply`, request explicit authorization to apply the
   fully resolved plan, including its recorded profile. Only after that authorization, run `apply --plan
   <resolved-plan.json> --approve --format json`. Do not infer approval from
   earlier discussion or from selecting decisions.
6. Run `verify --receipt <receipt.json> --format json` after apply. A report
   with failed checks, unresolved sidecars, or status other than `success` is
   incomplete; report the receipt, sidecars, and manual merge work without
   claiming migration success.
7. Immediately before `rollback`, request explicit authorization to restore
   the receipt-owned paths. Only after it is granted, run `rollback --receipt
   <receipt.json> --approve --format json`. Stop if the CLI refuses the action.

For direct adoption, persist and review the exact normal plan and resolve only
its normal CLI-issued choices. `adoptPartial`, `targetState`, and `profile` are
digest-bound and canonically replayed before backup creation. Preserve task,
workspace, developer, current-task, and runtime state; do not infer a choice
for a shared path. New direct-adoption receipts also record filtered digests
for retained project state, excluding only exact journal destinations, so
verification rejects project-state changes made by its commands. Historical
recovery remains independently authorized and never authorizes a
direct-adoption apply.

The CLI validates roots, current Git/session safety, plan and receipt digests,
and external backups. Report JSON emitted by `plan`, `apply`, `verify`, and
`rollback`, plus the resolved-plan JSON written by `resolve`, alongside stderr
diagnostics. Do not bypass a blocker, stale plan, unresolved decision, failed
verification, or rollback refusal.
