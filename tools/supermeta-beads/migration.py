"""Deterministic Beans 0.4.2 to Beads JSONL migration."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class MigrationError(Exception):
    """Raised when Beans data cannot be migrated without guessing."""


STATUS_MAP = {
    "todo": "open",
    "in-progress": "in_progress",
    "draft": "deferred",
    "completed": "closed",
    "scrapped": "closed",
}
TYPE_MAP = {
    "milestone": "epic",
    "epic": "epic",
    "bug": "bug",
    "feature": "feature",
    "task": "task",
}
PRIORITY_MAP = {"critical": 0, "high": 1, "normal": 2, "": 2, "low": 3, "deferred": 4}
KNOWN_FIELDS = {
    "title",
    "status",
    "type",
    "priority",
    "tags",
    "created_at",
    "updated_at",
    "parent",
    "blocking",
    "blocked_by",
}
VALID_ID = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class MigrationResult:
    jsonl: str
    issue_count: int
    source_paths: tuple[str, ...]


def migrate_repository(root: Path) -> MigrationResult:
    beans_dir = root / ".beans"
    if not beans_dir.is_dir():
        return MigrationResult(jsonl=existing_jsonl(root), issue_count=0, source_paths=())
    records = [parse_bean(path, beans_dir) for path in sorted(beans_dir.rglob("*.md"))]
    migrated = build_records(records)
    merged = merge_existing(migrated, parse_jsonl(existing_jsonl(root)))
    return MigrationResult(
        jsonl=render_jsonl(merged),
        issue_count=len(records),
        source_paths=tuple(path.relative_to(root).as_posix() for path in sorted(beans_dir.rglob("*.md"))),
    )


def existing_jsonl(root: Path) -> str:
    path = root / ".beads" / "issues.jsonl"
    return path.read_text(encoding="utf-8") if path.is_file() else ""


def parse_bean(path: Path, beans_dir: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise MigrationError(f"{path}: missing YAML frontmatter")
    try:
        frontmatter, body = text[4:].split("\n---\n", 1)
    except ValueError as error:
        raise MigrationError(f"{path}: unterminated YAML frontmatter") from error
    values = parse_frontmatter(frontmatter, path)
    bean_id = path.stem.split("--", 1)[0]
    if not VALID_ID.fullmatch(bean_id):
        raise MigrationError(f"{path}: invalid Beads issue id {bean_id!r}")
    title = required_string(values, "title", path)
    status = mapped(values, "status", "todo", STATUS_MAP, path)
    issue_type = mapped(values, "type", "task", TYPE_MAP, path)
    priority = mapped(values, "priority", "", PRIORITY_MAP, path)
    labels = string_list(values.get("tags", []), "tags", path)
    if values.get("status") == "scrapped":
        labels.append("beans-scrapped")
    if values.get("type") == "milestone":
        labels.append("beans-milestone")
    metadata = {key: value for key, value in values.items() if key not in KNOWN_FIELDS}
    return {
        "_type": "issue",
        "id": bean_id,
        "title": title,
        "description": body.rstrip("\n"),
        "status": status,
        "priority": priority,
        "issue_type": issue_type,
        "labels": sorted(set(labels)),
        "created_at": optional_string(values.get("created_at"), "created_at", path),
        "updated_at": optional_string(values.get("updated_at"), "updated_at", path),
        "parent": optional_string(values.get("parent"), "parent", path),
        "blocking": string_list(values.get("blocking", []), "blocking", path),
        "blocked_by": string_list(values.get("blocked_by", []), "blocked_by", path),
        "metadata": {"beans": metadata} if metadata else {},
        "_source": path.relative_to(beans_dir).as_posix(),
    }


def parse_frontmatter(text: str, path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    active_list: str | None = None
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if raw.startswith((" ", "\t")):
            if active_list and stripped.startswith("- "):
                result[active_list].append(parse_scalar(stripped[2:].strip()))
                continue
            raise MigrationError(f"{path}:{number}: nested YAML is not supported")
        if ":" not in raw:
            raise MigrationError(f"{path}:{number}: invalid frontmatter line")
        key, value = raw.split(":", 1)
        key = key.strip()
        if not key or key in result:
            raise MigrationError(f"{path}:{number}: invalid or duplicate key {key!r}")
        value = value.strip()
        if not value:
            result[key] = []
            active_list = key
        else:
            result[key] = parse_scalar(value)
            active_list = None
    return result


def parse_scalar(value: str) -> Any:
    if value.startswith("["):
        try:
            parsed = json.loads(value.replace("'", '"'))
        except json.JSONDecodeError:
            if not value.endswith("]"):
                raise MigrationError(f"invalid inline list {value!r}")
            inner = value[1:-1].strip()
            parsed = [] if not inner else [parse_scalar(item.strip()) for item in inner.split(",")]
        if not isinstance(parsed, list) or any(isinstance(item, (dict, list)) for item in parsed):
            raise MigrationError("nested YAML values are not supported")
        return parsed
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return json.loads(value)
        except json.JSONDecodeError as error:
            raise MigrationError(f"invalid quoted scalar {value!r}") from error
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    if value in {"true", "false"}:
        return value == "true"
    if re.fullmatch(r"-?[0-9]+", value):
        return int(value)
    return value


def build_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for record in records:
        issue_id = record["id"]
        if issue_id in by_id:
            raise MigrationError(f"duplicate Beans id {issue_id}")
        by_id[issue_id] = record
    edges: set[tuple[str, str, str]] = set()
    for record in records:
        issue_id = record["id"]
        parent = record.pop("parent")
        if parent:
            add_edge(edges, issue_id, parent, "parent-child", by_id)
        for target in record.pop("blocking"):
            add_edge(edges, target, issue_id, "blocks", by_id)
        for blocker in record.pop("blocked_by"):
            add_edge(edges, issue_id, blocker, "blocks", by_id)
    validate_acyclic(edges, by_id)
    dependencies: dict[str, list[dict[str, str]]] = {issue_id: [] for issue_id in by_id}
    for issue_id, depends_on, edge_type in sorted(edges):
        dependencies[issue_id].append(
            {"issue_id": issue_id, "depends_on_id": depends_on, "type": edge_type}
        )
    result: list[dict[str, Any]] = []
    for issue_id in sorted(by_id):
        record = by_id[issue_id]
        record.pop("_source")
        for key in ("created_at", "updated_at"):
            if record[key] is None:
                record.pop(key)
        if not record["labels"]:
            record.pop("labels")
        if not record["metadata"]:
            record.pop("metadata")
        if dependencies[issue_id]:
            record["dependencies"] = dependencies[issue_id]
        result.append(record)
    return result


def add_edge(
    edges: set[tuple[str, str, str]], issue_id: str, depends_on: str, edge_type: str,
    by_id: dict[str, dict[str, Any]],
) -> None:
    if issue_id not in by_id or depends_on not in by_id:
        raise MigrationError(f"dependency references missing issue: {issue_id} -> {depends_on}")
    if issue_id == depends_on:
        raise MigrationError(f"self dependency for {issue_id}")
    edges.add((issue_id, depends_on, edge_type))


def validate_acyclic(edges: set[tuple[str, str, str]], by_id: dict[str, Any]) -> None:
    graph: dict[str, set[str]] = {issue_id: set() for issue_id in by_id}
    for issue_id, depends_on, _edge_type in edges:
        graph[issue_id].add(depends_on)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(issue_id: str) -> None:
        if issue_id in visiting:
            raise MigrationError(f"dependency cycle contains {issue_id}")
        if issue_id in visited:
            return
        visiting.add(issue_id)
        for dependency in graph[issue_id]:
            visit(dependency)
        visiting.remove(issue_id)
        visited.add(issue_id)

    for issue_id in graph:
        visit(issue_id)


def merge_existing(migrated: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged = {record_id(record): record for record in existing}
    for record in migrated:
        issue_id = record_id(record)
        current = merged.get(issue_id)
        if current is not None and canonical(current) != canonical(record):
            raise MigrationError(f"Beads issue {issue_id} conflicts with migrated Beans data")
        merged[issue_id] = current or record
    return [merged[issue_id] for issue_id in sorted(merged)]


def parse_jsonl(text: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            raise MigrationError(f"existing Beads JSONL line {number} is invalid") from error
        if not isinstance(value, dict):
            raise MigrationError(f"existing Beads JSONL line {number} is not an object")
        result.append(value)
    return result


def render_jsonl(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(record, separators=(",", ":"), sort_keys=True) + "\n" for record in records)


def record_id(record: dict[str, Any]) -> str:
    value = record.get("id")
    if not isinstance(value, str) or not value:
        raise MigrationError("Beads JSONL record is missing an id")
    return value


def canonical(record: dict[str, Any]) -> str:
    ignored = {"created_by", "owner", "dependency_count", "dependent_count", "comment_count"}
    return json.dumps({key: value for key, value in record.items() if key not in ignored}, sort_keys=True)


def mapped(values: dict[str, Any], key: str, default: str, mapping: dict[str, Any], path: Path) -> Any:
    value = values.get(key, default)
    if not isinstance(value, str) or value not in mapping:
        raise MigrationError(f"{path}: unsupported {key} {value!r}")
    return mapping[value]


def required_string(values: dict[str, Any], key: str, path: Path) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise MigrationError(f"{path}: {key} must be a non-empty string")
    return value


def optional_string(value: Any, key: str, path: Path) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise MigrationError(f"{path}: {key} must be a string")
    return value


def string_list(value: Any, key: str, path: Path) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise MigrationError(f"{path}: {key} must be a list of strings")
    return list(value)
