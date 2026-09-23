from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum
import re
from typing import Any


class ExitCode(IntEnum):
    OK = 0
    INVALID_INPUT = 2
    BLOCKED = 3
    UNRESOLVED = 4
    APPLY_FAILED = 5
    VERIFICATION_FAILED = 6
    ROLLBACK_REFUSED = 7


class RuleKind(str, Enum):
    REPLACEABLE_MANAGED = "replaceable_managed"
    MERGE_REQUIRED = "merge_required"
    PRESERVE = "preserve"
    RUNTIME_EXCLUDED = "runtime_excluded"
    FRESH_ONLY_SKELETON = "fresh_only_skeleton"
    SUPPORT_ONLY = "support_only"


class TargetState(str, Enum):
    FRESH = "fresh"
    EXISTING_TRELLIS = "existing_trellis"
    UNSUPPORTED_PARTIAL = "unsupported_partial"
    UNSAFE = "unsafe"


class Operation(str, Enum):
    COPY = "copy"
    SIDECAR = "sidecar"
    PRESERVE = "preserve"
    SKIP = "skip"


class MigrationError(Exception):
    def __init__(
        self,
        message: str,
        exit_code: ExitCode = ExitCode.INVALID_INPUT,
        *,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.exit_code = exit_code
        self.details = details


ROUTE_CATALOG: dict[str, dict[str, tuple[str, str]]] = {
    "main": {
        "coordination": ("gpt-5.6-sol", "medium"),
        "planning": ("gpt-5.6-sol", "medium"),
    },
    "subagent-default": {"bounded_worker": ("gpt-5.6-terra", "high")},
    "role:research": {"exploration": ("gpt-5.6-terra", "medium")},
    "role:debug": {"debugging": ("gpt-5.6-sol", "low")},
    "role:review": {"review": ("gpt-5.6-sol", "high")},
    "role:audit": {"audit": ("gpt-5.6-sol", "high")},
    "role:release": {"release": ("gpt-5.6-sol", "high")},
    "dispatch:implement:default": {"bounded_worker": ("gpt-5.6-terra", "high")},
    "dispatch:implement:hard": {"hard_implementation": ("gpt-5.6-sol", "medium")},
    "dispatch:check:default": {
        "checking": ("gpt-5.6-terra", "max"),
        "checking_sol_medium": ("gpt-5.6-sol", "medium"),
    },
    "dispatch:check:hard": {"hard_checking": ("gpt-5.6-sol", "xhigh")},
}

DISPATCH_CONFIG_PATH = ".codex/trellis-dispatch.toml"

ROUTE_TARGETS = {
    "main": ".codex/config.toml",
    "subagent-default": ".codex/config.toml",
    "role:research": ".codex/agents/trellis-research.toml",
    "role:debug": ".codex/agents/trellis-debug.toml",
    "role:review": ".codex/agents/trellis-review.toml",
    "role:audit": ".codex/agents/trellis-audit.toml",
    "role:release": ".codex/agents/trellis-release.toml",
    "dispatch:implement:default": DISPATCH_CONFIG_PATH,
    "dispatch:implement:hard": DISPATCH_CONFIG_PATH,
    "dispatch:check:default": DISPATCH_CONFIG_PATH,
    "dispatch:check:hard": DISPATCH_CONFIG_PATH,
}

ROUTE_TABLES: dict[str, tuple[str, ...]] = {
    "main": (),
    "subagent-default": ("agents",),
    "role:research": (),
    "role:debug": (),
    "role:review": (),
    "role:audit": (),
    "role:release": (),
    "dispatch:implement:default": ("implement", "default"),
    "dispatch:implement:hard": ("implement", "hard"),
    "dispatch:check:default": ("check", "default"),
    "dispatch:check:hard": ("check", "hard"),
}

ROUTE_FIELDS: dict[str, tuple[str, str]] = {
    scope: ("default_subagent_model", "default_subagent_reasoning_effort")
    if scope == "subagent-default"
    else ("model", "model_reasoning_effort")
    for scope in ROUTE_CATALOG
}

DISPATCH_ROUTE_TABLES = frozenset(
    table for scope, table in ROUTE_TABLES.items() if scope.startswith("dispatch:")
)


@dataclass(frozen=True)
class RouteOverride:
    scope: str
    route: str | None
    model: str
    effort: str


ROUTE_VALUE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+@-]*\Z")


