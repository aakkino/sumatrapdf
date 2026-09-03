from __future__ import annotations

import json
import re
import shlex
import tomllib
from hashlib import sha256
from pathlib import Path
from typing import Any

from dispatch_routes import (
    DISPATCH_LANE_ORDER,
    DispatchRouteResolutionError,
    resolve_dispatch_lane,
)

from .codec import is_link_like
from .models import ExitCode, MigrationError, TargetState
from .safety import contained_path


CAPABILITY = "codex-dispatch-workflow-v1"
REMEDIATION = "plan --profile dispatch-only"
ROLE_NAMES = ("check", "implement", "research")
SUPPORT_PATHS = (
    ".codex/config.toml",
    ".trellis/scripts/common/active_task.py",
    ".trellis/scripts/common/config.py",
    ".trellis/scripts/common/paths.py",
)


def _failure(code: str, path: str, detail: str | None = None) -> dict[str, str]:
    result = {"code": code, "path": path}
    if detail is not None:
        result["detail"] = detail
    return result


def _digest_bytes(data: bytes) -> str:
    return "sha256:" + sha256(data).hexdigest()


def _safe_bytes(target: Path, relative: str, failures: list[dict[str, str]]) -> bytes | None:
    try:
        path = contained_path(target, relative, allow_missing=True)
    except MigrationError:
        failures.append(_failure("unsafe_path", relative))
        return None
    if not path.exists():
        failures.append(_failure("missing_file", relative))
        return None
    if is_link_like(path) or not path.is_file():
        failures.append(_failure("not_regular_file", relative))
        return None
    try:
        return path.read_bytes()
    except OSError:
        failures.append(_failure("unreadable_file", relative))
        return None


def _utf8(
    target: Path,
    relative: str,
    failures: list[dict[str, str]],
) -> tuple[bytes, str] | None:
    data = _safe_bytes(target, relative, failures)
    if data is None:
        return None
    try:
        return data, data.decode("utf-8")
    except UnicodeDecodeError:
        failures.append(_failure("non_utf8_file", relative))
        return None


def _toml(
    target: Path,
    relative: str,
    failures: list[dict[str, str]],
) -> tuple[bytes, dict[str, Any]] | None:
    loaded = _utf8(target, relative, failures)
    if loaded is None:
        return None
    data, text = loaded
    try:
        return data, tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        failures.append(_failure("malformed_toml", relative))
        return None


def _json(
    target: Path,
    relative: str,
    failures: list[dict[str, str]],
) -> tuple[bytes, dict[str, Any]] | None:
    loaded = _utf8(target, relative, failures)
    if loaded is None:
        return None
    data, text = loaded
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        failures.append(_failure("malformed_json", relative))
        return None
    if not isinstance(value, dict):
        failures.append(_failure("invalid_json_root", relative))
        return None
    return data, value


def _hook_command(
    document: dict[str, Any],
    event: str,
    script: str,
    roles: tuple[str, ...],
    failures: list[dict[str, str]],
) -> dict[str, Any] | None:
    hooks = document.get("hooks")
    entries = hooks.get(event) if isinstance(hooks, dict) else None
    if not isinstance(entries, list):
        failures.append(_failure("missing_hook_event", ".codex/hooks.json", event))
        return None
    role_set = set(roles)
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        matcher = entry.get("matcher")
        if role_set:
            if not isinstance(matcher, str):
                continue
            try:
                compiled = re.compile(matcher)
            except re.error:
                continue
            if any(compiled.fullmatch(role) is None for role in roles):
                continue
        nested = entry.get("hooks")
        if not isinstance(nested, list):
            continue
        for hook in nested:
            if not isinstance(hook, dict) or hook.get("type") != "command":
                continue
            command = hook.get("command")
            if not isinstance(command, str):
                continue
            try:
                command_parts = shlex.split(command, posix=True)
            except ValueError:
                continue
            if not _invokes_python_script(command_parts, script):
                continue
            return {"event": event, "command": command, "roles": list(roles)}
    failures.append(_failure("missing_required_hook", ".codex/hooks.json", f"{event}:{script}"))
    return None


