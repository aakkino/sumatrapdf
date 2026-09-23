from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any

from .models import MigrationError


MISSING_DIGEST = "missing"


def canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def digest_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MigrationError(f"JSON document must be an object: {path}")
    return value


def atomic_write_json(path: Path, value: Any) -> None:
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_value = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
        )
        temporary = Path(temporary_value)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        raise MigrationError(f"cannot atomically write JSON {path}: {exc}") from exc
    finally:
        if temporary is not None and temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def is_link_like(path: Path) -> bool:
    """Return whether a path is a symlink or Windows junction/mount point."""
    if path.is_symlink():
        return True
    try:
        reparse_tag = getattr(path.lstat(), "st_reparse_tag", 0)
    except OSError:
        return False
    return reparse_tag in {
        getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", -1),
        getattr(stat, "IO_REPARSE_TAG_SYMLINK", -1),
    }


def digest_path(path: Path) -> str:
    try:
        if not path.exists() and not is_link_like(path):
            return MISSING_DIGEST
        if is_link_like(path):
            raise MigrationError(f"symlinks are unsupported: {path}")
        if path.is_file():
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            return "sha256:" + digest.hexdigest()
        if path.is_dir():
            entries: list[dict[str, str]] = []
            for child in sorted(path.rglob("*"), key=lambda item: item.as_posix()):
                relative = child.relative_to(path).as_posix()
                if is_link_like(child):
                    raise MigrationError(f"symlinks are unsupported: {child}")
                if child.is_file():
                    entries.append({"path": relative, "digest": digest_path(child)})
            return digest_value(entries)
        raise MigrationError(f"unsupported filesystem entry: {path}")
    except OSError as exc:
        raise MigrationError(f"cannot inspect filesystem entry {path}: {exc}") from exc


def without_digest(value: dict[str, Any], field: str) -> dict[str, Any]:
    copy = dict(value)
    copy.pop(field, None)
    return copy
