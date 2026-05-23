#!/usr/bin/env python3
"""Local advisory coordination for parallel Codex agents."""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from pathlib import PureWindowsPath
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by Windows contract tests.
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - exercised on POSIX.
    msvcrt = None


SCHEMA_VERSION = 1
DEFAULT_TTL_SECONDS = 900
ACQUIRE_TIMEOUT_EXIT = 75
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
RESOURCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")


class CoordinationError(Exception):
    """User-facing coordination failure."""


@dataclass(frozen=True)
class AgentRecord:
    schemaVersion: int
    agentId: str
    pid: int
    host: str
    platform: str
    user: str
    cwd: str
    repoName: str
    templateId: str | None
    task: str
    tags: tuple[str, ...]
    resources: tuple[str, ...]
    startedAt: str
    updatedAt: str
    ttlSeconds: int

    @property
    def agent_id(self) -> str:
        return self.agentId


@dataclass(frozen=True)
class LeaseRecord:
    schemaVersion: int
    resource: str
    agentId: str
    pid: int
    host: str
    user: str
    cwd: str
    task: str
    acquiredAt: str
    updatedAt: str
    ttlSeconds: int

    @property
    def agent_id(self) -> str:
        return self.agentId


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_time(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def is_expired(updated_at: str, ttl_seconds: int, now: datetime) -> bool:
    return parse_time(updated_at) + timedelta_seconds(ttl_seconds) < now


def timedelta_seconds(seconds: int):
    from datetime import timedelta

    return timedelta(seconds=seconds)


def resolve_state_home(env: dict[str, str], platform_name: str | None = None) -> Path:
    override = env.get("CODEX_AGENT_COORD_HOME")
    if override:
        return Path(override).expanduser()

    platform = platform_name or sys.platform
    if platform.startswith("win"):
        local_app_data = env.get("LOCALAPPDATA")
        if not local_app_data:
            raise CoordinationError("LOCALAPPDATA is required on Windows unless CODEX_AGENT_COORD_HOME is set")
        return Path(str(PureWindowsPath(local_app_data) / "CodexBootstrap" / "agents"))
    if platform == "darwin":
        home = env.get("HOME")
        if not home:
            raise CoordinationError("HOME is required on macOS unless CODEX_AGENT_COORD_HOME is set")
        return Path(home) / "Library" / "Application Support" / "codex-bootstrap" / "agents"

    xdg_state = env.get("XDG_STATE_HOME")
    if xdg_state:
        return Path(xdg_state) / "codex-bootstrap" / "agents"
    home = env.get("HOME")
    if not home:
        raise CoordinationError("HOME is required unless CODEX_AGENT_COORD_HOME is set")
    return Path(home) / ".local" / "state" / "codex-bootstrap" / "agents"


def validate_agent_id(value: str) -> str:
    if not IDENTIFIER_RE.fullmatch(value):
        raise CoordinationError(f"invalid agent id: {value}")
    return value


def validate_resource_name(value: str) -> str:
    if not RESOURCE_RE.fullmatch(value):
        raise CoordinationError(f"invalid resource: {value}")
    return value


def resource_file_name(resource: str) -> str:
    validated = validate_resource_name(resource)
    digest = hashlib.sha256(validated.encode("utf-8")).hexdigest()[:24]
    return f"resource-{digest}.json"


def resolve_agent_identity(
    agent_id: str | None,
    env: dict[str, str],
    cwd: Path,
    host: str | None = None,
    user: str | None = None,
) -> str:
    if agent_id:
        return validate_agent_id(agent_id)
    if env.get("CODEX_AGENT_ID"):
        return validate_agent_id(env["CODEX_AGENT_ID"])
    if env.get("CODEX_SESSION_ID"):
        return validate_agent_id(env["CODEX_SESSION_ID"])

    resolved_host = sanitize_identifier(host or socket.gethostname())
    resolved_user = sanitize_identifier(user or getpass.getuser())
    repo_slug = sanitize_identifier(cwd.name or "repo")
    cwd_hash = hashlib.sha256(str(cwd.resolve()).encode("utf-8")).hexdigest()[:10]
    return validate_agent_id(f"{resolved_host}-{resolved_user}-{repo_slug}-{cwd_hash}")


def sanitize_identifier(value: str) -> str:
    sanitized = "".join(character if character.isalnum() or character in "._:-" else "-" for character in value)
    return sanitized.strip(".-_:") or "agent"


class CoordinationStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.registry_dir = root / "registry"
        self.leases_dir = root / "leases"
        self.locks_dir = root / "locks"
        self.corrupt_dir = root / "corrupt"

    def ensure_dirs(self) -> None:
        for path in (self.registry_dir, self.leases_dir, self.locks_dir, self.corrupt_dir):
            path.mkdir(parents=True, exist_ok=True)

    def announce(
        self,
        agent_id: str,
        cwd: Path,
        task: str,
        tags: tuple[str, ...],
        resources: tuple[str, ...],
        ttl_seconds: int,
        now: datetime,
        pid: int,
        host: str,
        platform_name: str,
        user: str,
    ) -> AgentRecord:
        self.ensure_dirs()
        existing = self._read_agent(agent_id)
        started_at = existing.startedAt if existing else format_time(now)
        record = AgentRecord(
            schemaVersion=SCHEMA_VERSION,
            agentId=agent_id,
            pid=pid,
            host=host,
            platform=platform_name,
            user=user,
            cwd=str(cwd.resolve()),
            repoName=cwd.resolve().name,
            templateId=read_template_id(cwd),
            task=task,
            tags=tuple(tags),
            resources=tuple(validate_resource_name(resource) for resource in resources),
            startedAt=started_at,
            updatedAt=format_time(now),
            ttlSeconds=ttl_seconds,
        )
        atomic_write_json(self.registry_dir / f"{agent_id}.json", record_to_json(record))
        return record

    def read_live_agents(self, now: datetime) -> tuple[list[AgentRecord], list[Path]]:
        self.ensure_dirs()
        records: list[AgentRecord] = []
        corrupt: list[Path] = []
        for path in sorted(self.registry_dir.glob("*.json")):
            try:
                record = agent_record_from_json(read_json(path))
            except (CoordinationError, OSError, json.JSONDecodeError):
                corrupt.append(path)
                move_corrupt(path, self.corrupt_dir)
                continue
            if not is_expired(record.updatedAt, record.ttlSeconds, now):
                records.append(record)
        return records, corrupt

    def cleanup_expired(self, now: datetime) -> tuple[str, ...]:
        self.ensure_dirs()
        removed: list[str] = []
        for path in sorted(self.registry_dir.glob("*.json")):
            try:
                record = agent_record_from_json(read_json(path))
            except (CoordinationError, OSError, json.JSONDecodeError):
                move_corrupt(path, self.corrupt_dir)
                continue
            if is_expired(record.updatedAt, record.ttlSeconds, now):
                path.unlink(missing_ok=True)
                removed.append(record.agent_id)
        return tuple(removed)

    def _read_agent(self, agent_id: str) -> AgentRecord | None:
        path = self.registry_dir / f"{agent_id}.json"
        if not path.is_file():
            return None
        return agent_record_from_json(read_json(path))


def read_template_id(cwd: Path) -> str | None:
    sync_path = cwd / ".codex-bootstrap" / "sync.json"
    if not sync_path.is_file():
        return None
    try:
        payload = read_json(sync_path)
    except (OSError, json.JSONDecodeError):
        return None
    template = payload.get("template")
    if isinstance(template, dict) and isinstance(template.get("id"), str):
        return template["id"]
    return None


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as temp_file:
        json.dump(payload, temp_file, indent=2, sort_keys=True)
        temp_file.write("\n")
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_name = temp_file.name
    os.replace(temp_name, path)


def record_to_json(record: AgentRecord | LeaseRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["tags"] = list(payload.get("tags", []))
    payload["resources"] = list(payload.get("resources", []))
    return payload


def agent_record_from_json(payload: dict[str, Any]) -> AgentRecord:
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise CoordinationError(f"unsupported agent schema: {payload.get('schemaVersion')}")
    return AgentRecord(
        schemaVersion=SCHEMA_VERSION,
        agentId=validate_agent_id(required_string(payload, "agentId")),
        pid=required_int(payload, "pid"),
        host=required_string(payload, "host"),
        platform=required_string(payload, "platform"),
        user=required_string(payload, "user"),
        cwd=required_string(payload, "cwd"),
        repoName=required_string(payload, "repoName"),
        templateId=optional_string(payload, "templateId"),
        task=required_string(payload, "task"),
        tags=tuple(required_string_list(payload, "tags")),
        resources=tuple(validate_resource_name(resource) for resource in required_string_list(payload, "resources")),
        startedAt=required_string(payload, "startedAt"),
        updatedAt=required_string(payload, "updatedAt"),
        ttlSeconds=required_int(payload, "ttlSeconds"),
    )


def required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise CoordinationError(f"{key} must be a string")
    return value


def optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None or isinstance(value, str):
        return value
    raise CoordinationError(f"{key} must be a string or null")


def required_int(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int):
        raise CoordinationError(f"{key} must be an integer")
    return value


def required_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CoordinationError(f"{key} must be an array of strings")
    return value


def move_corrupt(path: Path, corrupt_dir: Path) -> None:
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    target = corrupt_dir / f"{path.name}.{int(time.time())}"
    try:
        shutil.move(str(path), target)
    except OSError:
        pass
