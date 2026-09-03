# Deterministic Harness Migration Contract

## 1. Scope / Trigger

Use this contract when changing the Harness export policy, migration CLI,
transaction/receipt logic, inspection commands, verification commands, rollback
behavior, or the Agent Skill that operates the migrator. The migrator installs
or refreshes the Harness in a disjoint target Git root; it is not a recursive
overlay tool.
Approved persistent model routes are effective migration source bytes: route
planning never edits the template, global Codex configuration, or target
outside the normal plan/resolve/apply transaction.

Authority is deliberately split:

```text
Agent/operator -> plan -> resolve -> approved apply -> receipt -> verify/rollback
                         CLI owns every target filesystem mutation
```

- `export-manifest.json` owns source disposition and migration policy.
- A canonical, digested plan authorizes the proposed action set.
- An external, digested receipt and its action journal authorize recovery.
- The Skill may explain output and collect decisions, but must invoke the CLI
  for planning, resolution, writes, verification, and rollback.
- Apply and rollback have no dirty-worktree, session, conflict, or post-image
  force bypass.

## 2. Signatures

The public command surface is fixed:

```text
python .trellis/scripts/harness_migrate.py plan \
  --template <root> --target <root> [--developer <name>] \
  [--profile <name>] [--adopt-partial] \
  [--route <scope>=<route>]... \
  [--route-pair <scope>=<model>,<effort>]... [--route-only] \
  [--development-template] \
  [--format human|json] [--output <plan.json>]

python .trellis/scripts/harness_migrate.py inspect \
  --template <root> [--profile <name>] [--format human|json]

python .trellis/scripts/harness_migrate.py inspect-routes \
  --target <root> [--format human|json]

python .trellis/scripts/harness_migrate.py release-plan \
  --authoring-template <root> --release <root> \
  [--format human|json] [--output <plan.json>]

python .trellis/scripts/harness_migrate.py release-apply \
  --plan <plan.json> --approve [--backup <external-root>] \
  [--receipt <external-receipt.json>] [--format human|json]

python .trellis/scripts/harness_migrate.py release-verify \
  --receipt <receipt.json> [--format human|json]

python .trellis/scripts/harness_migrate.py release-rollback \
  --receipt <receipt.json> --approve [--format human|json]

python .trellis/scripts/harness_migrate.py resolve \
  --plan <plan.json> [--decision <id>=<choice>]... \
  --output <resolved-plan.json>

python .trellis/scripts/harness_migrate.py apply \
  --plan <resolved-plan.json> --approve [--backup <external-root>] \
  [--receipt <backup-contained-receipt.json>] [--format human|json]

python .trellis/scripts/harness_migrate.py verify \
  --receipt <receipt.json> [--integrity-only] [--format human|json]

python .trellis/scripts/harness_migrate.py rollback \
  --receipt <receipt.json> --approve [--format human|json]

python .trellis/scripts/harness_migrate.py recover-plan \
  --template <root> --target <root> --baseline <target-local-backup> \
  [--format human|json] [--output <recovery-plan.json>]

python .trellis/scripts/harness_migrate.py recover-resolve \
  --plan <recovery-plan.json> [--decision <id>=<choice>]... \
  --output <resolved-recovery-plan.json>

python .trellis/scripts/harness_migrate.py recover-apply \
  --plan <resolved-recovery-plan.json> --approve \
  [--backup <external-root>] [--receipt <backup-contained-receipt.json>] \
  [--format human|json]
```

Core Python boundaries:

```python
build_plan(template_value: str, target_value: str,
           developer: str | None = None,
           profile: str | None = "complete", adopt_partial: bool = False,
           route_overrides: list[str] | tuple[RouteOverride, ...] = (),
           route_only: bool = False,
           route_pairs: list[str] | tuple[RouteOverride, ...] = (),
           development_template: bool = False) -> Plan
inspect_template(template_value: str,
                 profile: str | None = None) -> dict[str, Any]
inspect_routes(target_value: str) -> dict[str, Any]
resolve_plan(plan: Plan, selections: dict[str, str]) -> Plan
apply_plan(plan: Plan, backup_value: str | None = None,
           receipt_value: str | None = None) -> tuple[dict[str, Any], Path]
verify_receipt(receipt_path: Path,
               *, run_commands: bool = True) -> dict[str, Any]
verify_integrity(receipt_path: Path) -> dict[str, Any]
rollback_receipt(receipt_path: Path) -> dict[str, Any]
```

Recovery uses `build_recovery_plan`, `resolve_recovery_plan`, and
`apply_recovery_plan`. It has a separate closed schema and canonical rebuild;
normal `Plan` parsing and behavior remain unchanged. Recovery parsers expose
neither `--route`, `--route-pair`, nor `--route-only` and reject them before producing
recovery output.

Exit codes are stable: `0` success, `2` invalid input, `3` blocked, `4`
unresolved decisions, `5` apply failure, `6` verification failure, and `7`
rollback refusal.

`inspect` is template-only and accepts no target, plan, or output path.
`inspect-routes` is target-only and accepts no `--template`. Neither is a plan,
admission, or mutation command.

## 3. Contracts

### Manifest and planning

The authoring discovery sequence is fixed:

```text
trellis platforms --json
  -> Harness inspect --template <root> [--profile <name>]
  -> relevant trellis-meta platform/customization guidance
  -> inspect actual local files, direct edit, focused tests
```

Native platform discovery identifies configured roots. Harness inspection is
the deterministic structure API. `trellis-meta` explains how to interpret and
customize the local Trellis/platform layers, but its prose is not export or
profile metadata. Harness-private rules belong in this project spec or the
project-local migration skill, never in bundled `.agents/skills/trellis-meta/**`.
Authoring is separate from target distribution. A reviewed target change starts
a new `plan [-> resolve] -> approved apply -> verify [-> approved rollback]`
transaction; inspecting a profile neither authorizes nor precomputes that plan.

### Template structure inspection

- `inspect` resolves one source template and validates a regular
  `export-manifest.json` plus exactly schema-2
  `.trellis/.template-hashes.json` with only `__version` and `hashes`.
  Hash paths are canonical safe POSIX-relative paths; digests are lowercase
  64-character SHA-256 hex. Present paths must be contained regular files.
- `export-manifest.json` owns the exported file set and every profile's
  membership. Omitting `--profile` reports the complete export while serializing
  `profile: null`; a named profile uses the same `exported_files` selector as
  planning. The hash map never selects a semantic closure.
- JSON schema 1 has `schemaVersion`, canonical `templateRoot`, nullable
  `profile`, sorted `areas`, and path-sorted `files`. Each area record has
  `area` and `fileCount`. Each file has `area`, nullable `baselineDigest`,
  nullable `currentDigest`, `path`, `platform`, `presence`, sorted `profiles`,
  `provenance`, and `status`. Human output renders the same ordered model.
- A hash-tracked present file is `trellis_managed` and either
  `official_unchanged` or `official_modified`; a missing tracked file is
  `official_missing`. An exported path absent from the hash map is
  `project_local`, with a null baseline digest. Hash absence is valid.
