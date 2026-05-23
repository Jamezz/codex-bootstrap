# Agent Coordination Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add advisory-by-default local agent coordination with opt-in serialized resource leases to every Codex Bootstrap generated project on Linux, macOS, and Windows.

**Architecture:** Add a stdlib-only Python tool under `tools/supermeta-agent` that manages a per-user JSON registry and exclusive resource leases with atomic writes and cross-platform file locks. Expose it through Unix and PowerShell wrappers, copy it through every template manifest, and update generated docs from `tools/bootstrap/bootstrap.py` so generated projects inherit the same operator workflow.

**Tech Stack:** Python 3 standard library, `unittest`, shell wrappers, PowerShell wrappers, JSON template manifests, existing bootstrap smoke tests, existing sync-contract managed sets.

---

## File Structure

- Create `tools/supermeta-agent/agent.py`: CLI, state-home resolution, agent identity, JSON registry, exclusive leases, atomic writes, file locking, status rendering, command execution, and exit-code behavior.
- Create `tools/supermeta-agent/agent_test.py`: unit tests for platform paths, identity, resource validation, registry lifecycle, leases, JSON status, corrupt records, and `run` cleanup.
- Create `tools/supermeta-agent/README.md`: generated-project operator docs for `agent-coord`.
- Create `scripts/agent-coord`: Unix wrapper that runs `tools/supermeta-agent/agent.py`.
- Create `scripts/agent-coord.ps1`: PowerShell wrapper that finds Python and runs `tools/supermeta-agent/agent.py`.
- Modify every `templates/*/bootstrap-template.json`: add the new wrappers and support package to support paths and sync managed sets.
- Modify every `templates/*/AGENTS.md`: add template-local command examples for coordination.
- Modify `tools/bootstrap/bootstrap.py`: add generated coordination sections to README, AGENTS, and operations docs.
- Modify `tools/bootstrap/bootstrap_test.py`: assert manifests, generated files, generated docs, and smoke-generated `agent-coord` behavior.
- Modify `README.md`: list the new root wrapper and describe the generated-project coordination surface.
- Modify `tools/supermeta-task/README.md` only if wording must distinguish diagnostics from coordination; otherwise leave it untouched.

## Task 1: Agent Coordination Core Tests

**Files:**
- Create: `tools/supermeta-agent/__init__.py`
- Create: `tools/supermeta-agent/agent_test.py`

- [ ] **Step 1: Add package marker and failing model tests**

Create `tools/supermeta-agent/__init__.py`:

```python
"""Codex Bootstrap local agent coordination helpers."""
```

Create `tools/supermeta-agent/agent_test.py`:

