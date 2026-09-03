from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / ".trellis" / "scripts"))

from harness_migration.cli import main as migration_main  # noqa: E402
from harness_migration.codec import digest_path  # noqa: E402
from harness_migration.inspect import _area, _platform, inspect_template  # noqa: E402
from harness_migration.manifest import exported_files, load_manifest  # noqa: E402
from harness_migration.models import ExitCode, MigrationError  # noqa: E402
from harness_migration.planner import build_plan, source_bytes  # noqa: E402
from harness_migration.release import apply_release_plan, build_release_plan  # noqa: E402


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class HarnessInspectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.template = Path(self.temporary.name) / "template"
        (self.template / "files").mkdir(parents=True)
        (self.template / ".trellis").mkdir()
        self.unchanged = b"unchanged\n"
        self.modified = b"modified now\n"
        (self.template / "files" / "unchanged.txt").write_bytes(self.unchanged)
        (self.template / "files" / "modified.txt").write_bytes(self.modified)
        (self.template / "files" / "local.txt").write_text("local\n", encoding="utf-8")
        self._write_manifest()
        self._write_hashes({
            "files/unchanged.txt": _sha256(self.unchanged),
            "files/modified.txt": _sha256(b"official old bytes\n"),
            "files/missing.txt": _sha256(b"missing official bytes\n"),
        })

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _write_manifest(self) -> None:
        manifest = {
            "schemaVersion": 2,
            "sourceVersion": "test",
            "currentSourceCopyGroups": ["files/**"],
            "migrationProfiles": {
                "complete": {"include": ["**"]},
                "focused": {"include": ["files/unchanged.txt"]},
            },
            "defaultSkeleton": {"source": "fixture", "developer": "tester", "paths": []},
            "placeholderOnly": [],
            "supportFiles": [],
            "migrationPolicy": {
                "schemaVersion": 1,
                "sourceExcludes": [],
                "migrationRules": [{
                    "path": "files/**",
                    "kind": "replaceable_managed",
                    "modes": ["fresh", "existing_trellis"],
                    "onExisting": "copy",
                    "onModified": "decision",
                    "sourceRequired": True,
                }],
            },
        }
        (self.template / "export-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def _write_hashes(self, hashes: dict[str, object], *, version: object = 2, extra: bool = False) -> None:
        value: dict[str, object] = {"__version": version, "hashes": hashes}
        if extra:
            value["extra"] = True
        (self.template / ".trellis" / ".template-hashes.json").write_text(json.dumps(value), encoding="utf-8")

    def test_complete_json_has_all_baseline_states_and_sorted_records(self) -> None:
        report = inspect_template(str(self.template))
        self.assertEqual(1, report["schemaVersion"])
        self.assertIsNone(report["profile"])
        paths = [record["path"] for record in report["files"]]
        self.assertEqual(sorted(paths), paths)
        self.assertEqual(
            ["files/local.txt", "files/missing.txt", "files/modified.txt", "files/unchanged.txt"],
            paths,
        )
        records = {record["path"]: record for record in report["files"]}
        self.assertEqual(
            {
                "area", "baselineDigest", "currentDigest", "path", "platform",
                "presence", "profiles", "provenance", "status",
            },
            set(records["files/local.txt"]),
        )
        self.assertEqual("project_local", records["files/local.txt"]["status"])
        self.assertEqual("project_local", records["files/local.txt"]["provenance"])
        self.assertEqual("harness", records["files/local.txt"]["platform"])
        self.assertIsNone(records["files/local.txt"]["baselineDigest"])
        self.assertEqual("official_missing", records["files/missing.txt"]["status"])
        self.assertEqual("missing", records["files/missing.txt"]["presence"])
        self.assertIsNone(records["files/missing.txt"]["currentDigest"])
        self.assertEqual("official_modified", records["files/modified.txt"]["status"])
        self.assertEqual("official_unchanged", records["files/unchanged.txt"]["status"])
        self.assertEqual(["complete", "focused"], records["files/unchanged.txt"]["profiles"])
        self.assertEqual([{"area": "support", "fileCount": 4}], report["areas"])

    def test_profile_uses_shared_selector_and_cli_outputs_are_deterministic(self) -> None:
        manifest = load_manifest(self.template.resolve())
        expected = exported_files(self.template.resolve(), manifest, "focused")
        report = inspect_template(str(self.template), "focused")
        self.assertEqual(expected, [record["path"] for record in report["files"]])

        for profile_arguments, expected_profile in (([], None), (["--profile", "focused"], "focused")):
            outputs: list[str] = []
            for output_format in ("json", "human"):
                first = StringIO()
                second = StringIO()
                arguments = [
                    "inspect", "--template", str(self.template),
                    *profile_arguments, "--format", output_format,
                ]
                with redirect_stdout(first):
                    first_code = migration_main(arguments)
                with redirect_stdout(second):
                    second_code = migration_main(arguments)
                self.assertEqual(ExitCode.OK, first_code)
                self.assertEqual(ExitCode.OK, second_code)
                self.assertEqual(first.getvalue(), second.getvalue())
                outputs.append(first.getvalue())
            self.assertEqual(expected_profile, json.loads(outputs[0])["profile"])
            self.assertIn("files/unchanged.txt: official_unchanged", outputs[1])

    def test_exact_declared_official_missing_path_remains_inspectable_and_profile_filtered(self) -> None:
        manifest_path = self.template / "export-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["currentSourceCopyGroups"].append("files/exact-missing.txt")
        manifest["migrationProfiles"]["missing-only"] = {
            "include": ["files/exact-missing.txt"],
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        hashes_path = self.template / ".trellis" / ".template-hashes.json"
        hashes = json.loads(hashes_path.read_text(encoding="utf-8"))["hashes"]
        hashes["files/exact-missing.txt"] = _sha256(b"official exact bytes\n")
        self._write_hashes(hashes)

        report = inspect_template(str(self.template), "missing-only")
        loaded = load_manifest(
            self.template.resolve(),
            additional_exported_paths=tuple(hashes),
        )
        expected = exported_files(
            self.template.resolve(),
            loaded,
            "missing-only",
            additional_exported_paths=tuple(hashes),
        )
        self.assertEqual(expected, [item["path"] for item in report["files"]])
        self.assertEqual(["files/exact-missing.txt"], expected)
        self.assertEqual("official_missing", report["files"][0]["status"])
        self.assertEqual(["complete", "missing-only"], report["files"][0]["profiles"])
        with self.assertRaisesRegex(MigrationError, "required exported path is missing"):
            load_manifest(self.template.resolve())

    def test_inspection_is_read_only_and_has_no_external_command_path(self) -> None:
        before = digest_path(self.template)
        with patch("harness_migration.safety.subprocess.run") as run, patch(
            "harness_migration.codec.atomic_write_json"
        ) as write:
            inspect_template(str(self.template))
        run.assert_not_called()
        write.assert_not_called()
        self.assertEqual(before, digest_path(self.template))

    def test_invalid_hash_schema_digest_and_paths_fail_closed(self) -> None:
        cases = (
            ({"files/a.txt": "A" * 64}, 2, False, "invalid template hash digest"),
            ({"../escape.txt": "0" * 64}, 2, False, "normalized and relative"),
            ({"files/a.txt": "0" * 64}, 1, False, "require schema 2"),
            ({"files/a.txt": "0" * 64}, 2.0, False, "require schema 2"),
            ({"files/a.txt": "0" * 64}, 2, True, "require schema 2"),
        )
        for hashes, version, extra, message in cases:
            with self.subTest(message=message):
                self._write_hashes(hashes, version=version, extra=extra)
                with self.assertRaisesRegex(MigrationError, message):
                    inspect_template(str(self.template))

    def test_unsafe_hash_containment_is_invalid_input(self) -> None:
        self._write_hashes({"files/unchanged.txt/child": "0" * 64})
        output = StringIO()
        error = StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = migration_main([
                "inspect", "--template", str(self.template), "--format", "json",
            ])
        self.assertEqual(ExitCode.INVALID_INPUT, code)
        self.assertIn("path parent is not a directory", error.getvalue())
        self.assertEqual(ExitCode.INVALID_INPUT, json.loads(output.getvalue())["exitCode"])

    def test_area_and_platform_classification_is_closed_and_path_aware(self) -> None:
        self.assertEqual("skills", _area(".codex/skills/.gitkeep"))
        self.assertEqual("codex", _platform(".codex/skills/.gitkeep"))
        self.assertEqual("skills", _area(".agents/skills/example/SKILL.md"))
        self.assertEqual("shared", _platform(".agents/skills/example/SKILL.md"))
        self.assertEqual("hooks", _area(".codex/hooks.json"))
        self.assertEqual("configuration", _area(".codex/hooks.json.backup"))
        self.assertEqual("workflow", _area("AGENTS.md"))
        self.assertEqual("workflow", _area(".trellis/workflows/reviewed.md"))
        self.assertEqual("support", _area("AGENTS.md.backup"))

    def test_unknown_profile_and_non_regular_source_are_invalid_input(self) -> None:
        with self.assertRaisesRegex(MigrationError, "unknown migration profile"):
            inspect_template(str(self.template), "absent")

        source = self.template / "files" / "local.txt"
        hashes_path = self.template / ".trellis" / ".template-hashes.json"
        hashes = json.loads(hashes_path.read_text(encoding="utf-8"))["hashes"]
        hashes["files/local.txt"] = _sha256(b"official local baseline\n")
        self._write_hashes(hashes)
        source.unlink()
        source.mkdir()
        error = StringIO()
        output = StringIO()
        with redirect_stdout(output), redirect_stderr(error):
            code = migration_main([
                "inspect", "--template", str(self.template), "--format", "json",
            ])
        self.assertEqual(ExitCode.INVALID_INPUT, code)
        self.assertEqual("error", json.loads(output.getvalue())["status"])

    def test_cli_contract_has_no_target_plan_or_output_surface(self) -> None:
        for forbidden in ("--target", "--plan", "--output"):
            with self.subTest(forbidden=forbidden), self.assertRaises(SystemExit) as raised:
                migration_main(["inspect", "--template", str(self.template), forbidden, "value"])
            self.assertEqual(2, raised.exception.code)


@unittest.skipUnless((ROOT / "export-manifest.json").is_file(), "requires a Harness source template")
class RealTemplateSanitationTests(unittest.TestCase):
    def test_release_projection_uses_clean_skeletons_without_changing_inspect(self) -> None:
        author_journal = ROOT / ".trellis/workspace/kino/journal-1.md"
        release_journal_asset = ROOT / ".trellis/release-assets/workspace/kino/journal-1.md"
        author_bytes = author_journal.read_bytes()
        author_digest = digest_path(author_journal)
        self.assertIn(b"## Session", author_bytes)
        self.assertIn(b"Git Commits", author_bytes)

        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            release = base / "release"
            release_plan = build_release_plan(str(ROOT), str(release))
            apply_release_plan(release_plan, str(base / "release-backup"))

            before_inspection = digest_path(release)
            report = inspect_template(str(release))
            self.assertEqual(1, report["schemaVersion"])
            self.assertIsNone(report["profile"])
            self.assertEqual(before_inspection, digest_path(release))
            self.assertEqual(
                exported_files(release, load_manifest(release), "complete"),
                [record["path"] for record in report["files"]],
            )
            self.assertTrue(all(
                set(record) == {
                    "area", "baselineDigest", "currentDigest", "path", "platform",
                    "presence", "profiles", "provenance", "status",
                }
                for record in report["files"]
            ))

            release_bytes = (release / ".trellis/workspace/kino/journal-1.md").read_bytes()
            self.assertEqual(release_journal_asset.read_bytes(), release_bytes)
            self.assertNotEqual(author_bytes, release_bytes)
            for historical_marker in (b"## Session", b"Git Commits", b"### Testing", b"Next Steps"):
                self.assertNotIn(historical_marker, release_bytes)
            self.assertEqual(author_digest, digest_path(author_journal))

            generic_specs = [
                path for path in exported_files(release, load_manifest(release), "complete")
                if path.startswith((".trellis/spec/backend/", ".trellis/spec/frontend/"))
                and path not in {
                    ".trellis/spec/backend/harness-migration.md",
                    ".trellis/spec/backend/model-routing-and-dispatch.md",
                }
            ]
            self.assertTrue(generic_specs)
            for path in generic_specs:
                content = (release / path).read_text(encoding="utf-8").lower()
                for foreign_marker in ("vue", "vite", "cloudflare", "openai", "src/app.vue", "src/lib/proxy.js"):
                    with self.subTest(path=path, foreign_marker=foreign_marker):
                        self.assertNotIn(foreign_marker, content)

            target = base / "fresh-target"
            target.mkdir()
            migration = build_plan(str(release), str(target), developer="alice")
            journal_action = next(
                action for action in migration.actions
                if action.path == ".trellis/workspace/alice/journal-1.md"
            )
            transformed = source_bytes(
                release,
                ".trellis/workspace/kino/journal-1.md",
                journal_action.path,
                "alice",
                journal_action.kind,
            )
            self.assertEqual("fresh_only_skeleton", journal_action.kind)
            self.assertEqual("copy", journal_action.operation)
            self.assertEqual("sha256:" + hashlib.sha256(transformed).hexdigest(), journal_action.source_digest)
            self.assertIn(b"kino", release_bytes)
            self.assertIn(b"alice", transformed)
            self.assertNotIn(b"kino", transformed)
            for historical_marker in (b"## Session", b"Git Commits", b"### Testing", b"Next Steps"):
                self.assertNotIn(historical_marker, transformed)
            for excluded_prefix in (
                ".trellis/tasks/09-02-sanitize-harness-template-export",
                ".trellis/tasks/archive/",
                ".trellis/release-assets/",
                ".trellis/.runtime/",
            ):
                self.assertFalse(any(
                    action.path.startswith(excluded_prefix) and action.operation != "skip"
                    for action in migration.actions
                ))


if __name__ == "__main__":
    unittest.main()