def _invokes_python_script(parts: list[str], script: str) -> bool:
    if not parts:
        return False
    executable = parts[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if executable not in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"}:
        return False
    arguments = parts[1:]
    return arguments in (
        [script],
        ["-X", "utf8", script],
        ["-Xutf8", script],
    )


def build_prerequisite_evidence(target: Path, target_state: TargetState) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    checked: dict[str, str] = {}
    if target_state != TargetState.EXISTING_TRELLIS:
        failures.append(_failure("incompatible_target_state", ".", target_state.value))

    for relative in SUPPORT_PATHS:
        if relative.endswith(".toml"):
            loaded = _toml(target, relative, failures)
            if loaded is not None:
                checked[relative] = _digest_bytes(loaded[0])
        else:
            data = _safe_bytes(target, relative, failures)
            if data is not None:
                checked[relative] = _digest_bytes(data)

    lanes: list[dict[str, str]] = []
    dispatch_path = ".codex/trellis-dispatch.toml"
    dispatch_bytes = _safe_bytes(target, dispatch_path, failures)
    dispatch_digest = _digest_bytes(dispatch_bytes) if dispatch_bytes is not None else None
    for role, lane in DISPATCH_LANE_ORDER:
        try:
            route = resolve_dispatch_lane(target, role, lane)
        except DispatchRouteResolutionError as exc:
            failures.append(_failure("invalid_dispatch_lane", dispatch_path, f"{exc.scope}:{exc.reason}"))
            continue
        lanes.append({
            "scope": route.scope,
            "route": route.route,
            "model": route.model,
            "effort": route.effort,
        })
    if dispatch_digest is not None:
        current_dispatch_bytes = _safe_bytes(target, dispatch_path, failures)
        if current_dispatch_bytes is None or _digest_bytes(current_dispatch_bytes) != dispatch_digest:
            failures.append(_failure("prerequisite_changed", dispatch_path))
        else:
            checked[dispatch_path] = dispatch_digest

    hook_path = ".codex/hooks.json"
    hook_records: list[dict[str, Any]] = []
    loaded_hooks = _json(target, hook_path, failures)
    if loaded_hooks is not None:
        checked[hook_path] = _digest_bytes(loaded_hooks[0])
        document = loaded_hooks[1]
        for event, script, roles in (
            ("SubagentStart", ".codex/hooks/inject-subagent-context.py", tuple(f"trellis-{role}" for role in ("implement", "check", "research"))),
            ("UserPromptSubmit", ".codex/hooks/inject-workflow-state.py", ()),
        ):
            record = _hook_command(document, event, script, roles, failures)
            if record is not None:
                hook_records.append(record)

    role_records: list[dict[str, Any]] = []
    for role in ROLE_NAMES:
        relative = f".codex/agents/trellis-{role}.toml"
        loaded = _toml(target, relative, failures)
        if loaded is None:
            continue
        data, document = loaded
        digest = _digest_bytes(data)
        checked[relative] = digest
        expected_name = f"trellis-{role}"
        if document.get("name") != expected_name:
            failures.append(_failure("invalid_role_identity", relative, expected_name))
        instructions = document.get("developer_instructions")
        if not isinstance(instructions, str) or not instructions.strip():
            failures.append(_failure("missing_role_instructions", relative, role))
        model_pinned = "model" in document or "model_reasoning_effort" in document
        if role in {"implement", "check"} and model_pinned:
            failures.append(_failure("pinned_dispatch_role", relative, role))
        role_records.append({
            "role": role,
            "path": relative,
            "name": document.get("name") if isinstance(document.get("name"), str) else "",
            "digest": digest,
            "modelPinned": model_pinned,
        })

    if failures:
        ordered = sorted(failures, key=lambda item: (item["code"], item["path"], item.get("detail", "")))
        raise MigrationError(
            f"profile admission failed for {CAPABILITY}; establish the dispatch baseline with {REMEDIATION}",
            exit_code=ExitCode.BLOCKED,
            details={
                "capability": CAPABILITY,
                "failures": ordered,
                "remediation": {"profile": "dispatch-only", "command": REMEDIATION},
            },
        )

    return {
        "capability": CAPABILITY,
        "status": "admitted",
        "checkedFiles": [
            {"path": path, "digest": checked[path]} for path in sorted(checked)
        ],
        "dispatchLanes": sorted(lanes, key=lambda item: item["scope"]),
        "hooks": sorted(hook_records, key=lambda item: item["event"]),
        "roles": sorted(role_records, key=lambda item: item["role"]),
    }


__all__ = ["CAPABILITY", "REMEDIATION", "build_prerequisite_evidence"]
