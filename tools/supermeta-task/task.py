#!/usr/bin/env python3
"""Shared stuck-task diagnostics for generated projects."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


DEFAULT_PROCESS_MATCHES = (
    "gradle",
    "gradlew",
    "maven",
    "mvn",
    "npm",
    "pnpm",
    "yarn",
    "node",
    "pytest",
    "tox",
    "supermeta",
)


def main() -> int:
    args = parse_args()
    if args.command == "ps":
        patterns = args.match or list(DEFAULT_PROCESS_MATCHES)
        return print_matching_processes(patterns, "matching task processes", unavailable_success=True)
    if args.command == "logs":
        return print_recent_logs(args.path, args.limit, args.glob)
    if args.command == "kill":
        if not args.match:
            print("agent-task: kill requires at least one --match pattern", file=sys.stderr)
            return 2
        return kill_matching_processes(args.match, "matching task processes")
    print(f"agent-task: unknown command: {args.command}", file=sys.stderr)
    return 2


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect and recover stuck build or task runs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ps_parser = subparsers.add_parser("ps", help="List matching build/task processes.")
    ps_parser.add_argument(
        "--match",
        action="append",
        default=[],
        help="Case-insensitive command substring to match. Can be repeated.",
    )

    logs_parser = subparsers.add_parser("logs", help="List recent log files in a directory.")
    logs_parser.add_argument("path", type=Path, help="Directory containing task log files.")
    logs_parser.add_argument("--limit", type=int, default=10, help="Maximum number of logs to list.")
    logs_parser.add_argument("--glob", default="*.log", help="File glob to list. Defaults to *.log.")

    kill_parser = subparsers.add_parser("kill", help="Send SIGTERM to matching build/task processes.")
    kill_parser.add_argument(
        "--match",
        action="append",
        default=[],
        help="Case-insensitive command substring to match. Can be repeated.",
    )

    return parser.parse_args()


def print_matching_processes(
    patterns: list[str] | tuple[str, ...],
    label: str,
    unavailable_success: bool,
) -> int:
    try:
        processes = list_matching_processes(patterns)
    except ProcessListingError as error:
        print(f"agent-task: process listing unavailable: {error}")
        return 0 if unavailable_success else 1

    if not processes:
        print(f"agent-task: no {label} found")
        return 0

    print(f"agent-task: {label}")
    for process in processes:
        print(f"{process.pid:>8} {process.command}")
    return 0


def print_recent_logs(log_dir: Path, limit: int, glob: str = "*.log") -> int:
    if not log_dir.is_dir():
        print(f"agent-task: no log directory found: {log_dir}")
        return 0

    logs = sorted(
        (path for path in log_dir.glob(glob) if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not logs:
        print(f"agent-task: no logs found in {log_dir}")
        return 0

    print(f"agent-task: recent logs in {log_dir}")
    for log_path in logs[: max(limit, 1)]:
        print(log_path)
    return 0


def kill_matching_processes(patterns: list[str] | tuple[str, ...], label: str) -> int:
    try:
        processes = list_matching_processes(patterns)
    except ProcessListingError as error:
        print(f"agent-task: process listing unavailable: {error}", file=sys.stderr)
        return 1

    if not processes:
        print(f"agent-task: no {label} found")
        return 0

    exit_code = 0
    for process in processes:
        if process.pid == os.getpid():
            continue
        try:
            os.kill(process.pid, signal.SIGTERM)
            print(f"agent-task: sent SIGTERM to {process.pid} {process.command}")
        except OSError as error:
            print(f"agent-task: failed to terminate {process.pid}: {error}", file=sys.stderr)
            exit_code = 1
    return exit_code


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    command: str


class ProcessListingError(RuntimeError):
    pass


def list_matching_processes(patterns: list[str] | tuple[str, ...]) -> list[ProcessInfo]:
    try:
        result = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    except OSError as error:
        raise ProcessListingError(str(error)) from error

    if result.returncode != 0:
        raise ProcessListingError(result.stdout.strip() or f"ps exited with {result.returncode}")

    processes: list[ProcessInfo] = []
    current_pid = os.getpid()
    for line in result.stdout.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == current_pid or not command_matches(command, patterns):
            continue
        processes.append(ProcessInfo(pid=pid, command=command))
    return processes


def command_matches(command: str, patterns: list[str] | tuple[str, ...]) -> bool:
    lowered = command.lower()
    return any(pattern.lower() in lowered for pattern in patterns if pattern)


if __name__ == "__main__":
    raise SystemExit(main())
