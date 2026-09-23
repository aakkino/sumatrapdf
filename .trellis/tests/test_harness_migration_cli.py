from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / ".trellis" / "scripts" / "harness_migrate.py"
SOURCE_MANIFEST = ROOT / "export-manifest.json"
sys.path.insert(0, str(ROOT / ".trellis" / "scripts"))

from harness_migration.cli import _parser, main as migration_main  # noqa: E402


@unittest.skipUnless(SOURCE_MANIFEST.is_file(), "requires a Harness source template")
class HarnessMigrationCliTests(unittest.TestCase):
    def test_agent_workflow_cli_admission_failure_is_structured_and_writes_no_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.mkdir()
            subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
            output = Path(temporary) / "blocked-plan.json"
            result = subprocess.run(
                [
                    "python", str(CLI), "plan", "--template", str(ROOT),
                    "--target", str(target), "--profile", "agent-workflow",
                    "--format", "json", "--output", str(output),
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False,
            )
            self.assertEqual(3, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual("codex-dispatch-workflow-v1", value["details"]["capability"])
            self.assertEqual("dispatch-only", value["details"]["remediation"]["profile"])
            self.assertTrue(value["details"]["failures"])
            self.assertFalse(output.exists())

    def test_route_only_cli_selects_only_requested_route_paths_and_rejects_conflicts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            (target / ".trellis").mkdir(parents=True)
            (target / ".trellis" / "config.yaml").write_text("project: test\n", encoding="utf-8")
            (target / ".trellis" / "workflow.md").write_text("workflow\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.email", "migration-tests@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.name", "Migration Tests"], check=True)
            subprocess.run(["git", "-C", str(target), "add", "."], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-qm", "fixture"], check=True)

            result = subprocess.run(
                [
                    "python", str(CLI), "plan", "--template", str(ROOT),
                    "--target", str(target), "--route-only",
                    "--route", "subagent-default=bounded_worker",
                    "--route", "main=planning", "--format", "json",
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(5, value["schemaVersion"])
            self.assertEqual("route-only", value["selectionMode"])
            self.assertIsNone(value["profile"])
            self.assertEqual([".codex/config.toml"], [action["path"] for action in value["actions"]])

            raw = subprocess.run(
                [
                    "python", str(CLI), "plan", "--template", str(ROOT),
                    "--target", str(target), "--route-only",
                    "--route-pair", "role:research=gpt-5.6-terra,xhigh", "--format", "json",
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False,
            )
            self.assertEqual(0, raw.returncode, raw.stderr)
            raw_value = json.loads(raw.stdout)
            self.assertEqual(7, raw_value["schemaVersion"])
            self.assertEqual(
                [{"scope": "role:research", "model": "gpt-5.6-terra", "effort": "xhigh"}],
                raw_value["routeOverrides"],
            )

            invalid_cases = (
                ["--route-only"],
                ["--route-only", "--route", "main=planning", "--profile", "complete"],
                ["--route-only", "--route", "main=planning", "--developer", "alice"],
                ["--route-only", "--route", "main=planning", "--adopt-partial"],
                ["--route-pair", "main=gpt-5.6-sol,medium"],
                ["--route-only", "--route-pair", "main=bad value,medium"],
                ["--route-only", "--route", "main=planning", "--route-pair", "main=gpt-5.6-sol,high"],
            )
            for index, arguments in enumerate(invalid_cases):
                output = Path(temporary) / f"invalid-route-only-{index}.json"
                invalid = subprocess.run(
                    [
                        "python", str(CLI), "plan", "--template", str(ROOT),
                        "--target", str(target), *arguments, "--output", str(output),
                    ],
                    cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", check=False,
                )
                self.assertEqual(2, invalid.returncode, invalid.stderr)
                self.assertFalse(output.exists())

    def test_plan_route_flags_normalize_in_json_and_invalid_input_writes_no_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.mkdir()
            subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
            result = subprocess.run(
                [
                    "python", str(CLI), "plan", "--template", str(ROOT),
                    "--target", str(target), "--developer", "alice",
                    "--profile", "dispatch-only",
                    "--route", "role:research=exploration",
                    "--route", "main=planning", "--format", "json",
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(3, value["schemaVersion"])
            self.assertEqual(
                ["main", "role:research"],
                [item["scope"] for item in value["routeOverrides"]],
            )

            output = Path(temporary) / "invalid-plan.json"
            invalid = subprocess.run(
                [
                    "python", str(CLI), "plan", "--template", str(ROOT),
                    "--target", str(target), "--developer", "alice",
                    "--route", "role:check=checking", "--output", str(output),
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                errors="replace", check=False,
            )
            self.assertEqual(2, invalid.returncode)
            self.assertFalse(output.exists())

    def test_dispatch_route_only_cli_composes_lanes_and_rejects_cross_family_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            (target / ".trellis").mkdir(parents=True)
            (target / ".trellis" / "config.yaml").write_text("project: test\n", encoding="utf-8")
            (target / ".trellis" / "workflow.md").write_text("workflow\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(target), "init", "-q"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.email", "migration-tests@example.invalid"], check=True)
            subprocess.run(["git", "-C", str(target), "config", "user.name", "Migration Tests"], check=True)
            subprocess.run(["git", "-C", str(target), "add", "."], check=True)
            subprocess.run(["git", "-C", str(target), "commit", "-qm", "fixture"], check=True)

            result = subprocess.run(
                [
                    "python", str(CLI), "plan", "--template", str(ROOT), "--target", str(target),
                    "--route-only", "--route", "dispatch:implement:default=bounded_worker",
                    "--route", "dispatch:check:default=checking_sol_medium", "--format", "json",
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual([".codex/trellis-dispatch.toml"], [action["path"] for action in value["actions"]])

            ordinary = subprocess.run(
                [
                    "python", str(CLI), "plan", "--template", str(ROOT), "--target", str(target),
                    "--profile", "dispatch-only",
                    "--route", "dispatch:implement:default=bounded_worker",
                    "--route", "dispatch:check:default=checking_sol_medium", "--format", "json",
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(0, ordinary.returncode, ordinary.stderr)
            ordinary_value = json.loads(ordinary.stdout)
            self.assertEqual(3, ordinary_value["schemaVersion"])
            self.assertEqual(
                ["dispatch:check:default", "dispatch:implement:default"],
                [item["scope"] for item in ordinary_value["routeOverrides"]],
            )
            self.assertEqual(
                1,
                sum(action["path"] == ".codex/trellis-dispatch.toml" for action in ordinary_value["actions"]),
            )

            output = Path(temporary) / "invalid-dispatch-plan.json"
            invalid = subprocess.run(
                [
                    "python", str(CLI), "plan", "--template", str(ROOT), "--target", str(target),
                    "--route-only", "--route", "dispatch:implement:default=checking", "--output", str(output),
                ],
                cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            self.assertEqual(2, invalid.returncode)
            self.assertFalse(output.exists())

    def test_help_exposes_fixed_command_contract(self) -> None:
        result = subprocess.run(
            ["python", str(CLI), "--help"], cwd=ROOT, capture_output=True,
            text=True, encoding="utf-8", errors="replace", check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        for command in (
            "inspect-routes", "plan", "resolve", "apply", "verify", "rollback",
            "recover-plan", "recover-resolve", "recover-apply",
        ):
            self.assertIn(command, result.stdout)

        inspect_help = subprocess.run(
            ["python", str(CLI), "inspect-routes", "--help"], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
        self.assertEqual(0, inspect_help.returncode, inspect_help.stderr)
        self.assertIn("--target", inspect_help.stdout)
        self.assertIn("--format", inspect_help.stdout)
        self.assertNotIn("--template", inspect_help.stdout)

        plan_help = subprocess.run(
            ["python", str(CLI), "plan", "--help"], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
        self.assertIn("--route-pair", plan_help.stdout)
        self.assertEqual(0, plan_help.returncode, plan_help.stderr)
        self.assertIn("--profile", plan_help.stdout)
        self.assertIn("--adopt-partial", plan_help.stdout)
        self.assertIn("--route", plan_help.stdout)
        self.assertIn("--route-only", plan_help.stdout)

        verify_help = subprocess.run(
            ["python", str(CLI), "verify", "--help"], cwd=ROOT,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False,
        )
        self.assertEqual(0, verify_help.returncode, verify_help.stderr)
        self.assertIn("--integrity-only", verify_help.stdout)
        self.assertIn("read-only integrity check", verify_help.stdout)
        self.assertIn("does not complete full verification", verify_help.stdout)

        default_plan = _parser().parse_args([
            "plan", "--template", "template", "--target", "target",
        ])
        dispatch_plan = _parser().parse_args([
            "plan", "--template", "template", "--target", "target",
            "--profile", "dispatch-only",
        ])
        self.assertEqual("complete", default_plan.profile)
        self.assertFalse(default_plan.profile_provided)
        self.assertEqual("dispatch-only", dispatch_plan.profile)
        self.assertTrue(dispatch_plan.profile_provided)
        adoption_plan = _parser().parse_args([
            "plan", "--template", "template", "--target", "target",
            "--profile", "complete", "--adopt-partial",
        ])
        self.assertTrue(adoption_plan.adopt_partial)
        self.assertTrue(adoption_plan.profile_provided)
        routed_plan = _parser().parse_args([
            "plan", "--template", "template", "--target", "target",
            "--route", "role:research=exploration", "--route", "main=planning",
        ])
        self.assertEqual(["role:research=exploration", "main=planning"], routed_plan.route)
        route_only_plan = _parser().parse_args([
            "plan", "--template", "template", "--target", "target",
            "--route-only", "--route", "main=planning",
        ])
        self.assertTrue(route_only_plan.route_only)

        full_verify = _parser().parse_args(["verify", "--receipt", "receipt.json"])
        integrity_verify = _parser().parse_args([
            "verify", "--receipt", "receipt.json", "--integrity-only",
        ])
        self.assertFalse(full_verify.integrity_only)
        self.assertTrue(integrity_verify.integrity_only)

        inspect_routes = _parser().parse_args([
            "inspect-routes", "--target", "target",
        ])
        self.assertEqual("inspect-routes", inspect_routes.command)
        self.assertEqual("target", inspect_routes.target)
        self.assertEqual("human", inspect_routes.format)

        recovery = _parser().parse_args([
            "recover-plan", "--template", "template", "--target", "target",
            "--baseline", "baseline",
        ])
        self.assertEqual("recover-plan", recovery.command)
        self.assertEqual("baseline", recovery.baseline)

        recovery_commands = (
            ["recover-plan", "--template", "template", "--target", "target", "--baseline", "baseline"],
            ["recover-resolve", "--plan", "plan.json", "--output", "resolved.json"],
            ["recover-apply", "--plan", "plan.json", "--approve"],
        )
        for command in recovery_commands:
            for unsupported in (["--route", "main=coordination"], ["--route-only"]):
                with self.subTest(command=command[0], unsupported=unsupported), redirect_stderr(StringIO()), self.assertRaises(SystemExit) as raised:
                    _parser().parse_args([*command, *unsupported])
                self.assertEqual(2, raised.exception.code)

    def test_verify_integrity_only_is_explicit_and_preserves_full_verify_routing(self) -> None:
        reports = {
            "success": {
                "schemaVersion": 1,
                "status": "success",
                "receiptPath": str((ROOT / "receipt.json").resolve()),
                "checks": [],
                "commands": [],
                "unresolvedSidecars": [],
                "mode": "integrity-only",
            },
            "incomplete": {
                "schemaVersion": 1,
                "status": "incomplete",
                "receiptPath": str((ROOT / "receipt.json").resolve()),
                "checks": [],
                "commands": [],
                "unresolvedSidecars": ["local.harness-new"],
                "mode": "integrity-only",
            },
            "failed": {
                "schemaVersion": 1,
                "status": "failed",
                "receiptPath": str((ROOT / "receipt.json").resolve()),
                "checks": [{"status": "failed"}],
                "commands": [],
                "unresolvedSidecars": [],
                "mode": "integrity-only",
            },
        }
        for status, expected_exit in (("success", 0), ("incomplete", 6), ("failed", 6)):
            output = StringIO()
            with patch("harness_migration.cli.verify_integrity", return_value=reports[status]) as integrity, patch(
                "harness_migration.cli.verify_receipt",
            ) as full, redirect_stdout(output):
                exit_code = migration_main([
                    "verify", "--receipt", "receipt.json", "--integrity-only", "--format", "json",
                ])
            integrity.assert_called_once_with((ROOT / "receipt.json").resolve())
            full.assert_not_called()
            self.assertEqual(expected_exit, exit_code)
            value = json.loads(output.getvalue())
            self.assertEqual(status, value["status"])
            self.assertEqual("integrity-only", value["mode"])

        full_report = {
            "schemaVersion": 1,
            "status": "success",
            "receiptPath": str((ROOT / "receipt.json").resolve()),
            "checks": [],
            "commands": [{"status": "passed"}],
            "unresolvedSidecars": [],
        }
        output = StringIO()
        with patch("harness_migration.cli.verify_integrity") as integrity, patch(
            "harness_migration.cli.verify_receipt", return_value=full_report,
        ) as full, redirect_stdout(output):
            exit_code = migration_main([
                "verify", "--receipt", "receipt.json", "--format", "json",
            ])
        integrity.assert_not_called()
        full.assert_called_once_with((ROOT / "receipt.json").resolve())
        self.assertEqual(0, exit_code)
        self.assertNotIn("mode", json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