def is_safe_route_value(value: object) -> bool:
    """Return whether a raw model or effort is safe in the CLI and TOML writer."""
    return isinstance(value, str) and ROUTE_VALUE_PATTERN.fullmatch(value) is not None


def has_dispatch_override_for_path(relative: str, overrides: tuple[RouteOverride, ...]) -> bool:
    return any(
        item.scope.startswith("dispatch:") and ROUTE_TARGETS[item.scope] == relative
        for item in overrides
    )


@dataclass(frozen=True)
class MigrationRule:
    path: str
    kind: RuleKind
    modes: tuple[str, ...]
    on_existing: str
    on_modified: str
    source_required: bool


@dataclass
class Action:
    path: str
    kind: str
    operation: str
    reason: str
    source_digest: str | None
    target_digest: str | None
    destination: str | None = None
    destination_digest: str | None = None
    decision_id: str | None = None


@dataclass
class Decision:
    id: str
    paths: list[str]
    reason: str
    allowed_choices: list[str]
    selection: str | None = None


@dataclass
class Plan:
    schema_version: int
    template_version: str
    template_root: str
    target_root: str
    target_state: str
    developer: str | None
    manifest_digest: str
    profile: str | None
    actions: list[Action]
    blockers: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    verification_commands: list[list[str]] = field(default_factory=list)
    plan_digest: str = ""
    adopt_partial: bool = False
    route_overrides: tuple[RouteOverride, ...] = ()
    selection_mode: str | None = None
    prerequisite_evidence: dict[str, Any] | None = None
    source_admission: dict[str, Any] = field(default_factory=lambda: {
        "kind": "unproven", "provenanceDigest": None, "projectionDigest": None,
    })

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["schemaVersion"] = data.pop("schema_version")
        data["templateVersion"] = data.pop("template_version")
        data["templateRoot"] = data.pop("template_root")
        data["targetRoot"] = data.pop("target_root")
        data["targetState"] = data.pop("target_state")
        data["manifestDigest"] = data.pop("manifest_digest")
        data["verificationCommands"] = data.pop("verification_commands")
        data["planDigest"] = data.pop("plan_digest")
        adopt_partial = data.pop("adopt_partial")
        route_overrides = data.pop("route_overrides")
        selection_mode = data.pop("selection_mode")
        prerequisite_evidence = data.pop("prerequisite_evidence")
        source_admission = data.pop("source_admission")
        data["sourceAdmission"] = source_admission
        if self.schema_version in {2, 3, 4, 5, 7}:
            data["adoptPartial"] = adopt_partial
        if self.schema_version in {3, 4, 5}:
            data["routeOverrides"] = list(route_overrides)
        if self.schema_version == 7:
            data["routeOverrides"] = [
                {"scope": item["scope"], "model": item["model"], "effort": item["effort"]}
                for item in route_overrides
            ]
        if self.schema_version in {5, 7}:
            data["selectionMode"] = selection_mode
        if self.schema_version == 6:
            data["prerequisiteEvidence"] = prerequisite_evidence
        for action in data["actions"]:
            action["sourceDigest"] = action.pop("source_digest")
            action["targetDigest"] = action.pop("target_digest")
            action["destinationDigest"] = action.pop("destination_digest")
            action["decisionId"] = action.pop("decision_id")
        for decision in data["decisions"]:
            decision["allowedChoices"] = decision.pop("allowed_choices")
        return data


