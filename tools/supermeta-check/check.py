#!/usr/bin/env python3
"""Focused verification lane selection for Codex Bootstrap generated projects."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CHECKS_POLICY = Path(".codex-bootstrap/checks.json")
LOCAL_POLICY = Path(".codex-bootstrap/checks.local.json")
SCHEMA_VERSION = 1


class SmartCheckError(Exception):
    pass


@dataclass(frozen=True)
class CheckTriggers:
    paths: tuple[str, ...]


@dataclass(frozen=True)
class CheckLane:
    lane_id: str
    description: str
    triggers: CheckTriggers
    commands: tuple[tuple[str, ...], ...]
    escalates_to: str | None
    stop_on_failure: bool


@dataclass(frozen=True)
class CheckPolicy:
    schema_version: int
    template_id: str
    lanes: dict[str, CheckLane]


@dataclass(frozen=True)
class PlanItem:
    lane: CheckLane
    reason: str


@dataclass(frozen=True)
class CheckPlan:
    items: tuple[PlanItem, ...]


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    output: str


class CapturedOutput:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> None:
        self.parts.append(text)

    def text(self) -> str:
        return "".join(self.parts)


def load_effective_policy(root: Path) -> tuple[CheckPolicy, tuple[str, ...]]:
    generated = parse_policy(load_json(root / CHECKS_POLICY), generated=True)
    local_path = root / LOCAL_POLICY
    if not local_path.exists():
        return generated, ()
    try:
        local = parse_policy(load_json(local_path), generated=False, template_id=generated.template_id)
    except (SmartCheckError, OSError, json.JSONDecodeError) as error:
        return generated, (f"ignored invalid local check policy {LOCAL_POLICY}: {error}",)
    return merge_policy(generated, local), ()


def parse_policy(raw: dict[str, Any], generated: bool, template_id: str | None = None) -> CheckPolicy:
    schema_version = require_int(raw, "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise SmartCheckError(f"unsupported checks schema {schema_version}")
    policy_template_id = require_string(raw, "templateId") if generated else (optional_string(raw, "templateId") or template_id or "")
    raw_lanes = raw.get("lanes")
    if not isinstance(raw_lanes, list):
        raise SmartCheckError("lanes must be an array")
    lanes: dict[str, CheckLane] = {}
    for index, item in enumerate(raw_lanes):
        if not isinstance(item, dict):
            raise SmartCheckError(f"lanes[{index}] must be an object")
        lane_id = require_string(item, "id")
        if lane_id in lanes:
            raise SmartCheckError(f"duplicate lane id: {lane_id}")
        lanes[lane_id] = parse_lane(item, generated)
    if generated and "full" not in lanes:
        raise SmartCheckError("generated checks policy must define full lane")
    return CheckPolicy(schema_version=schema_version, template_id=policy_template_id, lanes=lanes)


def parse_lane(raw: dict[str, Any], generated: bool) -> CheckLane:
    triggers_raw = raw.get("triggers", {})
    if not isinstance(triggers_raw, dict):
        raise SmartCheckError("lane triggers must be an object")
    commands_raw = raw.get("commands", [] if not generated else None)
    if not isinstance(commands_raw, list):
        raise SmartCheckError("lane commands must be an array")
    return CheckLane(
        lane_id=require_string(raw, "id"),
        description=optional_string(raw, "description") or "",
        triggers=CheckTriggers(paths=tuple(require_string_list(triggers_raw, "paths", allow_missing=True))),
        commands=parse_commands(commands_raw),
        escalates_to=optional_nullable_string(raw, "escalatesTo"),
        stop_on_failure=optional_bool(raw, "stopOnFailure", True),
    )


def merge_policy(generated: CheckPolicy, local: CheckPolicy) -> CheckPolicy:
    lanes = dict(generated.lanes)
    for lane_id, override in local.lanes.items():
        base = lanes.get(lane_id)
        if base is None:
            lanes[lane_id] = override
            continue
        lanes[lane_id] = CheckLane(
            lane_id=lane_id,
            description=override.description or base.description,
            triggers=override.triggers if override.triggers.paths else base.triggers,
            commands=override.commands if override.commands else base.commands,
            escalates_to=override.escalates_to if override.escalates_to is not None else base.escalates_to,
            stop_on_failure=override.stop_on_failure,
        )
    return CheckPolicy(schema_version=generated.schema_version, template_id=generated.template_id, lanes=lanes)


def select_lanes(policy: CheckPolicy, changed_files: tuple[str, ...], force_full: bool) -> CheckPlan:
    if force_full:
        return CheckPlan((PlanItem(require_lane(policy, "full"), "forced full lane"),))
    if not changed_files:
        return CheckPlan((PlanItem(require_lane(policy, "full"), "no changed files; using full lane"),))
    selected: list[PlanItem] = []
    seen: set[str] = set()
    for lane in policy.lanes.values():
        if lane.lane_id == "full":
            continue
        reason = match_reason(lane, changed_files)
        if reason:
            add_lane(policy, lane.lane_id, reason, selected, seen)
            if lane.escalates_to:
                add_lane(policy, lane.escalates_to, f"escalated from {lane.lane_id}", selected, seen)
    if not selected:
        add_lane(policy, "full", "no lane matched changed files", selected, seen)
    return CheckPlan(tuple(selected))


def add_lane(policy: CheckPolicy, lane_id: str, reason: str, selected: list[PlanItem], seen: set[str]) -> None:
    if lane_id in seen:
        return
    selected.append(PlanItem(require_lane(policy, lane_id), reason))
    seen.add(lane_id)


def require_lane(policy: CheckPolicy, lane_id: str) -> CheckLane:
    try:
        return policy.lanes[lane_id]
    except KeyError as error:
        raise SmartCheckError(f"missing lane: {lane_id}") from error


def match_reason(lane: CheckLane, changed_files: tuple[str, ...]) -> str | None:
    for changed_file in changed_files:
        normalized = changed_file.replace("\\", "/")
        for pattern in lane.triggers.paths:
            if matches_path_pattern(normalized, pattern):
                return f"matched {normalized} with {pattern}"
    return None


def matches_path_pattern(path: str, pattern: str) -> bool:
    if fnmatch.fnmatch(path, pattern):
        return True
    if "/**/" in pattern:
        return fnmatch.fnmatch(path, pattern.replace("/**/", "/"))
    return False


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SmartCheckError(f"missing check policy {path}") from error
    if not isinstance(raw, dict):
        raise SmartCheckError("check policy must be an object")
    return raw


def require_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise SmartCheckError(f"{key} must be a non-empty string")
    return value


def optional_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key, "")
    if value == "":
        return ""
    if not isinstance(value, str):
        raise SmartCheckError(f"{key} must be a string")
    return value


def optional_nullable_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SmartCheckError(f"{key} must be a string or null")
    return value


def require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise SmartCheckError(f"{key} must be an integer")
    return value


def optional_bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise SmartCheckError(f"{key} must be a boolean")
    return value


def require_string_list(raw: dict[str, Any], key: str, allow_missing: bool = False) -> list[str]:
    value = raw.get(key)
    if value is None and allow_missing:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SmartCheckError(f"{key} must be an array of non-empty strings")
    return value


def parse_commands(raw: list[Any]) -> tuple[tuple[str, ...], ...]:
    commands: list[tuple[str, ...]] = []
    for index, command in enumerate(raw):
        if not isinstance(command, list) or not all(isinstance(item, str) and item for item in command):
            raise SmartCheckError(f"commands[{index}] must be an array of non-empty strings")
        commands.append(tuple(command))
    return tuple(commands)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run focused Codex Bootstrap verification lanes.")
    parser.add_argument("--since", default="")
    parser.add_argument("--changed", nargs="*", default=[])
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--full", action="store_true")
    return parser.parse_args(argv)


def run_cli(argv: list[str], cwd: Path | None = None, stdout=None, command_runner=None) -> int:
    args = parse_args(argv)
    root = (cwd or Path.cwd()).resolve()
    output = stdout or sys.stdout
    runner = command_runner or run_command
    try:
        policy, warnings = load_effective_policy(root)
        for warning in warnings:
            print(f"agent-smart-check: {warning}", file=sys.stderr)
        changed_files = tuple(args.changed) if args.changed else detect_changed_files(root, args.since)
        plan = select_lanes(policy, changed_files, force_full=args.full)
        results: list[CommandResult] = []
        exit_code = 0
        if not args.plan_only:
            for item in plan.items:
                for command in item.lane.commands:
                    result = runner(list(command), root)
                    results.append(result)
                    if result.output:
                        output.write(result.output)
                    if result.exit_code != 0:
                        exit_code = result.exit_code
                        if item.lane.stop_on_failure:
                            return print_result(plan, results, args.json, True, exit_code, output)
        return print_result(plan, results, args.json, not args.plan_only, exit_code, output)
    except SmartCheckError as error:
        print(f"agent-smart-check: {error}", file=sys.stderr)
        return 2


def detect_changed_files(root: Path, since: str) -> tuple[str, ...]:
    if since:
        result = subprocess.run(
            ["git", "diff", "--name-only", since, "--"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return tuple(line for line in result.stdout.splitlines() if line)
    status = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        return ()
    changed: list[str] = []
    for line in status.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path)
    return tuple(changed)


def run_command(command: list[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return CommandResult(command=tuple(command), exit_code=completed.returncode, output=completed.stdout)


def print_result(
    plan: CheckPlan,
    results: list[CommandResult],
    as_json: bool,
    executed: bool,
    exit_code: int,
    output,
) -> int:
    if as_json:
        output.write(json.dumps(result_payload(plan, results, executed, exit_code), indent=2, sort_keys=True) + "\n")
        return exit_code
    for item in plan.items:
        output.write(f"agent-smart-check: selected {item.lane.lane_id}\n")
        output.write(f"  reason: {item.reason}\n")
        output.write("  commands:\n")
        for command in item.lane.commands:
            output.write(f"    {' '.join(command)}\n")
    return exit_code


def result_payload(plan: CheckPlan, results: list[CommandResult], executed: bool, exit_code: int) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "executed": executed,
        "exitCode": exit_code,
        "plan": [
            {
                "id": item.lane.lane_id,
                "description": item.lane.description,
                "reason": item.reason,
                "commands": [list(command) for command in item.lane.commands],
            }
            for item in plan.items
        ],
        "results": [
            {"command": list(result.command), "exitCode": result.exit_code}
            for result in results
        ],
    }


def main() -> int:
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