- Inspection is source-only and read-only. It performs no target admission,
  plan/receipt/backup creation, filesystem write, network access, external
  command, official update, or hash rewrite.

### Deterministic release projection

- `inspect` is a structural, read-only schema-1 report. It proves manifest
  selection and provenance only; it does not classify session history or
  foreign product conventions. Real-template regression tests own those
  semantic sanitation assertions.
- `release-plan` reads a disjoint authoring root and release root without
  mutation. `release-apply --approve` is the only release-refresh writer; it
  may write the declared release root and an external backup/receipt, never the
  authoring root or a business target. `release-verify` and
  `release-rollback --approve` operate only on that receipt.
- The projection copies only complete-profile payload paths, replaces declared
  workspace destinations with independent release skeleton bytes, and writes
  deterministic `.harness-release.json` provenance. The metadata is
  release-only and never becomes a target migration action.
- Release refresh preserves `.git`, rejects unexpected non-Git content and
  drifted release-owned bytes, and restores only receipt-owned preimages on
  rollback. Git initialization, commits, tags, remotes, and publication remain
  external operator or CI responsibilities.
- Direct directory copying or archiving is unsupported: it can include author
  tasks, journals, research, runtime state, or caches that a release projection
  deliberately excludes. A release template is a versionable, deterministic
  distribution artifact; a migration backup instead preserves one target's
  pre-migration bytes for recovery.
- A normal business-target apply requires valid release provenance. Authoring
  roots remain readable for planning, while `--development-template` is the
  explicit, digested development-only exception and cannot be supplied later
  at apply time.

The persistent named-route catalog is closed:

| Scope | Allowed route | Stored model / effort | Effective source |
| --- | --- | --- | --- |
| `main` | `coordination`, `planning` | `gpt-5.6-sol` / `medium` | `.codex/config.toml` root |
| `subagent-default` | `bounded_worker` | `gpt-5.6-terra` / `high` | `.codex/config.toml` `[agents]` |
| `role:research` | `exploration` | `gpt-5.6-terra` / `medium` | `trellis-research.toml` root |
| `role:debug` | `debugging` | `gpt-5.6-sol` / `low` | `trellis-debug.toml` root |
| `role:review` | `review` | `gpt-5.6-sol` / `high` | `trellis-review.toml` root |
| `role:audit` | `audit` | `gpt-5.6-sol` / `high` | `trellis-audit.toml` root |
| `role:release` | `release` | `gpt-5.6-sol` / `high` | `trellis-release.toml` root |
| `dispatch:implement:default` | `bounded_worker` | `gpt-5.6-terra` / `high` | `.codex/trellis-dispatch.toml` `[implement.default]` |
| `dispatch:implement:hard` | `hard_implementation` | `gpt-5.6-sol` / `medium` | `.codex/trellis-dispatch.toml` `[implement.hard]` |
| `dispatch:check:default` | `checking_sol_medium` (default), `checking` (legacy alternative) | `gpt-5.6-sol` / `medium`; `gpt-5.6-terra` / `max` | `.codex/trellis-dispatch.toml` `[check.default]` |
| `dispatch:check:hard` | `hard_checking` | `gpt-5.6-sol` / `xhigh` | `.codex/trellis-dispatch.toml` `[check.hard]` |

Role filenames live under `.codex/agents/`. Internal entries are
`RouteOverride(scope: str, route: str | None, model: str, effort: str)`.
`--route` remains closed to the named catalog above. `--route-pair` accepts an
explicit TOML-safe model/effort pair for any known scope, only with
`--route-only`; its internal `route` is null. Duplicate or unknown scopes,
unsupported named routes, unsafe/empty raw values, and persistent
`role:implement` or `role:check` pins are invalid. Route names such as `micro`,
`memory_worker`, and `curator` remain outside the named catalog but their model
pairs can be selected explicitly through `--route-pair`.

### Route inspection

- `inspect-routes` reads exactly eleven catalog scopes in stable
  `ROUTE_CATALOG` / `ROUTE_TARGETS` order: the original seven unchanged,
  followed by the four dispatch scopes. It reads root `model` and
  `model_reasoning_effort` for `main`, and `[agents]`
  `default_subagent_model` and `default_subagent_reasoning_effort` for
  `subagent-default`; role files use the root pair, while dispatch scopes read
  their nested tables. It reverse-matches the
  observed model/effort pair against that scope's named routes in
  `ROUTE_CATALOG` iteration order. When aliases share one pair, the first
  catalogued route is reported; `main` therefore reports `coordination` rather
  than `planning`.
- JSON is deterministic and contains canonical `targetRoot` and ordered
  `routes`; every route entry has `scope`, source `path`, `status`, nullable
  `route`, `model`, `effort`, and machine-readable nullable `detail`; dispatch
  entries additionally include `table` (`implement.default`,
  `implement.hard`, `check.default`, or `check.hard`). Human
  output is one concise line per scope with scope, status, route or raw pair,
  and source path (plus detail when present).
- `known` means an exact named pair; `custom` means two string values with no
  named pair; `missing` covers an absent source file or required key; and
  `invalid` covers unsafe/non-regular/unreadable/non-UTF-8/malformed TOML,
  table ownership, or value-type errors. `custom`, `missing`, and per-route
  `invalid` are successful observations (`0`). A target argument that is
  invalid or not a directory is invalid input (`2`).
- The exact observational `detail` values are `uncatalogued_pair` for
  `custom`; `missing_file`, `missing_model_and_effort`, `missing_model`, and
  `missing_effort` for `missing`; and `unsafe_path`, `not_regular_file`,
  `non_utf8_toml`, `unreadable_file`, `malformed_toml`, `invalid_table`,
  `wrong_table`, `model_not_string`, and `effort_not_string` for `invalid`.
  A `known` entry has `detail: null`.
- Inspection is strictly read-only: it does not check Git cleanliness or an
  active Trellis session, and it must not mutate the target, template, backup,
  receipt, task, or runtime files. A missing legacy dispatch file yields four
  independent `missing` / `missing_file` entries rather than an admission
  failure.

- Manifest schema `2` contains `migrationPolicy` schema `1`. Each normalized
  POSIX-relative rule has exactly `path`, `kind`, `modes`, `onExisting`,
  `onModified`, and `sourceRequired`.
- The top-level `migrationProfiles` object is manifest-owned and non-empty.
  Each non-empty profile name maps to a closed object with a non-empty `include`
  string array and optional `includeIfPresent` / `requires` fields.
  `complete` must include exactly `**`. `dispatch-only`
  includes only the dispatch governance/configuration surfaces: `AGENTS.md`,
  Codex config/hooks/agents plus `.codex/trellis-dispatch.toml`,
  `.trellis/config.yaml`, workflow and role cards, the shared dispatch resolver,
  its authoritative migration catalog dependency, the seven-role routing skill,
  and the model-routing spec. It must not select unrelated migration modules,
  `.trellis/tests/**`, the migration skill, or other generic specs.
