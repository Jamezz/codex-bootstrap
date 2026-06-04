#!/usr/bin/env python3
"""Focused verification lane selection for Codex Bootstrap generated projects."""

from __future__ import annotations

import argparse
import fnmatch
import json
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import hygiene


CHECKS_POLICY = Path(".codex-bootstrap/checks.json")
LOCAL_POLICY = Path(".codex-bootstrap/checks.local.json")
SCHEMA_VERSION = 1
HYGIENE_REVIEW_EXIT_CODE = hygiene.REVIEW_NEEDED_EXIT_CODE


class SmartCheckError(Exception):
    pass


@dataclass(frozen=True)
class CheckTriggers:
    paths: tuple[str, ...]


@dataclass(frozen=True)
class CheckCommand:
    argv: tuple[str, ...]
    timeout_seconds: float | None


@dataclass(frozen=True)
class CheckLane:
    lane_id: str
    description: str
    triggers: CheckTriggers
    commands: tuple[CheckCommand, ...]
    escalates_to: str | None
    stop_on_failure: bool
    cost: str = "standard"
    tags: tuple[str, ...] = ()
    requires: tuple[str, ...] = ()
    timeout_seconds: float | None = None


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


class CommandProgress:
    def __init__(
        self,
        lane_id: str,
        command_index: int,
        command_count: int,
        command: tuple[str, ...],
        stream,
        clock: Callable[[], float] = time.monotonic,
        heartbeat_interval_seconds: float = 30.0,
    ) -> None:
        self.lane_id = lane_id
        self.command_index = command_index
        self.command_count = command_count
        self.command = command
        self.stream = stream
        self.clock = clock
        self.heartbeat_interval_seconds = heartbeat_interval_seconds if heartbeat_interval_seconds > 0 else 30.0
        self.started_at = 0.0
        self.next_heartbeat_at = 0.0
        self.started = False

    def start(self) -> None:
        self.started_at = self.clock()
        self.next_heartbeat_at = self.started_at + self.heartbeat_interval_seconds
        self.started = True
        self.stream.write(f"agent-smart-check: running {self.command_label()}: {format_command(self.command)}\n")

    def maybe_emit_heartbeat(self) -> None:
        if not self.started:
            self.start()
        now = self.clock()
        if now < self.next_heartbeat_at:
            return
        elapsed = format_duration(now - self.started_at)
        self.stream.write(f"agent-smart-check: still running after {elapsed}: {self.command_label()}: {format_command(self.command)}\n")
        while self.next_heartbeat_at <= now:
            self.next_heartbeat_at += self.heartbeat_interval_seconds

    def finish(self, exit_code: int) -> None:
        if not self.started:
            self.start()
        elapsed = format_duration(self.clock() - self.started_at)
        self.stream.write(f"agent-smart-check: finished {self.command_label()} after {elapsed} with exit code {exit_code}\n")

    def command_label(self) -> str:
        return f"{self.lane_id} command {self.command_index}/{self.command_count}"


def load_effective_policy(root: Path) -> tuple[CheckPolicy, tuple[str, ...]]:
    generated_raw = load_json(root / CHECKS_POLICY)
    try:
        generated = parse_policy(generated_raw, generated=True)
    except SmartCheckError as error:
        generated = parse_generated_full_lane_policy(generated_raw, error)
        return generated, (f"invalid generated check policy {CHECKS_POLICY}: {error}; using full lane",)
    local_path = root / LOCAL_POLICY
    if not local_path.exists():
        return generated, ()
    try:
        local = parse_policy(load_json(local_path), generated=False, template_id=generated.template_id)
    except (SmartCheckError, OSError, json.JSONDecodeError) as error:
        return generated, (f"ignored invalid local check policy {LOCAL_POLICY}: {error}",)
    return merge_policy(generated, local), ()


