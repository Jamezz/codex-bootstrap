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
