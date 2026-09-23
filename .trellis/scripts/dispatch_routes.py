"""Resolve persistent Codex implement/check dispatch lanes."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

from harness_migration.models import DISPATCH_CONFIG_PATH, ROUTE_CATALOG


DISPATCH_ROLES = ("implement", "check")
DISPATCH_LANES = ("default", "hard")
DISPATCH_LANE_ORDER = tuple(
    (role, lane) for role in DISPATCH_ROLES for lane in DISPATCH_LANES
)


@dataclass(frozen=True)
class DispatchRoute:
    """One resolved named dispatch lane and its explicit spawn override."""

    role: str
    lane: str
    route: str
    model: str
    effort: str

    @property
    def scope(self) -> str:
        return dispatch_scope(self.role, self.lane)


class DispatchRouteResolutionError(ValueError):
    """A fail-closed configuration problem for one requested dispatch lane."""

    def __init__(self, role: str, lane: str, reason: str):
        self.role = role
        self.lane = lane
        self.scope = dispatch_scope(role, lane)
        self.reason = reason
        super().__init__(f"{DISPATCH_CONFIG_PATH}: {self.scope}: {reason}")


def dispatch_scope(role: str, lane: str) -> str:
    return f"dispatch:{role}:{lane}"


def _fail(role: str, lane: str, reason: str) -> NoReturn:
    raise DispatchRouteResolutionError(role, lane, reason)


def _validate_selection(role: str, lane: str) -> None:
    if role not in DISPATCH_ROLES:
        _fail(role, lane, "unsupported_role")
    if lane not in DISPATCH_LANES:
        _fail(role, lane, "unsupported_lane")


def _dispatch_config_path(root: Path, role: str, lane: str) -> Path:
    declared_root = Path(os.path.abspath(root.expanduser()))
    try:
        if declared_root.is_symlink():
            _fail(role, lane, "invalid_root")
        resolved_root = declared_root.resolve(strict=True)
    except (OSError, RuntimeError):
        _fail(role, lane, "invalid_root")
    if resolved_root != declared_root or not resolved_root.is_dir():
        _fail(role, lane, "invalid_root")

    path = resolved_root
    parts = DISPATCH_CONFIG_PATH.split("/")
    for index, part in enumerate(parts):
        path = path / part
        try:
            if path.is_symlink():
                reason = "not_regular_file" if index == len(parts) - 1 else "unsafe_path"
                _fail(role, lane, reason)
            if path.exists() and index < len(parts) - 1 and not path.is_dir():
                _fail(role, lane, "path_parent_not_directory")
        except OSError:
            _fail(role, lane, "unreadable_path")

    try:
        resolved_path = path.resolve(strict=False)
        resolved_path.relative_to(resolved_root)
    except (OSError, RuntimeError, ValueError):
        _fail(role, lane, "unsafe_path")
    return path


def _load_document(root: Path, role: str, lane: str) -> dict[str, Any]:
    path = _dispatch_config_path(root, role, lane)
    if not path.exists():
        _fail(role, lane, "missing_file")
    if not path.is_file():
        _fail(role, lane, "not_regular_file")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        _fail(role, lane, "non_utf8_toml")
    except OSError:
        _fail(role, lane, "unreadable_file")
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        _fail(role, lane, "malformed_toml")
    raise AssertionError("tomllib.loads either returns or raises")


def _lane_values(
    document: dict[str, Any], role: str, lane: str
) -> dict[str, Any]:
    role_values = document.get(role)
    if role_values is None:
        _fail(role, lane, "missing_table")
    if not isinstance(role_values, dict):
        _fail(role, lane, "invalid_table")
    values = role_values.get(lane)
    if values is None:
        _fail(role, lane, "missing_table")
    if not isinstance(values, dict):
        _fail(role, lane, "invalid_table")
    return values


def _string_fields(values: dict[str, Any], role: str, lane: str) -> tuple[str, str]:
    model = values.get("model")
    effort = values.get("model_reasoning_effort")
    if "model" not in values and "model_reasoning_effort" not in values:
        _fail(role, lane, "missing_model_and_effort")
    if "model" not in values:
        _fail(role, lane, "missing_model")
    if "model_reasoning_effort" not in values:
        _fail(role, lane, "missing_effort")
    if type(model) is not str:
        _fail(role, lane, "model_not_string")
    if type(effort) is not str:
        _fail(role, lane, "effort_not_string")
    if not model:
        _fail(role, lane, "model_empty")
    if not effort:
        _fail(role, lane, "effort_empty")
    return model, effort


def resolve_dispatch_lane(root: Path | str, role: str, lane: str) -> DispatchRoute:
    """Resolve one persisted lane or raise a precise fail-closed diagnostic."""
    _validate_selection(role, lane)
    values = _lane_values(_load_document(Path(root), role, lane), role, lane)
    model, effort = _string_fields(values, role, lane)
    scope = dispatch_scope(role, lane)
    allowed = ROUTE_CATALOG.get(scope)
    if allowed is None:
        _fail(role, lane, "unsupported_scope")
    for route, pair in allowed.items():
        if (model, effort) == pair:
            return DispatchRoute(role, lane, route, model, effort)
    return DispatchRoute(role, lane, "custom", model, effort)


def resolve_all_dispatch_lanes(root: Path | str) -> tuple[DispatchRoute, ...]:
    """Resolve every lane in stable order for main-session workflow context."""
    return tuple(
        resolve_dispatch_lane(root, role, lane)
        for role, lane in DISPATCH_LANE_ORDER
    )


__all__ = [
    "DISPATCH_CONFIG_PATH",
    "DISPATCH_LANE_ORDER",
    "DISPATCH_LANES",
    "DISPATCH_ROLES",
    "DispatchRoute",
    "DispatchRouteResolutionError",
    "dispatch_scope",
    "resolve_all_dispatch_lanes",
    "resolve_dispatch_lane",
]
