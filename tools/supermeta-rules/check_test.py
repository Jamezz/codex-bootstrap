from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


CHECK_MODULE_PATH = Path(__file__).resolve().parent / "check.py"


def load_check_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("supermeta_rules_check", CHECK_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module from {CHECK_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = load_check_module()


class ProjectCalloutRuleTest(unittest.TestCase):
    def test_successful_callout_returns_no_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_file(root)
            marker = root / "callout-ran.txt"

            findings = check.run_rules(
                callout_config(
                    [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('callout-ran.txt').write_text('yes')",
                    ]
                ),
                root,
            )

            self.assertEqual([], findings)
            self.assertEqual("yes", marker.read_text(encoding="utf-8"))

    def test_callout_is_skipped_when_no_files_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            marker = root / "callout-ran.txt"

            findings = check.run_rules(
                callout_config(
                    [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('callout-ran.txt').write_text('yes')",
                    ]
                ),
                root,
            )

            self.assertEqual([], findings)
            self.assertFalse(marker.exists())

    def test_failing_callout_returns_finding_with_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_file(root)

            findings = check.run_rules(
                callout_config(
                    [
                        sys.executable,
                        "-c",
                        "print('lint failed'); raise SystemExit(7)",
                    ]
                ),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertEqual("java-checkstyle", findings[0].rule)
            self.assertIn("exit 7", findings[0].message)
            self.assertIn("lint failed", findings[0].message)

    def test_skip_callouts_flag_skips_matching_callout(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_file(root)
            marker = root / "callout-ran.txt"

            findings = check.run_rules(
                callout_config(
                    [
                        sys.executable,
                        "-c",
                        "from pathlib import Path; Path('callout-ran.txt').write_text('yes')",
                    ]
                ),
                root,
                skip_callouts=True,
            )

            self.assertEqual([], findings)
            self.assertFalse(marker.exists())

    def test_skip_callouts_environment_skips_matching_callout(self) -> None:
        previous = os.environ.get("SUPERMETA_SKIP_PROJECT_CALLOUTS")
        os.environ["SUPERMETA_SKIP_PROJECT_CALLOUTS"] = "1"
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                write_java_file(root)
                marker = root / "callout-ran.txt"

                findings = check.run_rules(
                    callout_config(
                        [
                            sys.executable,
                            "-c",
                            "from pathlib import Path; Path('callout-ran.txt').write_text('yes')",
                        ]
                    ),
                    root,
                )

                self.assertEqual([], findings)
                self.assertFalse(marker.exists())
        finally:
            if previous is None:
                os.environ.pop("SUPERMETA_SKIP_PROJECT_CALLOUTS", None)
            else:
                os.environ["SUPERMETA_SKIP_PROJECT_CALLOUTS"] = previous

    def test_unknown_rule_keys_still_fail(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "unknown rule keys: no_such_rule"):
                check.run_rules({"no_such_rule": []}, Path(temp_dir))

    def test_rejects_empty_callout_command(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_file(root)
            config = callout_config([])

            with self.assertRaisesRegex(ValueError, "command must contain at least one string"):
                check.run_rules(config, root)

    def test_cli_skip_callouts_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_file(root)
            marker = root / "callout-ran.txt"
            config_path = root / "supermeta-rules.json"
            config_path.write_text(
                """{
  "project_callouts": [
    {
      "name": "java-checkstyle",
      "language": "java",
      "paths": ["src/main/java"],
      "include": ["**/*.java"],
      "exclude": [],
      "command": ["python3", "-c", "from pathlib import Path; Path('callout-ran.txt').write_text('yes')"]
    }
  ]
}
""",
                encoding="utf-8",
            )

            exit_code = check.main(
                [
                    "--config",
                    str(config_path),
                    "--root",
                    str(root),
                    "--skip-callouts",
                ]
            )

            self.assertEqual(0, exit_code)
            self.assertFalse(marker.exists())


class JavaPackageFileCountRuleTest(unittest.TestCase):
    def test_allows_package_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_files(root, "src/main/java/example", count=8)

            findings = check.run_rules(java_package_count_config(max_files=8), root)

            self.assertEqual([], findings)

    def test_fails_package_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_files(root, "src/main/java/example", count=9)

            findings = check.run_rules(java_package_count_config(max_files=8), root)

            self.assertEqual(1, len(findings))
            self.assertEqual("java-package-size", findings[0].rule)
            self.assertEqual(Path("src/main/java/example"), findings[0].path)
            self.assertIn("9 Java source files exceeds package limit of 8", findings[0].message)

    def test_counts_subpackages_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_files(root, "src/main/java/example", count=8)
            write_java_files(root, "src/main/java/example/nested", count=8)

            findings = check.run_rules(java_package_count_config(max_files=8), root)

            self.assertEqual([], findings)


def write_java_file(root: Path) -> None:
    source = root / "src" / "main" / "java" / "example" / "App.java"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("package example;\nfinal class App {}\n", encoding="utf-8")


def write_java_files(root: Path, package_path: str, count: int) -> None:
    package_dir = root / package_path
    package_dir.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        package_name = package_path.removeprefix("src/main/java/").replace("/", ".")
        type_name = f"Type{index}"
        (package_dir / f"{type_name}.java").write_text(
            f"package {package_name};\nfinal class {type_name} {{}}\n",
            encoding="utf-8",
        )


def callout_config(command: list[str]) -> dict[str, object]:
    return {
        "project_callouts": [
            {
                "name": "java-checkstyle",
                "language": "java",
                "paths": ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": ["**/generated/**"],
                "command": command,
            }
        ]
    }


def java_package_count_config(max_files: int) -> dict[str, object]:
    return {
        "java_package_file_count": [
            {
                "name": "java-package-size",
                "max_files": max_files,
                "paths": ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": ["**/generated/**"],
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
