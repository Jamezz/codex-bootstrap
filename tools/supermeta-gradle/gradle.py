#!/usr/bin/env python3
"""Run Gradle with defaults that are safer for agent harnesses."""

from __future__ import annotations

import argparse
import os
import signal
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on Windows.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX.
    msvcrt = None

GRADLE_TOOL_DIR = Path(__file__).resolve().parent
if str(GRADLE_TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(GRADLE_TOOL_DIR))

TASK_TOOL_DIR = Path(__file__).resolve().parents[1] / "supermeta-task"
if TASK_TOOL_DIR.is_dir():
    sys.path.insert(0, str(TASK_TOOL_DIR))

from capsule import BuildCapsule
from capsule import resolve_capsule
from generated_hygiene import GeneratedHygieneResult
from generated_hygiene import run_generated_hygiene
from project_directory import IncludedBuildDefaults
from project_directory import ProjectDirectoryError
from project_directory import load_included_build_defaults
from project_directory import load_project_directory
from project_directory import materialize_included_worktrees
from project_directory import PROJECT_DIRECTORY_ENV
from project_directory import resolve_project_directory_source
from project_directory import write_project_directory
from task import command_matches
from task import list_matching_processes
from task import ProcessListingError
from task import print_matching_processes
from task import print_recent_logs as print_task_recent_logs


DEFAULT_COLD_MAX_WORKERS = "2"
GRADLE_PROCESS_MATCHES = (
    "supermeta-gradle/gradle.py",
    "gradle-launcher",
    "gradle.daemon",
    "/gradlew",
    " gradlew",
)


