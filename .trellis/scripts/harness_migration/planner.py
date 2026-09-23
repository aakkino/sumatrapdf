from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

from .codec import MISSING_DIGEST, digest_path, digest_value
from .admission import build_prerequisite_evidence
from .manifest import Manifest, exported_files, matching_rule
from .models import (
    Action,
    DISPATCH_CONFIG_PATH,
    Decision,
    has_dispatch_override_for_path,
    is_safe_route_value,
    MigrationError,
    Operation,
    Plan,
    ROUTE_CATALOG,
    ROUTE_FIELDS,
    ROUTE_TARGETS,
    ROUTE_TABLES,
    RouteOverride,
    RuleKind,
    TargetState,
    route_target_paths,
    validate_prerequisite_evidence,
    validate_route_only_plan_shape,
    validate_source_admission,
)
from .safety import apply_blockers, classify_target, contained_path, resolve_directory, validate_root_relationship


PLAN_SCHEMA_VERSION = 1
ADOPTION_PLAN_SCHEMA_VERSION = 2
OVERRIDE_PLAN_SCHEMA_VERSION = 3
ADOPTION_OVERRIDE_PLAN_SCHEMA_VERSION = 4
ROUTE_ONLY_PLAN_SCHEMA_VERSION = 5
CAPABILITY_PLAN_SCHEMA_VERSION = 6
RAW_ROUTE_ONLY_PLAN_SCHEMA_VERSION = 7
SIDECAR_SUFFIX = ".harness-new"
VERIFICATION_COMMANDS = [
    ["python", ".trellis/scripts/get_context.py"],
    ["python", ".trellis/scripts/task.py", "current", "--json"],
    ["python", ".trellis/scripts/task.py", "list"],
    ["python", "-m", "unittest", "discover", "-s", ".trellis/tests", "-p", "test_*.py"],
    ["trellis", "update", "--dry-run"],
]

def normalize_route_overrides(values: list[str] | tuple[RouteOverride, ...]) -> tuple[RouteOverride, ...]:
    normalized: list[RouteOverride] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, RouteOverride):
            scope, route = value.scope, value.route
        elif isinstance(value, str) and value.count("=") == 1:
            scope, route = value.split("=", 1)
        else:
            raise MigrationError(f"route override must use scope=route syntax: {value}")
        if not scope or not route or scope in seen:
            raise MigrationError(f"invalid or duplicate route override scope: {scope}")
        pair = ROUTE_CATALOG.get(scope, {}).get(route)
        if pair is None:
            raise MigrationError(f"unsupported route override: {scope}={route}")
        candidate = RouteOverride(scope, route, pair[0], pair[1])
        if isinstance(value, RouteOverride) and candidate != value:
            raise MigrationError(f"route override tuple does not match policy: {scope}={route}")
        seen.add(scope)
        normalized.append(candidate)
    return tuple(sorted(normalized, key=lambda item: item.scope))


def normalize_route_pairs(values: list[str] | tuple[RouteOverride, ...]) -> tuple[RouteOverride, ...]:
    normalized: list[RouteOverride] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, RouteOverride):
            scope, model, effort = value.scope, value.model, value.effort
            if value.route is not None:
                raise MigrationError(f"raw route pair must not declare a named route: {scope}")
        elif isinstance(value, str) and value.count("=") == 1:
            scope, pair = value.split("=", 1)
            if pair.count(",") != 1:
                raise MigrationError(f"route pair must use scope=model,effort syntax: {value}")
            model, effort = pair.split(",", 1)
        else:
            raise MigrationError(f"route pair must use scope=model,effort syntax: {value}")
        if scope not in ROUTE_TARGETS or scope in seen:
            raise MigrationError(f"invalid or duplicate route pair scope: {scope}")
        if not is_safe_route_value(model) or not is_safe_route_value(effort):
            raise MigrationError(f"route pair contains an unsafe model or effort: {scope}")
        seen.add(scope)
        normalized.append(RouteOverride(scope, None, model, effort))
    return tuple(sorted(normalized, key=lambda item: item.scope))


def _table_owner(document: dict[str, Any], table: tuple[str, ...]) -> dict[str, Any] | None:
    owner: Any = document
    for key in table:
        if not isinstance(owner, dict):
            return None
        owner = owner.get(key)
    return owner if isinstance(owner, dict) else None


