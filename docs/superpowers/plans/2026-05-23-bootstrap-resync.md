# Bootstrap Resync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a sync-capable generated-project contract so downstream projects can pull later Codex Bootstrap managed-file and managed-region updates from GitHub without rerunning the destructive launcher.

**Architecture:** Add a small `tools/supermeta-bootstrap` Python package copied into generated projects, with `scripts/agent-bootstrap` wrappers that expose `sync --dry-run` and `sync --apply`. Extend template manifests and the bootstrap generator to write `.codex-bootstrap/sync.json`, track SHA-256 hashes for managed files and regions, and update only declared managed targets. Keep the current destructive `./bootstrap` creation flow intact.

**Tech Stack:** Python 3 standard library, `unittest`, shell and PowerShell wrappers, JSON template manifests, existing bootstrap smoke tests, existing Pages metadata builder.

---

## File Structure

- Create `tools/supermeta-bootstrap/bootstrap_sync.py`: core sync CLI, metadata parser, manifest parser, SHA-256 hashing, managed-region scanner, dry-run planner, apply writer, report writer, and candidate bootstrap regeneration.
- Create `tools/supermeta-bootstrap/bootstrap_sync_test.py`: focused unit tests for metadata validation, dry-run planning, whole-file updates, managed-region updates, conflict handling, report writing, and offline `--source-dir` operation.
- Create `tools/supermeta-bootstrap/README.md`: terse operator docs for the copied sync helper.
- Create `scripts/agent-bootstrap`: Unix wrapper that runs `tools/supermeta-bootstrap/bootstrap_sync.py`.
- Create `scripts/agent-bootstrap.ps1`: PowerShell wrapper equivalent.
- Modify `tools/bootstrap/bootstrap.py`: parse `syncContract`, copy the new bootstrap sync support paths, emit `.codex-bootstrap/sync.json`, emit `.codex-bootstrap/reports/.gitignore`, mark generated sync docs regions, and compute initial hashes.
- Modify `tools/bootstrap/bootstrap_test.py`: assert generated sync metadata, wrappers, support package, docs, dry-run behavior, and conflict behavior through generated-project smoke tests.
- Modify every `templates/*/bootstrap-template.json`: add `scripts/agent-bootstrap`, `scripts/agent-bootstrap.ps1`, and `tools/supermeta-bootstrap` support paths; add a `syncContract` section with managed sets and verification commands.
- Modify `tools/pages/build_pages.py`: include sync contract summary fields in `templates.json`.
- Modify `tools/pages/pages_test.py`: assert Pages metadata exposes sync capability.
- Modify `README.md`: document generated-project resync at the catalog level.
- Modify `CHANGELOG.md`: add an unreleased entry for the generated-project resync contract.

## Task 1: Core Sync Model Tests

**Files:**
- Create: `tools/supermeta-bootstrap/bootstrap_sync_test.py`
- Create: `tools/supermeta-bootstrap/__init__.py`

- [ ] **Step 1: Create failing tests for metadata and manifest parsing**

Create `tools/supermeta-bootstrap/__init__.py` as an empty package marker:

```python
"""Codex Bootstrap generated-project sync helpers."""
```

Create `tools/supermeta-bootstrap/bootstrap_sync_test.py` with these tests and helpers:

```python
from __future__ import annotations

import argparse
import json
import tempfile
import unittest
from pathlib import Path

import bootstrap_sync


class SyncModelTest(unittest.TestCase):
    def test_loads_sync_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-model-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "sync.json",
                {
                    "schemaVersion": 1,
                    "source": {
                        "repository": "file:///tmp/codex-bootstrap",
                        "ref": "main",
                        "commit": "0123456789abcdef0123456789abcdef01234567",
                    },
                    "template": {"id": "python-uv-cli", "contractVersion": 1},
                    "identity": {"projectName": "sample-app"},
                    "managedSets": ["agent-scripts"],
                    "optOut": [],
                    "managedFiles": {
                        "scripts/agent-bootstrap": {
                            "set": "agent-scripts",
                            "sha256": "a" * 64,
                        }
                    },
                    "managedRegions": {},
                    "verificationCommands": ["./scripts/check"],
                },
            )

            metadata = bootstrap_sync.load_sync_metadata(root)

            self.assertEqual(1, metadata.schema_version)
            self.assertEqual("file:///tmp/codex-bootstrap", metadata.source_repository)
            self.assertEqual("main", metadata.source_ref)
            self.assertEqual("0123456789abcdef0123456789abcdef01234567", metadata.source_commit)
            self.assertEqual("python-uv-cli", metadata.template_id)
            self.assertEqual(1, metadata.contract_version)
            self.assertEqual({"projectName": "sample-app"}, metadata.identity)
            self.assertEqual(("agent-scripts",), metadata.managed_sets)
            self.assertEqual(("scripts/agent-bootstrap",), tuple(metadata.managed_files))

    def test_rejects_missing_sync_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-missing-") as temp_dir:
            with self.assertRaisesRegex(bootstrap_sync.SyncError, "missing .codex-bootstrap/sync.json"):
                bootstrap_sync.load_sync_metadata(Path(temp_dir))

    def test_rejects_unsupported_schema(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-schema-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "sync.json",
                {
                    "schemaVersion": 99,
                    "source": {"repository": "x", "ref": "main", "commit": "c"},
                    "template": {"id": "java-gradle-cli", "contractVersion": 1},
                    "identity": {"projectName": "sample-app"},
                    "managedSets": [],
                    "optOut": [],
                    "managedFiles": {},
                    "managedRegions": {},
                    "verificationCommands": [],
                },
            )

            with self.assertRaisesRegex(bootstrap_sync.SyncError, "unsupported sync schema 99"):
                bootstrap_sync.load_sync_metadata(root)

    def test_loads_sync_contract_from_template_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-contract-") as temp_dir:
            catalog = Path(temp_dir)
            manifest = catalog / "templates" / "python-uv-cli" / "bootstrap-template.json"
            write_json(
                manifest,
                {
                    "id": "python-uv-cli",
                    "displayName": "Python uv CLI",
                    "description": "test",
                    "type": "python-uv-cli",
                    "requiredInputs": ["name"],
                    "supportPaths": [],
                    "verificationCommands": ["./scripts/check"],
                    "generatedDocs": {
                        "summary": "summary",
                        "runtime": "runtime",
                        "entrypoints": [],
                        "sourceRoots": [],
                        "testRoots": [],
                        "verificationCommands": [],
                        "runCommands": [],
                        "firstUsefulEdit": "edit",
                    },
                    "syncContract": {
                        "version": 1,
                        "managedSets": [
                            {
                                "id": "agent-scripts",
                                "description": "Agent scripts",
                                "files": [
                                    {"path": "scripts/agent-bootstrap", "mode": "whole-file"}
                                ],
                                "regions": [
                                    {
                                        "path": "AGENTS.md",
                                        "id": "generated-docs/bootstrap-sync",
                                    }
                                ],
                            }
                        ],
                        "verificationCommands": ["./scripts/check"],
                        "migrationNotes": ["Read the release notes."],
                    },
                },
            )

            contract = bootstrap_sync.load_sync_contract(catalog, "python-uv-cli")

            self.assertEqual(1, contract.version)
            self.assertEqual(("agent-scripts",), tuple(contract.managed_sets))
            self.assertEqual(("scripts/agent-bootstrap",), tuple(contract.managed_files))
            self.assertEqual(("AGENTS.md:generated-docs/bootstrap-sync",), tuple(contract.managed_regions))
            self.assertEqual(("Read the release notes.",), contract.migration_notes)

    def test_hashes_file_bytes_with_sha256(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-hash-") as temp_dir:
            path = Path(temp_dir) / "file.txt"
            path.write_text("hello\n", encoding="utf-8")

            self.assertEqual(
                "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03",
                bootstrap_sync.sha256_file(path),
            )


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

- [ ] **Step 2: Run tests and verify the missing module failure**

Run:

```bash
PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
```

Expected: FAIL with `ModuleNotFoundError: No module named 'bootstrap_sync'`.

- [ ] **Step 3: Commit the failing model tests**

```bash
git add tools/supermeta-bootstrap/__init__.py tools/supermeta-bootstrap/bootstrap_sync_test.py
git commit -m "test: cover bootstrap sync model"
```

## Task 2: Core Sync Model Implementation

**Files:**
- Create: `tools/supermeta-bootstrap/bootstrap_sync.py`
- Test: `tools/supermeta-bootstrap/bootstrap_sync_test.py`

- [ ] **Step 1: Implement metadata, contract, and hash primitives**

Create `tools/supermeta-bootstrap/bootstrap_sync.py`:

```python
#!/usr/bin/env python3
"""Managed resync for Codex Bootstrap generated projects."""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
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


