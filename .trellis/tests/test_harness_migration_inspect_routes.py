from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / ".trellis" / "scripts" / "harness_migrate.py"


class HarnessMigrationInspectRoutesTests(unittest.TestCase):
    def _run(self, target: Path, output_format: str = "json") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python", str(CLI), "inspect-routes", "--target", str(target), "--format", output_format],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
        )

    def _write(self, target: Path, relative: str, text: str) -> Path:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_known_shared_config_is_deterministic_and_read_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.mkdir()
            files = [
                self._write(target, ".codex/config.toml", """model = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"medium\"\n\n[agents]\ndefault_subagent_model = \"gpt-5.6-terra\"\ndefault_subagent_reasoning_effort = \"high\"\n"""),
                self._write(target, ".codex/agents/trellis-research.toml", "model = \"gpt-5.6-terra\"\nmodel_reasoning_effort = \"medium\"\n"),
                self._write(target, ".codex/agents/trellis-debug.toml", "model = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"low\"\n"),
                self._write(target, ".codex/agents/trellis-review.toml", "model = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"high\"\n"),
                self._write(target, ".codex/agents/trellis-audit.toml", "model = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"high\"\n"),
                self._write(target, ".codex/agents/trellis-release.toml", "model = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"high\"\n"),
                self._write(target, ".codex/trellis-dispatch.toml", """[implement.default]\nmodel = \"gpt-5.6-terra\"\nmodel_reasoning_effort = \"high\"\n\n[implement.hard]\nmodel = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"medium\"\n\n[check.default]\nmodel = \"gpt-5.6-terra\"\nmodel_reasoning_effort = \"max\"\n\n[check.hard]\nmodel = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"xhigh\"\n"""),
            ]
            self._write(target, ".trellis/.runtime/sessions/active.json", '{"task":"active"}\n')
            before = {
                path.relative_to(target).as_posix(): path.read_bytes()
                for path in target.rglob("*") if path.is_file()
            }

            first = self._run(target)
            second = self._run(target)

            self.assertEqual(0, first.returncode, first.stderr)
            self.assertEqual(first.stdout, second.stdout)
            value = json.loads(first.stdout)
            self.assertEqual(str(target.resolve()), value["targetRoot"])
            self.assertEqual(
                [
                    "main", "subagent-default", "role:research", "role:debug", "role:review", "role:audit", "role:release",
                    "dispatch:implement:default", "dispatch:implement:hard", "dispatch:check:default", "dispatch:check:hard",
                ],
                [route["scope"] for route in value["routes"]],
            )
            self.assertTrue(all(route["status"] == "known" for route in value["routes"]))
            self.assertEqual("coordination", value["routes"][0]["route"])
            self.assertEqual("bounded_worker", value["routes"][1]["route"])
            legacy_keys = {"scope", "path", "status", "route", "model", "effort", "detail"}
            self.assertTrue(all(set(route) == legacy_keys for route in value["routes"][:7]))
            self.assertEqual(
                ["implement.default", "implement.hard", "check.default", "check.hard"],
                [route["table"] for route in value["routes"][-4:]],
            )
            self.assertEqual(
                before,
                {
                    path.relative_to(target).as_posix(): path.read_bytes()
                    for path in target.rglob("*") if path.is_file()
                },
            )

    def test_custom_missing_and_invalid_route_states_are_distinguished(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.mkdir()
            self._write(target, ".codex/config.toml", """model = \"gpt-custom\"\nmodel_reasoning_effort = \"extra\"\n\n[agents]\ndefault_subagent_model = \"gpt-5.6-terra\"\n""")
            self._write(target, ".codex/agents/trellis-research.toml", "model = 3\nmodel_reasoning_effort = \"medium\"\n")
            self._write(target, ".codex/agents/trellis-debug.toml", "model = [\n")
            self._write(target, ".codex/agents/trellis-release.toml", """[agents]\nmodel = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"high\"\n""")

            result = self._run(target)

            self.assertEqual(0, result.returncode, result.stderr)
            routes = {route["scope"]: route for route in json.loads(result.stdout)["routes"]}
            self.assertEqual(("custom", "uncatalogued_pair"), (routes["main"]["status"], routes["main"]["detail"]))
            self.assertEqual(("missing", "missing_effort"), (routes["subagent-default"]["status"], routes["subagent-default"]["detail"]))
            self.assertEqual(("invalid", "model_not_string"), (routes["role:research"]["status"], routes["role:research"]["detail"]))
            self.assertEqual(("invalid", "malformed_toml"), (routes["role:debug"]["status"], routes["role:debug"]["detail"]))
            self.assertEqual(("missing", "missing_file"), (routes["role:review"]["status"], routes["role:review"]["detail"]))
            self.assertEqual(("invalid", "wrong_table"), (routes["role:release"]["status"], routes["role:release"]["detail"]))
            for scope in (
                "dispatch:implement:default", "dispatch:implement:hard",
                "dispatch:check:default", "dispatch:check:hard",
            ):
                self.assertEqual(("missing", "missing_file"), (routes[scope]["status"], routes[scope]["detail"]))

    def test_dispatch_lanes_distinguish_nested_table_states(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.mkdir()
            self._write(target, ".codex/trellis-dispatch.toml", """[implement.default]\nmodel = \"custom-implement\"\nmodel_reasoning_effort = \"custom-effort\"\n\n[implement.hard]\nmodel = \"gpt-5.6-sol\"\n\n[check.default]\nmodel = 3\nmodel_reasoning_effort = \"max\"\n\n[check.hard]\nmodel = \"gpt-5.6-sol\"\nmodel_reasoning_effort = \"xhigh\"\n""")

            result = self._run(target)

            self.assertEqual(0, result.returncode, result.stderr)
            routes = {route["scope"]: route for route in json.loads(result.stdout)["routes"]}
            self.assertEqual(("custom", "uncatalogued_pair"), (routes["dispatch:implement:default"]["status"], routes["dispatch:implement:default"]["detail"]))
            self.assertEqual(("missing", "missing_effort"), (routes["dispatch:implement:hard"]["status"], routes["dispatch:implement:hard"]["detail"]))
            self.assertEqual(("invalid", "model_not_string"), (routes["dispatch:check:default"]["status"], routes["dispatch:check:default"]["detail"]))
            self.assertEqual(("known", "hard_checking"), (routes["dispatch:check:hard"]["status"], routes["dispatch:check:hard"]["route"]))

    def test_human_output_and_invalid_target_argument(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "target"
            target.mkdir()
            self._write(target, ".codex/config.toml", "model = \"gpt-custom\"\nmodel_reasoning_effort = \"extra\"\n")

            human = self._run(target, "human")
            invalid = self._run(target / "missing")

            self.assertEqual(0, human.returncode, human.stderr)
            self.assertIn("main: custom; gpt-custom / extra; .codex/config.toml [uncatalogued_pair]", human.stdout)
            self.assertIn("subagent-default: missing; - / -; .codex/config.toml [missing_model_and_effort]", human.stdout)
            self.assertIn("dispatch:implement:default: missing; - / -; .codex/trellis-dispatch.toml [implement.default] [missing_file]", human.stdout)
            self.assertEqual(2, invalid.returncode)


if __name__ == "__main__":
    unittest.main()
