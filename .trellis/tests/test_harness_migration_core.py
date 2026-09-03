from __future__ import annotations

import json
import os
import shutil
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".trellis" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from harness_migration.codec import atomic_write_json, digest_path  # noqa: E402
from harness_migration.cli import main as migration_main  # noqa: E402
import harness_migration.transaction as transaction_module  # noqa: E402
from harness_migration.inspect import inspect_template  # noqa: E402
from harness_migration.manifest import exported_files, load_manifest  # noqa: E402
from harness_migration.models import ExitCode, MigrationError, ROUTE_CATALOG, plan_from_dict  # noqa: E402
from harness_migration.planner import build_plan as _build_plan, calculate_plan_digest, normalize_route_overrides, resolve_plan, source_bytes, validate_plan_digest  # noqa: E402
from harness_migration.safety import active_sessions, contained_path  # noqa: E402
from harness_migration.transaction import _write_receipt, apply_plan, load_receipt, rollback_receipt  # noqa: E402
from harness_migration.verify import (  # noqa: E402
    DEFAULT_COMMAND_TIMEOUT_SECONDS,
    UNITTEST_COMMAND_TIMEOUT_SECONDS,
    _run,
    verify_integrity,
    verify_receipt,
)
from common.paths import get_developer  # noqa: E402


def build_plan(*args, **kwargs):
    """Existing transaction tests intentionally exercise the authoring-root path."""
    kwargs.setdefault("development_template", True)
    return _build_plan(*args, **kwargs)


def git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *args], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )


def initialize_git(path: Path) -> None:
    git(path, "init", "-q")
    git(path, "config", "user.email", "migration-tests@example.invalid")
    git(path, "config", "user.name", "Migration Tests")
    (path / "project.txt").write_text("project\n", encoding="utf-8")
    git(path, "add", ".")
    git(path, "commit", "-qm", "fixture")


def resolve_all(plan, *, existing: bool = False, modified_sidecar: str | None = None):
    selections: dict[str, str] = {}
    for decision in plan.decisions:
        if decision.id.startswith("official-baseline:"):
            selections[decision.id] = "preserve"
        elif modified_sidecar and modified_sidecar in decision.paths:
            selections[decision.id] = "sidecar"
        elif existing:
            selections[decision.id] = "keep" if "keep" in decision.allowed_choices else "skip"
        else:
            selections[decision.id] = "install" if "install" in decision.allowed_choices else "replace"
    return resolve_plan(plan, selections)


