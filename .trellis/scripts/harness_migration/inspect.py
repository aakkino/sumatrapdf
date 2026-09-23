from __future__ import annotations

import re
import tomllib
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Any

from .codec import digest_path, is_link_like, read_json
from .manifest import (
    exported_files,
    load_manifest,
)
from .models import (
    DISPATCH_ROUTE_TABLES,
    MigrationError,
    ROUTE_CATALOG,
    ROUTE_FIELDS,
    ROUTE_TABLES,
    ROUTE_TARGETS,
)
from .safety import contained_path, resolve_directory


_ROOT_FIELDS = ("model", "model_reasoning_effort")
_AGENTS_FIELDS = ("default_subagent_model", "default_subagent_reasoning_effort")
_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_AREA_DIRECTORIES = (
    (".agents/skills/", "skills"),
    (".codex/skills/", "skills"),
    (".codex/agents/", "agents"),
    (".trellis/agents/", "agents"),
    (".trellis/workflows/", "workflow"),
    (".codex/hooks/", "hooks"),
    (".trellis/scripts/", "scripts"),
    (".trellis/spec/", "specs"),
    (".trellis/tests/", "tests"),
    (".trellis/tasks/", "tasks"),
    (".trellis/workspace/", "workspace"),
)
_AREA_FILES = {
    ".codex/hooks.json": "hooks",
    ".trellis/workflow.md": "workflow",
    "AGENTS.md": "workflow",
}