```python
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from unittest.mock import patch

import agent


class StateHomeTest(unittest.TestCase):
    def test_uses_override_state_home(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-home-") as temp_dir:
            env = {"CODEX_AGENT_COORD_HOME": temp_dir}

            self.assertEqual(Path(temp_dir), agent.resolve_state_home(env, platform_name="linux"))

    def test_resolves_linux_state_home_from_xdg(self) -> None:
        env = {"XDG_STATE_HOME": "/tmp/state-home"}

        self.assertEqual(Path("/tmp/state-home/codex-bootstrap/agents"), agent.resolve_state_home(env, platform_name="linux"))

    def test_resolves_linux_state_home_fallback(self) -> None:
        env = {"HOME": "/home/alice"}

        self.assertEqual(Path("/home/alice/.local/state/codex-bootstrap/agents"), agent.resolve_state_home(env, platform_name="linux"))

    def test_resolves_macos_state_home(self) -> None:
        env = {"HOME": "/Users/alice"}

        self.assertEqual(
            Path("/Users/alice/Library/Application Support/codex-bootstrap/agents"),
            agent.resolve_state_home(env, platform_name="darwin"),
        )

    def test_resolves_windows_state_home(self) -> None:
        env = {"LOCALAPPDATA": r"C:\Users\alice\AppData\Local"}

        self.assertEqual(
            Path(r"C:\Users\alice\AppData\Local\CodexBootstrap\agents"),
            agent.resolve_state_home(env, platform_name="win32"),
        )


class IdentityTest(unittest.TestCase):
    def test_agent_id_prefers_cli_value(self) -> None:
        identity = agent.resolve_agent_identity(
            agent_id="cli-agent",
            env={"CODEX_AGENT_ID": "env-agent"},
            cwd=Path("/tmp/repo"),
            host="host",
            user="alice",
        )

        self.assertEqual("cli-agent", identity)

    def test_agent_id_uses_codex_agent_id(self) -> None:
        identity = agent.resolve_agent_identity(
            agent_id=None,
            env={"CODEX_AGENT_ID": "env-agent"},
            cwd=Path("/tmp/repo"),
            host="host",
            user="alice",
        )

        self.assertEqual("env-agent", identity)

    def test_agent_id_uses_codex_session_id(self) -> None:
        identity = agent.resolve_agent_identity(
            agent_id=None,
            env={"CODEX_SESSION_ID": "session-123"},
            cwd=Path("/tmp/repo"),
            host="host",
            user="alice",
        )

        self.assertEqual("session-123", identity)

    def test_fallback_agent_id_is_stable_for_checkout(self) -> None:
        first = agent.resolve_agent_identity(
            agent_id=None,
            env={},
            cwd=Path("/tmp/my-service"),
            host="host",
            user="alice",
        )
        second = agent.resolve_agent_identity(
            agent_id=None,
            env={},
            cwd=Path("/tmp/my-service"),
            host="host",
            user="alice",
        )

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("host-alice-my-service-"))

    def test_rejects_unsafe_agent_id(self) -> None:
        with self.assertRaisesRegex(agent.CoordinationError, "invalid agent id"):
            agent.validate_agent_id("../bad")


class ResourceValidationTest(unittest.TestCase):
    def test_accepts_recommended_resource_names(self) -> None:
        for value in ("perf", "perf:exclusive", "cpu:heavy", "memory:heavy", "docker", "hazeldisk:perf-cluster"):
            with self.subTest(value=value):
                self.assertEqual(value, agent.validate_resource_name(value))

    def test_rejects_unsafe_resource_names(self) -> None:
        for value in ("", "../perf", "perf/exclusive", "perf exclusive", "perf*", ".hidden"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(agent.CoordinationError, "invalid resource"):
                    agent.validate_resource_name(value)

    def test_resource_file_name_is_safe_for_windows(self) -> None:
        self.assertEqual("resource-268dbe08db0de18b979c784d.json", agent.resource_file_name("perf:exclusive"))
        self.assertNotIn(":", agent.resource_file_name("perf:exclusive"))


class RegistryLifecycleTest(unittest.TestCase):
    def test_announces_and_reads_live_agent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-registry-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)

            record = store.announce(
                agent_id="agent-1",
                cwd=Path("/tmp/sample-app"),
                task="perf pass",
                tags=("hazeldisk",),
                resources=("cpu:heavy", "perf"),
                ttl_seconds=900,
                now=now,
                pid=123,
                host="host",
                platform_name="linux",
                user="alice",
            )

            self.assertEqual("agent-1", record.agent_id)
            live_agents, corrupt = store.read_live_agents(now=now + timedelta(seconds=5))
            self.assertEqual([], corrupt)
            self.assertEqual(("agent-1",), tuple(item.agent_id for item in live_agents))
            self.assertEqual(("cpu:heavy", "perf"), live_agents[0].resources)

    def test_stale_agent_records_are_removed_during_cleanup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-stale-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            old = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            store.announce(
                agent_id="stale-agent",
                cwd=Path("/tmp/sample-app"),
                task="old work",
                tags=(),
                resources=("perf",),
                ttl_seconds=10,
                now=old,
                pid=123,
                host="host",
                platform_name="linux",
                user="alice",
            )

            removed = store.cleanup_expired(now=old + timedelta(seconds=30))

            self.assertEqual(("stale-agent",), tuple(removed))
            self.assertFalse((Path(temp_dir) / "registry" / "stale-agent.json").exists())

    def test_corrupt_registry_record_is_ignored_and_moved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-corrupt-") as temp_dir:
            root = Path(temp_dir)
            registry = root / "registry"
            registry.mkdir(parents=True)
            (registry / "bad.json").write_text("{not json", encoding="utf-8")
            store = agent.CoordinationStore(root)

            live_agents, corrupt = store.read_live_agents(now=datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc))

            self.assertEqual([], live_agents)
            self.assertEqual(("bad.json",), tuple(item.name for item in corrupt))
            self.assertTrue(any(path.name.startswith("bad.json") for path in (root / "corrupt").iterdir()))


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run tests and verify the missing module failure**

Run:

```bash
PYTHONPATH=tools/supermeta-agent python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
```

Expected: FAIL with `ModuleNotFoundError: No module named 'agent'`.

- [ ] **Step 3: Commit the failing core tests**

```bash
git add tools/supermeta-agent/__init__.py tools/supermeta-agent/agent_test.py
git commit -m "test: cover agent coordination core"
```

## Task 2: Agent Coordination Core Implementation

**Files:**
- Create: `tools/supermeta-agent/agent.py`
- Test: `tools/supermeta-agent/agent_test.py`

- [ ] **Step 1: Add the core model and filesystem primitives**

Create `tools/supermeta-agent/agent.py`:

```python
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
        return Path(local_app_data) / "CodexBootstrap" / "agents"
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
```

- [ ] **Step 2: Add JSON helpers and template-id discovery**

Append to `tools/supermeta-agent/agent.py`:

```python
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
```

- [ ] **Step 3: Run core tests and verify they pass**

Run:

```bash
PYTHONPATH=tools/supermeta-agent python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 4: Commit the core implementation**

```bash
git add tools/supermeta-agent/agent.py tools/supermeta-agent/agent_test.py
git commit -m "feat: add agent coordination core"
```

## Task 3: Lease and Command Tests

**Files:**
- Modify: `tools/supermeta-agent/agent_test.py`

- [ ] **Step 1: Add lease lifecycle tests**

Append these tests to `tools/supermeta-agent/agent_test.py`:

