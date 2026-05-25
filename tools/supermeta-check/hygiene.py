#!/usr/bin/env python3
"""Repo-scoped Finder-copy hygiene for Supermeta smart-check."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVIEW_NEEDED_EXIT_CODE = 3
QUARANTINE_ROOT = Path(".codex-bootstrap/cleanup-quarantine")
SKIPPED_DIR_NAMES = {
    ".git",
    ".gradle",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "out",
    "target",
}
NUMBERED_COPY_PATTERN = re.compile(r"^(?P<stem>.+) (?P<number>[2-9][0-9]*)(?P<suffix>(?:\.[^./]+)*)$")
COPY_SUFFIX_PATTERN = re.compile(r"^(?P<stem>.+) copy(?P<suffix>(?:\.[^./]+)*)$")


@dataclass(frozen=True)
class FinderCopyCandidate:
    duplicate_path: str
    original_path: str | None
    kind: str
    reason: str


def infer_finder_copy_candidate(root: Path, relative_path: str) -> FinderCopyCandidate | None:
    normalized = normalize_relative_path(relative_path)
    path = root / normalized
    name = path.name
    match = NUMBERED_COPY_PATTERN.match(name) or COPY_SUFFIX_PATTERN.match(name)
    if match is None:
        return None
    original_name = f"{match.group('stem')}{match.group('suffix')}"
    original = path.with_name(original_name)
    kind = path_kind(path)
    if not original.exists():
        return FinderCopyCandidate(
            duplicate_path=normalized,
            original_path=None,
            kind=kind,
            reason="ambiguous-original",
        )
    if path.is_dir() and not original.is_dir():
        return FinderCopyCandidate(normalized, None, kind, "kind-mismatch")
    if path.is_file() and not original.is_file():
        return FinderCopyCandidate(normalized, None, kind, "kind-mismatch")
    return FinderCopyCandidate(
        duplicate_path=normalized,
        original_path=normalize_relative_path(str(original.relative_to(root))),
        kind=kind,
        reason="single-original",
    )


def normalize_relative_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def path_kind(path: Path) -> str:
    if path.is_dir():
        return "directory"
    return "file"


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_manifest(path: Path) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    for child in sorted(path.rglob("*")):
        relative = normalize_relative_path(str(child.relative_to(path)))
        if should_skip_manifest_path(relative):
            continue
        if child.is_symlink():
            entries[relative] = {
                "kind": "symlink",
                "target": os.readlink(child),
            }
            continue
        if child.is_dir():
            entries[relative] = {"kind": "directory"}
            continue
        if child.is_file():
            entries[relative] = {
                "kind": "file",
                "size": child.stat().st_size,
                "sha256": hash_file(child),
            }
    return {"entries": entries}


def should_skip_manifest_path(relative_path: str) -> bool:
    parts = relative_path.split("/")
    return any(part in SKIPPED_DIR_NAMES for part in parts)


@dataclass(frozen=True)
class HygieneConfig:
    platform_name: str = platform.system().lower()
    quarantine_root: Path = QUARANTINE_ROOT
    trash_root: Path | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class HygieneAction:
    action: str
    reason: str
    duplicate_path: str
    original_path: str | None = None
    destination_path: str | None = None
    manifest_path: str | None = None
    review_needed: bool = False


@dataclass(frozen=True)
class HygieneResult:
    enabled: bool
    review_needed: bool
    actions: tuple[HygieneAction, ...]


def plan_hygiene(
    root: Path,
    changed_files: tuple[str, ...],
    git_status: dict[str, str],
    config: HygieneConfig,
) -> HygieneResult:
    actions: list[HygieneAction] = []
    for changed_file in changed_files:
        normalized = normalize_relative_path(changed_file)
        if not is_mutable_status(git_status.get(normalized, "")):
            continue
        if should_skip_candidate_path(normalized):
            continue
        candidate = infer_finder_copy_candidate(root, normalized)
        if candidate is None:
            continue
        actions.append(classify_candidate(root, candidate, config))
    return HygieneResult(
        enabled=True,
        review_needed=any(action.review_needed for action in actions),
        actions=tuple(actions),
    )


def is_mutable_status(status: str) -> bool:
    return status in {"??", "A ", "AM", "AD", "A"}


def should_skip_candidate_path(relative_path: str) -> bool:
    parts = relative_path.split("/")
    if ".codex-bootstrap" in parts and "cleanup-quarantine" in parts:
        return True
    return any(part in SKIPPED_DIR_NAMES for part in parts)


def classify_candidate(root: Path, candidate: FinderCopyCandidate, config: HygieneConfig) -> HygieneAction:
    if candidate.original_path is None:
        return HygieneAction(
            action="report",
            reason=candidate.reason,
            duplicate_path=candidate.duplicate_path,
            review_needed=True,
        )
    duplicate = root / candidate.duplicate_path
    original = root / candidate.original_path
    if candidate.kind == "directory":
        duplicate_manifest = directory_manifest(duplicate)
        original_manifest = directory_manifest(original)
        if duplicate_manifest == original_manifest:
            return trash_or_quarantine_exact(candidate, config, "exact-directory-duplicate")
        return HygieneAction(
            action="quarantine",
            reason="divergent-directory-duplicate",
            duplicate_path=candidate.duplicate_path,
            original_path=candidate.original_path,
            review_needed=True,
        )
    if hash_file(duplicate) == hash_file(original):
        return trash_or_quarantine_exact(candidate, config, "exact-file-duplicate")
    return HygieneAction(
        action="quarantine",
        reason="divergent-file-duplicate",
        duplicate_path=candidate.duplicate_path,
        original_path=candidate.original_path,
        review_needed=True,
    )


def trash_or_quarantine_exact(
    candidate: FinderCopyCandidate,
    config: HygieneConfig,
    reason: str,
) -> HygieneAction:
    if supports_trash(config):
        return HygieneAction(
            action="trash",
            reason=reason,
            duplicate_path=candidate.duplicate_path,
            original_path=candidate.original_path,
            review_needed=False,
        )
    return HygieneAction(
        action="quarantine",
        reason=f"{reason}-trash-unavailable",
        duplicate_path=candidate.duplicate_path,
        original_path=candidate.original_path,
        review_needed=False,
    )


def supports_trash(config: HygieneConfig) -> bool:
    platform_name = config.platform_name.lower()
    if platform_name not in {"darwin", "macos"}:
        return False
    trash_root = config.trash_root or (Path.home() / ".Trash")
    return trash_root.exists() or trash_root.parent.exists()


def apply_hygiene_actions(
    root: Path,
    result: HygieneResult,
    config: HygieneConfig,
    dry_run: bool,
) -> HygieneResult:
    applied: list[HygieneAction] = []
    for action in result.actions:
        if dry_run or action.action == "report":
            applied.append(action)
            continue
        if action.action == "trash":
            applied.append(move_to_trash(root, action, config))
            continue
        if action.action == "quarantine":
            applied.append(move_to_quarantine(root, action, config))
            continue
        applied.append(action)
    return HygieneResult(result.enabled, result.review_needed, tuple(applied))


def move_to_trash(root: Path, action: HygieneAction, config: HygieneConfig) -> HygieneAction:
    trash_root = config.trash_root or (Path.home() / ".Trash")
    trash_root.mkdir(parents=True, exist_ok=True)
    source = root / action.duplicate_path
    destination = unique_destination(trash_root / source.name)
    shutil.move(str(source), str(destination))
    return replace_action(action, destination_path=normalize_relative_path(str(destination.relative_to(trash_root))))


def move_to_quarantine(root: Path, action: HygieneAction, config: HygieneConfig) -> HygieneAction:
    run_id = config.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source = root / action.duplicate_path
    quarantine_dir = root / config.quarantine_root / run_id / short_path_hash(action.duplicate_path)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(quarantine_dir / source.name)
    shutil.move(str(source), str(destination))
    manifest_path = write_quarantine_manifest(root, quarantine_dir, action, destination)
    return replace_action(
        action,
        destination_path=normalize_relative_path(str(destination.relative_to(root))),
        manifest_path=normalize_relative_path(str(manifest_path.relative_to(root))),
    )


def write_quarantine_manifest(root: Path, quarantine_dir: Path, action: HygieneAction, destination: Path) -> Path:
    manifest_path = quarantine_dir / "manifest.json"
    payload: dict[str, Any] = {
        "action": action.action,
        "reason": action.reason,
        "duplicatePath": action.duplicate_path,
        "originalPath": action.original_path,
        "destinationPath": normalize_relative_path(str(destination.relative_to(root))),
        "reviewNeeded": action.review_needed,
    }
    if action.original_path is not None:
        original = root / action.original_path
        if original.is_dir():
            payload["originalManifest"] = directory_manifest(original)
        elif original.is_file():
            payload["originalSha256"] = hash_file(original)
    if destination.is_dir():
        payload["duplicateManifest"] = directory_manifest(destination)
    elif destination.is_file():
        payload["duplicateSha256"] = hash_file(destination)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def short_path_hash(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:8]


def replace_action(action: HygieneAction, **changes: object) -> HygieneAction:
    payload = asdict(action)
    payload.update(changes)
    return HygieneAction(**payload)
