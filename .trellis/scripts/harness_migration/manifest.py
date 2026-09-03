from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .codec import digest_value, is_link_like, read_json
from .models import MigrationError, MigrationRule, RuleKind, TargetState


ALLOWED_MODES = {"fresh", "existing_trellis"}
ALLOWED_PROFILE_CAPABILITIES = {"codex-dispatch-workflow-v1"}
ALLOWED_POLICIES = {"copy", "skip", "preserve", "decision", "exclude", "generate"}
POLICY_COMBINATIONS = {
    RuleKind.REPLACEABLE_MANAGED: {("copy", "decision")},
    RuleKind.MERGE_REQUIRED: {("decision", "decision")},
    RuleKind.PRESERVE: {("preserve", "preserve")},
    RuleKind.RUNTIME_EXCLUDED: {("exclude", "exclude")},
    RuleKind.FRESH_ONLY_SKELETON: {("generate", "decision"), ("skip", "decision")},
    RuleKind.SUPPORT_ONLY: {("exclude", "exclude")},
}


@dataclass(frozen=True)
class Manifest:
    raw: dict[str, Any]
    path: Path
    digest: str
    template_version: str
    rules: tuple[MigrationRule, ...]
    profiles: dict[str, "MigrationProfile"]


@dataclass(frozen=True)
class MigrationProfile:
    include: tuple[str, ...]
    include_if_present: tuple[str, ...] = ()
    target_states: tuple[str, ...] = ()
    capability: str | None = None


def _normalized_pattern(pattern: object) -> str:
    if not isinstance(pattern, str) or not pattern or "\\" in pattern or "\0" in pattern or ":" in pattern:
        raise MigrationError(f"invalid migration rule path: {pattern!r}")
    path = PurePosixPath(pattern)
    if (
        path.is_absolute()
        or ".." in path.parts
        or pattern in {".", ".."}
        or path.as_posix() != pattern
    ):
        raise MigrationError(f"migration rule path must be normalized and relative: {pattern}")
    return pattern


def _specificity(pattern: str) -> tuple[int, int]:
    wildcard_count = pattern.count("*") + pattern.count("?")
    literal_count = len(pattern) - wildcard_count
    return literal_count, -wildcard_count


def _glob_regex(pattern: str) -> re.Pattern[str]:
    pieces: list[str] = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                pieces.append(".*")
                index += 2
            else:
                pieces.append("[^/]*")
                index += 1
        elif char == "?":
            pieces.append("[^/]")
            index += 1
        else:
            pieces.append(re.escape(char))
            index += 1
    return re.compile("^" + "".join(pieces) + "$")


def _glob_tokens(pattern: str) -> tuple[tuple[str, str | None], ...]:
    tokens: list[tuple[str, str | None]] = []
    index = 0
    while index < len(pattern):
        if pattern[index:index + 2] == "**":
            tokens.append(("star_any", None))
            index += 2
        elif pattern[index] == "*":
            tokens.append(("star_segment", None))
            index += 1
        elif pattern[index] == "?":
            tokens.append(("segment", None))
            index += 1
        else:
            tokens.append(("literal", pattern[index]))
            index += 1
    return tuple(tokens)


def _labels_overlap(left: tuple[str, str | None], right: tuple[str, str | None]) -> bool:
    left_kind, left_value = left
    right_kind, right_value = right
    if left_kind == "literal" and right_kind == "literal":
        return left_value == right_value
    if left_kind == "literal":
        return right_kind == "star_any" or left_value != "/"
    if right_kind == "literal":
        return left_kind == "star_any" or right_value != "/"
    return left_kind == "star_any" or right_kind == "star_any" or (
        left_kind in {"segment", "star_segment"}
        and right_kind in {"segment", "star_segment"}
    )