```python
class LeaseLifecycleTest(unittest.TestCase):
    def test_acquires_free_exclusive_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-lease-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)

            lease = store.acquire_once(
                resource="perf:exclusive",
                agent_id="agent-1",
                cwd=Path("/tmp/sample-app"),
                task="perf pass",
                ttl_seconds=900,
                now=now,
                pid=123,
                host="host",
                user="alice",
            )

            self.assertEqual("perf:exclusive", lease.resource)
            self.assertEqual("agent-1", lease.agent_id)

    def test_reentrant_acquire_by_same_agent_refreshes_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-reentrant-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            first = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            second = first + timedelta(seconds=30)
            store.acquire_once("docker", "agent-1", Path("/tmp/sample-app"), "docker work", 900, first, 123, "host", "alice")

            lease = store.acquire_once("docker", "agent-1", Path("/tmp/sample-app"), "docker work", 900, second, 123, "host", "alice")

            self.assertEqual(agent.format_time(second), lease.updatedAt)

    def test_live_lease_blocks_other_agent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-blocked-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            store.acquire_once("perf:exclusive", "agent-1", Path("/tmp/one"), "first", 900, now, 123, "host", "alice")

            with self.assertRaisesRegex(agent.LeaseUnavailable, "perf:exclusive is held by agent-1"):
                store.acquire_once("perf:exclusive", "agent-2", Path("/tmp/two"), "second", 900, now, 456, "host", "alice")

    def test_expired_lease_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-expired-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            first = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            second = first + timedelta(seconds=30)
            store.acquire_once("perf:exclusive", "agent-1", Path("/tmp/one"), "first", 10, first, 123, "host", "alice")

            lease = store.acquire_once("perf:exclusive", "agent-2", Path("/tmp/two"), "second", 900, second, 456, "host", "alice")

            self.assertEqual("agent-2", lease.agent_id)

    def test_release_removes_owned_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-release-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            store.acquire_once("docker", "agent-1", Path("/tmp/sample-app"), "docker work", 900, now, 123, "host", "alice")

            released = store.release(("docker",), "agent-1")

            self.assertEqual(("docker",), tuple(released))
            self.assertFalse((Path(temp_dir) / "leases" / agent.resource_file_name("docker")).exists())

    def test_release_all_removes_all_owned_leases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-release-all-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            store.acquire_once("docker", "agent-1", Path("/tmp/sample-app"), "work", 900, now, 123, "host", "alice")
            store.acquire_once("perf:exclusive", "agent-1", Path("/tmp/sample-app"), "work", 900, now, 123, "host", "alice")

            released = store.release_all("agent-1")

            self.assertEqual(("docker", "perf:exclusive"), tuple(sorted(released)))
```

- [ ] **Step 2: Add CLI behavior tests**

Append these tests:

```python
class CliBehaviorTest(unittest.TestCase):
    def test_status_json_reports_agents_and_leases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-status-") as temp_dir:
            output = agent.run_cli(
                [
                    "--state-home",
                    temp_dir,
                    "--agent-id",
                    "agent-1",
                    "announce",
                    "--task",
                    "perf pass",
                    "--resource",
                    "perf",
                ],
                cwd=Path(temp_dir),
                env={},
                stdout=None,
            )
            self.assertEqual(0, output)

            captured = agent.CapturedOutput()
            exit_code = agent.run_cli(["--state-home", temp_dir, "status", "--json"], cwd=Path(temp_dir), env={}, stdout=captured)

            self.assertEqual(0, exit_code)
            payload = json.loads(captured.text)
            self.assertEqual(["agent-1"], [item["agentId"] for item in payload["agents"]])
            self.assertEqual([], payload["leases"])

    def test_acquire_timeout_returns_75(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-timeout-") as temp_dir:
            first = agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-1", "acquire", "--resource", "docker"],
                cwd=Path(temp_dir),
                env={},
                stdout=None,
            )
            second = agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-2", "acquire", "--resource", "docker", "--timeout", "0s"],
                cwd=Path(temp_dir),
                env={},
                stdout=None,
            )

            self.assertEqual(0, first)
            self.assertEqual(agent.ACQUIRE_TIMEOUT_EXIT, second)

    def test_leave_removes_agent_and_owned_leases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-leave-") as temp_dir:
            agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-1", "announce", "--task", "work", "--resource", "docker"],
                cwd=Path(temp_dir),
                env={},
                stdout=None,
            )
            agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-1", "acquire", "--resource", "docker"],
                cwd=Path(temp_dir),
                env={},
                stdout=None,
            )

            exit_code = agent.run_cli(["--state-home", temp_dir, "--agent-id", "agent-1", "leave"], cwd=Path(temp_dir), env={}, stdout=None)

            self.assertEqual(0, exit_code)
            self.assertFalse((Path(temp_dir) / "registry" / "agent-1.json").exists())
            self.assertFalse((Path(temp_dir) / "leases" / agent.resource_file_name("docker")).exists())

    def test_run_returns_child_exit_code_and_releases_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-run-") as temp_dir:
            command = [
                sys.executable,
                "-c",
                "import sys; sys.exit(7)",
            ]

            exit_code = agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-1", "run", "--resource", "perf:exclusive", "--", *command],
                cwd=Path(temp_dir),
                env={},
                stdout=None,
            )

            self.assertEqual(7, exit_code)
            self.assertFalse((Path(temp_dir) / "leases" / agent.resource_file_name("perf:exclusive")).exists())
```

- [ ] **Step 3: Run tests and verify missing lease methods fail**

Run:

```bash
PYTHONPATH=tools/supermeta-agent python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
```

Expected: FAIL with `AttributeError` for `acquire_once` or `run_cli`.

- [ ] **Step 4: Commit the failing lease and CLI tests**

```bash
git add tools/supermeta-agent/agent_test.py
git commit -m "test: cover agent coordination leases"
```

## Task 4: Lease and CLI Implementation

**Files:**
- Modify: `tools/supermeta-agent/agent.py`
- Test: `tools/supermeta-agent/agent_test.py`

- [ ] **Step 1: Add lease records and locking**

Append to `tools/supermeta-agent/agent.py`:

```python
class LeaseUnavailable(CoordinationError):
    """Raised when a resource is already leased by another live agent."""


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.handle = None

    def __enter__(self) -> FileLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handle = self.path.open("a+", encoding="utf-8")
        if fcntl is not None:
            fcntl.flock(self.handle, fcntl.LOCK_EX)
        elif msvcrt is not None:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            raise CoordinationError("file locking is unavailable on this platform")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self.handle is None:
            return
        if fcntl is not None:
            fcntl.flock(self.handle, fcntl.LOCK_UN)
        elif msvcrt is not None:
            self.handle.seek(0)
            msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
        self.handle.close()


def lease_record_from_json(payload: dict[str, Any]) -> LeaseRecord:
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        raise CoordinationError(f"unsupported lease schema: {payload.get('schemaVersion')}")
    return LeaseRecord(
        schemaVersion=SCHEMA_VERSION,
        resource=validate_resource_name(required_string(payload, "resource")),
        agentId=validate_agent_id(required_string(payload, "agentId")),
        pid=required_int(payload, "pid"),
        host=required_string(payload, "host"),
        user=required_string(payload, "user"),
        cwd=required_string(payload, "cwd"),
        task=required_string(payload, "task"),
        acquiredAt=required_string(payload, "acquiredAt"),
        updatedAt=required_string(payload, "updatedAt"),
        ttlSeconds=required_int(payload, "ttlSeconds"),
    )
```

