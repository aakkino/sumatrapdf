from __future__ import annotations

import os
import shutil
import stat
from hashlib import sha256
from pathlib import Path
from pathlib import PurePosixPath
import re
import tempfile
from typing import Any

from .codec import MISSING_DIGEST, atomic_write_json, digest_path, digest_value, read_json, without_digest
from .manifest import load_manifest
from .models import ExitCode, has_dispatch_override_for_path, MigrationError, Operation, Plan, validate_source_admission
from .planner import build_plan, resolve_plan, source_bytes, validate_plan_digest
from .safety import PureParts, apply_blockers, contained_path, is_link_like, is_relative_to, resolve_directory, resolve_recorded_directory, validate_backup_root, validate_root_relationship


RECEIPT_SCHEMA_VERSION = 1
LEGACY_ADOPTION_RECEIPT_SCHEMA_VERSION = 2
ADOPTION_RECEIPT_SCHEMA_VERSION = 3
RECEIPT_REQUIRED_KEYS = {
    "schemaVersion", "status", "planDigest", "targetState", "templateRoot",
    "targetRoot", "backupRoot", "receiptPath", "journal",
    "preservedDigests", "verificationCommands", "verification", "receiptDigest",
    "sourceAdmission",
}
RECEIPT_OPTIONAL_KEYS = {"failure"}
RECOVERY_FIELDS = {"baselineRoot", "baselineAudit", "quarantinedTargetStates"}
RECOVERY_RECEIPT_REQUIRED_KEYS = (
    RECEIPT_REQUIRED_KEYS - {"sourceAdmission"} | RECOVERY_FIELDS
)
LEGACY_ADOPTION_RECEIPT_KEYS = RECEIPT_REQUIRED_KEYS | {"adoptPartial"}
ADOPTION_RECEIPT_KEYS = LEGACY_ADOPTION_RECEIPT_KEYS | {"projectStateDigests"}
ADOPTION_RECEIPT_OPTIONAL_KEYS = {"failure"}
JOURNAL_KEYS = {
    "sourcePath", "path", "operation", "preDigest", "postDigest",
    "expectedPostDigest", "backupPath", "createdParents", "state",
}
PRESERVED_ROOTS = [
    ".trellis/tasks", ".trellis/workspace", ".trellis/.developer",
    ".trellis/.current-task", ".trellis/.runtime",
]
PROJECT_STATE_TREE_ROOTS = (".agents/skills", ".trellis/spec")
PROJECT_STATE_FILE_PATHS = (
    "AGENTS.md",
    ".codex/config.toml",
    ".codex/hooks.json",
    ".trellis/.gitignore",
    ".trellis/.template-hashes.json",
    ".trellis/.version",
    ".trellis/config.yaml",
)
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")


def _receipt_digest(receipt: dict[str, Any]) -> str:
    return digest_value(without_digest(receipt, "receiptDigest"))


def _write_receipt(path: Path, receipt: dict[str, Any]) -> None:
    receipt["receiptDigest"] = _receipt_digest(receipt)
    atomic_write_json(path, receipt)


def _project_state_digest_paths(mutation_paths: set[str]) -> set[str]:
    return {
        *PROJECT_STATE_TREE_ROOTS,
        *(relative for relative in PROJECT_STATE_FILE_PATHS if relative not in mutation_paths),
    }


def _digest_project_state_tree(target: Path, relative: str, mutation_paths: set[str]) -> str:
    root = contained_path(target, relative)
    if not root.exists():
        if is_link_like(root):
            raise MigrationError(f"symlinks are unsupported: {root}")
        return MISSING_DIGEST
    if is_link_like(root) or not root.is_dir():
        raise MigrationError(f"project state root is not a regular directory: {root}")
    entries: list[dict[str, str]] = []
    try:
        for child in sorted(root.rglob("*"), key=lambda item: item.as_posix()):
            metadata = child.lstat()
            if is_link_like(child):
                raise MigrationError(f"symlinks are unsupported: {child}")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise MigrationError(f"unsupported filesystem entry: {child}")
            target_relative = child.relative_to(target).as_posix()
            if target_relative in mutation_paths:
                continue
            entries.append({
                "path": child.relative_to(root).as_posix(),
                "digest": digest_path(child),
            })
    except OSError as exc:
        raise MigrationError(f"cannot inspect project state {root}: {exc}") from exc
    if not entries:
        return MISSING_DIGEST
    return digest_value(entries)


def project_state_digests(target: Path, mutation_paths: set[str]) -> dict[str, str]:
    values: dict[str, str] = {}
    for relative in sorted(_project_state_digest_paths(mutation_paths)):
        if relative in PROJECT_STATE_TREE_ROOTS:
            values[relative] = _digest_project_state_tree(target, relative, mutation_paths)
        else:
            values[relative] = digest_path(contained_path(target, relative))
    return values