- `agent-workflow` is a literal closure containing root instructions, workflow,
  all runtime agent cards, Codex hook registration/scripts, workflow selection
  and phase helpers, task runtime, only the native check TOML, the Trellis check
  and seven-role skills, the routing spec/test, and optional
  `.trellis/workflows/**`. It excludes other native agent TOMLs, Codex
  model/dispatch configuration, `.trellis/config.yaml`,
  `.trellis/.template-hashes.json`, unrelated specs/tests, and task/workspace/
  runtime state. Its closed applicability is target state `existing_trellis`
  and capability `codex-dispatch-workflow-v1`.
- Profile include patterns use the same normalized POSIX-relative pattern
  grammar as export rules: forward slashes only; no backslash, NUL, colon,
  absolute path, `.`/`..`, parent traversal, or non-canonical spelling such as
  doubled separators. Duplicate patterns and a pattern that matches no
  exported source file are invalid. `*` and `?` do not cross `/`; `**` may.
  Profile selection filters the exported-file set before actions, conflicts,
  and decisions are constructed, while the normal most-specific migration-rule
  ownership resolution still applies to every selected path.
- Tests selected into an installed-target profile must not unconditionally
  depend on `support_only` source files. Source-template CLI and manifest
  assertions use an explicit `unittest.skipUnless` guard when
  `export-manifest.json` is absent, while target-runtime dispatch assertions
  remain active and live in a separately runnable test method.
- Rule kinds are `replaceable_managed`, `merge_required`, `preserve`,
  `runtime_excluded`, `fresh_only_skeleton`, and `support_only`. Every exported
  source file has exactly one most-specific disposition; equal-specificity
  overlap and unmatched required rules are invalid.
- `plan` is non-mutating except for an explicitly requested `--output`. It
  resolves explicit template/target roots and classifies `fresh` versus
  `existing_trellis`. Actions sort by `(path, operation)`, decisions by `id`,
  and blockers/conflicts lexicographically. `planDigest` hashes the complete
  plan without `planDigest` as ASCII JSON with sorted keys, compact separators,
  and one trailing LF.
- The plan schema is closed: unknown or missing top-level, action, or decision
  fields are rejected. It records canonical roots, target state, template and
  manifest versions/digests, per-action source/target/destination digests,
  stable decision IDs, allowed choices, a schema-sensitive `profile`,
  blockers, conflicts, logical
  verification commands, and `planDigest`.
- Schemas `1` (ordinary) and `2` (partial adoption) are legacy no-override
  plans and omit `routeOverrides`. Schemas `3` (ordinary override) and `4`
  (adoption override) require boolean `adoptPartial` and a non-empty
  `routeOverrides` array. Every item has exactly string fields `scope`,
  `route`, `model`, and `effort`; items are scope-sorted and unique, and
  each complete tuple must match the catalog. Missing/extra/reordered/duplicate
  or catalog-mismatched data is rejected. The normalized array is plan-digested.
- Schema `5` is the closed route-only form. It requires `selectionMode` exactly
  `"route-only"`, `profile: null`, `developer: null`, `adoptPartial: false`,
  `targetState: "existing_trellis"`, and a non-empty scope-sorted, unique,
  catalog-valid `routeOverrides` array. Its action paths must equal the sorted,
  unique paths derived directly from `ROUTE_TARGETS` for those scopes; no extra,
  missing, reordered, or substituted action path is accepted. Schemas `1`-`4` retain
  their existing fields, string-profile requirement, serialization, digest
  behavior, and compatibility.
- Schema `6` is the closed `agent-workflow` capability form. It requires
  `profile: "agent-workflow"`, `targetState: "existing_trellis"`, and
  `prerequisiteEvidence` with capability `codex-dispatch-workflow-v1`, status
  `admitted`, sorted unique checked-file path/digest records, all four approved
  structurally valid persisted implement/check lane records, required Codex hook evidence, and
  role identity/instruction evidence. The complete evidence is plan-digested.
  Apply rebuilds it from live target files during canonical replay before backup
  or mutation; drift makes the plan non-canonical.
- Schema `7` is the raw-pair route-only form. It has the same closed mode,
  target-state, action, decision, digest, and transaction invariants as schema
  `5`, but each scope-sorted `routeOverrides` item has exactly `scope`, `model`,
  and `effort`; it deliberately omits `route`. Model and effort must be non-empty
  TOML-safe identifiers using letters, digits, `.`, `_`, `:`, `/`, `+`, `@`, or
  `-`. Apply canonically rebuilds schema `7` from those raw pairs before backup.
- Admission fails closed on unsafe/missing prerequisites, invalid lanes,
  missing required hook commands/roles, wrong role identity or instructions,
  and any model pin in native implement/check definitions. The structured
  failure identifies capability and sorted failures and recommends
  `dispatch-only`; admission never falls back to prose or partial capability.
- `agent-workflow` preserves normal whole-file decisions for modified managed
  and merge-required files, including `.codex/agents/trellis-check.toml`. It
  performs no field-level TOML patch. Because its action set excludes the hash
  map, apply, verify, and rollback leave the target official hash baseline
  byte-identical; customized Harness bytes do not become official Trellis
  output.
- `agent-workflow` executes only existing Harness transaction action kinds.
  There is no Copier answers/Jinja rendering, Git template tag or smart-diff
  lifecycle, template task/migration execution, external template runtime,
  command runner, or network path. Those belong to a different generated-
  project trust model and are outside this literal transaction.
- `plan --adopt-partial --profile complete` emits schema `2` without route
  overrides or schema `4` with a non-empty route override set, only for the
  authoritative `unsupported_partial` target state. Its required boolean
  `adoptPartial`, input state, profile, and any route overrides are digested and
  replayed canonically by normal apply. The `--profile complete` flag is
  explicit for adoption even though ordinary planning defaults to that
  profile. It takes no baseline and reads no historical backup. Fresh,
  existing, unsafe, linked, non-Git, dirty, or active-session targets are
  refused before backup or target writes. Schema-1 ordinary plans remain
  supported unchanged.
- `plan --profile <name>` defaults to `complete`; the strict target overlay
  uses `--profile dispatch-only`. An unknown name is refused by manifest
  export selection. A selected profile is part of the serialized plan and
  `planDigest`, so changing it without recomputing the digest is invalid.
- Every requested route path must be selected by the recorded profile, or plan
  creation fails with `route override paths are not selected by profile`.
- `plan --route-only` with one or more `--route <scope>=<route>` or
  `--route-pair <scope>=<model>,<effort>` values is a separate selection mode,
  not a synthesized manifest profile. It requires at least one normalized route
  and rejects an explicitly supplied `--profile`, `--developer`, or
  `--adopt-partial` with exit `2` before `--output` is created. It only admits
  a clean target classified exactly as `existing_trellis`; fresh and
  `unsupported_partial` targets must use ordinary migration or recovery first.
  Route-only paths are selected from `ROUTE_TARGETS`, then remain subject to export,
  rule, containment, regular-file, and strict TOML effective-source validation.
