# Implementation Plan

## Stax-Stacked Workflow

This task is pinned to `stax-stacked`. The coordinator owns topology, branch and
worktree creation, leases, commits, Draft publication, restacks, sync and
cleanup. Workers and paired checkers edit only their admitted worktree and
owned paths; they must not run Stax topology, push, submit, merge, restack or
cleanup commands.

Planned linear layers:

1. `google-providers`: service IDs, `tk` generation, GET request construction,
   parsing and local fixture tests.
2. `ui-docs`: provider labels/configuration integration and documentation,
   based on the first layer's frozen head.

Before creating branches or worktrees, inspect the topology with a read-only
`stax submit --plan --json` or equivalent status/plan command. For each layer,
the coordinator must persist a binding containing task ID, stack ID, branch,
immediate base branch, lane ID, worker identity, owned paths, lease ID and full
expected parent object ID. The bottom layer targets `master`; the second layer
targets the bottom branch.

For every implement or paired-check dispatch, run:

```text
python .agents/skills/trellis-stax-stacked/scripts/admit.py <child-task-dir> --json
```

Dispatch is allowed only when the envelope is `admitted` with no failures. Bind
all check evidence to the exact branch head and parent head. Any amend,
restack, rebase or conflict continuation invalidates that layer and all
descendant evidence; re-admit and recheck before publication.

After the scoped paired checks pass, inspect `stax submit --plan --json` and
publish Draft PRs only. Readiness and merge remain human decisions. The final
stack gate must verify current heads, parent bases, PR chain, checks and stale
descendant evidence before any human review/landing decision.

## Contract

```json
{"schemaVersion":1,"forbiddenVerification":["test","lint","typecheck","build"],"units":[{"id":"google-providers","dependsOn":[],"ownedPaths":["src/TranslationService.cpp","src/TranslationService.h","tests/translation-api.ts"],"forbiddenPaths":["ext/**"],"allowedGenerators":[],"actions":["Add Google and GoogleAPI providers, tk generation, GET requests, parsing and fixture coverage."],"acceptanceCriteria":["AC1","AC2","AC3","AC4"],"stopConditions":["The provider contract requires changing popup lifecycle or exposing secrets."]},{"id":"ui-docs","dependsOn":["google-providers"],"ownedPaths":["src/TranslationConfig.cpp","src/SelectionTranslate.cpp","docs/md/Customize-search-translation-services.md"],"forbiddenPaths":["ext/**"],"allowedGenerators":[],"actions":["Expose canonical provider names and document endpoint behavior without changing popup lifecycle."],"acceptanceCriteria":["AC1","AC5","AC6"],"stopConditions":["The change requires replacing the existing Google Cloud provider."]}]}
```

## Validation Plan

- Run `bun cmd/format.ts` after source/test edits.
- Run `bun tests/translation-api.ts --no-build`.
- Run `bun tests/translation-config.ts --no-build` and
  `bun tests/selection-translate-popup.ts --no-build`.
- Run `bun cmd/build.ts -debug` and `git diff --check`.
- Do not call live Google endpoints in automated tests.
