from __future__ import annotations

import argparse
from pathlib import Path
import re
import shlex
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
SKILLS_ROOT = ROOT / ".agents" / "skills"
SKILL_ROOT = SKILLS_ROOT / "harness-migration"
CLI_PATH = ".trellis/scripts/harness_migrate.py"
sys.path.insert(0, str(ROOT / ".trellis" / "scripts"))
from harness_migration.cli import _parser
from harness_migration.manifest import exported_files, load_manifest, matching_rule
from harness_migration.models import ACTION_KEYS, DECISION_KEYS, PLAN_KEYS, RuleKind
from harness_migration.planner import (
    SIDECAR_SUFFIX,
    VERIFICATION_COMMANDS,
    normalize_route_overrides,
    normalize_route_pairs,
)
from harness_migration.transaction import PRESERVED_ROOTS


INVOCATION = re.compile(
    r'^\s*python\s+(?:\$runner|"[^"\r\n]*harness_migrate\.py")\s+(?P<arguments>[^\r\n]+)$',
    re.MULTILINE,
)


def has_source_template_support_files(root: Path) -> bool:
    return all((root / relative).is_file() for relative in ("README.md", "export-manifest.json"))


class HarnessMigrationSkillTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (SKILL_ROOT / relative).read_text(encoding="utf-8")

    def command_parsers(self) -> dict[str, argparse.ArgumentParser]:
        subparsers = next(
            action for action in _parser()._actions
            if isinstance(action, argparse._SubParsersAction)
        )
        return subparsers.choices

    def test_bundled_trellis_meta_has_no_harness_private_workflow_rules(self) -> None:
        meta_root = SKILLS_ROOT / "trellis-meta"
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in sorted(meta_root.rglob("*.md"))
        ).lower()
        for private_term in (
            "agent-workflow",
            "codex-dispatch-workflow-v1",
            "export-manifest.json",
            "harness_migrate.py",
            "copier answers",
        ):
            with self.subTest(private_term=private_term):
                self.assertNotIn(private_term, combined)

    def documented_invocations(self, text: str) -> list[tuple[list[str], argparse.Namespace]]:
        parser = _parser()
        return [
            (arguments := shlex.split(match.group("arguments")), parser.parse_args(arguments))
            for match in INVOCATION.finditer(text)
        ]

    def assert_invocations_follow_parser(self, text: str) -> list[tuple[list[str], argparse.Namespace]]:
        command_parsers = self.command_parsers()
        invocations = self.documented_invocations(text)
        self.assertTrue(invocations, "expected at least one source-runner invocation")
        for arguments, parsed in invocations:
            with self.subTest(command=parsed.command):
                options = {argument for argument in arguments if argument.startswith("--")}
                required = {
                    option
                    for action in command_parsers[parsed.command]._actions
                    if action.required
                    for option in action.option_strings
                }
                self.assertTrue(required <= options)
                if parsed.command in {"plan", "recover-plan"}:
                    self.assertTrue({"--template", "--target"} <= options)
                elif parsed.command == "inspect":
                    self.assertIn("--template", options)
                    self.assertNotIn("--target", options)
                elif parsed.command == "inspect-routes":
                    self.assertIn("--target", options)
                    self.assertNotIn("--template", options)
                else:
                    self.assertFalse({"--template", "--target"} & options)
                if "--approve" in {
                    option for action in command_parsers[parsed.command]._actions
                    for option in action.option_strings
                }:
                    self.assertIn("--approve", options)
        return invocations

    def test_skill_is_discoverable_and_scoped_to_cli_migration(self) -> None:
        skill = self.read("SKILL.md")
        frontmatter = re.match(r"\A---\n(?P<body>.*?)\n---\n", skill, re.DOTALL)
        self.assertIsNotNone(frontmatter)
        fields = dict(
            (key.strip(), value.strip().strip('"'))
            for key, value in (
                line.split(":", 1)
                for line in frontmatter.group("body").splitlines()
                if ":" in line
            )
        )
        self.assertEqual("harness-migration", fields.get("name"))
        description = fields.get("description", "").lower()
        self.assertIn("migrat", description)
        self.assertIn("official", description)
        self.assertIn(CLI_PATH, skill)
        linked_references = set(re.findall(r"\]\((references/[^)]+)\)", skill))
        self.assertEqual({"references/plan-contract.md", "references/operator-flow.md"}, linked_references)
        for reference in linked_references:
            with self.subTest(reference=reference):
                self.assertTrue((SKILL_ROOT / reference).is_file())

    def test_skill_routes_filesystem_work_to_the_cli_with_authorization(self) -> None:
        skill = self.read("SKILL.md")
        operator = self.read("references/operator-flow.md")
        plan_contract = self.read("references/plan-contract.md")
        combined = skill + "\n" + plan_contract + "\n" + operator

        invocations = self.assert_invocations_follow_parser(combined)
        commands = {parsed.command for _, parsed in invocations}
        self.assertEqual(set(self.command_parsers()), commands)

        route_only_invocations = [
            (arguments, parsed)
            for arguments, parsed in invocations
            if parsed.command == "plan" and parsed.route_only
        ]
        self.assertEqual(2, len(route_only_invocations))
        route_only = next(parsed for _, parsed in route_only_invocations if parsed.route)
        self.assertEqual(
            ["dispatch:implement:default=bounded_worker"],
            route_only.route,
        )
        self.assertFalse(route_only.profile_provided)
        self.assertFalse(route_only.developer_provided)
        self.assertFalse(route_only.adopt_partial)
        raw_route_only = next(parsed for _, parsed in route_only_invocations if parsed.route_pair)
        self.assertEqual(
            ["role:research=gpt-5.6-terra,xhigh"],
            raw_route_only.route_pair,
        )
        raw = normalize_route_pairs(raw_route_only.route_pair)
        self.assertEqual(("role:research", "gpt-5.6-terra", "xhigh"), (raw[0].scope, raw[0].model, raw[0].effort))
        for override in (
            "dispatch:implement:default=bounded_worker",
            "dispatch:implement:hard=hard_implementation",
            "dispatch:check:default=checking",
            "dispatch:check:default=checking_sol_medium",
            "dispatch:check:hard=hard_checking",
        ):
            with self.subTest(override=override):
                self.assertIn(f"`{override}`", skill)
                normalized = normalize_route_overrides([override])
                self.assertEqual(override, f"{normalized[0].scope}={normalized[0].route}")
        self.assertRegex(skill, r"arbitrary\s+model/effort\s+combination")
        self.assertRegex(
            skill,
            r"(?s)`--route-only`.*?`existing_trellis` target.*?`--profile`.*?"
            r"`--developer`.*?`--adopt-partial`",
        )
        self.assertIn("explicit authorization", skill)
        self.assertIn("sole filesystem authority", skill)
        self.assertIn("ownership classification", skill)
        self.assertIn("Stop when `blockers` is non-empty", skill)
        self.assertRegex(skill, r"unresolved\s+`decisions`")
        self.assertIn("incomplete", operator)

        for required in (
            "trellis platforms --json",
            "inspect --template",
            "trellis-meta",
            "actual local files",
            "directly with focused tests",
            "official_unchanged",
            "official_modified",
            "official_missing",
            "project_local",
            "manifest, not the hash map",
            "schema-6",
            "codex-dispatch-workflow-v1",
            "Copier answers",
            "render Jinja",
            "Git template tags",
            "template tasks or migrations",
        ):
            with self.subTest(documentation_contract=required):
                self.assertIn(required, combined)
        self.assertRegex(combined, r"(?s)agent-workflow.*?excludes\s+`\.trellis/\.template-hashes\.json`")
        self.assertRegex(combined, r"(?s)apply and rollback never\s+rewrite.*?official baseline")

        forbidden = (
            r"\bCopy-Item\b",
            r"\bRemove-Item\b",
            r"\bMove-Item\b",
            r"\bNew-Item\b",
            r"\brobocopy\b",
            r"\bxcopy\b",
            r"\brsync\b",
            r"\bshutil\.copy",
            r"\bshutil\.",
            r"\bos\.remove\b",
            r"\bos\.unlink\b",
            r"\brmtree\b",
            r"(?m)^\s*(?:cp|rm)\s",
        )
        for pattern in forbidden:
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, combined))

    def test_source_template_support_detection_rejects_business_readme_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "README.md").write_text("# Business project\n", encoding="utf-8")

            self.assertFalse(has_source_template_support_files(root))

            (root / "export-manifest.json").write_text("{}\n", encoding="utf-8")
            self.assertTrue(has_source_template_support_files(root))

    @unittest.skipUnless((ROOT / "export-manifest.json").is_file(), "requires source-template support files")
    def test_references_match_plan_schema_and_manifest_policy(self) -> None:
        skill = self.read("SKILL.md")
        plan_reference = self.read("references/plan-contract.md")
        manifest = load_manifest(ROOT)
        for field in PLAN_KEYS:
            with self.subTest(field=field):
                self.assertIn(f"`{field}`", plan_reference)
        for field in ACTION_KEYS | DECISION_KEYS:
            with self.subTest(field=field):
                self.assertIn(f"`{field}`", plan_reference)
        for kind in RuleKind:
            with self.subTest(kind=kind):
                self.assertIn(f"`{kind.value}`", plan_reference)
        self.assertIn("`--profile <name>`", plan_reference)
        self.assertIn("manifest-owned `complete` profile", plan_reference)
        self.assertIn("part of `planDigest`", plan_reference)
        self.assertIn("`apply` rebuilds that same profile canonically", plan_reference)
        self.assertIn("including its recorded profile", skill)

    @unittest.skipUnless((ROOT / "export-manifest.json").is_file(), "requires source-template support files")
    def test_manifest_declares_and_recursively_exports_project_local_skills(self) -> None:
        manifest = load_manifest(ROOT)
        skills = manifest.raw["skills"]
        project_local_skills = skills["projectLocal"]
        npm_managed_skills = skills["npmManaged"]
        source_skill_roots = {
            path.name: path
            for path in SKILLS_ROOT.iterdir()
            if path.is_dir() and (path / "SKILL.md").is_file()
        }
        source_skill_names = set(source_skill_roots)

        self.assertEqual(
            sorted(project_local_skills),
            project_local_skills,
        )
        self.assertEqual(len(project_local_skills), len(set(project_local_skills)))
        self.assertFalse(set(project_local_skills) & set(npm_managed_skills))
        self.assertEqual(
            source_skill_names,
            set(project_local_skills) | set(npm_managed_skills),
        )
        self.assertEqual(
            set(project_local_skills),
            source_skill_names - set(npm_managed_skills),
        )

        exported = set(exported_files(ROOT, manifest))
        for name in project_local_skills:
            with self.subTest(skill=name):
                skill_root = source_skill_roots[name]
                source_files = {
                    path.relative_to(ROOT).as_posix()
                    for path in skill_root.rglob("*")
                    if path.is_file()
                }
                self.assertTrue(source_files)
                self.assertTrue(source_files <= exported)
                for relative in sorted(source_files):
                    with self.subTest(artifact=relative):
                        rule = matching_rule(manifest.rules, relative)
                        self.assertEqual(RuleKind.MERGE_REQUIRED, rule.kind)
                        self.assertTrue(rule.source_required)

    @unittest.skipUnless(has_source_template_support_files(ROOT), "requires source-template support files")
    def test_readme_uses_the_actual_cli_contract_and_retains_safety_caveats(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn(CLI_PATH, readme)
        invocations = self.assert_invocations_follow_parser(readme)
        self.assertEqual(
            {"inspect", "plan", "resolve", "apply", "verify", "rollback"},
            {parsed.command for _, parsed in invocations},
        )

        plan_options = [
            {argument for argument in arguments if argument.startswith("--")}
            for arguments, parsed in invocations if parsed.command == "plan"
        ]
        self.assertTrue(any("--developer" in options for options in plan_options))
        self.assertTrue(any("--developer" not in options for options in plan_options))

        for relative in PRESERVED_ROOTS[:-1]:
            with self.subTest(preserved=relative):
                self.assertIn(relative, readme)
        self.assertIn("runtime state", readme)
        self.assertIn("external backup", readme)
        self.assertIn("trellis update --dry-run", readme)
        self.assertIn("trellis platforms --json", readme)
        self.assertIn("`trellis-meta` platform/customization guidance", readme)
        self.assertIn("`--profile agent-workflow`", readme)
        self.assertIn("schema-6 plan", readme)
        self.assertIn("valid `project_local` content", readme)
        self.assertIn("never selects or rewrites", readme)
        for excluded_runtime in (
            "Copier-style answers", "render Jinja", "Git template tags",
            "template-provided tasks or migrations",
        ):
            with self.subTest(excluded_runtime=excluded_runtime):
                self.assertIn(excluded_runtime, readme)
        self.assertIn(SIDECAR_SUFFIX, readme)
        self.assertIn("incomplete", readme)
        self.assertIn("rollback", readme.lower())
        self.assertTrue(any("trellis update --dry-run" == " ".join(command) for command in VERIFICATION_COMMANDS))

        codex_config = (ROOT / ".codex" / "config.toml").read_text(encoding="utf-8")
        for setting in ("sandbox_mode", "approval_policy"):
            with self.subTest(setting=setting):
                value = re.search(rf"^{setting}\s*=\s*(.+)$", codex_config, re.MULTILINE)
                self.assertIsNotNone(value)
                self.assertIn(value.group(1).strip().strip('"'), readme)
        for legacy in ("Copy-Item", "Remove-Item", "$replaceDirs"):
            with self.subTest(legacy=legacy):
                self.assertNotIn(legacy, readme)


if __name__ == "__main__":
    unittest.main()