def _patterns_overlap(left: str, right: str) -> bool:
    """Return whether the two supported glob languages have any common path."""
    left_tokens = _glob_tokens(left)
    right_tokens = _glob_tokens(right)
    pending = [(0, 0)]
    visited: set[tuple[int, int]] = set()
    while pending:
        left_index, right_index = pending.pop()
        state = (left_index, right_index)
        if state in visited:
            continue
        visited.add(state)
        if left_index == len(left_tokens) and right_index == len(right_tokens):
            return True
        if left_index < len(left_tokens) and left_tokens[left_index][0].startswith("star_"):
            pending.append((left_index + 1, right_index))
        if right_index < len(right_tokens) and right_tokens[right_index][0].startswith("star_"):
            pending.append((left_index, right_index + 1))
        if left_index >= len(left_tokens) or right_index >= len(right_tokens):
            continue
        left_token = left_tokens[left_index]
        right_token = right_tokens[right_index]
        if not _labels_overlap(left_token, right_token):
            continue
        next_left = left_index if left_token[0].startswith("star_") else left_index + 1
        next_right = right_index if right_token[0].startswith("star_") else right_index + 1
        pending.append((next_left, next_right))
    return False


def rule_matches(rule: MigrationRule, relative: str) -> bool:
    return bool(_glob_regex(rule.path).match(relative))


def matching_rule(rules: tuple[MigrationRule, ...], relative: str) -> MigrationRule:
    matches = [rule for rule in rules if rule_matches(rule, relative)]
    if not matches:
        raise MigrationError(f"source path has no migration disposition: {relative}")
    ranked = sorted(matches, key=lambda rule: _specificity(rule.path), reverse=True)
    if len(ranked) > 1 and _specificity(ranked[0].path) == _specificity(ranked[1].path):
        raise MigrationError(f"source path has ambiguous migration rules: {relative}")
    return ranked[0]


def _expand_exported_files(
    root: Path,
    raw: dict[str, Any],
    *,
    additional_paths: tuple[str, ...] = (),
) -> set[str]:
    candidates: set[str] = set()
    copy_groups = raw.get("currentSourceCopyGroups")
    skeleton = raw.get("defaultSkeleton")
    placeholders = raw.get("placeholderOnly")
    support_files = raw.get("supportFiles")
    if not isinstance(copy_groups, list) or not all(isinstance(item, str) for item in copy_groups):
        raise MigrationError("currentSourceCopyGroups must be an array of paths or globs")
    if not isinstance(skeleton, dict) or set(skeleton) != {"source", "developer", "paths"} or not isinstance(skeleton.get("paths"), list) or not all(
        isinstance(item, str) for item in skeleton["paths"]
    ):
        raise MigrationError("defaultSkeleton must contain typed source, developer, and paths fields")
    if not isinstance(skeleton["source"], str) or not skeleton["source"] or not isinstance(skeleton["developer"], str) or not skeleton["developer"]:
        raise MigrationError("defaultSkeleton source and developer must be non-empty strings")
    for label, values in (("placeholderOnly", placeholders), ("supportFiles", support_files)):
        if not isinstance(values, list) or not all(
            isinstance(item, dict)
            and set(item) == {"path", "reason"}
            and isinstance(item["path"], str)
            and isinstance(item["reason"], str)
            and bool(item["reason"])
            for item in values
        ):
            raise MigrationError(f"{label} must be an array of typed path records")
    declared = list(copy_groups)
    declared.extend(skeleton["paths"])
    declared.extend(item["path"] for item in placeholders)
    declared.extend(item["path"] for item in support_files)
    all_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() or is_link_like(path)
    }
    for relative in additional_paths:
        normalized = _normalized_pattern(relative)
        if "*" in normalized or "?" in normalized:
            raise MigrationError(f"additional exported path must not contain wildcards: {relative}")
        all_files.add(normalized)
    policy = raw.get("migrationPolicy", {})
    exclude_values = policy.get("sourceExcludes", []) if isinstance(policy, dict) else []
    if not isinstance(exclude_values, list) or not all(isinstance(item, str) for item in exclude_values):
        raise MigrationError("migrationPolicy.sourceExcludes must be an array of paths or globs")
    exclude_patterns = [_glob_regex(_normalized_pattern(item)) for item in exclude_values]
    for pattern in declared:
        normalized = _normalized_pattern(pattern)
        regex = _glob_regex(normalized)
        matched = False
        for relative in all_files:
            if regex.match(relative) and not any(exclude.match(relative) for exclude in exclude_patterns):
                candidates.add(relative)
                matched = True
        if not matched and not any(token in normalized for token in "*?"):
            raise MigrationError(f"required exported path is missing: {normalized}")
    return candidates


