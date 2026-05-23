#!/usr/bin/env python3
"""Advisory nag hooks for Codex Bootstrap generated projects."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
NAGS_POLICY = Path(".codex-bootstrap/nags.json")
LOCAL_POLICY = Path(".codex-bootstrap/nags.local.json")
NAG_STATE = Path(".codex-bootstrap/nag-state.json")
SYNC_METADATA = Path(".codex-bootstrap/sync.json")
DEFAULT_TIMEOUT_SECONDS = 30


class NagError(Exception):
    """Raised for user-facing nag failures."""


@dataclass(frozen=True)
class NagDefinition:
    nag_id: str
    enabled: bool
    hook: str
    cadence: str
    action: str
    message: str
    commands: tuple[tuple[str, ...], ...]
    when: dict[str, Any]


@dataclass(frozen=True)
class NagPolicy:
    schema_version: int
    nags: dict[str, NagDefinition]


@dataclass(frozen=True)
class NagRuntimeState:
    last_shown_at: datetime | None
    last_checked_at: datetime | None
    last_seen_value: str | None
    snoozed_until: datetime | None
    acknowledged: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "lastShownAt": format_time(self.last_shown_at),
            "lastCheckedAt": format_time(self.last_checked_at),
            "lastSeenValue": self.last_seen_value,
            "snoozedUntil": format_time(self.snoozed_until),
            "acknowledged": self.acknowledged,
        }


@dataclass(frozen=True)
class NagState:
    schema_version: int
    nags: dict[str, NagRuntimeState]

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "nags": {
                nag_id: state.to_json()
                for nag_id, state in sorted(self.nags.items())
            },
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def load_effective_policy(root: Path) -> tuple[NagPolicy, tuple[str, ...]]:
    managed = parse_policy(load_json(root / NAGS_POLICY), managed=True)
    warnings: list[str] = []
    local_path = root / LOCAL_POLICY
    if not local_path.is_file():
        return managed, ()
    try:
        local = parse_policy(load_json(local_path), managed=False)
    except (NagError, OSError, json.JSONDecodeError) as error:
        warnings.append(f"ignored invalid local nag policy {LOCAL_POLICY}: {error}")
        return managed, tuple(warnings)
    return merge_policy(managed, local), tuple(warnings)


def parse_policy(raw: dict[str, Any], managed: bool) -> NagPolicy:
    schema_version = require_int(raw, "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise NagError(f"unsupported nag policy schema {schema_version}")
    raw_nags = raw.get("nags")
    if not isinstance(raw_nags, list):
        raise NagError("nags must be an array")
    nags: dict[str, NagDefinition] = {}
    for index, item in enumerate(raw_nags):
        if not isinstance(item, dict):
            raise NagError(f"nags[{index}] must be an object")
        nag_id = require_string(item, "id")
        if nag_id in nags:
            raise NagError(f"duplicate nag id: {nag_id}")
        if managed:
            nags[nag_id] = NagDefinition(
                nag_id=nag_id,
                enabled=require_bool(item, "enabled"),
                hook=require_string(item, "hook"),
                cadence=require_string(item, "cadence"),
                action=require_string(item, "action"),
                message=require_string(item, "message"),
                commands=parse_commands(item.get("commands", [])),
                when=parse_when(item.get("when", {})),
            )
        else:
            nags[nag_id] = NagDefinition(
                nag_id=nag_id,
                enabled=optional_bool(item, "enabled", True),
                hook=optional_string(item, "hook", ""),
                cadence=optional_string(item, "cadence", ""),
                action=optional_string(item, "action", ""),
                message=optional_string(item, "message", ""),
                commands=parse_commands(item.get("commands", [])),
                when=parse_when(item.get("when", {})),
            )
    return NagPolicy(schema_version=schema_version, nags=nags)


def merge_policy(managed: NagPolicy, local: NagPolicy) -> NagPolicy:
    result = dict(managed.nags)
    for nag_id, override in local.nags.items():
        base = result.get(nag_id)
        if base is None:
            result[nag_id] = override
            continue
        result[nag_id] = NagDefinition(
            nag_id=nag_id,
            enabled=override.enabled,
            hook=override.hook or base.hook,
            cadence=override.cadence or base.cadence,
            action=override.action or base.action,
            message=override.message or base.message,
            commands=override.commands or base.commands,
            when=override.when or base.when,
        )
    return NagPolicy(schema_version=managed.schema_version, nags=result)


def load_state(root: Path) -> NagState:
    path = root / NAG_STATE
    if not path.is_file():
        return NagState(schema_version=SCHEMA_VERSION, nags={})
    try:
        raw = load_json(path)
        if require_int(raw, "schemaVersion") != SCHEMA_VERSION:
            raise NagError("unsupported nag state schema")
        raw_nags = raw.get("nags")
        if not isinstance(raw_nags, dict):
            raise NagError("state nags must be an object")
        return NagState(
            schema_version=SCHEMA_VERSION,
            nags={
                nag_id: NagRuntimeState(
                    last_shown_at=parse_time(optional_nullable_string(value, "lastShownAt")),
                    last_checked_at=parse_time(optional_nullable_string(value, "lastCheckedAt")),
                    last_seen_value=optional_nullable_string(value, "lastSeenValue"),
                    snoozed_until=parse_time(optional_nullable_string(value, "snoozedUntil")),
                    acknowledged=optional_bool(value, "acknowledged", False),
                )
                for nag_id, value in raw_nags.items()
                if isinstance(nag_id, str) and isinstance(value, dict)
            },
        )
    except (NagError, OSError, json.JSONDecodeError):
        corrupt = path.with_name(f"{path.name}.corrupt-{int(utc_now().timestamp())}")
        shutil.move(str(path), corrupt)
        print(f"agent-nag: moved corrupt nag state to {corrupt}", file=sys.stderr)
        return NagState(schema_version=SCHEMA_VERSION, nags={})


def should_show(definition: NagDefinition, state: NagState, now: datetime) -> bool:
    if not definition.enabled:
        return False
    runtime = state.nags.get(definition.nag_id)
    if runtime is None:
        return True
    if runtime.snoozed_until is not None and runtime.snoozed_until > now:
        return False
    if definition.cadence == "per-run":
        return True
    if definition.cadence == "once":
        return not runtime.acknowledged
    duration = parse_duration(definition.cadence)
    if runtime.last_shown_at is None:
        return True
    return runtime.last_shown_at + duration <= now


def parse_duration(value: str) -> timedelta:
    if value.endswith("h"):
        return timedelta(hours=int(value[:-1]))
    if value.endswith("d"):
        return timedelta(days=int(value[:-1]))
    if value.endswith("m"):
        return timedelta(minutes=int(value[:-1]))
    if value.endswith("s"):
        return timedelta(seconds=int(value[:-1]))
    raise NagError(f"invalid duration: {value}")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise NagError(f"{key} must be a non-empty string")
    return value


def optional_string(raw: dict[str, Any], key: str, default: str) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise NagError(f"{key} must be a string")
    return value


def optional_nullable_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None or isinstance(value, str):
        return value
    raise NagError(f"{key} must be a string or null")


def require_bool(raw: dict[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise NagError(f"{key} must be a boolean")
    return value


def optional_bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise NagError(f"{key} must be a boolean")
    return value


def require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise NagError(f"{key} must be an integer")
    return value


def parse_commands(value: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list):
        raise NagError("commands must be an array")
    commands: list[tuple[str, ...]] = []
    for index, item in enumerate(value):
        if not isinstance(item, list) or not all(isinstance(part, str) and part for part in item):
            raise NagError(f"commands[{index}] must be a non-empty string array")
        commands.append(tuple(item))
    return tuple(commands)


def parse_when(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NagError("when must be an object")
    allowed = {"exitCode", "wrapper", "command"}
    for key in value:
        if key not in allowed:
            raise NagError(f"unsupported when key: {key}")
    return dict(value)


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


def run_cli(
    argv: list[str],
    stdout=None,
    now: datetime | None = None,
    command_runner=None,
) -> int:
    args = parse_args(argv)
    output = stdout or sys.stdout
    current_time = now or utc_now()
    runner = command_runner or run_unchecked
    root = args.project_root.resolve()
    try:
        if args.command == "run-hook":
            return run_hook_command(root, args, output, current_time, runner)
        if args.command == "check-updates":
            return check_updates_command(root, args.quiet, args.verbose, output, current_time, runner)
        if args.command == "ack":
            state = set_acknowledged(load_state(root), args.nag_id, True)
            write_state(root, state)
            return 0
        if args.command == "snooze":
            state = set_snooze(load_state(root), args.nag_id, current_time + parse_duration(args.duration))
            write_state(root, state)
            return 0
        if args.command == "reset":
            state = clear_runtime_state(load_state(root), args.nag_id)
            write_state(root, state)
            return 0
        if args.command == "list":
            policy, warnings = load_effective_policy(root)
            print_warnings(warnings)
            for nag_id in sorted(policy.nags):
                output.write(f"{nag_id}\n")
            return 0
        if args.command == "status":
            policy, warnings = load_effective_policy(root)
            print_warnings(warnings)
            state = load_state(root)
            output.write(json.dumps(status_payload(policy, state), indent=2, sort_keys=True) + "\n")
            return 0
    except NagError as error:
        print(f"agent-nag: {error}", file=sys.stderr)
        return 2
    return 2


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex Bootstrap agent nags.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    hook = subparsers.add_parser("run-hook")
    hook.add_argument("hook")
    hook.add_argument("--wrapper", default="")
    hook.add_argument("--command", dest="child_command", default="")
    hook.add_argument("--exit-code", type=int)

    updates = subparsers.add_parser("check-updates")
    updates.add_argument("--quiet", action="store_true")
    updates.add_argument("--verbose", action="store_true")

    subparsers.add_parser("list")
    subparsers.add_parser("status")

    ack = subparsers.add_parser("ack")
    ack.add_argument("nag_id")

    snooze = subparsers.add_parser("snooze")
    snooze.add_argument("nag_id")
    snooze.add_argument("--for", dest="duration", required=True)

    reset = subparsers.add_parser("reset")
    reset.add_argument("nag_id")

    return parser.parse_args(argv)


def run_hook_command(root: Path, args: argparse.Namespace, output, now: datetime, command_runner) -> int:
    policy, warnings = load_effective_policy(root)
    print_warnings(warnings)
    state = load_state(root)
    context = hook_context(root, args)
    should_write_state = False
    for definition in sorted(policy.nags.values(), key=lambda item: item.nag_id):
        if definition.hook != args.hook or not matches_when(definition, context):
            continue
        if definition.action == "check-bootstrap-update":
            _shown, updated_state = evaluate_bootstrap_update(
                root,
                definition,
                state,
                now,
                output,
                command_runner,
                quiet=True,
                verbose=False,
            )
            should_write_state = should_write_state or updated_state != state
            state = updated_state
            continue
        if should_show(definition, state, now):
            print_nag(definition, output)
            state = mark_shown(state, definition.nag_id, now)
            should_write_state = True
    if should_write_state:
        write_state(root, state)
    return 0


def matches_when(definition: NagDefinition, context: dict[str, Any]) -> bool:
    for key, expected in definition.when.items():
        if context.get(key) != expected:
            return False
    return True


def hook_context(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    context: dict[str, Any] = {
        "wrapper": getattr(args, "wrapper", ""),
        "command": getattr(args, "child_command", ""),
    }
    exit_code = getattr(args, "exit_code", None)
    if exit_code is not None:
        context["exitCode"] = exit_code
    context.update(read_sync_metadata(root))
    return context


def print_nag(definition: NagDefinition, output) -> None:
    output.write(f"agent-nag: {definition.nag_id}\n")
    output.write(f"  {definition.message}\n")
    if definition.commands:
        output.write("  Suggested:\n")
        for command in definition.commands:
            output.write(f"    {' '.join(command)}\n")


def mark_shown(state: NagState, nag_id: str, now: datetime) -> NagState:
    current = state.nags.get(nag_id, empty_runtime_state())
    updated = dataclasses.replace(current, last_shown_at=now)
    return replace_runtime_state(state, nag_id, updated)


def set_acknowledged(state: NagState, nag_id: str, acknowledged: bool) -> NagState:
    current = state.nags.get(nag_id, empty_runtime_state())
    return replace_runtime_state(state, nag_id, dataclasses.replace(current, acknowledged=acknowledged))


def set_snooze(state: NagState, nag_id: str, snoozed_until: datetime) -> NagState:
    current = state.nags.get(nag_id, empty_runtime_state())
    return replace_runtime_state(state, nag_id, dataclasses.replace(current, snoozed_until=snoozed_until))


def clear_runtime_state(state: NagState, nag_id: str) -> NagState:
    nags = dict(state.nags)
    nags.pop(nag_id, None)
    return NagState(schema_version=state.schema_version, nags=nags)


def replace_runtime_state(state: NagState, nag_id: str, runtime: NagRuntimeState) -> NagState:
    nags = dict(state.nags)
    nags[nag_id] = runtime
    return NagState(schema_version=state.schema_version, nags=nags)


def empty_runtime_state() -> NagRuntimeState:
    return NagRuntimeState(
        last_shown_at=None,
        last_checked_at=None,
        last_seen_value=None,
        snoozed_until=None,
        acknowledged=False,
    )


def write_state(root: Path, state: NagState) -> None:
    destination = root / NAG_STATE
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as temp_file:
        json.dump(state.to_json(), temp_file, indent=2, sort_keys=True)
        temp_file.write("\n")
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_name = temp_file.name
    os.replace(temp_name, destination)


def check_updates_command(root: Path, quiet: bool, verbose: bool, output, now: datetime, command_runner) -> int:
    try:
        policy, warnings = load_effective_policy(root)
        print_warnings(warnings)
        state = load_state(root)
        definition = policy.nags.get("bootstrap-update-check")
        if definition is None:
            definition = NagDefinition(
                nag_id="bootstrap-update-check",
                enabled=True,
                hook="session-start",
                cadence="per-run",
                action="check-bootstrap-update",
                message="A newer Codex Bootstrap version is available.",
                commands=(),
                when={},
            )
        _shown, state = evaluate_bootstrap_update(
            root,
            definition,
            state,
            now,
            output,
            command_runner,
            quiet=quiet,
            verbose=verbose,
        )
        write_state(root, state)
        return 0
    except NagError as error:
        if verbose:
            print(f"agent-nag: update check failed: {error}", file=sys.stderr)
            return 1
        state = mark_checked(load_state(root), "bootstrap-update-check", now, f"error:{error}")
        write_state(root, state)
        return 0


def evaluate_bootstrap_update(
    root: Path,
    definition: NagDefinition,
    state: NagState,
    now: datetime,
    output,
    command_runner,
    quiet: bool,
    verbose: bool,
) -> tuple[bool, NagState]:
    if not should_show(definition, state, now):
        return False, state
    sync = read_required_sync_metadata(root)
    result = command_runner(["git", "ls-remote", sync["sourceRepository"], sync["sourceRef"]], cwd=root)
    if result.returncode != 0:
        raise NagError(result.stdout.strip() or "git ls-remote failed")
    latest = parse_ls_remote_commit(result.stdout)
    current = sync["sourceCommit"]
    checked_state = mark_checked(state, definition.nag_id, now, latest)
    if latest == current:
        if verbose and not quiet:
            output.write("agent-nag: bootstrap-update-check\n  Codex Bootstrap is current.\n")
        return False, checked_state
    output.write(f"agent-nag: {definition.nag_id}\n")
    output.write(f"  {definition.message}\n")
    output.write(f"  current: {current}\n")
    output.write(f"  latest:  {latest}\n")
    output.write("  Suggested:\n")
    output.write("    ./scripts/agent-bootstrap sync --dry-run\n")
    output.write("    ./scripts/agent-bootstrap sync --apply\n")
    return True, mark_shown(checked_state, definition.nag_id, now)


def mark_checked(state: NagState, nag_id: str, now: datetime, value: str) -> NagState:
    current = state.nags.get(nag_id, empty_runtime_state())
    return replace_runtime_state(
        state,
        nag_id,
        dataclasses.replace(current, last_checked_at=now, last_seen_value=value),
    )


def read_sync_metadata(root: Path) -> dict[str, str]:
    path = root / SYNC_METADATA
    if not path.is_file():
        return {}
    try:
        return read_required_sync_metadata(root)
    except (NagError, OSError, json.JSONDecodeError):
        return {}


def read_required_sync_metadata(root: Path) -> dict[str, str]:
    raw = load_json(root / SYNC_METADATA)
    source = raw.get("source")
    template = raw.get("template")
    if not isinstance(source, dict) or not isinstance(template, dict):
        raise NagError("sync metadata is missing source or template")
    return {
        "sourceRepository": require_string(source, "repository"),
        "sourceRef": require_string(source, "ref"),
        "sourceCommit": require_string(source, "commit"),
        "templateId": require_string(template, "id"),
    }


def parse_ls_remote_commit(output: str) -> str:
    for line in output.splitlines():
        commit, separator, _ref = line.partition("\t")
        if separator and len(commit) == 40:
            return commit
    raise NagError("git ls-remote did not return a commit")


def run_unchecked(command: list[str], cwd: Path | None = None) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout)


def status_payload(policy: NagPolicy, state: NagState) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "nags": {
            nag_id: {
                "enabled": definition.enabled,
                "hook": definition.hook,
                "cadence": definition.cadence,
                "state": state.nags.get(nag_id, empty_runtime_state()).to_json(),
            }
            for nag_id, definition in sorted(policy.nags.items())
        },
    }


def print_warnings(warnings: tuple[str, ...]) -> None:
    for warning in warnings:
        print(f"agent-nag: {warning}", file=sys.stderr)


def main() -> int:
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
