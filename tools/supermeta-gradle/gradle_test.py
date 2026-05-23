from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from pathlib import Path
from types import ModuleType


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
    def test_defaults_disable_file_watch_and_daemon(self) -> None:
        command = gradle.build_command(
            wrapper=Path("/tmp/gradlew"),
            gradle_args=["check"],
            no_default_flags=False,
            cold_mode=False,
        )

        self.assertEqual(["sh", "/tmp/gradlew", "--no-watch-fs", "--no-daemon", "check"], command)

    def test_keep_daemon_env_opts_back_into_daemon_reuse(self) -> None:
        with patched_env(SUPERMETA_GRADLE_KEEP_DAEMON="1"):
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

        self.assertEqual(["C:/repo/gradlew.bat", "--no-watch-fs", "--no-daemon", "check"], command)

    def test_parallel_env_adds_parallel_defaults(self) -> None:
        with patched_env(SUPERMETA_GRADLE_PARALLEL="1", SUPERMETA_GRADLE_MAX_WORKERS="4"):
            command = gradle.build_command(
                wrapper=Path("/tmp/gradlew"),
                gradle_args=["check"],
                no_default_flags=False,
                cold_mode=False,
            )

        self.assertEqual(
            ["sh", "/tmp/gradlew", "--no-watch-fs", "--no-daemon", "--parallel", "--max-workers=4", "check"],
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
            ["sh", "/tmp/gradlew", "--no-watch-fs", "--no-daemon", "check", "--no-parallel", "--max-workers=2"],
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
    def test_default_gradle_home_is_project_scoped(self) -> None:
        previous = os.environ.pop("SUPERMETA_GRADLE_USER_HOME", None)
        try:
            project_dir = Path("/workspace/sample-app")

            gradle_home = gradle.resolve_gradle_home(None, project_dir)

            self.assertEqual(project_dir / ".gradle" / "supermeta-gradle" / "gradle-user-home", gradle_home)
        finally:
            if previous is not None:
                os.environ["SUPERMETA_GRADLE_USER_HOME"] = previous

    def test_env_gradle_home_still_overrides_project_scoped_default(self) -> None:
        with patched_env(SUPERMETA_GRADLE_USER_HOME="/tmp/shared-gradle-home"):
            gradle_home = gradle.resolve_gradle_home(None, Path("/workspace/sample-app"))

        self.assertEqual(Path("/tmp/shared-gradle-home").resolve(), gradle_home)


class DiagnosticsTest(unittest.TestCase):
    def test_matches_gradle_processes(self) -> None:
        self.assertTrue(gradle.is_gradle_process("/tmp/project/gradlew check"))
        self.assertTrue(gradle.is_gradle_process("java -classpath gradle-launcher-9.2.1.jar org.gradle.launcher.daemon.bootstrap.GradleDaemon"))
        self.assertTrue(gradle.is_gradle_process("python3 tools/supermeta-gradle/gradle.py --project . -- check"))

    def test_ignores_unrelated_java_processes(self) -> None:
        self.assertFalse(gradle.is_gradle_process("java -jar app.jar"))
        self.assertFalse(gradle.is_gradle_process("python3 scripts/tool.py"))


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
