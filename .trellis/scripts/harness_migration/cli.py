from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .codec import atomic_write_json, read_json
from .inspect import inspect_routes, inspect_template
from .models import ExitCode, MigrationError, plan_from_dict
from .planner import build_plan, resolve_plan
from .recovery import (
    apply_recovery_plan,
    build_recovery_plan,
    recovery_plan_from_dict,
    resolve_recovery_plan,
)
from .release import (
    apply_release_plan,
    build_release_plan,
    rollback_release_receipt,
    verify_release_receipt,
)
from .transaction import apply_plan, rollback_receipt
from .verify import verify_integrity, verify_receipt


class _ProvidedAction(argparse.Action):
    """Preserve defaults while recording explicit operator intent."""

    def __call__(self, parser, namespace, values, option_string=None) -> None:
        setattr(namespace, self.dest, values)
        setattr(namespace, f"{self.dest}_provided", True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="harness_migrate.py", description="Plan and execute deterministic Harness migrations.")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = commands.add_parser("inspect", help="report source Harness structure and provenance")
    inspect_parser.add_argument("--template", required=True)
    inspect_parser.add_argument("--profile")
    inspect_parser.add_argument("--format", choices=("human", "json"), default="human")
    inspect_routes_parser = commands.add_parser("inspect-routes", help="report effective persistent model routes in a target")
    inspect_routes_parser.add_argument("--target", required=True)
    inspect_routes_parser.add_argument("--format", choices=("human", "json"), default="human")
    plan = commands.add_parser("plan", help="inspect a target and emit a non-mutating migration plan")
    plan.add_argument("--template", required=True)
    plan.add_argument("--target", required=True)
    plan.add_argument("--developer", action=_ProvidedAction)
    plan.set_defaults(profile_provided=False, developer_provided=False)
    plan.add_argument(
        "--profile", default="complete", action=_ProvidedAction,
        help="manifest-owned migration profile (default: complete; explicit for --adopt-partial)",
    )
    plan.add_argument("--adopt-partial", action="store_true", help="adopt only an unsupported partial target with the complete profile")
    plan.add_argument("--route", action="append", default=[], metavar="SCOPE=ROUTE", help="approved named route override (repeatable)")
    plan.add_argument("--route-pair", action="append", default=[], metavar="SCOPE=MODEL,EFFORT", help="custom model and effort pair for --route-only (repeatable)")
    plan.add_argument("--route-only", action="store_true", help="select only files owned by the requested routes")
    plan.add_argument("--development-template", action="store_true", help="explicitly admit an authoring template for development-only apply")
    plan.add_argument("--format", choices=("human", "json"), default="human")
    plan.add_argument("--output")
    resolve = commands.add_parser("resolve", help="apply validated choices to a saved plan")
    resolve.add_argument("--plan", required=True)
    resolve.add_argument("--decision", action="append", default=[])
    resolve.add_argument("--output", required=True)
    apply = commands.add_parser("apply", help="apply an approved, fully resolved plan")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--approve", action="store_true")
    apply.add_argument("--backup")
    apply.add_argument("--receipt")
    apply.add_argument("--format", choices=("human", "json"), default="human")
    verify = commands.add_parser("verify", help="verify an apply receipt and target state")
    verify.add_argument("--receipt", required=True)
    verify.add_argument(
        "--integrity-only",
        action="store_true",
        help="read-only integrity check; skips receipt commands and does not complete full verification",
    )
    verify.add_argument("--format", choices=("human", "json"), default="human")
    rollback = commands.add_parser("rollback", help="restore migration-owned paths from a receipt")
    rollback.add_argument("--receipt", required=True)
    rollback.add_argument("--approve", action="store_true")
    rollback.add_argument("--format", choices=("human", "json"), default="human")
    recover_plan = commands.add_parser("recover-plan", help="inspect an unsupported partial target and emit a baseline-bound recovery plan")
    recover_plan.add_argument("--template", required=True)
    recover_plan.add_argument("--target", required=True)
    recover_plan.add_argument("--baseline", required=True)
    recover_plan.add_argument("--format", choices=("human", "json"), default="human")
    recover_plan.add_argument("--output")
    recover_resolve = commands.add_parser("recover-resolve", help="apply validated choices to a saved recovery plan")
    recover_resolve.add_argument("--plan", required=True)
    recover_resolve.add_argument("--decision", action="append", default=[])
    recover_resolve.add_argument("--output", required=True)
    recover_apply = commands.add_parser("recover-apply", help="apply an approved, fully resolved recovery plan")
    recover_apply.add_argument("--plan", required=True)
    recover_apply.add_argument("--approve", action="store_true")
    recover_apply.add_argument("--backup")
    recover_apply.add_argument("--receipt")
    recover_apply.add_argument("--format", choices=("human", "json"), default="human")
    release_plan = commands.add_parser("release-plan", help="emit a deterministic authoring-to-release projection plan")
    release_plan.add_argument("--authoring-template", required=True)
    release_plan.add_argument("--release", required=True)
    release_plan.add_argument("--format", choices=("human", "json"), default="human")
    release_plan.add_argument("--output")
    release_apply = commands.add_parser("release-apply", help="apply an approved release projection plan")
    release_apply.add_argument("--plan", required=True)
    release_apply.add_argument("--approve", action="store_true")
    release_apply.add_argument("--backup")
    release_apply.add_argument("--receipt")
    release_apply.add_argument("--format", choices=("human", "json"), default="human")
    release_verify = commands.add_parser("release-verify", help="verify a release projection receipt")
    release_verify.add_argument("--receipt", required=True)
    release_verify.add_argument("--format", choices=("human", "json"), default="human")
    release_rollback = commands.add_parser("release-rollback", help="restore release-owned preimages")
    release_rollback.add_argument("--receipt", required=True)
    release_rollback.add_argument("--approve", action="store_true")
    release_rollback.add_argument("--format", choices=("human", "json"), default="human")
    return parser


