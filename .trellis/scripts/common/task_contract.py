"""Machine-checked planning contracts and execution evidence for Trellis tasks.

The task documents remain the human-facing source of intent. This module only
validates their small JSON contracts and records the state needed to protect
pre-existing work during implementation and final readiness review.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from .git import run_git
from .io import read_json, write_json


SCHEMA_VERSION = 1
BASELINE_FILE = "baseline.json"
CANDIDATE_FILE = "candidate.json"
EVIDENCE_FILE = "evidence.jsonl"
_PLACEHOLDER_RE = re.compile(r"\b(?:TBD|TODO)\b|<[^>\r\n]+>", re.IGNORECASE)
_JSON_FENCE_RE = re.compile(r"(?ms)^```json\s*\r?\n(.*?)^```\s*$")

_REQUIRED_SECTIONS: dict[str, tuple[str, ...]] = {
    "prd.md": ("Goal", "Requirements", "Acceptance Criteria"),
    "design.md": ("Architecture", "Lifecycle and State", "Compatibility and Ownership"),
    "implement.md": ("Contract", "Validation Plan"),
    "check.md": ("Machine Contract", "Audit Matrix", "Paired Check Procedure", "Final Gate Procedure"),
}


def _heading_exists(content: str, heading: str) -> bool:
    if heading == "Paired Check Procedure":
        return bool(
            re.search(r"(?m)^##\s+Paired (?:Check|Checker) Procedure\s*$", content)
        )
    return bool(re.search(rf"(?m)^##\s+{re.escape(heading)}\s*$", content))


def _read_markdown(task_dir: Path, filename: str, errors: list[str]) -> str | None:
    path = task_dir / filename
    if not path.is_file():
        errors.append(f"{filename}: required file is missing")
        return None
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        errors.append(f"{filename}: cannot read file ({exc})")
        return None
    if _PLACEHOLDER_RE.search(content):
        errors.append(f"{filename}: unresolved placeholder marker")
    for heading in _REQUIRED_SECTIONS[filename]:
        if not _heading_exists(content, heading):
            errors.append(f"{filename}: missing required section '{heading}'")
    return content


def _parse_json_contract(
    filename: str, content: str | None, errors: list[str]
) -> dict[str, Any] | None:
    if content is None:
        return None
    blocks = _JSON_FENCE_RE.findall(content)
    if len(blocks) != 1:
        errors.append(f"{filename}: requires exactly one fenced json object")
        return None
    try:
        value = json.loads(blocks[0])
    except json.JSONDecodeError as exc:
        errors.append(f"{filename}: invalid JSON contract ({exc.msg})")
        return None
    if not isinstance(value, dict):
        errors.append(f"{filename}: JSON contract must be an object")
        return None
    return value


def _is_string_list(value: Any, *, nonempty: bool = False) -> bool:
    return (
        isinstance(value, list)
        and (bool(value) or not nonempty)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def _validate_implement_contract(contract: dict[str, Any], errors: list[str]) -> None:
    if contract.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("implement.md: schemaVersion must be 1")
    forbidden = contract.get("forbiddenVerification")
    required_forbidden = {"test", "lint", "typecheck", "build"}
    if not _is_string_list(forbidden) or not required_forbidden.issubset(set(forbidden)):
        errors.append("implement.md: forbiddenVerification must include test, lint, typecheck, and build")

    units = contract.get("units")
    if not isinstance(units, list) or not units:
        errors.append("implement.md: units must be a non-empty list")
        return

    seen_ids: set[str] = set()
    required_lists = {
        "dependsOn": False,
        "ownedPaths": True,
        "actions": True,
        "forbiddenPaths": False,
        "allowedGenerators": False,
        "acceptanceCriteria": True,
        "stopConditions": True,
    }
    for index, unit in enumerate(units, start=1):
        prefix = f"implement.md: units[{index}]"
        if not isinstance(unit, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        unit_id = unit.get("id")
        if not isinstance(unit_id, str) or not unit_id.strip():
            errors.append(f"{prefix}: id must be a non-empty string")
        elif unit_id in seen_ids:
            errors.append(f"{prefix}: duplicate id '{unit_id}'")
        else:
            seen_ids.add(unit_id)
        for field, nonempty in required_lists.items():
            if not _is_string_list(unit.get(field), nonempty=nonempty):
                suffix = "non-empty " if nonempty else ""
                errors.append(f"{prefix}: {field} must be a {suffix}list of strings")
        dependencies = unit.get("dependsOn")
        if _is_string_list(dependencies) and any(dep == unit_id for dep in dependencies):
            errors.append(f"{prefix}: dependsOn cannot include its own id")

    for unit in units:
        if not isinstance(unit, dict):
            continue
        for dependency in unit.get("dependsOn", []):
            if isinstance(dependency, str) and dependency not in seen_ids:
                errors.append(f"implement.md: unknown unit dependency '{dependency}'")


def _validate_command(command: Any, prefix: str, errors: list[str]) -> None:
    if not isinstance(command, dict):
        errors.append(f"{prefix}: must be an object")
        return
    if not isinstance(command.get("id"), str) or not command["id"].strip():
        errors.append(f"{prefix}: id must be a non-empty string")
    if not _is_string_list(command.get("argv"), nonempty=True):
        errors.append(f"{prefix}: argv must be a non-empty string array")
    if command.get("tier") not in {"T0", "T1", "T2", "T3"}:
        errors.append(f"{prefix}: tier must be T0, T1, T2, or T3")
    if not _is_string_list(command.get("invalidatedBy")):
        errors.append(f"{prefix}: invalidatedBy must be a string array")
    max_runs = command.get("maxRuns")
    if not isinstance(max_runs, int) or isinstance(max_runs, bool) or max_runs < 1:
        errors.append(f"{prefix}: maxRuns must be an integer of at least 1")


def _validate_check_contract(contract: dict[str, Any], errors: list[str]) -> None:
    if contract.get("schemaVersion") != SCHEMA_VERSION:
        errors.append("check.md: schemaVersion must be 1")
    if contract.get("protectedBaseline") != BASELINE_FILE:
        errors.append("check.md: protectedBaseline must be baseline.json")

    self_fix = contract.get("selfFix")
    if not isinstance(self_fix, dict):
        errors.append("check.md: selfFix must be an object")
    else:
        if not _is_string_list(self_fix.get("allowedPaths"), nonempty=True):
            errors.append("check.md: selfFix.allowedPaths must be a non-empty string array")
        if not _is_string_list(self_fix.get("allowedIssueClasses"), nonempty=True):
            errors.append("check.md: selfFix.allowedIssueClasses must be a non-empty string array")
        rounds = self_fix.get("maxRounds")
        if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 0:
            errors.append("check.md: selfFix.maxRounds must be a non-negative integer")

    for stage in ("paired", "finalGate"):
        budget = contract.get(stage)
        if not isinstance(budget, dict):
            errors.append(f"check.md: {stage} must be an object")
            continue
        if budget.get("maxTier") not in {"T0", "T1", "T2", "T3"}:
            errors.append(f"check.md: {stage}.maxTier must be T0, T1, T2, or T3")
        commands = budget.get("commands")
        if not isinstance(commands, list):
            errors.append(f"check.md: {stage}.commands must be an array")
            continue
        seen_ids: set[str] = set()
        for index, command in enumerate(commands, start=1):
            _validate_command(command, f"check.md: {stage}.commands[{index}]", errors)
            if isinstance(command, dict) and isinstance(command.get("id"), str):
                command_id = command["id"]
                if command_id in seen_ids:
                    errors.append(f"check.md: {stage}.commands has duplicate id '{command_id}'")
                seen_ids.add(command_id)


def _task_relative(task_dir: Path, repo_root: Path) -> str:
    try:
        return task_dir.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return ""


def _validate_manifests(task_dir: Path, repo_root: Path, errors: list[str]) -> None:
    for filename in ("implement.jsonl", "check.jsonl"):
        path = task_dir / filename
        if not path.is_file():
            errors.append(f"{filename}: required context manifest is missing")
            continue
        real_entries = 0
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            errors.append(f"{filename}: cannot read file ({exc})")
            continue
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"{filename}:{line_number}: invalid JSON")
                continue
            if not isinstance(entry, dict):
                errors.append(f"{filename}:{line_number}: manifest entry must be an object")
                continue
            file_value = entry.get("file")
            if file_value is None:
                continue
            if not isinstance(file_value, str) or not file_value.strip():
                errors.append(f"{filename}:{line_number}: file must be a non-empty string")
                continue
            candidate = (repo_root / file_value).resolve()
            try:
                candidate.relative_to(repo_root.resolve())
            except ValueError:
                errors.append(f"{filename}:{line_number}: file must remain inside the repository")
                continue
            entry_type = entry.get("type", "file")
            if entry_type not in {"file", "directory"}:
                errors.append(f"{filename}:{line_number}: type must be file or directory")
                continue
            if entry_type == "directory" and not candidate.is_dir():
                errors.append(f"{filename}:{line_number}: directory not found: {file_value}")
                continue
            if entry_type == "file" and not candidate.is_file():
                errors.append(f"{filename}:{line_number}: file not found: {file_value}")
                continue
            real_entries += 1
        if real_entries == 0:
            errors.append(f"{filename}: requires at least one curated file or directory entry")


def validate_task_contract(task_dir: Path, repo_root: Path) -> list[str]:
    """Return deterministic errors for all documents and context manifests."""
    errors: list[str] = []
    artifacts = {
        filename: _read_markdown(task_dir, filename, errors)
        for filename in _REQUIRED_SECTIONS
    }
    implement_contract = _parse_json_contract("implement.md", artifacts["implement.md"], errors)
    check_contract = _parse_json_contract("check.md", artifacts["check.md"], errors)
    if implement_contract is not None:
        _validate_implement_contract(implement_contract, errors)
    if check_contract is not None:
        _validate_check_contract(check_contract, errors)
    _validate_manifests(task_dir, repo_root, errors)
    return errors


def load_machine_contracts(task_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load already-validated implement and check contracts for runtime use."""
    contracts: list[dict[str, Any]] = []
    for filename in ("implement.md", "check.md"):
        content = (task_dir / filename).read_text(encoding="utf-8")
        blocks = _JSON_FENCE_RE.findall(content)
        if len(blocks) != 1:
            raise ValueError(f"{filename} has no unique JSON contract")
        value = json.loads(blocks[0])
        if not isinstance(value, dict):
            raise ValueError(f"{filename} JSON contract is not an object")
        contracts.append(value)
    return contracts[0], contracts[1]


