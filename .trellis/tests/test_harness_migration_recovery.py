from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".trellis" / "scripts"))

from harness_migration.codec import atomic_write_json, digest_path  # noqa: E402
from harness_migration.cli import main as migration_main  # noqa: E402
from harness_migration.manifest import exported_files, load_manifest, matching_rule  # noqa: E402
from harness_migration.models import ExitCode, MigrationError, RuleKind  # noqa: E402
from harness_migration.planner import build_plan  # noqa: E402
import harness_migration.recovery as recovery_module  # noqa: E402
import harness_migration.transaction as transaction_module  # noqa: E402
from harness_migration.recovery import (  # noqa: E402
    BASELINE_QUARANTINE_REASON,
    RECOVERY_PLAN_KEYS,
    RECOVERY_PRESERVED_ROOTS,
    apply_recovery_plan,
    build_recovery_plan,
    calculate_recovery_plan_digest,
    recovery_plan_from_dict,
    resolve_recovery_plan,
)
from harness_migration.transaction import load_receipt, rollback_receipt  # noqa: E402
from harness_migration.verify import verify_receipt  # noqa: E402


SELECTED_CONFIG_EXPECTED = "4224eb7df6802a623cb1bee522aed0a23ba6be862b90f1b597a313fc16864b06"
SELECTED_CONFIG_ACTUAL = "2d3dd0071f4e37228af93892e7514c8b3ad272a63f9b4770761a76508445fc8b"
SELECTED_CONFIG_BYTES = '''# Project-scoped Codex defaults for Trellis workflows.
# Codex merges this layer after the user-level config when the project
# is marked as a trusted project. To trust this project, add it under
# `[projects]` in ~/.codex/config.toml, e.g.:
#
#   [projects."/abs/path/to/this/repo"]
#   trust_level = "trusted"

# Keep AGENTS.md as the primary project instruction file.
project_doc_fallback_filenames = ["AGENTS.md"]

# Codex hooks (`hooks.json` in this directory) only fire when the user
# has enabled them in their USER-level config: `[features].hooks = true`
# in ~/.codex/config.toml (Codex 0.129+; legacy name: `codex_hooks = true`,
# still works but emits a deprecation warning on 0.129+). Project-level
# config.toml cannot set feature flags; they must be user-level.
# Codex 0.129+ additionally gates each installed hook behind a one-time
# `/hooks` TUI review; until the user approves it, the hook stays inactive.

# NOTE: Trellis intentionally does NOT write a [features.multi_agent_v2]
# block here. Codex CLI changed `features` deserialization between 0.130
# and 0.131: the structured table form (with max_concurrent_threads_per_session
# / *_wait_timeout_ms) is only accepted by 0.131+. On 0.130 and earlier —
# including the codex CLI bundled inside the Codex desktop app — it fails
# with `data did not match any variant of untagged enum FeatureToml`, which
# aborts the entire config load and blocks Codex from starting. Codex's own
# default for multi_agent_v2 is used instead; tune it in your user-level
# config if needed.

# Allow project sessions to run without filesystem sandbox restrictions
# and without approval prompts.
approval_policy = "never"
sandbox_mode = "danger-full-access"
'''.encode("utf-8")


def git(path: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(path), *arguments], capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    )


def initialize_git(path: Path) -> None:
    git(path, "init", "-q")
    git(path, "config", "user.email", "recovery-tests@example.invalid")
    git(path, "config", "user.name", "Recovery Tests")
    git(path, "add", ".")
    git(path, "commit", "-qm", "partial fixture")