Add these methods inside `CoordinationStore`:

```python
    def acquire_once(
        self,
        resource: str,
        agent_id: str,
        cwd: Path,
        task: str,
        ttl_seconds: int,
        now: datetime,
        pid: int,
        host: str,
        user: str,
    ) -> LeaseRecord:
        resource = validate_resource_name(resource)
        self.ensure_dirs()
        with FileLock(self.locks_dir / "leases.lock"):
            path = self.leases_dir / resource_file_name(resource)
            existing = self._read_lease(path)
            if existing and not is_expired(existing.updatedAt, existing.ttlSeconds, now) and existing.agent_id != agent_id:
                raise LeaseUnavailable(f"{resource} is held by {existing.agent_id} from {existing.cwd}: {existing.task}")
            acquired_at = existing.acquiredAt if existing and existing.agent_id == agent_id else format_time(now)
            lease = LeaseRecord(
                schemaVersion=SCHEMA_VERSION,
                resource=resource,
                agentId=agent_id,
                pid=pid,
                host=host,
                user=user,
                cwd=str(cwd.resolve()),
                task=task,
                acquiredAt=acquired_at,
                updatedAt=format_time(now),
                ttlSeconds=ttl_seconds,
            )
            atomic_write_json(path, record_to_json(lease))
            return lease

    def release(self, resources: tuple[str, ...], agent_id: str) -> tuple[str, ...]:
        self.ensure_dirs()
        released: list[str] = []
        with FileLock(self.locks_dir / "leases.lock"):
            for resource in resources:
                path = self.leases_dir / resource_file_name(resource)
                lease = self._read_lease(path)
                if lease and lease.agent_id == agent_id:
                    path.unlink(missing_ok=True)
                    released.append(resource)
        return tuple(released)

    def release_all(self, agent_id: str) -> tuple[str, ...]:
        self.ensure_dirs()
        released: list[str] = []
        with FileLock(self.locks_dir / "leases.lock"):
            for path in sorted(self.leases_dir.glob("*.json")):
                lease = self._read_lease(path)
                if lease and lease.agent_id == agent_id:
                    path.unlink(missing_ok=True)
                    released.append(lease.resource)
        return tuple(released)

    def remove_agent(self, agent_id: str) -> None:
        self.ensure_dirs()
        (self.registry_dir / f"{validate_agent_id(agent_id)}.json").unlink(missing_ok=True)

    def read_live_leases(self, now: datetime) -> tuple[list[LeaseRecord], list[Path]]:
        self.ensure_dirs()
        leases: list[LeaseRecord] = []
        corrupt: list[Path] = []
        for path in sorted(self.leases_dir.glob("*.json")):
            try:
                lease = lease_record_from_json(read_json(path))
            except (CoordinationError, OSError, json.JSONDecodeError):
                corrupt.append(path)
                move_corrupt(path, self.corrupt_dir)
                continue
            if not is_expired(lease.updatedAt, lease.ttlSeconds, now):
                leases.append(lease)
        return leases, corrupt

    def _read_lease(self, path: Path) -> LeaseRecord | None:
        if not path.is_file():
            return None
        return lease_record_from_json(read_json(path))
```

Replace the write section of `CoordinationStore.announce()` so registry updates use the registry lock:

```python
        with FileLock(self.locks_dir / "registry.lock"):
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
```

Replace `remove_agent()` with a locked version:

```python
    def remove_agent(self, agent_id: str) -> None:
        self.ensure_dirs()
        with FileLock(self.locks_dir / "registry.lock"):
            (self.registry_dir / f"{validate_agent_id(agent_id)}.json").unlink(missing_ok=True)
```

- [ ] **Step 2: Add argument parsing and command dispatch**

Append:

