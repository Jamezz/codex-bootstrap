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
            with self.assertRaisesRegex(
                bootstrap_sync.SyncError, "missing .codex-bootstrap/sync.json"
            ):
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
            self.assertEqual(
                ("AGENTS.md:generated-docs/bootstrap-sync",), tuple(contract.managed_regions)
            )
            self.assertEqual(("Read the release notes.",), contract.migration_notes)

    def test_hashes_file_bytes_with_sha256(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-hash-") as temp_dir:
            path = Path(temp_dir) / "file.txt"
            path.write_text("hello\n", encoding="utf-8")

            self.assertEqual(
                "5891b5b522d5df086d0ff0b110fbd9d21bb4fc7163af34d08286a2e846f6be03",
                bootstrap_sync.sha256_file(path),
            )


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

            plan = bootstrap_sync.plan_managed_updates(
                root, candidate, metadata, contract, git_status={}
            )

            self.assertEqual((), plan.conflicts)
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

            plan = bootstrap_sync.plan_managed_updates(
                root, candidate, metadata, contract, git_status={}
            )

            self.assertEqual((), plan.file_changes)
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

            self.assertEqual((), plan.file_changes)
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

            plan = bootstrap_sync.plan_managed_updates(
                root, candidate, metadata, contract, git_status={}
            )

            self.assertEqual((), plan.conflicts)
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

            plan = bootstrap_sync.plan_managed_updates(
                root, candidate, metadata, contract, git_status={}
            )

            self.assertEqual((), plan.region_changes)
            self.assertIn("marker count", plan.conflicts[0].reason)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def managed_region(region_id: str, body: str) -> str:
    return (
        f"<!-- codex-bootstrap:begin {region_id} -->\n"
        f"{body}"
        f"<!-- codex-bootstrap:end {region_id} -->"
    )


def metadata_for_files(
    root: Path, managed_files: dict[str, dict[str, str]]
) -> bootstrap_sync.SyncMetadata:
    return metadata_for(root, managed_files=managed_files, managed_regions={})


def metadata_for_regions(
    root: Path, managed_regions: dict[str, dict[str, str]]
) -> bootstrap_sync.SyncMetadata:
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