@unittest.skipUnless((ROOT / "export-manifest.json").is_file(), "requires a Harness source template")
class HarnessMigrationCoreTests(unittest.TestCase):
    def test_route_catalog_matches_persistent_dispatch_policy(self) -> None:
        self.assertEqual({
            "main": {
                "coordination": ("gpt-5.6-sol", "medium"),
                "planning": ("gpt-5.6-sol", "medium"),
            },
            "subagent-default": {"bounded_worker": ("gpt-5.6-terra", "high")},
            "role:research": {"exploration": ("gpt-5.6-terra", "medium")},
            "role:debug": {"debugging": ("gpt-5.6-sol", "low")},
            "role:review": {"review": ("gpt-5.6-sol", "high")},
            "role:audit": {"audit": ("gpt-5.6-sol", "high")},
            "role:release": {"release": ("gpt-5.6-sol", "high")},
            "dispatch:implement:default": {"bounded_worker": ("gpt-5.6-terra", "high")},
            "dispatch:implement:hard": {"hard_implementation": ("gpt-5.6-sol", "medium")},
            "dispatch:check:default": {
                "checking": ("gpt-5.6-terra", "max"),
                "checking_sol_medium": ("gpt-5.6-sol", "medium"),
            },
            "dispatch:check:hard": {"hard_checking": ("gpt-5.6-sol", "xhigh")},
        }, ROUTE_CATALOG)
        for rejected in (
            "role:implement=bounded_worker", "role:check=checking",
            "main=gpt-5.6-sol", "main=hard_implementation",
            "subagent-default=memory_worker",
            "dispatch:implement:default=checking", "dispatch:check:default=bounded_worker",
        ):
            with self.subTest(rejected=rejected), self.assertRaises(MigrationError):
                normalize_route_overrides([rejected])

    def test_route_overrides_are_closed_sorted_and_transform_only_owned_assignments(self) -> None:
        overrides = normalize_route_overrides([
            "role:research=exploration", "subagent-default=bounded_worker", "main=planning",
        ])
        self.assertEqual(["main", "role:research", "subagent-default"], [item.scope for item in overrides])
        config = source_bytes(
            ROOT, ".codex/config.toml", ".codex/config.toml", None,
            "merge_required", overrides,
        ).decode("utf-8")
        self.assertIn('model = "gpt-5.6-sol"', config)
        self.assertIn('model_reasoning_effort = "medium"', config)
        self.assertIn('default_subagent_model = "gpt-5.6-terra"', config)
        self.assertIn('default_subagent_reasoning_effort = "high"', config)
        research = source_bytes(
            ROOT, ".codex/agents/trellis-research.toml",
            ".codex/agents/trellis-research.toml", None,
            "replaceable_managed", overrides,
        ).decode("utf-8")
        self.assertIn('model = "gpt-5.6-terra"', research)
        self.assertIn('model_reasoning_effort = "medium"', research)
        with self.assertRaises(MigrationError):
            normalize_route_overrides(["role:implement=bounded_worker"])
        with self.assertRaises(MigrationError):
            normalize_route_overrides(["main=planning", "main=coordination"])

    def test_route_transform_preserves_unrelated_bytes_and_rejects_invalid_toml(self) -> None:
        template = self.base / "route-source"
        config = template / ".codex" / "config.toml"
        config.parent.mkdir(parents=True)
        original = (
            b'# heading\r\nmodel  =  "old-main" # keep\r\n'
            b'model_reasoning_effort="low"\r\nunchanged = [1, 2]\r\n\r\n'
            b'[agents] # defaults\r\nmax_depth = 1\r\n'
            b'default_subagent_model = "old-worker"\r\n'
            b'default_subagent_reasoning_effort = "medium" # keep too\r\n'
        )
        config.write_bytes(original)
        overrides = normalize_route_overrides([
            "subagent-default=bounded_worker", "main=coordination",
        ])
        transformed = source_bytes(
            template, ".codex/config.toml", ".codex/config.toml", None,
            "merge_required", overrides,
        )
        expected = original.replace(b'"old-main"', b'"gpt-5.6-sol"').replace(
            b'model_reasoning_effort="low"', b'model_reasoning_effort="medium"',
        ).replace(b'"old-worker"', b'"gpt-5.6-terra"').replace(
            b'default_subagent_reasoning_effort = "medium"',
            b'default_subagent_reasoning_effort = "high"',
        )
        self.assertEqual(expected, transformed)

        config.write_text(
            'model = "old"\nmodel_reasoning_effort = "low"\n[broken\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MigrationError, "malformed TOML"):
            source_bytes(
                template, ".codex/config.toml", ".codex/config.toml", None,
                "merge_required", normalize_route_overrides(["main=coordination"]),
            )

        config.write_text(
            '[agents]\nmodel = "wrong-table"\nmodel_reasoning_effort = "low"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MigrationError, "string model pair in root"):
            source_bytes(
                template, ".codex/config.toml", ".codex/config.toml", None,
                "merge_required", normalize_route_overrides(["main=coordination"]),
            )

        config.write_text(
            'model = "old"\nmodel_reasoning_effort = "low"\n'
            '[unexpected]\nmodel = "also-old"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MigrationError, "wrong table"):
            source_bytes(
                template, ".codex/config.toml", ".codex/config.toml", None,
                "merge_required", normalize_route_overrides(["main=coordination"]),
            )

        config.write_text(
            'model = "escaped\\\"value"\nmodel_reasoning_effort = "low"\n',
            encoding="utf-8",
        )
        with self.assertRaisesRegex(MigrationError, "exactly one model pair"):
            source_bytes(
                template, ".codex/config.toml", ".codex/config.toml", None,
                "merge_required", normalize_route_overrides(["main=coordination"]),
            )

    def test_no_route_plan_keeps_legacy_schema_and_existing_override_requires_copy(self) -> None:
        target = self.fresh_target("legacy-route")
        legacy = build_plan(str(ROOT), str(target), "alice", "dispatch-only")
        self.assertEqual(1, legacy.schema_version)
        self.assertNotIn("routeOverrides", legacy.to_dict())
        self.assertNotIn("adoptPartial", legacy.to_dict())

        installed = resolve_all(legacy)
        apply_plan(installed, str(self.base / "legacy-route-backup"))
        git(target, "add", ".")
        git(target, "commit", "-qm", "install harness")
        config = target / ".codex" / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                'model = "gpt-5.6-sol"', 'model = "local-model"', 1,
            ),
            encoding="utf-8",
        )
        git(target, "add", ".")
        git(target, "commit", "-qm", "customize route")

        routed = build_plan(
            str(ROOT), str(target), profile="dispatch-only",
            route_overrides=["main=coordination"],
        )
        route_decision = next(
            decision for decision in routed.decisions
            if ".codex/config.toml" in decision.paths
        )
        for ineffective in ("keep", "sidecar"):
            candidate = plan_from_dict(routed.to_dict())
            with self.assertRaisesRegex(MigrationError, "live-target copy"):
                resolve_plan(candidate, {route_decision.id: ineffective})
        resolved = resolve_plan(routed, {route_decision.id: "replace"})
        action = next(item for item in resolved.actions if item.path == ".codex/config.toml")
        self.assertEqual("copy", action.operation)

    def test_route_only_plan_is_closed_to_requested_paths_and_composes_shared_config(self) -> None:
        target = self.existing_target("route-only-selection")
        plan = build_plan(
            str(ROOT), str(target), route_only=True,
            route_overrides=[
                "role:debug=debugging", "subagent-default=bounded_worker", "main=planning",
            ],
        )
        value = plan.to_dict()
        self.assertEqual(5, plan.schema_version)
        self.assertEqual("route-only", value["selectionMode"])
        self.assertIsNone(value["profile"])
        self.assertFalse(value["adoptPartial"])
        self.assertEqual(
            [".codex/agents/trellis-debug.toml", ".codex/config.toml"],
            [action.path for action in plan.actions],
        )
        self.assertEqual(1, sum(action.path == ".codex/config.toml" for action in plan.actions))
        self.assertTrue(all(action.operation == "copy" for action in plan.actions))
        self.assertFalse(plan.decisions)
        self.assertEqual(value, plan_from_dict(value).to_dict())

        receipt, receipt_path = apply_plan(plan, str(self.base / "route-only-selection-backup"))
        self.assertEqual("applied", receipt["status"])
        config = (target / ".codex" / "config.toml").read_text(encoding="utf-8")
        self.assertIn('model = "gpt-5.6-sol"', config)
        self.assertIn('default_subagent_model = "gpt-5.6-terra"', config)
        self.assertIn('model_reasoning_effort = "low"', (target / ".codex" / "agents" / "trellis-debug.toml").read_text(encoding="utf-8"))
        self.assertEqual("success", verify_receipt(receipt_path, run_commands=False)["status"])
        self.assertEqual("rolled_back", rollback_receipt(receipt_path)["status"])
        self.assertFalse((target / ".codex" / "config.toml").exists())
        self.assertFalse((target / ".codex" / "agents" / "trellis-debug.toml").exists())

    def test_route_only_existing_files_are_replace_only_and_rollback_exact_preimages(self) -> None:
        target = self.existing_target("route-only-existing")
        overrides = normalize_route_overrides(["main=planning", "role:debug=debugging"])
        config = target / ".codex" / "config.toml"
        profile = target / ".codex" / "agents" / "trellis-debug.toml"
        config.parent.mkdir(parents=True)
        profile.parent.mkdir(parents=True)
        config.write_bytes(source_bytes(
            ROOT, ".codex/config.toml", ".codex/config.toml", None,
            "merge_required", overrides,
        ))
        profile.write_bytes(source_bytes(
            ROOT, ".codex/agents/trellis-debug.toml", ".codex/agents/trellis-debug.toml", None,
            "replaceable_managed", overrides,
        ))
        before = {path: digest_path(target / path) for path in (".codex/config.toml", ".codex/agents/trellis-debug.toml")}
        git(target, "add", ".")
        git(target, "commit", "-qm", "route preimages")

        plan = build_plan(str(ROOT), str(target), route_only=True, route_overrides=overrides)
        self.assertTrue(all(action.operation == "skip" for action in plan.actions))
        self.assertTrue(all(decision.allowed_choices == ["replace"] for decision in plan.decisions))
        for rejected in ("keep", "sidecar", "install"):
            candidate = plan_from_dict(plan.to_dict())
            with self.subTest(rejected=rejected), self.assertRaises(MigrationError):
                resolve_plan(candidate, {candidate.decisions[0].id: rejected})
        resolved = resolve_plan(plan, {decision.id: "replace" for decision in plan.decisions})
        self.assertTrue(all(action.operation == "copy" for action in resolved.actions))

        receipt, receipt_path = apply_plan(resolved, str(self.base / "route-only-existing-backup"))
        self.assertEqual("success", verify_receipt(receipt_path, run_commands=False)["status"])
        self.assertEqual("rolled_back", rollback_receipt(receipt_path)["status"])
        self.assertEqual(before, {path: digest_path(target / path) for path in before})

    def test_dispatch_route_only_composes_target_preimage_and_rejects_stale_replay(self) -> None:
        target = self.existing_target("dispatch-route-only")
        config = target / ".codex" / "trellis-dispatch.toml"
        config.parent.mkdir(parents=True, exist_ok=True)
        preimage = (
            b"# target-owned dispatch comments\r\n"
            b"[implement.default] # selected\r\nmodel = \"old-implement\"\r\nmodel_reasoning_effort = \"low\"\r\n\r\n"
            b"[implement.hard]\r\nmodel = \"custom-implement-hard\"\r\nmodel_reasoning_effort = \"custom-effort\"\r\n\r\n"
            b"[check.default]\r\nmodel = \"custom-check\"\r\nmodel_reasoning_effort = \"custom-effort\"\r\n\r\n"
            b"[check.hard]\r\nmodel = \"old-check\"\r\nmodel_reasoning_effort = \"low\" # selected\r\n\r\nextra = \"keep\"\r\n"
        )
        config.write_bytes(preimage)
        git(target, "add", ".")
        git(target, "commit", "-qm", "dispatch preimage")
        overrides = normalize_route_overrides([
            "dispatch:implement:default=bounded_worker",
            "dispatch:check:hard=hard_checking",
        ])

        stale = build_plan(str(ROOT), str(target), route_only=True, route_overrides=overrides)
        self.assertEqual([".codex/trellis-dispatch.toml"], [action.path for action in stale.actions])
        self.assertEqual(["replace"], stale.decisions[0].allowed_choices)
        stale = resolve_plan(stale, {stale.decisions[0].id: "replace"})
        config.write_bytes(preimage + b"# stale preimage\r\n")
        git(target, "add", ".")
        git(target, "commit", "-qm", "stale dispatch preimage")
        backup = self.base / "dispatch-stale-backup"
        with self.assertRaisesRegex(MigrationError, "canonical migration plan"):
            apply_plan(stale, str(backup))
        self.assertFalse(backup.exists())

        config.write_bytes(preimage)
        git(target, "add", ".")
        git(target, "commit", "-qm", "restore dispatch preimage")
        plan = build_plan(str(ROOT), str(target), route_only=True, route_overrides=overrides)
        resolved = resolve_plan(plan, {plan.decisions[0].id: "replace"})
        receipt, receipt_path = apply_plan(resolved, str(self.base / "dispatch-route-backup"))
        expected = preimage.replace(b'"old-implement"', b'"gpt-5.6-terra"').replace(
            b'model_reasoning_effort = "low"', b'model_reasoning_effort = "high"', 1,
        ).replace(b'"old-check"', b'"gpt-5.6-sol"').replace(
            b'model_reasoning_effort = "low" # selected', b'model_reasoning_effort = "xhigh" # selected',
        )
        self.assertEqual(expected, config.read_bytes())
        self.assertEqual("success", verify_receipt(receipt_path, run_commands=False)["status"])
        self.assertEqual("rolled_back", rollback_receipt(receipt_path)["status"])
        self.assertEqual(preimage, config.read_bytes())
        self.assertEqual("applied", receipt["status"])

    def test_dispatch_route_only_creates_missing_configuration_from_template_defaults(self) -> None:
        target = self.existing_target("dispatch-route-create")
        overrides = normalize_route_overrides([
            "dispatch:implement:hard=hard_implementation",
            "dispatch:check:default=checking",
        ])
        plan = build_plan(str(ROOT), str(target), route_only=True, route_overrides=overrides)
        self.assertEqual([".codex/trellis-dispatch.toml"], [action.path for action in plan.actions])
        self.assertEqual([], plan.decisions)
        receipt, receipt_path = apply_plan(plan, str(self.base / "dispatch-create-backup"))
        config = target / ".codex" / "trellis-dispatch.toml"
        self.assertIn('[implement.default]', config.read_text(encoding="utf-8"))
        self.assertIn('model_reasoning_effort = "xhigh"', config.read_text(encoding="utf-8"))
        self.assertEqual("success", verify_receipt(receipt_path, run_commands=False)["status"])
        self.assertEqual("rolled_back", rollback_receipt(receipt_path)["status"])
        self.assertFalse(config.exists())
        self.assertEqual("applied", receipt["status"])

    def test_route_only_schema_and_admission_are_digest_and_canonical_bound(self) -> None:
        fresh = self.fresh_target("route-only-fresh")
        with self.assertRaisesRegex(MigrationError, "requires a target classified exactly") as raised:
            build_plan(str(ROOT), str(fresh), route_only=True, route_overrides=["main=planning"])
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)

        partial = self.fresh_target("route-only-partial")
        (partial / ".codex").mkdir()
        with self.assertRaisesRegex(MigrationError, "requires a target classified exactly"):
            build_plan(str(ROOT), str(partial), route_only=True, route_overrides=["main=planning"])

        target = self.existing_target("route-only-schema")
        plan = build_plan(str(ROOT), str(target), route_only=True, route_overrides=["main=planning"])
        value = plan.to_dict()
        malformed_values = []
        wrong_profile = json.loads(json.dumps(value))
        wrong_profile["profile"] = "complete"
        malformed_values.append(wrong_profile)
        wrong_mode = json.loads(json.dumps(value))
        wrong_mode["selectionMode"] = "complete"
        malformed_values.append(wrong_mode)
        wrong_path = json.loads(json.dumps(value))
        wrong_path["actions"][0]["path"] = "AGENTS.md"
        malformed_values.append(wrong_path)
        for malformed in malformed_values:
            with self.subTest(value=malformed), self.assertRaises(MigrationError):
                plan_from_dict(malformed)

        plan.selection_mode = None
        plan.plan_digest = calculate_plan_digest(plan)
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            validate_plan_digest(plan)

        plan = build_plan(str(ROOT), str(target), route_only=True, route_overrides=["main=planning"])
        plan.actions[0].reason = "forged route-only action"
        plan.plan_digest = calculate_plan_digest(plan)
        backup = self.base / "route-only-forged-backup"
        before = digest_path(target)
        with self.assertRaisesRegex(MigrationError, "canonical migration plan") as raised:
            apply_plan(plan, str(backup))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertEqual(before, digest_path(target))
        self.assertFalse(backup.exists())

    def test_raw_route_pair_schema_round_trips_and_applies_transactionally(self) -> None:
        target = self.existing_target("raw-route-pair")
        plan = build_plan(
            str(ROOT), str(target), route_only=True,
            route_pairs=["role:research=gpt-5.6-terra,xhigh"],
        )
        self.assertEqual(7, plan.schema_version)
        value = plan.to_dict()
        self.assertEqual(
            [{"scope": "role:research", "model": "gpt-5.6-terra", "effort": "xhigh"}],
            value["routeOverrides"],
        )
        self.assertEqual(value, plan_from_dict(value).to_dict())

        malformed = json.loads(json.dumps(value))
        malformed["routeOverrides"][0]["route"] = "exploration"
        with self.assertRaises(MigrationError):
            plan_from_dict(malformed)

        resolved = resolve_plan(
            plan,
            {decision.id: "replace" for decision in plan.decisions},
        )
        receipt, receipt_path = apply_plan(
            resolved, str(self.base / "raw-route-pair-backup"),
        )
        research = target / ".codex" / "agents" / "trellis-research.toml"
        self.assertIn('model_reasoning_effort = "xhigh"', research.read_text(encoding="utf-8"))
        self.assertEqual("success", verify_receipt(receipt_path, run_commands=False)["status"])
        self.assertEqual("applied", receipt["status"])

    def test_override_plan_schema_rejects_tampered_policy_tuple(self) -> None:
        target = self.fresh_target("schema-route")
        plan = build_plan(
            str(ROOT), str(target), "alice", "dispatch-only",
            route_overrides=["role:debug=debugging"],
        )
        self.assertEqual(3, plan.schema_version)
        value = plan.to_dict()
        self.assertEqual("role:debug", value["routeOverrides"][0]["scope"])
        self.assertEqual(plan.to_dict(), plan_from_dict(value).to_dict())
        value["routeOverrides"][0]["effort"] = "high"
        with self.assertRaises(MigrationError):
            plan_from_dict(value)

    def test_override_plan_schema_is_closed_ordered_and_digest_bound(self) -> None:
        target = self.fresh_target("closed-route-schema")
        plan = build_plan(
            str(ROOT), str(target), "alice", "dispatch-only",
            route_overrides=["role:research=exploration", "main=coordination"],
        )
        value = plan.to_dict()
        malformed_values = []

        missing = json.loads(json.dumps(value))
        missing.pop("routeOverrides")
        malformed_values.append(missing)
        unknown = json.loads(json.dumps(value))
        unknown["routeOverrides"][0]["unexpected"] = True
        malformed_values.append(unknown)
        unsorted = json.loads(json.dumps(value))
        unsorted["routeOverrides"].reverse()
        malformed_values.append(unsorted)
        duplicated = json.loads(json.dumps(value))
        duplicated["routeOverrides"][1] = dict(duplicated["routeOverrides"][0])
        malformed_values.append(duplicated)
        for malformed in malformed_values:
            with self.subTest(keys=sorted(malformed)), self.assertRaises(MigrationError):
                plan_from_dict(malformed)

        tampered = plan_from_dict(value)
        tampered.actions[0].reason = "tampered"
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            validate_plan_digest(tampered)

    def test_adoption_route_plan_uses_closed_schema_four_and_refuses_snapshot(self) -> None:
        template = self.base / "adoption-route-template"
        shutil.copytree(ROOT, template)
        config = template / ".codex" / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                'model = "gpt-5.6-sol"', 'model = "snapshot-main-model"', 1,
            ),
            encoding="utf-8",
        )
        hashes_path = template / ".trellis" / ".template-hashes.json"
        hashes = json.loads(hashes_path.read_text(encoding="utf-8"))
        hashes["hashes"][".codex/config.toml"] = digest_path(config).removeprefix("sha256:")
        atomic_write_json(hashes_path, hashes)
        target = self.partial_target("adoption-route-schema")
        for relative in (".trellis/.version", ".trellis/.template-hashes.json"):
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template / relative, destination)
        git(target, "add", ".")
        git(target, "commit", "-qm", "add official baseline pair")
        plan = build_plan(
            str(template), str(target), profile="complete", adopt_partial=True,
            route_overrides=["role:debug=debugging", "main=planning"],
        )
        value = plan.to_dict()

        self.assertEqual(4, plan.schema_version)
        self.assertTrue(value["adoptPartial"])
        self.assertEqual(
            ["main", "role:debug"],
            [item["scope"] for item in value["routeOverrides"]],
        )
        self.assertEqual(
            {"scope", "route", "model", "effort"},
            set(value["routeOverrides"][0]),
        )
        self.assertEqual(value, plan_from_dict(value).to_dict())

        extra = json.loads(json.dumps(value))
        extra["routeOverrides"][0]["extra"] = "not-closed"
        with self.assertRaisesRegex(MigrationError, "unknown or missing fields"):
            plan_from_dict(extra)
        tampered = plan_from_dict(value)
        tampered.route_overrides = tuple(reversed(tampered.route_overrides))
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            validate_plan_digest(tampered)

        resolved = resolve_plan(plan, {
            decision.id: (
                "snapshot" if decision.id.startswith("official-baseline:")
                else "install" if "install" in decision.allowed_choices
                else "replace"
            )
            for decision in plan.decisions
        })
        config_action = next(
            action for action in resolved.actions if action.path == ".codex/config.toml"
        )
        self.assertNotEqual(
            "sha256:" + hashes["hashes"][".codex/config.toml"],
            config_action.source_digest,
        )
        self.assertEqual(
            "snapshot",
            next(
                decision.selection for decision in resolved.decisions
                if decision.id.startswith("official-baseline:")
            ),
        )
        backup = self.base / "adoption-route-backup"
        before = digest_path(target)
        with self.assertRaisesRegex(MigrationError, "snapshot baseline") as raised:
            apply_plan(resolved, str(backup))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertEqual(before, digest_path(target))
        self.assertFalse(backup.exists())

    def test_route_override_apply_verify_and_rollback(self) -> None:
        target = self.fresh_target("route-transaction")
        plan = resolve_all(build_plan(
            str(ROOT), str(target), "alice", "dispatch-only",
            route_overrides=["main=planning", "role:debug=debugging"],
        ))
        receipt, receipt_path = apply_plan(plan, str(self.base / "route-backup"))
        self.assertEqual("applied", receipt["status"])
        config = (target / ".codex/config.toml").read_text(encoding="utf-8")
        debug = (target / ".codex/agents/trellis-debug.toml").read_text(encoding="utf-8")
        self.assertIn('model = "gpt-5.6-sol"', config)
        self.assertIn('model_reasoning_effort = "medium"', config)
        self.assertIn('model_reasoning_effort = "low"', debug)
        self.assertEqual("success", verify_receipt(receipt_path, run_commands=False)["status"])
        self.assertEqual("rolled_back", rollback_receipt(receipt_path)["status"])
        self.assertFalse((target / ".codex/config.toml").exists())
        self.assertFalse((target / ".codex/agents/trellis-debug.toml").exists())

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def fresh_target(self, name: str = "target") -> Path:
        target = self.base / name
        target.mkdir()
        initialize_git(target)
        return target

    def partial_target(self, name: str = "partial") -> Path:
        target = self.base / name
        target.mkdir()
        (target / "project.txt").write_text("project\n", encoding="utf-8")
        for relative, contents in (
            (".trellis/spec/project.md", "project spec\n"),
            (".trellis/tasks/local/prd.md", "task history\n"),
            (".trellis/workspace/kino/journal.md", "journal\n"),
            (".trellis/.developer", "name=kino\n"),
            (".trellis/.current-task", "local\n"),
            (".trellis/.runtime/sessions/placeholder.json", "{}\n"),
        ):
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        initialize_git(target)
        return target

    def existing_target(self, name: str = "existing") -> Path:
        target = self.fresh_target(name)
        (target / ".trellis").mkdir()
        (target / ".trellis" / "config.yaml").write_text("project: test\n", encoding="utf-8")
        (target / ".trellis" / "workflow.md").write_text("workflow\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "existing Trellis fixture")
        return target

    def admitted_agent_workflow_target(self, name: str = "agent-workflow") -> Path:
        target = self.existing_target(name)
        prerequisites = (
            ".codex/config.toml",
            ".codex/trellis-dispatch.toml",
            ".codex/hooks.json",
            ".codex/agents/trellis-implement.toml",
            ".codex/agents/trellis-check.toml",
            ".codex/agents/trellis-research.toml",
            ".trellis/scripts/common/active_task.py",
            ".trellis/scripts/common/config.py",
            ".trellis/scripts/common/paths.py",
        )
        for relative in prerequisites:
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        git(target, "add", ".")
        git(target, "commit", "-qm", "establish dispatch workflow baseline")
        return target

    def test_partial_adoption_is_complete_only_closed_and_preserves_project_roots(self) -> None:
        target = self.partial_target()
        project_spec = ".trellis/spec/project.md"
        project_spec_digest = digest_path(target / project_spec)
        preserved = {
            relative: digest_path(target / relative)
            for relative in (
                ".trellis/tasks", ".trellis/workspace", ".trellis/.developer",
                ".trellis/.current-task", ".trellis/.runtime",
            )
        }
        plan = build_plan(str(ROOT), str(target), profile="complete", adopt_partial=True)
        self.assertEqual(2, plan.schema_version)
        self.assertTrue(plan.adopt_partial)
        self.assertEqual("unsupported_partial", plan.target_state)
        self.assertFalse(plan.blockers)
        self.assertIn("adoptPartial", plan.to_dict())
        self.assertEqual(plan.to_dict(), plan_from_dict(plan.to_dict()).to_dict())
        missing_marker = dict(plan.to_dict())
        missing_marker.pop("adoptPartial")
        with self.assertRaisesRegex(MigrationError, "unknown or missing fields"):
            plan_from_dict(missing_marker)
        false_marker = dict(plan.to_dict())
        false_marker["adoptPartial"] = False
        with self.assertRaisesRegex(MigrationError, "reserved for partial adoption"):
            plan_from_dict(false_marker)
        re_digested_marker = plan_from_dict(plan.to_dict())
        re_digested_marker.adopt_partial = False
        re_digested_marker.plan_digest = calculate_plan_digest(re_digested_marker)
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            validate_plan_digest(re_digested_marker)
        self.assertFalse(any("baseline" in field.lower() for field in plan.to_dict()))
        with patch("harness_migration.recovery.build_recovery_plan") as recovery:
            self.assertEqual(
                plan.to_dict(),
                build_plan(str(ROOT), str(target), profile="complete", adopt_partial=True).to_dict(),
            )
        recovery.assert_not_called()
        self.assertTrue(any(
            action.path == ".trellis/.developer" and action.operation == "skip"
            for action in plan.actions
        ))
        self.assertTrue(any(
            action.path.startswith(".trellis/spec/") and action.decision_id
            for action in plan.actions
        ))

        selections = {
            decision.id: (
                "snapshot" if decision.id.startswith("official-baseline:")
                else "install" if "install" in decision.allowed_choices
                else "replace"
            )
            for decision in plan.decisions
        }
        resolved = resolve_plan(plan, selections)
        receipt, receipt_path = apply_plan(resolved)
        self.assertEqual(3, receipt["schemaVersion"])
        self.assertTrue(receipt["adoptPartial"])
        self.assertEqual(set(preserved), set(receipt["preservedDigests"]))
        self.assertIn(".trellis/spec", receipt["projectStateDigests"])
        self.assertEqual("existing_trellis", build_plan(str(ROOT), str(target)).target_state)
        for relative, expected in preserved.items():
            self.assertEqual(expected, digest_path(target / relative), relative)
        self.assertEqual(project_spec_digest, digest_path(target / project_spec))
        self.assertNotIn(project_spec, {entry["path"] for entry in receipt["journal"]})
        initial_report = verify_receipt(receipt_path, run_commands=False)
        self.assertEqual(
            "success",
            initial_report["status"],
            [check for check in initial_report["checks"] if check["status"] != "passed"],
        )
        legacy = dict(receipt)
        legacy["schemaVersion"] = 2
        legacy.pop("projectStateDigests")
        _write_receipt(receipt_path, legacy)
        self.assertEqual(2, load_receipt(receipt_path)["schemaVersion"])
        missing_project_state = dict(receipt)
        missing_project_state.pop("projectStateDigests")
        _write_receipt(receipt_path, missing_project_state)
        with self.assertRaisesRegex(MigrationError, "unknown or missing fields"):
            load_receipt(receipt_path)
        extended_project_state = dict(receipt)
        extended_project_state["projectStateDigests"] = {
            **receipt["projectStateDigests"],
            "unexpected-project-state": "missing",
        }
        _write_receipt(receipt_path, extended_project_state)
        with self.assertRaisesRegex(MigrationError, "project state digest coverage"):
            load_receipt(receipt_path)
        _write_receipt(receipt_path, receipt)
        receipt = load_receipt(receipt_path)
        receipt["verificationCommands"] = [[
            "python", "-c",
            "from pathlib import Path; Path('.trellis/spec/project.md').write_text('changed\\n', encoding='utf-8')",
        ]]
        _write_receipt(receipt_path, receipt)
        report = verify_receipt(receipt_path)
        self.assertEqual("failed", report["status"])
        self.assertEqual("passed", report["commands"][0]["status"])
        self.assertEqual(
            "failed",
            next(check for check in report["checks"] if check["path"] == ".trellis/spec")["status"],
        )
        rollback_receipt(receipt_path)

    def test_partial_adoption_refuses_other_profiles_and_target_states(self) -> None:
        target = self.partial_target()
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(
                ExitCode.INVALID_INPUT,
                migration_main([
                    "plan", "--template", str(ROOT), "--target", str(target),
                    "--adopt-partial", "--format", "json",
                ]),
            )
        with self.assertRaisesRegex(MigrationError, "requires --profile complete"):
            build_plan(str(ROOT), str(target), profile="dispatch-only", adopt_partial=True)
        with self.assertRaisesRegex(MigrationError, "does not accept --developer"):
            build_plan(str(ROOT), str(target), "alice", profile="complete", adopt_partial=True)
        with self.assertRaisesRegex(MigrationError, "requires a target classified exactly"):
            build_plan(str(ROOT), str(self.fresh_target("fresh")), adopt_partial=True)
        existing = self.partial_target("existing")
        (existing / ".trellis" / "config.yaml").write_text("project: test\n", encoding="utf-8")
        (existing / ".trellis" / "workflow.md").write_text("workflow\n", encoding="utf-8")
        git(existing, "add", ".")
        git(existing, "commit", "-qm", "existing fixture")
        with self.assertRaisesRegex(MigrationError, "requires a target classified exactly"):
            build_plan(str(ROOT), str(existing), profile="complete", adopt_partial=True)

    def test_partial_adoption_reuses_normal_prewrite_blockers(self) -> None:
        non_git = self.base / "partial-non-git"
        (non_git / ".trellis" / "spec").mkdir(parents=True)
        plan = build_plan(str(ROOT), str(non_git), profile="complete", adopt_partial=True)
        self.assertTrue(any("Git worktree" in blocker for blocker in plan.blockers))

        dirty = self.partial_target("partial-dirty")
        (dirty / "untracked.txt").write_text("dirty\n", encoding="utf-8")
        plan = build_plan(str(ROOT), str(dirty), profile="complete", adopt_partial=True)
        self.assertIn("target Git worktree is dirty", plan.blockers)

        active = self.partial_target("partial-active")
        active_session = active / ".trellis" / ".runtime" / "sessions" / "active.json"
        active_session.write_text('{"active": true}\n', encoding="utf-8")
        git(active, "add", ".")
        git(active, "commit", "-qm", "active session fixture")
        plan = build_plan(str(ROOT), str(active), profile="complete", adopt_partial=True)
        self.assertTrue(any("active runtime session" in blocker for blocker in plan.blockers))

        linked = self.partial_target("partial-linked")
        link_path = linked / "AGENTS.md"
        with patch(
            "harness_migration.safety.is_link_like",
            side_effect=lambda path: path == link_path,
        ):
            plan = build_plan(str(ROOT), str(linked), profile="complete", adopt_partial=True)
        self.assertTrue(any("symlink traversal" in blocker for blocker in plan.blockers))

    def test_partial_adoption_canonical_replay_blocks_clean_decision_drift_before_backup(self) -> None:
        target = self.partial_target("partial-stale")
        plan = resolve_all(build_plan(str(ROOT), str(target), profile="complete", adopt_partial=True))
        (target / ".trellis" / "config.yaml").write_text("project: local\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "changed partial preimage")
        backup = self.base / "partial-stale-backup"

        with self.assertRaisesRegex(MigrationError, "canonical migration plan") as raised:
            apply_plan(plan, str(backup))

        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse(backup.exists())

    def test_route_canonical_replay_blocks_effective_source_drift_before_backup(self) -> None:
        template = self.base / "route-canonical-template"
        shutil.copytree(ROOT, template)
        config = template / ".codex" / "config.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                'model = "gpt-5.6-sol"', 'model = "pre-route-source-model"', 1,
            ),
            encoding="utf-8",
        )
        target = self.fresh_target("route-canonical-target")
        plan = resolve_all(build_plan(
            str(template), str(target), "alice", "dispatch-only",
            route_overrides=["main=planning"],
        ))
        config_action = next(
            action for action in plan.actions if action.path == ".codex/config.toml"
        )
        self.assertNotEqual(digest_path(config), config_action.source_digest)
        config.write_bytes(config.read_bytes() + b"\n# route source drift\n")
        backup = self.base / "route-canonical-backup"
        before = digest_path(target)
        real_build_plan = transaction_module.build_plan
        replay_overrides = []

        def record_replay_overrides(*args, **kwargs):
            replay_overrides.append(kwargs.get("route_overrides"))
            return real_build_plan(*args, **kwargs)

        with patch(
            "harness_migration.transaction.build_plan",
            side_effect=record_replay_overrides,
        ):
            with self.assertRaisesRegex(MigrationError, "canonical migration plan") as raised:
                apply_plan(plan, str(backup))

        self.assertEqual([plan.route_overrides], replay_overrides)
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertEqual(before, digest_path(target))
        self.assertFalse(backup.exists())

    def test_route_staging_recomputes_overrides_and_blocks_post_replay_source_drift(self) -> None:
        template = self.base / "route-staging-template"
        shutil.copytree(ROOT, template)
        target = self.fresh_target("route-staging-target")
        plan = resolve_all(build_plan(
            str(template), str(target), "alice", "dispatch-only",
            route_overrides=["role:debug=debugging"],
        ))
        backup = self.base / "route-staging-backup"
        before = digest_path(target)
        config = template / ".codex" / "agents" / "trellis-debug.toml"
        real_source_bytes = transaction_module.source_bytes
        route_reads = 0

        def drift_after_revalidation(*args, **kwargs):
            nonlocal route_reads
            data = real_source_bytes(*args, **kwargs)
            if args[2] == ".codex/agents/trellis-debug.toml":
                route_reads += 1
                self.assertEqual(plan.route_overrides, args[5])
                if route_reads == 1:
                    config.write_bytes(config.read_bytes() + b"\n# post-replay drift\n")
            return data

        with patch(
            "harness_migration.transaction.source_bytes",
            side_effect=drift_after_revalidation,
        ):
            with self.assertRaisesRegex(
                MigrationError, "source changed after validation",
            ) as raised:
                apply_plan(plan, str(backup))

        self.assertEqual(2, route_reads)
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertEqual(before, digest_path(target))
        self.assertFalse(backup.exists())

    def test_partial_adoption_failure_receipts_remain_loadable_and_retryable(self) -> None:
        target = self.partial_target("partial-failure")
        before = digest_path(target)
        plan = resolve_all(build_plan(str(ROOT), str(target), profile="complete", adopt_partial=True))
        failed_backup = self.base / "partial-failure-backup"
        with patch.dict(os.environ, {"HARNESS_MIGRATE_FAIL_AFTER": "1"}):
            with self.assertRaises(MigrationError) as raised:
                apply_plan(plan, str(failed_backup))
        self.assertEqual(ExitCode.APPLY_FAILED, raised.exception.exit_code)
        failed_path = failed_backup / "receipt.json"
        failed_receipt = load_receipt(failed_path)
        self.assertEqual("apply_failed", failed_receipt["status"])
        self.assertIsInstance(failed_receipt["failure"], str)
        rollback_receipt(failed_path)
        self.assertEqual(before, digest_path(target))

        rollback_target = self.partial_target("partial-rollback-failure")
        config = rollback_target / ".trellis" / "config.yaml"
        config.write_text("project: local\n", encoding="utf-8")
        git(rollback_target, "add", ".")
        git(rollback_target, "commit", "-qm", "partial rollback fixture")
        rollback_before = digest_path(rollback_target)
        rollback_plan = resolve_all(build_plan(
            str(ROOT), str(rollback_target), profile="complete", adopt_partial=True,
        ))
        _, rollback_path = apply_plan(rollback_plan, str(self.base / "partial-rollback-backup"))
        with patch("harness_migration.transaction._copy_bytes_atomic", side_effect=OSError("injected rollback failure")):
            with self.assertRaises(MigrationError) as rollback_error:
                rollback_receipt(rollback_path)
        self.assertEqual(ExitCode.ROLLBACK_REFUSED, rollback_error.exception.exit_code)
        rollback_failed = load_receipt(rollback_path)
        self.assertEqual("rollback_failed", rollback_failed["status"])
        self.assertIsInstance(rollback_failed["failure"], str)
        rollback_receipt(rollback_path)
        self.assertEqual(rollback_before, digest_path(rollback_target))

    def test_manifest_is_complete_and_excludes_runtime_and_caches(self) -> None:
        manifest = load_manifest(ROOT)
        files = exported_files(ROOT, manifest)
        self.assertGreater(len(files), 50)
        self.assertNotIn(".trellis/.runtime/sessions/codex-test.json", files)
        self.assertFalse(any("__pycache__" in path or path.endswith(".pyc") for path in files))
        self.assertIn(".trellis/scripts/harness_migrate.py", files)

    def test_dispatch_only_profile_selects_only_dispatch_surfaces(self) -> None:
        manifest = load_manifest(ROOT)
        complete = exported_files(ROOT, manifest)
        dispatch = exported_files(ROOT, manifest, "dispatch-only")

        self.assertEqual(complete, exported_files(ROOT, manifest, "complete"))
        self.assertLess(len(dispatch), len(complete))
        expected = {
            ".agents/skills/trellis-seven-role-routing/SKILL.md",
            ".agents/skills/trellis-seven-role-routing/references/model-routing.md",
            ".agents/skills/trellis-seven-role-routing/references/role-contract.md",
            ".codex/agents/trellis-audit.toml",
            ".codex/agents/trellis-check.toml",
            ".codex/agents/trellis-debug.toml",
            ".codex/agents/trellis-implement.toml",
            ".codex/agents/trellis-release.toml",
            ".codex/agents/trellis-research.toml",
            ".codex/agents/trellis-review.toml",
            ".codex/hooks/inject-spec-context.py",
            ".codex/hooks/inject-subagent-context.py",
            ".codex/hooks/inject-workflow-state.py",
            ".codex/hooks/session-start.py",
            ".trellis/agents/audit.md",
            ".trellis/agents/check.md",
            ".trellis/agents/debug.md",
            ".trellis/agents/implement.md",
            ".trellis/agents/release.md",
            ".trellis/agents/research.md",
            ".trellis/agents/review.md",
            "AGENTS.md",
            ".codex/config.toml",
            ".codex/trellis-dispatch.toml",
            ".codex/hooks.json",
            ".trellis/config.yaml",
            ".trellis/workflow.md",
            ".trellis/scripts/dispatch_routes.py",
            ".trellis/scripts/harness_migration/models.py",
            ".trellis/spec/backend/model-routing-and-dispatch.md",
        }
        self.assertEqual(30, len(expected))
        self.assertEqual(expected, set(dispatch))
        self.assertTrue(all(
            relative == PurePosixPath(relative).as_posix()
            and "\\" not in relative
            and not relative.startswith("/")
            for relative in dispatch
        ))
        self.assertEqual(
            {
                ".trellis/scripts/dispatch_routes.py",
                ".trellis/scripts/harness_migration/models.py",
            },
            {relative for relative in dispatch if relative.startswith(".trellis/scripts/")},
        )
        self.assertFalse(any(relative.startswith(".trellis/tests/") for relative in dispatch))
        self.assertFalse(any(relative.startswith(".agents/skills/harness-migration/") for relative in dispatch))
        self.assertEqual(
            {".trellis/spec/backend/model-routing-and-dispatch.md"},
            {relative for relative in dispatch if relative.startswith(".trellis/spec/")},
        )

        with self.assertRaisesRegex(MigrationError, "unknown migration profile"):
            exported_files(ROOT, manifest, "missing")

    def test_agent_workflow_profile_is_the_exact_literal_closure(self) -> None:
        manifest = load_manifest(ROOT)
        selected = set(exported_files(ROOT, manifest, "agent-workflow"))
        expected = {
            "AGENTS.md", ".trellis/workflow.md", ".codex/hooks.json",
            ".codex/agents/trellis-check.toml",
            ".trellis/scripts/common/workflow_selection.py",
            ".trellis/scripts/common/workflow_phase.py",
            ".trellis/scripts/task.py",
            ".agents/skills/trellis-check/SKILL.md",
            ".agents/skills/trellis-seven-role-routing/SKILL.md",
            ".agents/skills/trellis-seven-role-routing/references/model-routing.md",
            ".agents/skills/trellis-seven-role-routing/references/role-contract.md",
            ".trellis/spec/backend/model-routing-and-dispatch.md",
            ".trellis/tests/test_seven_role_customization.py",
        }
        expected.update(path.relative_to(ROOT).as_posix() for path in (ROOT / ".trellis/agents").glob("**/*") if path.is_file())
        expected.update(path.relative_to(ROOT).as_posix() for path in (ROOT / ".codex/hooks").glob("**/*") if path.is_file() and "__pycache__" not in path.parts and not path.name.endswith(".pyc"))
        self.assertEqual(expected, selected)
        self.assertEqual(
            sorted(selected),
            [record["path"] for record in inspect_template(str(ROOT), "agent-workflow")["files"]],
        )
        self.assertNotIn(".trellis/.template-hashes.json", selected)
        self.assertNotIn(".codex/config.toml", selected)
        self.assertNotIn(".codex/trellis-dispatch.toml", selected)
        self.assertNotIn(".codex/agents/trellis-implement.toml", selected)
        self.assertNotIn(".codex/agents/trellis-research.toml", selected)
        self.assertNotIn(".trellis/config.yaml", selected)
        self.assertEqual(("existing_trellis",), manifest.profiles["agent-workflow"].target_states)
        self.assertEqual("codex-dispatch-workflow-v1", manifest.profiles["agent-workflow"].capability)

        template = self.base / "variant-template"
        shutil.copytree(ROOT, template, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git"))
        variant = template / ".trellis/workflows/reviewed.md"
        variant.parent.mkdir(parents=True)
        variant.write_text("# Reviewed\n", encoding="utf-8")
        variant_manifest = load_manifest(template)
        self.assertIn(".trellis/workflows/reviewed.md", exported_files(template, variant_manifest, "agent-workflow"))

        target = self.admitted_agent_workflow_target("variant-target")
        plan = build_plan(str(template), str(target), profile="agent-workflow")
        variant_action = next(action for action in plan.actions if action.path == ".trellis/workflows/reviewed.md")
        self.assertEqual("copy", variant_action.operation)
        self.assertIsNone(variant_action.decision_id)

        target_variant = target / ".trellis/workflows/reviewed.md"
        target_variant.parent.mkdir(parents=True)
        target_variant.write_text("# Local Review\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "add local workflow variant")
        plan = build_plan(str(template), str(target), profile="agent-workflow")
        variant_action = next(action for action in plan.actions if action.path == ".trellis/workflows/reviewed.md")
        self.assertEqual("skip", variant_action.operation)
        variant_decision = next(decision for decision in plan.decisions if decision.id == variant_action.decision_id)
        self.assertEqual(["sidecar", "keep", "replace"], variant_decision.allowed_choices)

    def test_agent_workflow_admission_schema_six_and_canonical_replay(self) -> None:
        target = self.admitted_agent_workflow_target()
        plan = build_plan(str(ROOT), str(target), profile="agent-workflow")
        self.assertEqual(6, plan.schema_version)
        self.assertEqual("admitted", plan.prerequisite_evidence["status"])
        self.assertEqual(
            [
                "dispatch:check:default", "dispatch:check:hard",
                "dispatch:implement:default", "dispatch:implement:hard",
            ],
            [item["scope"] for item in plan.prerequisite_evidence["dispatchLanes"]],
        )
        self.assertEqual(plan.to_dict(), plan_from_dict(plan.to_dict()).to_dict())
        tampered = plan.to_dict()
        tampered["prerequisiteEvidence"]["status"] = "unknown"
        with self.assertRaisesRegex(MigrationError, "capability or status"):
            plan_from_dict(tampered)
        missing = plan.to_dict()
        del missing["prerequisiteEvidence"]["roles"]
        with self.assertRaisesRegex(MigrationError, "unknown or missing fields"):
            plan_from_dict(missing)
        extra = plan.to_dict()
        extra["prerequisiteEvidence"]["unexpected"] = True
        with self.assertRaisesRegex(MigrationError, "unknown or missing fields"):
            plan_from_dict(extra)
        digest_tampered = plan.to_dict()
        digest_tampered["prerequisiteEvidence"]["checkedFiles"][0]["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            validate_plan_digest(plan_from_dict(digest_tampered))

        resolved = resolve_all(plan)
        dispatch = target / ".codex/trellis-dispatch.toml"
        dispatch.write_text(dispatch.read_text(encoding="utf-8") + "\n# late semantic drift\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "late prerequisite drift")
        with self.assertRaisesRegex(MigrationError, "canonical migration plan") as raised:
            apply_plan(resolved)
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse(any(target.parent.glob(f".{target.name}.harness-backup-*")))

    def test_agent_workflow_whole_file_conflict_hash_preservation_and_rollback(self) -> None:
        target = self.admitted_agent_workflow_target()
        target_hashes = target / ".trellis/.template-hashes.json"
        target_hashes.parent.mkdir(parents=True, exist_ok=True)
        target_hashes.write_bytes((ROOT / ".trellis/.template-hashes.json").read_bytes())
        check_toml = target / ".codex/agents/trellis-check.toml"
        check_toml.write_text(check_toml.read_text(encoding="utf-8").replace(
            "You are running as the `trellis-check` sub-agent.",
            "You are running as the locally customized `trellis-check` sub-agent.",
        ), encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "customize workflow baseline")
        hash_digest = digest_path(target_hashes)
        before = digest_path(target)

        plan = build_plan(str(ROOT), str(target), profile="agent-workflow")
        check_decision = next(decision for decision in plan.decisions if decision.paths == [".codex/agents/trellis-check.toml"])
        self.assertEqual(["sidecar", "keep", "replace"], check_decision.allowed_choices)
        resolved = resolve_all(plan)
        _, receipt_path = apply_plan(resolved)
        self.assertEqual(hash_digest, digest_path(target_hashes))
        self.assertEqual("success", verify_receipt(receipt_path, run_commands=False)["status"])
        self.assertEqual(hash_digest, digest_path(target_hashes))
        rollback_receipt(receipt_path)
        self.assertEqual(before, digest_path(target))
        self.assertEqual(hash_digest, digest_path(target_hashes))

    def test_agent_workflow_admission_is_closed_and_has_no_template_runtime(self) -> None:
        target = self.existing_target()
        with self.assertRaises(MigrationError) as raised:
            build_plan(str(ROOT), str(target), profile="agent-workflow")
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertEqual("dispatch-only", raised.exception.details["remediation"]["profile"])
        self.assertEqual(
            sorted(raised.exception.details["failures"], key=lambda item: (item["code"], item["path"], item.get("detail", ""))),
            raised.exception.details["failures"],
        )

        source = "\n".join(
            (ROOT / ".trellis/scripts/harness_migration" / name).read_text(encoding="utf-8")
            for name in ("admission.py", "manifest.py", "planner.py", "transaction.py")
        ).lower()
        for forbidden in (
            "import copier", "from copier", "import jinja", "from jinja",
            "subprocess", "os.system", "popen", "urllib", "requests",
            "http.client", "httpx", "import socket", "from socket",
            ".copier-answers", "copier.yml", "copier.yaml", "git tag",
        ):
            self.assertNotIn(forbidden, source)

        manifest_value = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))

        def nested_keys(value: object) -> set[str]:
            if isinstance(value, dict):
                return set(value) | set().union(*(nested_keys(item) for item in value.values()))
            if isinstance(value, list):
                return set().union(*(nested_keys(item) for item in value))
            return set()

        self.assertTrue({"answers", "tasks", "migrations"}.isdisjoint(nested_keys(manifest_value)))

    def test_agent_workflow_admission_rejects_invalid_lanes_hooks_roles_and_pins(self) -> None:
        cases = (
            (
                ".codex/trellis-dispatch.toml",
                lambda text: text.replace('model_reasoning_effort = "medium"', 'model_reasoning_effort = 3', 1),
                "invalid_dispatch_lane",
            ),
            (
                ".codex/hooks.json",
                lambda text: text.replace("|trellis-research", ""),
                "missing_required_hook",
            ),
            (
                ".codex/agents/trellis-implement.toml",
                lambda text: 'model = "gpt-5.6-sol"\n' + text,
                "pinned_dispatch_role",
            ),
            (
                ".codex/agents/trellis-check.toml",
                lambda text: 'model_reasoning_effort = "high"\n' + text,
                "pinned_dispatch_role",
            ),
            (
                ".codex/agents/trellis-research.toml",
                lambda text: text.replace('name = "trellis-research"', 'name = "other"'),
                "invalid_role_identity",
            ),
            (
                ".codex/agents/trellis-check.toml",
                lambda text: text.replace("developer_instructions =", "other_instructions =", 1),
                "missing_role_instructions",
            ),
            (
                ".codex/hooks.json",
                lambda text: text.replace(".codex/hooks/inject-workflow-state.py", ".codex/hooks/other.py"),
                "missing_required_hook",
            ),
        )
        for index, (relative, mutate, expected_code) in enumerate(cases):
            with self.subTest(relative=relative):
                target = self.admitted_agent_workflow_target(f"invalid-admission-{index}")
                path = target / relative
                path.write_text(mutate(path.read_text(encoding="utf-8")), encoding="utf-8")
                git(target, "add", ".")
                git(target, "commit", "-qm", "invalidate prerequisite")
                with self.assertRaises(MigrationError) as raised:
                    build_plan(str(ROOT), str(target), profile="agent-workflow")
                self.assertIn(expected_code, {item["code"] for item in raised.exception.details["failures"]})

    def test_agent_workflow_admission_accepts_custom_dispatch_pairs(self) -> None:
        target = self.admitted_agent_workflow_target("custom-dispatch-admission")
        dispatch = target / ".codex" / "trellis-dispatch.toml"
        dispatch.write_text(
            dispatch.read_text(encoding="utf-8").replace(
                'model = "gpt-5.6-terra"\nmodel_reasoning_effort = "xhigh"',
                'model = "custom-model"\nmodel_reasoning_effort = "ultra"',
                1,
            ),
            encoding="utf-8",
        )
        git(target, "add", ".")
        git(target, "commit", "-qm", "custom dispatch pair")
        plan = build_plan(str(ROOT), str(target), profile="agent-workflow")
        lane = next(
            item for item in plan.prerequisite_evidence["dispatchLanes"]
            if item["scope"] == "dispatch:implement:default"
        )
        self.assertEqual("custom", lane["route"])
        self.assertEqual(("custom-model", "ultra"), (lane["model"], lane["effort"]))
        self.assertEqual(plan.to_dict(), plan_from_dict(plan.to_dict()).to_dict())

    def test_agent_workflow_admission_rejects_unsafe_or_unreadable_prerequisites(self) -> None:
        def missing(path: Path) -> None:
            path.unlink()

        def directory(path: Path) -> None:
            path.unlink()
            path.mkdir()

        def non_utf8(path: Path) -> None:
            path.write_bytes(b"\xff\xfe")

        def malformed_toml(path: Path) -> None:
            path.write_text("[broken\n", encoding="utf-8")

        def malformed_json(path: Path) -> None:
            path.write_text("{broken\n", encoding="utf-8")

        cases = (
            (".trellis/scripts/common/config.py", missing, "missing_file"),
            (".trellis/scripts/common/paths.py", directory, "not_regular_file"),
            (".codex/agents/trellis-check.toml", non_utf8, "non_utf8_file"),
            (".codex/config.toml", malformed_toml, "malformed_toml"),
            (".codex/hooks.json", malformed_json, "malformed_json"),
        )
        for index, (relative, mutate, expected_code) in enumerate(cases):
            with self.subTest(relative=relative):
                target = self.admitted_agent_workflow_target(f"unsafe-admission-{index}")
                mutate(target / relative)
                with self.assertRaises(MigrationError) as raised:
                    build_plan(str(ROOT), str(target), profile="agent-workflow")
                self.assertIn(expected_code, {item["code"] for item in raised.exception.details["failures"]})

        target = self.admitted_agent_workflow_target("link-like-admission")
        linked = target / ".trellis/scripts/common/active_task.py"
        with patch("harness_migration.safety.is_link_like", side_effect=lambda path: path == linked):
            with self.assertRaises(MigrationError) as raised:
                build_plan(str(ROOT), str(target), profile="agent-workflow")
        self.assertIn("unsafe_path", {item["code"] for item in raised.exception.details["failures"]})

    def test_agent_workflow_hook_commands_must_execute_the_required_scripts(self) -> None:
        target = self.admitted_agent_workflow_target("inert-hook-command")
        hooks = target / ".codex/hooks.json"
        hooks.write_text(hooks.read_text(encoding="utf-8").replace(
            "python -X utf8 .codex/hooks/inject-subagent-context.py",
            "echo .codex/hooks/inject-subagent-context.py",
        ), encoding="utf-8")
        with self.assertRaises(MigrationError) as raised:
            build_plan(str(ROOT), str(target), profile="agent-workflow")
        self.assertIn("missing_required_hook", {item["code"] for item in raised.exception.details["failures"]})

        target = self.admitted_agent_workflow_target("minimal-python-hook-command")
        hooks = target / ".codex/hooks.json"
        hooks.write_text(hooks.read_text(encoding="utf-8").replace(
            "python -X utf8 .codex/hooks/inject-subagent-context.py",
            "python .codex/hooks/inject-subagent-context.py",
        ), encoding="utf-8")
        self.assertEqual(6, build_plan(str(ROOT), str(target), profile="agent-workflow").schema_version)

    def test_manifest_rejects_invalid_types_and_latent_equal_overlaps(self) -> None:
        raw = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
        template = self.base / "invalid-manifest"
        template.mkdir()
        raw["migrationPolicy"]["migrationRules"][0]["modes"] = "fresh"
        atomic_write_json(template / "export-manifest.json", raw)
        with self.assertRaises(MigrationError):
            load_manifest(template)

        raw = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
        duplicate = dict(raw["migrationPolicy"]["migrationRules"][0])
        duplicate["path"] = ".latent/*"
        duplicate["sourceRequired"] = False
        raw["migrationPolicy"]["migrationRules"].extend([duplicate, dict(duplicate)])
        atomic_write_json(template / "export-manifest.json", raw)
        with self.assertRaisesRegex(MigrationError, "overlap"):
            load_manifest(template)

        raw = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
        raw["sourceVersion"] = 7
        atomic_write_json(template / "export-manifest.json", raw)
        with self.assertRaisesRegex(MigrationError, "sourceVersion"):
            load_manifest(template)

        raw = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
        raw["migrationPolicy"]["migrationRules"][0]["path"] = ".agents//skills/**"
        atomic_write_json(template / "export-manifest.json", raw)
        with self.assertRaisesRegex(MigrationError, "normalized"):
            load_manifest(template)

        raw = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
        raw["migrationProfiles"]["dispatch-only"]["include"][0] = "AGENTS\\md"
        with patch("harness_migration.manifest.read_json", return_value=raw):
            with self.assertRaisesRegex(MigrationError, "invalid migration rule path"):
                load_manifest(ROOT)

        raw = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
        raw["migrationProfiles"]["dispatch-only"]["include"].append("AGENTS.md")
        with patch("harness_migration.manifest.read_json", return_value=raw):
            with self.assertRaisesRegex(MigrationError, "duplicate include patterns"):
                load_manifest(ROOT)

        raw = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
        raw["migrationProfiles"]["dispatch-only"]["include"][0] = "missing/**"
        with patch("harness_migration.manifest.read_json", return_value=raw):
            with self.assertRaisesRegex(MigrationError, "matched no exported path"):
                load_manifest(ROOT)

        raw = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
        raw["migrationProfiles"]["agent-workflow"]["includeIfPresent"] = "optional/**"
        with patch("harness_migration.manifest.read_json", return_value=raw):
            with self.assertRaisesRegex(MigrationError, "includeIfPresent"):
                load_manifest(ROOT)

        raw = json.loads((ROOT / "export-manifest.json").read_text(encoding="utf-8"))
        raw["migrationProfiles"]["agent-workflow"]["requires"]["capability"] = "unknown"
        with patch("harness_migration.manifest.read_json", return_value=raw):
            with self.assertRaisesRegex(MigrationError, "requires is invalid"):
                load_manifest(ROOT)

    def test_fresh_plan_is_stable_and_non_mutating(self) -> None:
        target = self.fresh_target()
        before = digest_path(target)
        first = build_plan(str(ROOT), str(target), "alice")
        second = build_plan(str(ROOT), str(target), "alice")
        explicit_complete = build_plan(
            str(ROOT), str(target), "alice", profile="complete"
        )
        self.assertEqual("fresh", first.target_state)
        self.assertEqual("complete", first.profile)
        self.assertFalse(first.blockers)
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(first.to_dict(), explicit_complete.to_dict())
        self.assertEqual(before, digest_path(target))
        destinations = {action.path for action in first.actions}
        self.assertIn(".trellis/workspace/alice/index.md", destinations)
        self.assertNotIn(".trellis/workspace/kino/index.md", destinations)
        baseline = {
            action.path: action.operation for action in first.actions
            if action.path in {".trellis/.version", ".trellis/.template-hashes.json"}
        }
        self.assertEqual({".trellis/.version": "copy", ".trellis/.template-hashes.json": "copy"}, baseline)

        value = first.to_dict()
        value["actions"][0]["unexpected"] = True
        with self.assertRaises(MigrationError):
            plan_from_dict(value)

    def test_plan_profile_round_trips_and_is_digest_protected(self) -> None:
        target = self.fresh_target()
        plan = build_plan(str(ROOT), str(target), "alice", "dispatch-only")
        self.assertEqual("dispatch-only", plan.profile)
        self.assertEqual("dispatch-only", plan_from_dict(plan.to_dict()).profile)

        resolved = resolve_all(plan_from_dict(plan.to_dict()))
        self.assertEqual("dispatch-only", resolved.profile)
        self.assertEqual("dispatch-only", plan_from_dict(resolved.to_dict()).profile)
        validate_plan_digest(resolved)

        missing_profile = plan.to_dict()
        missing_profile.pop("profile")
        with self.assertRaisesRegex(MigrationError, "unknown or missing fields"):
            plan_from_dict(missing_profile)

        non_string_profile = plan.to_dict()
        non_string_profile["profile"] = None
        with self.assertRaisesRegex(MigrationError, "profile must be a string"):
            plan_from_dict(non_string_profile)

        plan.profile = "complete"
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            validate_plan_digest(plan)

        with self.assertRaisesRegex(MigrationError, "unknown migration profile"):
            build_plan(str(ROOT), str(target), "alice", "missing")

    def test_apply_revalidates_the_selected_profile_canonically(self) -> None:
        target = self.fresh_target()
        plan = resolve_all(build_plan(str(ROOT), str(target), "alice", "dispatch-only"))
        plan.profile = "complete"
        plan.plan_digest = calculate_plan_digest(plan)

        with self.assertRaisesRegex(MigrationError, "canonical migration plan") as raised:
            apply_plan(plan)
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse((target / ".trellis").exists())

        plan.profile = "missing"
        plan.plan_digest = calculate_plan_digest(plan)
        with self.assertRaisesRegex(MigrationError, "unknown migration profile"):
            apply_plan(plan)
        self.assertFalse((target / ".trellis").exists())

    def test_dirty_non_git_and_session_targets_are_blocked(self) -> None:
        non_git = self.base / "non-git"
        non_git.mkdir()
        plan = build_plan(str(ROOT), str(non_git), "alice")
        self.assertTrue(any("Git worktree" in item for item in plan.blockers))

        dirty = self.fresh_target("dirty")
        (dirty / "untracked.txt").write_text("dirty", encoding="utf-8")
        plan = build_plan(str(ROOT), str(dirty), "alice")
        self.assertIn("target Git worktree is dirty", plan.blockers)

        existing = self.fresh_target("session")
        (existing / ".trellis" / ".runtime" / "sessions").mkdir(parents=True)
        (existing / ".trellis" / "config.yaml").write_text("project: test\n", encoding="utf-8")
        (existing / ".trellis" / "workflow.md").write_text("workflow\n", encoding="utf-8")
        (existing / ".trellis" / ".runtime" / "sessions" / "active.json").write_text('{"active":true}\n', encoding="utf-8")
        git(existing, "add", ".")
        git(existing, "commit", "-qm", "existing")
        plan = build_plan(str(ROOT), str(existing))
        self.assertTrue(any("active runtime session" in item for item in plan.blockers))

        nested = self.fresh_target("nested-session")
        sessions = nested / ".trellis" / ".runtime" / "sessions"
        (sessions / "worker" / "deep").mkdir(parents=True)
        (nested / ".trellis" / "config.yaml").write_text("project: test\n", encoding="utf-8")
        (nested / ".trellis" / "workflow.md").write_text("workflow\n", encoding="utf-8")
        (sessions / "placeholder.json").write_text("{}\n", encoding="utf-8")
        (sessions / "worker" / "empty.json").write_text("null\n", encoding="utf-8")
        (sessions / "worker" / "deep" / "active.json").write_text('{"active":true}\n', encoding="utf-8")
        git(nested, "add", ".")
        git(nested, "commit", "-qm", "nested session fixture")
        plan = build_plan(str(ROOT), str(nested))
        session_blocker = next(item for item in plan.blockers if "active runtime session" in item)
        self.assertIn("worker/deep/active.json", session_blocker)
        self.assertNotIn("placeholder.json", session_blocker)
        self.assertNotIn("worker/empty.json", session_blocker)

    def test_same_nested_and_symlink_paths_are_refused(self) -> None:
        same = self.fresh_target("same")
        with self.assertRaises(MigrationError):
            build_plan(str(same), str(same), "alice")

        template = self.base / "template"
        nested = template / "nested-target"
        nested.mkdir(parents=True)
        with self.assertRaises(MigrationError):
            build_plan(str(template), str(nested), "alice")

        target = self.fresh_target("symlink")
        outside = self.base / "outside-agents.md"
        outside.write_text("outside\n", encoding="utf-8")
        try:
            (target / "AGENTS.md").symlink_to(outside)
        except OSError:
            self.skipTest("filesystem does not permit symlink creation")
        git(target, "add", ".")
        git(target, "commit", "-qm", "symlink fixture")
        plan = build_plan(str(ROOT), str(target), "alice")
        self.assertTrue(any("symlink traversal" in item for item in plan.blockers))

    def test_link_traversal_probe_is_platform_independent(self) -> None:
        target = self.fresh_target()
        linked = target / "linked"
        linked.mkdir()
        with patch("harness_migration.safety.is_link_like", side_effect=lambda path: path == linked):
            with self.assertRaisesRegex(MigrationError, "symlink traversal"):
                contained_path(target, "linked/child.txt")

        sessions = target / ".trellis" / ".runtime" / "sessions"
        nested_link = sessions / "worker" / "linked-runtime"
        nested_link.mkdir(parents=True)
        with patch("harness_migration.safety.is_link_like", side_effect=lambda path: path == nested_link):
            self.assertEqual(["worker/linked-runtime"], active_sessions(target))

        unreadable = sessions / "worker" / "unreadable.json"
        unreadable.write_text("{}\n", encoding="utf-8")
        original_lstat = Path.lstat

        def deny_nested_entry(path):
            if path == unreadable:
                raise PermissionError("injected unreadable session entry")
            return original_lstat(path)

        with patch.object(Path, "lstat", autospec=True, side_effect=deny_nested_entry):
            self.assertEqual(["worker/unreadable.json"], active_sessions(target))

    def test_non_directory_target_parent_becomes_a_plan_blocker(self) -> None:
        target = self.fresh_target()
        (target / ".agents").write_text("not a directory\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "partial target")
        plan = build_plan(str(ROOT), str(target), "alice")
        self.assertTrue(any("path parent is not a directory" in blocker for blocker in plan.blockers))

    def test_existing_target_without_official_baseline_requires_snapshot_pair(self) -> None:
        target = self.fresh_target()
        (target / ".trellis").mkdir()
        (target / ".trellis" / "config.yaml").write_text("project: test\n", encoding="utf-8")
        (target / ".trellis" / "workflow.md").write_text("workflow\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "existing without baseline")
        plan = build_plan(str(ROOT), str(target))
        baseline = next(decision for decision in plan.decisions if decision.id.startswith("official-baseline:"))
        self.assertEqual(["snapshot"], baseline.allowed_choices)

    def test_fresh_apply_verify_and_exact_rollback(self) -> None:
        target = self.fresh_target()
        staging_sentinel = target / "AGENTS.md.harness-tmp"
        staging_sentinel.write_text("project-owned staging name\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "staging sentinel")
        before = digest_path(target)
        plan = resolve_all(build_plan(str(ROOT), str(target), "alice"))
        receipt, receipt_path = apply_plan(plan)
        self.assertEqual("applied", receipt["status"])
        self.assertEqual("name=alice\n", (target / ".trellis" / ".developer").read_text(encoding="utf-8"))
        self.assertEqual("alice", get_developer(target))
        self.assertEqual("project-owned staging name\n", staging_sentinel.read_text(encoding="utf-8"))
        self.assertEqual(plan.verification_commands, receipt["verificationCommands"])
        self.assertFalse((target / ".trellis" / "workspace" / "kino").exists())
        report = verify_receipt(receipt_path, run_commands=False)
        self.assertEqual("success", report["status"])
        rollback_receipt(receipt_path)
        self.assertEqual(before, digest_path(target))
        self.assertFalse((target / ".trellis").exists())
        self.assertFalse((target / ".codex").exists())

    def test_atomic_json_write_does_not_consume_legacy_temp_name(self) -> None:
        destination = self.base / "document.json"
        sentinel = destination.with_name(destination.name + ".tmp")
        sentinel.write_text("project-owned\n", encoding="utf-8")
        atomic_write_json(destination, {"ok": True})
        self.assertEqual("project-owned\n", sentinel.read_text(encoding="utf-8"))
        parent_file = self.base / "not-a-directory"
        parent_file.write_text("occupied\n", encoding="utf-8")
        with self.assertRaisesRegex(MigrationError, "atomically write"):
            atomic_write_json(parent_file / "document.json", {"ok": False})

    def test_invalid_receipt_errors_use_command_specific_exit_codes(self) -> None:
        missing = self.base / "missing-receipt.json"
        with self.assertRaises(MigrationError) as verify_error:
            verify_receipt(missing, run_commands=False)
        self.assertEqual(ExitCode.VERIFICATION_FAILED, verify_error.exception.exit_code)
        with self.assertRaises(MigrationError) as rollback_error:
            rollback_receipt(missing)
        self.assertEqual(ExitCode.ROLLBACK_REFUSED, rollback_error.exception.exit_code)

    def test_unresolved_apply_and_failed_verification_are_explicit(self) -> None:
        unresolved_target = self.fresh_target("unresolved")
        unresolved = build_plan(str(ROOT), str(unresolved_target), "alice")
        with self.assertRaises(MigrationError) as raised:
            apply_plan(unresolved)
        self.assertEqual(ExitCode.UNRESOLVED, raised.exception.exit_code)
        self.assertFalse(any(unresolved_target.parent.glob(f".{unresolved_target.name}.harness-backup-*")))

        forged = resolve_all(unresolved)
        support_action = next(action for action in forged.actions if action.path == "README.md")
        support_action.operation = "copy"
        support_action.reason = "forged support-file install"
        forged.plan_digest = calculate_plan_digest(forged)
        with self.assertRaisesRegex(MigrationError, "canonical migration plan") as forged_error:
            apply_plan(forged)
        self.assertEqual(ExitCode.BLOCKED, forged_error.exception.exit_code)
        self.assertFalse((unresolved_target / "README.md").exists())

        target = self.fresh_target("verify-failure")
        plan = resolve_all(build_plan(str(ROOT), str(target), "alice"))
        _, receipt_path = apply_plan(plan)
        installed = target / ".trellis" / "scripts" / "get_context.py"
        installed.unlink()
        report = verify_receipt(receipt_path, run_commands=False)
        self.assertEqual("failed", report["status"])
        self.assertTrue(any(check["path"] == ".trellis/scripts/get_context.py" and check["status"] == "failed" for check in report["checks"]))

    def test_verification_resolves_windows_command_shims_and_accepts_no_current_task(self) -> None:
        target = self.fresh_target()
        completed = SimpleNamespace(returncode=1, stdout='{"current_task":null}\n', stderr="")
        command = ["python", ".trellis/scripts/task.py", "current", "--json"]
        with patch("harness_migration.verify.shutil.which", return_value="C:/Python/python.exe"), patch(
            "harness_migration.verify.subprocess.run", return_value=completed,
        ) as run:
            result = _run(command, target)
        self.assertEqual("passed", result["status"])
        self.assertEqual("C:/Python/python.exe", run.call_args.args[0][0])
        self.assertEqual(DEFAULT_COMMAND_TIMEOUT_SECONDS, run.call_args.kwargs["timeout"])

        completed.stdout = ""
        with patch("harness_migration.verify.shutil.which", return_value="C:/Python/python.exe"), patch(
            "harness_migration.verify.subprocess.run", return_value=completed,
        ):
            result = _run(command, target)
        self.assertEqual("failed", result["status"])

        with patch("harness_migration.verify.shutil.which", return_value="C:/Tools/trellis.CMD"), patch(
            "harness_migration.verify.subprocess.run", return_value=completed,
        ) as run:
            result = _run(["trellis", "update", "--dry-run"], target)
        self.assertEqual("failed", result["status"])
        self.assertEqual("C:/Tools/trellis.CMD", run.call_args.args[0][0])
        self.assertEqual(DEFAULT_COMMAND_TIMEOUT_SECONDS, run.call_args.kwargs["timeout"])

        with patch("harness_migration.verify.shutil.which", return_value="C:/Python/python.exe"), patch(
            "harness_migration.verify.subprocess.run", return_value=completed,
        ) as run:
            _run(["python", "-m", "unittest", "discover"], target)
        self.assertEqual(UNITTEST_COMMAND_TIMEOUT_SECONDS, run.call_args.kwargs["timeout"])

    def test_integrity_only_is_read_only_for_clean_failed_uninspectable_and_sidecar_results(self) -> None:
        target = self.base / "integrity-only-target"
        target.mkdir()
        installed = target / "installed.txt"
        installed.write_text("installed\n", encoding="utf-8")
        installed_digest = digest_path(installed)
        receipt_path = self.base / "integrity-only-backup" / "receipt.json"

        def write_receipt(operation: str = "copy") -> bytes:
            receipt = {
                "schemaVersion": 1,
                "status": "applied",
                "planDigest": "sha256:" + "0" * 64,
                "targetState": "fresh",
                "templateRoot": str(ROOT),
                "targetRoot": str(target.resolve()),
                "backupRoot": str(receipt_path.parent.resolve()),
                "receiptPath": str(receipt_path.resolve()),
                "journal": [{
                    "sourcePath": "installed.txt",
                    "path": "installed.txt",
                    "operation": operation,
                    "preDigest": "missing",
                    "postDigest": installed_digest,
                    "expectedPostDigest": installed_digest,
                    "backupPath": None,
                    "createdParents": [],
                    "state": "applied",
                }],
                "preservedDigests": {},
                "verificationCommands": [["must-not-run"]],
                "verification": {"stored": "full verification remains unchanged"},
                "receiptDigest": "",
                "sourceAdmission": {
                    "kind": "development-only",
                    "provenanceDigest": None,
                    "projectionDigest": None,
                },
            }
            _write_receipt(receipt_path, receipt)
            return receipt_path.read_bytes()

        original_bytes = write_receipt()
        with patch("harness_migration.verify._run") as run:
            report = verify_integrity(receipt_path)
        run.assert_not_called()
        self.assertEqual("success", report["status"])
        self.assertEqual("integrity-only", report["mode"])
        self.assertEqual([], report["commands"])
        self.assertEqual(original_bytes, receipt_path.read_bytes())

        installed.write_text("drifted\n", encoding="utf-8")
        with patch("harness_migration.verify._run") as run:
            report = verify_integrity(receipt_path)
        run.assert_not_called()
        self.assertEqual("failed", report["status"])
        self.assertEqual("integrity-only", report["mode"])
        self.assertEqual([], report["commands"])
        self.assertEqual(original_bytes, receipt_path.read_bytes())

        installed.write_text("installed\n", encoding="utf-8")
        with patch(
            "harness_migration.verify.digest_path",
            side_effect=MigrationError("cannot inspect installed path"),
        ), patch("harness_migration.verify._run") as run:
            report = verify_integrity(receipt_path)
        run.assert_not_called()
        self.assertEqual("failed", report["status"])
        self.assertEqual("integrity-only", report["mode"])
        self.assertEqual([], report["commands"])
        self.assertEqual("cannot inspect installed path", report["checks"][0]["error"])
        self.assertEqual(original_bytes, receipt_path.read_bytes())

        sidecar_bytes = write_receipt("sidecar")
        with patch("harness_migration.verify._run") as run:
            report = verify_integrity(receipt_path)
        run.assert_not_called()
        self.assertEqual("incomplete", report["status"])
        self.assertEqual("integrity-only", report["mode"])
        self.assertEqual([], report["commands"])
        self.assertEqual(["installed.txt"], report["unresolvedSidecars"])
        self.assertEqual(sidecar_bytes, receipt_path.read_bytes())

    def test_verification_checks_final_state_after_commands(self) -> None:
        target = self.base / "verification-target"
        target.mkdir()
        installed = target / "installed.txt"
        installed.write_text("installed\n", encoding="utf-8")
        installed_digest = digest_path(installed)
        receipt_path = self.base / "verification-backup" / "receipt.json"
        receipt = {
            "schemaVersion": 1,
            "status": "applied",
            "planDigest": "sha256:" + "0" * 64,
            "targetState": "fresh",
            "templateRoot": str(ROOT),
            "targetRoot": str(target.resolve()),
            "backupRoot": str(receipt_path.parent.resolve()),
            "receiptPath": str(receipt_path.resolve()),
            "journal": [{
                "sourcePath": "installed.txt", "path": "installed.txt", "operation": "copy",
                "preDigest": "missing", "postDigest": installed_digest,
                "expectedPostDigest": installed_digest, "backupPath": None,
                "createdParents": [], "state": "applied",
            }],
            "preservedDigests": {},
            "verificationCommands": [["fake-check"]],
            "verification": None,
            "receiptDigest": "",
            "sourceAdmission": {"kind": "development-only", "provenanceDigest": None, "projectionDigest": None},
        }
        _write_receipt(receipt_path, receipt)

        def mutate_during_check(command, command_target):
            self.assertEqual(target, command_target)
            installed.write_text("changed by check\n", encoding="utf-8")
            return {"command": command, "status": "passed", "exitCode": 0, "stdout": "", "stderr": ""}

        with patch("harness_migration.verify._run", side_effect=mutate_during_check):
            report = verify_receipt(receipt_path)
        self.assertEqual("failed", report["status"])
        self.assertEqual("failed", report["checks"][0]["status"])
        self.assertNotEqual(installed_digest, report["checks"][0]["actual"])

    def test_verification_refuses_commands_when_precheck_fails(self) -> None:
        target = self.base / "verification-precheck-target"
        target.mkdir()
        installed = target / "installed.txt"
        installed.write_text("installed\n", encoding="utf-8")
        installed_digest = digest_path(installed)
        receipt_path = self.base / "verification-precheck-backup" / "receipt.json"
        receipt = {
            "schemaVersion": 1, "status": "applied", "planDigest": "sha256:" + "0" * 64,
            "targetState": "fresh", "templateRoot": str(ROOT),
            "targetRoot": str(target.resolve()), "backupRoot": str(receipt_path.parent.resolve()),
            "receiptPath": str(receipt_path.resolve()),
            "journal": [{
                "sourcePath": "installed.txt", "path": "installed.txt", "operation": "copy",
                "preDigest": "missing", "postDigest": installed_digest,
                "expectedPostDigest": installed_digest, "backupPath": None,
                "createdParents": [], "state": "applied",
            }],
            "preservedDigests": {}, "verificationCommands": [["fake-check"]],
            "verification": None, "receiptDigest": "",
            "sourceAdmission": {"kind": "development-only", "provenanceDigest": None, "projectionDigest": None},
        }
        _write_receipt(receipt_path, receipt)
        installed.write_text("changed before verification\n", encoding="utf-8")

        with patch("harness_migration.verify._run") as run:
            report = verify_receipt(receipt_path)

        run.assert_not_called()
        self.assertEqual("failed", report["status"])
        self.assertEqual([], report["commands"])
        self.assertNotEqual(installed_digest, report["checks"][0]["actual"])

        output = StringIO()
        with patch("harness_migration.verify._run") as run, redirect_stdout(output):
            exit_code = migration_main(["verify", "--receipt", str(receipt_path), "--format", "json"])
        run.assert_not_called()
        self.assertEqual(ExitCode.VERIFICATION_FAILED, exit_code)
        self.assertEqual("failed", json.loads(output.getvalue())["status"])

    def test_verification_reports_uninspectable_digest_without_running_commands(self) -> None:
        target = self.base / "verification-inspection-target"
        target.mkdir()
        installed = target / "installed.txt"
        installed.write_text("installed\n", encoding="utf-8")
        installed_digest = digest_path(installed)
        receipt_path = self.base / "verification-inspection-backup" / "receipt.json"
        receipt = {
            "schemaVersion": 1, "status": "applied", "planDigest": "sha256:" + "0" * 64,
            "targetState": "fresh", "templateRoot": str(ROOT),
            "targetRoot": str(target.resolve()), "backupRoot": str(receipt_path.parent.resolve()),
            "receiptPath": str(receipt_path.resolve()),
            "journal": [{
                "sourcePath": "installed.txt", "path": "installed.txt", "operation": "copy",
                "preDigest": "missing", "postDigest": installed_digest,
                "expectedPostDigest": installed_digest, "backupPath": None,
                "createdParents": [], "state": "applied",
            }],
            "preservedDigests": {}, "verificationCommands": [["fake-check"]],
            "verification": None, "receiptDigest": "",
            "sourceAdmission": {"kind": "development-only", "provenanceDigest": None, "projectionDigest": None},
        }
        _write_receipt(receipt_path, receipt)

        with patch("harness_migration.verify.digest_path", side_effect=MigrationError("cannot inspect installed path")), patch(
            "harness_migration.verify._run",
        ) as run:
            report = verify_receipt(receipt_path)

        run.assert_not_called()
        self.assertEqual("failed", report["status"])
        self.assertIsNone(report["checks"][0]["actual"])
        self.assertEqual("cannot inspect installed path", report["checks"][0]["error"])

    def test_verification_checks_all_preserved_digests_before_commands(self) -> None:
        target = self.base / "verification-preserved-target"
        tasks = target / ".trellis" / "tasks"
        tasks.mkdir(parents=True)
        (tasks / "history.md").write_text("preserved\n", encoding="utf-8")
        expected_tasks = digest_path(tasks)
        receipt_path = self.base / "verification-preserved-backup" / "receipt.json"
        receipt = {
            "schemaVersion": 1, "status": "applied", "planDigest": "sha256:" + "0" * 64,
            "targetState": "existing_trellis", "templateRoot": str(ROOT),
            "targetRoot": str(target.resolve()), "backupRoot": str(receipt_path.parent.resolve()),
            "receiptPath": str(receipt_path.resolve()), "journal": [],
            "preservedDigests": {
                ".trellis/tasks": expected_tasks,
                ".trellis/workspace": "missing",
                ".trellis/.developer": "missing",
                ".trellis/.current-task": "missing",
                ".trellis/.runtime": "missing",
            },
            "verificationCommands": [["fake-check"]], "verification": None,
            "receiptDigest": "",
            "sourceAdmission": {"kind": "development-only", "provenanceDigest": None, "projectionDigest": None},
        }
        _write_receipt(receipt_path, receipt)
        (tasks / "history.md").write_text("changed\n", encoding="utf-8")

        with patch("harness_migration.verify._run") as run:
            report = verify_receipt(receipt_path)

        run.assert_not_called()
        self.assertEqual("failed", report["status"])
        self.assertEqual(
            "failed",
            next(check for check in report["checks"] if check["path"] == ".trellis/tasks")["status"],
        )

    def test_existing_customization_becomes_sidecar_and_history_is_preserved(self) -> None:
        target = self.fresh_target()
        fresh = resolve_all(build_plan(str(ROOT), str(target), "alice"))
        _, fresh_receipt = apply_plan(fresh)
        # Commit the installed fixture so the existing-target safety probe is clean.
        git(target, "add", ".")
        git(target, "commit", "-qm", "installed harness")
        managed = target / ".trellis" / "scripts" / "get_context.py"
        managed.write_text("# local customization\n", encoding="utf-8")
        history = target / ".trellis" / "tasks" / "local-task" / "prd.md"
        history.parent.mkdir(parents=True)
        history.write_text("keep history\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "local changes")
        history_before = digest_path(history)

        plan = build_plan(str(ROOT), str(target))
        self.assertEqual("existing_trellis", plan.target_state)
        snapshot_plan = plan_from_dict(plan.to_dict())
        snapshot_selections = {}
        for decision in snapshot_plan.decisions:
            if decision.id.startswith("official-baseline:"):
                snapshot_selections[decision.id] = "snapshot"
            else:
                snapshot_selections[decision.id] = "keep" if "keep" in decision.allowed_choices else "skip"
        resolve_plan(snapshot_plan, snapshot_selections)
        with self.assertRaises(MigrationError) as raised:
            apply_plan(snapshot_plan)
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)

        plan = resolve_all(plan, existing=True, modified_sidecar=".trellis/scripts/get_context.py")
        _, receipt_path = apply_plan(plan)
        sidecar = target / ".trellis" / "scripts" / "get_context.py.harness-new"
        self.assertTrue(sidecar.is_file())
        self.assertEqual("# local customization\n", managed.read_text(encoding="utf-8"))
        self.assertEqual(history_before, digest_path(history))
        report = verify_receipt(receipt_path, run_commands=False)
        self.assertEqual("incomplete", report["status"])

    def test_stale_sidecar_and_post_apply_edit_refuse_mutation(self) -> None:
        target = self.fresh_target()
        (target / "AGENTS.md").write_text("project instructions\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "project instructions")
        plan = build_plan(str(ROOT), str(target), "alice")
        plan = resolve_all(plan, modified_sidecar="AGENTS.md")
        (target / "AGENTS.md.harness-new").write_text("late\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "late sidecar")
        with self.assertRaises(MigrationError) as raised:
            apply_plan(plan)
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)

        target2 = self.fresh_target("post-edit")
        applied = resolve_all(build_plan(str(ROOT), str(target2), "alice"))
        _, receipt_path = apply_plan(applied)
        changed = target2 / ".trellis" / "scripts" / "get_context.py"
        changed.write_text("post apply edit\n", encoding="utf-8")
        with self.assertRaises(MigrationError) as raised:
            rollback_receipt(receipt_path)
        self.assertEqual(ExitCode.ROLLBACK_REFUSED, raised.exception.exit_code)

    def test_partial_failure_receipt_rolls_back_applied_paths(self) -> None:
        target = self.fresh_target()
        before = digest_path(target)
        plan = resolve_all(build_plan(str(ROOT), str(target), "alice"))
        old = os.environ.get("HARNESS_MIGRATE_FAIL_AFTER")
        os.environ["HARNESS_MIGRATE_FAIL_AFTER"] = "2"
        expected_receipt = target.parent / f".{target.name}.harness-backup-{plan.plan_digest[7:19]}" / "receipt.json"
        try:
            with self.assertRaises(MigrationError) as raised:
                apply_plan(plan)
            self.assertEqual(ExitCode.APPLY_FAILED, raised.exception.exit_code)
        finally:
            if old is None:
                os.environ.pop("HARNESS_MIGRATE_FAIL_AFTER", None)
            else:
                os.environ["HARNESS_MIGRATE_FAIL_AFTER"] = old
        self.assertEqual("apply_failed", load_receipt(expected_receipt)["status"])
        rollback_receipt(expected_receipt)
        self.assertEqual(before, digest_path(target))
        self.assertFalse((target / ".trellis").exists())

    def test_apply_rechecks_live_preimage_before_backup(self) -> None:
        target = self.fresh_target()
        plan = resolve_all(build_plan(str(ROOT), str(target), "alice"))
        late_path = target / ".trellis" / "scripts" / "get_context.py"
        original_revalidate = transaction_module._revalidate_plan

        def mutate_after_revalidation(candidate):
            result = original_revalidate(candidate)
            late_path.parent.mkdir(parents=True)
            late_path.write_text("late user content\n", encoding="utf-8")
            return result

        with patch("harness_migration.transaction._revalidate_plan", side_effect=mutate_after_revalidation):
            with self.assertRaises(MigrationError) as raised:
                apply_plan(plan)
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertEqual("late user content\n", late_path.read_text(encoding="utf-8"))

    def test_interrupted_prepared_receipt_can_roll_back(self) -> None:
        target = self.fresh_target()
        before = digest_path(target)
        plan = resolve_all(build_plan(str(ROOT), str(target), "alice"))
        receipt_path = target.parent / f".{target.name}.harness-backup-{plan.plan_digest[7:19]}" / "receipt.json"
        original_copy = transaction_module._copy_bytes_atomic

        def interrupt_after_replace(destination, data):
            original_copy(destination, data)
            raise KeyboardInterrupt

        with patch("harness_migration.transaction._copy_bytes_atomic", side_effect=interrupt_after_replace):
            with self.assertRaises(KeyboardInterrupt):
                apply_plan(plan)
        receipt = load_receipt(receipt_path)
        self.assertEqual("prepared", receipt["status"])
        self.assertIn("applying", {entry["state"] for entry in receipt["journal"]})
        rollback_receipt(receipt_path)
        self.assertEqual(before, digest_path(target))

    def test_partial_rollback_is_retryable(self) -> None:
        target = self.base / "rollback-target"
        target.mkdir()
        backup = self.base / "rollback-backup"
        receipt_path = backup / "receipt.json"
        journal = []
        for name in ("a.txt", "b.txt"):
            destination = target / name
            destination.write_text(f"post-{name}\n", encoding="utf-8")
            preimage = backup / "preimage" / name
            preimage.parent.mkdir(parents=True, exist_ok=True)
            preimage.write_text(f"pre-{name}\n", encoding="utf-8")
            journal.append({
                "sourcePath": name, "path": name, "operation": "copy",
                "preDigest": digest_path(preimage), "postDigest": digest_path(destination),
                "expectedPostDigest": digest_path(destination), "backupPath": f"preimage/{name}",
                "createdParents": [], "state": "applied",
            })
        receipt = {
            "schemaVersion": 1, "status": "applied", "planDigest": "sha256:" + "0" * 64,
            "targetState": "fresh", "templateRoot": str(ROOT), "targetRoot": str(target.resolve()),
            "backupRoot": str(backup.resolve()), "receiptPath": str(receipt_path.resolve()),
            "journal": journal, "preservedDigests": {}, "verificationCommands": [["python", "--version"]],
            "verification": None, "receiptDigest": "",
            "sourceAdmission": {"kind": "development-only", "provenanceDigest": None, "projectionDigest": None},
        }
        _write_receipt(receipt_path, receipt)
        with patch("harness_migration.safety.is_link_like", side_effect=lambda path: path == target):
            with self.assertRaisesRegex(MigrationError, "canonical directory"):
                rollback_receipt(receipt_path)
        original_copy = transaction_module._copy_bytes_atomic
        calls = 0

        def fail_after_restore(destination, data):
            nonlocal calls
            original_copy(destination, data)
            calls += 1
            if calls == 1:
                raise OSError("injected rollback failure")

        with patch("harness_migration.transaction._copy_bytes_atomic", side_effect=fail_after_restore):
            with self.assertRaises(MigrationError):
                rollback_receipt(receipt_path)
        self.assertEqual("rollback_failed", load_receipt(receipt_path)["status"])
        rollback_receipt(receipt_path)
        self.assertEqual("pre-a.txt\n", (target / "a.txt").read_text(encoding="utf-8"))
        self.assertEqual("pre-b.txt\n", (target / "b.txt").read_text(encoding="utf-8"))

    def test_receipt_cannot_overlap_backup_preimages(self) -> None:
        target = self.fresh_target()
        plan = resolve_all(build_plan(str(ROOT), str(target), "alice"))
        backup = self.base / "explicit-backup"
        with self.assertRaisesRegex(MigrationError, "pre-images") as raised:
            apply_plan(plan, str(backup), str(backup / "preimage" / "receipt.json"))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse(backup.exists())

    def test_receipt_tampering_is_rejected(self) -> None:
        target = self.fresh_target()
        plan = resolve_all(build_plan(str(ROOT), str(target), "alice"))
        _, receipt_path = apply_plan(plan)
        value = json.loads(receipt_path.read_text(encoding="utf-8"))
        value["targetRoot"] = str(self.base / "elsewhere")
        atomic_write_json(receipt_path, value)
        with self.assertRaises(MigrationError):
            load_receipt(receipt_path)


if __name__ == "__main__":
    unittest.main()
