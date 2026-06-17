#!/usr/bin/env python3
"""Build capsule state for agent-safe Gradle runs."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


EXPLICIT_ID_ENV = (
    "SUPERMETA_BUILD_CAPSULE_ID",
    "CODEX_BUILD_CAPSULE_ID",
)
SESSION_ID_ENV = (
    "CODEX_SESSION_ID",
)
SAFE_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_.-]+")
ENV_NAME_PATTERN = re.compile(r"[^A-Z0-9]+")


@dataclass(frozen=True)
class BuildCapsule:
    capsule_id: str
    project_dir: Path
    root: Path
    gradle_user_home: Path
    build_cache: Path
    init_scripts: Path
    logs: Path
    locks: Path
    hygiene: Path
    repair_trash: Path
    included_builds: Path
    summary: Path

    def ensure_directories(self) -> None:
        for path in (
            self.gradle_user_home,
            self.build_cache,
            self.init_scripts,
            self.logs,
            self.locks,
            self.hygiene,
            self.repair_trash,
            self.included_builds,
            self.summary,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def gradle_environment(self) -> dict[str, str]:
        return {
            "GRADLE_USER_HOME": str(self.gradle_user_home),
            "SUPERMETA_GRADLE_BUILD_CACHE": str(self.build_cache),
        }

    def write_build_cache_init_script(self) -> Path:
        self.init_scripts.mkdir(parents=True, exist_ok=True)
        script = self.init_scripts / "capsule-build-cache.gradle.kts"
        escaped_cache = str(self.build_cache).replace("\\", "\\\\").replace('"', '\\"')
        script.write_text(
            "settingsEvaluated {\n"
            "  buildCache {\n"
            "    local {\n"
            f"      directory = file(\"{escaped_cache}\")\n"
            "      isEnabled = true\n"
            "    }\n"
            "  }\n"
            "}\n",
            encoding="utf-8",
        )
        return script

    def summary_payload(self) -> dict[str, str]:
        return {
            "capsuleId": self.capsule_id,
            "projectDir": str(self.project_dir),
            "capsuleRoot": str(self.root),
            "gradleUserHome": str(self.gradle_user_home),
            "buildCache": str(self.build_cache),
            "buildCacheInitScript": str(self.init_scripts / "capsule-build-cache.gradle.kts"),
            "logs": str(self.logs),
            "hygiene": str(self.hygiene),
            "includedBuilds": str(self.included_builds),
        }


def resolve_capsule(project_dir: Path, env: Mapping[str, str]) -> BuildCapsule:
    resolved_project = project_dir.expanduser().resolve()
    project_env_name = build_capsule_env_name(resolved_project)
    capsule_id = first_safe_env_id(env, (project_env_name,)) if project_env_name else None
    if capsule_id is None:
        capsule_id = first_safe_env_id(env, EXPLICIT_ID_ENV)
    if capsule_id is None:
        capsule_id = first_safe_env_id(env, SESSION_ID_ENV)
    if capsule_id is None:
        capsule_id = f"worktree-{stable_path_hash(resolved_project)}"
    root = resolved_project / ".gradle" / "agent-capsules" / capsule_id
    return BuildCapsule(
        capsule_id=capsule_id,
        project_dir=resolved_project,
        root=root,
        gradle_user_home=root / "gradle-user-home",
        build_cache=root / "build-cache",
        init_scripts=root / "init.d",
        logs=root / "logs",
        locks=root / "locks",
        hygiene=root / "hygiene",
        repair_trash=root / "repair-trash",
        included_builds=root / "included-builds",
        summary=root / "summary",
    )


def first_safe_env_id(env: Mapping[str, str], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = env.get(name, "").strip()
        if value:
            return safe_capsule_id(value)
    return None


def build_capsule_env_name(project_dir: Path) -> str | None:
    prefix = ENV_NAME_PATTERN.sub("_", project_dir.name.upper()).strip("_")
    if not prefix:
        return None
    return f"{prefix}_BUILD_CAPSULE_ID"


def safe_capsule_id(value: str) -> str:
    safe = SAFE_ID_PATTERN.sub("-", value.strip()).strip("-._")
    if not safe:
        return "agent"
    return safe[:80]


def stable_path_hash(path: Path) -> str:
    normalized = str(path).replace("\\", "/").lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