```python
class CapturedOutput:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> None:
        self.parts.append(text)

    @property
    def text(self) -> str:
        return "".join(self.parts)


def parse_duration(value: str) -> int:
    if value.endswith("ms"):
        return max(1, int(value[:-2]) // 1000)
    if value.endswith("s"):
        return int(value[:-1])
    if value.endswith("m"):
        return int(value[:-1]) * 60
    if value.endswith("h"):
        return int(value[:-1]) * 3600
    return int(value)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Coordinate local Codex agents.")
    parser.add_argument("--state-home", type=Path, help="Override coordination state directory.")
    parser.add_argument("--agent-id", help="Override agent identity.")
    parser.add_argument("--ttl", default=os.environ.get("CODEX_AGENT_COORD_TTL_SECONDS", str(DEFAULT_TTL_SECONDS)))
    subparsers = parser.add_subparsers(dest="command", required=True)

    announce = subparsers.add_parser("announce", help="Advertise this agent's current work.")
    announce.add_argument("--task", default="unspecified")
    announce.add_argument("--tag", action="append", default=[])
    announce.add_argument("--resource", action="append", default=[])
    announce.add_argument("--json", action="store_true")

    status = subparsers.add_parser("status", help="Show live agents and leases.")
    status.add_argument("--json", action="store_true")

    leave = subparsers.add_parser("leave", help="Remove this agent and release its leases.")
    leave.add_argument("--json", action="store_true")

    acquire = subparsers.add_parser("acquire", help="Acquire exclusive resource leases.")
    acquire.add_argument("--resource", action="append", required=True)
    acquire.add_argument("--timeout", default="0s")
    acquire.add_argument("--task", default="lease")
    acquire.add_argument("--json", action="store_true")

    release = subparsers.add_parser("release", help="Release exclusive resource leases.")
    release.add_argument("--resource", action="append", default=[])
    release.add_argument("--all", action="store_true")
    release.add_argument("--json", action="store_true")

    run = subparsers.add_parser("run", help="Acquire leases, run a command, then release leases.")
    run.add_argument("--resource", action="append", required=True)
    run.add_argument("--timeout", default="0s")
    run.add_argument("--task", default="serialized command")
    run.add_argument("child_command", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def run_cli(argv: list[str], cwd: Path | None = None, env: dict[str, str] | None = None, stdout=None) -> int:
    args = parse_args(argv)
    resolved_env = os.environ.copy()
    if env is not None:
        resolved_env.update(env)
    project_dir = (cwd or Path.cwd()).resolve()
    state_home = args.state_home or resolve_state_home(resolved_env)
    store = CoordinationStore(state_home)
    now = utc_now()
    ttl_seconds = parse_duration(str(args.ttl))
    host = socket.gethostname()
    user = getpass.getuser()
    agent_id = resolve_agent_identity(args.agent_id, resolved_env, project_dir, host=host, user=user)
    output = stdout or sys.stdout

    try:
        if args.command == "announce":
            record = store.announce(agent_id, project_dir, args.task, tuple(args.tag), tuple(args.resource), ttl_seconds, now, os.getpid(), host, sys.platform, user)
            return print_payload({"agent": record_to_json(record)}, args.json, output)
        if args.command == "status":
            return print_status(store, now, args.json, output)
        if args.command == "leave":
            released = store.release_all(agent_id)
            store.remove_agent(agent_id)
            return print_payload({"agentId": agent_id, "released": list(released)}, args.json, output)
        if args.command == "acquire":
            return acquire_with_timeout(store, tuple(args.resource), agent_id, project_dir, args.task, ttl_seconds, parse_duration(args.timeout), output, args.json)
        if args.command == "release":
            released = store.release_all(agent_id) if args.all else store.release(tuple(args.resource), agent_id)
            return print_payload({"agentId": agent_id, "released": list(released)}, args.json, output)
        if args.command == "run":
            return run_child_with_leases(store, args, agent_id, project_dir, ttl_seconds, output)
    except LeaseUnavailable as error:
        print(f"agent-coord: {error}", file=sys.stderr)
        return ACQUIRE_TIMEOUT_EXIT
    except CoordinationError as error:
        print(f"agent-coord: {error}", file=sys.stderr)
        return 2
    return 2
```

- [ ] **Step 3: Add status, acquire, run, and main helpers**

Append:

```python
def print_payload(payload: dict[str, Any], as_json: bool, output) -> int:
    if as_json:
        output.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    else:
        output.write("agent-coord: ok\n")
    return 0


def print_status(store: CoordinationStore, now: datetime, as_json: bool, output) -> int:
    store.cleanup_expired(now)
    agents, corrupt_agents = store.read_live_agents(now)
    leases, corrupt_leases = store.read_live_leases(now)
    payload = {
        "agents": [record_to_json(record) for record in agents],
        "leases": [record_to_json(lease) for lease in leases],
        "corrupt": [path.name for path in [*corrupt_agents, *corrupt_leases]],
    }
    if as_json:
        output.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
        return 0

    output.write("agent-coord: live agents\n")
    if not agents:
        output.write("  none\n")
    for record in agents:
        resources = ", ".join(record.resources) if record.resources else "-"
        output.write(f"  {record.agentId} {record.repoName} {resources} {record.task}\n")
    output.write("agent-coord: live leases\n")
    if not leases:
        output.write("  none\n")
    for lease in leases:
        output.write(f"  {lease.resource} held by {lease.agentId} {lease.cwd} {lease.task}\n")
    if payload["corrupt"]:
        output.write(f"agent-coord: ignored corrupt records: {', '.join(payload['corrupt'])}\n")
    return 0


def acquire_with_timeout(
    store: CoordinationStore,
    resources: tuple[str, ...],
    agent_id: str,
    cwd: Path,
    task: str,
    ttl_seconds: int,
    timeout_seconds: int,
    output,
    as_json: bool,
) -> int:
    deadline = time.monotonic() + timeout_seconds
    while True:
        acquired: list[LeaseRecord] = []
        try:
            for resource in resources:
                acquired.append(
                    store.acquire_once(resource, agent_id, cwd, task, ttl_seconds, utc_now(), os.getpid(), socket.gethostname(), getpass.getuser())
                )
            return print_payload({"leases": [record_to_json(lease) for lease in acquired]}, as_json, output)
        except LeaseUnavailable as error:
            if acquired:
                store.release(tuple(lease.resource for lease in acquired), agent_id)
            if time.monotonic() >= deadline:
                print(f"agent-coord: {error}", file=sys.stderr)
                return ACQUIRE_TIMEOUT_EXIT
            time.sleep(min(1.0, max(0.1, deadline - time.monotonic())))


def run_child_with_leases(store: CoordinationStore, args: argparse.Namespace, agent_id: str, cwd: Path, ttl_seconds: int, output) -> int:
    child_command = list(args.child_command)
    if child_command and child_command[0] == "--":
        child_command = child_command[1:]
    if not child_command:
        raise CoordinationError("run requires a child command after --")

    acquire_exit = acquire_with_timeout(store, tuple(args.resource), agent_id, cwd, args.task, ttl_seconds, parse_duration(args.timeout), output, False)
    if acquire_exit != 0:
        return acquire_exit
    store.announce(agent_id, cwd, args.task, (), tuple(args.resource), ttl_seconds, utc_now(), os.getpid(), socket.gethostname(), sys.platform, getpass.getuser())
    try:
        process = subprocess.Popen(child_command, cwd=cwd)
        heartbeat_seconds = max(1.0, min(30.0, ttl_seconds / 3))
        while True:
            exit_code = process.poll()
            if exit_code is not None:
                return exit_code
            now = utc_now()
            for resource in args.resource:
                store.acquire_once(resource, agent_id, cwd, args.task, ttl_seconds, now, os.getpid(), socket.gethostname(), getpass.getuser())
            store.announce(agent_id, cwd, args.task, (), tuple(args.resource), ttl_seconds, now, os.getpid(), socket.gethostname(), sys.platform, getpass.getuser())
            time.sleep(heartbeat_seconds)
    finally:
        store.release(tuple(args.resource), agent_id)


def main() -> int:
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tool tests**

Run:

```bash
PYTHONPATH=tools/supermeta-agent python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 5: Commit lease and CLI implementation**

