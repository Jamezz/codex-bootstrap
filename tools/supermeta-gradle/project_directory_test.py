from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import project_directory


class ProjectDirectoryTest(unittest.TestCase):
    def test_loads_relative_repo_paths_from_properties_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-directory-") as temp_dir:
            root = Path(temp_dir)
            catalog = root / "catalog"
            catalog.mkdir()
            file = catalog / "project-directory.properties"
            file.write_text(
                "version=1\n"
                "repo.shared-lib=.\n"
                "repo.worker-lib=../worker-lib\n",
                encoding="utf-8",
            )

            directory = project_directory.load_project_directory(file)

            self.assertEqual(catalog.resolve(), directory.repos["shared-lib"])
            self.assertEqual((root / "worker-lib").resolve(), directory.repos["worker-lib"])

    def test_rejects_missing_explicit_project_directory_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-directory-") as temp_dir:
            missing = Path(temp_dir) / "missing.properties"

            with self.assertRaisesRegex(project_directory.ProjectDirectoryError, "missing"):
                project_directory.resolve_project_directory_source(
                    Path(temp_dir),
                    {},
                    explicit_file=missing,
                )

    def test_default_source_falls_back_to_project_example(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-directory-") as temp_dir:
            project = Path(temp_dir) / "sample-service"
            project.mkdir(parents=True)
            example = project / "project-directory.properties.example"
            example.write_text("version=1\nrepo.shared-lib=../shared-lib\n", encoding="utf-8")

            source = project_directory.resolve_project_directory_source(project, {})

            self.assertEqual(example.resolve(), source.path)
            self.assertFalse(source.explicit)

    def test_default_source_uses_configured_project_directory_file_after_env(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-directory-") as temp_dir:
            project = Path(temp_dir) / "sample-service"
            project.mkdir(parents=True)
            configured = Path(temp_dir) / "catalog" / "project-directory.properties"
            configured.parent.mkdir(parents=True)
            configured.write_text("version=1\nrepo.shared-lib=../shared-lib\n", encoding="utf-8")

            source = project_directory.resolve_project_directory_source(
                project,
                {},
                default_file=configured,
            )

            self.assertEqual(configured.resolve(), source.path)
            self.assertFalse(source.explicit)

    def test_loads_included_build_defaults_from_project_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-directory-") as temp_dir:
            project = Path(temp_dir) / "sample-service"
            config_dir = project / ".supermeta-gradle"
            config_dir.mkdir(parents=True)
            (config_dir / "included-builds.properties").write_text(
                "projectDirectoryFile=../catalog/project-directory.properties\n"
                "repos=core-lib, storage-lib\n",
                encoding="utf-8",
            )

            defaults = project_directory.load_included_build_defaults(project)

            self.assertEqual(
                (Path(temp_dir) / "catalog" / "project-directory.properties").resolve(),
                defaults.project_directory_file,
            )
            self.assertEqual(("core-lib", "storage-lib"), defaults.repo_ids)

    def test_materializes_missing_included_worktrees(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-directory-") as temp_dir:
            root = Path(temp_dir)
            source_repo = root / "storage-lib"
            source_repo.mkdir()
            included_root = root / "capsule" / "included-builds"
            commands: list[tuple[str, ...]] = []

            def runner(command: list[str]) -> None:
                commands.append(tuple(command))
                Path(command[-2]).mkdir(parents=True)

            materialized = project_directory.materialize_included_worktrees(
                {"storage-lib": source_repo},
                included_root,
                ("storage-lib",),
                runner=runner,
            )

            self.assertEqual({"storage-lib": included_root / "storage-lib"}, materialized)
            self.assertEqual(
                [
                    (
                        "git",
                        "-C",
                        str(source_repo),
                        "worktree",
                        "add",
                        "--detach",
                        str(included_root / "storage-lib"),
                        "HEAD",
                    )
                ],
                commands,
            )

    def test_missing_source_repo_fails_before_gradle(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-directory-") as temp_dir:
            root = Path(temp_dir)

            with self.assertRaisesRegex(project_directory.ProjectDirectoryError, "storage-lib"):
                project_directory.materialize_included_worktrees(
                    {"storage-lib": root / "missing"},
                    root / "included-builds",
                    ("storage-lib",),
                    runner=lambda _command: None,
                )

    def test_writes_capsule_project_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="project-directory-") as temp_dir:
            root = Path(temp_dir)
            output_file = root / "capsule" / "project-directory.properties"
            repos = {
                "core-lib": root / "included-builds" / "core-lib",
                "storage-lib": root / "included-builds" / "storage-lib",
            }

            project_directory.write_project_directory(output_file, repos)

            self.assertEqual(
                "version=1\n"
                f"repo.core-lib={repos['core-lib'].resolve()}\n"
                f"repo.storage-lib={repos['storage-lib'].resolve()}\n",
                output_file.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
