#!/usr/bin/env python3
"""Project-directory handling for capsule-local included builds."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from typing import Mapping


PROJECT_DIRECTORY_ENV = "SUPERMETA_PROJECT_DIRECTORY_FILE"


class ProjectDirectoryError(RuntimeError):
    """Raised when the project-directory contract cannot be materialized."""


@dataclass(frozen=True)
class ProjectDirectorySource:
    path: Path
    explicit: bool


@dataclass(frozen=True)
class ProjectDirectory:
    path: Path
    repos: dict[str, Path]


def resolve_project_directory_source(
    project_dir: Path,
    env: Mapping[str, str],
    explicit_file: Path | None = None,
) -> ProjectDirectorySource:
    if explicit_file is not None:
        path = explicit_file.expanduser().resolve()
        if not path.is_file():
            raise ProjectDirectoryError(f"project directory file is missing: {path}")
        return ProjectDirectorySource(path, True)

    env_file = env.get(PROJECT_DIRECTORY_ENV, "").strip()
    if env_file:
        path = Path(env_file)
        if not path.is_absolute():
            raise ProjectDirectoryError(f"{PROJECT_DIRECTORY_ENV} must be absolute: {env_file}")
        if not path.is_file():
            raise ProjectDirectoryError(f"{PROJECT_DIRECTORY_ENV} points to a missing file: {path}")
        return ProjectDirectorySource(path, True)

    resolved_project = project_dir.resolve()
    properties_file = resolved_project / "project-directory.properties"
    if properties_file.is_file():
        return ProjectDirectorySource(properties_file, False)

    example_file = resolved_project / "project-directory.properties.example"
    if example_file.is_file():
        return ProjectDirectorySource(example_file, False)

    raise ProjectDirectoryError(
        "could not find project-directory.properties or "
        f"project-directory.properties.example under {resolved_project}"
    )


def load_project_directory(path: Path) -> ProjectDirectory:
    if not path.is_file():
        raise ProjectDirectoryError(f"project directory file is missing: {path}")

    base = path.resolve().parent
    repos: dict[str, Path] = {}
    version = None
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ProjectDirectoryError(f"invalid project directory entry at {path}:{line_number}")
        key, value = (part.strip() for part in line.split("=", 1))
        if key == "version":
            version = value
            continue
        if not key.startswith("repo."):
            continue
        repo_id = key.removeprefix("repo.")
        if not repo_id:
            raise ProjectDirectoryError(f"blank repo id at {path}:{line_number}")
        if not value:
            raise ProjectDirectoryError(f"blank project directory entry for {repo_id} at {path}:{line_number}")
        declared = Path(value)
        repos[repo_id] = (declared if declared.is_absolute() else base / declared).resolve()

    if version != "1":
        raise ProjectDirectoryError(f"project directory file must declare version=1: {path}")
    return ProjectDirectory(path.resolve(), repos)


def materialize_included_worktrees(
    source_repos: Mapping[str, Path],
    included_root: Path,
    repo_ids: tuple[str, ...],
    runner: Callable[[list[str]], None],
) -> dict[str, Path]:
    included_root.mkdir(parents=True, exist_ok=True)
    materialized: dict[str, Path] = {}
    for repo_id in repo_ids:
        source_repo = source_repos.get(repo_id)
        if source_repo is None:
            raise ProjectDirectoryError(f"project directory does not define repo.{repo_id}")
        if not source_repo.is_dir():
            raise ProjectDirectoryError(f"source repo for {repo_id} is missing: {source_repo}")
        destination = included_root / repo_id
        if destination.exists():
            materialized[repo_id] = destination
            continue
        runner(["git", "-C", str(source_repo), "worktree", "add", "--detach", str(destination), "HEAD"])
        if not destination.is_dir():
            raise ProjectDirectoryError(f"worktree for {repo_id} was not created: {destination}")
        materialized[repo_id] = destination
    return materialized


def write_project_directory(path: Path, repos: Mapping[str, Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["version=1"]
    for repo_id in sorted(repos):
        lines.append(f"repo.{repo_id}={repos[repo_id].resolve()}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
