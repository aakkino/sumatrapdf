from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path, PurePosixPath
import re
import stat
from typing import Any

from common.paths import get_developer

from .codec import MISSING_DIGEST, digest_path, digest_value, is_link_like, read_json
from .manifest import Manifest, exported_files, load_manifest, matching_rule
from .models import Action, Decision, ExitCode, MigrationError, Operation, RuleKind, TargetState
from .planner import SIDECAR_SUFFIX, VERIFICATION_COMMANDS, _decision_id, _destination_conflicts
from .safety import PureParts, apply_blockers, classify_target, contained_path, resolve_directory, validate_root_relationship


RECOVERY_PLAN_SCHEMA_VERSION = 2
RECOVERY_TRANSACTION_TYPE = "recovery"
BASELINE_HASH_VERIFIED = "verified"
BASELINE_HASH_VERIFIED_WITH_QUARANTINE = "verified_with_quarantined_merge_required"
BASELINE_QUARANTINE_REASON = "baseline_digest_mismatch_merge_required"
RECOVERY_PRESERVED_ROOTS = [
    ".trellis/spec",
    ".trellis/tasks",
    ".trellis/workspace",
    ".trellis/.developer",
    ".trellis/.current-task",
    ".trellis/.runtime",
]
RECOVERY_EXCLUDED_KINDS = {
    RuleKind.PRESERVE,
    RuleKind.RUNTIME_EXCLUDED,
    RuleKind.FRESH_ONLY_SKELETON,
    RuleKind.SUPPORT_ONLY,
}
RECOVERY_PLAN_KEYS = {
    "schemaVersion", "transactionType", "templateVersion", "templateRoot",
    "targetRoot", "targetState", "baselineRoot", "baselineVersion",
    "baselineDigest", "baselineAudit", "quarantinedTargetStates",
    "manifestDigest", "actions", "blockers", "conflicts", "decisions",
    "verificationCommands", "planDigest",
}
BASELINE_AUDIT_KEYS = {"hashStatus", "quarantinedPaths"}
QUARANTINED_PATH_KEYS = {
    "path", "expectedDigest", "actualDigest", "ruleKind", "reason",
}
QUARANTINED_TARGET_STATE_KEYS = {"path", "preDigest", "postDigest"}


@dataclass(frozen=True)
class QuarantinedPathAudit:
    path: str
    expected_digest: str
    actual_digest: str
    rule_kind: str
    reason: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "expectedDigest": self.expected_digest,
            "actualDigest": self.actual_digest,
            "ruleKind": self.rule_kind,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class BaselineAudit:
    hash_status: str
    quarantined_paths: tuple[QuarantinedPathAudit, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "hashStatus": self.hash_status,
            "quarantinedPaths": [item.to_dict() for item in self.quarantined_paths],
        }


@dataclass(frozen=True)
class QuarantinedTargetState:
    path: str
    pre_digest: str
    post_digest: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "preDigest": self.pre_digest,
            "postDigest": self.post_digest,
        }


@dataclass
class RecoveryPlan:
    schema_version: int
    transaction_type: str
    template_version: str
    template_root: str
    target_root: str
    target_state: str
    baseline_root: str
    baseline_version: str
    baseline_digest: str
    baseline_audit: BaselineAudit
    quarantined_target_states: list[QuarantinedTargetState]
    manifest_digest: str
    actions: list[Action]
    blockers: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    verification_commands: list[list[str]] = field(default_factory=list)
    plan_digest: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for source, destination in (
            ("schema_version", "schemaVersion"),
            ("transaction_type", "transactionType"),
            ("template_version", "templateVersion"),
            ("template_root", "templateRoot"),
            ("target_root", "targetRoot"),
            ("target_state", "targetState"),
            ("baseline_root", "baselineRoot"),
            ("baseline_version", "baselineVersion"),
            ("baseline_digest", "baselineDigest"),
            ("baseline_audit", "baselineAudit"),
            ("quarantined_target_states", "quarantinedTargetStates"),
            ("manifest_digest", "manifestDigest"),
            ("verification_commands", "verificationCommands"),
            ("plan_digest", "planDigest"),
        ):
            data[destination] = data.pop(source)
        data["baselineAudit"] = self.baseline_audit.to_dict()
        data["quarantinedTargetStates"] = [
            item.to_dict() for item in self.quarantined_target_states
        ]
        for action in data["actions"]:
            action["sourceDigest"] = action.pop("source_digest")
            action["targetDigest"] = action.pop("target_digest")
            action["destinationDigest"] = action.pop("destination_digest")
            action["decisionId"] = action.pop("decision_id")
        for decision in data["decisions"]:
            decision["allowedChoices"] = decision.pop("allowed_choices")
        return data


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MigrationError(f"recovery plan {label} must be a non-empty string")
    return value


