"""Git working-set detection for Supermeta rule scans."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


TRUTHY = {"1", "true", "yes"}
DEFAULT_FAST_SCAN_INTERVAL = 10
STATE_FILE_NAME = "supermeta-rules-state.json"


@dataclass(frozen=True)
class WorkingSet:
    mode: str
    files: frozenset[Path]
    reason: str

    def narrows_scan(self) -> bool:
        return self.mode == "working-set" and bool(self.files)


def full_working_set(reason: str = "full scan requested") -> WorkingSet:
    return WorkingSet(mode="full", files=frozenset(), reason=reason)


def detect_working_set(root: Path, force_full: bool = False) -> WorkingSet:
    if force_full or os.environ.get("SUPERMETA_RULES_FULL", "").lower() in TRUTHY:
        return full_working_set()

    root = root.resolve()
    git_root_raw = git_output(root, "rev-parse", "--show-toplevel")
    if git_root_raw is None:
        return full_working_set("not inside a Git worktree")

    git_root = Path(git_root_raw).resolve()
    try:
        root_prefix = root.relative_to(git_root).as_posix()
    except ValueError:
        return full_working_set("rule root is outside the Git worktree")
    root_prefix = "" if root_prefix == "." else root_prefix

    dirty_files = changed_files_from_status(git_root, root_prefix)
    if dirty_files is None:
        return full_working_set("Git status failed")
    if dirty_files:
        return WorkingSet(
            mode="working-set",
            files=frozenset(dirty_files),
            reason=f"{len(dirty_files)} dirty Git file(s)",
        )

    upstream = git_output(git_root, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}")
    if upstream is None:
        return full_working_set("clean tree with no upstream")

    merge_base = git_output(git_root, "merge-base", "HEAD", upstream)
    if merge_base is None:
        return full_working_set("clean tree with no merge-base")

    branch_files = changed_files_from_diff(git_root, root_prefix, merge_base)
    if branch_files is None:
        return full_working_set("Git diff failed")
    if branch_files:
        return WorkingSet(
            mode="working-set",
            files=frozenset(branch_files),
            reason=f"{len(branch_files)} branch Git file(s)",
        )
    return full_working_set("clean tree with no branch changes")


def apply_periodic_full_scan(root: Path, working_set: WorkingSet) -> WorkingSet:
    location = scan_state_location(root)
    if location is None:
        return working_set
    state_path, root_key = location
    state = read_scan_state(state_path)
    roots = state.setdefault("roots", {})
    if not isinstance(roots, dict):
        roots = {}
        state["roots"] = roots
    root_state = roots.setdefault(root_key, {})
    if not isinstance(root_state, dict):
        root_state = {}
        roots[root_key] = root_state

    fast_scan_count = non_negative_int(root_state.get("fastScansSinceFull", 0))
    if working_set.narrows_scan():
        interval = fast_scan_interval()
        if fast_scan_count >= interval:
            root_state["fastScansSinceFull"] = 0
            write_scan_state(state_path, state)
            return full_working_set(f"periodic full scan after {fast_scan_count} fast scans")
        root_state["fastScansSinceFull"] = fast_scan_count + 1
        write_scan_state(state_path, state)
        return working_set

    root_state["fastScansSinceFull"] = 0
    write_scan_state(state_path, state)
    return working_set


def scan_state_location(root: Path) -> tuple[Path, str] | None:
    root = root.resolve()
    git_root_raw = git_output(root, "rev-parse", "--show-toplevel")
    if git_root_raw is None:
        return None
    git_root = Path(git_root_raw).resolve()
    try:
        root_key = root.relative_to(git_root).as_posix()
    except ValueError:
        return None
    if root_key == ".":
        root_key = ""
    state_path_raw = git_output(git_root, "rev-parse", "--git-path", STATE_FILE_NAME)
    if state_path_raw is None:
        return None
    state_path = Path(state_path_raw)
    if not state_path.is_absolute():
        state_path = git_root / state_path
    return state_path.resolve(), root_key


def read_scan_state(state_path: Path) -> dict[str, object]:
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def write_scan_state(state_path: Path, state: dict[str, object]) -> None:
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    except OSError:
        return


def fast_scan_interval() -> int:
    raw_interval = os.environ.get("SUPERMETA_RULES_FAST_SCAN_INTERVAL", "")
    if not raw_interval:
        return DEFAULT_FAST_SCAN_INTERVAL
    try:
        interval = int(raw_interval)
    except ValueError:
        return DEFAULT_FAST_SCAN_INTERVAL
    return interval if interval > 0 else DEFAULT_FAST_SCAN_INTERVAL


def non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def changed_files_from_status(git_root: Path, root_prefix: str) -> set[Path] | None:
    pathspec = root_prefix or "."
    result = git_run(git_root, "status", "--porcelain=v1", "--untracked-files=all", "--", pathspec)
    if result.returncode != 0:
        return None
    files: set[Path] = set()
    for line in result.stdout.splitlines():
        if not line:
            continue
        relative_path = repo_path_to_root_path(normalize_git_status_path(line[3:]), root_prefix)
        if relative_path is not None:
            files.add(relative_path)
    return files


def changed_files_from_diff(git_root: Path, root_prefix: str, merge_base: str) -> set[Path] | None:
    pathspec = root_prefix or "."
    result = git_run(git_root, "diff", "--name-only", merge_base, "--", pathspec)
    if result.returncode != 0:
        return None
    files: set[Path] = set()
    for line in result.stdout.splitlines():
        relative_path = repo_path_to_root_path(line, root_prefix)
        if relative_path is not None:
            files.add(relative_path)
    return files


def git_visible_files(root: Path, paths: list[str]) -> set[Path] | None:
    root = root.resolve()
    git_root_raw = git_output(root, "rev-parse", "--show-toplevel")
    if git_root_raw is None:
        return None
    git_root = Path(git_root_raw).resolve()
    try:
        root_prefix = root.relative_to(git_root).as_posix()
    except ValueError:
        return None
    root_prefix = "" if root_prefix == "." else root_prefix
    pathspecs = [root_pathspec_to_repo_pathspec(root_prefix, path) for path in paths]
    result = git_run(git_root, "ls-files", "--cached", "--others", "--exclude-standard", "--", *pathspecs)
    if result.returncode != 0:
        return None
    files: set[Path] = set()
    for line in result.stdout.splitlines():
        relative_path = repo_path_to_root_path(line, root_prefix)
        if relative_path is not None:
            files.add(relative_path)
    return files


def root_pathspec_to_repo_pathspec(root_prefix: str, path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    if normalized in {"", "."}:
        normalized = "."
    if not root_prefix:
        return normalized
    if normalized == ".":
        return root_prefix
    return f"{root_prefix}/{normalized}"


def repo_path_to_root_path(repo_path: str, root_prefix: str) -> Path | None:
    normalized = repo_path.replace("\\", "/").strip("/")
    if not normalized:
        return None
    if root_prefix:
        prefix = root_prefix.strip("/")
        if normalized == prefix:
            return Path(".")
        prefix_with_slash = f"{prefix}/"
        if not normalized.startswith(prefix_with_slash):
            return None
        normalized = normalized[len(prefix_with_slash) :]
    parts = normalized.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        return None
    return Path(*parts)


def normalize_git_status_path(path: str) -> str:
    if path.startswith('"'):
        parts = shlex.split(path)
        if "->" in parts:
            return parts[-1]
        if len(parts) == 1:
            return parts[0]
    if " -> " in path:
        path = path.split(" -> ", 1)[1]
    return path


def git_output(cwd: Path, *args: str) -> str | None:
    result = git_run(cwd, *args)
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def git_run(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