- Transformation occurs after contained template reading and before action
  `sourceDigest` and plan digest calculation. Root scopes require parsed TOML
  string `model` and `model_reasoning_effort` values plus exactly one active
  simple double-quoted source assignment for each at root. `subagent-default`
  requires the analogous `default_subagent_model` and
  `default_subagent_reasoning_effort` pair exactly inside `[agents]`.
  Missing/duplicate/non-string/wrong-table assignments, malformed or non-UTF-8
  TOML, and non-simple strings the line codec cannot replace are rejected.
- Dispatch scopes require the same exact simple double-quoted pair in their
  owned nested table. When `.codex/trellis-dispatch.toml` already exists, its
  complete target preimage, not template bytes, is the transform input. All
  requested dispatch lanes compose in scope-sorted order into one file action;
  unselected lanes and unrelated TOML therefore retain their target bytes. If
  the file is absent, template defaults seed all four tables before selected
  overrides are applied.
- Only the two quoted values change. Comments, spacing, order, CRLF/LF endings,
  final-newline state, and unrelated bytes are preserved; nonselected files are
  byte-identical. Effective bytes are ephemeral and never mutate source or
  generated templates.
- `resolve` accepts only known `ID=choice` pairs and only declared choices. It
  preserves the plan's selected `profile`, derives `copy`, `sidecar`,
  `preserve`, or `skip`, checks destination collisions, and writes a newly
  digested plan; hand-edited plans are invalid.
- After choices are applied, every override-owned live path must have operation
  `copy`. `keep`/`skip` and `sidecar` are rejected with `route overrides
  require live-target copy`. Existing targets still preview normal decisions,
  but an override-owned collision must explicitly resolve as `replace`.
- In route-only mode, scopes sharing `.codex/config.toml` or
  `.codex/trellis-dispatch.toml` compose their transforms into one action. A
  missing selected target is an automatic live `copy` with no
  decision. Every existing selected target, including one whose bytes already
  equal the effective source, has one `replace`-only decision: before resolution
  its action is `skip`, and after `replace` it is a live `copy`. `keep`, `skip`,
  `sidecar`, `install`, and preserve outcomes are not valid successful
  route-only resolutions. The content-idempotent equal case is still an
  approved, receipt-backed replacement.
- `.trellis/.version` and `.trellis/.template-hashes.json` are one official
  baseline decision. Snapshot adoption is allowed only when every referenced
  official-managed file matches the resolved snapshot image. An override whose
  transformed official bytes differ from that image is blocked before backup.

### Apply and recovery

- Apply rebinds the authority to live state before backup: validate the plan
  digest/schema, canonical and disjoint roots, current manifest digest,
  blockers, all decisions, canonical rebuilt plan, baseline parity, every
  target/sidecar pre-image, and every transformed or ordinary source digest.
- Canonical rebuilding calls `build_plan` with the recorded `plan.profile`,
  `adoptPartial` mode, normalized `plan.route_overrides`, and
  `route_only=plan.selection_mode == "route-only"`,
  resolves the recorded choices, and compares the complete serialized plan.
  Thus a re-digested switch from `dispatch-only` to `complete` is blocked as
  `plan no longer matches the canonical migration plan`; an unknown recorded
  profile is refused during manifest selection. Both failures happen before
  backup creation or target writes.
- A target must be the root of a clean Git worktree. Recursively inspect
  `.trellis/.runtime/sessions/`; any non-placeholder JSON, unreadable/non-file
  entry, symlink, junction, or reparse point blocks before target writes.
  `{}`, `[]`, and `null` JSON placeholders do not represent active sessions.
- Roots and every traversed path must remain canonical and contained. Same or
  nested template/target roots, rebinding through links/reparse points, and
  symlink traversal are unsupported.
- Backup is external to template and target. Validate each copied pre-image,
  then atomically write a `prepared` receipt before the first target write.
  Each journal entry transitions `prepared -> applying -> applied`, with the
  receipt rewritten before and after replacement. Thus an interrupted receipt
  whose global status is still `prepared` and whose entry is `applying` remains
  a recovery authority.
- The closed receipt schema records canonical roots, its own contained path,
  plan digest, target state, backup root, journal, preserved-root digests,
  logical verification commands, verification report, status, and
  `receiptDigest`. Ordinary and direct-adoption receipts also bind the plan's
  closed `sourceAdmission`; schema-1 recovery receipts retain their existing
  baseline-owned schema and do not invent an admission record absent from the
  recovery plan. Optional fields are string `failure` and the recovery-only
  `baselineRoot`, closed `baselineAudit`, and `quarantinedTargetStates`, which
  must appear together only on an `unsupported_partial` receipt.
  Status values are `prepared`, `applied`, `apply_failed`, `verified`,
  `verified_incomplete`, `verification_failed`, `rollback_failed`, and
  `rolled_back`. Receipt/root/path rebinding, unknown fields, invalid state
  transitions, incomplete preserved coverage, or pre-image tampering is fatal.
- A direct-adoption receipt is schema 3 with required `adoptPartial: true`,
  `targetState: unsupported_partial`, and closed `projectStateDigests`; its
  only optional field is the normal string `failure`, and it has no
  baseline/recovery fields. The digest set covers project-owned merge roots
  and exact config paths while filtering only the receipt's journal
  destinations. This permits an exact reviewed replacement to be verified by
  its installed post-image while retaining target-only and sidecar-retained
  project state in both verification sweeps. Schema-2 direct-adoption receipts
  remain readable for backward compatibility, alongside schema-1 ordinary and
  recovery receipts.
- Mutations use sibling temporary files plus `os.replace`. Apply writes only
  resolved `copy` and `sidecar` destinations. Support-only content is never an
  install action, and project-owned state remains covered by preserved digests.
- Normal staging recomputes the same route-aware effective source and checks its
  action digest before backup. Route-only plans retain the same backup, journal,
  receipt, verify, stale-preimage, and exact rollback behavior; their missing
  preimages cause rollback to remove the newly created route file, while
  existing preimages are restored byte-for-byte. Recovery staging remains
  baseline-owned and never accepts or replays route overrides or route-only
  flags.
- Recovery accepts only `unsupported_partial`, and only an explicitly selected
  direct target `.trellis/.backup-*` directory. The baseline must be a real,
  canonical directory tree with no link-like or special entries. Its version
  must equal the current template version; its closed version-2 template-hash
  document must reference regular files whose SHA-256 values match, except for
  an exact normalized path whose most-specific current complete-manifest rule
  is `merge_required`; and its parsed, non-empty `name=` developer identity
  must match a live target identity when one exists. Other preserved developer
  metadata may differ. Every non-`merge_required` mismatch remains blocked.
- The closed recovery plan records `transactionType: recovery`, the canonical
  baseline root/version/complete digest, template and manifest identity, a
  closed `baselineAudit`, sorted actionless `quarantinedTargetStates`, actions,
  decisions, commands, and `planDigest`. `baselineAudit` uses `verified` with
  no exclusions or `verified_with_quarantined_merge_required` with sorted
  entries containing path, expected digest, actual digest, `merge_required`,
  and fixed reason `baseline_digest_mismatch_merge_required`. Candidates are the
  intersection of baseline files and the current manifest-owned `complete`
  export. Recovery excludes preserve, runtime, support, fresh-skeleton, spec,
  task, workspace, developer, current-task, and runtime paths.
