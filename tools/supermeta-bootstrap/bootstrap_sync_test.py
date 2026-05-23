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


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
