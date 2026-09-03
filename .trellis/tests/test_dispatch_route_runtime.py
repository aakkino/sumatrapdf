from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".trellis" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from dispatch_routes import (  # noqa: E402
    DispatchRouteResolutionError,
    resolve_all_dispatch_lanes,
    resolve_dispatch_lane,
)


def _load_workflow_hook():
    spec = importlib.util.spec_from_file_location(
        "trellis_test_inject_workflow_state",
        ROOT / ".codex" / "hooks" / "inject-workflow-state.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


WORKFLOW_HOOK = _load_workflow_hook()


class DispatchRouteRuntimeTests(unittest.TestCase):
    def write_dispatch_config(self, root: Path, contents: str) -> None:
        path = root / ".codex" / "trellis-dispatch.toml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding="utf-8")

    def test_resolves_all_persisted_lanes_in_stable_order(self) -> None:
        lanes = resolve_all_dispatch_lanes(ROOT)
        self.assertEqual(
            [
                ("implement", "default", "custom", "gpt-5.6-terra", "xhigh"),
                ("implement", "hard", "hard_implementation", "gpt-5.6-sol", "medium"),
                ("check", "default", "custom", "gpt-5.6-terra", "xhigh"),
                ("check", "hard", "hard_checking", "gpt-5.6-sol", "xhigh"),
            ],
            [
                (item.role, item.lane, item.route, item.model, item.effort)
                for item in lanes
            ],
        )

    def test_fail_closed_configuration_errors_identify_selected_lane(self) -> None:
        cases = (
            ("missing_file", None, "missing_file"),
            ("malformed", "[implement.default]\nmodel = [\n", "malformed_toml"),
            (
                "missing_table",
                "[check.default]\nmodel = \"gpt-5.6-terra\"\n"
                "model_reasoning_effort = \"max\"\n",
                "missing_table",
            ),
            (
                "incomplete",
                "[implement.default]\nmodel = \"gpt-5.6-terra\"\n",
                "missing_effort",
            ),
            (
                "missing_model",
                "[implement.default]\nmodel_reasoning_effort = \"high\"\n",
                "missing_model",
            ),
            (
                "missing_both",
                "[implement.default]\nother = \"value\"\n",
                "missing_model_and_effort",
            ),
            (
                "invalid_table",
                "implement = \"not-a-table\"\n",
                "invalid_table",
            ),
            (
                "non_string",
                "[implement.default]\nmodel = 3\n"
                "model_reasoning_effort = \"high\"\n",
                "model_not_string",
            ),
            (
                "non_string_effort",
                "[implement.default]\nmodel = \"gpt-5.6-terra\"\n"
                "model_reasoning_effort = 3\n",
                "effort_not_string",
            ),
            (
                "empty_model",
                "[implement.default]\nmodel = \"\"\n"
                "model_reasoning_effort = \"high\"\n",
                "model_empty",
            ),
            (
                "empty_effort",
                "[implement.default]\nmodel = \"gpt-5.6-terra\"\n"
                "model_reasoning_effort = \"\"\n",
                "effort_empty",
            ),
        )
        for name, contents, reason in cases:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                if contents is not None:
                    self.write_dispatch_config(root, contents)
                with self.assertRaises(DispatchRouteResolutionError) as raised:
                    resolve_dispatch_lane(root, "implement", "default")
                self.assertEqual("dispatch:implement:default", raised.exception.scope)
                self.assertEqual(reason, raised.exception.reason)
                self.assertIn(".codex/trellis-dispatch.toml", str(raised.exception))

    def test_custom_and_cross_catalog_pairs_resolve_as_custom_routes(self) -> None:
        for model, effort in (("custom-model", "custom-effort"), ("gpt-5.6-terra", "max")):
            with self.subTest(model=model, effort=effort), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                self.write_dispatch_config(
                    root,
                    f'[implement.default]\nmodel = "{model}"\nmodel_reasoning_effort = "{effort}"\n',
                )
                route = resolve_dispatch_lane(root, "implement", "default")
                self.assertEqual("custom", route.route)
                self.assertEqual(model, route.model)
                self.assertEqual(effort, route.effort)

    def test_fail_closed_path_validation_rejects_rebound_or_non_directory_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex = root / ".codex"
            original_is_symlink = Path.is_symlink

            def mark_codex_as_link(path: Path) -> bool:
                return path == codex or original_is_symlink(path)

            with mock.patch.object(Path, "is_symlink", autospec=True, side_effect=mark_codex_as_link):
                with self.assertRaises(DispatchRouteResolutionError) as raised:
                    resolve_dispatch_lane(root, "check", "hard")
            self.assertEqual("dispatch:check:hard", raised.exception.scope)
            self.assertEqual("unsafe_path", raised.exception.reason)

            codex.write_text("not a directory\n", encoding="utf-8")
            with self.assertRaises(DispatchRouteResolutionError) as raised:
                resolve_dispatch_lane(root, "implement", "default")
            self.assertEqual("path_parent_not_directory", raised.exception.reason)

            with mock.patch.object(Path, "is_symlink", autospec=True, return_value=True):
                with self.assertRaises(DispatchRouteResolutionError) as raised:
                    resolve_dispatch_lane(root, "implement", "hard")
            self.assertEqual("invalid_root", raised.exception.reason)

    def test_hook_adds_resolved_lanes_to_codex_in_progress_context(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(
                WORKFLOW_HOOK,
                "_load_hook_input",
                return_value={"cwd": str(ROOT), "prompt": "continue"},
            ),
            mock.patch.object(WORKFLOW_HOOK, "_detect_platform", return_value="codex"),
            mock.patch.object(
                WORKFLOW_HOOK,
                "get_active_task",
                return_value=("runtime-test", "in_progress", "test"),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, WORKFLOW_HOOK.main())

        additional_context = json.loads(output.getvalue())["hookSpecificOutput"][
            "additionalContext"
        ]
        self.assertIn("<workflow-state>", additional_context)
        self.assertIn("<trellis-dispatch>", additional_context)
        for expected in (
            "dispatch:implement:default: custom (gpt-5.6-terra / xhigh)",
            "dispatch:implement:hard: hard_implementation (gpt-5.6-sol / medium)",
            "dispatch:check:default: custom (gpt-5.6-terra / xhigh)",
            "dispatch:check:hard: hard_checking (gpt-5.6-sol / xhigh)",
        ):
            self.assertIn(expected, additional_context)

    def test_hook_surfaces_a_block_without_suppressing_workflow_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            blocking_context = WORKFLOW_HOOK._codex_dispatch_context(Path(temporary))
        self.assertIn("BLOCKED", blocking_context)
        self.assertIn("dispatch:implement:default", blocking_context)
        self.assertIn("missing_file", blocking_context)
        self.assertIn("Other prompts may continue", blocking_context)

        output = io.StringIO()
        with (
            mock.patch.object(
                WORKFLOW_HOOK,
                "_load_hook_input",
                return_value={"cwd": str(ROOT), "prompt": "unrelated question"},
            ),
            mock.patch.object(WORKFLOW_HOOK, "_detect_platform", return_value="codex"),
            mock.patch.object(
                WORKFLOW_HOOK,
                "get_active_task",
                return_value=("runtime-test", "in_progress", "test"),
            ),
            mock.patch.object(
                WORKFLOW_HOOK,
                "_codex_dispatch_context",
                return_value=blocking_context,
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, WORKFLOW_HOOK.main())

        additional_context = json.loads(output.getvalue())["hookSpecificOutput"][
            "additionalContext"
        ]
        self.assertIn("<workflow-state>", additional_context)
        self.assertIn(blocking_context, additional_context)

    def test_hook_reports_custom_lanes_and_keeps_named_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.write_dispatch_config(
                root,
                """[implement.default]
model = "custom-model"
model_reasoning_effort = "high"

[implement.hard]
model = "gpt-5.6-sol"
model_reasoning_effort = "medium"

[check.default]
model = "gpt-5.6-terra"
model_reasoning_effort = "max"

[check.hard]
model = "gpt-5.6-sol"
model_reasoning_effort = "xhigh"
""",
            )
            context = WORKFLOW_HOOK._codex_dispatch_context(root)

        self.assertIn(
            "dispatch:implement:default: custom (custom-model / high)", context
        )
        self.assertIn(
            "dispatch:implement:hard: hard_implementation (gpt-5.6-sol / medium)",
            context,
        )
        self.assertIn(
            "dispatch:check:default: checking (gpt-5.6-terra / max)", context
        )
        self.assertNotIn("BLOCKED", context)

    def test_non_codex_hook_does_not_resolve_codex_dispatch_lanes(self) -> None:
        output = io.StringIO()
        with (
            mock.patch.object(
                WORKFLOW_HOOK,
                "_load_hook_input",
                return_value={"cwd": str(ROOT), "prompt": "continue"},
            ),
            mock.patch.object(WORKFLOW_HOOK, "_detect_platform", return_value="claude"),
            mock.patch.object(
                WORKFLOW_HOOK,
                "get_active_task",
                return_value=("runtime-test", "in_progress", "test"),
            ),
            mock.patch.object(
                WORKFLOW_HOOK,
                "_codex_dispatch_context",
                side_effect=AssertionError("Codex resolver reached from Claude hook"),
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(0, WORKFLOW_HOOK.main())

        additional_context = json.loads(output.getvalue())["hookSpecificOutput"][
            "additionalContext"
        ]
        self.assertTrue(additional_context.startswith("<workflow-state>"))
        self.assertNotIn("<codex-mode>", additional_context)


if __name__ == "__main__":
    unittest.main()
