from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace


GRADLE_MODULE_PATH = Path(__file__).resolve().parent / "gradle.py"


def load_gradle_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("supermeta_gradle", GRADLE_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module from {GRADLE_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gradle = load_gradle_module()


class BuildCommandTest(unittest.TestCase):
    def test_warm_defaults_disable_file_watch_only(self) -> None:
        command = gradle.build_command(
            wrapper=Path("/tmp/gradlew"),
            gradle_args=["check"],
            no_default_flags=False,
            cold_mode=False,
        )

        self.assertEqual(["sh", "/tmp/gradlew", "--no-watch-fs", "check"], command)

    def test_windows_uses_gradlew_bat(self) -> None:
        command = gradle.build_command(
            wrapper=Path("C:/repo/gradlew"),
            gradle_args=["check"],
            no_default_flags=False,
            cold_mode=False,
            platform_name="nt",
        )

        self.assertEqual(["C:/repo/gradlew.bat", "--no-watch-fs", "check"], command)

    def test_parallel_env_adds_parallel_defaults(self) -> None:
        with patched_env(SUPERMETA_GRADLE_PARALLEL="1", SUPERMETA_GRADLE_MAX_WORKERS="4"):
            command = gradle.build_command(
                wrapper=Path("/tmp/gradlew"),
                gradle_args=["check"],
                no_default_flags=False,
                cold_mode=False,
            )

        self.assertEqual(
            ["sh", "/tmp/gradlew", "--no-watch-fs", "--parallel", "--max-workers=4", "check"],
            command,
        )

    def test_explicit_parallel_flags_are_not_duplicated(self) -> None:
        with patched_env(SUPERMETA_GRADLE_PARALLEL="1", SUPERMETA_GRADLE_MAX_WORKERS="4"):
            command = gradle.build_command(
                wrapper=Path("/tmp/gradlew"),
                gradle_args=["check", "--no-parallel", "--max-workers=2"],
                no_default_flags=False,
                cold_mode=False,
            )

        self.assertEqual(
            ["sh", "/tmp/gradlew", "--no-watch-fs", "check", "--no-parallel", "--max-workers=2"],
            command,
        )

    def test_cold_mode_overrides_parallel_env(self) -> None:
        with patched_env(SUPERMETA_GRADLE_PARALLEL="1", SUPERMETA_GRADLE_MAX_WORKERS="4"):
            command = gradle.build_command(
                wrapper=Path("/tmp/gradlew"),
                gradle_args=["check"],
                no_default_flags=False,
                cold_mode=True,
            )

        self.assertEqual(
            ["sh", "/tmp/gradlew", "--no-watch-fs", "--no-daemon", "--no-parallel", "--max-workers=4", "check"],
            command,
        )


class GradleHomeTest(unittest.TestCase):
    def test_default_gradle_home_is_capsule_scoped(self) -> None:
        project_dir = Path("/workspace/sample-app")
        build_capsule = gradle.resolve_capsule(project_dir, {"SUPERMETA_BUILD_CAPSULE_ID": "agent-1"})

        gradle_home = gradle.resolve_gradle_home(None, project_dir, build_capsule)

        self.assertEqual(project_dir / ".gradle" / "agent-capsules" / "agent-1" / "gradle-user-home", gradle_home)

    def test_env_gradle_home_still_overrides_project_scoped_default(self) -> None:
        with patched_env(SUPERMETA_GRADLE_USER_HOME="/tmp/shared-gradle-home"):
            build_capsule = gradle.resolve_capsule(
                Path("/workspace/sample-app"),
                {"SUPERMETA_BUILD_CAPSULE_ID": "agent-1"},
            )
            gradle_home = gradle.resolve_gradle_home(None, Path("/workspace/sample-app"), build_capsule)

        self.assertEqual(Path("/tmp/shared-gradle-home").resolve(), gradle_home)

    def test_init_script_is_prepended_when_absent(self) -> None:
        args = gradle.add_init_script_arg(["check"], Path("/tmp/init.gradle.kts"))

        self.assertEqual(["--init-script=/tmp/init.gradle.kts", "check"], args)

    def test_existing_init_script_is_preserved(self) -> None:
        args = gradle.add_init_script_arg(["--init-script=/tmp/custom.gradle.kts", "check"], Path("/tmp/init.gradle.kts"))

        self.assertEqual(["--init-script=/tmp/custom.gradle.kts", "check"], args)


class GeneratedHygieneIntegrationTest(unittest.TestCase):
    def test_hygiene_only_removes_exact_duplicate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gradle-hygiene-") as temp_dir:
            project_dir = Path(temp_dir)
            build_capsule = gradle.resolve_capsule(project_dir, {"SUPERMETA_BUILD_CAPSULE_ID": "agent-1"})
            build = project_dir / "module" / "build" / "classes"
            build.mkdir(parents=True)
            (build / "Worker.class").write_bytes(b"same")
            duplicate = build / "Worker 2.class"
            duplicate.write_bytes(b"same")

            exit_code = gradle.run_hygiene_only(project_dir, build_capsule)

            self.assertEqual(0, exit_code)
            self.assertFalse(duplicate.exists())

    def test_hygiene_only_quarantines_divergent_duplicate_without_failing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gradle-hygiene-") as temp_dir:
            project_dir = Path(temp_dir)
            build_capsule = gradle.resolve_capsule(project_dir, {"SUPERMETA_BUILD_CAPSULE_ID": "agent-1"})
            build = project_dir / "module" / "build" / "classes"
            build.mkdir(parents=True)
            (build / "Worker.class").write_bytes(b"original")
            duplicate = build / "Worker 2.class"
            duplicate.write_bytes(b"divergent")

            exit_code = gradle.run_hygiene_only(project_dir, build_capsule)

            self.assertEqual(0, exit_code)
            self.assertFalse(duplicate.exists())
            self.assertTrue(any(build_capsule.hygiene.rglob("manifest.json")))


class SupermetaRulesCacheCleanTest(unittest.TestCase):
    def test_clean_supermeta_rules_cache_removes_known_cache_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gradle-supermeta-cache-") as temp_dir:
            project_dir = Path(temp_dir)
            build_capsule = gradle.resolve_capsule(project_dir, {"SUPERMETA_BUILD_CAPSULE_ID": "agent-1"})
            env_cache = project_dir / "custom-cache" / "cache-v1.json"
            paths = (
                project_dir / ".gradle" / "supermeta-rules" / "cache-v1.json",
                build_capsule.root / "supermeta-rules" / "cache-v1.json",
                project_dir / "sample-ui" / ".gradle" / "supermeta-rules" / "cache-v1.json",
                env_cache,
            )
            for path in paths:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("stale\n", encoding="utf-8")

            exit_code = gradle.clean_supermeta_rules_cache(
                project_dir,
                build_capsule,
                {"SUPERMETA_RULES_CACHE_FILE": str(env_cache)},
            )

            self.assertEqual(0, exit_code)
            for path in paths:
                self.assertFalse(path.exists(), path)


class ProjectDirectoryIntegrationTest(unittest.TestCase):
    def test_strict_included_builds_exports_capsule_project_directory(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gradle-project-directory-") as temp_dir:
            root = Path(temp_dir)
            project_dir = root / "sample-service"
            core_lib = root / "core-lib"
            storage_lib = root / "storage-lib"
            identity_lib = root / "identity-lib"
            for path in (project_dir, core_lib, storage_lib, identity_lib):
                path.mkdir(parents=True)
            catalog = root / "catalog"
            catalog.mkdir()
            (catalog / "project-directory.properties").write_text(
                "version=1\n"
                "repo.core-lib=../core-lib\n"
                "repo.storage-lib=../storage-lib\n"
                "repo.identity-lib=../identity-lib\n",
                encoding="utf-8",
            )
            config_dir = project_dir / ".supermeta-gradle"
            config_dir.mkdir()
            (config_dir / "included-builds.properties").write_text(
                "projectDirectoryFile=../catalog/project-directory.properties\n"
                "repos=core-lib, storage-lib, identity-lib\n",
                encoding="utf-8",
            )
            build_capsule = gradle.resolve_capsule(project_dir, {"SUPERMETA_BUILD_CAPSULE_ID": "agent-1"})
            build_capsule.ensure_directories()
            commands: list[tuple[str, ...]] = []

            def runner(command: list[str]) -> None:
                commands.append(tuple(command))
                Path(command[-2]).mkdir(parents=True)

            original_runner = gradle.run_project_directory_command
            gradle.run_project_directory_command = runner
            env: dict[str, str] = {}
            try:
                output_file = gradle.configure_project_directory_env(
                    SimpleNamespace(
                        project_directory_file=None,
                        included_build_repo=[],
                    ),
                    project_dir,
                    build_capsule,
                    env,
                )
            finally:
                gradle.run_project_directory_command = original_runner

            self.assertEqual(str(output_file), env["SUPERMETA_PROJECT_DIRECTORY_FILE"])
            self.assertEqual(3, len(commands))
            self.assertEqual(
                "version=1\n"
                f"repo.core-lib={build_capsule.included_builds / 'core-lib'}\n"
                f"repo.identity-lib={build_capsule.included_builds / 'identity-lib'}\n"
                f"repo.storage-lib={build_capsule.included_builds / 'storage-lib'}\n",
                output_file.read_text(encoding="utf-8"),
            )

    def test_included_build_defaults_come_from_project_config(self) -> None:
        with tempfile.TemporaryDirectory(prefix="gradle-project-directory-") as temp_dir:
            project_dir = Path(temp_dir) / "sample-service"
            config_dir = project_dir / ".supermeta-gradle"
            config_dir.mkdir(parents=True)
            (config_dir / "included-builds.properties").write_text(
                "repos=core-lib, storage-lib\n",
                encoding="utf-8",
            )

            defaults = gradle.load_included_build_defaults(project_dir)

            self.assertEqual(
                ("core-lib", "storage-lib"),
                gradle.resolve_included_build_repo_ids(
                    SimpleNamespace(included_build_repo=[]),
                    defaults,
                ),
            )

    def test_included_build_defaults_are_empty_without_project_config(self) -> None:
        self.assertEqual(
            (),
            gradle.resolve_included_build_repo_ids(
                SimpleNamespace(included_build_repo=[]),
                gradle.load_included_build_defaults(Path("/workspace/sample-service")),
            ),
        )

    def test_included_build_repo_argument_overrides_project_default(self) -> None:
        defaults = gradle.IncludedBuildDefaults(
            project_directory_file=None,
            repo_ids=("identity-lib",),
        )

        self.assertEqual(
            ("core-lib", "storage-lib"),
            gradle.resolve_included_build_repo_ids(
                SimpleNamespace(included_build_repo=["core-lib", "storage-lib"]),
                defaults,
            ),
        )


class DiagnosticsTest(unittest.TestCase):
    def test_matches_gradle_processes(self) -> None:
        self.assertTrue(gradle.is_gradle_process("/tmp/project/gradlew check"))
        self.assertTrue(gradle.is_gradle_process("java -classpath gradle-launcher-9.2.1.jar org.gradle.launcher.daemon.bootstrap.GradleDaemon"))
        self.assertTrue(gradle.is_gradle_process("python3 tools/supermeta-gradle/gradle.py --project . -- check"))

    def test_ignores_unrelated_java_processes(self) -> None:
        self.assertFalse(gradle.is_gradle_process("java -jar app.jar"))
        self.assertFalse(gradle.is_gradle_process("python3 scripts/tool.py"))

    def test_scoped_gradle_process_matches_project_path(self) -> None:
        self.assertTrue(
            gradle.is_scoped_gradle_process(
                "/workspace/sample-app/gradlew check",
                Path("/workspace/sample-app"),
                Path("/workspace/sample-app/.gradle/agent-capsules/agent-1/gradle-user-home"),
            )
        )

    def test_scoped_gradle_process_matches_gradle_home_path(self) -> None:
        self.assertTrue(
            gradle.is_scoped_gradle_process(
                "java -Dgradle.user.home=/workspace/sample-app/.gradle/agent-capsules/agent-1/gradle-user-home gradle.daemon",
                Path("/workspace/sample-app"),
                Path("/workspace/sample-app/.gradle/agent-capsules/agent-1/gradle-user-home"),
            )
        )

    def test_scoped_gradle_process_ignores_other_worktree(self) -> None:
        self.assertFalse(
            gradle.is_scoped_gradle_process(
                "/workspace/sample-app-worktree/gradlew check",
                Path("/workspace/sample-app"),
                Path("/workspace/sample-app/.gradle/agent-capsules/agent-1/gradle-user-home"),
            )
        )


class patched_env:
    def __init__(self, **values: str) -> None:
        self.values = values
        self.previous: dict[str, str | None] = {}

    def __enter__(self) -> None:
        for key, value in self.values.items():
            self.previous[key] = os.environ.get(key)
            os.environ[key] = value

    def __exit__(self, _error_type: object, _error: object, _traceback: object) -> None:
        for key, previous_value in self.previous.items():
            if previous_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous_value


if __name__ == "__main__":
    unittest.main()