def _emit(value: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        sys.stdout.write(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n")
        return
    if "files" in value:
        print(f"Template: {value['templateRoot']}")
        print(f"Profile: {value['profile'] or 'all'}")
        print("Areas: " + ", ".join(f"{item['area']}={item['fileCount']}" for item in value["areas"]))
        for record in value["files"]:
            profiles = ",".join(record["profiles"]) or "-"
            baseline = record["baselineDigest"] or "-"
            current = record["currentDigest"] or "-"
            print(
                f"{record['path']}: {record['status']}; {record['presence']}; "
                f"{record['area']}/{record['platform']}; profiles={profiles}; "
                f"baseline={baseline}; current={current}"
            )
    elif "routes" in value:
        print(f"Target: {value['targetRoot']}")
        for route in value["routes"]:
            pair = f"{route['model'] or '-'} / {route['effort'] or '-'}"
            route_name = route["route"]
            observed = f"{route_name} ({pair})" if route_name else pair
            detail = f" [{route['detail']}]" if route["detail"] else ""
            table = f" [{route['table']}]" if "table" in route else ""
            print(f"{route['scope']}: {route['status']}; {observed}; {route['path']}{table}{detail}")
    elif value.get("kind") == "harness-release-plan":
        print(f"Release: {value['releaseRoot']}")
        print(f"Operations: {len(value['operations'])}")
        print(f"Plan digest: {value['planDigest']}")
    elif "targetState" in value:
        print(f"Target state: {value['targetState']}")
        if "sourceAdmission" in value:
            print(f"Source admission: {value['sourceAdmission']['kind']}")
        print(f"Actions: {len(value['actions'])}; blockers: {len(value['blockers'])}; decisions: {len(value['decisions'])}")
        print(f"Plan digest: {value['planDigest']}")
    elif "checks" in value:
        detail = ""
        if "unresolvedSidecars" in value:
            detail = f"; unresolved sidecars: {len(value['unresolvedSidecars'])}"
        print(f"Verification: {value['status']}; checks: {len(value['checks'])}{detail}")
    else:
        print(f"Status: {value.get('status', 'ok')}")
        if "receiptPath" in value:
            print(f"Receipt: {value['receiptPath']}")


def _load_plan(path_value: str):
    return plan_from_dict(read_json(Path(path_value).expanduser().resolve()))


def _load_recovery_plan(path_value: str):
    return recovery_plan_from_dict(read_json(Path(path_value).expanduser().resolve()))


def _selections(values: list[str], *, recovery: bool = False) -> dict[str, str]:
    selections: dict[str, str] = {}
    for item in values:
        if "=" not in item:
            prefix = "recovery " if recovery else ""
            raise MigrationError(f"{prefix}decision must use ID=choice syntax: {item}")
        identifier, choice = item.split("=", 1)
        if not identifier or identifier in selections:
            prefix = "recovery " if recovery else ""
            raise MigrationError(f"invalid or duplicate {prefix}decision ID: {identifier}")
        selections[identifier] = choice
    return selections


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            _emit(inspect_template(args.template, args.profile), args.format)
            return int(ExitCode.OK)
        if args.command == "inspect-routes":
            _emit(inspect_routes(args.target), args.format)
            return int(ExitCode.OK)
        if args.command == "plan":
            if args.route_only:
                if not args.route and not args.route_pair:
                    raise MigrationError("--route-only requires at least one --route or --route-pair")
                if args.profile_provided:
                    raise MigrationError("--route-only does not accept --profile")
                if args.developer_provided:
                    raise MigrationError("--route-only does not accept --developer")
                if args.adopt_partial:
                    raise MigrationError("--route-only does not accept --adopt-partial")
            if args.route_pair and not args.route_only:
                raise MigrationError("--route-pair requires --route-only")
            if args.adopt_partial and not args.profile_provided:
                raise MigrationError("--adopt-partial requires an explicit --profile complete")
            plan = build_plan(
                args.template, args.target, args.developer, args.profile,
                adopt_partial=args.adopt_partial,
                route_overrides=args.route,
                route_only=args.route_only,
                route_pairs=args.route_pair,
                development_template=args.development_template,
            )
            value = plan.to_dict()
            if args.output:
                atomic_write_json(Path(args.output).expanduser().resolve(), value)
            _emit(value, args.format)
            return int(ExitCode.BLOCKED if plan.blockers else ExitCode.OK)
        if args.command == "resolve":
            plan = resolve_plan(_load_plan(args.plan), _selections(args.decision))
            atomic_write_json(Path(args.output).expanduser().resolve(), plan.to_dict())
            _emit(plan.to_dict(), "human")
            return int(ExitCode.OK)
        if args.command == "apply":
            if not args.approve:
                raise MigrationError("apply requires --approve", exit_code=ExitCode.BLOCKED)
            receipt, receipt_path = apply_plan(_load_plan(args.plan), args.backup, args.receipt)
            value = {"status": receipt["status"], "receiptPath": str(receipt_path), "planDigest": receipt["planDigest"]}
            _emit(value, args.format)
            return int(ExitCode.OK)
        if args.command == "verify":
            receipt_path = Path(args.receipt).expanduser().resolve()
            report = verify_integrity(receipt_path) if args.integrity_only else verify_receipt(receipt_path)
            _emit(report, args.format)
            return int(ExitCode.OK if report["status"] == "success" else ExitCode.VERIFICATION_FAILED)
        if args.command == "rollback":
            if not args.approve:
                raise MigrationError("rollback requires --approve", exit_code=ExitCode.ROLLBACK_REFUSED)
            receipt = rollback_receipt(Path(args.receipt).expanduser().resolve())
            _emit({"status": receipt["status"], "receiptPath": str(Path(args.receipt).resolve())}, args.format)
            return int(ExitCode.OK)
        if args.command == "recover-plan":
            plan = build_recovery_plan(args.template, args.target, args.baseline)
            value = plan.to_dict()
            if args.output:
                atomic_write_json(Path(args.output).expanduser().resolve(), value)
            _emit(value, args.format)
            return int(ExitCode.BLOCKED if plan.blockers else ExitCode.OK)
        if args.command == "recover-resolve":
            plan = resolve_recovery_plan(_load_recovery_plan(args.plan), _selections(args.decision, recovery=True))
            atomic_write_json(Path(args.output).expanduser().resolve(), plan.to_dict())
            _emit(plan.to_dict(), "human")
            return int(ExitCode.OK)
        if args.command == "recover-apply":
            if not args.approve:
                raise MigrationError("recover-apply requires --approve", exit_code=ExitCode.BLOCKED)
            receipt, receipt_path = apply_recovery_plan(_load_recovery_plan(args.plan), args.backup, args.receipt)
            value = {"status": receipt["status"], "receiptPath": str(receipt_path), "planDigest": receipt["planDigest"]}
            _emit(value, args.format)
            return int(ExitCode.OK)
        if args.command == "release-plan":
            value = build_release_plan(args.authoring_template, args.release)
            if args.output:
                atomic_write_json(Path(args.output).expanduser().resolve(), value)
            _emit(value, args.format)
            return int(ExitCode.OK)
        if args.command == "release-apply":
            if not args.approve:
                raise MigrationError("release-apply requires --approve", exit_code=ExitCode.BLOCKED)
            receipt, receipt_path = apply_release_plan(read_json(Path(args.plan).expanduser().resolve()), args.backup, args.receipt)
            _emit({"status": receipt["status"], "receiptPath": str(receipt_path), "planDigest": receipt["planDigest"]}, args.format)
            return int(ExitCode.OK)
        if args.command == "release-verify":
            report = verify_release_receipt(Path(args.receipt).expanduser().resolve())
            _emit(report, args.format)
            return int(ExitCode.OK if report["status"] == "success" else ExitCode.VERIFICATION_FAILED)
        if args.command == "release-rollback":
            if not args.approve:
                raise MigrationError("release-rollback requires --approve", exit_code=ExitCode.ROLLBACK_REFUSED)
            receipt = rollback_release_receipt(Path(args.receipt).expanduser().resolve())
            _emit({"status": receipt["status"], "receiptPath": str(Path(args.receipt).resolve())}, args.format)
            return int(ExitCode.OK)
        raise MigrationError("unknown command")
    except MigrationError as exc:
        print(str(exc), file=sys.stderr)
        if getattr(args, "format", None) == "json":
            value = {"status": "error", "exitCode": int(exc.exit_code), "error": str(exc)}
            if exc.details is not None:
                value["details"] = exc.details
            _emit(value, "json")
        return int(exc.exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
