from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from .codec import is_link_like
from .models import ExitCode, MigrationError, TargetState


def resolve_directory(path_value: str, label: str) -> Path:
    declared = Path(os.path.abspath(Path(path_value).expanduser()))
    if is_link_like(declared):
        raise MigrationError(
            f"{label} root must not be link-like or rebound: {declared}",
            exit_code=ExitCode.BLOCKED,
        )
    try:
        resolved = declared.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise MigrationError(
            f"cannot resolve {label} root: {declared}: {exc}", exit_code=ExitCode.BLOCKED,
        ) from exc
    if resolved != declared:
        raise MigrationError(
            f"{label} root must not be link-like or rebound: {declared}",
            exit_code=ExitCode.BLOCKED,
        )
    if not declared.exists() or not declared.is_dir():
        raise MigrationError(f"{label} root is not an existing directory: {declared}")
    return resolved


def is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def validate_root_relationship(template: Path, target: Path) -> None:
    if template == target or is_relative_to(template, target) or is_relative_to(target, template):
        raise MigrationError("template and target roots must be disjoint", exit_code=3)


def contained_path(root: Path, relative: str, *, allow_missing: bool = True) -> Path:
    if is_link_like(root) or root.resolve(strict=False) != root:
        raise MigrationError(f"declared root was rebound through a link: {root}", exit_code=3)
    candidate = root.joinpath(*relative.split("/"))
    current = root
    parts = PureParts(relative)
    for index, part in enumerate(parts):
        current = current / part
        if is_link_like(current):
            raise MigrationError(f"symlink traversal is unsupported: {current}", exit_code=3)
        if current.exists():
            if index < len(parts) - 1 and not current.is_dir():
                raise MigrationError(f"path parent is not a directory: {current}", exit_code=3)
        elif allow_missing:
            break
        else:
            raise MigrationError(f"required path does not exist: {current}", exit_code=3)
    resolved = candidate.resolve(strict=False)
    if not is_relative_to(resolved, root):
        raise MigrationError(f"path escapes declared root: {relative}", exit_code=3)
    return candidate


def PureParts(relative: str) -> tuple[str, ...]:
    parts = tuple(relative.split("/"))
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise MigrationError(f"invalid relative path: {relative}")
    return parts


def resolve_recorded_directory(path_value: str, label: str, *, exit_code: ExitCode) -> Path:
    recorded = Path(path_value).expanduser()
    if not recorded.is_absolute() or is_link_like(recorded):
        raise MigrationError(f"recorded {label} root is not a canonical directory: {recorded}", exit_code=exit_code)
    try:
        resolved = resolve_directory(str(recorded), label)
    except MigrationError as exc:
        raise MigrationError(str(exc), exit_code=exit_code) from exc
    if resolved != recorded:
        raise MigrationError(f"recorded {label} root was rebound: {recorded}", exit_code=exit_code)
    return resolved


def _git(target: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ["git", "-C", str(target), *arguments], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=20, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MigrationError(f"cannot inspect target Git worktree: {exc}", exit_code=3) from exc


def require_git_worktree(target: Path) -> None:
    probe = _git(target, "rev-parse", "--show-toplevel")
    if probe.returncode != 0:
        raise MigrationError("target must be a Git worktree", exit_code=3)
    top = Path(probe.stdout.strip()).resolve()
    if top != target:
        raise MigrationError("target must be the root of its Git worktree", exit_code=3)


def git_is_dirty(target: Path) -> bool:
    result = _git(target, "status", "--porcelain=v1", "--untracked-files=all")
    if result.returncode != 0:
        raise MigrationError("unable to inspect target Git status", exit_code=3)
    return bool(result.stdout.strip())


def active_sessions(target: Path) -> list[str]:
    sessions = target / ".trellis" / ".runtime" / "sessions"
    try:
        sessions_metadata = sessions.lstat()
    except FileNotFoundError:
        return []
    except OSError:
        return [str(sessions)]
    if is_link_like(sessions) or not stat.S_ISDIR(sessions_metadata.st_mode):
        return [str(sessions)]
    active: list[str] = []
    pending = [sessions]
    while pending:
        directory = pending.pop()
        try:
            children = sorted(directory.iterdir(), key=lambda path: path.name)
        except OSError:
            active.append(directory.relative_to(sessions).as_posix() or ".")
            continue
        for path in children:
            relative = path.relative_to(sessions).as_posix()
            try:
                metadata = path.lstat()
            except OSError:
                active.append(relative)
                continue
            if is_link_like(path):
                active.append(relative)
                continue
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                active.append(relative)
                continue
            if path.suffix.lower() != ".json":
                continue
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError):
                active.append(relative)
                continue
            if value not in ({}, [], None):
                active.append(relative)
    return sorted(active)


def classify_target(target: Path) -> TargetState:
    trellis = target / ".trellis"
    codex = target / ".codex"
    if not trellis.exists():
        return TargetState.UNSUPPORTED_PARTIAL if codex.exists() else TargetState.FRESH
    if is_link_like(trellis) or not trellis.is_dir():
        return TargetState.UNSUPPORTED_PARTIAL
    required_markers = (trellis / "config.yaml", trellis / "workflow.md")
    if not all(path.is_file() and not is_link_like(path) for path in required_markers):
        return TargetState.UNSUPPORTED_PARTIAL
    return TargetState.EXISTING_TRELLIS


def apply_blockers(target: Path) -> list[str]:
    blockers: list[str] = []
    try:
        require_git_worktree(target)
    except MigrationError as exc:
        blockers.append(str(exc))
    else:
        if git_is_dirty(target):
            blockers.append("target Git worktree is dirty")
    sessions = active_sessions(target)
    if sessions:
        blockers.append("active runtime session state exists: " + ", ".join(sessions))
    return blockers


def validate_backup_root(backup: Path, template: Path, target: Path) -> None:
    backup = backup.resolve(strict=False)
    for root, label in ((template, "template"), (target, "target")):
        if backup == root or is_relative_to(backup, root) or is_relative_to(root, backup):
            raise MigrationError(f"backup root must be external to {label} root", exit_code=3)