def load_sync_metadata(root: Path) -> SyncMetadata:
    metadata_path = root / SYNC_METADATA
    if not metadata_path.is_file():
        raise SyncError("missing .codex-bootstrap/sync.json; this project is not sync-enabled")
    raw = load_json_object(metadata_path)
    schema_version = require_int(raw, "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise SyncError(f"unsupported sync schema {schema_version}; supported schema is {SCHEMA_VERSION}")
    source = require_object(raw, "source")
    template = require_object(raw, "template")
    identity = require_string_map(raw, "identity")
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
        identity=identity,
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


def require_object_array(raw: dict[str, Any], key: str, allow_missing: bool = False) -> list[dict[str, Any]]:
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
```

- [ ] **Step 2: Run model tests and verify they pass**

Run:

```bash
PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 3: Commit the model implementation**

```bash
git add tools/supermeta-bootstrap/bootstrap_sync.py tools/supermeta-bootstrap/bootstrap_sync_test.py
git commit -m "feat: add bootstrap sync model"
```

## Task 3: Managed File And Region Planner

**Files:**
- Modify: `tools/supermeta-bootstrap/bootstrap_sync.py`
- Modify: `tools/supermeta-bootstrap/bootstrap_sync_test.py`

- [ ] **Step 1: Add failing tests for whole-file and managed-region planning**

Append to `tools/supermeta-bootstrap/bootstrap_sync_test.py`:

```python
class SyncPlannerTest(unittest.TestCase):
    def test_plans_whole_file_update_when_current_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-plan-file-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            write_text(root / "scripts" / "agent-bootstrap", "old\n")
            write_text(candidate / "scripts" / "agent-bootstrap", "new\n")
            metadata = metadata_for_files(
                root,
                managed_files={
                    "scripts/agent-bootstrap": {
                        "set": "agent-scripts",
                        "sha256": bootstrap_sync.sha256_file(root / "scripts" / "agent-bootstrap"),
                    }
                },
            )
            contract = contract_for(
                files=[bootstrap_sync.ManagedFileSpec("scripts/agent-bootstrap", "agent-scripts")]
            )

            plan = bootstrap_sync.plan_managed_updates(root, candidate, metadata, contract, git_status={})

            self.assertEqual([], plan.conflicts)
            self.assertEqual(("scripts/agent-bootstrap",), tuple(change.path for change in plan.file_changes))
            self.assertEqual("new\n", plan.file_changes[0].new_text)

    def test_conflicts_whole_file_update_when_current_hash_changed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-plan-conflict-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            write_text(root / "scripts" / "agent-bootstrap", "locally edited\n")
            write_text(candidate / "scripts" / "agent-bootstrap", "new\n")
            metadata = metadata_for_files(
                root,
                managed_files={
                    "scripts/agent-bootstrap": {
                        "set": "agent-scripts",
                        "sha256": "0" * 64,
                    }
                },
            )
            contract = contract_for(
                files=[bootstrap_sync.ManagedFileSpec("scripts/agent-bootstrap", "agent-scripts")]
            )

            plan = bootstrap_sync.plan_managed_updates(root, candidate, metadata, contract, git_status={})

            self.assertEqual([], plan.file_changes)
            self.assertEqual("scripts/agent-bootstrap", plan.conflicts[0].path)
            self.assertIn("hash mismatch", plan.conflicts[0].reason)

    def test_refuses_untracked_whole_file_overwrite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-plan-untracked-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            write_text(root / "scripts" / "agent-bootstrap", "local\n")
            write_text(candidate / "scripts" / "agent-bootstrap", "new\n")
            metadata = metadata_for_files(root, managed_files={})
            contract = contract_for(
                files=[bootstrap_sync.ManagedFileSpec("scripts/agent-bootstrap", "agent-scripts")]
            )

            plan = bootstrap_sync.plan_managed_updates(
                root,
                candidate,
                metadata,
                contract,
                git_status={"scripts/agent-bootstrap": "??"},
            )

            self.assertEqual([], plan.file_changes)
            self.assertIn("untracked file would be overwritten", plan.conflicts[0].reason)

    def test_plans_managed_region_update(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-plan-region-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            old_region = managed_region("generated-docs/bootstrap-sync", "old commands\n")
            new_region = managed_region("generated-docs/bootstrap-sync", "new commands\n")
            write_text(root / "AGENTS.md", f"# Agents\n\n{old_region}\n")
            write_text(candidate / "AGENTS.md", f"# Agents\n\n{new_region}\n")
            metadata = metadata_for_regions(
                root,
                managed_regions={
                    "AGENTS.md:generated-docs/bootstrap-sync": {
                        "set": "generated-docs",
                        "path": "AGENTS.md",
                        "id": "generated-docs/bootstrap-sync",
                        "sha256": bootstrap_sync.sha256_text("old commands\n"),
                    }
                },
            )
            contract = contract_for(
                regions=[
                    bootstrap_sync.ManagedRegionSpec(
                        path="AGENTS.md",
                        region_id="generated-docs/bootstrap-sync",
                        managed_set="generated-docs",
                    )
                ]
            )

            plan = bootstrap_sync.plan_managed_updates(root, candidate, metadata, contract, git_status={})

            self.assertEqual([], plan.conflicts)
            self.assertEqual("AGENTS.md", plan.region_changes[0].path)
            self.assertIn("new commands", plan.region_changes[0].new_text)

    def test_conflicts_missing_region_marker(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-plan-missing-region-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            write_text(root / "AGENTS.md", "# Agents\n")
            write_text(candidate / "AGENTS.md", managed_region("generated-docs/bootstrap-sync", "new\n"))
            metadata = metadata_for_regions(
                root,
                managed_regions={
                    "AGENTS.md:generated-docs/bootstrap-sync": {
                        "set": "generated-docs",
                        "path": "AGENTS.md",
                        "id": "generated-docs/bootstrap-sync",
                        "sha256": bootstrap_sync.sha256_text("old\n"),
                    }
                },
            )
            contract = contract_for(
                regions=[
                    bootstrap_sync.ManagedRegionSpec(
                        path="AGENTS.md",
                        region_id="generated-docs/bootstrap-sync",
                        managed_set="generated-docs",
                    )
                ]
            )

            plan = bootstrap_sync.plan_managed_updates(root, candidate, metadata, contract, git_status={})

            self.assertEqual([], plan.region_changes)
            self.assertIn("marker count", plan.conflicts[0].reason)
```

Add helper functions at the bottom:

```python
def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def managed_region(region_id: str, body: str) -> str:
    return (
        f"<!-- codex-bootstrap:begin {region_id} -->\n"
        f"{body}"
        f"<!-- codex-bootstrap:end {region_id} -->"
    )


def metadata_for_files(root: Path, managed_files: dict[str, dict[str, str]]) -> bootstrap_sync.SyncMetadata:
    return metadata_for(root, managed_files=managed_files, managed_regions={})


def metadata_for_regions(root: Path, managed_regions: dict[str, dict[str, str]]) -> bootstrap_sync.SyncMetadata:
    return metadata_for(root, managed_files={}, managed_regions=managed_regions)


def metadata_for(
    root: Path,
    managed_files: dict[str, dict[str, str]],
    managed_regions: dict[str, dict[str, str]],
) -> bootstrap_sync.SyncMetadata:
    write_json(
        root / ".codex-bootstrap" / "sync.json",
        {
            "schemaVersion": 1,
            "source": {
                "repository": "file:///tmp/codex-bootstrap",
                "ref": "main",
                "commit": "0123456789abcdef0123456789abcdef01234567",
            },
            "template": {"id": "python-uv-cli", "contractVersion": 1},
            "identity": {"projectName": "sample-app"},
            "managedSets": ["agent-scripts", "generated-docs"],
            "optOut": [],
            "managedFiles": managed_files,
            "managedRegions": managed_regions,
            "verificationCommands": ["./scripts/check"],
        },
    )
    return bootstrap_sync.load_sync_metadata(root)


def contract_for(
    files: list[bootstrap_sync.ManagedFileSpec] | None = None,
    regions: list[bootstrap_sync.ManagedRegionSpec] | None = None,
) -> bootstrap_sync.SyncContract:
    managed_sets = {
        "agent-scripts": bootstrap_sync.ManagedSetSpec(
            managed_set="agent-scripts",
            description="Agent scripts",
            files=tuple(files or []),
            regions=(),
        ),
        "generated-docs": bootstrap_sync.ManagedSetSpec(
            managed_set="generated-docs",
            description="Generated docs",
            files=(),
            regions=tuple(regions or []),
        ),
    }
    return bootstrap_sync.SyncContract(
        version=1,
        managed_sets=managed_sets,
        verification_commands=("./scripts/check",),
        migration_notes=(),
    )
```

- [ ] **Step 2: Run planner tests and verify the missing function failure**

Run:

```bash
PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
```

Expected: FAIL with `AttributeError: module 'bootstrap_sync' has no attribute 'plan_managed_updates'`.

- [ ] **Step 3: Implement planner dataclasses and region extraction**

Append to `tools/supermeta-bootstrap/bootstrap_sync.py` after `SyncContract`:

```python
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
```

Append these helpers:

```python
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
            current_region = extract_region(current.read_text(encoding="utf-8"), spec.region_id)
            candidate_region = extract_region(candidate.read_text(encoding="utf-8"), spec.region_id)
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
                    new_text=replace_region(
                        current.read_text(encoding="utf-8"),
                        spec.region_id,
                        candidate_region.body,
                    ),
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


@dataclass(frozen=True)
class RegionBody:
    body: str


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
```

- [ ] **Step 4: Run planner tests and verify they pass**

Run:

```bash
PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 5: Commit the planner**

```bash
git add tools/supermeta-bootstrap/bootstrap_sync.py tools/supermeta-bootstrap/bootstrap_sync_test.py
git commit -m "feat: plan managed bootstrap sync updates"
```

## Task 4: Apply, Reports, Git State, And CLI

**Files:**
- Modify: `tools/supermeta-bootstrap/bootstrap_sync.py`
- Modify: `tools/supermeta-bootstrap/bootstrap_sync_test.py`
- Create: `tools/supermeta-bootstrap/README.md`

- [ ] **Step 1: Add failing tests for apply, reports, dirty checks, and CLI output**

Append to `tools/supermeta-bootstrap/bootstrap_sync_test.py`:

```python
class SyncApplyTest(unittest.TestCase):
    def test_apply_writes_files_regions_report_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-apply-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            write_text(root / "scripts" / "agent-bootstrap", "old\n")
            write_text(candidate / "scripts" / "agent-bootstrap", "new\n")
            write_text(root / "AGENTS.md", managed_region("generated-docs/bootstrap-sync", "old\n"))
            write_text(candidate / "AGENTS.md", managed_region("generated-docs/bootstrap-sync", "new\n"))
            metadata = metadata_for(
                root,
                managed_files={
                    "scripts/agent-bootstrap": {
                        "set": "agent-scripts",
                        "sha256": bootstrap_sync.sha256_file(root / "scripts" / "agent-bootstrap"),
                    }
                },
                managed_regions={
                    "AGENTS.md:generated-docs/bootstrap-sync": {
                        "set": "generated-docs",
                        "path": "AGENTS.md",
                        "id": "generated-docs/bootstrap-sync",
                        "sha256": bootstrap_sync.sha256_text("old\n"),
                    }
                },
            )
            contract = contract_for(
                files=[bootstrap_sync.ManagedFileSpec("scripts/agent-bootstrap", "agent-scripts")],
                regions=[
                    bootstrap_sync.ManagedRegionSpec(
                        path="AGENTS.md",
                        region_id="generated-docs/bootstrap-sync",
                        managed_set="generated-docs",
                    )
                ],
            )
            plan = bootstrap_sync.plan_managed_updates(root, candidate, metadata, contract, git_status={})

            updated = bootstrap_sync.apply_sync_plan(
                root,
                metadata,
                contract,
                plan,
                new_commit="abcdef0123456789abcdef0123456789abcdef01",
            )

            self.assertEqual("new\n", (root / "scripts" / "agent-bootstrap").read_text(encoding="utf-8"))
            self.assertIn("new", (root / "AGENTS.md").read_text(encoding="utf-8"))
            self.assertEqual("abcdef0123456789abcdef0123456789abcdef01", updated.source_commit)
            self.assertTrue(any((root / ".codex-bootstrap" / "reports").glob("*.json")))
            persisted = bootstrap_sync.load_sync_metadata(root)
            self.assertEqual("abcdef0123456789abcdef0123456789abcdef01", persisted.source_commit)

    def test_cli_dry_run_prints_no_changes_for_matching_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-cli-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            write_text(root / "scripts" / "agent-bootstrap", "same\n")
            write_text(candidate / "scripts" / "agent-bootstrap", "same\n")
            metadata_for(
                root,
                managed_files={
                    "scripts/agent-bootstrap": {
                        "set": "agent-scripts",
                        "sha256": bootstrap_sync.sha256_file(root / "scripts" / "agent-bootstrap"),
                    }
                },
                managed_regions={},
            )
            write_json(
                candidate / "templates" / "python-uv-cli" / "bootstrap-template.json",
                manifest_with_sync_contract(files=["scripts/agent-bootstrap"]),
            )
            commit_project_snapshot(root)

            exit_code = bootstrap_sync.main(
                [
                    "sync",
                    "--dry-run",
                    "--project-root",
                    str(root),
                    "--candidate-root",
                    str(candidate),
                    "--candidate-commit",
                    "abcdef0123456789abcdef0123456789abcdef01",
                ]
            )

            self.assertEqual(0, exit_code)

    def test_refuses_apply_with_conflicts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-cli-conflict-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            write_text(root / "scripts" / "agent-bootstrap", "edited\n")
            write_text(candidate / "scripts" / "agent-bootstrap", "new\n")
            metadata_for(
                root,
                managed_files={
                    "scripts/agent-bootstrap": {
                        "set": "agent-scripts",
                        "sha256": "0" * 64,
                    }
                },
                managed_regions={},
            )
            write_json(
                candidate / "templates" / "python-uv-cli" / "bootstrap-template.json",
                manifest_with_sync_contract(files=["scripts/agent-bootstrap"]),
            )
            commit_project_snapshot(root)

            exit_code = bootstrap_sync.main(
                [
                    "sync",
                    "--apply",
                    "--project-root",
                    str(root),
                    "--candidate-root",
                    str(candidate),
                    "--candidate-commit",
                    "abcdef0123456789abcdef0123456789abcdef01",
                ]
            )

            self.assertEqual(1, exit_code)
            self.assertEqual("edited\n", (root / "scripts" / "agent-bootstrap").read_text(encoding="utf-8"))

    def test_read_git_status_reports_untracked_and_modified_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-git-status-") as temp_dir:
            root = Path(temp_dir)
            bootstrap_sync.run_checked(["git", "init"], cwd=root)
            write_text(root / "tracked.txt", "old\n")
            bootstrap_sync.run_checked(["git", "add", "tracked.txt"], cwd=root)
            bootstrap_sync.run_checked(
                [
                    "git",
                    "-c",
                    "user.name=Codex Bootstrap Test",
                    "-c",
                    "user.email=codex-bootstrap@example.invalid",
                    "commit",
                    "-m",
                    "snapshot",
                ],
                cwd=root,
            )
            write_text(root / "tracked.txt", "new\n")
            write_text(root / "untracked.txt", "local\n")

            status = bootstrap_sync.read_git_status(root)

            self.assertEqual("M", status["tracked.txt"])
            self.assertEqual("??", status["untracked.txt"])

    def test_apply_refuses_dirty_worktree_without_allow_dirty(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-dirty-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            write_text(root / "scripts" / "agent-bootstrap", "same\n")
            write_text(candidate / "scripts" / "agent-bootstrap", "same\n")
            metadata_for(
                root,
                managed_files={
                    "scripts/agent-bootstrap": {
                        "set": "agent-scripts",
                        "sha256": bootstrap_sync.sha256_file(root / "scripts" / "agent-bootstrap"),
                    }
                },
                managed_regions={},
            )
            write_json(
                candidate / "templates" / "python-uv-cli" / "bootstrap-template.json",
                manifest_with_sync_contract(files=["scripts/agent-bootstrap"]),
            )

            exit_code = bootstrap_sync.run_sync_command(
                argparse.Namespace(
                    project_root=root,
                    candidate_root=candidate,
                    candidate_commit="abcdef0123456789abcdef0123456789abcdef01",
                    source_dir=None,
                    apply=True,
                    dry_run=False,
                    allow_dirty=False,
                    git_status_override={"scripts/agent-bootstrap": "M"},
                )
            )

            self.assertEqual(1, exit_code)
```

Add helper:

```python
def manifest_with_sync_contract(files: list[str]) -> dict[str, object]:
    return {
        "id": "python-uv-cli",
        "displayName": "Python uv CLI",
        "description": "test",
        "type": "python-uv-cli",
        "requiredInputs": ["name"],
        "supportPaths": [],
        "verificationCommands": ["./scripts/check"],
        "generatedDocs": {
            "summary": "summary",
            "runtime": "runtime",
            "entrypoints": [],
            "sourceRoots": [],
            "testRoots": [],
            "verificationCommands": [],
            "runCommands": [],
            "firstUsefulEdit": "edit",
        },
        "syncContract": {
            "version": 1,
            "managedSets": [
                {
                    "id": "agent-scripts",
                    "description": "Agent scripts",
                    "files": [{"path": path, "mode": "whole-file"} for path in files],
                    "regions": [],
                }
            ],
            "verificationCommands": ["./scripts/check"],
            "migrationNotes": [],
        },
    }


def commit_project_snapshot(root: Path) -> None:
    bootstrap_sync.run_checked(["git", "init"], cwd=root)
    bootstrap_sync.run_checked(["git", "add", "."], cwd=root)
    bootstrap_sync.run_checked(
        [
            "git",
            "-c",
            "user.name=Codex Bootstrap Test",
            "-c",
            "user.email=codex-bootstrap@example.invalid",
            "commit",
            "-m",
            "snapshot",
        ],
        cwd=root,
    )
```

- [ ] **Step 2: Run tests and verify apply/CLI functions are missing**

Run:

```bash
PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
```

Expected: FAIL with missing `apply_sync_plan` or `main`.

- [ ] **Step 3: Implement apply, report, metadata persistence, and CLI**

Append to `tools/supermeta-bootstrap/bootstrap_sync.py`:

```python
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
    destination.write_text(json.dumps(metadata.to_json(), indent=2, sort_keys=True) + "\n", encoding="utf-8")


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


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add README for the helper**

Create `tools/supermeta-bootstrap/README.md`:

```markdown
# Supermeta Bootstrap Sync

`bootstrap_sync.py` is copied into generated projects and updates only Codex
Bootstrap managed files and managed regions.

Use dry-run first:

```bash
./scripts/agent-bootstrap sync --dry-run
```

Apply when the plan has no conflicts:

```bash
./scripts/agent-bootstrap sync --apply
```
```

- [ ] **Step 5: Run sync helper tests**

Run:

```bash
PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 6: Commit apply and CLI behavior**

```bash
git add tools/supermeta-bootstrap
git commit -m "feat: apply managed bootstrap sync updates"
```

## Task 5: Candidate Regeneration And Wrappers

**Files:**
- Modify: `tools/supermeta-bootstrap/bootstrap_sync.py`
- Modify: `tools/supermeta-bootstrap/bootstrap_sync_test.py`
- Create: `scripts/agent-bootstrap`
- Create: `scripts/agent-bootstrap.ps1`

- [ ] **Step 1: Add failing tests for wrapper static contract and local source regeneration**

Append to `tools/supermeta-bootstrap/bootstrap_sync_test.py`:

```python
class CandidateRegenerationTest(unittest.TestCase):
    def test_builds_bootstrap_args_from_identity(self) -> None:
        metadata = bootstrap_sync.SyncMetadata(
            schema_version=1,
            source_repository="file:///tmp/codex-bootstrap",
            source_ref="main",
            source_commit="old",
            template_id="java-gradle-cli",
            contract_version=1,
            identity={"projectName": "sample-app", "javaPackage": "com.acme.sample"},
            managed_sets=("agent-scripts",),
            opt_out=(),
            managed_files={},
            managed_regions={},
            verification_commands=(),
        )

        self.assertEqual(
            [
                "./bootstrap",
                "--template",
                "java-gradle-cli",
                "--name",
                "sample-app",
                "--yes",
                "--package",
                "com.acme.sample",
            ],
            bootstrap_sync.bootstrap_args(metadata),
        )

    def test_agent_bootstrap_unix_wrapper_points_at_sync_helper(self) -> None:
        wrapper = (Path(__file__).resolve().parents[2] / "scripts" / "agent-bootstrap").read_text(
            encoding="utf-8"
        )

        self.assertIn("tools/supermeta-bootstrap/bootstrap_sync.py", wrapper)
        self.assertIn('exec python3 "$repo_root/tools/supermeta-bootstrap/bootstrap_sync.py" "$@"', wrapper)

    def test_agent_bootstrap_powershell_wrapper_points_at_sync_helper(self) -> None:
        wrapper = (Path(__file__).resolve().parents[2] / "scripts" / "agent-bootstrap.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("tools/supermeta-bootstrap/bootstrap_sync.py", wrapper)
        self.assertIn("Invoke-PythonChecked", wrapper)
```

- [ ] **Step 2: Run tests and verify wrapper files/functions are missing**

Run:

```bash
PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
```

Expected: FAIL with missing `bootstrap_args` or missing wrapper files.

- [ ] **Step 3: Implement candidate regeneration helpers**

Add to `tools/supermeta-bootstrap/bootstrap_sync.py` before `main()`:

```python
def bootstrap_args(metadata: SyncMetadata) -> list[str]:
    project_name = metadata.identity.get("projectName")
    if not project_name:
        raise SyncError("sync identity is missing projectName")
    args = [
        "./bootstrap",
        "--template",
        metadata.template_id,
        "--name",
        project_name,
        "--yes",
    ]
    java_package = metadata.identity.get("javaPackage")
    if metadata.template_id == "java-gradle-cli":
        if not java_package:
            raise SyncError("Java sync identity is missing javaPackage")
        args.extend(["--package", java_package])
    return args


def prepare_candidate_from_source(metadata: SyncMetadata, source_dir: Path | None) -> tuple[Path, str, tempfile.TemporaryDirectory[str] | None]:
    temp_dir = tempfile.TemporaryDirectory(prefix="codex-bootstrap-sync-")
    checkout = Path(temp_dir.name) / "source"
    if source_dir is not None:
        shutil.copytree(source_dir, checkout, ignore=shutil.ignore_patterns(".git"))
        commit = git_output(["git", "rev-parse", "HEAD"], cwd=source_dir, fallback="local-source")
        return checkout, commit, temp_dir
    run_checked(["git", "clone", "--depth", "1", metadata.source_repository, str(checkout)], cwd=Path.cwd())
    if run_unchecked(["git", "-C", str(checkout), "checkout", "--detach", metadata.source_ref]).returncode != 0:
        run_checked(["git", "-C", str(checkout), "fetch", "--depth", "1", "origin", metadata.source_ref], cwd=Path.cwd())
        run_checked(["git", "-C", str(checkout), "checkout", "--detach", "FETCH_HEAD"], cwd=Path.cwd())
    commit = git_output(["git", "rev-parse", "HEAD"], cwd=checkout, fallback="unknown")
    return checkout, commit, temp_dir


def regenerate_candidate_project(source_root: Path, metadata: SyncMetadata) -> Path:
    run_checked(bootstrap_args(metadata), cwd=source_root)
    return source_root


def git_output(command: list[str], cwd: Path, fallback: str) -> str:
    result = run_unchecked(command, cwd=cwd)
    if result.returncode != 0:
        return fallback
    return result.stdout.strip() or fallback
```

Update CLI parser:

```python
    sync_parser.add_argument("--source-dir", type=Path)
```

Update `run_sync_command()`:

```python
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    try:
        if args.candidate_root is not None:
            candidate_root = args.candidate_root.resolve()
            candidate_commit = args.candidate_commit
            contract = load_sync_contract(candidate_root, metadata.template_id)
        else:
            source_root, candidate_commit, temp_dir = prepare_candidate_from_source(
                metadata,
                args.source_dir.resolve() if args.source_dir else None,
            )
            contract = load_sync_contract(source_root, metadata.template_id)
            candidate_root = regenerate_candidate_project(source_root, metadata)
        git_status = getattr(args, "git_status_override", None)
        if git_status is None:
            git_status = read_git_status(root)
        if args.apply and git_status and not args.allow_dirty:
            print("Bootstrap sync refused: worktree has local changes; pass --allow-dirty to continue.")
            return 1
        plan = plan_managed_updates(root, candidate_root, metadata, contract, git_status=git_status)
        print_sync_plan(metadata, contract, plan, candidate_commit)
        if plan.conflicts:
            return 1
        if args.apply:
            apply_sync_plan(root, metadata, contract, plan, candidate_commit)
        return 0
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()
```

- [ ] **Step 4: Create Unix wrapper**

Create `scripts/agent-bootstrap`:

```sh
#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd "$script_dir/.." && pwd)

exec python3 "$repo_root/tools/supermeta-bootstrap/bootstrap_sync.py" "$@"
```

Run:

```bash
chmod +x scripts/agent-bootstrap
```

- [ ] **Step 5: Create PowerShell wrapper**

Create `scripts/agent-bootstrap.ps1`:

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

    [Console]::Error.WriteLine("scripts/agent-bootstrap.ps1: python3, python, or py is required")
    exit 2
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$syncScript = Join-Path $repoRoot "tools/supermeta-bootstrap/bootstrap_sync.py"
$pythonArgs = @($syncScript)
$pythonArgs += $args
Invoke-PythonChecked @pythonArgs
```

- [ ] **Step 6: Run wrapper and helper tests**

Run:

```bash
bash -n scripts/agent-bootstrap
PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 7: Commit candidate regeneration and wrappers**

```bash
git add scripts/agent-bootstrap scripts/agent-bootstrap.ps1 tools/supermeta-bootstrap
git commit -m "feat: add bootstrap sync wrappers"
```

## Task 6: Bootstrap Manifest Parsing And Generated Metadata

**Files:**
- Modify: `tools/bootstrap/bootstrap.py`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add failing bootstrap tests for sync metadata and support paths**

Modify `ManifestTest.test_loads_java_template_manifest` in `tools/bootstrap/bootstrap_test.py` after the existing `support_paths` assertion:

```python
        self.assertEqual(1, manifest.sync_contract.version)
        self.assertIn("agent-scripts", manifest.sync_contract.managed_sets)
        self.assertIn("scripts/agent-bootstrap", manifest.sync_contract.managed_files)
        self.assertIn("AGENTS.md:generated-docs/bootstrap-sync", manifest.sync_contract.managed_regions)
```

Modify the Java bootstrap smoke test after support path assertions:

```python
            self.assertTrue((checkout / ".codex-bootstrap" / "sync.json").is_file())
            self.assertTrue((checkout / ".codex-bootstrap" / "reports" / ".gitignore").is_file())
            self.assertTrue((checkout / "scripts" / "agent-bootstrap").is_file())
            self.assertTrue((checkout / "scripts" / "agent-bootstrap.ps1").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-bootstrap" / "bootstrap_sync.py").is_file())

            sync_metadata = json.loads((checkout / ".codex-bootstrap" / "sync.json").read_text(encoding="utf-8"))
            self.assertEqual(1, sync_metadata["schemaVersion"])
            self.assertEqual("java-gradle-cli", sync_metadata["template"]["id"])
            self.assertEqual("sample-app", sync_metadata["identity"]["projectName"])
            self.assertEqual("com.acme.sample", sync_metadata["identity"]["javaPackage"])
            self.assertIn("agent-scripts", sync_metadata["managedSets"])
            self.assertIn("scripts/agent-bootstrap", sync_metadata["managedFiles"])
            self.assertIn("AGENTS.md:generated-docs/bootstrap-sync", sync_metadata["managedRegions"])
```

- [ ] **Step 2: Run bootstrap tests and verify missing sync fields**

Run:

```bash
python3 -m unittest tools.bootstrap.bootstrap_test.ManifestTest.test_loads_java_template_manifest
```

Expected: FAIL with missing `sync_contract` or empty sync contract.

- [ ] **Step 3: Add sync dataclasses to bootstrap.py**

In `tools/bootstrap/bootstrap.py`, add dataclasses after `GeneratedDocs`:

```python
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
```

Add `sync_contract: SyncContract` to `TemplateManifest`, parse it in `load()`, and pass it to the constructor:

```python
        sync_contract = parse_sync_contract(raw.get("syncContract"))
```

```python
            sync_contract=sync_contract,
```

- [ ] **Step 4: Parse sync contract in bootstrap.py**

Add parser functions near `parse_generated_docs()`:

```python
def parse_sync_contract(raw: Any) -> SyncContract:
    if not isinstance(raw, dict):
        raise UsageError("syncContract must be an object")
    managed_sets: dict[str, ManagedSetSpec] = {}
    for index, item in enumerate(require_object_list(raw, "managedSets")):
        managed_set = require_string(item, "id")
        files = tuple(
            ManagedFileSpec(
                path=require_string(file_item, "path"),
                managed_set=managed_set,
            )
            for file_item in require_object_list(item, "files", allow_missing=True)
            if require_string(file_item, "mode") == "whole-file"
        )
        regions = tuple(
            ManagedRegionSpec(
                path=require_string(region_item, "path"),
                region_id=require_string(region_item, "id"),
                managed_set=managed_set,
            )
            for region_item in require_object_list(item, "regions", allow_missing=True)
        )
        if managed_set in managed_sets:
            raise UsageError(f"syncContract managedSets[{index}] duplicates id {managed_set}")
        managed_sets[managed_set] = ManagedSetSpec(
            managed_set=managed_set,
            description=require_string(item, "description"),
            files=files,
            regions=regions,
        )
    return SyncContract(
        version=require_int(raw, "version"),
        managed_sets=managed_sets,
        verification_commands=tuple(require_string_list(raw, "verificationCommands")),
        migration_notes=tuple(require_string_list(raw, "migrationNotes")),
    )


def require_object_list(raw: dict[str, Any], key: str, allow_missing: bool = False) -> list[dict[str, Any]]:
    value = raw.get(key, [] if allow_missing else None)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise UsageError(f"{key} must be an array of objects")
    return value


def require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise UsageError(f"{key} must be an integer")
    return value
```

- [ ] **Step 5: Emit sync metadata after generated docs and beads**

In `stage_template()`, after the rewriter call:

```python
    write_sync_metadata(plan, staged_root)
```

Add helpers near `write_generated_beads()`:

```python
def write_sync_metadata(plan: BootstrapPlan, staged_root: Path) -> None:
    sync_dir = staged_root / ".codex-bootstrap"
    reports_dir = sync_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    metadata = {
        "schemaVersion": 1,
        "source": {
            "repository": detect_source_repository(plan.repo_root),
            "ref": detect_source_ref(plan.repo_root),
            "commit": detect_source_commit(plan.repo_root),
        },
        "template": {
            "id": plan.manifest.template_id,
            "contractVersion": plan.manifest.sync_contract.version,
        },
        "identity": sync_identity(plan),
        "managedSets": sorted(plan.manifest.sync_contract.managed_sets),
        "optOut": [],
        "managedFiles": managed_file_hashes(plan, staged_root),
        "managedRegions": managed_region_hashes(plan, staged_root),
        "verificationCommands": list(plan.manifest.sync_contract.verification_commands),
    }
    (sync_dir / "sync.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sync_identity(plan: BootstrapPlan) -> dict[str, str]:
    identity = {"projectName": plan.config.project_name}
    if plan.config.package_name is not None:
        identity["javaPackage"] = plan.config.package_name
    return identity


def managed_file_hashes(plan: BootstrapPlan, staged_root: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path, spec in sorted(plan.manifest.sync_contract.managed_files.items()):
        target = staged_root / path
        if not target.is_file():
            raise UsageError(f"sync managed file does not exist after bootstrap: {path}")
        result[path] = {"set": spec.managed_set, "sha256": sha256_file(target)}
    return result


def managed_region_hashes(plan: BootstrapPlan, staged_root: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for key, spec in sorted(plan.manifest.sync_contract.managed_regions.items()):
        target = staged_root / spec.path
        if not target.is_file():
            raise UsageError(f"sync managed region file does not exist after bootstrap: {spec.path}")
        body = extract_managed_region(target.read_text(encoding="utf-8"), spec.region_id)
        result[key] = {
            "set": spec.managed_set,
            "path": spec.path,
            "id": spec.region_id,
            "sha256": sha256_text(body),
        }
    return result


def extract_managed_region(text: str, region_id: str) -> str:
    begin = f"<!-- codex-bootstrap:begin {region_id} -->"
    end = f"<!-- codex-bootstrap:end {region_id} -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise UsageError(f"sync managed region {region_id} must have exactly one begin and end marker")
    begin_index = text.index(begin) + len(begin)
    end_index = text.index(end)
    body = text[begin_index:end_index]
    if body.startswith("\n"):
        body = body[1:]
    return body


def sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def detect_source_repository(repo_root: Path) -> str:
    return git_output_or(repo_root, ["git", "remote", "get-url", "origin"], "https://github.com/Jamezz/codex-bootstrap.git")


def detect_source_ref(repo_root: Path) -> str:
    return git_output_or(repo_root, ["git", "branch", "--show-current"], "main") or "main"


def detect_source_commit(repo_root: Path) -> str:
    return git_output_or(repo_root, ["git", "rev-parse", "HEAD"], "unknown")


def git_output_or(repo_root: Path, command: list[str], fallback: str) -> str:
    result = subprocess.run(
        command,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return fallback
    return result.stdout.strip() or fallback
```

- [ ] **Step 6: Run focused bootstrap tests**

Run:

```bash
python3 -m unittest tools.bootstrap.bootstrap_test.ManifestTest.test_loads_java_template_manifest
```

Expected: still FAIL until manifests include `syncContract`.

- [ ] **Step 7: Commit parser and generator scaffolding**

```bash
git add tools/bootstrap/bootstrap.py tools/bootstrap/bootstrap_test.py
git commit -m "feat: parse bootstrap sync contracts"
```

## Task 7: Template Manifests And Generated Sync Docs

**Files:**
- Modify: `templates/csharp-dotnet-cli/bootstrap-template.json`
- Modify: `templates/java-gradle-cli/bootstrap-template.json`
- Modify: `templates/python-uv-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-mcp-server/bootstrap-template.json`
- Modify: `tools/bootstrap/bootstrap.py`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add sync support paths to each template manifest**

In every `templates/*/bootstrap-template.json`, add these entries to `supportPaths`:

```json
{
  "source": "scripts/agent-bootstrap",
  "destination": "scripts/agent-bootstrap"
},
{
  "source": "scripts/agent-bootstrap.ps1",
  "destination": "scripts/agent-bootstrap.ps1"
},
{
  "source": "tools/supermeta-bootstrap",
  "destination": "tools/supermeta-bootstrap"
}
```

- [ ] **Step 2: Add common sync contract to each template manifest**

Add this `syncContract` object near `generatedDocs` in every template manifest. For Java include `scripts/agent-gradle` and `tools/supermeta-gradle`; for C# include `scripts/agent-dotnet`; for all templates include the shared agent/bootstrap/task/beads/rules paths already copied by that template.

```json
"syncContract": {
  "version": 1,
  "managedSets": [
    {
      "id": "agent-scripts",
      "description": "Agent wrapper scripts and bootstrap sync entrypoints.",
      "files": [
        {"path": "scripts/agent-bootstrap", "mode": "whole-file"},
        {"path": "scripts/agent-bootstrap.ps1", "mode": "whole-file"},
        {"path": "scripts/agent-beads", "mode": "whole-file"},
        {"path": "scripts/agent-beads.ps1", "mode": "whole-file"},
        {"path": "scripts/agent-task", "mode": "whole-file"},
        {"path": "scripts/agent-task.ps1", "mode": "whole-file"}
      ],
      "regions": []
    },
    {
      "id": "supermeta-tools",
      "description": "Shared Supermeta support tools copied into generated projects.",
      "files": [
        {"path": "tools/supermeta-bootstrap/bootstrap_sync.py", "mode": "whole-file"},
        {"path": "tools/supermeta-bootstrap/README.md", "mode": "whole-file"},
        {"path": "tools/supermeta-task/task.py", "mode": "whole-file"},
        {"path": "tools/supermeta-task/README.md", "mode": "whole-file"},
        {"path": "tools/supermeta-beads/beads.py", "mode": "whole-file"},
        {"path": "tools/supermeta-beads/README.md", "mode": "whole-file"},
        {"path": "tools/supermeta-rules/check.py", "mode": "whole-file"},
        {"path": "tools/supermeta-rules/README.md", "mode": "whole-file"}
      ],
      "regions": []
    },
    {
      "id": "generated-docs",
      "description": "Generated bootstrap sync instructions in project docs.",
      "files": [],
      "regions": [
        {"path": "README.md", "id": "generated-docs/bootstrap-sync"},
        {"path": "AGENTS.md", "id": "generated-docs/bootstrap-sync"},
        {"path": "docs/OPERATIONS.md", "id": "generated-docs/bootstrap-sync"}
      ]
    },
    {
      "id": "language-checks",
      "description": "Template verification and reusable rule configuration.",
      "files": [
        {"path": "supermeta-rules.json", "mode": "whole-file"}
      ],
      "regions": []
    }
  ],
  "verificationCommands": [
    "./scripts/agent-bootstrap sync --dry-run"
  ],
  "migrationNotes": []
}
```

For Java add these file entries under `agent-scripts` and `supermeta-tools`:

```json
{"path": "scripts/agent-gradle", "mode": "whole-file"},
{"path": "scripts/agent-gradle.ps1", "mode": "whole-file"},
{"path": "tools/supermeta-gradle/gradle.py", "mode": "whole-file"},
{"path": "tools/supermeta-gradle/README.md", "mode": "whole-file"}
```

For C# add:

```json
{"path": "scripts/agent-dotnet", "mode": "whole-file"},
{"path": "scripts/agent-dotnet.ps1", "mode": "whole-file"}
```

- [ ] **Step 3: Add generated sync docs regions**

Add this helper in `tools/bootstrap/bootstrap.py` near generated docs helpers:

```python
def generated_bootstrap_sync_region(check_command: str) -> str:
    return f"""<!-- codex-bootstrap:begin generated-docs/bootstrap-sync -->
## Bootstrap Sync

This project can resync Codex Bootstrap managed files and generated doc regions from the recorded bootstrap source.

Preview managed updates first:

```bash
./scripts/agent-bootstrap sync --dry-run
```

Apply only when the plan has no conflicts:

```bash
./scripts/agent-bootstrap sync --apply
{check_command}
```
<!-- codex-bootstrap:end generated-docs/bootstrap-sync -->
"""
```

Append `{generated_bootstrap_sync_region(...)}` to every generated README before `## Agent Workflow`. Use the template check command:

```python
generated_bootstrap_sync_region("./scripts/agent-gradle . check")
generated_bootstrap_sync_region("./scripts/check")
```

Add this helper for AGENTS/OPERATIONS:

```python
def generated_agent_sync_region(check_command: str) -> str:
    return f"""<!-- codex-bootstrap:begin generated-docs/bootstrap-sync -->
## Bootstrap Sync

- Run `./scripts/agent-bootstrap sync --dry-run` before applying bootstrap updates.
- Inspect conflicts instead of forcing over local edits.
- Apply managed updates with `./scripts/agent-bootstrap sync --apply` only when the plan is clean.
- After apply, run `{check_command}` and any extra verification commands printed by sync.
- If this repo has `CHANGELOG.md`, update it when sync changes merge-relevant behavior.
<!-- codex-bootstrap:end generated-docs/bootstrap-sync -->
"""
```

Include `generated_agent_sync_region(...)` in every generated `AGENTS.md` and `generated_operations()`.

- [ ] **Step 4: Run manifest and bootstrap smoke tests**

Run:

```bash
python3 -m unittest tools.bootstrap.bootstrap_test.ManifestTest
python3 -m unittest tools.bootstrap.bootstrap_test.BootstrapSmokeTest.test_bootstrap_rewrites_checkout_into_standalone_project
```

Expected: PASS for manifest parsing and Java smoke. If smoke fails because generated metadata references a missing managed file, update the manifest file list to match the actual generated tree named in the failure.

- [ ] **Step 5: Commit template sync contracts**

```bash
git add templates/*/bootstrap-template.json tools/bootstrap/bootstrap.py tools/bootstrap/bootstrap_test.py
git commit -m "feat: emit bootstrap sync metadata"
```

## Task 8: Generated Project Sync Smoke Tests

**Files:**
- Modify: `tools/bootstrap/bootstrap_test.py`
- Modify: `tools/supermeta-bootstrap/bootstrap_sync.py`

- [ ] **Step 1: Add generated-project dry-run and conflict tests**

In `tools/bootstrap/bootstrap_test.py`, add this test to `BootstrapSmokeTest`:

```python
    @unittest.skipIf(shutil.which("git") is None, "git is required for bootstrap sync smoke test")
    def test_generated_project_sync_dry_run_and_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-sync-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            source_repo = temp_root / "source"
            checkout = temp_root / "sample-app"
            copy_bootstrap_checkout(source_repo)
            initialize_source_repo(source_repo)
            shutil.copytree(source_repo, checkout, ignore=shutil.ignore_patterns(".git"))
            initialize_fake_origin(checkout)

            run_checked(
                [
                    "./bootstrap",
                    "--template",
                    "python-uv-cli",
                    "--name",
                    "sample-app",
                    "--yes",
                ],
                cwd=checkout,
            )

            dry_run = run_checked(
                [
                    "./scripts/agent-bootstrap",
                    "sync",
                    "--dry-run",
                    "--source-dir",
                    str(source_repo),
                ],
                cwd=checkout,
                timeout=180,
            )
            self.assertIn("Bootstrap sync plan:", dry_run.stdout)
            self.assertIn("template: python-uv-cli", dry_run.stdout)

            agent_task = checkout / "scripts" / "agent-task"
            agent_task.write_text(agent_task.read_text(encoding="utf-8") + "\n# local edit\n", encoding="utf-8")
            conflict = run_unchecked(
                [
                    "./scripts/agent-bootstrap",
                    "sync",
                    "--apply",
                    "--source-dir",
                    str(source_repo),
                ],
                cwd=checkout,
                timeout=180,
            )
            self.assertEqual(1, conflict.returncode)
            self.assertIn("conflict: scripts/agent-task", conflict.stdout)
```

- [ ] **Step 2: Run the new smoke test**

Run:

```bash
python3 -m unittest tools.bootstrap.bootstrap_test.BootstrapSmokeTest.test_generated_project_sync_dry_run_and_conflict
```

Expected: PASS.

- [ ] **Step 3: Commit generated sync smoke tests**

```bash
git add tools/bootstrap/bootstrap_test.py tools/supermeta-bootstrap/bootstrap_sync.py
git commit -m "test: cover generated bootstrap sync"
```

## Task 9: Pages Metadata And Catalog Docs

**Files:**
- Modify: `tools/pages/build_pages.py`
- Modify: `tools/pages/pages_test.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add failing Pages metadata assertions**

In `tools/pages/pages_test.py`, inside `test_builds_static_pages_artifacts`, after `templates` is loaded:

```python
            java_template = next(
                template for template in templates["templates"] if template["id"] == "java-gradle-cli"
            )
            self.assertTrue(java_template["syncCapable"])
            self.assertEqual(1, java_template["syncContractVersion"])
            self.assertIn("agent-scripts", java_template["managedSets"])
```

- [ ] **Step 2: Run Pages tests and verify missing fields**

Run:

```bash
python3 -m unittest discover -s tools/pages -p '*_test.py'
```

Expected: FAIL with `KeyError: 'syncCapable'`.

- [ ] **Step 3: Emit sync metadata from Pages builder**

In `tools/pages/build_pages.py`, add helper:

```python
def sync_summary(raw: dict[str, Any]) -> dict[str, Any]:
    sync_contract = raw.get("syncContract")
    if not isinstance(sync_contract, dict):
        return {
            "syncCapable": False,
            "syncContractVersion": 0,
            "managedSets": [],
        }
    managed_sets = sync_contract.get("managedSets", [])
    if not isinstance(managed_sets, list):
        raise ValueError("syncContract.managedSets must be an array")
    return {
        "syncCapable": True,
        "syncContractVersion": sync_contract.get("version", 0),
        "managedSets": [
            require_string(item, "id", Path("syncContract"))
            for item in managed_sets
            if isinstance(item, dict)
        ],
    }
```

Merge it into each template payload:

```python
            template_payload = {
                "id": require_string(raw, "id", manifest_path),
                "displayName": require_string(raw, "displayName", manifest_path),
                "description": require_string(raw, "description", manifest_path),
                "type": require_string(raw, "type", manifest_path),
                "requiredInputs": require_string_list(raw, "requiredInputs", manifest_path),
                "verificationCommands": require_string_list(
                    raw, "verificationCommands", manifest_path
                ),
            }
            template_payload.update(sync_summary(raw))
            templates.append(template_payload)
```

- [ ] **Step 4: Update README**

Add a section after Quick Start:

```markdown
## Resync Generated Projects

New generated projects include a bootstrap sync contract under
`.codex-bootstrap/sync.json`.

Preview managed updates:

```bash
./scripts/agent-bootstrap sync --dry-run
```

Apply when the plan has no conflicts:

```bash
./scripts/agent-bootstrap sync --apply
```

Sync updates only declared managed files and managed regions. It does not merge
arbitrary product source under `src/` or `tests/`, and it reports conflicts
instead of overwriting local edits.
```

- [ ] **Step 5: Update CHANGELOG**

Replace the current Unreleased entry with:

```markdown
## Unreleased

### Generated Contract

- Added the bootstrap resync contract for newly generated projects:
  `.codex-bootstrap/sync.json`, `scripts/agent-bootstrap`,
  `scripts/agent-bootstrap.ps1`, `tools/supermeta-bootstrap/`, managed-file
  hashes, managed-region hashes, and generated sync instructions.

### Pages / Installer

- Extended `templates.json` with sync capability metadata so catalog consumers
  can tell which templates support downstream resync.

### Verification

- `PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'`
- `python3 -m unittest discover -s tools/bootstrap -p '*_test.py'`
- `python3 -m unittest discover -s tools/pages -p '*_test.py'`
```

- [ ] **Step 6: Run Pages tests**

Run:

```bash
python3 -m unittest discover -s tools/pages -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 7: Commit Pages and docs**

```bash
git add tools/pages/build_pages.py tools/pages/pages_test.py README.md CHANGELOG.md
git commit -m "docs: document bootstrap resync contract"
```

## Task 10: Full Verification And Contract Cleanup

**Files:**
- Modify: `tools/supermeta-bootstrap/bootstrap_sync.py` when sync helper verification finds a defect.
- Modify: `tools/bootstrap/bootstrap.py` when generated-project verification finds a metadata or docs defect.
- Modify: `templates/*/bootstrap-template.json` when manifest verification finds a missing managed target.
- Modify: `README.md` when final docs verification finds stale command text.
- Modify: `CHANGELOG.md` when final verification changes the implementation scope or verification list.

- [ ] **Step 1: Run sync helper tests**

Run:

```bash
PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 2: Run bootstrap tests**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 3: Run Pages tests**

Run:

```bash
python3 -m unittest discover -s tools/pages -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 4: Run all Python tool tests**

Run:

```bash
python3 -m unittest discover -s tools -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 5: Run Java template verification because support paths and manifests changed**

Run:

```bash
./scripts/agent-gradle templates/java-gradle-cli check
```

Expected: PASS.

- [ ] **Step 6: Run diff hygiene checks**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` prints nothing. `git status --short` shows only intentional files for the final commit.

- [ ] **Step 7: Commit final fixes if any verification command required changes**

If Step 1 through Step 6 forced any edits, commit them:

```bash
git add tools scripts templates README.md CHANGELOG.md
git commit -m "fix: stabilize bootstrap resync verification"
```

If no edits were needed after the prior commits, do not create an empty commit.

---

## Self-Review Checklist

- The plan implements `.codex-bootstrap/sync.json`, `.codex-bootstrap/reports/`, `scripts/agent-bootstrap`, `scripts/agent-bootstrap.ps1`, and `tools/supermeta-bootstrap/`.
- The plan implements whole-file hash checks and managed-region hash checks.
- The plan keeps arbitrary `src/` and `tests/` source outside sync unless a future manifest explicitly marks regions there.
- The plan keeps old-project adoption out of V1.
- The plan updates generated docs and root docs.
- The plan updates Pages metadata.
- The plan includes focused unit tests, generated-project smoke tests, Pages tests, and final verification commands.