- Quarantined paths are removed before recovery actions and decisions are
  built. Their baseline bytes never enter source staging, sidecars, backup
  journals, apply, or rollback. The plan binds equal target pre/post digests,
  including `missing`, so canonical replay refuses target drift before backup.
- Recovery collisions expose only `sidecar`, `keep`, and `replace`. Apply
  canonically rebuilds the recovery plan and revalidates the complete baseline,
  source images, target images, decisions, Git cleanliness, and sessions before
  external backup creation or target writes. Mutation source bytes are staged
  and digest-checked before backup creation, and only those validated bytes may
  be written, so post-replay source drift cannot partially update the target.
- A recovery receipt has `targetState: unsupported_partial`, binds the
  canonical `baselineRoot`, repeats `baselineAudit` and
  `quarantinedTargetStates`, and preserves digests for the baseline and all
  project-owned Trellis roots. Verification proves quarantined target state is
  unchanged in both digest sweeps. The journal must not name a quarantined
  source or destination, and rollback never restores those bytes. It is never
  authority for a later normal migration; generate and approve a fresh normal
  `complete` plan after recovery verification, where excluded paths receive
  their ordinary current-source action or decision.

### Verification and rollback

- Verification first performs a complete installed and preserved digest pass.
  If any precheck fails or is uninspectable, run no commands. Otherwise execute
  the receipt's commands, then repeat the complete digest pass so commands
  cannot mutate installed or preserved state unnoticed.

#### Scenario: `verify --integrity-only`

##### 1. Scope / Trigger

- This is an explicit, operator-selected read-only observation after a simple
  change; the CLI must never classify a change or select the mode itself.
  This new CLI/API and report boundary requires code-spec depth.
- It applies only to normal `verify`; `release-verify` has no integrity-only
  mode. Plain `verify` remains the unconditional full-verification default.

##### 2. Signatures

```text
python .trellis/scripts/harness_migrate.py verify \
  --receipt <receipt.json> [--integrity-only] [--format human|json]
```

```python
verify_integrity(receipt_path: Path) -> dict[str, Any]
verify_receipt(receipt_path: Path, *, run_commands: bool = True) -> dict[str, Any]
```

The flag dispatches only to `verify_integrity()`. Existing callers may retain
`verify_receipt(..., run_commands=False)`; it is not the integrity-only API.

##### 3. Contracts

- `verify_integrity()` performs the regular receipt load/root validation and
  all installed, preserved-state, project-state, quarantined-target, and
  sidecar checks. It never calls `_run()` or `_write_receipt()`.
- Its report has the normal `schemaVersion`, `status`, `receiptPath`, `checks`,
  and `unresolvedSidecars` fields, plus `mode: "integrity-only"`; `commands`
  is always `[]`. The priority is `failed` for any failed/uninspectable check,
  then `incomplete` for sidecars, otherwise `success`.
- The receipt bytes, lifecycle status, and stored full-verification report are
  unchanged on every result. `success` proves current integrity only; it is
  not proof that receipt verification commands completed.
- Full `verify_receipt()` retains its command execution, post-command digest
  pass, write-back, lifecycle transition, and report shape without `mode`.

##### 4. Validation & Error Matrix

| Condition | Integrity-only result | Exit |
| --- | --- | --- |
| Valid receipt; every integrity check passes; no sidecar | `status: success`, empty `commands`, `mode: integrity-only`; receipt unchanged | `0` |
| Digest drift or an uninspectable installed/preserved/quarantined path | `status: failed`, empty `commands`, `mode: integrity-only`; receipt unchanged | `6` |
| No failed checks but an unresolved sidecar exists | `status: incomplete`, reported `unresolvedSidecars`, empty `commands`; receipt unchanged | `6` |
| Invalid/rebound/unreadable receipt or a receipt status ineligible for verification | Raise verification failure; no command or receipt write | `6` |
| Flag absent | Dispatch to full `verify_receipt()` and preserve its existing result/write-back behavior | Existing full-verify result |

##### 5. Good / Base / Bad Cases

- **Good:** `verify --receipt receipt.json --integrity-only --format json`
  reports `success`, `mode: integrity-only`, and `commands: []` after all
  receipt-bound state matches, while `receipt.json` stays byte-identical.
- **Base:** `verify --receipt receipt.json` invokes full verification, executes
  eligible receipt commands, writes its verification report/lifecycle status,
  and does not add `mode` to its existing report shape.
- **Bad:** Routing the flag to `verify_receipt(..., run_commands=False)` skips
  commands but still writes the receipt as a full-verification result; that
  violates the read-only boundary.

##### 6. Tests Required

- Core: construct a receipt with a command that must not run. For clean,
  drifted, uninspectable, and sidecar outcomes, patch `_run` and assert it is
  never called; compare receipt bytes before and after every outcome. Assert
  `success`/`failed`/`incomplete`, `mode: integrity-only`, empty `commands`,
  the uninspectable error, and sidecar paths as applicable.
- CLI: assert `--help` describes the read-only/non-full mode; parse with and
  without the flag; mock both core functions to prove the flagged path calls
  only `verify_integrity()` and the plain path calls only `verify_receipt()`.
  Assert JSON mode/status fields and `0` for success versus `6` for failed or
  incomplete; assert plain JSON has no `mode` field.

##### 7. Wrong vs Correct

**Wrong:**

```python
report = verify_receipt(receipt_path, run_commands=False)
```

That shared compatibility path writes a receipt verification result.

**Correct:**

```python
report = verify_integrity(receipt_path) if args.integrity_only else verify_receipt(receipt_path)
```

The dedicated read-only entry point prevents a skipped-command observation
from being recorded as completed full verification.
- Resolve argv element zero with `shutil.which`, then pass that resolved path
  directly to `subprocess.run` with `shell=False`; this includes Windows paths
  such as `python.exe` and `trellis.CMD`. Report the original logical command
  array, not the machine-specific resolved path, in structured output.
- A nonzero command result fails unless a command-specific structured decoder
  proves the expected semantic state. The defined exception is the exact
  logical command `python .trellis/scripts/task.py current --json`: exit `1`,
  whitespace-only stderr, and a valid JSON object whose `current_task` field is
  `null` mean passed; additional object fields are currently tolerated. Prose,
  an array/scalar, a missing field, or empty output never qualifies.
- Sidecars make verification `incomplete`, not success. Digest or command
  failures make it `failed`. Verification tests that ship into targets must run
  without template-only `README.md` or `export-manifest.json`; source-export
  tests may be explicitly skipped when those `support_only` assets are absent.
- Rollback accepts recoverable receipt states, validates receipt/root/backup
  integrity and every live post-image before mutation, and restores only the
  reverse journal. For an `applying` entry with no recorded post-digest, live
  content must equal either its pre-image or expected post-image. Any unrelated
  post-apply edit refuses rollback.
