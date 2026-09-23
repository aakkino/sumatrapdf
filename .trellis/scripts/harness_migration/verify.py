from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .codec import digest_path
from .models import ExitCode, MigrationError
from .safety import contained_path
from .transaction import _write_receipt, load_receipt, project_state_digests, validate_receipt_roots

DEFAULT_COMMAND_TIMEOUT_SECONDS = 120
UNITTEST_COMMAND_TIMEOUT_SECONDS = 1_200


def _command_timeout_seconds(command: list[str]) -> int:
    if command[:3] == ["python", "-m", "unittest"]:
        return UNITTEST_COMMAND_TIMEOUT_SECONDS
    return DEFAULT_COMMAND_TIMEOUT_SECONDS


def _run(command: list[str], target: Path) -> dict[str, Any]:
    executable = command[0]
    resolved_executable = shutil.which(executable)
    if resolved_executable is None:
        return {"command": command, "status": "unavailable", "exitCode": None, "stdout": "", "stderr": f"{executable} is unavailable"}
    try:
        environment = os.environ.copy()
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        result = subprocess.run(
            [resolved_executable, *command[1:]], cwd=target, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=_command_timeout_seconds(command), check=False, env=environment,
        )
        no_current_task = False
        if (
            command[1:] == [".trellis/scripts/task.py", "current", "--json"]
            and result.returncode == 1
            and not result.stderr.strip()
        ):
            try:
                current = json.loads(result.stdout)
                no_current_task = isinstance(current, dict) and current.get("current_task", object()) is None
            except json.JSONDecodeError:
                pass
        status = "passed" if result.returncode == 0 or no_current_task else "failed"
        return {"command": command, "status": status, "exitCode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"command": command, "status": "failed", "exitCode": None, "stdout": "", "stderr": str(exc)}


def _integrity_checks(receipt: dict[str, Any], target: Path) -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    for entry in receipt["journal"]:
        expected = entry["expectedPostDigest"]
        recorded = entry.get("postDigest")
        check = {
            "kind": "installed_digest", "path": entry["path"], "status": "failed",
            "expected": expected, "recorded": recorded, "actual": None,
        }
        try:
            check["actual"] = digest_path(contained_path(target, entry["path"]))
        except (MigrationError, OSError) as exc:
            check["error"] = str(exc)
        check["status"] = (
            "passed"
            if recorded is not None and recorded == expected and check["actual"] == expected
            else "failed"
        )
        checks.append(check)
    for relative, expected in sorted(receipt.get("preservedDigests", {}).items()):
        check = {
            "kind": "preserved_digest", "path": relative, "status": "failed",
            "expected": expected, "actual": None,
        }
        try:
            check["actual"] = digest_path(contained_path(target, relative))
        except (MigrationError, OSError) as exc:
            check["error"] = str(exc)
        check["status"] = "passed" if check["actual"] == expected else "failed"
        checks.append(check)
    project_state = receipt.get("projectStateDigests")
    if project_state is not None:
        mutation_paths = {entry["path"] for entry in receipt["journal"]}
        values: dict[str, str] | None = None
        error: str | None = None
        try:
            values = project_state_digests(target, mutation_paths)
        except (MigrationError, OSError) as exc:
            error = str(exc)
        for relative, expected in sorted(project_state.items()):
            check = {
                "kind": "project_state_digest", "path": relative, "status": "failed",
                "expected": expected, "actual": None,
            }
            if values is not None:
                check["actual"] = values.get(relative)
            else:
                check["error"] = error
            check["status"] = "passed" if check["actual"] == expected else "failed"
            checks.append(check)
    for state in receipt.get("quarantinedTargetStates", []):
        check = {
            "kind": "quarantined_target_unchanged",
            "path": state["path"],
            "status": "failed",
            "preDigest": state["preDigest"],
            "postDigest": state["postDigest"],
            "actual": None,
        }
        try:
            check["actual"] = digest_path(contained_path(target, state["path"]))
        except (MigrationError, OSError) as exc:
            check["error"] = str(exc)
        check["status"] = (
            "passed"
            if check["actual"] == state["preDigest"] == state["postDigest"]
            else "failed"
        )
        checks.append(check)
    return checks


def _verification_context(receipt_path: Path) -> tuple[dict[str, Any], Path]:
    try:
        receipt = load_receipt(receipt_path)
    except MigrationError as exc:
        raise MigrationError(str(exc), exit_code=ExitCode.VERIFICATION_FAILED) from exc
    if receipt["status"] not in {"applied", "verified", "verified_incomplete", "verification_failed"}:
        raise MigrationError(f"receipt status cannot be verified: {receipt['status']}", exit_code=ExitCode.VERIFICATION_FAILED)
    target, _ = validate_receipt_roots(receipt, receipt_path, exit_code=ExitCode.VERIFICATION_FAILED)
    return receipt, target


def _verification_report(
    receipt_path: Path,
    checks: list[dict[str, Any]],
    command_results: list[dict[str, Any]],
    sidecars: list[str],
) -> dict[str, Any]:
    failed = any(check["status"] != "passed" for check in checks) or any(
        result["status"] != "passed" for result in command_results
    )
    status = "failed" if failed else "incomplete" if sidecars else "success"
    return {
        "schemaVersion": 1,
        "status": status,
        "receiptPath": str(receipt_path.resolve()),
        "checks": checks,
        "commands": command_results,
        "unresolvedSidecars": sidecars,
    }


def verify_integrity(receipt_path: Path) -> dict[str, Any]:
    receipt, target = _verification_context(receipt_path)
    checks = _integrity_checks(receipt, target)
    sidecars = sorted(entry["path"] for entry in receipt["journal"] if entry["operation"] == "sidecar")
    report = _verification_report(receipt_path, checks, [], sidecars)
    report["mode"] = "integrity-only"
    return report


def verify_receipt(receipt_path: Path, *, run_commands: bool = True) -> dict[str, Any]:
    receipt, target = _verification_context(receipt_path)
    checks = _integrity_checks(receipt, target)
    precheck_failed = any(check["status"] != "passed" for check in checks)
    command_results = []
    if run_commands and not precheck_failed:
        command_results = [_run(command, target) for command in receipt["verificationCommands"]]
        checks = _integrity_checks(receipt, target)
    sidecars = sorted(entry["path"] for entry in receipt["journal"] if entry["operation"] == "sidecar")
    report = _verification_report(receipt_path, checks, command_results, sidecars)
    receipt["verification"] = report
    receipt["status"] = (
        "verification_failed"
        if report["status"] == "failed"
        else "verified_incomplete"
        if report["status"] == "incomplete"
        else "verified"
    )
    try:
        _write_receipt(receipt_path, receipt)
    except MigrationError as exc:
        raise MigrationError(f"cannot record verification result: {exc}", exit_code=ExitCode.VERIFICATION_FAILED) from exc
    return report
