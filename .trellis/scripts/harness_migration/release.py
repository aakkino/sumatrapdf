from __future__ import annotations

import os
import re
import shutil
import stat
import tempfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

from .codec import MISSING_DIGEST, atomic_write_json, canonical_bytes, digest_path, digest_value, is_link_like, read_json, without_digest
from .inspect import inspect_template
from .manifest import exported_files, load_manifest
from .models import ExitCode, MigrationError
from .safety import contained_path, is_relative_to, resolve_directory, resolve_recorded_directory


PROVENANCE_PATH = ".harness-release.json"
PROVENANCE_SCHEMA_VERSION = 1
PLAN_SCHEMA_VERSION = 1
RECEIPT_SCHEMA_VERSION = 1
PLAN_KEYS = {
    "schemaVersion", "kind", "authoringRoot", "releaseRoot", "manifestDigest",
    "projectionDigest", "previousProvenanceDigest", "operations", "planDigest",
}
OPERATION_KEYS = {"path", "operation", "preDigest", "postDigest"}
RECEIPT_KEYS = {
    "schemaVersion", "kind", "status", "planDigest", "authoringRoot", "releaseRoot",
    "backupRoot", "receiptPath", "releaseRootExisted", "gitDigest", "journal",
    "verification", "receiptDigest",
}
RECEIPT_OPTIONAL_KEYS = {"failure"}
JOURNAL_KEYS = {
    "path", "operation", "preDigest", "postDigest", "expectedPostDigest",
    "backupPath", "createdParents", "state",
}
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}\Z")
RECEIPT_STATUSES = {
    "prepared", "applied", "apply_failed", "verified", "verification_failed",
    "rollback_failed", "rolled_back",
}
JOURNAL_STATES = {"prepared", "applying", "applied"}