- A partial rollback records `rollback_failed`; rerunning the same receipt is
  supported because already restored paths may equal their pre-images. Success
  records `rolled_back` and removes only empty parent directories created by
  the migration.

## 4. Validation & Error Matrix

| Condition | Required result | Exit |
| --- | --- | --- |
| Invalid JSON/schema, unknown plan field, bad `ID=choice` | Reject input; no target write | `2` |
| Missing/non-string plan `profile` for schemas `1`-`4`, non-null schema-5 profile, unknown `--profile`, malformed profile include pattern, duplicate profile pattern, or a profile pattern with no exported match | Reject plan/profile input; no target write | `2` |
| Malformed `--route`/`--route-pair`, empty/duplicate/unknown scope, unsupported named route, unsafe raw value, or implement/check pin | Reject before plan output; do not create `--output` or mutate target | `2` |
| Dispatch scope names any route outside that exact scope's closed map, including another lane or role family | Reject as an unsupported route override; no plan output or target mutation | `2` |
| `--route-only` has neither `--route` nor `--route-pair`, or explicitly combines with `--profile`, `--developer`, or `--adopt-partial` | Reject before plan output; do not create `--output` or mutate target | `2` |
| Override/schema-5 data has missing/extra/non-string fields, empty/unsorted/duplicate entries, catalog mismatch, invalid schema/adoption pairing, wrong `selectionMode`, or action paths not exactly derived from `ROUTE_TARGETS` | Reject closed plan input; no target write | `2` |
| Selected profile omits a requested route path | Reject planning with missing paths; no output or target write | `2` |
| Override TOML is malformed/non-UTF-8, lacks a simple string pair, duplicates it, or owns it in the wrong table | Reject effective source; no output or target write | `2` |
| Existing dispatch target preimage is stale at apply replay | Reject because the canonical migration plan differs; create no backup and perform no target write | `3` |
| Route-only existing target resolves to anything except its `replace` choice, or a route-only missing target is not live `copy` | Reject resolution/closed plan; no resolved output or target write | `2` |
| `--route-only` target is fresh, partial, unsafe, non-Git, dirty, or has an active session | Block before backup or target write | `3` |
| Recovery command receives `--route` or `--route-only` | Reject argument parsing; no recovery output or target write | `2` |
| `inspect` template/manifest/hash schema, digest, path containment, or regular-file check is invalid | Reject invalid input; perform no write, command, network, target admission, or plan construction | `2` |
| `inspect` names an unknown profile | Reject through manifest profile selection; perform no mutation | `2` |
| Exported path has no template-hash entry | Report `project_local` with null baseline; continue deterministic inspection | `0` |
| `inspect-routes` target is invalid or not a directory | Reject invalid input; no inspection or filesystem mutation | `2` |
| `inspect-routes` observes custom, missing, or per-route invalid configuration | Emit the ordered observational result; no admission checks or mutation | `0` |
| `agent-workflow` target is not `existing_trellis` or fails a capability prerequisite | Emit sorted structured admission failures and `dispatch-only` remediation; create no plan output, backup, or target write | `3` |
| Schema-6 prerequisite evidence is malformed, tampered, or stale at canonical replay | Reject the closed/digested plan or canonical mismatch before backup and target mutation | `2` or `3` |
| Changed `profile` without a matching digest | Reject as `plan digest or schema is invalid`; no target write | `3` |
| Same/nested/rebound root, non-Git root, dirty tree, recursive session/reparse blocker | Block before target write | `3` |
| Manifest digest changed, rebuilt profile plan differs, source/pre-image/sidecar digest stale | Block before target write | `3` |
| Route-aware rebuild/staging differs, or transformed bytes conflict with snapshot baseline | Block before external backup or target write | `3` |
| Unknown re-digested recorded profile during apply canonical rebuild | Refuse before backup or target write | `2` |
| Apply invoked without `--approve` | Refuse apply without backup or target mutation | `3` |
| Unresolved decision | Do not create backup or mutate target | `4` |
| Failure after prepared receipt or during mutation | Persist `apply_failed` when possible and report receipt for recovery | `5` |
| Precheck, command, post-command digest, or unresolved-sidecar verification is not success | Emit structured failed/incomplete report | `6` |
| Rollback missing `--approve`, invalid/rebound receipt, changed backup/post-image, or unprovable applying state | Refuse rollback without mutation | `7` |
| Rollback fails after partial restoration | Persist `rollback_failed`; preserve retry authority | `7` |
| Recovery target is not exactly `unsupported_partial`, or its explicit baseline is outside the direct target backup layout, wrong-version, malformed, hash-stale, identity-incompatible, link-like, or contains a special entry | Reject recovery before external backup or target write | `3` |
| Recovery plan/baseline/target/decision replay differs at apply | Reject recovery before external backup or target write | `3` |
| Baseline mismatch is not exact current `merge_required`, or a quarantine audit/state entry is malformed, duplicated, stale, or enters actions/journal | Reject before external backup or target write | `3` |

`plan` may return `3` while still emitting its structured blockers. There is no
`--force` equivalent for any row.

## 5. Good / Base / Bad Cases

- **Good:** `trellis platforms --json` identifies configured integrations;
  source `inspect --template <root> --profile agent-workflow --format json`
  returns the exact manifest-selected closure and provenance; the author then
  reads relevant `trellis-meta` guidance plus actual files before a direct edit.
- **Good:** A valid existing Trellis target plans `agent-workflow` as schema 6,
  records all closed prerequisite evidence, resolves whole-file choices, and
  applies/verifies/rolls back without changing the target template-hash bytes.
- **Good:** A clean fresh Git root plans twice to byte-equivalent JSON without
  changing the target; resolution initializes the explicit developer, apply
  creates an external backup and prepared receipt, verify passes both digest
  sweeps, and rollback restores the original target digest exactly.
- **Good:** `plan --profile dispatch-only` emits only its selected dispatch
  surfaces, serializes `"profile": "dispatch-only"`, and keeps that value
  after resolve; apply canonically rebuilds the same narrow action set before
  any write.
- **Good:** Repeated `--route role:research=exploration --route main=planning`
  emits schema `3` sorted as `main`, `role:research`; only owned quoted
  values are eligible for replacement, verify succeeds, and rollback restores
  exact preimages. Effective bytes may equal the template when it already uses
  the selected routes.
- **Good:** On a clean `existing_trellis` target,
  `plan --route-only --route main=planning --route subagent-default=bounded_worker`
  emits schema `5`, `selectionMode: "route-only"`, `profile: null`, and one
  `.codex/config.toml` action. If absent, it is an automatic `copy`; rollback
  removes it. If present, resolve its only `replace` decision, apply, verify,
  and rollback restores its exact original bytes even when they already equal
  the effective source.
- **Good:** `inspect-routes --target <root> --format json` returns canonical
  `targetRoot` and all eleven scopes in catalog order; the original seven retain
  their order and object shape, and each appended dispatch entry identifies its
  nested source table.
- **Good:** A route-only update of two lanes in an existing dispatch file emits
  one replace-only action derived from the complete target preimage. Apply
  changes only the four selected assignments, preserves CRLF/comments/custom
  unselected lanes, verify succeeds, and rollback restores the exact preimage.