def _normalized_relative(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\0" in value
        or ":" in value
        or "*" in value
        or "?" in value
    ):
        raise MigrationError(f"invalid template hash path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value in {".", ".."} or path.as_posix() != value:
        raise MigrationError(f"template hash path must be normalized and relative: {value}")
    return value


def _contained_inspection_path(
    template: Path,
    relative: str,
    *,
    allow_missing: bool = True,
) -> Path:
    try:
        return contained_path(template, relative, allow_missing=allow_missing)
    except MigrationError as exc:
        raise MigrationError(str(exc)) from exc


def _regular_metadata_file(template: Path, relative: str) -> Path:
    path = _contained_inspection_path(template, relative, allow_missing=False)
    if is_link_like(path) or not path.is_file():
        raise MigrationError(f"template metadata must be a regular file: {relative}")
    return path


def _template_hashes(template: Path) -> dict[str, str]:
    value = read_json(_regular_metadata_file(template, ".trellis/.template-hashes.json"))
    if (
        set(value) != {"__version", "hashes"}
        or type(value.get("__version")) is not int
        or value["__version"] != 2
    ):
        raise MigrationError("template hashes require schema 2 with only __version and hashes")
    hashes = value.get("hashes")
    if not isinstance(hashes, dict):
        raise MigrationError("template hashes must contain a hashes object")
    normalized: dict[str, str] = {}
    for raw_path, raw_digest in hashes.items():
        relative = _normalized_relative(raw_path)
        if not isinstance(raw_digest, str) or not _HASH_PATTERN.fullmatch(raw_digest):
            raise MigrationError(f"invalid template hash digest for {relative}")
        path = _contained_inspection_path(template, relative)
        if is_link_like(path) or path.exists() and not path.is_file():
            raise MigrationError(f"template hash path must be a regular file when present: {relative}")
        if relative in normalized:
            raise MigrationError(f"duplicate template hash path: {relative}")
        normalized[relative] = raw_digest
    return normalized


def _area(relative: str) -> str:
    if relative in _AREA_FILES:
        return _AREA_FILES[relative]
    for prefix, area in _AREA_DIRECTORIES:
        if relative.startswith(prefix):
            return area
    if relative.startswith((".codex/", ".trellis/")):
        return "configuration"
    return "support"


def _platform(relative: str) -> str:
    if relative.startswith(".codex/"):
        return "codex"
    if relative.startswith(".agents/"):
        return "shared"
    if relative.startswith(".trellis/") or relative == "AGENTS.md":
        return "trellis"
    return "harness"


def _source_digest(template: Path, relative: str) -> tuple[str, str | None]:
    path = _contained_inspection_path(template, relative)
    if not path.exists() and not is_link_like(path):
        return "missing", None
    if is_link_like(path) or not path.is_file():
        raise MigrationError(f"exported source must be a regular file: {relative}")
    return "present", digest_path(path)


def inspect_template(template_value: str, profile: str | None = None) -> dict[str, Any]:
    """Describe manifest-selected template files without target admission or writes."""
    template = _inspection_target(template_value, label="template")
    _regular_metadata_file(template, "export-manifest.json")
    hashes = _template_hashes(template)
    manifest = load_manifest(
        template,
        additional_exported_paths=tuple(hashes),
    )
    if profile is not None and profile not in manifest.profiles:
        raise MigrationError(f"unknown migration profile: {profile}")

    selected_profile = profile or "complete"
    additional_paths = tuple(hashes)
    selected = set(exported_files(
        template,
        manifest,
        selected_profile,
        additional_exported_paths=additional_paths,
    ))

    memberships = {
        name: set(exported_files(
            template,
            manifest,
            name,
            additional_exported_paths=additional_paths,
        ))
        for name in sorted(manifest.profiles)
    }

    records: list[dict[str, Any]] = []
    for relative in sorted(selected):
        presence, current_digest = _source_digest(template, relative)
        baseline = hashes.get(relative)
        if baseline is None:
            provenance = "project_local"
            status = "project_local"
            baseline_digest = None
        else:
            provenance = "trellis_managed"
            baseline_digest = "sha256:" + baseline
            if presence == "missing":
                status = "official_missing"
            elif current_digest == baseline_digest:
                status = "official_unchanged"
            else:
                status = "official_modified"
        records.append({
            "area": _area(relative),
            "baselineDigest": baseline_digest,
            "currentDigest": current_digest,
            "path": relative,
            "platform": _platform(relative),
            "presence": presence,
            "profiles": [name for name in sorted(memberships) if relative in memberships[name]],
            "provenance": provenance,
            "status": status,
        })

    counts = Counter(record["area"] for record in records)
    areas = [{"area": area, "fileCount": counts[area]} for area in sorted(counts)]
    return {
        "schemaVersion": 1,
        "templateRoot": str(template),
        "profile": profile,
        "areas": areas,
        "files": records,
    }


def _inspection_target(target_value: str, *, label: str = "target") -> Path:
    """Resolve an observational root without applying migration admission rules."""
    try:
        return resolve_directory(target_value, label)
    except MigrationError as exc:
        # An inspect-only invocation has no blocked target state: an unusable
        # root is simply invalid command input.
        raise MigrationError(str(exc)) from exc


def _load_document(target: Path, relative: str) -> tuple[dict[str, Any] | None, str | None, str | None]:
    """Return a parsed route file or its observed status/detail."""
    try:
        path = contained_path(target, relative)
    except MigrationError:
        return None, "invalid", "unsafe_path"
    if not path.exists():
        return None, "missing", "missing_file"
    if not path.is_file():
        return None, "invalid", "not_regular_file"
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return None, "invalid", "non_utf8_toml"
    except OSError:
        return None, "invalid", "unreadable_file"
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return None, "invalid", "malformed_toml"
    return document, None, None


def _has_field_outside_table(
    document: dict[str, Any],
    field: str,
    expected_table: tuple[str, ...],
    allowed_tables: frozenset[tuple[str, ...]] = frozenset(),
) -> bool:
    def visit(value: dict[str, Any], table: tuple[str, ...]) -> bool:
        for key, item in value.items():
            if key == field and table != expected_table and table not in allowed_tables:
                return True
            if isinstance(item, dict) and visit(item, (*table, key)):
                return True
        return False

    return visit(document, ())


def _missing_detail(fields: tuple[str, str], values: dict[str, Any]) -> str:
    missing = [field for field in fields if field not in values]
    if len(missing) == 2:
        return "missing_model_and_effort"
    return "missing_model" if missing[0].endswith("model") else "missing_effort"


def _field_values(scope: str, document: dict[str, Any]) -> tuple[dict[str, Any] | None, tuple[str, str], tuple[str, ...], str | None]:
    table = ROUTE_TABLES[scope]
    values: Any = document
    for part in table:
        if not isinstance(values, dict):
            return None, ROUTE_FIELDS[scope], table, "invalid_table"
        values = values.get(part)
        if values is None:
            return {}, ROUTE_FIELDS[scope], table, None
    if not isinstance(values, dict):
        return None, ROUTE_FIELDS[scope], table, "invalid_table"
    return values, ROUTE_FIELDS[scope], table, None


def _route_entry(scope: str, relative: str, document: dict[str, Any] | None, file_status: str | None, file_detail: str | None) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "scope": scope,
        "path": relative,
        "status": file_status or "missing",
        "route": None,
        "model": None,
        "effort": None,
        "detail": file_detail,
    }
    if scope.startswith("dispatch:"):
        entry["table"] = ".".join(ROUTE_TABLES[scope])
    if document is None:
        return entry

    values, fields, table, table_detail = _field_values(scope, document)
    if table_detail is not None:
        entry.update(status="invalid", detail=table_detail)
        return entry
    assert values is not None
    model_field, effort_field = fields
    model = values.get(model_field)
    effort = values.get(effort_field)
    entry["model"] = model if isinstance(model, str) else None
    entry["effort"] = effort if isinstance(effort, str) else None

    allowed_tables = DISPATCH_ROUTE_TABLES if scope.startswith("dispatch:") else frozenset()
    wrong_table = any(
        field not in values and _has_field_outside_table(document, field, table, allowed_tables)
        for field in fields
    )
    if wrong_table:
        entry.update(status="invalid", detail="wrong_table")
        return entry
    if model_field in values and not isinstance(model, str):
        entry.update(status="invalid", detail="model_not_string")
        return entry
    if effort_field in values and not isinstance(effort, str):
        entry.update(status="invalid", detail="effort_not_string")
        return entry
    if model_field not in values or effort_field not in values:
        entry.update(status="missing", detail=_missing_detail(fields, values))
        return entry

    for route, pair in ROUTE_CATALOG[scope].items():
        if pair == (model, effort):
            entry.update(status="known", route=route, detail=None)
            return entry
    entry.update(status="custom", detail="uncatalogued_pair")
    return entry


def inspect_routes(target_value: str) -> dict[str, Any]:
    """Inspect every persistent route without mutating or admitting the target."""
    target = _inspection_target(target_value)
    documents: dict[str, tuple[dict[str, Any] | None, str | None, str | None]] = {}
    routes: list[dict[str, Any]] = []
    for scope in ROUTE_CATALOG:
        relative = ROUTE_TARGETS[scope]
        if relative not in documents:
            documents[relative] = _load_document(target, relative)
        document, file_status, file_detail = documents[relative]
        routes.append(_route_entry(scope, relative, document, file_status, file_detail))
    return {"targetRoot": str(target), "routes": routes}
