from __future__ import annotations

import json
from pathlib import Path
import re
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[2]


class RoleContextCustomizationTests(unittest.TestCase):
    def read(self, path: str) -> str:
        return (ROOT / path).read_text(encoding="utf-8")

    def profile(self, role: str) -> dict[str, object]:
        return tomllib.loads(self.read(f".codex/agents/trellis-{role}.toml"))

    def test_native_final_gate_is_read_only_and_reachable(self) -> None:
        hooks = json.loads(self.read(".codex/hooks.json"))
        matcher = hooks["hooks"]["SubagentStart"][0]["matcher"]
        for role in ("trellis-implement", "trellis-check", "trellis-final-check", "trellis-research"):
            self.assertRegex(role, matcher)

        final = self.profile("final-check")
        instructions = str(final["developer_instructions"])
        self.assertEqual("read-only", final["sandbox_mode"])
        self.assertEqual("gpt-5.6-sol", final["model"])
        self.assertEqual("high", final["model_reasoning_effort"])
        self.assertIn("candidate.json", instructions)
        self.assertIn("exactly `ready` or `blocked`", instructions)
        self.assertIn("Do not edit files", instructions)

    def test_role_contexts_have_distinct_authority(self) -> None:
        hook = self.read(".codex/hooks/inject-subagent-context.py")
        implement = self.profile("implement")["developer_instructions"]
        check = self.profile("check")["developer_instructions"]

        self.assertIn("get_implement_context", hook)
        self.assertIn("get_check_context", hook)
        self.assertIn("get_final_check_context", hook)
        self.assertIn("build_final_check_prompt", hook)
        self.assertIn("check.md", hook)
        self.assertIn("baseline.json", hook)
        self.assertIn("evidence.jsonl", hook)
        self.assertIn("Do not run tests, lint, type-check, build", str(implement))
        self.assertIn("only commands explicitly listed in `check.md`", str(check))
        self.assertNotIn("full-scope validation", hook)

    def test_channel_cards_and_workflow_use_bounded_final_gate(self) -> None:
        final_card = self.read(".trellis/agents/final-check.md")
        workflow = self.read(".trellis/workflow.md")
        check_skill = self.read(".agents/skills/trellis-check/SKILL.md")

        self.assertIn("name: final-check", final_card)
        self.assertIn("Do not edit files", final_card)
        self.assertIn("finalGate commands", final_card)
        self.assertIn("trellis-final-check", workflow)
        self.assertIn("freeze-candidate", workflow)
        self.assertIn("No paired check may infer a broader validation tier", workflow)
        self.assertNotIn("full-scope validation", workflow)
        self.assertNotIn("full-scope validation", check_skill)

    def test_project_policy_and_export_cover_project_local_final_role(self) -> None:
        if not (ROOT / "export-manifest.json").is_file():
            self.skipTest("export manifest is only present in the authoring template")

        agents = self.read("AGENTS.md")
        manifest = json.loads(self.read("export-manifest.json"))
        exported = manifest["migrationProfiles"]["agent-workflow"]["include"]

        self.assertIn("trellis-final-check", agents)
        self.assertIn("finalGate budget", agents)
        self.assertIn(".codex/agents/trellis-final-check.toml", exported)
        self.assertIn(".trellis/scripts/common/task_contract.py", exported)
        self.assertIn(".trellis/agents/final-check.md", exported)

    def test_template_hashes_do_not_claim_project_local_final_role(self) -> None:
        hashes = json.loads(self.read(".trellis/.template-hashes.json"))["hashes"]
        self.assertNotIn(".codex/agents/trellis-final-check.toml", hashes)
        self.assertNotIn(".trellis/agents/final-check.md", hashes)


if __name__ == "__main__":
    unittest.main()