PLAN_KEYS = {
    "schemaVersion",
    "templateVersion",
    "templateRoot",
    "targetRoot",
    "targetState",
    "developer",
    "manifestDigest",
    "profile",
    "actions",
    "blockers",
    "conflicts",
    "decisions",
    "verificationCommands",
    "planDigest",
    "sourceAdmission",
}
ADOPTION_PLAN_KEYS = PLAN_KEYS | {"adoptPartial"}
OVERRIDE_PLAN_KEYS = PLAN_KEYS | {"adoptPartial", "routeOverrides"}
ROUTE_ONLY_PLAN_KEYS = OVERRIDE_PLAN_KEYS | {"selectionMode"}
CAPABILITY_PLAN_KEYS = PLAN_KEYS | {"prerequisiteEvidence"}
ACTION_KEYS = {
    "path", "kind", "operation", "reason", "sourceDigest", "targetDigest",
    "destination", "destinationDigest", "decisionId",
}
DECISION_KEYS = {"id", "paths", "reason", "allowedChoices", "selection"}


def route_target_paths(overrides: tuple[RouteOverride, ...]) -> list[str]:
    return sorted({ROUTE_TARGETS[item.scope] for item in overrides})


def validate_route_only_plan_shape(plan: Plan) -> None:
    """Validate route-only action and decision invariants before transaction replay."""
    if plan.schema_version not in {5, 7}:
        return
    if (
        plan.selection_mode != "route-only"
        or plan.profile is not None
        or plan.developer is not None
        or plan.adopt_partial
        or plan.target_state != TargetState.EXISTING_TRELLIS.value
        or not plan.route_overrides
    ):
        raise MigrationError("route-only plan has invalid mode fields")
    expected_paths = route_target_paths(plan.route_overrides)
    if [action.path for action in plan.actions] != expected_paths:
        raise MigrationError("route-only plan actions do not match requested route paths")
    decisions_by_id = {decision.id: decision for decision in plan.decisions}
    if len(decisions_by_id) != len(plan.decisions):
        raise MigrationError("route-only plan decisions are not unique")
    referenced_decisions: set[str] = set()
    for action in plan.actions:
        if (
            action.source_digest is None
            or action.target_digest is None
            or action.destination is not None
            or action.destination_digest is not None
            or action.operation not in {Operation.COPY.value, Operation.SKIP.value}
        ):
            raise MigrationError("route-only plan action is invalid")
        if action.target_digest == "missing":
            if action.operation != Operation.COPY.value or action.decision_id is not None:
                raise MigrationError("route-only missing target must be a live copy")
            continue
        if action.decision_id is None:
            raise MigrationError("route-only existing target requires a replace decision")
        decision = decisions_by_id.get(action.decision_id)
        if (
            decision is None
            or decision.paths != [action.path]
            or decision.allowed_choices != ["replace"]
            or decision.selection not in {None, "replace"}
            or (decision.selection is None and action.operation != Operation.SKIP.value)
            or (decision.selection == "replace" and action.operation != Operation.COPY.value)
        ):
            raise MigrationError("route-only plan decision is invalid")
        referenced_decisions.add(decision.id)
    if referenced_decisions != set(decisions_by_id):
        raise MigrationError("route-only plan has an unrelated decision")


