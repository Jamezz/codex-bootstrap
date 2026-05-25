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