```bash
git add tools/supermeta-agent/agent.py tools/supermeta-agent/agent_test.py
git commit -m "feat: add agent coordination leases"
```

## Task 5: Wrappers and Tool Documentation

**Files:**
- Create: `scripts/agent-coord`
- Create: `scripts/agent-coord.ps1`
- Create: `tools/supermeta-agent/README.md`
- Test: `tools/supermeta-agent/agent_test.py`

- [ ] **Step 1: Add Unix wrapper**

Create `scripts/agent-coord`:

```sh
#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd "$script_dir/.." && pwd)

exec python3 "$repo_root/tools/supermeta-agent/agent.py" "$@"
```

Run:

```bash
chmod +x scripts/agent-coord
```

- [ ] **Step 2: Add PowerShell wrapper**

Create `scripts/agent-coord.ps1`:

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-PythonChecked {
    $PythonArgs = @($args)

    $python = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        exit $LASTEXITCODE
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        exit $LASTEXITCODE
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 @PythonArgs
        exit $LASTEXITCODE
    }

    [Console]::Error.WriteLine("scripts/agent-coord.ps1: python3, python, or py is required")
    exit 2
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$coordScript = Join-Path $repoRoot "tools/supermeta-agent/agent.py"
$pythonArgs = @($coordScript)
$pythonArgs += $args
Invoke-PythonChecked @pythonArgs
```

- [ ] **Step 3: Add README**

Create `tools/supermeta-agent/README.md`:

```markdown
# Supermeta Agent Coordination

Shared local coordination for generated projects. The tool is advisory by default: agents can announce their work and inspect other live agents without blocking ordinary checks.

```bash
./scripts/agent-coord announce --task "perf pass" --resource cpu:heavy --resource perf
./scripts/agent-coord status
./scripts/agent-coord leave
```

Use `run` when a command should serialize on an exclusive local resource:

```bash
./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check
```

Windows PowerShell:

```powershell
.\scripts\agent-coord.ps1 status
.\scripts\agent-coord.ps1 run --resource perf:exclusive -- .\scripts\check.ps1
```

State is per-user:

- Linux: `$XDG_STATE_HOME/codex-bootstrap/agents`, or `~/.local/state/codex-bootstrap/agents`.
- macOS: `~/Library/Application Support/codex-bootstrap/agents`.
- Windows: `%LOCALAPPDATA%\CodexBootstrap\agents`.