def _validate_project_state_digests(value: object, mutation_paths: set[str]) -> None:
    if not isinstance(value, dict):
        raise MigrationError("receipt project state digests are invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    expected_paths = _project_state_digest_paths(mutation_paths)
    if set(value) != expected_paths:
        raise MigrationError("receipt project state digest coverage is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    for relative, digest in value.items():
        if not isinstance(digest, str) or (digest != MISSING_DIGEST and not DIGEST_PATTERN.fullmatch(digest)):
            raise MigrationError("receipt project state digest value is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)


def load_receipt(path: Path) -> dict[str, Any]:
    if is_link_like(path):
        raise MigrationError("receipt path must not be a link", exit_code=ExitCode.ROLLBACK_REFUSED)
    receipt = read_json(path)
    if (
        receipt.get("schemaVersion") not in {
            RECEIPT_SCHEMA_VERSION,
            LEGACY_ADOPTION_RECEIPT_SCHEMA_VERSION,
            ADOPTION_RECEIPT_SCHEMA_VERSION,
        }
        or isinstance(receipt.get("schemaVersion"), bool)
        or receipt.get("receiptDigest") != _receipt_digest(receipt)
    ):
        raise MigrationError("receipt digest or schema is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    keys = set(receipt)
    schema_version = receipt["schemaVersion"]
    if schema_version == ADOPTION_RECEIPT_SCHEMA_VERSION:
        keys_are_valid = ADOPTION_RECEIPT_KEYS.issubset(keys) and not (
            keys - ADOPTION_RECEIPT_KEYS - ADOPTION_RECEIPT_OPTIONAL_KEYS
        )
    elif schema_version == LEGACY_ADOPTION_RECEIPT_SCHEMA_VERSION:
        keys_are_valid = LEGACY_ADOPTION_RECEIPT_KEYS.issubset(keys) and not (
            keys - LEGACY_ADOPTION_RECEIPT_KEYS - ADOPTION_RECEIPT_OPTIONAL_KEYS
        )
    elif RECOVERY_RECEIPT_REQUIRED_KEYS.issubset(keys):
        keys_are_valid = not (keys - RECOVERY_RECEIPT_REQUIRED_KEYS - RECEIPT_OPTIONAL_KEYS)
    else:
        keys_are_valid = RECEIPT_REQUIRED_KEYS.issubset(keys) and not (keys - RECEIPT_REQUIRED_KEYS - RECEIPT_OPTIONAL_KEYS)
    if not keys_are_valid:
        raise MigrationError("receipt has unknown or missing fields", exit_code=ExitCode.ROLLBACK_REFUSED)
    if "sourceAdmission" in receipt:
        try:
            validate_source_admission(receipt["sourceAdmission"])
        except MigrationError as exc:
            raise MigrationError(str(exc), exit_code=ExitCode.ROLLBACK_REFUSED) from exc
    for field in ("status", "planDigest", "targetState", "templateRoot", "targetRoot", "backupRoot", "receiptPath"):
        if not isinstance(receipt[field], str):
            raise MigrationError(f"receipt field is not a string: {field}", exit_code=ExitCode.ROLLBACK_REFUSED)
    if receipt["status"] not in {
        "prepared", "applied", "apply_failed", "verified", "verified_incomplete",
        "verification_failed", "rollback_failed", "rolled_back",
    }:
        raise MigrationError("receipt status is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if receipt["targetState"] not in {"fresh", "existing_trellis", "unsupported_partial"}:
        raise MigrationError("receipt target state is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    recovery_fields = RECOVERY_FIELDS
    is_adoption = schema_version in {
        LEGACY_ADOPTION_RECEIPT_SCHEMA_VERSION,
        ADOPTION_RECEIPT_SCHEMA_VERSION,
    }
    if is_adoption and (receipt.get("adoptPartial") is not True or receipt["targetState"] != "unsupported_partial"):
        raise MigrationError("receipt adoption binding is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if is_adoption and recovery_fields.intersection(receipt):
        raise MigrationError("receipt adoption fields are invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not is_adoption and (receipt["targetState"] == "unsupported_partial") != recovery_fields.issubset(receipt):
        raise MigrationError("receipt recovery baseline binding is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not is_adoption and receipt["targetState"] != "unsupported_partial" and recovery_fields.intersection(receipt):
        raise MigrationError("receipt recovery fields are invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if "baselineRoot" in receipt and not isinstance(receipt["baselineRoot"], str):
        raise MigrationError("receipt recovery baseline root is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not isinstance(receipt["receiptDigest"], str):
        raise MigrationError("receipt digest is not a string", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not DIGEST_PATTERN.fullmatch(receipt["planDigest"]) or not DIGEST_PATTERN.fullmatch(receipt["receiptDigest"]):
        raise MigrationError("receipt contains an invalid canonical digest", exit_code=ExitCode.ROLLBACK_REFUSED)
    if Path(receipt["receiptPath"]).resolve() != path.resolve():
        raise MigrationError("receipt is not at its recorded path", exit_code=ExitCode.ROLLBACK_REFUSED)
    if not isinstance(receipt["journal"], list) or not isinstance(receipt["preservedDigests"], dict):
        raise MigrationError("receipt journal or preserved digests are invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    for relative, value in receipt["preservedDigests"].items():
        if not isinstance(relative, str) or not isinstance(value, str):
            raise MigrationError("receipt preserved digests are invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if value != MISSING_DIGEST and not DIGEST_PATTERN.fullmatch(value):
            raise MigrationError("receipt preserved digest value is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        try:
            PureParts(relative)
        except MigrationError as exc:
            raise MigrationError("receipt preserved digest path is invalid", exit_code=ExitCode.ROLLBACK_REFUSED) from exc
    commands = receipt["verificationCommands"]
    if not isinstance(commands, list) or not all(
        isinstance(command, list) and command and all(isinstance(item, str) for item in command)
        for command in commands
    ):
        raise MigrationError("receipt verification commands are invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if receipt["verification"] is not None and not isinstance(receipt["verification"], dict):
        raise MigrationError("receipt verification report is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    if "failure" in receipt and not isinstance(receipt["failure"], str):
        raise MigrationError("receipt failure is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    journal_paths: set[str] = set()
    journal_source_paths: set[str] = set()
    for entry in receipt["journal"]:
        if not isinstance(entry, dict) or set(entry) != JOURNAL_KEYS:
            raise MigrationError("receipt contains an invalid journal entry", exit_code=ExitCode.ROLLBACK_REFUSED)
        if not all(isinstance(entry[field], str) for field in ("sourcePath", "path", "operation", "preDigest", "expectedPostDigest", "state")):
            raise MigrationError("receipt journal contains invalid field types", exit_code=ExitCode.ROLLBACK_REFUSED)
        if entry["backupPath"] is not None and not isinstance(entry["backupPath"], str):
            raise MigrationError("receipt journal backupPath is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if entry["postDigest"] is not None and not isinstance(entry["postDigest"], str):
            raise MigrationError("receipt journal postDigest is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        try:
            PureParts(entry["sourcePath"])
            PureParts(entry["path"])
            if entry["backupPath"] is not None:
                PureParts(entry["backupPath"])
        except (MigrationError, TypeError) as exc:
            raise MigrationError("receipt journal contains an invalid path", exit_code=ExitCode.ROLLBACK_REFUSED) from exc
        if entry["operation"] not in {Operation.COPY.value, Operation.SIDECAR.value}:
            raise MigrationError("receipt journal contains an invalid operation", exit_code=ExitCode.ROLLBACK_REFUSED)
        if entry["state"] not in {"prepared", "applying", "applied"}:
            raise MigrationError("receipt journal contains an invalid state", exit_code=ExitCode.ROLLBACK_REFUSED)
        if entry["path"] in journal_paths:
            raise MigrationError("receipt journal contains duplicate destinations", exit_code=ExitCode.ROLLBACK_REFUSED)
        journal_paths.add(entry["path"])
        journal_source_paths.add(entry["sourcePath"])
        if not DIGEST_PATTERN.fullmatch(entry["expectedPostDigest"]):
            raise MigrationError("receipt journal expected post-digest is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if entry["preDigest"] != MISSING_DIGEST and not DIGEST_PATTERN.fullmatch(entry["preDigest"]):
            raise MigrationError("receipt journal pre-digest is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if entry["postDigest"] is not None and not DIGEST_PATTERN.fullmatch(entry["postDigest"]):
            raise MigrationError("receipt journal post-digest is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if (entry["state"] == "applied") != (entry["postDigest"] is not None):
            raise MigrationError("receipt journal state and post-digest disagree", exit_code=ExitCode.ROLLBACK_REFUSED)
        expected_backup = None if entry["preDigest"] == MISSING_DIGEST else "preimage/" + entry["path"]
        if entry["backupPath"] != expected_backup:
            raise MigrationError("receipt journal backup path is inconsistent", exit_code=ExitCode.ROLLBACK_REFUSED)
        if not isinstance(entry["createdParents"], list) or not all(isinstance(relative, str) for relative in entry["createdParents"]):
            raise MigrationError("receipt journal createdParents is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if len(set(entry["createdParents"])) != len(entry["createdParents"]):
            raise MigrationError("receipt journal createdParents contains duplicates", exit_code=ExitCode.ROLLBACK_REFUSED)
        destination_parts = PureParts(entry["path"])
        allowed_parents = {
            PurePosixPath(*destination_parts[:index]).as_posix()
            for index in range(1, len(destination_parts))
        }
        for relative in entry["createdParents"]:
            try:
                PureParts(relative)
            except (MigrationError, TypeError) as exc:
                raise MigrationError("receipt journal contains an invalid parent path", exit_code=ExitCode.ROLLBACK_REFUSED) from exc
            if relative not in allowed_parents:
                raise MigrationError("receipt journal parent is outside its destination", exit_code=ExitCode.ROLLBACK_REFUSED)
        if entry["createdParents"] != sorted(entry["createdParents"], key=lambda value: len(PurePosixPath(value).parts)):
            raise MigrationError("receipt journal parents are not canonically ordered", exit_code=ExitCode.ROLLBACK_REFUSED)
    if schema_version == ADOPTION_RECEIPT_SCHEMA_VERSION:
        _validate_project_state_digests(receipt["projectStateDigests"], journal_paths)
    if receipt["targetState"] == "existing_trellis":
        expected_preserved = set(PRESERVED_ROOTS)
    elif receipt["targetState"] == "unsupported_partial" and is_adoption:
        expected_preserved = set(PRESERVED_ROOTS)
    elif receipt["targetState"] == "unsupported_partial":
        from .recovery import (
            RECOVERY_PRESERVED_ROOTS,
            baseline_audit_from_dict,
            quarantined_target_states_from_dict,
        )
        baseline = Path(receipt["baselineRoot"])
        target = Path(receipt["targetRoot"])
        try:
            baseline_relative = baseline.relative_to(target).as_posix()
        except ValueError as exc:
            raise MigrationError("receipt recovery baseline is outside the target", exit_code=ExitCode.ROLLBACK_REFUSED) from exc
        expected_preserved = {*RECOVERY_PRESERVED_ROOTS, baseline_relative}
        try:
            audit = baseline_audit_from_dict(receipt["baselineAudit"], "receipt baselineAudit")
            target_states = quarantined_target_states_from_dict(
                receipt["quarantinedTargetStates"], "receipt quarantinedTargetStates",
            )
        except MigrationError as exc:
            raise MigrationError(str(exc), exit_code=ExitCode.ROLLBACK_REFUSED) from exc
        audit_paths = [item.path for item in audit.quarantined_paths]
        if [item.path for item in target_states] != audit_paths:
            raise MigrationError("receipt quarantine target coverage is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
        if journal_paths.intersection(audit_paths) or journal_source_paths.intersection(audit_paths):
            raise MigrationError("receipt journal contains a quarantined path", exit_code=ExitCode.ROLLBACK_REFUSED)
    else:
        expected_preserved = set()
    if set(receipt["preservedDigests"]) != expected_preserved:
        raise MigrationError("receipt preserved digest coverage is invalid", exit_code=ExitCode.ROLLBACK_REFUSED)
    return receipt


def validate_receipt_roots(
    receipt: dict[str, Any], receipt_path: Path, *, exit_code: ExitCode = ExitCode.ROLLBACK_REFUSED,
) -> tuple[Path, Path]:
    target = resolve_recorded_directory(receipt["targetRoot"], "target", exit_code=exit_code)
    backup = resolve_recorded_directory(receipt["backupRoot"], "backup", exit_code=exit_code)
    if backup == target or is_relative_to(backup, target) or is_relative_to(target, backup):
        raise MigrationError("recorded backup and target roots are not disjoint", exit_code=exit_code)
    resolved_receipt = receipt_path.resolve()
    if not is_relative_to(resolved_receipt, backup):
        raise MigrationError("receipt is outside its recorded backup root", exit_code=exit_code)
    preimage_root = backup / "preimage"
    if resolved_receipt == preimage_root or is_relative_to(resolved_receipt, preimage_root):
        raise MigrationError("receipt collides with backup pre-images", exit_code=exit_code)
    if "baselineRoot" in receipt:
        baseline = resolve_recorded_directory(receipt["baselineRoot"], "recovery baseline", exit_code=exit_code)
        expected_parent = contained_path(target, ".trellis", allow_missing=False)
        if baseline.parent != expected_parent or not baseline.name.startswith(".backup-"):
            raise MigrationError("recorded recovery baseline is outside the target backup layout", exit_code=exit_code)
    return target, backup


def _copy_bytes_atomic(destination: Path, data: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_value = tempfile.mkstemp(
        prefix=f".{destination.name}.harness-", suffix=".tmp", dir=destination.parent,
    )
    temporary = Path(temporary_value)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _missing_parents(destination: Path, root: Path) -> list[str]:
    missing: list[str] = []
    current = destination.parent
    while current != root and not current.exists():
        missing.append(current.relative_to(root).as_posix())
        current = current.parent
    return list(reversed(missing))


def _validate_snapshot_baseline(plan: Plan, template: Path) -> None:
    baseline = next((decision for decision in plan.decisions if decision.id.startswith("official-baseline:")), None)
    if baseline is None or baseline.selection != "snapshot":
        return
    hashes_document = read_json(template / ".trellis" / ".template-hashes.json")
    hashes = hashes_document.get("hashes")
    if not isinstance(hashes, dict) or not all(isinstance(path, str) and isinstance(value, str) for path, value in hashes.items()):
        raise MigrationError("snapshot template hashes are invalid", exit_code=ExitCode.BLOCKED)
    actions = {action.path: action for action in plan.actions}
    mismatches: list[str] = []
    for relative, expected in sorted(hashes.items()):
        action = actions.get(relative)
        if action is None:
            mismatches.append(relative)
            continue
        final_digest = action.source_digest if action.operation == Operation.COPY.value else action.target_digest
        if final_digest != "sha256:" + expected:
            mismatches.append(relative)
    if mismatches:
        preview = ", ".join(mismatches[:5])
        remainder = f" (+{len(mismatches) - 5} more)" if len(mismatches) > 5 else ""
        raise MigrationError(
            f"snapshot baseline does not match resolved official-managed files: {preview}{remainder}",
            exit_code=ExitCode.BLOCKED,
        )


def _normal_source_bytes(template: Path, target: Path, plan: Plan, action: Any) -> bytes:
    source_relative = action.path
    if action.kind == "fresh_only_skeleton" and plan.developer and action.path.startswith(f".trellis/workspace/{plan.developer}/"):
        source_relative = ".trellis/workspace/kino/" + action.path[len(f".trellis/workspace/{plan.developer}/"):]
    target_preimage = None
    if has_dispatch_override_for_path(action.path, plan.route_overrides):
        destination = contained_path(target, action.path)
        if destination.exists():
            try:
                target_preimage = destination.read_bytes()
            except OSError as exc:
                raise MigrationError(f"cannot read route override target pre-image: {action.path}: {exc}") from exc
    return source_bytes(
        template,
        source_relative,
        action.path,
        plan.developer,
        action.kind,
        plan.route_overrides,
        target_preimage,
    )


def _revalidate_plan(plan: Plan) -> tuple[Path, Path]:
    validate_plan_digest(plan)
    template = resolve_directory(plan.template_root, "template")
    target = resolve_directory(plan.target_root, "target")
    validate_root_relationship(template, target)
    manifest = load_manifest(template)
    if manifest.digest != plan.manifest_digest:
        raise MigrationError("manifest changed after planning", exit_code=ExitCode.BLOCKED)
    if plan.source_admission["kind"] == "unproven":
        raise MigrationError(
            "apply requires release provenance; rebuild the plan from a release root or use plan --development-template",
            exit_code=ExitCode.BLOCKED,
        )
    if plan.blockers:
        raise MigrationError("plan contains blockers: " + "; ".join(plan.blockers), exit_code=ExitCode.BLOCKED)
    unresolved = [decision.id for decision in plan.decisions if decision.selection is None]
    if unresolved:
        raise MigrationError("plan has unresolved decisions: " + ", ".join(unresolved), exit_code=ExitCode.UNRESOLVED)
    blockers = apply_blockers(target)
    if blockers:
        raise MigrationError("apply blocked: " + "; ".join(blockers), exit_code=ExitCode.BLOCKED)
    expected = build_plan(
        str(template), str(target), plan.developer, plan.profile,
        adopt_partial=plan.adopt_partial,
        route_overrides=() if plan.schema_version == 7 else plan.route_overrides,
        route_only=plan.selection_mode == "route-only",
        route_pairs=plan.route_overrides if plan.schema_version == 7 else (),
        development_template=plan.source_admission["kind"] == "development-only",
    )
    selections = {decision.id: decision.selection for decision in plan.decisions}
    try:
        expected = resolve_plan(
            expected,
            {identifier: choice for identifier, choice in selections.items() if choice is not None},
        )
    except MigrationError as exc:
        raise MigrationError(
            "plan no longer matches the canonical migration plan",
            exit_code=ExitCode.BLOCKED,
        ) from exc
    if expected.to_dict() != plan.to_dict():
        raise MigrationError("plan no longer matches the canonical migration plan", exit_code=ExitCode.BLOCKED)
    _validate_snapshot_baseline(plan, template)
    for action in plan.actions:
        current = digest_path(contained_path(target, action.path))
        if current != action.target_digest:
            raise MigrationError(f"stale plan: target pre-image changed for {action.path}", exit_code=ExitCode.BLOCKED)
        if action.operation == Operation.SIDECAR.value:
            if not action.destination:
                raise MigrationError(f"sidecar action has no destination: {action.path}", exit_code=ExitCode.BLOCKED)
            destination_digest = digest_path(contained_path(target, action.destination))
            if destination_digest != action.destination_digest:
                raise MigrationError(f"stale plan: sidecar pre-image changed for {action.destination}", exit_code=ExitCode.BLOCKED)
        if action.source_digest is not None:
            # Recompute transformed skeleton content as well as ordinary files.
            source_relative = action.path
            if action.kind == "fresh_only_skeleton" and plan.developer and action.path.startswith(f".trellis/workspace/{plan.developer}/"):
                source_relative = ".trellis/workspace/kino/" + action.path[len(f".trellis/workspace/{plan.developer}/"):]
            current_source = _normal_source_bytes(template, target, plan, action)
            if "sha256:" + sha256(current_source).hexdigest() != action.source_digest:
                raise MigrationError(f"stale plan: source changed for {action.path}", exit_code=ExitCode.BLOCKED)
    return template, target


def _validate_recovery_baseline_digest(plan: Any, baseline_root: Path | None, message: str) -> None:
    if baseline_root is None:
        return
    try:
        actual = digest_path(baseline_root)
    except MigrationError as exc:
        raise MigrationError(f"{message}: {exc}", exit_code=ExitCode.BLOCKED) from exc
    if actual != plan.baseline_digest:
        raise MigrationError(message, exit_code=ExitCode.BLOCKED)


def _validate_quarantined_target_states(
    target: Path, states: list[dict[str, str]] | None, message: str,
    *, exit_code: ExitCode = ExitCode.BLOCKED,
) -> None:
    if states is None:
        return
    for state in states:
        try:
            actual = digest_path(contained_path(target, state["path"]))
        except (MigrationError, OSError) as exc:
            raise MigrationError(f"{message}: {state['path']}: {exc}", exit_code=exit_code) from exc
        if actual != state["preDigest"] or actual != state["postDigest"]:
            raise MigrationError(f"{message}: {state['path']}", exit_code=exit_code)


def _apply_validated_transaction(
    plan: Any,
    template: Path,
    target: Path,
    source_reader: Any,
    preserved_roots: list[str],
    *,
    backup_value: str | None = None,
    receipt_value: str | None = None,
    baseline_root: Path | None = None,
    baseline_audit: dict[str, Any] | None = None,
    quarantined_target_states: list[dict[str, str]] | None = None,
) -> tuple[dict[str, Any], Path]:
    backup = Path(backup_value).expanduser().resolve() if backup_value else target.parent / f".{target.name}.harness-backup-{plan.plan_digest[7:19]}"
    validate_backup_root(backup, template, target)
    if backup.exists():
        raise MigrationError(f"backup root already exists: {backup}", exit_code=ExitCode.BLOCKED)
    receipt_path = Path(receipt_value).expanduser().resolve() if receipt_value else backup / "receipt.json"
    if receipt_path == backup or not receipt_path.is_relative_to(backup):
        raise MigrationError("receipt must be a file within the external backup root", exit_code=ExitCode.BLOCKED)
    preimage_root = backup / "preimage"
    if receipt_path == preimage_root or receipt_path.is_relative_to(preimage_root):
        raise MigrationError("receipt must not collide with backup pre-images", exit_code=ExitCode.BLOCKED)

    mutation_actions: list[tuple[Any, Path, bytes]] = []
    quarantined_paths = {
        item["path"] for item in (baseline_audit or {}).get("quarantinedPaths", [])
    }
    for action in plan.actions:
        if action.path in quarantined_paths:
            raise MigrationError(
                f"quarantined path entered recovery actions: {action.path}",
                exit_code=ExitCode.BLOCKED,
            )
        if action.operation not in {Operation.COPY.value, Operation.SIDECAR.value}:
            continue
        destination_relative = action.destination if action.operation == Operation.SIDECAR.value else action.path
        if not destination_relative:
            raise MigrationError(f"missing destination for {action.path}")
        if action.source_digest is None:
            raise MigrationError(f"mutation action has no source digest: {action.path}", exit_code=ExitCode.BLOCKED)
        try:
            source_data = source_reader(action)
        except MigrationError as exc:
            raise MigrationError(
                f"cannot stage migration source {action.path}: {exc}", exit_code=ExitCode.BLOCKED,
            ) from exc
        if not isinstance(source_data, bytes):
            raise MigrationError(f"migration source is not bytes: {action.path}", exit_code=ExitCode.BLOCKED)
        actual_source_digest = "sha256:" + sha256(source_data).hexdigest()
        if actual_source_digest != action.source_digest:
            raise MigrationError(
                f"stale plan: source changed after validation for {action.path}",
                exit_code=ExitCode.BLOCKED,
            )
        mutation_actions.append((action, contained_path(target, destination_relative), source_data))
    _validate_recovery_baseline_digest(plan, baseline_root, "stale recovery plan: baseline changed after validation")
    _validate_quarantined_target_states(
        target, quarantined_target_states,
        "stale recovery plan: quarantined target changed after validation",
    )
    project_state = None
    if getattr(plan, "adopt_partial", False):
        mutation_paths: set[str] = set()
        for action, _, _ in mutation_actions:
            destination = action.destination if action.operation == Operation.SIDECAR.value else action.path
            if not destination:
                raise MigrationError(f"missing destination for project state digest: {action.path}")
            mutation_paths.add(destination)
        project_state = project_state_digests(target, mutation_paths)

    try:
        backup.mkdir(parents=True)
    except OSError as exc:
        raise MigrationError(f"cannot create external backup root {backup}: {exc}", exit_code=ExitCode.BLOCKED) from exc

    journal: list[dict[str, Any]] = []
    for action, destination, _ in mutation_actions:
        destination_relative = action.destination if action.operation == Operation.SIDECAR.value else action.path
        pre_digest = digest_path(destination)
        expected_pre_digest = action.destination_digest if action.operation == Operation.SIDECAR.value else action.target_digest
        if pre_digest != expected_pre_digest:
            raise MigrationError(
                f"stale plan: target pre-image changed before backup for {destination_relative}",
                exit_code=ExitCode.BLOCKED,
            )
        backup_relative: str | None = None
        if pre_digest != MISSING_DIGEST:
            backup_relative = "preimage/" + destination_relative
            backup_path = contained_path(backup, backup_relative)
            try:
                backup_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(destination, backup_path, follow_symlinks=False)
            except OSError as exc:
                raise MigrationError(
                    f"cannot prepare backup pre-image for {destination_relative}: {exc}",
                    exit_code=ExitCode.BLOCKED,
                ) from exc
            if digest_path(backup_path) != pre_digest:
                raise MigrationError(
                    f"backup validation failed for {destination_relative}",
                    exit_code=ExitCode.BLOCKED,
                )
        journal.append({
            "sourcePath": action.path,
            "path": destination_relative,
            "operation": action.operation,
            "preDigest": pre_digest,
            "postDigest": None,
            "expectedPostDigest": action.source_digest,
            "backupPath": backup_relative,
            "createdParents": _missing_parents(destination, target),
            "state": "prepared",
        })
    preserved = {
        relative: digest_path(contained_path(target, relative))
        for relative in preserved_roots
    }
    receipt: dict[str, Any] = {
        "schemaVersion": ADOPTION_RECEIPT_SCHEMA_VERSION if getattr(plan, "adopt_partial", False) else RECEIPT_SCHEMA_VERSION,
        "status": "prepared",
        "planDigest": plan.plan_digest,
        "targetState": plan.target_state,
        "templateRoot": str(template),
        "targetRoot": str(target),
        "backupRoot": str(backup),
        "receiptPath": str(receipt_path),
        "journal": journal,
        "preservedDigests": preserved,
        "verificationCommands": [list(command) for command in plan.verification_commands],
        "verification": None,
        "receiptDigest": "",
    }
    if hasattr(plan, "source_admission"):
        receipt["sourceAdmission"] = dict(plan.source_admission)
    if getattr(plan, "adopt_partial", False):
        receipt["adoptPartial"] = True
        receipt["projectStateDigests"] = project_state
    if baseline_root is not None:
        receipt["baselineRoot"] = str(baseline_root)
        receipt["baselineAudit"] = baseline_audit
        receipt["quarantinedTargetStates"] = quarantined_target_states
    try:
        _write_receipt(receipt_path, receipt)
    except MigrationError as exc:
        raise MigrationError(
            f"cannot create prepared receipt {receipt_path}: {exc}", exit_code=ExitCode.BLOCKED,
        ) from exc
    try:
        fail_after = int(os.environ.get("HARNESS_MIGRATE_FAIL_AFTER", "-1"))
    except ValueError as exc:
        receipt["status"] = "apply_failed"
        receipt["failure"] = "HARNESS_MIGRATE_FAIL_AFTER must be an integer"
        _write_receipt(receipt_path, receipt)
        raise MigrationError(receipt["failure"], exit_code=ExitCode.APPLY_FAILED) from exc
    try:
        mutation_count = 0
        final_blockers = apply_blockers(target)
        if final_blockers:
            raise MigrationError("apply blocked before mutation: " + "; ".join(final_blockers), exit_code=ExitCode.BLOCKED)
        for entry in journal:
            current = digest_path(contained_path(target, entry["path"]))
            if current != entry["preDigest"]:
                raise MigrationError(f"stale plan: target pre-image changed after backup for {entry['path']}", exit_code=ExitCode.BLOCKED)
        _validate_recovery_baseline_digest(plan, baseline_root, "stale recovery plan: baseline changed before mutation")
        _validate_quarantined_target_states(
            target, quarantined_target_states,
            "stale recovery plan: quarantined target changed before mutation",
        )
        for (action, _, source_data), entry in zip(mutation_actions, journal):
            if fail_after >= 0 and mutation_count >= fail_after:
                raise OSError("injected apply failure")
            entry["state"] = "applying"
            _write_receipt(receipt_path, receipt)
            destination = contained_path(target, entry["path"])
            if digest_path(destination) != entry["preDigest"]:
                raise MigrationError(f"stale plan: target pre-image changed before write for {entry['path']}", exit_code=ExitCode.BLOCKED)
            _copy_bytes_atomic(destination, source_data)
            mutation_count += 1
            entry["postDigest"] = digest_path(destination)
            entry["state"] = "applied"
            _write_receipt(receipt_path, receipt)
            if entry["postDigest"] != entry["expectedPostDigest"]:
                raise OSError(f"installed content digest mismatch for {entry['path']}")
        _validate_quarantined_target_states(
            target, quarantined_target_states,
            "recovery changed a quarantined target",
        )
        receipt["status"] = "applied"
        _write_receipt(receipt_path, receipt)
        return receipt, receipt_path
    except Exception as exc:
        receipt["status"] = "apply_failed"
        receipt["failure"] = str(exc)
        exit_code = exc.exit_code if mutation_count == 0 and isinstance(exc, MigrationError) else ExitCode.APPLY_FAILED
        try:
            _write_receipt(receipt_path, receipt)
        except MigrationError as receipt_exc:
            raise MigrationError(
                f"apply failed; receipt update also failed; recover with existing receipt {receipt_path}: {exc}; {receipt_exc}",
                exit_code=ExitCode.APPLY_FAILED,
            ) from receipt_exc
        raise MigrationError(f"apply failed; recover with receipt {receipt_path}: {exc}", exit_code=exit_code) from exc


def apply_plan(plan: Plan, backup_value: str | None = None, receipt_value: str | None = None) -> tuple[dict[str, Any], Path]:
    template, target = _revalidate_plan(plan)

    def normal_source(action: Any) -> bytes:
        return _normal_source_bytes(template, target, plan, action)

    preserved_roots = PRESERVED_ROOTS if plan.target_state == "existing_trellis" or plan.adopt_partial else []
    return _apply_validated_transaction(
        plan, template, target, normal_source, preserved_roots,
        backup_value=backup_value, receipt_value=receipt_value,
    )


def rollback_receipt(receipt_path: Path) -> dict[str, Any]:
    try:
        receipt = load_receipt(receipt_path)
    except MigrationError as exc:
        raise MigrationError(str(exc), exit_code=ExitCode.ROLLBACK_REFUSED) from exc
    target, backup = validate_receipt_roots(receipt, receipt_path)
    if receipt["status"] not in {"prepared", "applied", "apply_failed", "verification_failed", "verified_incomplete", "verified", "rollback_failed"}:
        raise MigrationError(f"receipt status cannot be rolled back: {receipt['status']}", exit_code=ExitCode.ROLLBACK_REFUSED)
    _validate_quarantined_target_states(
        target, receipt.get("quarantinedTargetStates"),
        "quarantined target changed after recovery",
        exit_code=ExitCode.ROLLBACK_REFUSED,
    )
    for entry in receipt["journal"]:
        destination = contained_path(target, entry["path"])
        current = digest_path(destination)
        post_digest = entry.get("postDigest")
        if post_digest is None:
            if entry.get("state") not in {"prepared", "applying"} or current not in {entry["preDigest"], entry.get("expectedPostDigest")}:
                raise MigrationError(f"incomplete journal cannot prove post-image for {entry['path']}", exit_code=ExitCode.ROLLBACK_REFUSED)
        elif current not in {post_digest, entry["preDigest"]}:
            raise MigrationError(f"post-migration content changed: {entry['path']}", exit_code=ExitCode.ROLLBACK_REFUSED)
        if entry["preDigest"] != MISSING_DIGEST:
            backup_relative = entry.get("backupPath")
            if not backup_relative:
                raise MigrationError(f"missing backup path for {entry['path']}", exit_code=ExitCode.ROLLBACK_REFUSED)
            preimage = contained_path(backup, backup_relative)
            if digest_path(preimage) != entry["preDigest"]:
                raise MigrationError(f"backup pre-image changed: {entry['path']}", exit_code=ExitCode.ROLLBACK_REFUSED)
    try:
        for entry in reversed(receipt["journal"]):
            destination = contained_path(target, entry["path"])
            if digest_path(destination) != entry["preDigest"]:
                if entry["preDigest"] == MISSING_DIGEST:
                    destination.unlink()
                else:
                    backup_relative = entry.get("backupPath")
                    if not backup_relative:
                        raise MigrationError(f"missing backup path for {entry['path']}", exit_code=ExitCode.ROLLBACK_REFUSED)
                    preimage = contained_path(backup, backup_relative)
                    if digest_path(preimage) != entry["preDigest"]:
                        raise MigrationError(f"backup pre-image changed: {entry['path']}", exit_code=ExitCode.ROLLBACK_REFUSED)
                    _copy_bytes_atomic(destination, preimage.read_bytes())
            for relative in reversed(entry.get("createdParents", [])):
                directory = contained_path(target, relative)
                if directory.exists() and directory.is_dir() and not any(directory.iterdir()):
                    directory.rmdir()
        _validate_quarantined_target_states(
            target, receipt.get("quarantinedTargetStates"),
            "rollback changed a quarantined target",
            exit_code=ExitCode.ROLLBACK_REFUSED,
        )
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
                f"rollback failed; receipt update also failed; retry with existing receipt {receipt_path}: {exc}; {receipt_exc}",
                exit_code=ExitCode.ROLLBACK_REFUSED,
            ) from receipt_exc
        raise MigrationError(f"rollback failed and can be retried: {exc}", exit_code=ExitCode.ROLLBACK_REFUSED) from exc
