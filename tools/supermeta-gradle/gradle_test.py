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
    def test_warm_defaults_disable_file_watch_only(self) -> None:
        command = gradle.build_command(
            wrapper=Path("/tmp/gradlew"),
            gradle_args=["check"],
            no_default_flags=False,
            cold_mode=False,
        )

        self.assertEqual(["sh", "/tmp/gradlew", "--no-watch-fs", "check"], command)

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