def _migration_profiles(raw: dict[str, Any], exported: set[str]) -> dict[str, MigrationProfile]:
    values = raw.get("migrationProfiles")
    if not isinstance(values, dict) or not values:
        raise MigrationError("migrationProfiles must be a non-empty object")
    profiles: dict[str, MigrationProfile] = {}
    for name, value in values.items():
        allowed_keys = {"include", "includeIfPresent", "requires"}
        if (
            not isinstance(name, str)
            or not name
            or not isinstance(value, dict)
            or not set(value).issubset(allowed_keys)
            or "include" not in value
            or not isinstance(value.get("include"), list)
            or not value["include"]
            or not all(isinstance(item, str) for item in value["include"])
        ):
            raise MigrationError("each migration profile must contain a non-empty include array")
        patterns = tuple(_normalized_pattern(item) for item in value["include"])
        if len(set(patterns)) != len(patterns):
            raise MigrationError(f"migration profile contains duplicate include patterns: {name}")
        for pattern in patterns:
            regex = _glob_regex(pattern)
            if not any(regex.match(relative) for relative in exported):
                raise MigrationError(f"migration profile pattern matched no exported path: {name}: {pattern}")
        optional_values = value.get("includeIfPresent", [])
        if not isinstance(optional_values, list) or not all(isinstance(item, str) for item in optional_values):
            raise MigrationError(f"migration profile includeIfPresent must be an array: {name}")
        optional_patterns = tuple(_normalized_pattern(item) for item in optional_values)
        if len(set(optional_patterns)) != len(optional_patterns) or set(patterns) & set(optional_patterns):
            raise MigrationError(f"migration profile contains duplicate include patterns: {name}")
        requires = value.get("requires")
        target_states: tuple[str, ...] = ()
        capability: str | None = None
        if requires is not None:
            if (
                not isinstance(requires, dict)
                or set(requires) != {"targetStates", "capability"}
                or not isinstance(requires.get("targetStates"), list)
                or not requires["targetStates"]
                or not all(isinstance(item, str) for item in requires["targetStates"])
                or len(set(requires["targetStates"])) != len(requires["targetStates"])
                or set(requires["targetStates"]) - {state.value for state in TargetState}
                or not isinstance(requires.get("capability"), str)
                or not requires["capability"]
                or requires["capability"] not in ALLOWED_PROFILE_CAPABILITIES
            ):
                raise MigrationError(f"migration profile requires is invalid: {name}")
            target_states = tuple(requires["targetStates"])
            capability = requires["capability"]
        profiles[name] = MigrationProfile(patterns, optional_patterns, target_states, capability)
    if profiles.get("complete") is None or profiles["complete"].include != ("**",):
        raise MigrationError("migration profile complete must include exactly **")
    workflow_profile = profiles.get("agent-workflow")
    if workflow_profile is not None and (
        workflow_profile.target_states != (TargetState.EXISTING_TRELLIS.value,)
        or workflow_profile.capability != "codex-dispatch-workflow-v1"
    ):
        raise MigrationError("migration profile agent-workflow has invalid applicability requirements")
    return profiles