def parse_generated_full_lane_policy(raw: dict[str, Any], original_error: SmartCheckError) -> CheckPolicy:
    raw_lanes = raw.get("lanes")
    if not isinstance(raw_lanes, list):
        raise original_error
    for item in raw_lanes:
        if not isinstance(item, dict) or item.get("id") != "full":
            continue
        try:
            full_lane = parse_lane(item, generated=True)
        except SmartCheckError:
            raise original_error
        template_id = raw.get("templateId", "")
        return CheckPolicy(
            schema_version=SCHEMA_VERSION,
            template_id=template_id if isinstance(template_id, str) else "",
            lanes={"full": full_lane},
        )
    raise original_error


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
        cost=optional_string(raw, "cost") or "standard",
        tags=tuple(require_string_list(raw, "tags", allow_missing=True)),
        requires=tuple(require_string_list(raw, "requires", allow_missing=True)),
        timeout_seconds=optional_positive_number(raw, "timeoutSeconds"),
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
            cost=override.cost if override.cost != "standard" or base.cost == "standard" else base.cost,
            tags=override.tags if override.tags else base.tags,
            requires=override.requires if override.requires else base.requires,
            timeout_seconds=override.timeout_seconds if override.timeout_seconds is not None else base.timeout_seconds,
        )
    return CheckPolicy(schema_version=generated.schema_version, template_id=generated.template_id, lanes=lanes)


def select_lanes(
    policy: CheckPolicy,
    changed_files: tuple[str, ...],
    force_full: bool,
    fast_only: bool = False,
    tags: tuple[str, ...] = (),
) -> CheckPlan:
    if force_full:
        return CheckPlan((PlanItem(require_lane(policy, "full"), "forced full lane"),))
    if not changed_files:
        full_lane = require_lane(policy, "full")
        if fast_only and full_lane.cost != "fast":
            return CheckPlan(())
        return CheckPlan((PlanItem(full_lane, "no changed files; using full lane"),))
    selected: list[PlanItem] = []
    seen: set[str] = set()
    for lane in policy.lanes.values():
        if lane.lane_id == "full":
            continue
        if fast_only and lane.cost != "fast":
            continue
        if tags and not set(tags).intersection(lane.tags):
            continue
        reason = match_reason(lane, changed_files)
        if reason:
            add_lane(policy, lane.lane_id, reason, selected, seen)
            if lane.escalates_to:
                escalated_lane = require_lane(policy, lane.escalates_to)
                if not fast_only or escalated_lane.cost == "fast":
                    add_lane(policy, lane.escalates_to, f"escalated from {lane.lane_id}", selected, seen)
    if not selected:
        full_lane = require_lane(policy, "full")
        if fast_only and full_lane.cost != "fast":
            return CheckPlan(())
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