def _string_list(value: object, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MigrationError(f"recovery plan {label} must be an array of strings")
    if not allow_empty and not value:
        raise MigrationError(f"recovery plan {label} must not be empty")
    return list(value)


def _normalized_relative(value: object, label: str) -> str:
    relative = _require_string(value, label)
    try:
        parts = PureParts(relative)
    except MigrationError as exc:
        raise MigrationError(f"{label} must be a normalized relative path") from exc
    if PurePosixPath(*parts).as_posix() != relative:
        raise MigrationError(f"{label} must be a normalized relative path")
    return relative


def _canonical_digest(value: object, label: str, *, allow_missing: bool = False) -> str:
    digest = _require_string(value, label)
    if allow_missing and digest == MISSING_DIGEST:
        return digest
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise MigrationError(f"{label} must be a canonical SHA-256 digest")
    return digest


def baseline_audit_from_dict(value: object, label: str = "recovery plan baselineAudit") -> BaselineAudit:
    if not isinstance(value, dict) or set(value) != BASELINE_AUDIT_KEYS:
        raise MigrationError(f"{label} has unknown or missing fields")
    status = _require_string(value["hashStatus"], f"{label} hashStatus")
    items = value["quarantinedPaths"]
    if not isinstance(items, list):
        raise MigrationError(f"{label} quarantinedPaths must be an array")
    parsed: list[QuarantinedPathAudit] = []
    paths: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != QUARANTINED_PATH_KEYS:
            raise MigrationError(f"{label} quarantined path has unknown or missing fields")
        path = _normalized_relative(item["path"], f"{label} quarantined path")
        if path in paths:
            raise MigrationError(f"{label} contains duplicate quarantined paths")
        paths.add(path)
        expected = _canonical_digest(item["expectedDigest"], f"{label} expectedDigest")
        actual = _canonical_digest(item["actualDigest"], f"{label} actualDigest")
        if expected == actual:
            raise MigrationError(f"{label} quarantined digests must differ")
        if item["ruleKind"] != RuleKind.MERGE_REQUIRED.value:
            raise MigrationError(f"{label} quarantined ruleKind is invalid")
        if item["reason"] != BASELINE_QUARANTINE_REASON:
            raise MigrationError(f"{label} quarantined reason is invalid")
        parsed.append(QuarantinedPathAudit(
            path, expected, actual, item["ruleKind"], item["reason"],
        ))
    if parsed != sorted(parsed, key=lambda item: item.path):
        raise MigrationError(f"{label} quarantined paths are not canonically ordered")
    expected_status = BASELINE_HASH_VERIFIED_WITH_QUARANTINE if parsed else BASELINE_HASH_VERIFIED
    if status != expected_status:
        raise MigrationError(f"{label} hashStatus is inconsistent")
    return BaselineAudit(status, tuple(parsed))


def quarantined_target_states_from_dict(
    value: object, label: str = "recovery plan quarantinedTargetStates",
) -> list[QuarantinedTargetState]:
    if not isinstance(value, list):
        raise MigrationError(f"{label} must be an array")
    parsed: list[QuarantinedTargetState] = []
    paths: set[str] = set()
    for item in value:
        if not isinstance(item, dict) or set(item) != QUARANTINED_TARGET_STATE_KEYS:
            raise MigrationError(f"{label} entry has unknown or missing fields")
        path = _normalized_relative(item["path"], f"{label} path")
        if path in paths:
            raise MigrationError(f"{label} contains duplicate paths")
        paths.add(path)
        pre_digest = _canonical_digest(item["preDigest"], f"{label} preDigest", allow_missing=True)
        post_digest = _canonical_digest(item["postDigest"], f"{label} postDigest", allow_missing=True)
        if pre_digest != post_digest:
            raise MigrationError(f"{label} must record an unchanged target state")
        parsed.append(QuarantinedTargetState(path, pre_digest, post_digest))
    if parsed != sorted(parsed, key=lambda item: item.path):
        raise MigrationError(f"{label} is not canonically ordered")
    return parsed


def recovery_plan_from_dict(data: dict[str, Any]) -> RecoveryPlan:
    from .models import ACTION_KEYS, DECISION_KEYS

    if set(data) != RECOVERY_PLAN_KEYS:
        raise MigrationError("recovery plan has unknown or missing fields")
    if not isinstance(data["schemaVersion"], int) or isinstance(data["schemaVersion"], bool):
        raise MigrationError("recovery plan schemaVersion must be an integer")
    strings = {
        key: _require_string(data[key], key)
        for key in (
            "transactionType", "templateVersion", "templateRoot", "targetRoot",
            "targetState", "baselineRoot", "baselineVersion", "baselineDigest",
            "manifestDigest", "planDigest",
        )
    }
    if strings["transactionType"] != RECOVERY_TRANSACTION_TYPE:
        raise MigrationError("recovery plan transactionType is invalid")
    if strings["targetState"] != TargetState.UNSUPPORTED_PARTIAL.value:
        raise MigrationError("recovery plan targetState is invalid")
    if not isinstance(data["actions"], list) or not isinstance(data["decisions"], list):
        raise MigrationError("recovery plan actions and decisions must be arrays")
    actions: list[Action] = []
    for item in data["actions"]:
        if not isinstance(item, dict) or set(item) != ACTION_KEYS:
            raise MigrationError("recovery plan action has unknown or missing fields")
        for key in ("path", "kind", "operation", "reason"):
            _require_string(item[key], f"action {key}")
        if item["kind"] not in {kind.value for kind in RuleKind}:
            raise MigrationError("recovery plan action kind is invalid")
        if item["operation"] not in {operation.value for operation in Operation}:
            raise MigrationError("recovery plan action operation is invalid")
        optional = {}
        for key in ("sourceDigest", "targetDigest", "destination", "destinationDigest", "decisionId"):
            if item[key] is not None and not isinstance(item[key], str):
                raise MigrationError(f"recovery plan action {key} must be a string or null")
            optional[key] = item[key]
        actions.append(Action(
            item["path"], item["kind"], item["operation"], item["reason"],
            optional["sourceDigest"], optional["targetDigest"], optional["destination"],
            optional["destinationDigest"], optional["decisionId"],
        ))
    decisions: list[Decision] = []
    decision_ids: set[str] = set()
    for item in data["decisions"]:
        if not isinstance(item, dict) or set(item) != DECISION_KEYS:
            raise MigrationError("recovery plan decision has unknown or missing fields")
        identifier = _require_string(item["id"], "decision id")
        reason = _require_string(item["reason"], "decision reason")
        paths = _string_list(item["paths"], "decision paths", allow_empty=False)
        choices = _string_list(item["allowedChoices"], "decision allowedChoices", allow_empty=False)
        selection = item["selection"]
        if selection is not None and not isinstance(selection, str):
            raise MigrationError("recovery plan decision selection must be a string or null")
        if identifier in decision_ids or len(set(choices)) != len(choices) or selection is not None and selection not in choices:
            raise MigrationError(f"recovery plan decision is invalid: {identifier}")
        decision_ids.add(identifier)
        decisions.append(Decision(identifier, paths, reason, choices, selection))
    commands = data["verificationCommands"]
    if not isinstance(commands, list) or not all(isinstance(command, list) for command in commands):
        raise MigrationError("recovery plan verificationCommands must be an array of command arrays")
    baseline_audit = baseline_audit_from_dict(data["baselineAudit"])
    target_states = quarantined_target_states_from_dict(data["quarantinedTargetStates"])
    audit_paths = [item.path for item in baseline_audit.quarantined_paths]
    if [item.path for item in target_states] != audit_paths:
        raise MigrationError("recovery plan quarantine target coverage is invalid")
    action_paths = {item.path for item in actions}
    decision_paths = {path for item in decisions for path in item.paths}
    if action_paths.intersection(audit_paths) or decision_paths.intersection(audit_paths):
        raise MigrationError("recovery plan quarantined paths must not enter actions or decisions")
    return RecoveryPlan(
        data["schemaVersion"], strings["transactionType"], strings["templateVersion"],
        strings["templateRoot"], strings["targetRoot"], strings["targetState"],
        strings["baselineRoot"], strings["baselineVersion"], strings["baselineDigest"],
        baseline_audit, target_states, strings["manifestDigest"], actions,
        _string_list(data["blockers"], "blockers"),
        _string_list(data["conflicts"], "conflicts"), decisions,
        [_string_list(command, "verification command", allow_empty=False) for command in commands],
        strings["planDigest"],
    )


def calculate_recovery_plan_digest(plan: RecoveryPlan) -> str:
    value = plan.to_dict()
    value.pop("planDigest", None)
    return digest_value(value)


def validate_recovery_plan_digest(plan: RecoveryPlan) -> None:
    if (
        plan.schema_version != RECOVERY_PLAN_SCHEMA_VERSION
        or plan.transaction_type != RECOVERY_TRANSACTION_TYPE
        or plan.plan_digest != calculate_recovery_plan_digest(plan)
    ):
        raise MigrationError("recovery plan digest or schema is invalid", exit_code=ExitCode.BLOCKED)


def _validate_tree_shape(root: Path) -> None:
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except OSError as exc:
            raise MigrationError(f"cannot inspect recovery baseline: {directory}: {exc}", exit_code=ExitCode.BLOCKED) from exc
        for entry in entries:
            path = Path(entry.path)
            try:
                metadata = path.lstat()
            except OSError as exc:
                raise MigrationError(f"cannot inspect recovery baseline entry: {path}: {exc}", exit_code=ExitCode.BLOCKED) from exc
            if is_link_like(path):
                raise MigrationError(f"recovery baseline contains a link-like entry: {path}", exit_code=ExitCode.BLOCKED)
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            elif not stat.S_ISREG(metadata.st_mode):
                raise MigrationError(f"recovery baseline contains an unsupported entry: {path}", exit_code=ExitCode.BLOCKED)


def _validate_baseline(
    target: Path, baseline_value: str, manifest: Manifest, complete_paths: set[str],
) -> tuple[Path, str, BaselineAudit]:
    trellis = contained_path(target, ".trellis", allow_missing=False)
    baseline = resolve_directory(baseline_value, "recovery baseline")
    if baseline.parent != trellis or not re.fullmatch(r"\.backup-[A-Za-z0-9][A-Za-z0-9T_.-]*", baseline.name):
        raise MigrationError("recovery baseline must be an explicitly selected direct .trellis/.backup-* directory", exit_code=ExitCode.BLOCKED)
    if is_link_like(baseline) or baseline.resolve(strict=False) != baseline:
        raise MigrationError("recovery baseline must not be link-like or rebound", exit_code=ExitCode.BLOCKED)
    _validate_tree_shape(baseline)
    version_path = contained_path(baseline, ".trellis/.version", allow_missing=False)
    try:
        version = version_path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        raise MigrationError(f"cannot read recovery baseline version: {exc}", exit_code=ExitCode.BLOCKED) from exc
    if version != manifest.template_version:
        raise MigrationError(
            f"recovery baseline version {version!r} does not match template version {manifest.template_version!r}",
            exit_code=ExitCode.BLOCKED,
        )
    hashes_path = contained_path(baseline, ".trellis/.template-hashes.json", allow_missing=False)
    try:
        hashes_document = read_json(hashes_path)
    except MigrationError as exc:
        raise MigrationError(
            f"cannot validate recovery baseline template hashes: {exc}",
            exit_code=ExitCode.BLOCKED,
        ) from exc
    if set(hashes_document) != {"__version", "hashes"} or hashes_document["__version"] != 2:
        raise MigrationError("recovery baseline template hashes schema is invalid", exit_code=ExitCode.BLOCKED)
    hashes = hashes_document["hashes"]
    if not isinstance(hashes, dict) or not hashes or not all(
        isinstance(relative, str) and isinstance(expected, str) and re.fullmatch(r"[0-9a-f]{64}", expected)
        for relative, expected in hashes.items()
    ):
        raise MigrationError("recovery baseline template hashes are invalid", exit_code=ExitCode.BLOCKED)
    quarantined: list[QuarantinedPathAudit] = []
    for relative, expected in sorted(hashes.items()):
        try:
            normalized = _normalized_relative(relative, "recovery baseline hash path")
            path = contained_path(baseline, normalized, allow_missing=False)
        except MigrationError as exc:
            raise MigrationError(
                f"cannot validate recovery baseline hash path: {relative}: {exc}",
                exit_code=ExitCode.BLOCKED,
            ) from exc
        if not path.is_file() or is_link_like(path):
            raise MigrationError(
                f"recovery baseline hash does not reference a regular file: {normalized}",
                exit_code=ExitCode.BLOCKED,
            )
        try:
            actual = digest_path(path)
        except MigrationError as exc:
            raise MigrationError(
                f"cannot validate recovery baseline hash: {normalized}: {exc}",
                exit_code=ExitCode.BLOCKED,
            ) from exc
        expected_digest = "sha256:" + expected
        if actual == expected_digest:
            continue
        eligible = False
        if normalized in complete_paths:
            try:
                eligible = matching_rule(manifest.rules, normalized).kind == RuleKind.MERGE_REQUIRED
            except MigrationError:
                eligible = False
        if not eligible:
            raise MigrationError(f"recovery baseline hash mismatch: {normalized}", exit_code=ExitCode.BLOCKED)
        quarantined.append(QuarantinedPathAudit(
            normalized,
            expected_digest,
            actual,
            RuleKind.MERGE_REQUIRED.value,
            BASELINE_QUARANTINE_REASON,
        ))
    baseline_developer = contained_path(baseline, ".trellis/.developer", allow_missing=False)
    try:
        baseline_identity = get_developer(baseline) if baseline_developer.is_file() else None
    except (OSError, UnicodeError) as exc:
        raise MigrationError(
            f"cannot read recovery baseline developer identity: {exc}",
            exit_code=ExitCode.BLOCKED,
        ) from exc
    if not baseline_identity:
        raise MigrationError("recovery baseline developer identity is missing", exit_code=ExitCode.BLOCKED)
    live_developer = contained_path(target, ".trellis/.developer")
    if live_developer.exists():
        try:
            live_identity = get_developer(target) if live_developer.is_file() else None
        except (OSError, UnicodeError) as exc:
            raise MigrationError(
                f"cannot read target developer identity: {exc}", exit_code=ExitCode.BLOCKED,
            ) from exc
        if not live_identity or live_identity != baseline_identity:
            raise MigrationError("recovery baseline developer identity is incompatible with the target", exit_code=ExitCode.BLOCKED)
    status = BASELINE_HASH_VERIFIED_WITH_QUARANTINE if quarantined else BASELINE_HASH_VERIFIED
    return baseline, version, BaselineAudit(status, tuple(quarantined))


def _is_preserved_path(relative: str) -> bool:
    return any(relative == root or relative.startswith(root + "/") for root in RECOVERY_PRESERVED_ROOTS)


def build_recovery_plan(template_value: str, target_value: str, baseline_value: str) -> RecoveryPlan:
    template = resolve_directory(template_value, "template")
    target = resolve_directory(target_value, "target")
    validate_root_relationship(template, target)
    manifest = load_manifest(template)
    complete_paths = set(exported_files(template, manifest, "complete"))
    state = classify_target(target)
    if state != TargetState.UNSUPPORTED_PARTIAL:
        raise MigrationError(
            f"recovery requires an unsupported_partial target, got {state.value}",
            exit_code=ExitCode.BLOCKED,
        )
    blockers = apply_blockers(target)
    if blockers:
        raise MigrationError("recovery plan blocked: " + "; ".join(blockers), exit_code=ExitCode.BLOCKED)
    baseline, baseline_version, baseline_audit = _validate_baseline(
        target, baseline_value, manifest, complete_paths,
    )
    quarantined_paths = {item.path for item in baseline_audit.quarantined_paths}
    quarantined_target_states: list[QuarantinedTargetState] = []
    for relative in sorted(quarantined_paths):
        destination = contained_path(target, relative)
        if destination.exists() and (not destination.is_file() or is_link_like(destination)):
            raise MigrationError(
                f"unsupported target entry for quarantined path: {relative}",
                exit_code=ExitCode.BLOCKED,
            )
        target_digest = digest_path(destination)
        quarantined_target_states.append(QuarantinedTargetState(
            relative, target_digest, target_digest,
        ))
    actions: list[Action] = []
    decisions: list[Decision] = []
    conflicts: list[str] = []
    for relative in sorted(complete_paths):
        if relative in quarantined_paths:
            continue
        rule = matching_rule(manifest.rules, relative)
        if rule.kind in RECOVERY_EXCLUDED_KINDS or _is_preserved_path(relative):
            continue
        source = contained_path(baseline, relative)
        if not source.exists():
            continue
        if not source.is_file() or is_link_like(source):
            raise MigrationError(f"unsupported recovery baseline entry: {relative}", exit_code=ExitCode.BLOCKED)
        destination = contained_path(target, relative)
        if destination.exists() and not destination.is_file():
            raise MigrationError(f"unsupported target entry (expected a file): {relative}", exit_code=ExitCode.BLOCKED)
        incoming_digest = digest_path(source)
        current_digest = digest_path(destination)
        if current_digest == incoming_digest:
            actions.append(Action(relative, rule.kind.value, Operation.SKIP.value, "target already matches recovery baseline", incoming_digest, current_digest))
        elif current_digest == MISSING_DIGEST:
            actions.append(Action(relative, rule.kind.value, Operation.COPY.value, "managed foundation path is absent", incoming_digest, current_digest))
        else:
            identifier = _decision_id("recover", [relative])
            decisions.append(Decision(identifier, [relative], "live path differs from the selected recovery baseline", ["sidecar", "keep", "replace"]))
            conflicts.append(relative)
            actions.append(Action(relative, rule.kind.value, Operation.SKIP.value, "awaiting recovery collision decision", incoming_digest, current_digest, decision_id=identifier))
    required = {".trellis/.version", ".trellis/.template-hashes.json", ".trellis/config.yaml", ".trellis/workflow.md"}
    missing_required = sorted(required - {action.path for action in actions})
    if missing_required:
        raise MigrationError("recovery baseline lacks required managed foundation paths: " + ", ".join(missing_required), exit_code=ExitCode.BLOCKED)
    actions.sort(key=lambda item: (item.path, item.operation))
    destination_conflicts = _destination_conflicts([action.path for action in actions])
    if destination_conflicts:
        raise MigrationError("; ".join(destination_conflicts), exit_code=ExitCode.BLOCKED)
    decisions.sort(key=lambda item: item.id)
    try:
        baseline_digest = digest_path(baseline)
    except MigrationError as exc:
        raise MigrationError(
            f"cannot digest recovery baseline: {exc}", exit_code=ExitCode.BLOCKED,
        ) from exc
    plan = RecoveryPlan(
        RECOVERY_PLAN_SCHEMA_VERSION, RECOVERY_TRANSACTION_TYPE, manifest.template_version,
        str(template), str(target), state.value, str(baseline), baseline_version,
        baseline_digest, baseline_audit, quarantined_target_states,
        manifest.digest, actions, [], sorted(conflicts), decisions,
        [list(command) for command in VERIFICATION_COMMANDS],
    )
    plan.plan_digest = calculate_recovery_plan_digest(plan)
    return plan


def resolve_recovery_plan(plan: RecoveryPlan, selections: dict[str, str]) -> RecoveryPlan:
    validate_recovery_plan_digest(plan)
    known = {decision.id: decision for decision in plan.decisions}
    unknown = set(selections) - set(known)
    if unknown:
        raise MigrationError("unknown recovery decision IDs: " + ", ".join(sorted(unknown)))
    for identifier, choice in selections.items():
        decision = known[identifier]
        if choice not in decision.allowed_choices:
            raise MigrationError(f"invalid recovery choice {choice!r} for {identifier}")
        decision.selection = choice
        for action in plan.actions:
            if action.decision_id != identifier:
                continue
            if choice == "replace":
                action.operation = Operation.COPY.value
                action.reason = "resolved recovery decision: replace"
                action.destination = None
                action.destination_digest = None
            elif choice == "sidecar":
                action.operation = Operation.SIDECAR.value
                action.reason = "resolved recovery decision: sidecar"
                action.destination = action.path + SIDECAR_SUFFIX
                destination = contained_path(Path(plan.target_root), action.destination)
                if destination.exists() and not destination.is_file():
                    raise MigrationError(f"unsupported recovery sidecar target entry: {action.destination}", exit_code=ExitCode.BLOCKED)
                action.destination_digest = digest_path(destination)
            else:
                action.operation = Operation.PRESERVE.value
                action.reason = "resolved recovery decision: keep"
                action.destination = None
                action.destination_digest = None
    destinations = [
        action.destination if action.operation == Operation.SIDECAR.value else action.path
        for action in plan.actions if action.operation in {Operation.COPY.value, Operation.SIDECAR.value}
    ]
    conflicts = _destination_conflicts([path for path in destinations if path])
    if conflicts:
        raise MigrationError("; ".join(conflicts), exit_code=ExitCode.BLOCKED)
    plan.plan_digest = calculate_recovery_plan_digest(plan)
    return plan


def recovery_source_bytes(plan: RecoveryPlan, relative: str) -> bytes:
    if relative in {item.path for item in plan.baseline_audit.quarantined_paths}:
        raise MigrationError(
            f"quarantined recovery source must not be read: {relative}",
            exit_code=ExitCode.BLOCKED,
        )
    path = contained_path(Path(plan.baseline_root), relative, allow_missing=False)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise MigrationError(f"cannot read recovery baseline source: {relative}: {exc}", exit_code=ExitCode.BLOCKED) from exc


def revalidate_recovery_plan(plan: RecoveryPlan) -> tuple[Path, Path, Path]:
    validate_recovery_plan_digest(plan)
    template = resolve_directory(plan.template_root, "template")
    target = resolve_directory(plan.target_root, "target")
    validate_root_relationship(template, target)
    manifest = load_manifest(template)
    if manifest.digest != plan.manifest_digest:
        raise MigrationError("manifest changed after recovery planning", exit_code=ExitCode.BLOCKED)
    if classify_target(target) != TargetState.UNSUPPORTED_PARTIAL:
        raise MigrationError("target state changed after recovery planning", exit_code=ExitCode.BLOCKED)
    blockers = apply_blockers(target)
    if blockers:
        raise MigrationError("recovery apply blocked: " + "; ".join(blockers), exit_code=ExitCode.BLOCKED)
    if plan.blockers:
        raise MigrationError("recovery plan contains blockers: " + "; ".join(plan.blockers), exit_code=ExitCode.BLOCKED)
    unresolved = [decision.id for decision in plan.decisions if decision.selection is None]
    if unresolved:
        raise MigrationError("recovery plan has unresolved decisions: " + ", ".join(unresolved), exit_code=ExitCode.UNRESOLVED)
    expected = build_recovery_plan(str(template), str(target), plan.baseline_root)
    selections = {decision.id: decision.selection for decision in plan.decisions if decision.selection is not None}
    try:
        resolve_recovery_plan(expected, selections)
    except MigrationError as exc:
        raise MigrationError(
            "recovery plan no longer matches the canonical recovery plan",
            exit_code=ExitCode.BLOCKED,
        ) from exc
    if expected.to_dict() != plan.to_dict():
        raise MigrationError("recovery plan no longer matches the canonical recovery plan", exit_code=ExitCode.BLOCKED)
    baseline = Path(plan.baseline_root)
    quarantined_paths = {item.path for item in plan.baseline_audit.quarantined_paths}
    if quarantined_paths.intersection(action.path for action in plan.actions):
        raise MigrationError("recovery plan quarantined paths entered actions", exit_code=ExitCode.BLOCKED)
    for state in plan.quarantined_target_states:
        if digest_path(contained_path(target, state.path)) != state.pre_digest:
            raise MigrationError(
                f"stale recovery plan: quarantined target pre-image changed for {state.path}",
                exit_code=ExitCode.BLOCKED,
            )
    for action in plan.actions:
        if digest_path(contained_path(target, action.path)) != action.target_digest:
            raise MigrationError(f"stale recovery plan: target pre-image changed for {action.path}", exit_code=ExitCode.BLOCKED)
        if action.operation == Operation.SIDECAR.value and action.destination:
            if digest_path(contained_path(target, action.destination)) != action.destination_digest:
                raise MigrationError(f"stale recovery plan: sidecar pre-image changed for {action.destination}", exit_code=ExitCode.BLOCKED)
        if action.source_digest is not None and digest_path(contained_path(baseline, action.path, allow_missing=False)) != action.source_digest:
            raise MigrationError(f"stale recovery plan: baseline source changed for {action.path}", exit_code=ExitCode.BLOCKED)
    return template, target, baseline


def apply_recovery_plan(plan: RecoveryPlan, backup_value: str | None = None, receipt_value: str | None = None):
    template, target, baseline = revalidate_recovery_plan(plan)
    from .transaction import _apply_validated_transaction

    return _apply_validated_transaction(
        plan, template, target,
        lambda action: recovery_source_bytes(plan, action.path),
        [*RECOVERY_PRESERVED_ROOTS, baseline.relative_to(target).as_posix()],
        backup_value=backup_value,
        receipt_value=receipt_value,
        baseline_root=baseline,
        baseline_audit=plan.baseline_audit.to_dict(),
        quarantined_target_states=[item.to_dict() for item in plan.quarantined_target_states],
    )