def _replace_assignments(
    data: bytes,
    relative: str,
    table: tuple[str, ...],
    keys: tuple[str, str],
    override: RouteOverride,
) -> bytes:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationError(f"route override source is not UTF-8: {relative}") from exc
    try:
        document = tomllib.loads(text.replace("\r\n", "\n"))
    except tomllib.TOMLDecodeError as exc:
        raise MigrationError(f"route override source is malformed TOML: {relative}: {exc}") from exc
    lines = text.splitlines(keepends=True)
    current_table: tuple[str, ...] = ()
    owner = _table_owner(document, table)
    if not isinstance(owner, dict) or any(not isinstance(owner.get(key), str) for key in keys):
        location = "root" if not table else f"[{'.'.join(table)}]"
        raise MigrationError(f"route override requires a string model pair in {location} of {relative}")
    matches: dict[str, list[int]] = {key: [] for key in keys}
    wrong_table: list[str] = []
    table_pattern = re.compile(r"^[ \t]*\[([^\]]+)\][ \t]*(?:#.*)?(?:\r?\n)?$")
    assignment_pattern = re.compile(
        r"^([ \t]*)(" + "|".join(keys) + r")([ \t]*=[ \t]*)\"[^\"\r\n]*\""
        r"([ \t]*(?:#[^\r\n]*)?)(\r?\n)?\Z"
    )
    for index, line in enumerate(lines):
        table_match = table_pattern.match(line)
        if table_match:
            current_table = tuple(part.strip() for part in table_match.group(1).strip().split("."))
            continue
        assignment = assignment_pattern.match(line)
        if assignment:
            if current_table == table:
                matches[assignment.group(2)].append(index)
            else:
                wrong_table.append(assignment.group(2))
    if wrong_table and (not table or any(len(indices) != 1 for indices in matches.values())):
        raise MigrationError(f"route override model assignment is in the wrong table in {relative}")
    if any(len(indices) != 1 for indices in matches.values()):
        raise MigrationError(f"route override requires exactly one model pair in {relative}")
    replacements = {
        keys[0]: override.model,
        keys[1]: override.effort,
    }
    for key, indices in matches.items():
        index = indices[0]
        assignment = assignment_pattern.match(lines[index])
        assert assignment is not None
        lines[index] = (
            f'{assignment.group(1)}{key}{assignment.group(3)}"{replacements[key]}"'
            f'{assignment.group(4)}{assignment.group(5) or ""}'
        )
    return "".join(lines).encode("utf-8")


def _apply_route_overrides(data: bytes, relative: str, overrides: tuple[RouteOverride, ...]) -> bytes:
    result = data
    for override in overrides:
        if ROUTE_TARGETS[override.scope] != relative:
            continue
        result = _replace_assignments(
            result,
            relative,
            ROUTE_TABLES[override.scope],
            ROUTE_FIELDS[override.scope],
            override,
        )
    return result