- **Base:** With no `--route`, ordinary/adoption plans remain schemas `1`/`2`
  and omit route data and effective-source changes.
- **Base:** A complete inspection includes an exported project-local skill with
  `provenance/status: project_local` and null `baselineDigest`; lack of an
  official hash is not an error and does not remove profile membership.
- **Base:** A missing dispatch file remains inspectable as four independent
  `missing_file` observations; a named route-only update creates it from the
  shipped four-table default and rollback removes it.
- **Base:** An existing Trellis project preserves tasks, workspace, developer,
  current task, runtime, and specs. A modified managed file resolves to a
  `.harness-new` sidecar; apply succeeds but verification remains incomplete
  until the merge is reconciled.
- **Base:** `inspect-routes` reports a custom raw pair, absent key/file, or
  malformed/wrong-table TOML as `custom`, `missing`, or `invalid` and exits
  successfully without considering the target Git or session state.
- **Bad:** A plan becomes stale, the target gains an untracked file, or a
  nested session contains active JSON after planning. Apply rejects the live
  state before its first target mutation; approval does not override it.
- **Bad:** Treating hash membership as workflow-profile membership, rewriting
  target hashes after `agent-workflow` apply, or invoking Copier/Jinja/tasks/
  migrations turns local bytes into false official provenance or adds an
  unreviewed execution model. None is a valid Harness action.
- **Bad:** A caller changes a `dispatch-only` plan to `complete`. Without a new
  digest it fails digest validation; with a recalculated digest it still fails
  canonical rebuild because the complete profile produces a different plan.
  A recorded profile named `missing` is refused before backup or target writes.
- **Bad:** An existing config collision resolves as `keep` or `sidecar`, a
  profile contains an escaped/non-simple assignment, or the profile excludes
  the requested role path. Planning/resolution fails with zero target mutation.
- **Bad:** Supplying `--route-only --profile complete`, omitting both `--route`
  and `--route-pair`, or
  selecting a fresh/partial target fails before plan output or mutation. A
  re-digested schema-5 plan with `profile: "complete"`, another selection mode, or an
  `AGENTS.md` action still fails closed parsing or canonical replay.
- **Bad:** Applying dispatch overrides to template bytes when the target file
  exists silently resets unselected lanes. Such a plan is non-canonical; the
  effective postimage must be derived from the reviewed target preimage.
- **Bad:** A check executable returns `1` and prints prose resembling "no
  current task". Verification fails because semantic acceptance requires the
  exact command and valid structured null state.
- **Bad:** Treating a non-directory inspection target as a route observation,
  or requiring `--template`, Git cleanliness, or an inactive session, changes
  the target-only read contract; invalid target input exits `2` instead.

## 6. Tests Required

- Template inspection: assert deterministic complete and profile-filtered JSON
  and human output, path/profile equality with the shared manifest selector,
  every official status, valid project-local hash absence, sorted records and
  area summaries, schema-2/hash/path/containment/regular-file failures, unknown
  profile rejection, and byte-identical source state. Patch filesystem writes,
  subprocess, and network/runtime entry points and assert none are called.
- Meta/documentation contract: parser-check every documented Harness command;
  assert the authoring sequence contains `trellis platforms --json`, source
  `inspect`, `trellis-meta`, actual-file inspection/direct edit, and separately
  target `agent-workflow` planning. Assert docs state manifest selection
  authority, hash provenance/project-local behavior, no target hash rewrite,
  and the Copier/Jinja/answers/Git-tag/tasks/migrations exclusions. Assert no
  Harness-private text was added under bundled `trellis-meta`.
- Agent-workflow profile: assert its exact required/optional literal selection
  and exclusions, inspect/selector equality, closed applicability, structured
  admission/remediation, schema-6 evidence shape/digest/round-trip/canonical
  replay, whole-file conflicts, verify/rollback, and byte-identical target hash
  map. Static source checks must exclude template runtimes, external command/
  network paths, and manifest keys for answers, tasks, or migrations.
- Route catalog/normalization: assert exact scopes, routes and model/effort
  pairs; sorted normalization; duplicate/raw input refusal; and explicit
  implement/check role-pin rejection plus dispatch routes from another lane or
  role-family scope.
- Effective-source codec: compose main and subagent defaults in one config plus
  a pinned role; compare bytes exactly across CRLF, comments, spacing, ordering,
  and final newline. Assert malformed TOML, wrong-table, missing/non-string or
  duplicate pairs, and escaped strings fail before output. Wrong-table and
  escaped-string cases are regression points for defects fixed during check.
- Override schema/digest: assert schema `3` round-trip, exact item keys,
  non-empty ordered unique scopes, catalog tuple validation, missing/extra/order/
  duplicate rejection, digest tamper rejection, and schema `1` compatibility.
  Exercise schema `4` adoption validation or snapshot incompatibility.
- Route-only schema/digest: assert schema `5` round-trip with exactly
  `selectionMode: "route-only"` and `profile: null`; reject non-null profile,
  wrong mode, developer/adoption state, empty/unsorted/non-catalog overrides,
  and an action list not exactly equal to sorted unique `ROUTE_TARGETS` paths.
  Reassert schemas `1`-`4` accept their prior string-profile shapes unchanged.
- CLI: assert help exposes repeatable `--route`, repeated flags normalize in
  JSON, `--route-only` requires at least one route and rejects explicitly
  supplied profile/developer/adoption flags with exit `2` and no `--output`, and
  every recovery parser rejects both `--route` and `--route-only`.
- Route inspection: the default validation set is exactly:

  ```text
  python -m unittest discover -s .trellis/tests -p 'test_harness_migration_inspect_routes.py'
  python -m unittest discover -s .trellis/tests -p 'test_harness_migration_cli.py'
  python -m compileall -q .trellis/scripts/harness_migration
  ```

  The focused inspect suite covers the stable eleven-scope order, dispatch
  `table` values, known shared-config reads, per-lane custom/missing/invalid
  states, deterministic JSON/human output, invalid target exit `2`, and no
  target mutation; the CLI suite preserves named lane selection and rejects
  cross-family routes.
- Route-only selection/resolve: assert clean `existing_trellis` admission only;
  shared `main` and `subagent-default` scopes produce one config action; missing
  paths auto-copy with a missing receipt preimage; existing equal and different
  paths expose exactly one `replace` decision and resolve only to live `copy`.
  Verify rollback removes missing-preimage files and restores exact existing
  preimages.
- Dispatch shared-file transaction: assert several lane overrides produce one
  action; an existing file uses its target preimage and preserves unselected
  lanes, comments, spacing, CRLF/LF, unrelated keys, and final-newline state;
  a missing file starts from template defaults. Change the reviewed preimage
  before apply and assert canonical replay refuses before backup. Then verify
  and rollback, comparing exact bytes or absence.
- Resolve/apply: for an existing customized target, assert `keep` and
  `sidecar` raise the live-copy error while `replace` yields `copy`. Apply
  a fresh route plan, inspect installed config/profile values, verify, rollback,
  and compare exact preimages or absence for created files.