def _sha256_path(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _head_identity(repo_root: Path) -> str:
    code, stdout, _ = run_git(["rev-parse", "HEAD"], cwd=repo_root)
    return stdout.strip() if code == 0 else ""


def _matches_exclusion(path: str, exclusions: tuple[str, ...]) -> bool:
    return any(path == prefix.rstrip("/") or path.startswith(prefix.rstrip("/") + "/") for prefix in exclusions)


def git_status_records(repo_root: Path, *, exclusions: tuple[str, ...] = ()) -> list[dict[str, str | None]]:
    """Return stable content-aware porcelain records without invoking a shell."""
    code, stdout, stderr = run_git(
        ["status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=repo_root
    )
    if code != 0:
        raise RuntimeError(f"git status failed: {stderr.strip()}")
    items = stdout.split("\0")
    records: list[dict[str, str | None]] = []
    index = 0
    while index < len(items):
        item = items[index]
        index += 1
        if not item:
            continue
        status = item[:2]
        path = item[3:].replace("\\", "/")
        if status[:1] in {"R", "C"} or status[1:2] in {"R", "C"}:
            index += 1
        if not path or _matches_exclusion(path, exclusions):
            continue
        records.append(
            {"path": path, "status": status, "sha256": _sha256_path(repo_root / path)}
        )
    return sorted(records, key=lambda record: str(record["path"]))


def capture_baseline(task_dir: Path, repo_root: Path) -> list[str]:
    """Capture protected pre-existing changes once planning has been accepted."""
    baseline_path = task_dir / BASELINE_FILE
    if baseline_path.exists():
        return []
    task_relative = _task_relative(task_dir, repo_root)
    exclusions = tuple(prefix for prefix in (task_relative, ".trellis/.runtime") if prefix)
    try:
        records = git_status_records(repo_root, exclusions=exclusions)
    except RuntimeError as exc:
        return [str(exc)]
    implement_contract, _ = load_machine_contracts(task_dir)
    for record in records:
        path = str(record["path"])
        for unit in implement_contract["units"]:
            if any(_path_matches(path, pattern) for pattern in unit["ownedPaths"]):
                return [
                    f"baseline-dirty path overlaps unit '{unit['id']}' ownership: {path}"
                ]
    payload: dict[str, Any] = {
        "schemaVersion": SCHEMA_VERSION,
        "head": _head_identity(repo_root),
        "paths": records,
    }
    if not write_json(baseline_path, payload):
        return [f"{BASELINE_FILE}: could not write baseline"]
    return []


def _read_baseline(task_dir: Path) -> tuple[dict[str, Any] | None, list[str]]:
    baseline = read_json(task_dir / BASELINE_FILE)
    if not isinstance(baseline, dict):
        return None, [f"{BASELINE_FILE}: missing or invalid"]
    paths = baseline.get("paths")
    if baseline.get("schemaVersion") != SCHEMA_VERSION or not isinstance(paths, list):
        return None, [f"{BASELINE_FILE}: unsupported schema"]
    for entry in paths:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            return None, [f"{BASELINE_FILE}: invalid path record"]
    return baseline, []


def validate_protected_baseline(task_dir: Path, repo_root: Path) -> list[str]:
    """Return every baseline-dirty path whose status or content changed."""
    baseline, errors = _read_baseline(task_dir)
    if errors or baseline is None:
        return errors
    current = {str(record["path"]): record for record in git_status_records(repo_root)}
    for entry in baseline["paths"]:
        original = {key: entry.get(key) for key in ("path", "status", "sha256")}
        now = current.get(str(entry["path"]))
        if now != original:
            errors.append(f"protected baseline changed: {entry['path']}")
    return errors


def _path_matches(path: str, pattern: str) -> bool:
    normalized = pattern.replace("\\", "/").lstrip("./")
    if normalized.endswith("/**") and path.startswith(normalized[:-3].rstrip("/") + "/"):
        return True
    return fnmatch.fnmatchcase(path, normalized)


def validate_unit_ownership(task_dir: Path, repo_root: Path, unit_id: str) -> list[str]:
    """Ensure current task changes are constrained to one reviewed unit."""
    errors = validate_task_contract(task_dir, repo_root)
    if errors:
        return errors
    implement_contract, _ = load_machine_contracts(task_dir)
    unit = next((item for item in implement_contract["units"] if item["id"] == unit_id), None)
    if unit is None:
        return [f"implement.md: unknown unit '{unit_id}'"]
    units_by_id = {item["id"]: item for item in implement_contract["units"]}
    allowed_unit_ids = {unit_id}
    pending = list(unit["dependsOn"])
    while pending:
        dependency = pending.pop()
        if dependency in allowed_unit_ids:
            continue
        allowed_unit_ids.add(dependency)
        pending.extend(units_by_id[dependency]["dependsOn"])
    allowed_patterns = [
        pattern
        for allowed_id in allowed_unit_ids
        for pattern in units_by_id[allowed_id]["ownedPaths"]
    ]
    baseline, baseline_errors = _read_baseline(task_dir)
    if baseline_errors or baseline is None:
        return baseline_errors
    protected_paths = {str(item["path"]) for item in baseline["paths"]}
    task_relative = _task_relative(task_dir, repo_root)
    exclusions = tuple(prefix for prefix in (task_relative, ".trellis/.runtime") if prefix)
    for record in git_status_records(repo_root, exclusions=exclusions):
        path = str(record["path"])
        if path in protected_paths:
            continue
        if not any(_path_matches(path, pattern) for pattern in allowed_patterns):
            errors.append(f"out-of-ownership change for unit '{unit_id}': {path}")
    return errors


def candidate_digest(task_dir: Path, repo_root: Path) -> str:
    """Hash the candidate tree while excluding runtime and task-stage evidence."""
    task_relative = _task_relative(task_dir, repo_root)
    evidence_paths = tuple(
        f"{task_relative}/{filename}"
        for filename in (BASELINE_FILE, CANDIDATE_FILE, EVIDENCE_FILE)
        if task_relative
    )
    payload = {
        "head": _head_identity(repo_root),
        "paths": git_status_records(repo_root, exclusions=(".trellis/.runtime", *evidence_paths)),
    }
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def freeze_candidate(task_dir: Path, repo_root: Path) -> tuple[str | None, list[str]]:
    errors = validate_protected_baseline(task_dir, repo_root)
    if errors:
        return None, errors
    digest = candidate_digest(task_dir, repo_root)
    if not write_json(task_dir / CANDIDATE_FILE, {"schemaVersion": SCHEMA_VERSION, "candidateTreeHash": digest}):
        return None, [f"{CANDIDATE_FILE}: could not write candidate digest"]
    return digest, []


def _read_evidence(task_dir: Path) -> tuple[list[dict[str, Any]], list[str]]:
    path = task_dir / EVIDENCE_FILE
    if not path.is_file():
        return [], []
    evidence: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        return [], [f"{EVIDENCE_FILE}: cannot read file ({exc})"]
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            return [], [f"{EVIDENCE_FILE}:{index}: invalid JSON"]
        if not isinstance(entry, dict):
            return [], [f"{EVIDENCE_FILE}:{index}: entry must be an object"]
        evidence.append(entry)
    return evidence, []


def record_evidence(
    task_dir: Path,
    repo_root: Path,
    *,
    stage: str,
    unit_id: str,
    command_id: str,
    result: str,
) -> list[str]:
    """Record one authorized command outcome bound to the current candidate."""
    errors = validate_task_contract(task_dir, repo_root)
    if stage not in {"paired", "final"}:
        errors.append("evidence stage must be paired or final")
    if result not in {"pass", "fail"}:
        errors.append("evidence result must be pass or fail")
    if errors:
        return errors
    implement_contract, check_contract = load_machine_contracts(task_dir)
    valid_unit_ids = {unit["id"] for unit in implement_contract["units"]}
    if stage == "paired" and unit_id not in valid_unit_ids:
        return [f"implement.md: unknown unit '{unit_id}'"]
    if stage == "final" and unit_id != "final-gate":
        return ["final evidence must use unitId 'final-gate'"]
    stage_errors = validate_protected_baseline(task_dir, repo_root)
    if stage == "paired":
        stage_errors.extend(validate_unit_ownership(task_dir, repo_root, unit_id))
    if stage_errors:
        return stage_errors
    budget = check_contract["paired" if stage == "paired" else "finalGate"]
    command = next((item for item in budget["commands"] if item["id"] == command_id), None)
    if command is None:
        return [f"check.md: {stage} command '{command_id}' is not authorized"]
    evidence, evidence_errors = _read_evidence(task_dir)
    if evidence_errors:
        return evidence_errors
    prior = [
        item
        for item in evidence
        if item.get("stage") == stage
        and item.get("unitId") == unit_id
        and item.get("commandId") == command_id
    ]
    if len(prior) >= command["maxRuns"]:
        return [f"check.md: {stage} command '{command_id}' exceeded maxRuns={command['maxRuns']}"]
    record = {
        "schemaVersion": SCHEMA_VERSION,
        "stage": stage,
        "unitId": unit_id,
        "commandId": command_id,
        "result": result,
        "candidateTreeHash": candidate_digest(task_dir, repo_root),
        "runCount": len(prior) + 1,
    }
    try:
        with (task_dir / EVIDENCE_FILE).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n")
    except OSError as exc:
        return [f"{EVIDENCE_FILE}: could not write evidence ({exc})"]
    return []


def final_gate_decision(task_dir: Path, repo_root: Path) -> tuple[str, list[str]]:
    """Return a read-only final-gate decision without executing commands."""
    errors = validate_task_contract(task_dir, repo_root)
    errors.extend(validate_protected_baseline(task_dir, repo_root))
    if errors:
        return "blocked", errors
    frozen = read_json(task_dir / CANDIDATE_FILE)
    digest = candidate_digest(task_dir, repo_root)
    if not isinstance(frozen, dict) or frozen.get("candidateTreeHash") != digest:
        errors.append("candidate digest is missing or stale; freeze the current candidate first")
        return "blocked", errors
    implement_contract, check_contract = load_machine_contracts(task_dir)
    evidence, evidence_errors = _read_evidence(task_dir)
    errors.extend(evidence_errors)
    for unit in implement_contract["units"]:
        if not any(item.get("stage") == "paired" and item.get("unitId") == unit["id"] and item.get("result") == "pass" for item in evidence):
            errors.append(f"missing successful paired-check closure for unit '{unit['id']}'")
    for command in check_contract["finalGate"]["commands"]:
        if not any(
            item.get("stage") == "final"
            and item.get("commandId") == command["id"]
            and item.get("result") == "pass"
            and item.get("candidateTreeHash") == digest
            for item in evidence
        ):
            errors.append(f"missing current-candidate final evidence for '{command['id']}'")
    return ("blocked", errors) if errors else ("ready", [])