def _string_list(value: object, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise MigrationError(f"plan {label} must be an array of strings")
    if not allow_empty and not value:
        raise MigrationError(f"plan {label} must not be empty")
    return list(value)


def _optional_string(value: object, label: str) -> str | None:
    if value is not None and not isinstance(value, str):
        raise MigrationError(f"plan {label} must be a string or null")
    return value


def validate_source_admission(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"kind", "provenanceDigest", "projectionDigest"}:
        raise MigrationError("plan sourceAdmission has unknown or missing fields")
    if not isinstance(value["kind"], str) or value["kind"] not in {"release", "unproven", "development-only"}:
        raise MigrationError("plan sourceAdmission kind is invalid")
    provenance = value["provenanceDigest"]
    projection = value["projectionDigest"]
    digest_pattern = re.compile(r"sha256:[0-9a-f]{64}\Z")
    if value["kind"] == "release":
        if not isinstance(provenance, str) or not digest_pattern.fullmatch(provenance) or not isinstance(projection, str) or not digest_pattern.fullmatch(projection):
            raise MigrationError("release sourceAdmission digests are invalid")
    elif provenance is not None or projection is not None:
        raise MigrationError("non-release sourceAdmission must not carry provenance digests")


def validate_prerequisite_evidence(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "capability", "status", "checkedFiles", "dispatchLanes", "hooks", "roles"
    }:
        raise MigrationError("plan prerequisiteEvidence has unknown or missing fields")
    if value["capability"] != "codex-dispatch-workflow-v1" or value["status"] != "admitted":
        raise MigrationError("plan prerequisiteEvidence capability or status is invalid")
    checked = value["checkedFiles"]
    if not isinstance(checked, list) or not checked:
        raise MigrationError("plan prerequisiteEvidence checkedFiles must be non-empty")
    for item in checked:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "digest"}
            or not isinstance(item["path"], str)
            or not isinstance(item["digest"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"])
        ):
            raise MigrationError("plan prerequisiteEvidence checked file is invalid")
    expected_checked_paths = [
        ".codex/agents/trellis-check.toml",
        ".codex/agents/trellis-implement.toml",
        ".codex/agents/trellis-research.toml",
        ".codex/config.toml",
        ".codex/hooks.json",
        ".codex/trellis-dispatch.toml",
        ".trellis/scripts/common/active_task.py",
        ".trellis/scripts/common/config.py",
        ".trellis/scripts/common/paths.py",
    ]
    if [item["path"] for item in checked] != expected_checked_paths:
        raise MigrationError("plan prerequisiteEvidence checkedFiles must be unique and sorted")
    lanes = value["dispatchLanes"]
    expected_scopes = [
        "dispatch:check:default", "dispatch:check:hard",
        "dispatch:implement:default", "dispatch:implement:hard",
    ]
    if not isinstance(lanes, list) or [item.get("scope") if isinstance(item, dict) else None for item in lanes] != expected_scopes:
        raise MigrationError("plan prerequisiteEvidence dispatchLanes are invalid")
    for item in lanes:
        if not isinstance(item, dict) or set(item) != {"scope", "route", "model", "effort"}:
            raise MigrationError("plan prerequisiteEvidence dispatch lane is invalid")
        route = item["route"]
        pair = ROUTE_CATALOG.get(item["scope"], {}).get(route)
        if route == "custom":
            if (
                not is_safe_route_value(item["model"])
                or not is_safe_route_value(item["effort"])
                or (item["model"], item["effort"])
                in ROUTE_CATALOG.get(item["scope"], {}).values()
            ):
                raise MigrationError("plan prerequisiteEvidence custom dispatch lane is invalid")
        elif pair != (item["model"], item["effort"]):
            raise MigrationError("plan prerequisiteEvidence dispatch lane is not approved")
    hooks = value["hooks"]
    if not isinstance(hooks, list) or [item.get("event") if isinstance(item, dict) else None for item in hooks] != ["SubagentStart", "UserPromptSubmit"]:
        raise MigrationError("plan prerequisiteEvidence hooks are invalid")
    for item in hooks:
        if (
            not isinstance(item, dict)
            or set(item) != {"event", "command", "roles"}
            or not isinstance(item["command"], str)
            or not item["command"]
            or not isinstance(item["roles"], list)
            or not all(isinstance(role, str) for role in item["roles"])
        ):
            raise MigrationError("plan prerequisiteEvidence hook is invalid")
    if hooks[0]["roles"] != ["trellis-implement", "trellis-check", "trellis-research"] or hooks[1]["roles"] != []:
        raise MigrationError("plan prerequisiteEvidence hook roles are invalid")
    if ".codex/hooks/inject-subagent-context.py" not in hooks[0]["command"] or ".codex/hooks/inject-workflow-state.py" not in hooks[1]["command"]:
        raise MigrationError("plan prerequisiteEvidence hook commands are invalid")
    roles = value["roles"]
    if not isinstance(roles, list) or [item.get("role") if isinstance(item, dict) else None for item in roles] != ["check", "implement", "research"]:
        raise MigrationError("plan prerequisiteEvidence roles are invalid")
    for item in roles:
        if (
            not isinstance(item, dict)
            or set(item) != {"role", "path", "name", "digest", "modelPinned"}
            or item["name"] != f"trellis-{item['role']}"
            or item["path"] != f".codex/agents/trellis-{item['role']}.toml"
            or not isinstance(item["modelPinned"], bool)
            or item["role"] in {"implement", "check"} and item["modelPinned"]
            or not isinstance(item["path"], str)
            or not isinstance(item["digest"], str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", item["digest"])
        ):
            raise MigrationError("plan prerequisiteEvidence role is invalid")


def plan_from_dict(data: dict[str, Any]) -> Plan:
    schema_version = data.get("schemaVersion")
    expected_keys = (
        ROUTE_ONLY_PLAN_KEYS if schema_version in {5, 7}
        else CAPABILITY_PLAN_KEYS if schema_version == 6
        else OVERRIDE_PLAN_KEYS if schema_version in {3, 4}
        else ADOPTION_PLAN_KEYS if schema_version == 2 else PLAN_KEYS
    )
    if set(data) != expected_keys:
        raise MigrationError("plan has unknown or missing fields")
    try:
        if not isinstance(data["schemaVersion"], int) or isinstance(data["schemaVersion"], bool) or data["schemaVersion"] not in {1, 2, 3, 4, 5, 6, 7}:
            raise MigrationError("plan schemaVersion must be an integer")
        for field in ("templateVersion", "templateRoot", "targetRoot", "targetState", "manifestDigest", "planDigest"):
            if not isinstance(data[field], str):
                raise MigrationError(f"plan {field} must be a string")
        profile = data["profile"]
        selection_mode: str | None = None
        if data["schemaVersion"] in {5, 7}:
            if profile is not None:
                raise MigrationError("route-only plan profile must be null")
            if data["selectionMode"] != "route-only":
                raise MigrationError("route-only plan selectionMode is invalid")
            selection_mode = data["selectionMode"]
        elif not isinstance(profile, str):
            raise MigrationError("plan profile must be a string")
        if data["targetState"] not in {state.value for state in TargetState}:
            raise MigrationError("plan targetState is invalid")
        developer = _optional_string(data["developer"], "developer")
        if not isinstance(data["actions"], list) or not isinstance(data["decisions"], list):
            raise MigrationError("plan actions and decisions must be arrays")
        actions: list[Action] = []
        for item in data["actions"]:
            if not isinstance(item, dict) or set(item) != ACTION_KEYS:
                raise MigrationError("plan action has unknown or missing fields")
            for field in ("path", "kind", "operation", "reason"):
                if not isinstance(item[field], str):
                    raise MigrationError(f"plan action {field} must be a string")
            if item["kind"] not in {kind.value for kind in RuleKind}:
                raise MigrationError(f"plan action kind is invalid: {item['kind']}")
            if item["operation"] not in {operation.value for operation in Operation}:
                raise MigrationError(f"plan action operation is invalid: {item['operation']}")
            actions.append(Action(
                path=item["path"], kind=item["kind"], operation=item["operation"],
                reason=item["reason"], source_digest=_optional_string(item["sourceDigest"], "action sourceDigest"),
                target_digest=_optional_string(item["targetDigest"], "action targetDigest"),
                destination=_optional_string(item["destination"], "action destination"),
                destination_digest=_optional_string(item["destinationDigest"], "action destinationDigest"),
                decision_id=_optional_string(item["decisionId"], "action decisionId"),
            ))
        decisions: list[Decision] = []
        decision_ids: set[str] = set()
        for item in data["decisions"]:
            if not isinstance(item, dict) or set(item) != DECISION_KEYS:
                raise MigrationError("plan decision has unknown or missing fields")
            if not isinstance(item["id"], str) or not isinstance(item["reason"], str):
                raise MigrationError("plan decision ID and reason must be strings")
            paths = _string_list(item["paths"], "decision paths", allow_empty=False)
            choices = _string_list(item["allowedChoices"], "decision allowedChoices", allow_empty=False)
            selection = _optional_string(item["selection"], "decision selection")
            if len(set(choices)) != len(choices) or selection is not None and selection not in choices:
                raise MigrationError(f"plan decision choices are invalid: {item['id']}")
            if item["id"] in decision_ids:
                raise MigrationError(f"plan decision ID is duplicated: {item['id']}")
            decision_ids.add(item["id"])
            decisions.append(Decision(item["id"], paths, item["reason"], choices, selection))
        blockers = _string_list(data["blockers"], "blockers")
        conflicts = _string_list(data["conflicts"], "conflicts")
        command_values = data["verificationCommands"]
        if not isinstance(command_values, list) or not all(isinstance(command, list) for command in command_values):
            raise MigrationError("plan verificationCommands must be an array of command arrays")
        verification_commands = [
            _string_list(command, "verification command", allow_empty=False) for command in command_values
        ]
        adopt_partial = data.get("adoptPartial", False)
        if not isinstance(adopt_partial, bool):
            raise MigrationError("plan adoptPartial must be a boolean")
        if data["schemaVersion"] in {1, 3, 5, 7} and adopt_partial:
            raise MigrationError("plan adoption mode requires schemaVersion 2")
        if adopt_partial and (data["targetState"] != TargetState.UNSUPPORTED_PARTIAL.value or profile != "complete"):
            raise MigrationError("plan adoption mode has an invalid target state or profile")
        if data["schemaVersion"] == 2 and not adopt_partial:
            raise MigrationError("plan schemaVersion 2 is reserved for partial adoption")
        if data["schemaVersion"] == 4 and not adopt_partial:
            raise MigrationError("plan schemaVersion 4 is reserved for partial adoption")
        raw_overrides = data.get("routeOverrides", [])
        if data["schemaVersion"] in {3, 4, 5, 7} and (not isinstance(raw_overrides, list) or not raw_overrides):
            raise MigrationError("plan routeOverrides must be a non-empty array")
        route_overrides: list[RouteOverride] = []
        for item in raw_overrides:
            expected_override_keys = {"scope", "model", "effort"} if data["schemaVersion"] == 7 else {"scope", "route", "model", "effort"}
            if not isinstance(item, dict) or set(item) != expected_override_keys:
                raise MigrationError("plan route override has unknown or missing fields")
            if not all(isinstance(item[field], str) for field in expected_override_keys):
                raise MigrationError("plan route override fields must be strings")
            if data["schemaVersion"] == 7:
                if item["scope"] not in ROUTE_TARGETS or not is_safe_route_value(item["model"]) or not is_safe_route_value(item["effort"]):
                    raise MigrationError("plan raw route override is invalid")
                route_overrides.append(RouteOverride(item["scope"], None, item["model"], item["effort"]))
            else:
                pair = ROUTE_CATALOG.get(item["scope"], {}).get(item["route"])
                if pair != (item["model"], item["effort"]):
                    raise MigrationError("plan route override is not an approved scope/route tuple")
                route_overrides.append(RouteOverride(item["scope"], item["route"], item["model"], item["effort"]))
        if route_overrides != sorted(route_overrides, key=lambda item: item.scope) or len({item.scope for item in route_overrides}) != len(route_overrides):
            raise MigrationError("plan routeOverrides must have unique scopes in sorted order")
        prerequisite_evidence = data.get("prerequisiteEvidence")
        if data["schemaVersion"] == 6:
            validate_prerequisite_evidence(prerequisite_evidence)
        validate_source_admission(data["sourceAdmission"])
        plan = Plan(
            schema_version=data["schemaVersion"], template_version=data["templateVersion"],
            template_root=data["templateRoot"], target_root=data["targetRoot"],
            target_state=data["targetState"], developer=developer,
            manifest_digest=data["manifestDigest"],
            profile=profile,
            actions=actions,
            blockers=blockers,
            conflicts=conflicts,
            decisions=decisions,
            verification_commands=verification_commands,
            plan_digest=data["planDigest"],
            adopt_partial=adopt_partial,
            route_overrides=tuple(route_overrides),
            selection_mode=selection_mode,
            prerequisite_evidence=prerequisite_evidence,
            source_admission=dict(data["sourceAdmission"]),
        )
        validate_route_only_plan_shape(plan)
        return plan
    except MigrationError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise MigrationError(f"invalid plan: {exc}") from exc