@unittest.skipUnless((ROOT / "export-manifest.json").is_file(), "requires a Harness source template")
class HarnessMigrationRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def partial_target(self, name: str = "partial") -> tuple[Path, Path]:
        target = self.base / name
        target.mkdir()
        (target / "app.txt").write_text("application\n", encoding="utf-8")
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
        baseline = target / ".trellis" / ".backup-2026-08-03T03-14-01"
        manifest = load_manifest(ROOT)
        for relative in exported_files(ROOT, manifest, "complete"):
            rule = matching_rule(manifest.rules, relative)
            if rule.kind in {
                RuleKind.PRESERVE, RuleKind.RUNTIME_EXCLUDED,
                RuleKind.FRESH_ONLY_SKELETON, RuleKind.SUPPORT_ONLY,
            } or relative.startswith(".trellis/spec/"):
                continue
            source = ROOT / relative
            if not source.is_file():
                continue
            destination = baseline / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        (baseline / ".trellis" / ".version").write_text(manifest.template_version + "\n", encoding="utf-8")
        (baseline / ".trellis" / ".developer").parent.mkdir(parents=True, exist_ok=True)
        (baseline / ".trellis" / ".developer").write_text("name=kino\n", encoding="utf-8")
        hashes = {}
        for relative in (".trellis/config.yaml", ".trellis/workflow.md"):
            hashes[relative] = digest_path(baseline / relative)[7:]
        atomic_write_json(
            baseline / ".trellis" / ".template-hashes.json",
            {"__version": 2, "hashes": hashes},
        )
        initialize_git(target)
        return target, baseline

    @staticmethod
    def resolve_all(plan):
        return resolve_recovery_plan(plan, {
            decision.id: "replace" for decision in plan.decisions
        })

    def test_recovery_plan_is_stable_closed_and_preserves_project_state(self) -> None:
        target, baseline = self.partial_target()
        before = digest_path(target)
        first = build_recovery_plan(str(ROOT), str(target), str(baseline))
        second = build_recovery_plan(str(ROOT), str(target), str(baseline))
        self.assertEqual(first.to_dict(), second.to_dict())
        self.assertEqual(before, digest_path(target))
        self.assertEqual("recovery", first.transaction_type)
        self.assertEqual("unsupported_partial", first.target_state)
        self.assertEqual(set(first.to_dict()), RECOVERY_PLAN_KEYS)
        action_paths = {action.path for action in first.actions}
        self.assertTrue({".trellis/config.yaml", ".trellis/workflow.md"} <= action_paths)
        self.assertFalse(any(
            path == root or path.startswith(root + "/")
            for path in action_paths for root in RECOVERY_PRESERVED_ROOTS
        ))
        expected_paths = set()
        manifest = load_manifest(ROOT)
        for relative in exported_files(ROOT, manifest, "complete"):
            rule = matching_rule(manifest.rules, relative)
            preserved = any(
                relative == root or relative.startswith(root + "/")
                for root in RECOVERY_PRESERVED_ROOTS
            )
            if (
                rule.kind not in {
                    RuleKind.PRESERVE, RuleKind.RUNTIME_EXCLUDED,
                    RuleKind.FRESH_ONLY_SKELETON, RuleKind.SUPPORT_ONLY,
                }
                and not preserved
                and (baseline / relative).is_file()
            ):
                expected_paths.add(relative)
        self.assertEqual(expected_paths, action_paths)
        malformed = first.to_dict()
        malformed["unexpected"] = True
        with self.assertRaisesRegex(MigrationError, "unknown or missing"):
            recovery_plan_from_dict(malformed)
        malformed_action = first.to_dict()
        malformed_action["actions"][0]["unexpected"] = True
        with self.assertRaisesRegex(MigrationError, "action has unknown or missing"):
            recovery_plan_from_dict(malformed_action)
        first.baseline_digest = "sha256:" + "0" * 64
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            self.assert_recovery_digest(first)

    @staticmethod
    def assert_recovery_digest(plan) -> None:
        from harness_migration.recovery import validate_recovery_plan_digest
        validate_recovery_plan_digest(plan)

    def test_recovery_rejects_wrong_state_version_hash_and_implicit_baseline(self) -> None:
        fresh = self.base / "fresh"
        fresh.mkdir()
        (fresh / "project.txt").write_text("project\n", encoding="utf-8")
        initialize_git(fresh)
        with self.assertRaisesRegex(MigrationError, "unsupported_partial"):
            build_recovery_plan(str(ROOT), str(fresh), str(fresh))

        target, baseline = self.partial_target("invalid")
        (baseline / ".trellis" / ".version").write_text("0.6.0\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "wrong version")
        with self.assertRaisesRegex(MigrationError, "does not match template"):
            build_recovery_plan(str(ROOT), str(target), str(baseline))

        (baseline / ".trellis" / ".version").write_text(load_manifest(ROOT).template_version + "\n", encoding="utf-8")
        (baseline / ".trellis" / "workflow.md").write_text("tampered\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "bad hash")
        with self.assertRaisesRegex(MigrationError, "hash mismatch"):
            build_recovery_plan(str(ROOT), str(target), str(baseline))

        outside = self.base / ".backup-outside"
        shutil.copytree(baseline, outside)
        with self.assertRaisesRegex(MigrationError, "direct .trellis/.backup"):
            build_recovery_plan(str(ROOT), str(target), str(outside))

        target, baseline = self.partial_target("malformed-hashes")
        (baseline / ".trellis" / ".template-hashes.json").write_text("{bad", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "malformed hashes")
        with self.assertRaisesRegex(MigrationError, "cannot validate recovery baseline template hashes") as raised:
            build_recovery_plan(str(ROOT), str(target), str(baseline))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)

    def test_recovery_uses_semantic_developer_identity_and_rejects_link_like_roots(self) -> None:
        target, baseline = self.partial_target()
        developer = target / ".trellis" / ".developer"
        developer.write_text("name=kino\ninitialized_at=later\nworkflow=custom\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "compatible developer metadata")
        self.assertEqual("unsupported_partial", build_recovery_plan(str(ROOT), str(target), str(baseline)).target_state)

        developer.write_text("name=someone-else\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "incompatible developer")
        with self.assertRaisesRegex(MigrationError, "developer identity is incompatible") as raised:
            build_recovery_plan(str(ROOT), str(target), str(baseline))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)

        developer.write_text("name=kino\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "restore developer")
        canonical_target = target.resolve()
        with patch(
            "harness_migration.safety.is_link_like",
            side_effect=lambda path: path == canonical_target,
        ):
            with self.assertRaisesRegex(MigrationError, "root must not be link-like or rebound") as raised:
                build_recovery_plan(str(ROOT), str(target), str(baseline))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)

        target, baseline = self.partial_target("malformed-developer")
        (baseline / ".trellis" / ".developer").write_bytes(b"\xff\xfe")
        with self.assertRaisesRegex(MigrationError, "cannot read recovery baseline developer identity") as raised:
            build_recovery_plan(str(ROOT), str(target), str(baseline))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)

    def test_merge_required_digest_mismatch_is_audited_and_never_recovered(self) -> None:
        target, baseline = self.partial_target("quarantined-config")
        config_relative = ".codex/config.toml"
        baseline_config = baseline / config_relative
        baseline_config.write_bytes(SELECTED_CONFIG_BYTES)
        hashes_path = baseline / ".trellis" / ".template-hashes.json"
        hashes_document = json.loads(hashes_path.read_text(encoding="utf-8"))
        hashes_document["hashes"][config_relative] = SELECTED_CONFIG_EXPECTED
        atomic_write_json(hashes_path, hashes_document)
        git(target, "add", ".")
        git(target, "commit", "-qm", "selected config mismatch")

        self.assertEqual("sha256:" + SELECTED_CONFIG_ACTUAL, digest_path(baseline_config))
        self.assertFalse((target / config_relative).exists())
        plan = build_recovery_plan(str(ROOT), str(target), str(baseline))
        self.assertEqual({
            "hashStatus": "verified_with_quarantined_merge_required",
            "quarantinedPaths": [{
                "path": config_relative,
                "expectedDigest": "sha256:" + SELECTED_CONFIG_EXPECTED,
                "actualDigest": "sha256:" + SELECTED_CONFIG_ACTUAL,
                "ruleKind": "merge_required",
                "reason": BASELINE_QUARANTINE_REASON,
            }],
        }, plan.baseline_audit.to_dict())
        self.assertEqual([{
            "path": config_relative,
            "preDigest": "missing",
            "postDigest": "missing",
        }], [item.to_dict() for item in plan.quarantined_target_states])
        self.assertNotIn(config_relative, {action.path for action in plan.actions})
        self.assertFalse(any(config_relative in decision.paths for decision in plan.decisions))

        resolved = self.resolve_all(plan)
        receipt, receipt_path = apply_recovery_plan(resolved)
        self.assertFalse((target / config_relative).exists())
        self.assertEqual(resolved.baseline_audit.to_dict(), receipt["baselineAudit"])
        self.assertEqual(
            [item.to_dict() for item in resolved.quarantined_target_states],
            receipt["quarantinedTargetStates"],
        )
        self.assertNotIn(config_relative, {entry["sourcePath"] for entry in receipt["journal"]})
        self.assertNotIn(config_relative, {entry["path"] for entry in receipt["journal"]})
        report = verify_receipt(receipt_path, run_commands=False)
        quarantine_checks = [
            check for check in report["checks"]
            if check["kind"] == "quarantined_target_unchanged"
        ]
        self.assertEqual("success", report["status"])
        self.assertEqual(1, len(quarantine_checks))
        self.assertEqual("passed", quarantine_checks[0]["status"])
        self.assertEqual("missing", quarantine_checks[0]["actual"])

        normal_plan = build_plan(str(ROOT), str(target), profile="complete")
        self.assertEqual("existing_trellis", normal_plan.target_state)
        self.assertIn(config_relative, {action.path for action in normal_plan.actions})
        installed_before_refusal = digest_path(target / ".trellis" / "workflow.md")
        (target / config_relative).parent.mkdir(parents=True, exist_ok=True)
        (target / config_relative).write_text("changed after recovery\n", encoding="utf-8")
        failed_report = verify_receipt(receipt_path, run_commands=False)
        self.assertEqual("failed", failed_report["status"])
        with self.assertRaisesRegex(MigrationError, "quarantined target changed"):
            rollback_receipt(receipt_path)
        self.assertEqual(installed_before_refusal, digest_path(target / ".trellis" / "workflow.md"))
        (target / config_relative).unlink()
        self.assertEqual("success", verify_receipt(receipt_path, run_commands=False)["status"])
        rollback_receipt(receipt_path)
        self.assertFalse((target / config_relative).exists())

    def test_quarantine_schema_and_canonical_target_binding_are_closed(self) -> None:
        target, baseline = self.partial_target("quarantine-schema")
        relative = ".codex/config.toml"
        (baseline / relative).write_bytes(b"untrusted historical config\n")
        hashes_path = baseline / ".trellis" / ".template-hashes.json"
        hashes_document = json.loads(hashes_path.read_text(encoding="utf-8"))
        hashes_document["hashes"][relative] = "0" * 64
        atomic_write_json(hashes_path, hashes_document)
        git(target, "add", ".")
        git(target, "commit", "-qm", "quarantine fixture")
        plan = self.resolve_all(build_recovery_plan(str(ROOT), str(target), str(baseline)))

        malformed = plan.to_dict()
        malformed["baselineAudit"]["unexpected"] = True
        with self.assertRaisesRegex(MigrationError, "unknown or missing"):
            recovery_plan_from_dict(malformed)
        malformed = plan.to_dict()
        malformed["baselineAudit"]["quarantinedPaths"].append(
            dict(malformed["baselineAudit"]["quarantinedPaths"][0])
        )
        with self.assertRaisesRegex(MigrationError, "duplicate quarantined"):
            recovery_plan_from_dict(malformed)
        malformed = plan.to_dict()
        malformed["baselineAudit"]["quarantinedPaths"][0]["reason"] = "skip"
        with self.assertRaisesRegex(MigrationError, "reason is invalid"):
            recovery_plan_from_dict(malformed)

        forged = plan.to_dict()
        forged["baselineAudit"]["quarantinedPaths"][0]["expectedDigest"] = "sha256:" + "1" * 64
        forged_plan = recovery_plan_from_dict(forged)
        forged_plan.plan_digest = calculate_recovery_plan_digest(forged_plan)
        backup = self.base / "forged-audit-backup"
        with self.assertRaisesRegex(MigrationError, "canonical recovery plan"):
            apply_recovery_plan(forged_plan, str(backup))
        self.assertFalse(backup.exists())

        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        (target / relative).write_text("late live config\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "change excluded target")
        backup = self.base / "stale-quarantine-target-backup"
        with self.assertRaisesRegex(MigrationError, "canonical recovery plan|quarantined target pre-image"):
            apply_recovery_plan(plan, str(backup))
        self.assertFalse(backup.exists())

    def test_recovery_rejects_dirty_session_active_and_link_like_baselines(self) -> None:
        target, baseline = self.partial_target()
        dirty = target / "dirty.txt"
        dirty.write_text("dirty\n", encoding="utf-8")
        with self.assertRaisesRegex(MigrationError, "worktree is dirty"):
            build_recovery_plan(str(ROOT), str(target), str(baseline))
        dirty.unlink()

        active = target / ".trellis" / ".runtime" / "sessions" / "active.json"
        active.write_text('{"active":true}\n', encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "active session")
        with self.assertRaisesRegex(MigrationError, "active runtime session"):
            build_recovery_plan(str(ROOT), str(target), str(baseline))
        active.write_text("{}\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "stop session")

        linked = baseline / ".codex"
        with patch("harness_migration.recovery.is_link_like", side_effect=lambda path: path == linked):
            with self.assertRaisesRegex(MigrationError, "link-like entry"):
                build_recovery_plan(str(ROOT), str(target), str(baseline))

    def test_recovery_apply_verify_rollback_and_normal_replan(self) -> None:
        target, baseline = self.partial_target()
        preserved = {relative: digest_path(target / relative) for relative in RECOVERY_PRESERVED_ROOTS}
        app_before = digest_path(target / "app.txt")
        before = digest_path(target)
        plan = self.resolve_all(build_recovery_plan(str(ROOT), str(target), str(baseline)))
        receipt, receipt_path = apply_recovery_plan(plan)
        self.assertEqual("applied", receipt["status"])
        self.assertEqual("unsupported_partial", receipt["targetState"])
        self.assertNotIn("sourceAdmission", receipt)
        self.assertEqual(str(baseline), receipt["baselineRoot"])
        self.assertEqual("existing_trellis", build_plan(str(ROOT), str(target)).target_state)
        for relative, expected in preserved.items():
            self.assertEqual(expected, digest_path(target / relative), relative)
        self.assertEqual(app_before, digest_path(target / "app.txt"))
        report = verify_receipt(receipt_path, run_commands=False)
        self.assertEqual("success", report["status"])
        rollback_receipt(receipt_path)
        self.assertEqual(before, digest_path(target))

    def test_recovery_resolution_choices_and_sidecar_verification(self) -> None:
        target, baseline = self.partial_target()
        instructions = target / "AGENTS.md"
        instructions.write_text("project instructions\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "project instructions")
        before = digest_path(target)
        plan = build_recovery_plan(str(ROOT), str(target), str(baseline))
        decision = next(item for item in plan.decisions if item.paths == ["AGENTS.md"])
        self.assertEqual(["sidecar", "keep", "replace"], decision.allowed_choices)

        expected_operations = {"sidecar": "sidecar", "keep": "preserve", "replace": "copy"}
        for choice, expected_operation in expected_operations.items():
            with self.subTest(choice=choice):
                candidate = recovery_plan_from_dict(plan.to_dict())
                resolve_recovery_plan(candidate, {decision.id: choice})
                action = next(item for item in candidate.actions if item.path == "AGENTS.md")
                self.assertEqual(expected_operation, action.operation)
        with self.assertRaisesRegex(MigrationError, "unknown recovery decision IDs"):
            resolve_recovery_plan(recovery_plan_from_dict(plan.to_dict()), {"recover:unknown:00000000": "keep"})
        with self.assertRaisesRegex(MigrationError, "invalid recovery choice"):
            resolve_recovery_plan(recovery_plan_from_dict(plan.to_dict()), {decision.id: "install"})

        resolved = recovery_plan_from_dict(plan.to_dict())
        resolve_recovery_plan(resolved, {decision.id: "sidecar"})
        receipt, receipt_path = apply_recovery_plan(resolved)
        self.assertEqual("applied", receipt["status"])
        self.assertEqual("project instructions\n", instructions.read_text(encoding="utf-8"))
        self.assertEqual(digest_path(baseline / "AGENTS.md"), digest_path(target / "AGENTS.md.harness-new"))
        self.assertEqual("incomplete", verify_receipt(receipt_path, run_commands=False)["status"])
        rollback_receipt(receipt_path)
        self.assertEqual(before, digest_path(target))

    def test_recovery_cli_round_trips_plan_and_requires_apply_approval(self) -> None:
        target, baseline = self.partial_target()
        (target / "AGENTS.md").write_text("project instructions\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "recovery decision fixture")
        plan_path = self.base / "recovery-plan.json"
        resolved_path = self.base / "resolved-recovery-plan.json"
        output = StringIO()
        with redirect_stdout(output):
            exit_code = migration_main([
                "recover-plan", "--template", str(ROOT), "--target", str(target),
                "--baseline", str(baseline), "--format", "json", "--output", str(plan_path),
            ])
        self.assertEqual(ExitCode.OK, exit_code)
        plan = recovery_plan_from_dict(json.loads(plan_path.read_text(encoding="utf-8")))
        self.assertTrue(plan.decisions)
        decisions = [
            value for decision in plan.decisions
            for value in ("--decision", f"{decision.id}=replace")
        ]
        with redirect_stdout(StringIO()):
            exit_code = migration_main([
                "recover-resolve", "--plan", str(plan_path), *decisions,
                "--output", str(resolved_path),
            ])
        self.assertEqual(ExitCode.OK, exit_code)
        backup = self.base / "unauthorized-backup"
        with redirect_stdout(StringIO()):
            exit_code = migration_main([
                "recover-apply", "--plan", str(resolved_path), "--backup", str(backup),
            ])
        self.assertEqual(ExitCode.BLOCKED, exit_code)
        self.assertFalse(backup.exists())

    def test_recovery_canonical_replay_refuses_stale_target_and_baseline_before_backup(self) -> None:
        target, baseline = self.partial_target()
        plan = self.resolve_all(build_recovery_plan(str(ROOT), str(target), str(baseline)))
        target_change = target / "AGENTS.md"
        target_change.write_text("late target change\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "late target")
        backup = self.base / "stale-target-backup"
        with self.assertRaisesRegex(MigrationError, "canonical recovery plan") as raised:
            apply_recovery_plan(plan, str(backup))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse(backup.exists())

        target, baseline = self.partial_target("decision-drift")
        config = target / ".trellis" / "config.yaml"
        config.write_text("project: local\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "local config before recovery plan")
        plan = self.resolve_all(build_recovery_plan(str(ROOT), str(target), str(baseline)))
        config.unlink()
        git(target, "add", "-A")
        git(target, "commit", "-qm", "removed config after recovery plan")
        backup = self.base / "decision-drift-backup"
        with self.assertRaisesRegex(MigrationError, "canonical recovery plan") as raised:
            apply_recovery_plan(plan, str(backup))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse(backup.exists())

        target, baseline = self.partial_target("apply-gates")
        plan = self.resolve_all(build_recovery_plan(str(ROOT), str(target), str(baseline)))
        dirty = target / "dirty-after-plan.txt"
        dirty.write_text("dirty\n", encoding="utf-8")
        backup = self.base / "dirty-apply-backup"
        with self.assertRaisesRegex(MigrationError, "worktree is dirty") as raised:
            apply_recovery_plan(plan, str(backup))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse(backup.exists())
        dirty.unlink()

        active = target / ".trellis" / ".runtime" / "sessions" / "active.json"
        active.write_text('{"active":true}\n', encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "active session after plan")
        backup = self.base / "active-session-apply-backup"
        with self.assertRaisesRegex(MigrationError, "active runtime session") as raised:
            apply_recovery_plan(plan, str(backup))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse(backup.exists())

        target, baseline = self.partial_target("stale-baseline")
        plan = self.resolve_all(build_recovery_plan(str(ROOT), str(target), str(baseline)))
        (baseline / ".trellis" / "workflow.md").write_text("late baseline change\n", encoding="utf-8")
        git(target, "add", ".")
        git(target, "commit", "-qm", "late baseline")
        backup = self.base / "stale-baseline-backup"
        with self.assertRaises(MigrationError) as raised:
            apply_recovery_plan(plan, str(backup))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse(backup.exists())

    def test_recovery_stages_sources_before_backup_or_target_write(self) -> None:
        target, baseline = self.partial_target()
        plan = self.resolve_all(build_recovery_plan(str(ROOT), str(target), str(baseline)))
        destination = target / ".trellis" / "workflow.md"
        backup = self.base / "late-source-backup"
        original_revalidate = recovery_module.revalidate_recovery_plan

        def mutate_after_revalidation(candidate):
            result = original_revalidate(candidate)
            (baseline / ".trellis" / "workflow.md").write_text(
                "changed after canonical replay\n", encoding="utf-8",
            )
            git(target, "add", ".")
            git(target, "commit", "-qm", "late baseline source mutation")
            return result

        with patch(
            "harness_migration.recovery.revalidate_recovery_plan",
            side_effect=mutate_after_revalidation,
        ):
            with self.assertRaisesRegex(MigrationError, "source changed after validation") as raised:
                apply_recovery_plan(plan, str(backup))
        self.assertEqual(ExitCode.BLOCKED, raised.exception.exit_code)
        self.assertFalse(backup.exists())
        self.assertFalse(destination.exists())

    def test_recovery_failure_receipt_is_recoverable_and_retryable_by_rollback(self) -> None:
        target, baseline = self.partial_target()
        before = digest_path(target)
        plan = self.resolve_all(build_recovery_plan(str(ROOT), str(target), str(baseline)))
        backup = self.base / "failure-backup"
        previous = os.environ.get("HARNESS_MIGRATE_FAIL_AFTER")
        os.environ["HARNESS_MIGRATE_FAIL_AFTER"] = "1"
        try:
            with self.assertRaises(MigrationError) as raised:
                apply_recovery_plan(plan, str(backup))
            self.assertEqual(ExitCode.APPLY_FAILED, raised.exception.exit_code)
        finally:
            if previous is None:
                os.environ.pop("HARNESS_MIGRATE_FAIL_AFTER", None)
            else:
                os.environ["HARNESS_MIGRATE_FAIL_AFTER"] = previous
        receipt_path = backup / "receipt.json"
        failed_receipt = load_receipt(receipt_path)
        self.assertEqual("apply_failed", failed_receipt["status"])
        self.assertIn("applied", {entry["state"] for entry in failed_receipt["journal"]})
        self.assertIn("prepared", {entry["state"] for entry in failed_receipt["journal"]})
        rollback_receipt(receipt_path)
        self.assertEqual(before, digest_path(target))

    def test_recovery_interrupted_prepared_receipt_can_roll_back(self) -> None:
        target, baseline = self.partial_target()
        before = digest_path(target)
        plan = self.resolve_all(build_recovery_plan(str(ROOT), str(target), str(baseline)))
        backup = self.base / "interrupted-backup"
        receipt_path = backup / "receipt.json"
        original_copy = transaction_module._copy_bytes_atomic

        def interrupt_after_replace(destination, data):
            original_copy(destination, data)
            raise KeyboardInterrupt

        with patch(
            "harness_migration.transaction._copy_bytes_atomic",
            side_effect=interrupt_after_replace,
        ):
            with self.assertRaises(KeyboardInterrupt):
                apply_recovery_plan(plan, str(backup))
        receipt = load_receipt(receipt_path)
        self.assertEqual("prepared", receipt["status"])
        self.assertIn("applying", {entry["state"] for entry in receipt["journal"]})
        self.assertEqual(str(baseline), receipt["baselineRoot"])
        rollback_receipt(receipt_path)
        self.assertEqual(before, digest_path(target))


if __name__ == "__main__":
    unittest.main()