def optional_positive_number(raw: dict[str, Any], key: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise SmartCheckError(f"{key} must be a positive number")
    return float(value)


def parse_commands(raw: list[Any]) -> tuple[CheckCommand, ...]:
    commands: list[CheckCommand] = []
    for index, command in enumerate(raw):
        if isinstance(command, list):
            commands.append(CheckCommand(argv=parse_argv(command, f"commands[{index}]"), timeout_seconds=None))
            continue
        if isinstance(command, dict):
            raw_argv = command.get("argv")
            if not isinstance(raw_argv, list):
                raise SmartCheckError(f"commands[{index}].argv must be an array of non-empty strings")
            commands.append(
                CheckCommand(
                    argv=parse_argv(raw_argv, f"commands[{index}].argv"),
                    timeout_seconds=optional_positive_number(command, "timeoutSeconds"),
                )
            )
            continue
        raise SmartCheckError(f"commands[{index}] must be an array or object")
    return tuple(commands)


def parse_argv(raw: list[Any], label: str) -> tuple[str, ...]:
    if not raw or not all(isinstance(item, str) and item for item in raw):
        raise SmartCheckError(f"{label} must be an array of non-empty strings")
    return tuple(raw)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run focused Codex Bootstrap verification lanes.")
    parser.add_argument("--since", default="")
    parser.add_argument("--changed", nargs="*", default=[])
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--fast-only", action="store_true")
    parser.add_argument("--tag", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--no-hygiene", action="store_true")
    parser.add_argument("--hygiene-only", action="store_true")
    return parser.parse_args(argv)


def run_cli(
    argv: list[str],
    cwd: Path | None = None,
    stdout=None,
    command_runner=None,
    progress_clock: Callable[[], float] = time.monotonic,
    heartbeat_interval_seconds: float = 30.0,
) -> int:
    args = parse_args(argv)
    root = (cwd or Path.cwd()).resolve()
    output = stdout or sys.stdout
    runner = command_runner or run_command
    try:
        policy, warnings = load_effective_policy(root)
        for warning in warnings:
            print(f"agent-smart-check: {warning}", file=sys.stderr)
        if args.self_test:
            return print_self_test(policy, args.json, output, warnings)
        changed_files = tuple(args.changed) if args.changed else detect_changed_files(root, args.since)
        hygiene_result = disabled_hygiene_result()
        if not args.no_hygiene:
            hygiene_config = hygiene.HygieneConfig()
            planned_hygiene = hygiene.plan_hygiene(
                root,
                changed_files,
                detect_git_status(root),
                hygiene_config,
            )
            hygiene_result = hygiene.apply_hygiene_actions(
                root,
                planned_hygiene,
                hygiene_config,
                dry_run=args.plan_only,
            )
            if not args.plan_only and hygiene_result.actions and not hygiene_result.review_needed and not args.changed:
                changed_files = detect_changed_files(root, args.since)
        if args.hygiene_only:
            return print_hygiene_only_result(hygiene_result, args.json, output, dry_run=args.plan_only)
        if hygiene_result.review_needed and not args.plan_only:
            if args.json:
                output.write(
                    json.dumps(
                        {
                            "schemaVersion": SCHEMA_VERSION,
                            "executed": False,
                            "exitCode": HYGIENE_REVIEW_EXIT_CODE,
                            "warnings": list(warnings),
                            "hygiene": hygiene_payload(hygiene_result),
                            "plan": [],
                            "results": [],
                        },
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                )
            else:
                print_hygiene_human(hygiene_result, output, dry_run=False)
                output.write("agent-smart-check: hygiene needs review; verification skipped\n")
            return HYGIENE_REVIEW_EXIT_CODE
        plan = select_lanes(
            policy,
            changed_files,
            force_full=args.full,
            fast_only=args.fast_only,
            tags=tuple(args.tag),
        )
        results: list[CommandResult] = []
        exit_code = 0
        if not args.plan_only:
            progress_output = sys.stderr if args.json else output
            print_execution_progress(plan, progress_output)
            for item in plan.items:
                missing = missing_requirements(item.lane)
                if missing:
                    result = CommandResult(
                        command=("requires", missing[0]),
                        exit_code=127,
                        output=f"agent-smart-check: missing required tool for {item.lane.lane_id}: {missing[0]}\n",
                    )
                    results.append(result)
                    output.write(result.output)
                    return print_result(plan, results, args.json, True, result.exit_code, output, warnings, hygiene_result)
                for command_index, command in enumerate(item.lane.commands, start=1):
                    timeout_seconds = args.timeout or command.timeout_seconds or item.lane.timeout_seconds
                    progress = CommandProgress(
                        lane_id=item.lane.lane_id,
                        command_index=command_index,
                        command_count=len(item.lane.commands),
                        command=command.argv,
                        stream=progress_output,
                        clock=progress_clock,
                        heartbeat_interval_seconds=heartbeat_interval_seconds,
                    )
                    progress.start()
                    result = run_command_runner(runner, list(command.argv), root, timeout_seconds, progress)
                    progress.finish(result.exit_code)
                    results.append(result)
                    if result.output:
                        output.write(result.output)
                    if result.exit_code != 0:
                        exit_code = result.exit_code
                        if item.lane.stop_on_failure:
                            return print_result(plan, results, args.json, True, exit_code, output, warnings, hygiene_result)
        return print_result(plan, results, args.json, not args.plan_only, exit_code, output, warnings, hygiene_result)
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
        changed.append(normalize_git_status_path(path))
    return tuple(changed)


def detect_git_status(root: Path) -> dict[str, str]:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        return {}
    entries: dict[str, str] = {}
    for line in status.stdout.splitlines():
        if not line:
            continue
        code = line[:2]
        path = line[3:]
        entries[normalize_git_status_path(path).replace("\\", "/")] = code
    return entries


def normalize_git_status_path(path: str) -> str:
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    if path.startswith('"'):
        parts = shlex.split(path)
        if len(parts) == 1:
            return parts[0]
    return path


def run_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: float | None = None,
    progress: CommandProgress | None = None,
) -> CommandResult:
    started_at = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    while True:
        remaining = remaining_timeout_seconds(started_at, timeout_seconds)
        if remaining is not None and remaining <= 0:
            process.kill()
            output, _ = process.communicate()
            output = output or ""
            output += f"agent-smart-check: command timed out after {timeout_seconds:g}s: {format_command(tuple(command))}\n"
            return CommandResult(command=tuple(command), exit_code=124, output=output)
        try:
            output, _ = process.communicate(timeout=poll_interval_seconds(remaining))
            return CommandResult(command=tuple(command), exit_code=process.returncode, output=output or "")
        except subprocess.TimeoutExpired:
            if progress is not None:
                progress.maybe_emit_heartbeat()


def run_command_runner(
    runner,
    command: list[str],
    cwd: Path,
    timeout_seconds: float | None,
    progress: CommandProgress,
) -> CommandResult:
    try:
        return runner(command, cwd, timeout_seconds=timeout_seconds, progress=progress)
    except TypeError:
        try:
            return runner(command, cwd, timeout_seconds=timeout_seconds)
        except TypeError:
            return runner(command, cwd)


def remaining_timeout_seconds(started_at: float, timeout_seconds: float | None) -> float | None:
    if timeout_seconds is None:
        return None
    return timeout_seconds - (time.monotonic() - started_at)


def poll_interval_seconds(remaining: float | None) -> float:
    interval = 0.25
    if remaining is None:
        return interval
    return max(0.01, min(interval, remaining))


def missing_requirements(lane: CheckLane) -> tuple[str, ...]:
    return tuple(requirement for requirement in lane.requires if shutil.which(requirement) is None)


def print_execution_progress(plan: CheckPlan, output) -> None:
    command_count = sum(len(item.lane.commands) for item in plan.items)
    output.write(
        "agent-smart-check: file scan complete; "
        f"selected {plural(len(plan.items), 'lane')} and {plural(command_count, 'command')}\n"
    )


def plural(count: int, singular: str) -> str:
    suffix = "" if count == 1 else "s"
    return f"{count} {singular}{suffix}"


def format_command(command: tuple[str, ...]) -> str:
    return " ".join(command)


def format_duration(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, seconds = divmod(total_seconds, 60)
    if minutes:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def print_self_test(policy: CheckPolicy, as_json: bool, output, warnings: tuple[str, ...]) -> int:
    errors = self_test_errors(policy)
    if as_json:
        output.write(
            json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "ok": not errors,
                    "errors": errors,
                    "warnings": list(warnings),
                    "lanes": [
                        {
                            "id": lane.lane_id,
                            "cost": lane.cost,
                            "tags": list(lane.tags),
                            "requires": list(lane.requires),
                            "commandCount": len(lane.commands),
                        }
                        for lane in policy.lanes.values()
                    ],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return 0 if not errors else 2
    if errors:
        output.write("agent-smart-check: self-test failed\n")
        for error in errors:
            output.write(f"  {error}\n")
        return 2
    output.write("agent-smart-check: self-test passed\n")
    return 0


def self_test_errors(policy: CheckPolicy) -> list[str]:
    errors: list[str] = []
    if "full" not in policy.lanes:
        errors.append("missing required full lane")
    for lane in policy.lanes.values():
        if not lane.commands:
            errors.append(f"lane {lane.lane_id} has no commands")
        if lane.escalates_to and lane.escalates_to not in policy.lanes:
            errors.append(f"lane {lane.lane_id} references unknown escalatesTo target {lane.escalates_to}")
        for index, command in enumerate(lane.commands):
            if not command.argv:
                errors.append(f"lane {lane.lane_id} command {index} has empty argv")
    return errors


def disabled_hygiene_result() -> hygiene.HygieneResult:
    return hygiene.HygieneResult(enabled=False, review_needed=False, actions=())


def print_hygiene_only_result(result: hygiene.HygieneResult, as_json: bool, output, dry_run: bool) -> int:
    if as_json:
        output.write(
            json.dumps(
                {
                    "schemaVersion": SCHEMA_VERSION,
                    "hygiene": hygiene_payload(result),
                },
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
    else:
        print_hygiene_human(result, output, dry_run=dry_run)
    return HYGIENE_REVIEW_EXIT_CODE if result.review_needed else 0


def print_hygiene_human(result: hygiene.HygieneResult, output, dry_run: bool) -> None:
    if not result.enabled:
        return
    prefix = "would " if dry_run else ""
    for action in result.actions:
        if action.action == "trash":
            output.write(f"agent-smart-check: hygiene {prefix}trash exact duplicate {action.duplicate_path}\n")
        elif action.action == "quarantine":
            output.write(f"agent-smart-check: hygiene {prefix}quarantine duplicate {action.duplicate_path}\n")
            if action.original_path:
                output.write(f"  original: {action.original_path}\n")
            if action.destination_path:
                output.write(f"  destination: {action.destination_path}\n")
            if action.manifest_path:
                output.write(f"  review: {action.manifest_path}\n")
        elif action.action == "report":
            output.write(f"agent-smart-check: hygiene needs review for {action.duplicate_path}: {action.reason}\n")


def hygiene_payload(result: hygiene.HygieneResult) -> dict[str, Any]:
    return {
        "enabled": result.enabled,
        "reviewNeeded": result.review_needed,
        "actions": [
            {
                "action": action.action,
                "reason": action.reason,
                "duplicatePath": action.duplicate_path,
                "originalPath": action.original_path,
                "destinationPath": action.destination_path,
                "manifestPath": action.manifest_path,
                "reviewNeeded": action.review_needed,
            }
            for action in result.actions
        ],
    }


def print_result(
    plan: CheckPlan,
    results: list[CommandResult],
    as_json: bool,
    executed: bool,
    exit_code: int,
    output,
    warnings: tuple[str, ...] = (),
    hygiene_result: hygiene.HygieneResult | None = None,
) -> int:
    if as_json:
        output.write(
            json.dumps(
                result_payload(plan, results, executed, exit_code, warnings, hygiene_result),
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )
        return exit_code
    if hygiene_result is not None:
        print_hygiene_human(hygiene_result, output, dry_run=not executed)
    for item in plan.items:
        output.write(f"agent-smart-check: selected {item.lane.lane_id}\n")
        output.write(f"  reason: {item.reason}\n")
        output.write("  commands:\n")
        for command in item.lane.commands:
            effective_timeout = command.timeout_seconds or item.lane.timeout_seconds
            suffix = f" (timeout {effective_timeout:g}s)" if effective_timeout else ""
            output.write(f"    {' '.join(command.argv)}{suffix}\n")
    return exit_code


def result_payload(
    plan: CheckPlan,
    results: list[CommandResult],
    executed: bool,
    exit_code: int,
    warnings: tuple[str, ...] = (),
    hygiene_result: hygiene.HygieneResult | None = None,
) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "executed": executed,
        "exitCode": exit_code,
        "warnings": list(warnings),
        "hygiene": hygiene_payload(hygiene_result or disabled_hygiene_result()),
        "plan": [
            {
                "id": item.lane.lane_id,
                "description": item.lane.description,
                "reason": item.reason,
                "cost": item.lane.cost,
                "tags": list(item.lane.tags),
                "requires": list(item.lane.requires),
                "timeoutSeconds": item.lane.timeout_seconds,
                "commands": [list(command.argv) for command in item.lane.commands],
                "commandDetails": [
                    {
                        "argv": list(command.argv),
                        "timeoutSeconds": command.timeout_seconds or item.lane.timeout_seconds,
                    }
                    for command in item.lane.commands
                ],
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
