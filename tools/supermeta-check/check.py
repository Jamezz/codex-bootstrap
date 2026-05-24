#!/usr/bin/env python3
"""Focused verification lane selection for Codex Bootstrap generated projects."""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CHECKS_POLICY = Path(".codex-bootstrap/checks.json")
LOCAL_POLICY = Path(".codex-bootstrap/checks.local.json")
SCHEMA_VERSION = 1


class SmartCheckError(Exception):
    pass


@dataclass(frozen=True)
class CheckTriggers:
    paths: tuple[str, ...]


@dataclass(frozen=True)
class CheckLane:
    lane_id: str
    description: str
    triggers: CheckTriggers
    commands: tuple[tuple[str, ...], ...]
    escalates_to: str | None
    stop_on_failure: bool


@dataclass(frozen=True)
class CheckPolicy:
    schema_version: int
    template_id: str
    lanes: dict[str, CheckLane]


@dataclass(frozen=True)
class PlanItem:
    lane: CheckLane
    reason: str


@dataclass(frozen=True)
class CheckPlan:
    items: tuple[PlanItem, ...]


def load_effective_policy(root: Path) -> tuple[CheckPolicy, tuple[str, ...]]:
    generated = parse_policy(load_json(root / CHECKS_POLICY), generated=True)
    local_path = root / LOCAL_POLICY
    if not local_path.exists():
        return generated, ()
    try:
        local = parse_policy(load_json(local_path), generated=False, template_id=generated.template_id)
    except (SmartCheckError, OSError, json.JSONDecodeError) as error:
        return generated, (f"ignored invalid local check policy {LOCAL_POLICY}: {error}",)
    return merge_policy(generated, local), ()


def parse_policy(raw: dict[str, Any], generated: bool, template_id: str | None = None) -> CheckPolicy:
    schema_version = require_int(raw, "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise SmartCheckError(f"unsupported checks schema {schema_version}")
    policy_template_id = require_string(raw, "templateId") if generated else (optional_string(raw, "templateId") or template_id or "")
    raw_lanes = raw.get("lanes")
    if not isinstance(raw_lanes, list):
        raise SmartCheckError("lanes must be an array")
    lanes: dict[str, CheckLane] = {}
    for index, item in enumerate(raw_lanes):
        if not isinstance(item, dict):
            raise SmartCheckError(f"lanes[{index}] must be an object")
        lane_id = require_string(item, "id")
        if lane_id in lanes:
            raise SmartCheckError(f"duplicate lane id: {lane_id}")
        lanes[lane_id] = parse_lane(item, generated)
    if generated and "full" not in lanes:
        raise SmartCheckError("generated checks policy must define full lane")
    return CheckPolicy(schema_version=schema_version, template_id=policy_template_id, lanes=lanes)


def parse_lane(raw: dict[str, Any], generated: bool) -> CheckLane:
    triggers_raw = raw.get("triggers", {})
    if not isinstance(triggers_raw, dict):
        raise SmartCheckError("lane triggers must be an object")
    commands_raw = raw.get("commands", [] if not generated else None)
    if not isinstance(commands_raw, list):
        raise SmartCheckError("lane commands must be an array")
    return CheckLane(
        lane_id=require_string(raw, "id"),
        description=optional_string(raw, "description") or "",
        triggers=CheckTriggers(paths=tuple(require_string_list(triggers_raw, "paths", allow_missing=True))),
        commands=parse_commands(commands_raw),
        escalates_to=optional_nullable_string(raw, "escalatesTo"),
        stop_on_failure=optional_bool(raw, "stopOnFailure", True),
    )


def merge_policy(generated: CheckPolicy, local: CheckPolicy) -> CheckPolicy:
    lanes = dict(generated.lanes)
    for lane_id, override in local.lanes.items():
        base = lanes.get(lane_id)
        if base is None:
            lanes[lane_id] = override
            continue
        lanes[lane_id] = CheckLane(
            lane_id=lane_id,
            description=override.description or base.description,
            triggers=override.triggers if override.triggers.paths else base.triggers,
            commands=override.commands if override.commands else base.commands,
            escalates_to=override.escalates_to if override.escalates_to is not None else base.escalates_to,
            stop_on_failure=override.stop_on_failure,
        )
    return CheckPolicy(schema_version=generated.schema_version, template_id=generated.template_id, lanes=lanes)


def select_lanes(policy: CheckPolicy, changed_files: tuple[str, ...], force_full: bool) -> CheckPlan:
    if force_full:
        return CheckPlan((PlanItem(require_lane(policy, "full"), "forced full lane"),))
    if not changed_files:
        return CheckPlan((PlanItem(require_lane(policy, "full"), "no changed files; using full lane"),))
    selected: list[PlanItem] = []
    seen: set[str] = set()
    for lane in policy.lanes.values():
        if lane.lane_id == "full":
            continue
        reason = match_reason(lane, changed_files)
        if reason:
            add_lane(policy, lane.lane_id, reason, selected, seen)
            if lane.escalates_to:
                add_lane(policy, lane.escalates_to, f"escalated from {lane.lane_id}", selected, seen)
    if not selected:
        add_lane(policy, "full", "no lane matched changed files", selected, seen)
    return CheckPlan(tuple(selected))


def add_lane(policy: CheckPolicy, lane_id: str, reason: str, selected: list[PlanItem], seen: set[str]) -> None:
    if lane_id in seen:
        return
    selected.append(PlanItem(require_lane(policy, lane_id), reason))
    seen.add(lane_id)


def require_lane(policy: CheckPolicy, lane_id: str) -> CheckLane:
    try:
        return policy.lanes[lane_id]
    except KeyError as error:
        raise SmartCheckError(f"missing lane: {lane_id}") from error


def match_reason(lane: CheckLane, changed_files: tuple[str, ...]) -> str | None:
    for changed_file in changed_files:
        normalized = changed_file.replace("\\", "/")
        for pattern in lane.triggers.paths:
            if fnmatch.fnmatch(normalized, pattern):
                return f"matched {normalized} with {pattern}"
    return None


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise SmartCheckError(f"missing check policy {path}") from error
    if not isinstance(raw, dict):
        raise SmartCheckError("check policy must be an object")
    return raw


def require_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise SmartCheckError(f"{key} must be a non-empty string")
    return value


def optional_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key, "")
    if value == "":
        return ""
    if not isinstance(value, str):
        raise SmartCheckError(f"{key} must be a string")
    return value


def optional_nullable_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SmartCheckError(f"{key} must be a string or null")
    return value


def require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise SmartCheckError(f"{key} must be an integer")
    return value


def optional_bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise SmartCheckError(f"{key} must be a boolean")
    return value


def require_string_list(raw: dict[str, Any], key: str, allow_missing: bool = False) -> list[str]:
    value = raw.get(key)
    if value is None and allow_missing:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SmartCheckError(f"{key} must be an array of non-empty strings")
    return value


def parse_commands(raw: list[Any]) -> tuple[tuple[str, ...], ...]:
    commands: list[tuple[str, ...]] = []
    for index, command in enumerate(raw):
        if not isinstance(command, list) or not all(isinstance(item, str) and item for item in command):
            raise SmartCheckError(f"commands[{index}] must be an array of non-empty strings")
        commands.append(tuple(command))
    return tuple(commands)