def _decision_id(prefix: str, paths: list[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", paths[0].lower()).strip("-")
    return f"{prefix}:{slug}:{digest_value(paths)[7:15]}"


def _transform_skeleton(relative: str, developer: str | None) -> str:
    if developer and relative.startswith(".trellis/workspace/kino/"):
        return ".trellis/workspace/" + developer + relative[len(".trellis/workspace/kino"):]
    return relative


def _generated_source_bytes(source: Path, relative: str, developer: str | None) -> bytes:
    try:
        data = source.read_bytes()
    except OSError as exc:
        raise MigrationError(f"cannot read migration source: {relative}: {exc}") from exc
    if not developer:
        return data
    if relative == ".trellis/.developer":
        return f"name={developer}\n".encode("utf-8")
    if relative.endswith("/task.json") and "00-bootstrap-guidelines" in relative:
        try:
            value = json.loads(data.decode("utf-8"))
            if not isinstance(value, dict) or not all(field in value for field in ("creator", "assignee")):
                raise MigrationError(f"bootstrap task identity fields are missing: {relative}")
            for field in ("creator", "assignee"):
                value[field] = developer
            return (json.dumps(value, ensure_ascii=True, indent=2) + "\n").encode("utf-8")
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise MigrationError(f"cannot initialize bootstrap task identity: {relative}") from exc
    if relative.startswith(".trellis/workspace/kino/"):
        return data.replace(b"kino", developer.encode("utf-8"))
    return data


def source_bytes(
    template: Path,
    source_relative: str,
    destination_relative: str,
    developer: str | None,
    kind: str,
    route_overrides: tuple[RouteOverride, ...] = (),
    target_preimage: bytes | None = None,
) -> bytes:
    source = contained_path(template, source_relative)
    if target_preimage is not None and has_dispatch_override_for_path(destination_relative, route_overrides):
        return _apply_route_overrides(target_preimage, destination_relative, route_overrides)
    if kind == RuleKind.FRESH_ONLY_SKELETON.value:
        data = _generated_source_bytes(source, source_relative, developer)
        return _apply_route_overrides(data, destination_relative, route_overrides)
    try:
        return _apply_route_overrides(source.read_bytes(), destination_relative, route_overrides)
    except OSError as exc:
        raise MigrationError(f"cannot read migration source: {source_relative}: {exc}") from exc


def source_digest(
    template: Path,
    source_relative: str,
    destination_relative: str,
    developer: str | None,
    kind: str,
    route_overrides: tuple[RouteOverride, ...] = (),
    target_preimage: bytes | None = None,
) -> str:
    from hashlib import sha256
    return "sha256:" + sha256(
        source_bytes(
            template,
            source_relative,
            destination_relative,
            developer,
            kind,
            route_overrides,
            target_preimage,
        )
    ).hexdigest()


def _add_decision(decisions: list[Decision], conflicts: list[str], path: str, reason: str, choices: list[str], prefix: str) -> str:
    identifier = _decision_id(prefix, [path])
    decisions.append(Decision(identifier, [path], reason, choices))
    conflicts.append(path)
    return identifier


def _destination_conflicts(paths: list[str]) -> list[str]:
    conflicts: list[str] = []
    ordered = sorted(paths)
    for index, path in enumerate(ordered):
        if index and path == ordered[index - 1]:
            conflicts.append(f"duplicate migration destination: {path}")
        prefix = path + "/"
        if any(candidate.startswith(prefix) for candidate in ordered[index + 1:]):
            conflicts.append(f"migration destination is both a file and parent: {path}")
    return conflicts


def build_plan(
    template_value: str,
    target_value: str,
    developer: str | None = None,
    profile: str | None = "complete",
    adopt_partial: bool = False,
    route_overrides: list[str] | tuple[RouteOverride, ...] = (),
    route_only: bool = False,
    route_pairs: list[str] | tuple[RouteOverride, ...] = (),
    development_template: bool = False,
) -> Plan:
    named_overrides = normalize_route_overrides(route_overrides)
    raw_overrides = normalize_route_pairs(route_pairs)
    duplicate_scopes = {item.scope for item in named_overrides} & {item.scope for item in raw_overrides}
    if duplicate_scopes:
        raise MigrationError("duplicate route override scope: " + ", ".join(sorted(duplicate_scopes)))
    if raw_overrides:
        named_overrides = tuple(
            RouteOverride(item.scope, None, item.model, item.effort)
            for item in named_overrides
        )
    normalized_overrides = tuple(sorted(named_overrides + raw_overrides, key=lambda item: item.scope))
    if raw_overrides and not route_only:
        raise MigrationError("--route-pair requires --route-only")
    if route_only and not normalized_overrides:
        raise MigrationError("--route-only requires at least one --route or --route-pair")
    if route_only and adopt_partial:
        raise MigrationError("--route-only does not accept --adopt-partial")
    if route_only and developer is not None:
        raise MigrationError("--route-only does not accept --developer")
    if route_only and profile not in {None, "complete"}:
        raise MigrationError("--route-only does not accept --profile")
    template = resolve_directory(template_value, "template")
    target = resolve_directory(target_value, "target")
    validate_root_relationship(template, target)
    from .manifest import load_manifest
    manifest = load_manifest(template)
    provenance_path = template / ".harness-release.json"
    if provenance_path.exists() or provenance_path.is_symlink():
        from .release import validate_release_provenance
        provenance = validate_release_provenance(template)
        source_admission = {
            "kind": "release",
            "provenanceDigest": digest_path(provenance_path),
            "projectionDigest": provenance["projectionDigest"],
        }
    elif development_template:
        source_admission = {"kind": "development-only", "provenanceDigest": None, "projectionDigest": None}
    else:
        source_admission = {"kind": "unproven", "provenanceDigest": None, "projectionDigest": None}
    state = classify_target(target)
    blockers = apply_blockers(target)
    prerequisite_evidence: dict[str, Any] | None = None
    if not route_only and profile is not None:
        profile_record = manifest.profiles.get(profile)
        if profile_record is None:
            raise MigrationError(f"unknown migration profile: {profile}")
        if profile_record.capability is not None:
            prerequisite_evidence = build_prerequisite_evidence(target, state)
    if adopt_partial and profile != "complete":
        raise MigrationError("--adopt-partial requires --profile complete")
    if adopt_partial and developer is not None:
        raise MigrationError("--adopt-partial does not accept --developer")
    if adopt_partial and state != TargetState.UNSUPPORTED_PARTIAL:
        raise MigrationError("--adopt-partial requires a target classified exactly as unsupported_partial", exit_code=3)
    if state == TargetState.UNSUPPORTED_PARTIAL and not adopt_partial:
        blockers.append("target has an unsupported partial Trellis/Codex footprint")
    if state == TargetState.FRESH and not developer:
        blockers.append("fresh migration requires --developer")
    if state == TargetState.EXISTING_TRELLIS and developer:
        blockers.append("--developer is only valid for a fresh migration")
    if developer and (developer in {".", ".."} or not re.fullmatch(r"[A-Za-z0-9_.-]+", developer)):
        blockers.append("developer must contain only letters, digits, dot, underscore, or hyphen")

    if route_only and state != TargetState.EXISTING_TRELLIS:
        raise MigrationError(
            "--route-only requires a target classified exactly as existing_trellis",
            exit_code=3,
        )

    mode = (
        TargetState.EXISTING_TRELLIS.value
        if adopt_partial or route_only
        else state.value if state in {TargetState.FRESH, TargetState.EXISTING_TRELLIS} else "fresh"
    )
    actions: list[Action] = []
    decisions: list[Decision] = []
    conflicts: list[str] = []
    baseline_paths = {".trellis/.version", ".trellis/.template-hashes.json"}
    baseline_actions: list[Action] = []

    if route_only:
        selected_files = route_target_paths(normalized_overrides)
        exported = set(exported_files(template, manifest))
        missing_sources = sorted(set(selected_files) - exported)
        if missing_sources:
            raise MigrationError("route-only source paths are not exported: " + ", ".join(missing_sources))
    else:
        selected_files = exported_files(template, manifest, profile)
        selected_set = set(selected_files)
        missing_override_paths = sorted(set(route_target_paths(normalized_overrides)) - selected_set)
        if missing_override_paths:
            raise MigrationError("route override paths are not selected by profile: " + ", ".join(missing_override_paths))
    for source_relative in selected_files:
        rule = matching_rule(manifest.rules, source_relative)
        destination_relative = _transform_skeleton(source_relative, developer)
        if mode not in rule.modes:
            if route_only:
                raise MigrationError(f"route-only source rule excludes target mode: {source_relative}")
            try:
                current_digest = digest_path(contained_path(target, destination_relative))
            except MigrationError as exc:
                blockers.append(str(exc))
                current_digest = None
            actions.append(Action(destination_relative, rule.kind.value, Operation.SKIP.value, "rule excludes this target mode", None, current_digest))
            continue
        source_path = contained_path(template, source_relative)
        if source_path.is_symlink() or not source_path.is_file():
            if route_only:
                raise MigrationError(f"unsupported source entry: {source_relative}", exit_code=3)
            blockers.append(f"unsupported source entry: {source_relative}")
            continue
        try:
            destination = contained_path(target, destination_relative)
            if destination.exists() and not destination.is_file():
                if route_only:
                    raise MigrationError(
                        f"unsupported target entry (expected a file): {destination_relative}",
                        exit_code=3,
                    )
                blockers.append(f"unsupported target entry (expected a file): {destination_relative}")
                continue
            current_digest = digest_path(destination)
            target_preimage = None
            if (
                destination_relative == DISPATCH_CONFIG_PATH
                and current_digest != MISSING_DIGEST
                and has_dispatch_override_for_path(destination_relative, normalized_overrides)
            ):
                try:
                    target_preimage = destination.read_bytes()
                except OSError as exc:
                    raise MigrationError(f"cannot read route override target pre-image: {destination_relative}: {exc}") from exc
            incoming_digest = source_digest(
                template,
                source_relative,
                destination_relative,
                developer,
                rule.kind.value,
                normalized_overrides,
                target_preimage,
            )
        except MigrationError as exc:
            if route_only:
                raise
            blockers.append(str(exc))
            continue
        exists = current_digest != MISSING_DIGEST
        same = exists and current_digest == incoming_digest

        if route_only:
            if rule.kind not in {RuleKind.MERGE_REQUIRED, RuleKind.REPLACEABLE_MANAGED}:
                raise MigrationError(f"route-only source is not managed for live replacement: {source_relative}")
            if exists:
                decision_id = _add_decision(
                    decisions, conflicts, destination_relative,
                    "route-only target requires live replacement", ["replace"], "route-only",
                )
                actions.append(Action(
                    destination_relative, rule.kind.value, Operation.SKIP.value,
                    "awaiting route-only replace decision", incoming_digest, current_digest,
                    decision_id=decision_id,
                ))
            else:
                actions.append(Action(
                    destination_relative, rule.kind.value, Operation.COPY.value,
                    "route-only target is absent", incoming_digest, current_digest,
                ))
            continue

        if rule.kind in {RuleKind.SUPPORT_ONLY, RuleKind.RUNTIME_EXCLUDED, RuleKind.PRESERVE}:
            operation = Operation.PRESERVE.value if rule.kind == RuleKind.PRESERVE else Operation.SKIP.value
            actions.append(Action(destination_relative, rule.kind.value, operation, "policy does not install this source path", incoming_digest, current_digest))
        elif rule.kind == RuleKind.FRESH_ONLY_SKELETON:
            if mode != TargetState.FRESH.value:
                actions.append(Action(destination_relative, rule.kind.value, Operation.SKIP.value, "skeleton is fresh-only", incoming_digest, current_digest))
            elif exists and not same:
                decision_id = _add_decision(decisions, conflicts, destination_relative, "fresh skeleton path already exists", ["sidecar", "keep", "replace"], "skeleton")
                actions.append(Action(destination_relative, rule.kind.value, Operation.SKIP.value, "awaiting skeleton decision", incoming_digest, current_digest, decision_id=decision_id))
            else:
                actions.append(Action(destination_relative, rule.kind.value, Operation.SKIP.value if same else Operation.COPY.value, "fresh project skeleton", incoming_digest, current_digest))
        elif source_relative in baseline_paths:
            if mode == TargetState.EXISTING_TRELLIS.value and (not adopt_partial or exists):
                action = Action(destination_relative, rule.kind.value, Operation.SKIP.value, "awaiting paired official baseline decision", incoming_digest, current_digest)
                baseline_actions.append(action)
                actions.append(action)
            else:
                actions.append(Action(
                    destination_relative, rule.kind.value,
                    Operation.SKIP.value if same else Operation.COPY.value,
                    "partial adoption initializes absent official baseline" if adopt_partial else "fresh project official baseline",
                    incoming_digest, current_digest,
                ))
        elif rule.kind == RuleKind.MERGE_REQUIRED:
            choices = ["install", "skip"] if not exists else ["sidecar", "keep", "replace"]
            decision_id = _add_decision(decisions, conflicts, destination_relative, "project-aware merge decision required", choices, "merge")
            actions.append(Action(destination_relative, rule.kind.value, Operation.SKIP.value, "awaiting merge decision", incoming_digest, current_digest, decision_id=decision_id))
        elif (
            source_relative == DISPATCH_CONFIG_PATH
            and has_dispatch_override_for_path(source_relative, normalized_overrides)
            and exists
        ):
            decision_id = _add_decision(
                decisions,
                conflicts,
                destination_relative,
                "dispatch route override requires live replacement",
                ["replace"],
                "dispatch-route",
            )
            actions.append(Action(
                destination_relative,
                rule.kind.value,
                Operation.SKIP.value,
                "awaiting dispatch route replace decision",
                incoming_digest,
                current_digest,
                decision_id=decision_id,
            ))
        elif same and not (state == TargetState.EXISTING_TRELLIS and source_relative in {ROUTE_TARGETS[item.scope] for item in normalized_overrides}):
            actions.append(Action(destination_relative, rule.kind.value, Operation.SKIP.value, "target already matches source", incoming_digest, current_digest))
        elif not exists:
            actions.append(Action(destination_relative, rule.kind.value, Operation.COPY.value, "managed path is absent", incoming_digest, current_digest))
        else:
            decision_id = _add_decision(decisions, conflicts, destination_relative, "managed target differs from incoming source", ["sidecar", "keep", "replace"], "modified")
            actions.append(Action(destination_relative, rule.kind.value, Operation.SKIP.value, "awaiting modified-managed decision", incoming_digest, current_digest, decision_id=decision_id))

    if baseline_actions:
        identifier = _decision_id("official-baseline", sorted(item.path for item in baseline_actions))
        choices = ["preserve", "snapshot"] if all(
            item.target_digest != MISSING_DIGEST for item in baseline_actions
        ) else ["snapshot"]
        decisions.append(Decision(identifier, sorted(item.path for item in baseline_actions), "preserve target official baseline or adopt the complete snapshot pair", choices))
        conflicts.extend(item.path for item in baseline_actions)
        for action in baseline_actions:
            action.decision_id = identifier

    actions.sort(key=lambda item: (item.path, item.operation))
    blockers.extend(_destination_conflicts([action.path for action in actions]))
    decisions.sort(key=lambda item: item.id)
    conflicts = sorted(set(conflicts))
    commands = [list(command) for command in VERIFICATION_COMMANDS]
    plan = Plan(
        RAW_ROUTE_ONLY_PLAN_SCHEMA_VERSION if raw_overrides else ROUTE_ONLY_PLAN_SCHEMA_VERSION if route_only else CAPABILITY_PLAN_SCHEMA_VERSION if prerequisite_evidence is not None else (ADOPTION_OVERRIDE_PLAN_SCHEMA_VERSION if adopt_partial else OVERRIDE_PLAN_SCHEMA_VERSION) if normalized_overrides else ADOPTION_PLAN_SCHEMA_VERSION if adopt_partial else PLAN_SCHEMA_VERSION,
        manifest.template_version, str(template), str(target),
        state.value, developer, manifest.digest, None if route_only else profile, actions,
        sorted(set(blockers)), conflicts, decisions, commands,
        adopt_partial=adopt_partial,
        route_overrides=normalized_overrides,
        selection_mode="route-only" if route_only else None,
        prerequisite_evidence=prerequisite_evidence,
        source_admission=source_admission,
    )
    plan.plan_digest = calculate_plan_digest(plan)
    return plan


def calculate_plan_digest(plan: Plan) -> str:
    value = plan.to_dict()
    value.pop("planDigest", None)
    return digest_value(value)


def validate_plan_digest(plan: Plan) -> None:
    if (
        plan.schema_version not in {PLAN_SCHEMA_VERSION, ADOPTION_PLAN_SCHEMA_VERSION, OVERRIDE_PLAN_SCHEMA_VERSION, ADOPTION_OVERRIDE_PLAN_SCHEMA_VERSION, ROUTE_ONLY_PLAN_SCHEMA_VERSION, CAPABILITY_PLAN_SCHEMA_VERSION, RAW_ROUTE_ONLY_PLAN_SCHEMA_VERSION}
        or (plan.schema_version == ADOPTION_PLAN_SCHEMA_VERSION and not plan.adopt_partial)
        or plan.schema_version == PLAN_SCHEMA_VERSION and plan.adopt_partial
        or plan.schema_version == OVERRIDE_PLAN_SCHEMA_VERSION and (plan.adopt_partial or not plan.route_overrides)
        or plan.schema_version == ADOPTION_OVERRIDE_PLAN_SCHEMA_VERSION and (not plan.adopt_partial or not plan.route_overrides)
        or plan.schema_version == ROUTE_ONLY_PLAN_SCHEMA_VERSION and (
            plan.adopt_partial or not plan.route_overrides or any(item.route is None for item in plan.route_overrides)
        )
        or plan.schema_version == RAW_ROUTE_ONLY_PLAN_SCHEMA_VERSION and (
            plan.adopt_partial or not plan.route_overrides or any(item.route is not None for item in plan.route_overrides)
        )
        or plan.schema_version in {PLAN_SCHEMA_VERSION, ADOPTION_PLAN_SCHEMA_VERSION} and bool(plan.route_overrides)
        or plan.schema_version == CAPABILITY_PLAN_SCHEMA_VERSION and (
            plan.profile != "agent-workflow"
            or plan.prerequisite_evidence is None
            or plan.adopt_partial
            or bool(plan.route_overrides)
            or plan.selection_mode is not None
        )
        or plan.schema_version != CAPABILITY_PLAN_SCHEMA_VERSION and plan.prerequisite_evidence is not None
        or plan.plan_digest != calculate_plan_digest(plan)
    ):
        raise MigrationError("plan digest or schema is invalid", exit_code=3)
    if plan.adopt_partial and (
        plan.target_state != TargetState.UNSUPPORTED_PARTIAL.value or plan.profile != "complete"
    ):
        raise MigrationError("plan adoption mode has an invalid target state or profile", exit_code=3)
    if plan.schema_version == CAPABILITY_PLAN_SCHEMA_VERSION:
        try:
            validate_prerequisite_evidence(plan.prerequisite_evidence)
        except MigrationError as exc:
            raise MigrationError("plan digest or schema is invalid", exit_code=3) from exc
    try:
        validate_source_admission(plan.source_admission)
    except MigrationError as exc:
        raise MigrationError("plan digest or schema is invalid", exit_code=3) from exc
    try:
        validate_route_only_plan_shape(plan)
    except MigrationError as exc:
        raise MigrationError("plan digest or schema is invalid", exit_code=3) from exc


def resolve_plan(plan: Plan, selections: dict[str, str]) -> Plan:
    validate_plan_digest(plan)
    known = {decision.id: decision for decision in plan.decisions}
    unknown = set(selections) - set(known)
    if unknown:
        raise MigrationError("unknown decision IDs: " + ", ".join(sorted(unknown)))
    for identifier, choice in selections.items():
        decision = known[identifier]
        if choice not in decision.allowed_choices:
            raise MigrationError(f"invalid choice {choice!r} for {identifier}")
        decision.selection = choice
        for action in plan.actions:
            if action.decision_id != identifier:
                continue
            if choice in {"install", "replace", "snapshot"}:
                action.operation = Operation.COPY.value
                action.reason = f"resolved decision: {choice}"
                action.destination = None
                action.destination_digest = None
            elif choice == "sidecar":
                action.operation = Operation.SIDECAR.value
                action.reason = "resolved decision: sidecar"
                action.destination = action.path + SIDECAR_SUFFIX
                destination = contained_path(Path(plan.target_root), action.destination)
                if destination.exists() and not destination.is_file():
                    raise MigrationError(f"unsupported sidecar target entry: {action.destination}", exit_code=3)
                action.destination_digest = digest_path(destination)
            else:
                action.operation = Operation.PRESERVE.value if choice in {"keep", "preserve"} else Operation.SKIP.value
                action.reason = f"resolved decision: {choice}"
                action.destination = None
                action.destination_digest = None
    mutation_destinations = [
        action.destination if action.operation == Operation.SIDECAR.value else action.path
        for action in plan.actions
        if action.operation in {Operation.COPY.value, Operation.SIDECAR.value}
    ]
    destination_conflicts = _destination_conflicts([path for path in mutation_destinations if path])
    if destination_conflicts:
        raise MigrationError("; ".join(destination_conflicts), exit_code=3)
    override_paths = {ROUTE_TARGETS[item.scope] for item in plan.route_overrides}
    ineffective = [action.path for action in plan.actions if action.path in override_paths and action.operation != Operation.COPY.value]
    if ineffective:
        raise MigrationError("route overrides require live-target copy: " + ", ".join(sorted(ineffective)))
    plan.plan_digest = calculate_plan_digest(plan)
    return plan
