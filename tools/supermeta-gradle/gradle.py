#!/usr/bin/env python3
"""Run Gradle with defaults that are safer for agent harnesses."""

from __future__ import annotations

import argparse
import fcntl
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_COLD_MAX_WORKERS = "2"


def main() -> int:
    args = parse_args()
    project_dir = args.project.resolve()
    gradle_args = normalize_gradle_args(args.gradle_args)

    if not gradle_args:
        print("supermeta-gradle: no Gradle arguments supplied", file=sys.stderr)
        return 2

    wrapper = project_dir / "gradlew"
    if not wrapper.is_file():
        print(f"supermeta-gradle: missing Gradle wrapper at {wrapper}", file=sys.stderr)
        return 2

    gradle_home = resolve_gradle_home(args.gradle_user_home, project_dir)
    gradle_home.mkdir(parents=True, exist_ok=True)

    log_dir = project_dir / ".gradle" / "supermeta-gradle" / "logs"
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{time.time_ns() % 1_000_000_000:09d}"
    log_path = log_dir / f"{run_id}-{safe_name(gradle_args)}.log"

    cold_mode = args.cold or os.environ.get("SUPERMETA_GRADLE_COLD") in {"1", "true", "yes"}
    command = build_command(wrapper, gradle_args, args.no_default_flags, cold_mode)
    env = os.environ.copy()
    env["GRADLE_USER_HOME"] = str(gradle_home)

    lock_path = gradle_home / "supermeta-gradle.lock"
    total_start_time = time.monotonic()
    lock_wait_seconds = 0.0

    with lock_path.open("w", encoding="utf-8") as lock_file:
        if not args.no_lock:
            print(f"supermeta-gradle: waiting for Gradle home lock {lock_path}", flush=True)
            lock_start_time = time.monotonic()
            fcntl.flock(lock_file, fcntl.LOCK_EX)
            lock_wait_seconds = time.monotonic() - lock_start_time

        log_dir.mkdir(parents=True, exist_ok=True)
        return run_gradle(
            command,
            project_dir,
            env,
            log_path,
            gradle_home,
            cold_mode,
            lock_wait_seconds,
            total_start_time,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Gradle with agent-safe defaults.")
    parser.add_argument(
        "--project",
        type=Path,
        default=Path("."),
        help="Gradle project directory containing gradlew.",
    )
    parser.add_argument(
        "--gradle-user-home",
        type=Path,
        help="Override GRADLE_USER_HOME for this run.",
    )
    parser.add_argument(
        "--no-default-flags",
        action="store_true",
        help="Do not add Supermeta Gradle defaults.",
    )
    parser.add_argument(
        "--cold",
        action="store_true",
        help="Use conservative no-daemon, no-parallel defaults for wedged or diagnostic runs.",
    )
    parser.add_argument(
        "--no-lock",
        action="store_true",
        help="Do not serialize runs for this project.",
    )
    parser.add_argument("gradle_args", nargs=argparse.REMAINDER)
    return parser.parse_args()


def normalize_gradle_args(raw_args: list[str]) -> list[str]:
    if raw_args and raw_args[0] == "--":
        return raw_args[1:]
    return raw_args


def resolve_gradle_home(configured_home: Path | None, project_dir: Path) -> Path:
    if configured_home is not None:
        return configured_home.expanduser().resolve()

    env_home = os.environ.get("SUPERMETA_GRADLE_USER_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    return Path("/tmp") / "supermeta-gradle" / "gradle-user-home"


def build_command(
    wrapper: Path,
    gradle_args: list[str],
    no_default_flags: bool,
    cold_mode: bool,
) -> list[str]:
    executable = [str(wrapper)] if os.access(wrapper, os.X_OK) else ["sh", str(wrapper)]
    if no_default_flags:
        return [*executable, *gradle_args]

    defaults: list[str] = []
    add_flag_pair(defaults, gradle_args, "--no-watch-fs", "--watch-fs")

    if cold_mode:
        add_flag_pair(defaults, gradle_args, "--no-daemon", "--daemon")
        add_flag_pair(defaults, gradle_args, "--no-parallel", "--parallel")
        if not has_max_workers(gradle_args):
            max_workers = os.environ.get("SUPERMETA_GRADLE_MAX_WORKERS", DEFAULT_COLD_MAX_WORKERS)
            defaults.append(f"--max-workers={max_workers}")
    elif os.environ.get("SUPERMETA_GRADLE_PARALLEL") in {"1", "true", "yes"}:
        add_flag_pair(defaults, gradle_args, "--parallel", "--no-parallel")
        if not has_max_workers(gradle_args) and os.environ.get("SUPERMETA_GRADLE_MAX_WORKERS"):
            defaults.append(f"--max-workers={os.environ['SUPERMETA_GRADLE_MAX_WORKERS']}")

    return [*executable, *defaults, *gradle_args]


def add_flag_pair(defaults: list[str], gradle_args: list[str], off_flag: str, on_flag: str) -> None:
    if off_flag not in gradle_args and on_flag not in gradle_args:
        defaults.append(off_flag)


def has_max_workers(gradle_args: list[str]) -> bool:
    return any(arg == "--max-workers" or arg.startswith("--max-workers=") for arg in gradle_args)


def run_gradle(
    command: list[str],
    project_dir: Path,
    env: dict[str, str],
    log_path: Path,
    gradle_home: Path,
    cold_mode: bool,
    lock_wait_seconds: float,
    total_start_time: float,
) -> int:
    run_start_time = time.monotonic()
    print("supermeta-gradle:", flush=True)
    print(f"  mode: {'cold' if cold_mode else 'warm'}", flush=True)
    print(f"  project: {project_dir}", flush=True)
    print(f"  gradle_user_home: {gradle_home}", flush=True)
    print(f"  lock_wait: {lock_wait_seconds:.1f}s", flush=True)
    print(f"  log: {log_path}", flush=True)
    print(f"  command: {shlex.join(command)}", flush=True)

    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"project: {project_dir}\n")
        log_file.write(f"mode: {'cold' if cold_mode else 'warm'}\n")
        log_file.write(f"gradle_user_home: {gradle_home}\n")
        log_file.write(f"lock_wait: {lock_wait_seconds:.1f}s\n")
        log_file.write(f"command: {shlex.join(command)}\n\n")
        log_file.flush()

        process = subprocess.Popen(
            command,
            cwd=project_dir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )

        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="", flush=True)
            log_file.write(line)

        exit_code = process.wait()
        run_elapsed_seconds = time.monotonic() - run_start_time
        total_elapsed_seconds = time.monotonic() - total_start_time
        summary = (
            f"\nsupermeta-gradle: exit={exit_code} "
            f"run_elapsed={run_elapsed_seconds:.1f}s "
            f"total_elapsed={total_elapsed_seconds:.1f}s "
            f"lock_wait={lock_wait_seconds:.1f}s "
            f"log={log_path}\n"
        )
        print(summary, end="", flush=True)
        log_file.write(summary)
        return exit_code


def safe_name(gradle_args: list[str]) -> str:
    joined = "-".join(arg.strip("-").replace("/", "_") for arg in gradle_args[:3])
    safe = "".join(character if character.isalnum() or character in "._-" else "_" for character in joined)
    return safe[:80] or "gradle"


if __name__ == "__main__":
    raise SystemExit(main())