Set `CODEX_AGENT_COORD_HOME` when several agents should coordinate through a shared directory. Set `CODEX_AGENT_ID` when multiple sessions in the same checkout should keep separate registry records.
```

- [ ] **Step 4: Smoke the wrappers**

Run:

```bash
./scripts/agent-coord --state-home /tmp/codex-bootstrap-agent-coord-smoke status
```

Expected: exit 0 and output includes `agent-coord: live agents`.

Run:

```bash
./scripts/agent-coord --state-home /tmp/codex-bootstrap-agent-coord-smoke --agent-id smoke-agent announce --task smoke --resource cpu:heavy
./scripts/agent-coord --state-home /tmp/codex-bootstrap-agent-coord-smoke status --json
./scripts/agent-coord --state-home /tmp/codex-bootstrap-agent-coord-smoke --agent-id smoke-agent leave
```

Expected: all exit 0; JSON status includes `smoke-agent` after announce.

- [ ] **Step 5: Run tests and commit wrappers**

Run:

```bash
PYTHONPATH=tools/supermeta-agent python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
```

Expected: PASS.

Commit:

```bash
git add scripts/agent-coord scripts/agent-coord.ps1 tools/supermeta-agent/README.md
git commit -m "feat: add agent coordination wrappers"
```

## Task 6: Template Manifest Propagation

**Files:**
- Modify: `templates/csharp-dotnet-cli/bootstrap-template.json`
- Modify: `templates/java-gradle-cli/bootstrap-template.json`
- Modify: `templates/python-uv-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-mcp-server/bootstrap-template.json`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add manifest tests for copied support paths**

In each `ManifestTest` expected support path list in `tools/bootstrap/bootstrap_test.py`, add these entries next to `scripts/agent-task`:

```python
"scripts/agent-coord",
"scripts/agent-coord.ps1",
```

In each list that includes `tools/supermeta-task`, add:

```python
"tools/supermeta-agent",
```

In the Java manifest sync assertions, add:

```python
self.assertIn("scripts/agent-coord", manifest.sync_contract.managed_files)
self.assertIn("tools/supermeta-agent/agent.py", manifest.sync_contract.managed_files)
```

Add equivalent assertions for the other four manifests after their support path assertions:

```python
self.assertIn("scripts/agent-coord", manifest.sync_contract.managed_files)
self.assertIn("tools/supermeta-agent/agent.py", manifest.sync_contract.managed_files)
```

- [ ] **Step 2: Run bootstrap tests and verify manifest failures**

Run:

```bash
python3 -m unittest tools.bootstrap.bootstrap_test.ManifestTest
```

Expected: FAIL because manifests do not yet list `agent-coord` or `tools/supermeta-agent`.

- [ ] **Step 3: Update all template manifests**

In every `templates/*/bootstrap-template.json`, add support paths:

```json
{
  "source": "scripts/agent-coord",
  "destination": "scripts/agent-coord"
},
{
  "source": "scripts/agent-coord.ps1",
  "destination": "scripts/agent-coord.ps1"
},
{
  "source": "tools/supermeta-agent",
  "destination": "tools/supermeta-agent"
}
```

In every `syncContract.managedSets` entry with id `agent-scripts`, add files:

```json
{
  "path": "scripts/agent-coord",
  "mode": "whole-file"
},
{
  "path": "scripts/agent-coord.ps1",
  "mode": "whole-file"
}
```

In every `syncContract.managedSets` entry with id `supermeta-tools`, add files:

```json
{
  "path": "tools/supermeta-agent/agent.py",
  "mode": "whole-file"
},
{
  "path": "tools/supermeta-agent/agent_test.py",
  "mode": "whole-file"
},
{
  "path": "tools/supermeta-agent/README.md",
  "mode": "whole-file"
}
```

- [ ] **Step 4: Run manifest tests**

Run:

```bash
python3 -m unittest tools.bootstrap.bootstrap_test.ManifestTest
```

Expected: PASS.

- [ ] **Step 5: Commit manifest propagation**

```bash
git add templates/*/bootstrap-template.json tools/bootstrap/bootstrap_test.py
git commit -m "feat: copy agent coordination into templates"
```

## Task 7: Generated Docs and Template Agent Notes

**Files:**
- Modify: `tools/bootstrap/bootstrap.py`
- Modify: `templates/csharp-dotnet-cli/AGENTS.md`
- Modify: `templates/java-gradle-cli/AGENTS.md`
- Modify: `templates/python-uv-cli/AGENTS.md`
- Modify: `templates/typescript-bun-cli/AGENTS.md`
- Modify: `templates/typescript-bun-mcp-server/AGENTS.md`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add generated-doc tests**

In `BootstrapSmokeTest.test_bootstrap_rewrites_checkout_into_standalone_project`, after existing support path assertions, add:

```python
self.assertTrue((checkout / "scripts" / "agent-coord").is_file())
self.assertTrue((checkout / "scripts" / "agent-coord.ps1").is_file())
self.assertTrue((checkout / "tools" / "supermeta-agent" / "agent.py").is_file())
```

In the generated README assertion block, add:

```python
self.assertIn("./scripts/agent-coord status", readme)
self.assertIn("./scripts/agent-coord run --resource perf:exclusive -- ./scripts/agent-gradle . check", readme)
self.assertIn(".\\scripts\\agent-coord.ps1 status", readme)
```

In the generated AGENTS assertion block, add:

```python
self.assertIn("./scripts/agent-coord announce --task", agents)
self.assertIn("./scripts/agent-coord status", agents)
self.assertIn("./scripts/agent-coord run --resource perf:exclusive", agents)
```

In the generated operations docs assertion block, add:

```python
operations = (checkout / "docs" / "OPERATIONS.md").read_text(encoding="utf-8")
self.assertIn("## Agent Coordination", operations)
self.assertIn("CODEX_AGENT_COORD_HOME", operations)
```

- [ ] **Step 2: Run bootstrap smoke test and verify doc failures**

Run:

```bash
python3 -m unittest tools.bootstrap.bootstrap_test.BootstrapSmokeTest.test_bootstrap_rewrites_checkout_into_standalone_project
```

Expected: FAIL because generated docs do not yet mention `agent-coord`.

- [ ] **Step 3: Add generated coordination section helpers**

In `tools/bootstrap/bootstrap.py`, add these helpers near the existing generated agent helper sections:

```python
def generated_agent_coordination_readme_section(check_command_text: str) -> str:
    return f"""## Agent Coordination

Advertise work when several local agents may share machine resources:

```bash
./scripts/agent-coord announce --task "verification" --resource cpu:heavy
./scripts/agent-coord status
```

Serialize sensitive work explicitly:

```bash
./scripts/agent-coord run --resource perf:exclusive -- {check_command_text}
```

PowerShell:

```powershell
.\\scripts\\agent-coord.ps1 status
```

The tool is advisory unless `run` or `acquire` is used. Set `CODEX_AGENT_COORD_HOME` when agents should coordinate through a shared directory.
"""


