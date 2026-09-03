from __future__ import annotations

import copy
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".trellis" / "scripts"
sys.path.insert(0, str(SCRIPTS))

from harness_migration.cli import _emit  # noqa: E402
from harness_migration.codec import atomic_write_json, digest_path, digest_value, without_digest  # noqa: E402
from harness_migration.inspect import inspect_template  # noqa: E402
from harness_migration.manifest import exported_files, load_manifest  # noqa: E402
from harness_migration.models import MigrationError, plan_from_dict  # noqa: E402
from harness_migration.planner import build_plan, calculate_plan_digest  # noqa: E402
from harness_migration.release import (  # noqa: E402
    PROVENANCE_PATH,
    apply_release_plan,
    build_release_plan,
    load_release_receipt,
    rollback_release_receipt,
    validate_release_plan,
    validate_release_provenance,
    verify_release_receipt,
)
import harness_migration.release as release_module  # noqa: E402
from harness_migration.transaction import apply_plan  # noqa: E402


@unittest.skipUnless((ROOT / "export-manifest.json").is_file(), "requires a Harness source template")
class HarnessReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.release = self.base / "release"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def create_release(self, *, preserve_git: bool = False):
        if preserve_git:
            git_file = self.release / ".git" / "config"
            git_file.parent.mkdir(parents=True)
            git_file.write_text("release git metadata\n", encoding="utf-8")
        plan = build_release_plan(str(ROOT), str(self.release))
        self.assertEqual(plan, build_release_plan(str(ROOT), str(self.release)))
        receipt, receipt_path = apply_release_plan(plan, str(self.base / "backup"))
        return plan, receipt, receipt_path

    def make_historical_release_with_stale_file(self) -> Path:
        manifest_path = self.release / "export-manifest.json"
        historical_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        obsolete_path = "obsolete/retired.txt"
        historical_manifest["currentSourceCopyGroups"].append(obsolete_path)
        historical_manifest["migrationPolicy"]["migrationRules"].append({
            "path": obsolete_path,
            "kind": "support_only",
            "modes": ["fresh", "existing_trellis"],
            "onExisting": "exclude",
            "onModified": "exclude",
            "sourceRequired": True,
        })
        atomic_write_json(manifest_path, historical_manifest)
        obsolete = self.release / Path(obsolete_path)
        obsolete.parent.mkdir()
        obsolete.write_text("historical release payload\n", encoding="utf-8")
        manifest = load_manifest(self.release)
        provenance = {
            "schemaVersion": 1,
            "kind": "harness-release-provenance",
            "templateVersion": manifest.template_version,
            "manifestDigest": manifest.digest,
            "payload": [
                {"path": relative, "digest": digest_path(self.release / Path(relative))}
                for relative in exported_files(self.release, manifest, "complete")
            ],
            "projectionDigest": "",
        }
        provenance["projectionDigest"] = digest_value(without_digest(provenance, "projectionDigest"))
        atomic_write_json(self.release / PROVENANCE_PATH, provenance)
        validate_release_provenance(self.release)
        return obsolete

    def test_create_is_deterministic_neutral_and_migration_ready(self) -> None:
        author_journal = ROOT / ".trellis/workspace/kino/journal-1.md"
        author_digest = digest_path(author_journal)
        unrelated_target = self.base / "unrelated-business-target"
        unrelated_target.mkdir()
        (unrelated_target / "sentinel.txt").write_text("unchanged\n", encoding="utf-8")
        unrelated_digest = digest_path(unrelated_target)
        with patch("subprocess.run", side_effect=AssertionError("release export must not invoke Git")):
            plan, receipt, receipt_path = self.create_release(preserve_git=True)
            verification = verify_release_receipt(receipt_path)
        self.assertEqual("applied", receipt["status"])
        self.assertEqual(author_digest, digest_path(author_journal))
        self.assertEqual(unrelated_digest, digest_path(unrelated_target))
        self.assertEqual("release git metadata\n", (self.release / ".git/config").read_text(encoding="utf-8"))

        journal = (self.release / ".trellis/workspace/kino/journal-1.md").read_text(encoding="utf-8")
        index = (self.release / ".trellis/workspace/kino/index.md").read_text(encoding="utf-8")
        self.assertNotIn("## Session", journal)
        self.assertNotIn("Harness dispatch", journal + index)
        self.assertIn("Total Sessions**: 0", index)
        provenance_bytes = (self.release / PROVENANCE_PATH).read_bytes()
        self.assertNotIn(str(ROOT).encode("utf-8"), provenance_bytes)
        self.assertNotIn(b"createdAt", provenance_bytes)
        provenance = validate_release_provenance(self.release)
        self.assertEqual(plan["projectionDigest"], provenance["projectionDigest"])
        self.assertEqual("success", verification["status"])
        output = io.StringIO()
        with redirect_stdout(output):
            _emit(verification, "human")
        self.assertIn("Verification: success", output.getvalue())
        self.assertTrue(inspect_template(str(self.release))["files"])

        target = self.base / "business-target"
        target.mkdir()
        migration = build_plan(str(self.release), str(target), developer="alice")
        self.assertEqual("release", migration.source_admission["kind"])
        journal_action = next(action for action in migration.actions if action.path == ".trellis/workspace/alice/journal-1.md")
        self.assertIsNotNone(journal_action.source_digest)

    def test_refresh_refuses_drift_and_unexpected_content(self) -> None:
        self.create_release()
        journal = self.release / ".trellis/workspace/kino/journal-1.md"
        journal.write_text("drift\n", encoding="utf-8")
        with self.assertRaisesRegex(MigrationError, "drifted"):
            build_release_plan(str(ROOT), str(self.release))
        journal.write_bytes((ROOT / ".trellis/release-assets/workspace/kino/journal-1.md").read_bytes())
        extra = self.release / "unexpected.txt"
        extra.write_text("unexpected\n", encoding="utf-8")
        with self.assertRaisesRegex(MigrationError, "unexpected"):
            build_release_plan(str(ROOT), str(self.release))
        extra.unlink()

        obsolete = self.make_historical_release_with_stale_file()

        refresh = build_release_plan(str(ROOT), str(self.release))
        delete = next(item for item in refresh["operations"] if item["path"] == "obsolete/retired.txt")
        self.assertEqual("delete", delete["operation"])
        _, refresh_receipt = apply_release_plan(refresh, str(self.base / "refresh-backup"))
        self.assertFalse(obsolete.exists())
        self.assertFalse(obsolete.parent.exists())
        self.assertEqual("rolled_back", rollback_release_receipt(refresh_receipt)["status"])
        self.assertEqual("historical release payload\n", obsolete.read_text(encoding="utf-8"))
        validate_release_provenance(self.release)

    def test_partial_rollback_failure_is_persisted_and_retryable(self) -> None:
        self.create_release()
        self.make_historical_release_with_stale_file()
        pre_refresh_digest = digest_path(self.release)
        refresh = build_release_plan(str(ROOT), str(self.release))
        _, receipt_path = apply_release_plan(refresh, str(self.base / "refresh-backup"))

        real_write = release_module._write_bytes
        writes = 0

        def fail_second_restore(path: Path, data: bytes) -> None:
            nonlocal writes
            writes += 1
            if writes == 2:
                raise OSError("injected release rollback failure")
            real_write(path, data)

        with patch("harness_migration.release._write_bytes", side_effect=fail_second_restore):
            with self.assertRaisesRegex(MigrationError, "can be retried"):
                rollback_release_receipt(receipt_path)
        failed = load_release_receipt(receipt_path)
        self.assertEqual("rollback_failed", failed["status"])
        self.assertIn("injected release rollback failure", failed["failure"])

        self.assertEqual("rolled_back", rollback_release_receipt(receipt_path)["status"])
        self.assertEqual(pre_refresh_digest, digest_path(self.release))
        validate_release_provenance(self.release)

    def test_plan_provenance_and_git_validation_are_closed(self) -> None:
        plan = build_release_plan(str(ROOT), str(self.release))
        invalid_plans = []
        invalid_schema = copy.deepcopy(plan)
        invalid_schema["schemaVersion"] = True
        invalid_plans.append(invalid_schema)
        invalid_path = copy.deepcopy(plan)
        invalid_path["operations"][0]["path"] = "../escape"
        invalid_path["planDigest"] = digest_value(without_digest(invalid_path, "planDigest"))
        invalid_plans.append(invalid_path)
        invalid_transition = copy.deepcopy(plan)
        invalid_transition["operations"][0]["preDigest"] = invalid_transition["operations"][0]["postDigest"]
        invalid_transition["planDigest"] = digest_value(without_digest(invalid_transition, "planDigest"))
        invalid_plans.append(invalid_transition)
        for invalid in invalid_plans:
            with self.subTest(invalid=invalid["operations"][0].get("path")):
                with self.assertRaises(MigrationError):
                    validate_release_plan(invalid)

        self.create_release()
        provenance_path = self.release / PROVENANCE_PATH
        original = json.loads(provenance_path.read_text(encoding="utf-8"))
        invalid_provenance = copy.deepcopy(original)
        invalid_provenance["payload"][0]["digest"] = False
        invalid_provenance["projectionDigest"] = digest_value(without_digest(invalid_provenance, "projectionDigest"))
        atomic_write_json(provenance_path, invalid_provenance)
        with self.assertRaisesRegex(MigrationError, "payload digest"):
            validate_release_provenance(self.release)
        atomic_write_json(provenance_path, original)

        git_path = self.release / ".git"
        git_path.mkdir()
        with patch("harness_migration.release.is_link_like", side_effect=lambda path: path == git_path):
            with self.assertRaisesRegex(MigrationError, "link-like .git"):
                build_release_plan(str(ROOT), str(self.release))

    def test_interrupted_apply_has_receipt_and_rolls_back(self) -> None:
        plan = build_release_plan(str(ROOT), str(self.release))
        backup = self.base / "backup"
        with patch.dict(os.environ, {"HARNESS_RELEASE_FAIL_AFTER": "2"}):
            with self.assertRaisesRegex(MigrationError, "recover with receipt"):
                apply_release_plan(plan, str(backup))
        receipt_path = backup / "receipt.json"
        self.assertEqual("apply_failed", load_release_receipt(receipt_path)["status"])
        self.assertEqual("rolled_back", rollback_release_receipt(receipt_path)["status"])
        self.assertFalse(self.release.exists())

    def test_rollback_restores_refresh_preimages_and_receipt_tamper_is_rejected(self) -> None:
        _, _, first_receipt = self.create_release()
        self.assertEqual("success", verify_release_receipt(first_receipt)["status"])
        second_plan = build_release_plan(str(ROOT), str(self.release))
        self.assertEqual([], second_plan["operations"])

        original = json.loads(first_receipt.read_text(encoding="utf-8"))
        receipt = copy.deepcopy(original)
        receipt["planDigest"] = "sha256:" + "0" * 64
        atomic_write_json(first_receipt, receipt)
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            load_release_receipt(first_receipt)

        rebound_values = []
        rebound = copy.deepcopy(original)
        rebound["releaseRootExisted"] = "false"
        rebound_values.append(rebound)
        rebound = copy.deepcopy(original)
        rebound["journal"][0]["createdParents"] = [rebound["journal"][0]["path"]]
        rebound_values.append(rebound)
        rebound = copy.deepcopy(original)
        rebound["journal"][0]["operation"] = "delete"
        rebound_values.append(rebound)
        rebound = copy.deepcopy(original)
        rebound["journal"][0]["state"] = []
        rebound_values.append(rebound)
        rebound = copy.deepcopy(original)
        rebound["verification"]["checks"][0]["actual"] = False
        rebound_values.append(rebound)
        for rebound in rebound_values:
            rebound["receiptDigest"] = digest_value(without_digest(rebound, "receiptDigest"))
            atomic_write_json(first_receipt, rebound)
            with self.assertRaises(MigrationError):
                load_release_receipt(first_receipt)
        atomic_write_json(first_receipt, original)
        self.assertEqual("rolled_back", rollback_release_receipt(first_receipt)["status"])

    def test_root_relations_and_source_admission_are_closed(self) -> None:
        with self.assertRaisesRegex(MigrationError, "disjoint"):
            build_release_plan(str(ROOT), str(ROOT / "nested-release"))
        target = self.base / "target"
        target.mkdir()
        unproven = build_plan(str(ROOT), str(target), developer="alice")
        self.assertEqual("unproven", unproven.source_admission["kind"])
        development = build_plan(str(ROOT), str(target), developer="alice", development_template=True)
        self.assertEqual("development-only", development.source_admission["kind"])
        self.assertNotEqual(unproven.plan_digest, development.plan_digest)
        rebound = development.to_dict()
        rebound["sourceAdmission"]["kind"] = "unproven"
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            apply_plan(plan_from_dict(rebound))
        development.source_admission = {"kind": [], "provenanceDigest": None, "projectionDigest": None}
        development.plan_digest = calculate_plan_digest(development)
        with self.assertRaisesRegex(MigrationError, "digest or schema"):
            apply_plan(development)
        with self.assertRaisesRegex(MigrationError, "requires release provenance"):
            apply_plan(unproven)


if __name__ == "__main__":
    unittest.main()
