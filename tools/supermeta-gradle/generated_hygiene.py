#!/usr/bin/env python3
"""Generated-output hygiene for agent Gradle capsules."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


NUMBERED_COPY_PATTERN = re.compile(r"^(?P<stem>.+) (?P<number>[2-9][0-9]*)(?P<suffix>(?:\.[^./]+)*)$")
COPY_SUFFIX_PATTERN = re.compile(r"^(?P<stem>.+) copy(?P<suffix>(?:\.[^./]+)*)$")
GENERATED_DIR_NAMES = {"build", "out", "target"}
SKIPPED_DIR_NAMES = {".build", ".git", ".gradle", ".idea", ".venv", ".worktrees", "artifacts", "node_modules"}
CLASSPATH_SUFFIXES = {".class", ".jar", ".properties", ".xml", ".json", ".yml", ".yaml"}
REPORT_SUFFIXES = {".html", ".xml", ".json", ".txt"}


@dataclass(frozen=True)
class GeneratedHygieneAction:
    action: str
    reason: str
    duplicate_path: str
    original_path: str | None = None
    destination_path: str | None = None
    manifest_path: str | None = None


@dataclass(frozen=True)
class GeneratedHygieneResult:
    review_needed: bool
    actions: tuple[GeneratedHygieneAction, ...]


def run_generated_hygiene(root: Path, hygiene_root: Path) -> GeneratedHygieneResult:
    resolved_root = root.resolve()
    hygiene_root.mkdir(parents=True, exist_ok=True)
    actions: list[GeneratedHygieneAction] = []
    for duplicate in generated_duplicate_candidates(resolved_root):
        original = original_for_duplicate(duplicate)
        if is_generated_report_output(duplicate):
            actions.append(remove_generated_duplicate(resolved_root, duplicate, original))
            continue
        if original is None or not original.exists():
            actions.append(
                quarantine(
                    resolved_root,
                    hygiene_root,
                    duplicate,
                    original,
                    "quarantine-ambiguous-generated-duplicate",
                )
            )
            continue
        actions.append(
            quarantine(resolved_root, hygiene_root, duplicate, original, "quarantine-generated-duplicate")
        )
    return GeneratedHygieneResult(
        review_needed=any(action.action == "quarantine" for action in actions),
        actions=tuple(actions),
    )


def generated_duplicate_candidates(root: Path) -> list[Path]:
    candidates: list[Path] = []
    for generated_dir in generated_dirs(root):
        for child in generated_dir.rglob("*"):
            if child.is_file() and is_generated_duplicate_relevant(child) and original_for_duplicate(child) is not None:
                candidates.append(child)
    return sorted(candidates)


def generated_dirs(root: Path) -> list[Path]:
    dirs: list[Path] = []
    for current_root, dir_names, _file_names in os.walk(root):
        dir_names[:] = [name for name in dir_names if name not in SKIPPED_DIR_NAMES]
        current = Path(current_root)
        for name in dir_names:
            if name in GENERATED_DIR_NAMES:
                dirs.append(current / name)
    return dirs


def original_for_duplicate(path: Path) -> Path | None:
    match = NUMBERED_COPY_PATTERN.match(path.name) or COPY_SUFFIX_PATTERN.match(path.name)
    if match is None:
        return None
    return path.with_name(f"{match.group('stem')}{match.group('suffix')}")


def is_generated_duplicate_relevant(path: Path) -> bool:
    if is_generated_report_output(path):
        return True
    return is_classpath_relevant(path)


def is_classpath_relevant(path: Path) -> bool:
    if path.suffix.lower() not in CLASSPATH_SUFFIXES:
        return False
    return path.suffix.lower() == ".jar" or "classes" in path.parts or "resources" in path.parts


def is_generated_report_output(path: Path) -> bool:
    return ("reports" in path.parts or "test-results" in path.parts) and path.suffix.lower() in REPORT_SUFFIXES


def remove_generated_duplicate(
    root: Path,
    duplicate: Path,
    original: Path | None,
) -> GeneratedHygieneAction:
    duplicate.unlink()
    return GeneratedHygieneAction(
        action="remove",
        reason="remove-generated-output-duplicate",
        duplicate_path=relative_text(root, duplicate),
        original_path=relative_text(root, original) if original is not None else None,
    )


def quarantine(
    root: Path,
    hygiene_root: Path,
    duplicate: Path,
    original: Path | None,
    reason: str,
) -> GeneratedHygieneAction:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination_dir = hygiene_root / run_id / short_path_hash(relative_text(root, duplicate))
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(destination_dir / duplicate.name)
    shutil.move(str(duplicate), str(destination))
    manifest = write_manifest(root, destination_dir, duplicate, original, destination, reason)
    return GeneratedHygieneAction(
        action="quarantine",
        reason=reason,
        duplicate_path=relative_text(root, duplicate),
        original_path=relative_text(root, original) if original is not None else None,
        destination_path=str(destination),
        manifest_path=str(manifest),
    )


def write_manifest(
    root: Path,
    destination_dir: Path,
    duplicate: Path,
    original: Path | None,
    destination: Path,
    reason: str,
) -> Path:
    manifest = destination_dir / "manifest.json"
    payload = {
        "reason": reason,
        "duplicatePath": relative_text(root, duplicate),
        "originalPath": relative_text(root, original) if original is not None else None,
        "destinationPath": str(destination),
        "duplicateSize": destination.stat().st_size if destination.is_file() else None,
        "originalSize": original.stat().st_size if original is not None and original.is_file() else None,
    }
    manifest.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def relative_text(root: Path, path: Path | None) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)


def short_path_hash(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:8]


def unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    index = 2
    while True:
        candidate = destination.with_name(f"{destination.stem}-{index}{destination.suffix}")
        if not candidate.exists():
            return candidate
        index += 1