def load_manifest(
    template_root: Path,
    *,
    additional_exported_paths: tuple[str, ...] = (),
) -> Manifest:
    path = template_root / "export-manifest.json"
    raw = read_json(path)
    if raw.get("schemaVersion") != 2 or isinstance(raw.get("schemaVersion"), bool):
        raise MigrationError("manifest requires schemaVersion 2")
    if not isinstance(raw.get("sourceVersion"), str) or not raw["sourceVersion"]:
        raise MigrationError("manifest sourceVersion must be a non-empty string")
    policy = raw.get("migrationPolicy")
    if (
        not isinstance(policy, dict)
        or set(policy) != {"schemaVersion", "sourceExcludes", "migrationRules"}
        or policy.get("schemaVersion") != 1
        or isinstance(policy.get("schemaVersion"), bool)
    ):
        raise MigrationError("manifest requires migrationPolicy schemaVersion 1")
    rule_values = policy.get("migrationRules")
    if not isinstance(rule_values, list) or not rule_values:
        raise MigrationError("manifest migrationRules must be a non-empty array")
    rules: list[MigrationRule] = []
    for value in rule_values:
        if not isinstance(value, dict) or set(value) != {
            "path", "kind", "modes", "onExisting", "onModified", "sourceRequired"
        }:
            raise MigrationError("each migration rule must contain only the typed policy fields")
        try:
            kind = RuleKind(value["kind"])
        except (TypeError, ValueError) as exc:
            raise MigrationError(f"invalid migration rule kind: {value.get('kind')}") from exc
        mode_values = value["modes"]
        if not isinstance(mode_values, list) or not mode_values or not all(isinstance(item, str) for item in mode_values):
            raise MigrationError(f"invalid migration rule modes for {value['path']}")
        modes = tuple(mode_values)
        if len(set(modes)) != len(modes) or set(modes) - ALLOWED_MODES:
            raise MigrationError(f"invalid migration rule modes for {value['path']}")
        if not isinstance(value["onExisting"], str) or not isinstance(value["onModified"], str) or (
            value["onExisting"] not in ALLOWED_POLICIES or value["onModified"] not in ALLOWED_POLICIES
        ):
            raise MigrationError(f"invalid migration rule action for {value['path']}")
        if not isinstance(value["sourceRequired"], bool):
            raise MigrationError(f"sourceRequired must be boolean for {value['path']}")
        if (value["onExisting"], value["onModified"]) not in POLICY_COMBINATIONS[kind]:
            raise MigrationError(f"migration rule actions are inconsistent with kind for {value['path']}")
        rules.append(MigrationRule(
            path=_normalized_pattern(value["path"]), kind=kind, modes=modes,
            on_existing=value["onExisting"], on_modified=value["onModified"],
            source_required=value["sourceRequired"],
        ))
    for index, left in enumerate(rules):
        for right in rules[index + 1:]:
            if _specificity(left.path) == _specificity(right.path) and _patterns_overlap(left.path, right.path):
                raise MigrationError(f"migration rules overlap at equal specificity: {left.path}, {right.path}")
    exported = _expand_exported_files(
        template_root,
        raw,
        additional_paths=additional_exported_paths,
    )
    profiles = _migration_profiles(raw, exported)
    result = Manifest(raw, path, digest_value(raw), raw["sourceVersion"], tuple(rules), profiles)
    for relative in sorted(exported):
        matching_rule(result.rules, relative)
    for rule in result.rules:
        if rule.source_required and not any(rule_matches(rule, path) for path in exported):
            raise MigrationError(f"source-required migration rule matched no exported path: {rule.path}")
    return result


def exported_files(
    template_root: Path,
    manifest: Manifest,
    profile: str = "complete",
    *,
    additional_exported_paths: tuple[str, ...] = (),
) -> list[str]:
    patterns = manifest.profiles.get(profile)
    if patterns is None:
        raise MigrationError(f"unknown migration profile: {profile}")
    exported = _expand_exported_files(
        template_root,
        manifest.raw,
        additional_paths=additional_exported_paths,
    )
    return sorted(relative for relative in exported if profile_selects_path(manifest, profile, relative))


def profile_selects_path(manifest: Manifest, profile: str, relative: str) -> bool:
    """Return whether a normalized exported path belongs to a manifest profile."""
    record = manifest.profiles.get(profile)
    if record is None:
        raise MigrationError(f"unknown migration profile: {profile}")
    return any(
        _glob_regex(pattern).match(relative)
        for pattern in (*record.include, *record.include_if_present)
    )
