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


class LeaseUnavailable(CoordinationError):
    """Raised when a resource is already leased by another live agent."""


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
        with FileLock(self.locks_dir / "registry.lock"):
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
    if "tags" in payload:
        payload["tags"] = list(payload["tags"])
    if "resources" in payload:
        payload["resources"] = list(payload["resources"])
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
            record = store.announce(
                agent_id,
                project_dir,
                args.task,
                tuple(args.tag),
                tuple(args.resource),
                ttl_seconds,
                now,
                os.getpid(),
                host,
                sys.platform,
                user,
            )
            return print_payload({"agent": record_to_json(record)}, args.json, output)
        if args.command == "status":
            return print_status(store, now, args.json, output)
        if args.command == "leave":
            released = store.release_all(agent_id)
            store.remove_agent(agent_id)
            return print_payload({"agentId": agent_id, "released": list(released)}, args.json, output)
        if args.command == "acquire":
            return acquire_with_timeout(
                store,
                tuple(args.resource),
                agent_id,
                project_dir,
                args.task,
                ttl_seconds,
                parse_duration(args.timeout),
                output,
                args.json,
            )
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
                    store.acquire_once(
                        resource,
                        agent_id,
                        cwd,
                        task,
                        ttl_seconds,
                        utc_now(),
                        os.getpid(),
                        socket.gethostname(),
                        getpass.getuser(),
                    )
                )
            return print_payload({"leases": [record_to_json(lease) for lease in acquired]}, as_json, output)
        except LeaseUnavailable as error:
            if acquired:
                store.release(tuple(lease.resource for lease in acquired), agent_id)
            if time.monotonic() >= deadline:
                print(f"agent-coord: {error}", file=sys.stderr)
                return ACQUIRE_TIMEOUT_EXIT
            time.sleep(min(1.0, max(0.1, deadline - time.monotonic())))


def run_child_with_leases(
    store: CoordinationStore,
    args: argparse.Namespace,
    agent_id: str,
    cwd: Path,
    ttl_seconds: int,
    output,
) -> int:
    child_command = list(args.child_command)
    if child_command and child_command[0] == "--":
        child_command = child_command[1:]
    if not child_command:
        raise CoordinationError("run requires a child command after --")

    acquire_exit = acquire_with_timeout(
        store,
        tuple(args.resource),
        agent_id,
        cwd,
        args.task,
        ttl_seconds,
        parse_duration(args.timeout),
        output,
        False,
    )
    if acquire_exit != 0:
        return acquire_exit
    store.announce(
        agent_id,
        cwd,
        args.task,
        (),
        tuple(args.resource),
        ttl_seconds,
        utc_now(),
        os.getpid(),
        socket.gethostname(),
        sys.platform,
        getpass.getuser(),
    )
    try:
        process = subprocess.Popen(child_command, cwd=cwd)
        heartbeat_seconds = max(1.0, min(30.0, ttl_seconds / 3))
        while True:
            try:
                return process.wait(timeout=heartbeat_seconds)
            except subprocess.TimeoutExpired:
                now = utc_now()
                for resource in args.resource:
                    store.acquire_once(
                        resource,
                        agent_id,
                        cwd,
                        args.task,
                        ttl_seconds,
                        now,
                        os.getpid(),
                        socket.gethostname(),
                        getpass.getuser(),
                    )
                store.announce(
                    agent_id,
                    cwd,
                    args.task,
                    (),
                    tuple(args.resource),
                    ttl_seconds,
                    now,
                    os.getpid(),
                    socket.gethostname(),
                    sys.platform,
                    getpass.getuser(),
                )
    finally:
        store.release(tuple(args.resource), agent_id)


def main() -> int:
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
