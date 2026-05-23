#!/usr/bin/env python3
"""Managed resync for Codex Bootstrap generated projects."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
SYNC_METADATA = Path(".codex-bootstrap/sync.json")
REPORTS_DIR = Path(".codex-bootstrap/reports")
TEMPLATE_MANIFEST = "bootstrap-template.json"
DEFAULT_TIMEOUT_SECONDS = 300


class SyncError(Exception):
    """Raised for user-facing sync failures."""


@dataclass(frozen=True)
class ManagedFileState:
    managed_set: str
    sha256: str


@dataclass(frozen=True)
class ManagedRegionState:
    managed_set: str
    path: str
    region_id: str
    sha256: str


@dataclass(frozen=True)
class SyncMetadata:
    schema_version: int
    source_repository: str
    source_ref: str
    source_commit: str
    template_id: str
    contract_version: int
    identity: dict[str, str]
    managed_sets: tuple[str, ...]
    opt_out: tuple[str, ...]
    managed_files: dict[str, ManagedFileState]
    managed_regions: dict[str, ManagedRegionState]
    verification_commands: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "source": {
                "repository": self.source_repository,
                "ref": self.source_ref,
                "commit": self.source_commit,
            },
            "template": {
                "id": self.template_id,
                "contractVersion": self.contract_version,
            },
            "identity": dict(self.identity),
            "managedSets": list(self.managed_sets),
            "optOut": list(self.opt_out),
            "managedFiles": {
                path: {"set": state.managed_set, "sha256": state.sha256}
                for path, state in sorted(self.managed_files.items())
            },
            "managedRegions": {
                key: {
                    "set": state.managed_set,
                    "path": state.path,
                    "id": state.region_id,
                    "sha256": state.sha256,
                }
                for key, state in sorted(self.managed_regions.items())
            },
            "verificationCommands": list(self.verification_commands),
        }


@dataclass(frozen=True)
class ManagedFileSpec:
    path: str
    managed_set: str


@dataclass(frozen=True)
class ManagedRegionSpec:
    path: str
    region_id: str
    managed_set: str

    @property
    def key(self) -> str:
        return f"{self.path}:{self.region_id}"


@dataclass(frozen=True)
class ManagedSetSpec:
    managed_set: str
    description: str
    files: tuple[ManagedFileSpec, ...]
    regions: tuple[ManagedRegionSpec, ...]


@dataclass(frozen=True)
class SyncContract:
    version: int
    managed_sets: dict[str, ManagedSetSpec]
    verification_commands: tuple[str, ...]
    migration_notes: tuple[str, ...]

    @property
    def managed_files(self) -> dict[str, ManagedFileSpec]:
        result: dict[str, ManagedFileSpec] = {}
        for managed_set in self.managed_sets.values():
            for spec in managed_set.files:
                result[spec.path] = spec
        return result

    @property
    def managed_regions(self) -> dict[str, ManagedRegionSpec]:
        result: dict[str, ManagedRegionSpec] = {}
        for managed_set in self.managed_sets.values():
            for spec in managed_set.regions:
                result[spec.key] = spec
        return result


@dataclass(frozen=True)
class FileChange:
    path: str
    new_text: str
    new_sha256: str
    managed_set: str


@dataclass(frozen=True)
class RegionChange:
    path: str
    region_id: str
    new_text: str
    new_body: str
    new_sha256: str
    managed_set: str


@dataclass(frozen=True)
class SyncConflict:
    path: str
    reason: str


@dataclass(frozen=True)
class SyncPlan:
    file_changes: tuple[FileChange, ...]
    region_changes: tuple[RegionChange, ...]
    conflicts: tuple[SyncConflict, ...]
    migration_notes: tuple[str, ...]
    verification_commands: tuple[str, ...]

    @property
    def has_changes(self) -> bool:
        return bool(self.file_changes or self.region_changes)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)


@dataclass(frozen=True)
class RegionBody:
    body: str


def load_sync_metadata(root: Path) -> SyncMetadata:
    metadata_path = root / SYNC_METADATA
    if not metadata_path.is_file():
        raise SyncError("missing .codex-bootstrap/sync.json; this project is not sync-enabled")
    raw = load_json_object(metadata_path)
    schema_version = require_int(raw, "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise SyncError(
            f"unsupported sync schema {schema_version}; supported schema is {SCHEMA_VERSION}"
        )
    source = require_object(raw, "source")
    template = require_object(raw, "template")
    managed_files = {
        normalize_path(path): ManagedFileState(
            managed_set=require_string(value, "set"),
            sha256=require_sha256(value, "sha256"),
        )
        for path, value in require_object_map(raw, "managedFiles").items()
    }
    managed_regions = {
        key: ManagedRegionState(
            managed_set=require_string(value, "set"),
            path=normalize_path(require_string(value, "path")),
            region_id=require_string(value, "id"),
            sha256=require_sha256(value, "sha256"),
        )
        for key, value in require_object_map(raw, "managedRegions").items()
    }
    return SyncMetadata(
        schema_version=schema_version,
        source_repository=require_string(source, "repository"),
        source_ref=require_string(source, "ref"),
        source_commit=require_string(source, "commit"),
        template_id=require_string(template, "id"),
        contract_version=require_int(template, "contractVersion"),
        identity=require_string_map(raw, "identity"),
        managed_sets=tuple(require_string_list(raw, "managedSets")),
        opt_out=tuple(require_string_list(raw, "optOut")),
        managed_files=managed_files,
        managed_regions=managed_regions,
        verification_commands=tuple(require_string_list(raw, "verificationCommands")),
    )


def load_sync_contract(catalog_root: Path, template_id: str) -> SyncContract:
    manifest_path = catalog_root / "templates" / template_id / TEMPLATE_MANIFEST
    if not manifest_path.is_file():
        raise SyncError(f"unknown template '{template_id}' in {catalog_root}")
    raw = load_json_object(manifest_path)
    sync_raw = require_object(raw, "syncContract")
    managed_sets: dict[str, ManagedSetSpec] = {}
    for item in require_object_array(sync_raw, "managedSets"):
        managed_set = require_string(item, "id")
        files = tuple(
            ManagedFileSpec(
                path=normalize_path(require_string(file_item, "path")),
                managed_set=managed_set,
            )
            for file_item in require_object_array(item, "files", allow_missing=True)
            if require_string(file_item, "mode") == "whole-file"
        )
        regions = tuple(
            ManagedRegionSpec(
                path=normalize_path(require_string(region_item, "path")),
                region_id=require_string(region_item, "id"),
                managed_set=managed_set,
            )
            for region_item in require_object_array(item, "regions", allow_missing=True)
        )
        managed_sets[managed_set] = ManagedSetSpec(
            managed_set=managed_set,
            description=require_string(item, "description"),
            files=files,
            regions=regions,
        )
    return SyncContract(
        version=require_int(sync_raw, "version"),
        managed_sets=managed_sets,
        verification_commands=tuple(require_string_list(sync_raw, "verificationCommands")),
        migration_notes=tuple(require_string_list(sync_raw, "migrationNotes")),
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def plan_managed_updates(
    root: Path,
    candidate_root: Path,
    metadata: SyncMetadata,
    contract: SyncContract,
    git_status: dict[str, str],
) -> SyncPlan:
    file_changes: list[FileChange] = []
    region_changes: list[RegionChange] = []
    conflicts: list[SyncConflict] = []
    enabled_sets = set(metadata.managed_sets) - set(metadata.opt_out)

    for path, spec in sorted(contract.managed_files.items()):
        if spec.managed_set not in enabled_sets or path in metadata.opt_out:
            continue
        current = root / path
        candidate = candidate_root / path
        if not candidate.is_file():
            conflicts.append(SyncConflict(path, "managed target missing from regenerated template"))
            continue
        if git_status.get(path) == "??":
            conflicts.append(SyncConflict(path, "untracked file would be overwritten"))
            continue
        previous = metadata.managed_files.get(path)
        if current.exists() and previous and sha256_file(current) != previous.sha256:
            conflicts.append(SyncConflict(path, "hash mismatch; downstream file was edited"))
            continue
        candidate_text = candidate.read_text(encoding="utf-8")
        candidate_hash = sha256_file(candidate)
        current_hash = sha256_file(current) if current.exists() else ""
        if current_hash != candidate_hash:
            file_changes.append(
                FileChange(
                    path=path,
                    new_text=candidate_text,
                    new_sha256=candidate_hash,
                    managed_set=spec.managed_set,
                )
            )

    for key, spec in sorted(contract.managed_regions.items()):
        if spec.managed_set not in enabled_sets or key in metadata.opt_out:
            continue
        current = root / spec.path
        candidate = candidate_root / spec.path
        if not current.is_file() or not candidate.is_file():
            conflicts.append(SyncConflict(spec.path, f"managed region {spec.region_id} file is missing"))
            continue
        previous = metadata.managed_regions.get(key)
        try:
            current_text = current.read_text(encoding="utf-8")
            candidate_text = candidate.read_text(encoding="utf-8")
            current_region = extract_region(current_text, spec.region_id)
            candidate_region = extract_region(candidate_text, spec.region_id)
        except SyncError as error:
            conflicts.append(SyncConflict(spec.path, str(error)))
            continue
        if previous and sha256_text(current_region.body) != previous.sha256:
            conflicts.append(SyncConflict(spec.path, f"managed region {spec.region_id} hash mismatch"))
            continue
        if current_region.body != candidate_region.body:
            region_changes.append(
                RegionChange(
                    path=spec.path,
                    region_id=spec.region_id,
                    new_text=replace_region(current_text, spec.region_id, candidate_region.body),
                    new_body=candidate_region.body,
                    new_sha256=sha256_text(candidate_region.body),
                    managed_set=spec.managed_set,
                )
            )

    return SyncPlan(
        file_changes=tuple(file_changes),
        region_changes=tuple(region_changes),
        conflicts=tuple(conflicts),
        migration_notes=contract.migration_notes,
        verification_commands=contract.verification_commands,
    )


def extract_region(text: str, region_id: str) -> RegionBody:
    begin = f"<!-- codex-bootstrap:begin {region_id} -->"
    end = f"<!-- codex-bootstrap:end {region_id} -->"
    begin_count = text.count(begin)
    end_count = text.count(end)
    if begin_count != 1 or end_count != 1:
        raise SyncError(f"managed region {region_id} marker count is begin={begin_count} end={end_count}")
    begin_index = text.index(begin) + len(begin)
    end_index = text.index(end)
    if end_index < begin_index:
        raise SyncError(f"managed region {region_id} end marker appears before begin marker")
    body = text[begin_index:end_index]
    if body.startswith("\n"):
        body = body[1:]
    return RegionBody(body=body)


def replace_region(text: str, region_id: str, body: str) -> str:
    begin = f"<!-- codex-bootstrap:begin {region_id} -->"
    end = f"<!-- codex-bootstrap:end {region_id} -->"
    extract_region(text, region_id)
    prefix, rest = text.split(begin, 1)
    _old_body, suffix = rest.split(end, 1)
    return f"{prefix}{begin}\n{body}{end}{suffix}"


def apply_sync_plan(
    root: Path,
    metadata: SyncMetadata,
    contract: SyncContract,
    plan: SyncPlan,
    new_commit: str,
) -> SyncMetadata:
    if plan.conflicts:
        raise SyncError("refusing to apply sync plan with conflicts")
    for change in plan.file_changes:
        destination = root / change.path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(change.new_text, encoding="utf-8")
    for change in plan.region_changes:
        destination = root / change.path
        destination.write_text(change.new_text, encoding="utf-8")

    managed_files = dict(metadata.managed_files)
    for change in plan.file_changes:
        managed_files[change.path] = ManagedFileState(
            managed_set=change.managed_set,
            sha256=change.new_sha256,
        )
    managed_regions = dict(metadata.managed_regions)
    for change in plan.region_changes:
        key = f"{change.path}:{change.region_id}"
        managed_regions[key] = ManagedRegionState(
            managed_set=change.managed_set,
            path=change.path,
            region_id=change.region_id,
            sha256=change.new_sha256,
        )

    updated = dataclasses.replace(
        metadata,
        source_commit=new_commit,
        contract_version=contract.version,
        managed_files=managed_files,
        managed_regions=managed_regions,
        verification_commands=contract.verification_commands,
    )
    write_sync_metadata(root, updated)
    write_sync_report(root, plan, updated)
    return updated


def write_sync_metadata(root: Path, metadata: SyncMetadata) -> None:
    destination = root / SYNC_METADATA
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(metadata.to_json(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_sync_report(root: Path, plan: SyncPlan, metadata: SyncMetadata) -> Path:
    reports = root / REPORTS_DIR
    reports.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    destination = reports / f"{timestamp}.json"
    payload = {
        "commit": metadata.source_commit,
        "fileChanges": [dataclasses.asdict(change) for change in plan.file_changes],
        "regionChanges": [dataclasses.asdict(change) for change in plan.region_changes],
        "conflicts": [dataclasses.asdict(conflict) for conflict in plan.conflicts],
        "verificationCommands": list(plan.verification_commands),
        "migrationNotes": list(plan.migration_notes),
    }
    destination.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


def run_checked(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = run_unchecked(command, cwd=cwd)
    if result.returncode != 0:
        raise SyncError(f"command failed with exit {result.returncode}: {' '.join(command)}\n{result.stdout}")
    return result


def run_unchecked(command: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        check=False,
    )


def read_git_status(root: Path) -> dict[str, str]:
    result = run_unchecked(["git", "status", "--porcelain=v1"], cwd=root)
    if result.returncode != 0:
        raise SyncError("sync requires a Git worktree")
    status: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if not line:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        status[normalize_path(path)] = "??" if code == "??" else code.strip() or code
    return status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Codex Bootstrap managed files.")
    subparsers = parser.add_subparsers(dest="command")
    sync_parser = subparsers.add_parser("sync")
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument("--apply", action="store_true")
    sync_parser.add_argument("--allow-dirty", action="store_true")
    sync_parser.add_argument("--project-root", type=Path, default=Path.cwd())
    sync_parser.add_argument("--candidate-root", type=Path)
    sync_parser.add_argument("--candidate-commit", default="unknown")
    sync_parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args(argv)
    if args.command != "sync":
        parser.print_help(sys.stderr)
        return 2
    try:
        return run_sync_command(args)
    except SyncError as error:
        print(f"agent-bootstrap: {error}", file=sys.stderr)
        return 2


def run_sync_command(args: argparse.Namespace) -> int:
    root = args.project_root.resolve()
    metadata = load_sync_metadata(root)
    if args.candidate_root is None:
        raise SyncError("--candidate-root is required until candidate regeneration is implemented")
    candidate_root = args.candidate_root.resolve()
    contract = load_sync_contract(candidate_root, metadata.template_id)
    git_status = getattr(args, "git_status_override", None)
    if git_status is None:
        git_status = read_git_status(root)
    if args.apply and git_status and not args.allow_dirty:
        print("Bootstrap sync refused: worktree has local changes; pass --allow-dirty to continue.")
        return 1
    plan = plan_managed_updates(root, candidate_root, metadata, contract, git_status=git_status)
    print_sync_plan(metadata, contract, plan, args.candidate_commit)
    if plan.conflicts:
        return 1
    if args.apply:
        apply_sync_plan(root, metadata, contract, plan, args.candidate_commit)
    return 0


def print_sync_plan(
    metadata: SyncMetadata,
    contract: SyncContract,
    plan: SyncPlan,
    candidate_commit: str,
) -> None:
    print("Bootstrap sync plan:")
    print(f"  template: {metadata.template_id}")
    print(f"  current-commit: {metadata.source_commit}")
    print(f"  candidate-commit: {candidate_commit}")
    print(f"  contract: {metadata.contract_version} -> {contract.version}")
    for change in plan.file_changes:
        print(f"  update-file: {change.path}")
    for change in plan.region_changes:
        print(f"  update-region: {change.path}#{change.region_id}")
    for conflict in plan.conflicts:
        print(f"  conflict: {conflict.path}: {conflict.reason}")
    for note in plan.migration_notes:
        print(f"  migration-note: {note}")
    for command in plan.verification_commands:
        print(f"  verify: {command}")


def normalize_path(value: str) -> str:
    normalized = Path(value).as_posix()
    if normalized.startswith("../") or normalized == ".." or normalized.startswith("/"):
        raise SyncError(f"path escapes project root: {value}")
    return normalized


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SyncError(f"invalid JSON in {path}: {error}") from error
    if not isinstance(raw, dict):
        raise SyncError(f"{path} must contain a JSON object")
    return raw


def require_object(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise SyncError(f"{key} must be an object")
    return value


def require_object_map(raw: dict[str, Any], key: str) -> dict[str, dict[str, Any]]:
    value = raw.get(key)
    if not isinstance(value, dict):
        raise SyncError(f"{key} must be an object")
    if not all(isinstance(item, dict) for item in value.values()):
        raise SyncError(f"{key} values must be objects")
    return value


def require_object_array(
    raw: dict[str, Any], key: str, allow_missing: bool = False
) -> list[dict[str, Any]]:
    value = raw.get(key, [] if allow_missing else None)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise SyncError(f"{key} must be an array of objects")
    return value


def require_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise SyncError(f"{key} must be a non-empty string")
    return value


def require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise SyncError(f"{key} must be an integer")
    return value


def require_string_list(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise SyncError(f"{key} must be an array of non-empty strings")
    return value


def require_string_map(raw: dict[str, Any], key: str) -> dict[str, str]:
    value = raw.get(key)
    if not isinstance(value, dict) or not all(
        isinstance(map_key, str)
        and map_key
        and isinstance(map_value, str)
        and map_value
        for map_key, map_value in value.items()
    ):
        raise SyncError(f"{key} must be an object of non-empty strings")
    return dict(value)


def require_sha256(raw: dict[str, Any], key: str) -> str:
    value = require_string(raw, key)
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise SyncError(f"{key} must be a lowercase SHA-256 hex digest")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