def _sha256_bytes(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()


def _is_digest(value: object, *, allow_missing: bool = False) -> bool:
    return isinstance(value, str) and (
        allow_missing and value == MISSING_DIGEST or DIGEST_PATTERN.fullmatch(value) is not None
    )


def _validate_relative_path(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\0" in value or ":" in value:
        raise MigrationError(f"{label} is not a normalized relative path", exit_code=ExitCode.BLOCKED)
    path = PurePosixPath(value)
    if path.is_absolute() or value in {".", ".."} or ".." in path.parts or path.as_posix() != value:
        raise MigrationError(f"{label} is not a normalized relative path", exit_code=ExitCode.BLOCKED)
    return value


def _validate_recorded_path(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value:
        raise MigrationError(f"{label} must be a canonical absolute path", exit_code=ExitCode.BLOCKED)
    recorded = Path(value)
    try:
        normalized = Path(os.path.abspath(recorded))
    except (OSError, ValueError) as exc:
        raise MigrationError(f"{label} must be a canonical absolute path", exit_code=ExitCode.BLOCKED) from exc
    if not recorded.is_absolute() or recorded != normalized:
        raise MigrationError(f"{label} must be a canonical absolute path", exit_code=ExitCode.BLOCKED)
    return recorded


def _validate_git_metadata(release: Path) -> None:
    git_path = release / ".git"
    if is_link_like(git_path):
        raise MigrationError("release root contains link-like .git metadata", exit_code=ExitCode.BLOCKED)
    if git_path.exists():
        digest_path(git_path)


def _resolve_output_root(value: str, label: str) -> Path:
    declared = Path(os.path.abspath(Path(value).expanduser()))
    if is_link_like(declared):
        raise MigrationError(f"{label} root must not be link-like: {declared}", exit_code=ExitCode.BLOCKED)
    if declared.exists() and not declared.is_dir():
        raise MigrationError(f"{label} root is not a directory: {declared}")
    current = declared.parent
    while not current.exists() and current != current.parent:
        current = current.parent
    if not current.is_dir() or is_link_like(current):
        raise MigrationError(f"{label} root has an unsafe parent: {declared}", exit_code=ExitCode.BLOCKED)
    try:
        if declared.resolve(strict=False) != declared:
            raise MigrationError(f"{label} root must not be link-like or rebound: {declared}", exit_code=ExitCode.BLOCKED)
    except (OSError, RuntimeError) as exc:
        raise MigrationError(f"cannot resolve {label} root: {declared}: {exc}", exit_code=ExitCode.BLOCKED) from exc
    return declared


def _validate_release_roots(authoring: Path, release: Path) -> None:
    if authoring == release or is_relative_to(authoring, release) or is_relative_to(release, authoring):
        raise MigrationError("authoring and release roots must be disjoint", exit_code=ExitCode.BLOCKED)


def _release_skeletons(authoring: Path) -> dict[str, bytes]:
    raw = read_json(authoring / "export-manifest.json")
    records = raw.get("releaseSkeletons")
    if not isinstance(records, list) or not records:
        raise MigrationError("export manifest releaseSkeletons must be a non-empty array")
    result: dict[str, bytes] = {}
    sources: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"source", "destination"}:
            raise MigrationError("release skeleton record has unknown or missing fields")
        source, destination = record.get("source"), record.get("destination")
        if not isinstance(source, str) or not isinstance(destination, str):
            raise MigrationError("release skeleton source and destination must be unique strings")
        _validate_relative_path(source, "release skeleton source")
        _validate_relative_path(destination, "release skeleton destination")
        if source in sources or destination in result:
            raise MigrationError("release skeleton source and destination must be unique strings")
        sources.add(source)
        source_path = contained_path(authoring, source, allow_missing=False)
        if is_link_like(source_path) or not source_path.is_file():
            raise MigrationError(f"release skeleton source is not a regular file: {source}")
        result[destination] = source_path.read_bytes()
    return result


def _provenance(manifest_digest: str, template_version: str, payload: dict[str, bytes]) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schemaVersion": PROVENANCE_SCHEMA_VERSION,
        "kind": "harness-release-provenance",
        "templateVersion": template_version,
        "manifestDigest": manifest_digest,
        "payload": [
            {"path": path, "digest": _sha256_bytes(data)} for path, data in sorted(payload.items())
        ],
        "projectionDigest": "",
    }
    value["projectionDigest"] = digest_value(without_digest(value, "projectionDigest"))
    return value


def _projection(authoring: Path) -> tuple[dict[str, bytes], dict[str, Any]]:
    manifest = load_manifest(authoring)
    skeletons = _release_skeletons(authoring)
    selected = exported_files(authoring, manifest, "complete")
    unknown_destinations = sorted(set(skeletons) - set(selected))
    if unknown_destinations:
        raise MigrationError("release skeleton destination is not in complete profile: " + ", ".join(unknown_destinations))
    payload: dict[str, bytes] = {}
    for relative in selected:
        if relative in skeletons:
            payload[relative] = skeletons[relative]
            continue
        source = contained_path(authoring, relative, allow_missing=False)
        if is_link_like(source) or not source.is_file():
            raise MigrationError(f"release payload source is not a regular file: {relative}")
        payload[relative] = source.read_bytes()
    provenance = _provenance(manifest.digest, manifest.template_version, payload)
    with tempfile.TemporaryDirectory(prefix="harness-release-stage-") as temporary:
        stage = Path(temporary)
        for relative, data in payload.items():
            destination = contained_path(stage, relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        atomic_write_json(stage / PROVENANCE_PATH, provenance)
        report = inspect_template(str(stage))
        if [item["path"] for item in report["files"]] != selected:
            raise MigrationError("staged release inspection does not match complete profile")
    return payload, provenance


def validate_release_provenance(root: Path) -> dict[str, Any]:
    path = contained_path(root, PROVENANCE_PATH, allow_missing=False)
    value = read_json(path)
    if set(value) != {"schemaVersion", "kind", "templateVersion", "manifestDigest", "payload", "projectionDigest"}:
        raise MigrationError("release provenance has unknown or missing fields", exit_code=ExitCode.BLOCKED)
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != PROVENANCE_SCHEMA_VERSION or value["kind"] != "harness-release-provenance":
        raise MigrationError("release provenance schema or kind is invalid", exit_code=ExitCode.BLOCKED)
    if not isinstance(value["templateVersion"], str) or not value["templateVersion"]:
        raise MigrationError("release provenance identity is invalid", exit_code=ExitCode.BLOCKED)
    if not _is_digest(value["manifestDigest"]) or not _is_digest(value["projectionDigest"]):
        raise MigrationError("release provenance identity digests are invalid", exit_code=ExitCode.BLOCKED)
    payload = value["payload"]
    if not isinstance(payload, list) or not payload:
        raise MigrationError("release provenance payload must be non-empty", exit_code=ExitCode.BLOCKED)
    paths: list[str] = []
    for item in payload:
        if not isinstance(item, dict) or set(item) != {"path", "digest"}:
            raise MigrationError("release provenance payload record is invalid", exit_code=ExitCode.BLOCKED)
        relative = _validate_relative_path(item["path"], "release provenance payload path")
        if not _is_digest(item["digest"]):
            raise MigrationError("release provenance payload digest is invalid", exit_code=ExitCode.BLOCKED)
        paths.append(relative)
        if digest_path(contained_path(root, relative, allow_missing=False)) != item["digest"]:
            raise MigrationError(f"release-owned content drifted: {relative}", exit_code=ExitCode.BLOCKED)
    if paths != sorted(set(paths)):
        raise MigrationError("release provenance payload paths must be unique and sorted", exit_code=ExitCode.BLOCKED)
    if value["projectionDigest"] != digest_value(without_digest(value, "projectionDigest")):
        raise MigrationError("release provenance digest is invalid", exit_code=ExitCode.BLOCKED)
    allowed_files = set(paths) | {PROVENANCE_PATH}
    allowed_directories = {"."}
    for relative in allowed_files:
        parent = Path(relative).parent
        while parent.as_posix() not in {".", ""}:
            allowed_directories.add(parent.as_posix())
            parent = parent.parent
    try:
        for entry in root.rglob("*"):
            relative = entry.relative_to(root).as_posix()
            if is_link_like(entry):
                raise MigrationError(f"release root contains a link-like entry: {relative}", exit_code=ExitCode.BLOCKED)
            metadata = entry.lstat()
            if not stat.S_ISREG(metadata.st_mode) and not stat.S_ISDIR(metadata.st_mode):
                raise MigrationError(f"release root contains unsupported content: {relative}", exit_code=ExitCode.BLOCKED)
            if relative == ".git" or relative.startswith(".git/"):
                continue
            if stat.S_ISREG(metadata.st_mode) and relative not in allowed_files:
                raise MigrationError(f"release root contains unexpected content: {relative}", exit_code=ExitCode.BLOCKED)
            if stat.S_ISDIR(metadata.st_mode) and relative not in allowed_directories:
                raise MigrationError(f"release root contains unexpected content: {relative}", exit_code=ExitCode.BLOCKED)
    except OSError as exc:
        raise MigrationError(f"cannot inspect release root: {exc}", exit_code=ExitCode.BLOCKED) from exc
    manifest = load_manifest(root)
    if manifest.digest != value["manifestDigest"] or manifest.template_version != value["templateVersion"]:
        raise MigrationError("release provenance does not match its manifest", exit_code=ExitCode.BLOCKED)
    expected_paths = exported_files(root, manifest, "complete")
    if paths != expected_paths:
        raise MigrationError("release provenance payload does not match the complete profile", exit_code=ExitCode.BLOCKED)
    return value


def _plan_digest(plan: dict[str, Any]) -> str:
    return digest_value(without_digest(plan, "planDigest"))


def build_release_plan(authoring_value: str, release_value: str) -> dict[str, Any]:
    authoring = resolve_directory(authoring_value, "authoring template")
    release = _resolve_output_root(release_value, "release")
    _validate_release_roots(authoring, release)
    payload, provenance = _projection(authoring)
    desired = dict(payload)
    desired[PROVENANCE_PATH] = canonical_bytes(provenance)
    previous_digest = MISSING_DIGEST
    old_paths: set[str] = set()
    if release.exists():
        _validate_git_metadata(release)
        non_git = [entry for entry in release.iterdir() if entry.name != ".git"]
        if non_git:
            previous = validate_release_provenance(release)
            previous_digest = digest_path(release / PROVENANCE_PATH)
            old_paths = {item["path"] for item in previous["payload"]} | {PROVENANCE_PATH}
    operations: list[dict[str, str]] = []
    for relative in sorted(set(desired) | old_paths):
        pre_digest = digest_path(contained_path(release, relative)) if release.exists() else MISSING_DIGEST
        post_digest = _sha256_bytes(desired[relative]) if relative in desired else MISSING_DIGEST
        if pre_digest == post_digest:
            continue
        operations.append({
            "path": relative,
            "operation": "delete" if post_digest == MISSING_DIGEST else "create" if pre_digest == MISSING_DIGEST else "replace",
            "preDigest": pre_digest,
            "postDigest": post_digest,
        })
    plan: dict[str, Any] = {
        "schemaVersion": PLAN_SCHEMA_VERSION,
        "kind": "harness-release-plan",
        "authoringRoot": str(authoring),
        "releaseRoot": str(release),
        "manifestDigest": provenance["manifestDigest"],
        "projectionDigest": provenance["projectionDigest"],
        "previousProvenanceDigest": previous_digest,
        "operations": operations,
        "planDigest": "",
    }
    plan["planDigest"] = _plan_digest(plan)
    return plan


def validate_release_plan(value: dict[str, Any]) -> None:
    if not isinstance(value, dict) or set(value) != PLAN_KEYS:
        raise MigrationError("release plan has unknown fields or invalid schema")
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != PLAN_SCHEMA_VERSION or value.get("kind") != "harness-release-plan":
        raise MigrationError("release plan has unknown fields or invalid schema")
    authoring = _validate_recorded_path(value.get("authoringRoot"), "release plan authoringRoot")
    release = _validate_recorded_path(value.get("releaseRoot"), "release plan releaseRoot")
    _validate_release_roots(authoring, release)
    for field in ("manifestDigest", "projectionDigest", "planDigest"):
        if not _is_digest(value.get(field)):
            raise MigrationError(f"release plan {field} is not a canonical digest")
    if not _is_digest(value.get("previousProvenanceDigest"), allow_missing=True):
        raise MigrationError("release plan previousProvenanceDigest is not a canonical digest")
    operations = value.get("operations")
    if not isinstance(operations, list):
        raise MigrationError("release plan operations must be an array")
    paths: list[str] = []
    for operation in operations:
        if (
            not isinstance(operation, dict)
            or set(operation) != OPERATION_KEYS
            or not isinstance(operation.get("operation"), str)
            or operation["operation"] not in {"create", "replace", "delete"}
        ):
            raise MigrationError("release plan operation is invalid")
        relative = _validate_relative_path(operation.get("path"), "release plan operation path")
        pre_digest = operation.get("preDigest")
        post_digest = operation.get("postDigest")
        if not _is_digest(pre_digest, allow_missing=True) or not _is_digest(post_digest, allow_missing=True):
            raise MigrationError("release plan operation contains an invalid digest")
        expected_shape = {
            "create": (pre_digest == MISSING_DIGEST and post_digest != MISSING_DIGEST),
            "replace": (pre_digest != MISSING_DIGEST and post_digest != MISSING_DIGEST and pre_digest != post_digest),
            "delete": (pre_digest != MISSING_DIGEST and post_digest == MISSING_DIGEST),
        }
        if not expected_shape[operation["operation"]]:
            raise MigrationError("release plan operation does not match its digest transition")
        paths.append(relative)
    if paths != sorted(set(paths)) or value["planDigest"] != _plan_digest(value):
        raise MigrationError("release plan digest or operation order is invalid", exit_code=ExitCode.BLOCKED)


def _receipt_digest(value: dict[str, Any]) -> str:
    return digest_value(without_digest(value, "receiptDigest"))


def _write_receipt(path: Path, value: dict[str, Any]) -> None:
    value["receiptDigest"] = _receipt_digest(value)
    atomic_write_json(path, value)


def _validate_release_verification(receipt: dict[str, Any]) -> None:
    report = receipt["verification"]
    if report is None:
        if receipt["status"] in {"verified", "verification_failed"}:
            raise MigrationError("release receipt verification status has no report", exit_code=ExitCode.ROLLBACK_REFUSED)
        return
    if not isinstance(report, dict) or set(report) != {"schemaVersion", "status", "receiptPath", "checks"}:
        raise MigrationError("release receipt verification report is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if (
        type(report["schemaVersion"]) is not int
        or report["schemaVersion"] != 1
        or not isinstance(report["status"], str)
        or report["status"] not in {"success", "failed"}
    ):
        raise MigrationError("release receipt verification report is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if report["receiptPath"] != receipt["receiptPath"] or not isinstance(report["checks"], list):
        raise MigrationError("release receipt verification report binding is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    expected_count = len(receipt["journal"]) + 2
    if len(report["checks"]) != expected_count:
        raise MigrationError("release receipt verification check coverage is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    for entry, check in zip(receipt["journal"], report["checks"][:len(receipt["journal"])]):
        if not isinstance(check, dict) or set(check) != {"path", "expected", "actual", "status"}:
            raise MigrationError("release receipt verification check is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if check["path"] != entry["path"] or check["expected"] != entry["expectedPostDigest"]:
            raise MigrationError("release receipt verification check binding is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if (
            not _is_digest(check["actual"], allow_missing=True)
            or not isinstance(check["status"], str)
            or check["status"] not in {"passed", "failed"}
        ):
            raise MigrationError("release receipt verification check is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        expected_status = "passed" if check["actual"] == check["expected"] else "failed"
        if check["status"] != expected_status:
            raise MigrationError("release receipt verification check status is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    git_check = report["checks"][-2]
    if (
        not isinstance(git_check, dict)
        or set(git_check) != {"path", "expected", "actual", "status"}
        or git_check.get("path") != ".git"
        or git_check.get("expected") != receipt["gitDigest"]
        or not _is_digest(git_check.get("actual"), allow_missing=True)
        or git_check.get("status") != ("passed" if git_check.get("actual") == receipt["gitDigest"] else "failed")
    ):
        raise MigrationError("release receipt Git verification check is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    provenance_check = report["checks"][-1]
    if (
        not isinstance(provenance_check, dict)
        or set(provenance_check) != {"path", "kind", "status"}
        or provenance_check.get("path") != PROVENANCE_PATH
        or provenance_check.get("kind") != "provenance"
        or not isinstance(provenance_check.get("status"), str)
        or provenance_check.get("status") not in {"passed", "failed"}
    ):
        raise MigrationError("release receipt provenance verification check is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    expected_report_status = "success" if all(item["status"] == "passed" for item in report["checks"]) else "failed"
    if report["status"] != expected_report_status:
        raise MigrationError("release receipt verification result is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if receipt["status"] == "verified" and report["status"] != "success":
        raise MigrationError("release receipt verification status is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if receipt["status"] == "verification_failed" and report["status"] != "failed":
        raise MigrationError("release receipt verification status is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)


def load_release_receipt(path: Path) -> dict[str, Any]:
    declared = Path(os.path.abspath(path))
    try:
        rebound = declared.resolve(strict=False) != declared
    except (OSError, RuntimeError) as exc:
        raise MigrationError("release receipt path cannot be resolved", exit_code=ExitCode.ROLLBACK_REFUSED) from exc
    if is_link_like(declared) or rebound:
        raise MigrationError("release receipt path must not be link-like", exit_code=ExitCode.ROLLBACK_REFUSED)
    value = read_json(declared)
    if not RECEIPT_KEYS.issubset(value) or set(value) - RECEIPT_KEYS - RECEIPT_OPTIONAL_KEYS:
        raise MigrationError("release receipt has unknown or missing fields", exit_code=ExitCode.ROLLBACK_REFUSED)
    if type(value.get("schemaVersion")) is not int or value["schemaVersion"] != RECEIPT_SCHEMA_VERSION or value.get("kind") != "harness-release-receipt":
        raise MigrationError("release receipt digest or schema is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not _is_digest(value.get("receiptDigest")) or value["receiptDigest"] != _receipt_digest(value):
        raise MigrationError("release receipt digest or schema is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not isinstance(value.get("status"), str) or value["status"] not in RECEIPT_STATUSES:
        raise MigrationError("release receipt status is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not _is_digest(value.get("planDigest")) or not _is_digest(value.get("gitDigest"), allow_missing=True):
        raise MigrationError("release receipt contains an invalid canonical digest", exit_code=ExitCode.ROLLBACK_REFUSED)
    authoring = _validate_recorded_path(value.get("authoringRoot"), "release receipt authoringRoot")
    release = _validate_recorded_path(value.get("releaseRoot"), "release receipt releaseRoot")
    backup = _validate_recorded_path(value.get("backupRoot"), "release receipt backupRoot")
    recorded_receipt = _validate_recorded_path(value.get("receiptPath"), "release receipt receiptPath")
    _validate_release_roots(authoring, release)
    if any(
        left == right or is_relative_to(left, right) or is_relative_to(right, left)
        for left, right in ((backup, authoring), (backup, release))
    ):
        raise MigrationError("release receipt backup root binding is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if (
        recorded_receipt != declared
        or recorded_receipt == backup
        or not is_relative_to(recorded_receipt, backup)
        or is_relative_to(recorded_receipt, backup / "preimage")
    ):
        raise MigrationError("release receipt path binding is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if type(value.get("releaseRootExisted")) is not bool:
        raise MigrationError("release receipt releaseRootExisted must be a boolean", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not value["releaseRootExisted"] and value["gitDigest"] != MISSING_DIGEST:
        raise MigrationError("release receipt Git digest contradicts a new release root", exit_code=ExitCode.ROLLBACK_REFUSED)
    if "failure" in value and (not isinstance(value["failure"], str) or not value["failure"]):
        raise MigrationError("release receipt failure is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if value["status"] in {"apply_failed", "rollback_failed"} and "failure" not in value:
        raise MigrationError("release receipt failure status has no detail", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not isinstance(value.get("journal"), list):
        raise MigrationError("release receipt journal is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    paths: list[str] = []
    for item in value["journal"]:
        if not isinstance(item, dict) or set(item) != JOURNAL_KEYS:
            raise MigrationError("release receipt journal is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        relative = _validate_relative_path(item.get("path"), "release receipt journal path")
        operation = item.get("operation")
        state = item.get("state")
        if (
            not isinstance(operation, str)
            or operation not in {"create", "replace", "delete"}
            or not isinstance(state, str)
            or state not in JOURNAL_STATES
        ):
            raise MigrationError("release receipt journal operation or state is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        pre_digest = item.get("preDigest")
        post_digest = item.get("postDigest")
        expected_post = item.get("expectedPostDigest")
        if not _is_digest(pre_digest, allow_missing=True) or not _is_digest(expected_post, allow_missing=True):
            raise MigrationError("release receipt journal digest is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if post_digest is not None and not _is_digest(post_digest, allow_missing=True):
            raise MigrationError("release receipt journal postDigest is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        expected_shape = {
            "create": (pre_digest == MISSING_DIGEST and expected_post != MISSING_DIGEST),
            "replace": (pre_digest != MISSING_DIGEST and expected_post != MISSING_DIGEST and pre_digest != expected_post),
            "delete": (pre_digest != MISSING_DIGEST and expected_post == MISSING_DIGEST),
        }
        if not expected_shape[operation]:
            raise MigrationError("release receipt journal digest transition is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if (state == "applied") != (post_digest is not None):
            raise MigrationError("release receipt journal state and postDigest disagree", exit_code=ExitCode.ROLLBACK_REFUSED)
        if state == "applied" and value["status"] not in {"apply_failed", "rollback_failed", "rolled_back"} and post_digest != expected_post:
            raise MigrationError("release receipt journal postDigest is inconsistent", exit_code=ExitCode.ROLLBACK_REFUSED)
        expected_backup = None if pre_digest == MISSING_DIGEST else "preimage/" + relative
        if item.get("backupPath") != expected_backup:
            raise MigrationError("release receipt journal backup path is inconsistent", exit_code=ExitCode.ROLLBACK_REFUSED)
        if expected_backup is not None:
            _validate_relative_path(expected_backup, "release receipt journal backupPath")
        created_parents = item.get("createdParents")
        if not isinstance(created_parents, list) or not all(isinstance(parent, str) for parent in created_parents):
            raise MigrationError("release receipt journal createdParents is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        destination_parts = PurePosixPath(relative).parts
        allowed_parents = {
            PurePosixPath(*destination_parts[:index]).as_posix()
            for index in range(1, len(destination_parts))
        }
        normalized_parents = [
            _validate_relative_path(parent, "release receipt journal created parent")
            for parent in created_parents
        ]
        if (
            len(set(normalized_parents)) != len(normalized_parents)
            or any(parent not in allowed_parents for parent in normalized_parents)
            or normalized_parents != sorted(normalized_parents, key=lambda parent: len(PurePosixPath(parent).parts))
        ):
            raise MigrationError("release receipt journal createdParents binding is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        paths.append(relative)
    if paths != sorted(set(paths)):
        raise MigrationError("release receipt journal paths must be unique and sorted", exit_code=ExitCode.ROLLBACK_REFUSED)
    if value["status"] in {"applied", "verified", "verification_failed"} and any(item["state"] != "applied" for item in value["journal"]):
        raise MigrationError("release receipt status and journal disagree", exit_code=ExitCode.ROLLBACK_REFUSED)
    _validate_release_verification(value)
    return value


def _missing_parents(path: Path, root: Path) -> list[str]:
    values: list[str] = []
    current = path.parent
    while current != root and is_relative_to(current, root):
        if current.exists():
            break
        values.append(current.relative_to(root).as_posix())
        current = current.parent
    return list(reversed(values))


def _write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.harness-release-tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _prune_empty_parents(path: Path, root: Path) -> None:
    current = path
    while current != root and is_relative_to(current, root) and current.exists() and not any(current.iterdir()):
        parent = current.parent
        current.rmdir()
        current = parent


def apply_release_plan(plan: dict[str, Any], backup_value: str | None = None, receipt_value: str | None = None) -> tuple[dict[str, Any], Path]:
    validate_release_plan(plan)
    expected = build_release_plan(plan["authoringRoot"], plan["releaseRoot"])
    if expected != plan:
        raise MigrationError("release plan no longer matches the canonical projection", exit_code=ExitCode.BLOCKED)
    authoring = resolve_directory(plan["authoringRoot"], "authoring template")
    release = _resolve_output_root(plan["releaseRoot"], "release")
    payload, provenance = _projection(authoring)
    desired = dict(payload)
    desired[PROVENANCE_PATH] = canonical_bytes(provenance)
    backup = _resolve_output_root(backup_value, "release backup") if backup_value else release.parent / f".{release.name}.release-backup-{plan['planDigest'][7:19]}"
    if backup.exists():
        raise MigrationError(f"release backup root already exists: {backup}", exit_code=ExitCode.BLOCKED)
    if backup == release or is_relative_to(backup, release) or is_relative_to(release, backup) or is_relative_to(backup, authoring) or is_relative_to(authoring, backup):
        raise MigrationError("release backup must be external to authoring and release roots", exit_code=ExitCode.BLOCKED)
    receipt_path = Path(receipt_value).expanduser().resolve() if receipt_value else backup / "receipt.json"
    if receipt_path == backup or not is_relative_to(receipt_path, backup) or is_relative_to(receipt_path, backup / "preimage"):
        raise MigrationError("release receipt must be inside backup and outside preimages", exit_code=ExitCode.BLOCKED)
    existed = release.exists()
    git_digest = digest_path(release / ".git") if existed else MISSING_DIGEST
    journal: list[dict[str, Any]] = []
    backup.mkdir(parents=True)
    for operation in plan["operations"]:
        destination = contained_path(release, operation["path"]) if existed else release.joinpath(*operation["path"].split("/"))
        backup_relative = None
        if operation["preDigest"] != MISSING_DIGEST:
            backup_relative = "preimage/" + operation["path"]
            backup_path = contained_path(backup, backup_relative)
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(destination, backup_path, follow_symlinks=False)
            if digest_path(backup_path) != operation["preDigest"]:
                raise MigrationError(f"release backup validation failed: {operation['path']}", exit_code=ExitCode.BLOCKED)
        journal.append({
            "path": operation["path"], "operation": operation["operation"],
            "preDigest": operation["preDigest"], "postDigest": None,
            "expectedPostDigest": operation["postDigest"], "backupPath": backup_relative,
            "createdParents": _missing_parents(destination, release), "state": "prepared",
        })
    receipt: dict[str, Any] = {
        "schemaVersion": RECEIPT_SCHEMA_VERSION, "kind": "harness-release-receipt", "status": "prepared",
        "planDigest": plan["planDigest"], "authoringRoot": str(authoring), "releaseRoot": str(release),
        "backupRoot": str(backup), "receiptPath": str(receipt_path), "releaseRootExisted": existed,
        "gitDigest": git_digest, "journal": journal, "verification": None, "receiptDigest": "",
    }
    _write_receipt(receipt_path, receipt)
    try:
        fail_after = int(os.environ.get("HARNESS_RELEASE_FAIL_AFTER", "-1"))
        release.mkdir(parents=True, exist_ok=True)
        for index, entry in enumerate(journal):
            if fail_after >= 0 and index >= fail_after:
                raise OSError("injected release apply failure")
            if digest_path(release / ".git") != git_digest:
                raise MigrationError("release .git changed during apply", exit_code=ExitCode.BLOCKED)
            destination = contained_path(release, entry["path"])
            if digest_path(destination) != entry["preDigest"]:
                raise MigrationError(f"release pre-image changed before mutation: {entry['path']}", exit_code=ExitCode.BLOCKED)
            entry["state"] = "applying"
            _write_receipt(receipt_path, receipt)
            if entry["operation"] == "delete":
                destination.unlink()
                _prune_empty_parents(destination.parent, release)
            else:
                _write_bytes(destination, desired[entry["path"]])
            entry["postDigest"] = digest_path(destination)
            entry["state"] = "applied"
            _write_receipt(receipt_path, receipt)
            if entry["postDigest"] != entry["expectedPostDigest"]:
                raise OSError(f"release post-image mismatch: {entry['path']}")
        validate_release_provenance(release)
        receipt["status"] = "applied"
        _write_receipt(receipt_path, receipt)
        return receipt, receipt_path
    except Exception as exc:
        receipt["status"] = "apply_failed"
        receipt["failure"] = str(exc)
        _write_receipt(receipt_path, receipt)
        code = exc.exit_code if isinstance(exc, MigrationError) else ExitCode.APPLY_FAILED
        raise MigrationError(f"release apply failed; recover with receipt {receipt_path}: {exc}", exit_code=code) from exc


def _release_receipt_roots(receipt: dict[str, Any], receipt_path: Path, exit_code: ExitCode) -> tuple[Path, Path]:
    release = _resolve_output_root(receipt["releaseRoot"], "release")
    backup = resolve_recorded_directory(receipt["backupRoot"], "release backup", exit_code=exit_code)
    recorded = Path(receipt["receiptPath"])
    if recorded != receipt_path.resolve() or not is_relative_to(recorded, backup):
        raise MigrationError("release receipt path binding is invalid", exit_code=exit_code)
    return release, backup


def verify_release_receipt(receipt_path: Path) -> dict[str, Any]:
    try:
        receipt = load_release_receipt(receipt_path)
        if receipt["status"] not in {"applied", "verified", "verification_failed"}:
            raise MigrationError(f"release receipt status cannot be verified: {receipt['status']}")
        release, _ = _release_receipt_roots(receipt, receipt_path, ExitCode.VERIFICATION_FAILED)
        checks = [
            {"path": entry["path"], "expected": entry["expectedPostDigest"], "actual": digest_path(contained_path(release, entry["path"]))}
            for entry in receipt["journal"]
        ]
        for check in checks:
            check["status"] = "passed" if check["actual"] == check["expected"] else "failed"
        git_actual = digest_path(release / ".git")
        checks.append({"path": ".git", "expected": receipt["gitDigest"], "actual": git_actual, "status": "passed" if git_actual == receipt["gitDigest"] else "failed"})
        try:
            validate_release_provenance(release)
            provenance_status = "passed"
        except MigrationError:
            provenance_status = "failed"
        checks.append({"path": PROVENANCE_PATH, "kind": "provenance", "status": provenance_status})
        status = "success" if all(item["status"] == "passed" for item in checks) else "failed"
        report = {"schemaVersion": 1, "status": status, "receiptPath": str(receipt_path.resolve()), "checks": checks}
        receipt["verification"] = report
        receipt["status"] = "verified" if status == "success" else "verification_failed"
        _write_receipt(receipt_path, receipt)
        return report
    except MigrationError as exc:
        raise MigrationError(str(exc), exit_code=ExitCode.VERIFICATION_FAILED) from exc


def rollback_release_receipt(receipt_path: Path) -> dict[str, Any]:
    try:
        receipt = load_release_receipt(receipt_path)
    except MigrationError as exc:
        raise MigrationError(str(exc), exit_code=ExitCode.ROLLBACK_REFUSED) from exc
    if receipt["status"] not in {"prepared", "applied", "apply_failed", "verified", "verification_failed", "rollback_failed"}:
        raise MigrationError(f"release receipt status cannot be rolled back: {receipt['status']}", exit_code=ExitCode.ROLLBACK_REFUSED)
    release, backup = _release_receipt_roots(receipt, receipt_path, ExitCode.ROLLBACK_REFUSED)
    if digest_path(release / ".git") != receipt["gitDigest"]:
        raise MigrationError("release .git changed after apply", exit_code=ExitCode.ROLLBACK_REFUSED)
    for entry in receipt["journal"]:
        current = digest_path(contained_path(release, entry["path"]))
        allowed = {entry["preDigest"], entry["expectedPostDigest"]}
        if current not in allowed:
            raise MigrationError(f"release content changed after apply: {entry['path']}", exit_code=ExitCode.ROLLBACK_REFUSED)
        if entry["preDigest"] != MISSING_DIGEST:
            preimage = contained_path(backup, entry["backupPath"])
            if digest_path(preimage) != entry["preDigest"]:
                raise MigrationError(f"release backup pre-image changed: {entry['path']}", exit_code=ExitCode.ROLLBACK_REFUSED)
    try:
        for entry in reversed(receipt["journal"]):
            destination = contained_path(release, entry["path"])
            if entry["preDigest"] == MISSING_DIGEST:
                if destination.exists():
                    destination.unlink()
            else:
                _write_bytes(destination, contained_path(backup, entry["backupPath"]).read_bytes())
            for relative in reversed(entry["createdParents"]):
                directory = contained_path(release, relative)
                if directory.exists() and not any(directory.iterdir()):
                    directory.rmdir()
        if not receipt["releaseRootExisted"] and release.exists() and not any(release.iterdir()):
            release.rmdir()
        receipt["status"] = "rolled_back"
        _write_receipt(receipt_path, receipt)
        return receipt
    except Exception as exc:
        receipt["status"] = "rollback_failed"
        receipt["failure"] = str(exc)
        try:
            _write_receipt(receipt_path, receipt)
        except MigrationError as receipt_exc:
            raise MigrationError(
                f"release rollback failed; receipt update also failed; retry with existing receipt {receipt_path}: {exc}; {receipt_exc}",
                exit_code=ExitCode.ROLLBACK_REFUSED,
            ) from receipt_exc
        raise MigrationError(f"release rollback failed and can be retried: {exc}", exit_code=ExitCode.ROLLBACK_REFUSED) from exc