def main() -> int:
    args = parse_args()
    project_dir = args.project.resolve()
    env = os.environ.copy()
    if args.capsule_id:
        env["SUPERMETA_BUILD_CAPSULE_ID"] = args.capsule_id
    build_capsule = resolve_capsule(project_dir, env)
    build_capsule.ensure_directories()

    if args.clean_supermeta_cache:
        clean_exit = clean_supermeta_rules_cache(project_dir, build_capsule, env)
        if clean_exit != 0:
            return clean_exit

    if args.diagnostics_command:
        return run_diagnostics_command(args, project_dir, build_capsule)

    gradle_args = normalize_gradle_args(args.gradle_args)
    if not gradle_args:
        if args.clean_supermeta_cache:
            return 0
        print("supermeta-gradle: no Gradle arguments supplied", file=sys.stderr)
        return 2

    wrapper = resolve_gradle_wrapper(project_dir)
    if wrapper is None:
        print(f"supermeta-gradle: missing Gradle wrapper in {project_dir}", file=sys.stderr)
        return 2

    gradle_home = resolve_gradle_home(args.gradle_user_home, project_dir, build_capsule)
    gradle_home.mkdir(parents=True, exist_ok=True)

    log_dir = build_capsule.logs
    run_id = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}-{time.time_ns() % 1_000_000_000:09d}"
    log_path = log_dir / f"{run_id}-{safe_name(gradle_args)}.log"

    cold_mode = args.cold or os.environ.get("SUPERMETA_GRADLE_COLD") in {"1", "true", "yes"}
    build_cache_init_script = build_capsule.write_build_cache_init_script()
    gradle_args = add_init_script_arg(gradle_args, build_cache_init_script)
    command = build_command(wrapper, gradle_args, args.no_default_flags, cold_mode)
    env.update(build_capsule.gradle_environment())
    env["GRADLE_USER_HOME"] = str(gradle_home)
    env.setdefault("SUPERMETA_RULES_CACHE_FILE", str(build_capsule.root / "supermeta-rules" / "cache-v1.json"))

    lock_path = build_capsule.locks / "gradle-home.lock"
    total_start_time = time.monotonic()
    lock_wait_seconds = 0.0

    with lock_path.open("w", encoding="utf-8") as lock_file:
        if not args.no_lock:
            print(f"supermeta-gradle: waiting for Gradle home lock {lock_path}", flush=True)
            lock_start_time = time.monotonic()
            lock_file_exclusive(lock_file)
            lock_wait_seconds = time.monotonic() - lock_start_time

        if args.strict_included_builds:
            try:
                project_directory_file = configure_project_directory_env(args, project_dir, build_capsule, env)
            except ProjectDirectoryError as error:
                print(f"supermeta-gradle: {error}", file=sys.stderr)
                return 2
            print(f"supermeta-gradle: {PROJECT_DIRECTORY_ENV}={project_directory_file}", flush=True)

        hygiene_result = None
        if not args.no_hygiene:
            hygiene_result = run_generated_hygiene(project_dir, build_capsule.hygiene)
            if hygiene_result.actions:
                print_hygiene_result(hygiene_result)

        log_dir.mkdir(parents=True, exist_ok=True)
        return run_gradle(
            command,
            project_dir,
            env,
            log_path,
            gradle_home,
            build_capsule,
            cold_mode,
            hygiene_result,
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
    parser.add_argument("--capsule-id", help="Override the build capsule id for this run.")
    parser.add_argument(
        "--project-directory-file",
        type=Path,
        help="Project-directory file to use when materializing strict included builds.",
    )
    parser.add_argument(
        "--strict-included-builds",
        action="store_true",
        help=f"Materialize included builds into this capsule and export {PROJECT_DIRECTORY_ENV}.",
    )
    parser.add_argument(
        "--included-build-repo",
        action="append",
        default=[],
        help="Repo id to materialize for --strict-included-builds. Can be repeated.",
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
    parser.add_argument("--no-hygiene", action="store_true", help="Skip generated-output hygiene.")
    parser.add_argument(
        "--clean-supermeta-cache",
        action="store_true",
        help="Remove Supermeta rules analysis caches before running Gradle.",
    )
    parser.add_argument(
        "--ps",
        action="store_const",
        const="ps",
        dest="diagnostics_command",
        help="List likely Gradle/Java processes for stuck-build diagnostics.",
    )
    parser.add_argument(
        "--logs",
        action="store_const",
        const="logs",
        dest="diagnostics_command",
        help="List recent Supermeta Gradle harness logs for this project.",
    )
    parser.add_argument(
        "--stop",
        action="store_const",
        const="stop",
        dest="diagnostics_command",
        help="Ask this project's Gradle daemon to stop.",
    )
    parser.add_argument(
        "--kill",
        action="store_const",
        const="kill",
        dest="diagnostics_command",
        help="Terminate likely stuck Gradle/Java processes owned by this user.",
    )
    parser.add_argument(
        "--status",
        action="store_const",
        const="status",
        dest="diagnostics_command",
        help="Print capsule status and scoped Gradle process diagnostics.",
    )
    parser.add_argument(
        "--repair",
        action="store_const",
        const="repair",
        dest="diagnostics_command",
        help="Stop capsule Gradle daemons and reset capsule caches.",
    )
    parser.add_argument(
        "--hygiene-only",
        action="store_const",
        const="hygiene",
        dest="diagnostics_command",
        help="Run generated-output hygiene without invoking Gradle.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum number of recent logs to list with --logs.",
    )
    parser.add_argument("gradle_args", nargs=argparse.REMAINDER)
    return parser.parse_args()


def run_diagnostics_command(args: argparse.Namespace, project_dir: Path, build_capsule: BuildCapsule) -> int:
    command = args.diagnostics_command
    gradle_home = resolve_gradle_home(args.gradle_user_home, project_dir, build_capsule)
    if command == "ps":
        return print_processes()
    if command == "logs":
        return print_recent_logs(build_capsule, args.limit)
    if command == "stop":
        return stop_gradle_daemon(project_dir, gradle_home)
    if command == "kill":
        return kill_gradle_processes(project_dir, gradle_home)
    if command == "status":
        return print_status(build_capsule)
    if command == "repair":
        return repair_capsule(build_capsule)
    if command == "hygiene":
        return run_hygiene_only(project_dir, build_capsule)
    print(f"supermeta-gradle: unknown diagnostics command: {command}", file=sys.stderr)
    return 2


def normalize_gradle_args(raw_args: list[str]) -> list[str]:
    if raw_args and raw_args[0] == "--":
        return raw_args[1:]
    return raw_args


def resolve_gradle_home(
    configured_home: Path | None,
    project_dir: Path,
    build_capsule: BuildCapsule | None = None,
) -> Path:
    if configured_home is not None:
        return configured_home.expanduser().resolve()

    env_home = os.environ.get("SUPERMETA_GRADLE_USER_HOME")
    if env_home:
        return Path(env_home).expanduser().resolve()

    if build_capsule is not None:
        return build_capsule.gradle_user_home

    return (project_dir / ".gradle" / "supermeta-gradle" / "gradle-user-home").resolve()


def print_processes() -> int:
    return print_matching_processes(GRADLE_PROCESS_MATCHES, "likely Gradle/Java processes", True)


def print_recent_logs(build_capsule: BuildCapsule, limit: int) -> int:
    return print_task_recent_logs(build_capsule.logs, limit)


def stop_gradle_daemon(project_dir: Path, gradle_home: Path) -> int:
    wrapper = resolve_gradle_wrapper(project_dir)
    if wrapper is None:
        print(f"supermeta-gradle: missing Gradle wrapper in {project_dir}", file=sys.stderr)
        return 2

    command = [*gradle_executable(wrapper), "--stop"]
    env = os.environ.copy()
    env["GRADLE_USER_HOME"] = str(gradle_home)
    print(f"supermeta-gradle: stopping Gradle daemon with {shlex.join(command)}")
    result = subprocess.run(
        command,
        cwd=project_dir,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    print(result.stdout, end="")
    return result.returncode


def kill_gradle_processes(project_dir: Path, gradle_home: Path) -> int:
    try:
        processes = list_matching_processes(GRADLE_PROCESS_MATCHES)
    except ProcessListingError as error:
        print(f"supermeta-gradle: process listing unavailable: {error}", file=sys.stderr)
        return 1

    scoped_processes = [
        process
        for process in processes
        if is_scoped_gradle_process(process.command, project_dir, gradle_home)
    ]
    if not scoped_processes:
        print("supermeta-gradle: no scoped Gradle/Java processes found")
        return 0

    exit_code = 0
    for process in scoped_processes:
        if process.pid == os.getpid():
            continue
        try:
            os.kill(process.pid, signal.SIGTERM)
            print(f"supermeta-gradle: sent SIGTERM to {process.pid} {process.command}")
        except OSError as error:
            print(f"supermeta-gradle: failed to terminate {process.pid}: {error}", file=sys.stderr)
            exit_code = 1
    return exit_code


def is_gradle_process(command: str) -> bool:
    return command_matches(command, GRADLE_PROCESS_MATCHES)


def is_scoped_gradle_process(command: str, project_dir: Path, gradle_home: Path) -> bool:
    if not is_gradle_process(command):
        return False

    project_scope = normalize_path_text(project_dir.resolve())
    gradle_home_scope = normalize_path_text(gradle_home.resolve())
    return any(
        path_is_project_scoped(token, project_scope) or path_is_project_scoped(token, gradle_home_scope)
        for token in command_path_tokens(command)
    )


def command_path_tokens(command: str) -> list[str]:
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = command.split()

    path_tokens: list[str] = []
    for token in tokens:
        path_tokens.append(token)
        _, separator, value = token.partition("=")
        if separator and value:
            path_tokens.append(value)
    return path_tokens


def path_is_project_scoped(token: str, project_scope: str) -> bool:
    normalized = normalize_path_text(token)
    return normalized == project_scope or normalized.startswith(f"{project_scope}/")


def normalize_path_text(value: str | Path) -> str:
    text = str(value).strip().strip("\"'")
    return text.replace("\\", "/").rstrip("/").lower()


def build_command(
    wrapper: Path,
    gradle_args: list[str],
    no_default_flags: bool,
    cold_mode: bool,
    platform_name: str | None = None,
) -> list[str]:
    executable = gradle_executable(wrapper, platform_name)
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

    if not cold_mode and os.environ.get("SUPERMETA_GRADLE_PARALLEL") in {"1", "true", "yes"}:
        add_flag_pair(defaults, gradle_args, "--parallel", "--no-parallel")
        if not has_max_workers(gradle_args) and os.environ.get("SUPERMETA_GRADLE_MAX_WORKERS"):
            defaults.append(f"--max-workers={os.environ['SUPERMETA_GRADLE_MAX_WORKERS']}")

    return [*executable, *defaults, *gradle_args]


def add_init_script_arg(gradle_args: list[str], init_script: Path) -> list[str]:
    if any(arg == "--init-script" or arg.startswith("--init-script=") for arg in gradle_args):
        return gradle_args
    return [f"--init-script={init_script}", *gradle_args]


def configure_project_directory_env(
    args: argparse.Namespace,
    project_dir: Path,
    build_capsule: BuildCapsule,
    env: dict[str, str],
) -> Path:
    defaults = load_included_build_defaults(project_dir)
    repo_ids = resolve_included_build_repo_ids(args, defaults)
    materialized: dict[str, Path] = {}
    if repo_ids:
        source = resolve_project_directory_source(
            project_dir,
            env,
            explicit_file=args.project_directory_file,
            default_file=defaults.project_directory_file,
        )
        directory = load_project_directory(source.path)
        materialized = materialize_included_worktrees(
            directory.repos,
            build_capsule.included_builds,
            repo_ids,
            runner=run_project_directory_command,
        )
    output_file = build_capsule.included_builds / "project-directory.properties"
    write_project_directory(output_file, materialized)
    env[PROJECT_DIRECTORY_ENV] = str(output_file)
    return output_file


def resolve_included_build_repo_ids(
    args: argparse.Namespace,
    defaults: IncludedBuildDefaults,
) -> tuple[str, ...]:
    configured = tuple(repo_id.strip() for repo_id in args.included_build_repo if repo_id.strip())
    if configured:
        return configured
    return defaults.repo_ids


def run_project_directory_command(command: list[str]) -> None:
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        output = result.stdout.strip()
        detail = f": {output}" if output else ""
        raise ProjectDirectoryError(f"command failed ({shlex.join(command)}){detail}")


def resolve_gradle_wrapper(project_dir: Path, platform_name: str | None = None) -> Path | None:
    platform = platform_name or os.name
    if platform == "nt":
        batch_wrapper = project_dir / "gradlew.bat"
        if batch_wrapper.is_file():
            return batch_wrapper

    wrapper = project_dir / "gradlew"
    if wrapper.is_file():
        return wrapper

    if platform != "nt":
        batch_wrapper = project_dir / "gradlew.bat"
        if batch_wrapper.is_file():
            return batch_wrapper

    return None


def gradle_executable(wrapper: Path, platform_name: str | None = None) -> list[str]:
    platform = platform_name or os.name
    if platform == "nt":
        if wrapper.suffix.lower() in {".bat", ".cmd"}:
            return [str(wrapper)]
        return [f"{wrapper}.bat"]
    if wrapper.suffix.lower() in {".bat", ".cmd"}:
        return [str(wrapper)]
    return [str(wrapper)] if os.access(wrapper, os.X_OK) else ["sh", str(wrapper)]


def lock_file_exclusive(lock_file: object) -> None:
    if fcntl is not None:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        return

    if msvcrt is not None:
        lock_file.seek(0)
        msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        return

    print("supermeta-gradle: file locking unavailable on this platform", file=sys.stderr)


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
    build_capsule: BuildCapsule,
    cold_mode: bool,
    hygiene_result: GeneratedHygieneResult | None,
    lock_wait_seconds: float,
    total_start_time: float,
) -> int:
    run_start_time = time.monotonic()
    mode = "cold" if cold_mode else "warm"
    hygiene_actions = 0 if hygiene_result is None else len(hygiene_result.actions)
    print("supermeta-gradle:", flush=True)
    print(f"  capsule_id: {build_capsule.capsule_id}", flush=True)
    print(f"  mode: {mode}", flush=True)
    print(f"  project: {project_dir}", flush=True)
    print(f"  gradle_user_home: {gradle_home}", flush=True)
    print(f"  capsule_root: {build_capsule.root}", flush=True)
    print(f"  hygiene_actions: {hygiene_actions}", flush=True)
    print(f"  lock_wait: {lock_wait_seconds:.1f}s", flush=True)
    print(f"  log: {log_path}", flush=True)
    print(f"  command: {shlex.join(command)}", flush=True)

    with log_path.open("w", encoding="utf-8") as log_file:
        log_file.write(f"capsule_id: {build_capsule.capsule_id}\n")
        log_file.write(f"project: {project_dir}\n")
        log_file.write(f"mode: {mode}\n")
        log_file.write(f"gradle_user_home: {gradle_home}\n")
        log_file.write(f"capsule_root: {build_capsule.root}\n")
        log_file.write(f"hygiene_actions: {hygiene_actions}\n")
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


def print_hygiene_result(result: GeneratedHygieneResult) -> None:
    for action in result.actions:
        destination = f" -> {action.destination_path}" if action.destination_path else ""
        print(f"supermeta-gradle: hygiene {action.reason}: {action.duplicate_path}{destination}", flush=True)


def run_hygiene_only(project_dir: Path, build_capsule: BuildCapsule) -> int:
    result = run_generated_hygiene(project_dir, build_capsule.hygiene)
    print_hygiene_result(result)
    if not result.actions:
        print("supermeta-gradle: hygiene clean")
    return 0


def clean_supermeta_rules_cache(
    project_dir: Path,
    build_capsule: BuildCapsule,
    env: dict[str, str] | None = None,
) -> int:
    candidates = supermeta_rules_cache_paths(project_dir, build_capsule, env or os.environ)
    removed = 0
    for path in candidates:
        try:
            if path.is_file():
                path.unlink()
                removed += 1
                print(f"supermeta-gradle: removed Supermeta rules cache {path}", flush=True)
                remove_empty_supermeta_cache_dir(path.parent)
        except OSError as error:
            print(f"supermeta-gradle: failed to remove Supermeta rules cache {path}: {error}", file=sys.stderr)
            return 1
    if removed == 0:
        print("supermeta-gradle: Supermeta rules cache clean")
    return 0


def supermeta_rules_cache_paths(
    project_dir: Path,
    build_capsule: BuildCapsule,
    env: dict[str, str],
) -> tuple[Path, ...]:
    paths: list[Path] = [
        project_dir / ".gradle" / "supermeta-rules" / "cache-v1.json",
        build_capsule.root / "supermeta-rules" / "cache-v1.json",
    ]
    env_cache = env.get("SUPERMETA_RULES_CACHE_FILE")
    if env_cache:
        paths.append(Path(env_cache))
    paths.extend(project_dir.glob(".gradle/agent-capsules/*/supermeta-rules/cache-v1.json"))
    paths.extend(project_dir.glob("*/.gradle/supermeta-rules/cache-v1.json"))
    return tuple(dict.fromkeys(path.resolve() for path in paths))


def remove_empty_supermeta_cache_dir(path: Path) -> None:
    if path.name != "supermeta-rules":
        return
    try:
        path.rmdir()
    except OSError:
        return


def print_status(build_capsule: BuildCapsule) -> int:
    print("supermeta-gradle:")
    for key, value in build_capsule.summary_payload().items():
        print(f"  {key}: {value}")
    print_processes()
    return 0


def repair_capsule(build_capsule: BuildCapsule) -> int:
    stop_exit = stop_gradle_daemon(build_capsule.project_dir, build_capsule.gradle_user_home)
    for path in (build_capsule.gradle_user_home / "caches", build_capsule.build_cache):
        if path.exists():
            shutil.rmtree(path)
            print(f"supermeta-gradle: removed {path}")
    return stop_exit


def safe_name(gradle_args: list[str]) -> str:
    joined = "-".join(arg.strip("-").replace("/", "_") for arg in gradle_args[:3])
    safe = "".join(character if character.isalnum() or character in "._-" else "_" for character in joined)
    return safe[:80] or "gradle"


if __name__ == "__main__":
    raise SystemExit(main())
