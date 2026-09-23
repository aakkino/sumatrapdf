from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".trellis" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from common.task_contract import (  # noqa: E402
    BASELINE_FILE,
    CANDIDATE_FILE,
    capture_baseline,
    final_gate_decision,
    freeze_candidate,
    record_evidence,
    validate_protected_baseline,
    validate_task_contract,
    validate_unit_ownership,
)


class TaskContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        subprocess.run(["git", "init", "-q"], cwd=self.root, check=True)
        self.task_dir = self.root / ".trellis" / "tasks" / "09-03-contract"
        self.task_dir.mkdir(parents=True)
        (self.root / "spec.md").write_text("context\n", encoding="utf-8")
        self._write_valid_task()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_valid_task(self, *, max_runs: int = 1) -> None:
        (self.task_dir / "task.json").write_text(
            json.dumps({"status": "planning"}), encoding="utf-8"
        )
        (self.task_dir / "prd.md").write_text(
            "# Contract\n\n## Goal\n\nProtect work.\n\n## Requirements\n\n- Validate.\n\n## Acceptance Criteria\n\n- [ ] Pass.\n",
            encoding="utf-8",
        )
        (self.task_dir / "design.md").write_text(
            "# Design\n\n## Architecture\n\nLocal helper.\n\n## Lifecycle and State\n\nPlanning to execution.\n\n## Compatibility and Ownership\n\nProject local only.\n",
            encoding="utf-8",
        )
        implement = {
            "schemaVersion": 1,
            "forbiddenVerification": ["test", "lint", "typecheck", "build"],
            "units": [
                {
                    "id": "runtime",
                    "dependsOn": [],
                    "ownedPaths": ["src/**"],
                    "actions": ["Add runtime helper."],
                    "forbiddenPaths": [],
                    "allowedGenerators": [],
                    "acceptanceCriteria": ["AC1"],
                    "stopConditions": ["Blocked."],
                }
            ],
        }
        (self.task_dir / "implement.md").write_text(
            "# Implementation\n\n## Contract\n\n```json\n"
            + json.dumps(implement, indent=2)
            + "\n```\n\n## Unit 1\n\nAdd runtime helper.\n\n## Validation Plan\n\nUse the authorized command.\n",
            encoding="utf-8",
        )
        check = {
            "schemaVersion": 1,
            "protectedBaseline": "baseline.json",
            "selfFix": {
                "allowedPaths": ["src/**"],
                "allowedIssueClasses": ["contract-validation"],
                "maxRounds": 1,
            },
            "paired": {
                "maxTier": "T1",
                "commands": [
                    {
                        "id": "targeted",
                        "argv": ["python", "-m", "unittest"],
                        "tier": "T1",
                        "invalidatedBy": ["src/**"],
                        "maxRuns": max_runs,
                    }
                ],
            },
            "finalGate": {"maxTier": "T0", "commands": []},
        }
        (self.task_dir / "check.md").write_text(
            "# Check\n\n## Machine Contract\n\n```json\n"
            + json.dumps(check, indent=2)
            + "\n```\n\n## Audit Matrix\n\n| Requirement | Evidence |\n| --- | --- |\n| AC1 | Targeted |\n\n## Paired Check Procedure\n\nReview.\n\n## Final Gate Procedure\n\nDecide.\n",
            encoding="utf-8",
        )
        manifest = json.dumps({"file": "spec.md", "reason": "task context"}) + "\n"
        (self.task_dir / "implement.jsonl").write_text(manifest, encoding="utf-8")
        (self.task_dir / "check.jsonl").write_text(manifest, encoding="utf-8")

    def test_valid_contract_captures_and_preserves_baseline(self) -> None:
        self.assertEqual([], validate_task_contract(self.task_dir, self.root))
        self.assertEqual([], capture_baseline(self.task_dir, self.root))
        self.assertTrue((self.task_dir / BASELINE_FILE).is_file())
        self.assertEqual([], validate_protected_baseline(self.task_dir, self.root))

    def test_start_rejects_invalid_contract_without_partial_mutation(self) -> None:
        (self.task_dir / "implement.md").write_text("# Implementation\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(SCRIPTS / "task.py"), "start", str(self.task_dir)],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("task planning contract is invalid", result.stdout)
        self.assertEqual("planning", json.loads((self.task_dir / "task.json").read_text())["status"])
        self.assertFalse((self.task_dir / BASELINE_FILE).exists())

    def test_baseline_overlap_and_drift_are_blocked(self) -> None:
        source = self.root / "src" / "app.py"
        source.parent.mkdir()
        source.write_text("before\n", encoding="utf-8")
        errors = capture_baseline(self.task_dir, self.root)
        self.assertEqual(["baseline-dirty path overlaps unit 'runtime' ownership: src/app.py"], errors)
        self.assertFalse((self.task_dir / BASELINE_FILE).exists())

        source.unlink()
        self.assertEqual([], capture_baseline(self.task_dir, self.root))
        (self.root / "spec.md").write_text("changed\n", encoding="utf-8")
        self.assertEqual(["protected baseline changed: spec.md"], validate_protected_baseline(self.task_dir, self.root))

    def test_ownership_budget_and_stale_candidate_are_enforced(self) -> None:
        self.assertEqual([], capture_baseline(self.task_dir, self.root))
        source = self.root / "src" / "app.py"
        source.parent.mkdir()
        source.write_text("first\n", encoding="utf-8")
        self.assertEqual([], validate_unit_ownership(self.task_dir, self.root, "runtime"))
        self.assertEqual(
            [],
            record_evidence(
                self.task_dir,
                self.root,
                stage="paired",
                unit_id="runtime",
                command_id="targeted",
                result="pass",
            ),
        )
        self.assertIn(
            "exceeded maxRuns=1",
            record_evidence(
                self.task_dir,
                self.root,
                stage="paired",
                unit_id="runtime",
                command_id="targeted",
                result="pass",
            )[0],
        )
        digest, errors = freeze_candidate(self.task_dir, self.root)
        self.assertFalse(errors)
        self.assertTrue(digest)
        self.assertTrue((self.task_dir / CANDIDATE_FILE).is_file())
        self.assertEqual(("ready", []), final_gate_decision(self.task_dir, self.root))
        source.write_text("second\n", encoding="utf-8")
        decision, errors = final_gate_decision(self.task_dir, self.root)
        self.assertEqual("blocked", decision)
        self.assertTrue(
            any("candidate digest is missing or stale" in error for error in errors)
        )


if __name__ == "__main__":
    unittest.main()