- Canonical safety: assert undigested override edits fail digest validation;
  catalog-inconsistent tuples fail closed parsing; and re-digested overrides
  whose recorded action set or effective digests are not the canonical result
  fail replay. Change transformed source, target, profile, decision, or
  snapshot baseline and assert replay/staging blocks before backup or mutation.
  Assert no-route behavior remains unchanged. A fully canonical alternate
  catalog alias is a newly valid plan input, not distinguishable tampering.
- Manifest coverage: assert every exported file maps once; latent equal-ranked
  overlaps, malformed types, caches/runtime records, and forged support-only
  install actions are rejected.
- Profile coverage: assert `dispatch-only` is a strict subset of `complete`,
  contains exactly its approved roots, and excludes migration scripts/tests,
  the migration skill, and unrelated specs. Paths are POSIX; unknown profiles
  and an `AGENTS\\md` include are rejected.
- Stable dry run: compare two full plan dictionaries, compare target digest
  before/after, assert developer path rebinding, official baseline pairing,
  closed-schema rejection, and deterministic decision/action ordering.
- Plan-profile binding: omitted and explicit `complete` are equal;
  `dispatch-only` survives parse/resolve and digest validation; changed or
  unknown profiles fail. CLI help/parser coverage proves `--profile`, the
  `complete` default, and `dispatch-only` acceptance.
- Pre-write safety: assert non-Git, dirty Git, same/nested roots, link/reparse
  traversal, non-directory parents, nested active session JSON, unreadable
  session entries, stale sources, stale targets, and stale sidecars leave user
  content unchanged and create no unauthorized backup/write.
- Canonical profile safety: re-digested changes from `dispatch-only` to
  `complete` or `missing` are refused without target writes.
- Transaction recovery: inject failure before and after replacements; assert
  prepared/applying journal evidence exists, `apply_failed` is recoverable,
  backup digests match pre-images, and rollback returns the complete target
  digest to its pre-apply value.
- Verification order: mutate an installed file before verification and assert
  command execution is skipped; mutate it during a passing command and assert
  the post-pass fails. Repeat with a late preserved-root entry to prove the
  first pass is complete rather than short-circuiting early.
- Command semantics: mock Windows-resolved `python.exe` and `trellis.CMD` paths,
  assert subprocess receives the resolved executable while the report retains
  the logical array; accept only the exact structured no-current-task result.
- Installed-suite isolation: execute installed verification tests in a fixture
  without support-only export assets and assert support-dependent source tests
  skip rather than fail or silently weaken runtime checks.
- Rollback guards: assert receipt/root/backup tampering and post-apply edits
  refuse all restoration; inject partial rollback failure, assert
  `rollback_failed`, rerun, and compare every restored pre-image and created
  parent cleanup.
- Recovery coverage: assert exact partial-state admission; explicit direct
  baseline selection; version, hash, developer, tree-shape, link/reparse,
  dirty-worktree, and active-session refusal; closed plan schema and digest;
  deterministic decisions and resolution choices; canonical stale
  target/baseline and post-replay source-drift refusal before
  backup; preservation of project-owned roots and application files; prepared
  failure receipts; verification; retryable rollback; and a post-recovery
  normal plan classified as `existing_trellis`.
- Quarantine coverage: assert the selected `.codex/config.toml` expected and
  actual digests, exact rule and reason; closed/ordered audit codecs; no action,
  decision, staged source, or journal entry; unchanged absent target state in
  apply and both verification sweeps; non-merge mismatch refusal; canonical
  replay refusal after audit, manifest, baseline, or target drift; rollback
  exclusion; and normal handling in a fresh post-recovery complete plan.

## 7. Wrong vs Correct

### Wrong

```text
# Hashes and meta prose are incorrectly treated as semantic selectors.
select = template_hashes.keys()
render_with_copier_answers(select)
rewrite(target / ".trellis/.template-hashes.json")
```

Correct authoring and distribution keep each authority explicit:

```text
trellis platforms --json
inspect --template <root> --profile agent-workflow --format json
# read relevant trellis-meta guidance and actual files; edit/test source directly
plan --template <root> --target <root> --profile agent-workflow --output plan.json
resolve -> approved apply -> verify -> optional approved rollback
```

The manifest selects the closure; hashes only describe official provenance;
schema-6 admission and the normal transaction govern target mutation.

```python
# The caller silently broadens a reviewed dispatch migration after planning.
plan["profile"] = "complete"
plan["planDigest"] = recalculate_digest(plan)
copytree(template / ".trellis", target / ".trellis", dirs_exist_ok=True)
```

This changes the profile-owned action set, bypasses canonical revalidation,
and also bypasses ownership decisions, live-state rebinding, and recovery
guards.

Also wrong for routes:

```python
patch_toml(target / ".codex/config.toml", route)  # pre-plan overlay
apply_plan(plan)
write_text(target / ".codex/config.toml.harness-new", route)  # sidecar "success"
```

These writes are outside the reviewed action digest and receipt, and a sidecar
does not make the requested live route effective.

Also wrong for a shared dispatch file:

```python
postimage = patch_selected_lanes(template_dispatch_bytes, overrides)
```

This resets target-customized, unselected lanes. For an existing file, compose
the selected field replacements over `target_preimage`; bind that complete
postimage and preimage to the plan, canonical replay, receipt, and rollback.

Also wrong for route-only selection:

```text
plan --route-only --profile complete --route main=planning
```

This either widens selection or relies on a profile when route-only must derive
its action set solely from the named route targets.

Also wrong for inspection:

```text
inspect-routes --template <root> --target <root>
# or reject the target because Git is dirty or a session is active
```

Inspection has no template comparison or migration admission gate.

### Correct

```text
plan --profile dispatch-only --route main=planning \
  --route role:research=exploration --format json --output plan.json
resolve --plan plan.json --decision <id>=<allowed-choice> --output resolved.json
apply --plan resolved.json --approve --backup <external-root> --format json
verify --receipt <external-root>/receipt.json --format json
# only when explicitly authorized:
rollback --receipt <external-root>/receipt.json --approve --format json
```

For a route-only replacement, use the same transaction without a profile:

```text
plan --route-only --route main=planning --route subagent-default=bounded_worker \
  --template <root> --target <clean-existing-trellis-root> --output plan.json
resolve --plan plan.json --decision <route-only-decision>=replace --output resolved.json
apply --plan resolved.json --approve --backup <external-root>
```

The same narrow transaction supports named dispatch lanes:

```text
plan --route-only \
  --route dispatch:implement:hard=hard_implementation \
  --route dispatch:check:hard=hard_checking \
  --template <root> --target <clean-existing-trellis-root> --output plan.json
```

For an observational route report, use the target alone:

```text
inspect-routes --target <root> --format json
```

All target filesystem authority stays in the deterministic CLI, and every
destructive step remains bound to canonical digests, live safety checks, and a
recoverable receipt. Route changes belong on `plan --route scope=route`, become
effective source before digests, and must resolve override-owned collisions as
`replace` so approved apply writes the live destination.