def generated_agent_coordination_agent_section(check_command_text: str) -> str:
    return f"""## Agent Coordination

- Announce substantial work: `./scripts/agent-coord announce --task "short task name" --resource cpu:heavy`
- Inspect peers: `./scripts/agent-coord status`
- Serialize resource-sensitive work: `./scripts/agent-coord run --resource perf:exclusive -- {check_command_text}`
- Release this session when done: `./scripts/agent-coord leave`
- Use `CODEX_AGENT_COORD_HOME` for shared coordination across non-default locations.
"""
```

Add this operations helper:

```python
def generated_agent_coordination_operations_section(check_command_text: str) -> str:
    return f"""## Agent Coordination

```bash
./scripts/agent-coord status
./scripts/agent-coord run --resource perf:exclusive -- {check_command_text}
```

State locations:

- Linux: `$XDG_STATE_HOME/codex-bootstrap/agents`, or `~/.local/state/codex-bootstrap/agents`.
- macOS: `~/Library/Application Support/codex-bootstrap/agents`.
- Windows: `%LOCALAPPDATA%\\CodexBootstrap\\agents`.

Set `CODEX_AGENT_COORD_HOME` to coordinate through a specific directory. Use `./scripts/agent-coord leave` to remove the current agent record and release leases. Stale records expire through TTL cleanup.
"""
```

Insert `{generated_agent_coordination_readme_section(check_command(plan))}` after the stuck-task section in generated README output. Insert `{generated_agent_coordination_agent_section(check_command(plan))}` after each generated command list in generated AGENTS output. Insert `{generated_agent_coordination_operations_section(check_command(plan))}` after the Backlog section in `generated_operations()`.

- [ ] **Step 4: Update template-local AGENTS files**

In each `templates/*/AGENTS.md` command list, add:

```markdown
- Announce coordination state: `./scripts/agent-coord announce --task "verification" --resource cpu:heavy`
- Inspect peer agents: `./scripts/agent-coord status`
- Serialize perf-sensitive work: `./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check`
```

For `templates/java-gradle-cli/AGENTS.md`, use the Java verification command:

```markdown
- Serialize perf-sensitive work: `./scripts/agent-coord run --resource perf:exclusive -- ./scripts/agent-gradle templates/java-gradle-cli check`
```

In each Windows section, add:

```markdown
- Inspect peer agents: `.\scripts\agent-coord.ps1 status`
```

- [ ] **Step 5: Run bootstrap smoke test**

Run:

```bash
python3 -m unittest tools.bootstrap.bootstrap_test.BootstrapSmokeTest.test_bootstrap_rewrites_checkout_into_standalone_project
```

Expected: PASS.

- [ ] **Step 6: Commit generated docs**

```bash
git add tools/bootstrap/bootstrap.py tools/bootstrap/bootstrap_test.py templates/*/AGENTS.md
git commit -m "docs: document agent coordination workflow"
```

## Task 8: Root README and End-to-End Verification Tests

**Files:**
- Modify: `README.md`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add generated wrapper smoke assertions**

In `BootstrapSmokeTest.test_bootstrap_rewrites_checkout_into_standalone_project`, after existing generated wrapper smoke commands, add:

```python
coord_home = checkout / ".tmp-agent-coord"
run_checked(
    [
        "./scripts/agent-coord",
        "--state-home",
        str(coord_home),
        "--agent-id",
        "bootstrap-smoke",
        "announce",
        "--task",
        "bootstrap smoke",
        "--resource",
        "cpu:heavy",
    ],
    cwd=checkout,
    timeout=120,
)
status = run_checked(
    [
        "./scripts/agent-coord",
        "--state-home",
        str(coord_home),
        "status",
        "--json",
    ],
    cwd=checkout,
    timeout=120,
)
self.assertIn("bootstrap-smoke", status.stdout)
run_checked(
    [
        "./scripts/agent-coord",
        "--state-home",
        str(coord_home),
        "--agent-id",
        "bootstrap-smoke",
        "leave",
    ],
    cwd=checkout,
    timeout=120,
)
```

- [ ] **Step 2: Update root README**

In `README.md`, add `scripts/agent-coord` and `scripts/agent-coord.ps1` to the shipped wrapper list:

```markdown
- `scripts/agent-coord` and `scripts/agent-coord.ps1`: advisory local agent coordination with opt-in serialized resource leases.
```

Add a short generated-project operations section after "Resync Generated Projects":

```markdown
## Coordinate Local Agents

Generated projects include advisory coordination for parallel local agents:

```bash
./scripts/agent-coord announce --task "perf pass" --resource cpu:heavy
./scripts/agent-coord status
./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check
```

PowerShell:

```powershell
.\scripts\agent-coord.ps1 status
```

The tool stores per-user state on Linux, macOS, and Windows and only serializes work when `run` or `acquire` is used.
```

- [ ] **Step 3: Run bootstrap smoke test**

Run:

```bash
python3 -m unittest tools.bootstrap.bootstrap_test.BootstrapSmokeTest.test_bootstrap_rewrites_checkout_into_standalone_project
```

Expected: PASS.

- [ ] **Step 4: Commit root docs and smoke proof**

```bash
git add README.md tools/bootstrap/bootstrap_test.py
git commit -m "test: smoke generated agent coordination"
```

## Task 9: Full Verification and Cleanup

**Files:**
- Verify all changed files

- [ ] **Step 1: Run focused agent tests**

Run:

```bash
PYTHONPATH=tools/supermeta-agent python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 2: Run bootstrap tests**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 3: Run all tool tests**

Run:

```bash
python3 -m unittest discover -s tools -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 4: Check shell syntax**

Run:

```bash
bash -n scripts/agent-coord
```

Expected: no output and exit 0.

- [ ] **Step 5: Run coordination smoke through serialization**

Run:

```bash
rm -rf /tmp/codex-bootstrap-agent-coord-final
./scripts/agent-coord --state-home /tmp/codex-bootstrap-agent-coord-final --agent-id final-smoke run --resource perf:exclusive -- python3 -c 'print("serialized")'
./scripts/agent-coord --state-home /tmp/codex-bootstrap-agent-coord-final status --json
```

Expected: first command prints `serialized` and exits 0. Second command exits 0 and has no live lease for `perf:exclusive`.

- [ ] **Step 6: Inspect git diff**

Run:

```bash
git status --short
git diff --check
```

Expected: only intentional files are modified, and `git diff --check` exits 0.

- [ ] **Step 7: Commit verification adjustments if needed**

If verification required fixes, commit only those fixes:

```bash
git add <fixed-files>
git commit -m "fix: stabilize agent coordination verification"
```

If no fixes were required, do not create an empty commit.
