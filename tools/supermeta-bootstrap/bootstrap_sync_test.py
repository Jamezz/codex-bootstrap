from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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


class SyncApplyTest(unittest.TestCase):
    def test_apply_preserves_candidate_file_mode_for_managed_scripts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="bootstrap-sync-mode-") as temp_dir:
            root = Path(temp_dir) / "project"
            candidate = Path(temp_dir) / "candidate"
            write_text(root / "scripts" / "agent-coord", "#!/bin/sh\necho ok\n")
            write_text(candidate / "scripts" / "agent-coord", "#!/bin/sh\necho ok\n")
            (root / "scripts" / "agent-coord").chmod(0o644)
            (candidate / "scripts" / "agent-coord").chmod(0o755)
            metadata = metadata_for(
                root,
                managed_files={
                    "scripts/agent-coord": {
                        "set": "agent-scripts",
                        "sha256": bootstrap_sync.sha256_file(root / "scripts" / "agent-coord"),
                    }
                },
                managed_regions={},
            )
            contract = contract_for(
                files=[bootstrap_sync.ManagedFileSpec("scripts/agent-coord", "agent-scripts")]
            )

            plan = bootstrap_sync.plan_managed_updates(
                root, candidate, metadata, contract, git_status={}
            )
            bootstrap_sync.apply_sync_plan(
                root,
                metadata,
                contract,
                plan,
                new_commit="abcdef0123456789abcdef0123456789abcdef01",
            )

            self.assertEqual(("scripts/agent-coord",), tuple(change.path for change in plan.file_changes))
            self.assertEqual(0o755, file_mode(root / "scripts" / "agent-coord"))

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
            plan = bootstrap_sync.plan_managed_updates(
                root, candidate, metadata, contract, git_status={}
            )

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
        wrapper = (
            Path(__file__).resolve().parents[2] / "scripts" / "agent-bootstrap.ps1"
        ).read_text(encoding="utf-8")

        self.assertIn("tools/supermeta-bootstrap/bootstrap_sync.py", wrapper)
        self.assertIn("Invoke-PythonChecked", wrapper)


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def file_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


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
