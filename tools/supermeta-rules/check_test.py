from __future__ import annotations

import contextlib
import io
import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


CHECK_MODULE_PATH = Path(__file__).resolve().parent / "check.py"
CHECK_MODULE_DIR = CHECK_MODULE_PATH.parent


def load_check_module() -> ModuleType:
    sys.path.insert(0, str(CHECK_MODULE_DIR))
    spec = importlib.util.spec_from_file_location("supermeta_rules_check", CHECK_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module from {CHECK_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


check = load_check_module()


class FileMatchingRuleTest(unittest.TestCase):
    def test_broad_path_uses_rooted_include_glob_before_filtering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            matched = write_source(
                root,
                "repo/src/main/java/example/App.java",
                "package example;\nfinal class App {}\n",
            )
            write_source(root, "repo/target/classes/noise.txt", "not relevant\n")

            with patch.object(Path, "rglob", side_effect=AssertionError("broad rglob should not run")):
                matches = list(
                    check.iter_matching_files(
                        root,
                        paths=["repo"],
                        include=["repo/src/main/java/example/*.java"],
                        exclude=[],
                    )
                )

            self.assertEqual([matched.resolve()], matches)

    def test_matching_files_stream_without_materialized_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            matched = write_source(
                root,
                "repo/src/main/java/example/App.java",
                "package example;\nfinal class App {}\n",
            )

            matches = check.iter_matching_files(
                root,
                paths=["repo"],
                include=["repo/src/main/java/example/*.java"],
                exclude=[],
            )

            self.assertNotIsInstance(matches, list)
            self.assertEqual(matched.resolve(), next(matches))
            with self.assertRaises(StopIteration):
                next(matches)

    def test_callout_probe_uses_first_matching_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "repo/src/main/java/example/App.java",
                "package example;\nfinal class App {}\n",
            )

            self.assertTrue(
                check.has_matching_file(
                    root,
                    paths=["repo"],
                    include=["repo/src/main/java/example/*.java"],
                    exclude=[],
                )
            )

    def test_rule_progress_streams_scan_and_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "src/main/java/example/App.java", "line 1\nline 2\n")
            stream = io.StringIO()

            findings = check.run_rules(
                {
                    "line_count": [
                        {
                            "name": "source-line-count",
                            "max_lines": 1,
                            "paths": ["src/main/java"],
                            "include": ["**/*.java"],
                            "exclude": [],
                        }
                    ]
                },
                root,
                progress=check.RuleProgress(stream, file_interval=1, time_interval_seconds=999),
            )

            self.assertEqual(1, len(findings))
            assert_domain_split_warning(self, findings[0].message)
            progress_output = stream.getvalue()
            self.assertIn("source-line-count: scanning", progress_output)
            self.assertIn("source-line-count: scanned 1 files", progress_output)
            self.assertIn("finding [source-line-count]", progress_output)

    def test_include_glob_is_scoped_to_configured_path(self) -> None:
        self.assertEqual(
            "src/main/java/**/*.java",
            check.include_glob_for_base("repo", "repo/src/main/java/**/*.java"),
        )
        self.assertEqual("**/*.java", check.include_glob_for_base("repo/src/main/java", "**/*.java"))


class RuleEnablementTest(unittest.TestCase):
    def test_disabled_rules_skip_required_field_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            findings = check.run_rules(
                {
                    "line_count": [{"enabled": False}],
                    "java_package_class_count": [{"enabled": False}],
                    "java_import_style": [{"enabled": False}],
                    "java_lombok_boilerplate": [{"enabled": False}],
                    "rust_module_item_count": [{"enabled": False}],
                    "rust_panic_boundary": [{"enabled": False}],
                    "project_callouts": [{"enabled": False}],
                },
                root,
            )

            self.assertEqual([], findings)


class RepeatedHelperMethodRuleConfigTest(unittest.TestCase):
    def test_disabled_rule_skips_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            findings = check.run_rules({"repeated_helper_methods": [{"enabled": False}]}, root)

            self.assertEqual([], findings)

    def test_rejects_non_array_rule_group(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(ValueError, "repeated_helper_methods must be an array"):
                check.run_rules({"repeated_helper_methods": {}}, Path(temp_dir))

    def test_rejects_unknown_language(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with self.assertRaisesRegex(ValueError, "language must be one of: java"):
                check.run_rules(repeated_helper_config(language="ruby"), root)

    def test_rejects_empty_groups(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = repeated_helper_config()
            config["repeated_helper_methods"][0]["groups"] = []

            with self.assertRaisesRegex(ValueError, "groups must contain at least one group"):
                check.run_rules(config, root)

    def test_rejects_invalid_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = repeated_helper_config()
            config["repeated_helper_methods"][0]["near_match_threshold"] = 2

            with self.assertRaisesRegex(ValueError, "near_match_threshold must be greater than 0 and at most 1"):
                check.run_rules(config, root)

    def test_rejects_nan_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = repeated_helper_config()
            config["repeated_helper_methods"][0]["near_match_threshold"] = float("nan")

            with self.assertRaisesRegex(ValueError, "near_match_threshold must be greater than 0 and at most 1"):
                check.run_rules(config, root)


class FindingSeverityTest(unittest.TestCase):
    def test_main_prints_advisories_without_failing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "supermeta-rules.json"
            config_path.write_text("{}", encoding="utf-8")
            with patch.object(
                check,
                "run_rules",
                return_value=[
                    check.Finding(
                        rule="repeated-helper-methods",
                        path=Path("src/test/java/example/AppTest.java"),
                        message="similar helper; review for shared extraction",
                        severity="advisory",
                    )
                ],
            ):
                output = io.StringIO()
                error = io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                    exit_code = check.main(["--config", str(config_path), "--root", str(root), "--full"])

            self.assertEqual(0, exit_code)
            self.assertIn("Supermeta rule advisories:", output.getvalue())
            self.assertIn("[repeated-helper-methods]", output.getvalue())
            self.assertNotIn("Supermeta rule violations:", output.getvalue())

    def test_main_fails_when_errors_and_advisories_exist(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "supermeta-rules.json"
            config_path.write_text("{}", encoding="utf-8")
            with patch.object(
                check,
                "run_rules",
                return_value=[
                    check.Finding(
                        rule="repeated-helper-methods",
                        path=Path("src/main/java/example/Foo.java"),
                        message="duplicates helper body",
                    ),
                    check.Finding(
                        rule="repeated-helper-methods",
                        path=Path("src/test/java/example/FooTest.java"),
                        message="similar helper",
                        severity="advisory",
                    ),
                ],
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    exit_code = check.main(["--config", str(config_path), "--root", str(root), "--full"])

            self.assertEqual(1, exit_code)
            self.assertIn("Supermeta rule violations:", output.getvalue())
            self.assertIn("Supermeta rule advisories:", output.getvalue())


@unittest.skipIf(shutil.which("git") is None, "git is required")
class AutomaticWorkingSetTest(unittest.TestCase):
    def test_file_local_rules_scan_only_dirty_files_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_git_repo(root)
            write_source(root, "src/main/java/example/TooLarge.java", "line 1\nline 2\n")
            write_source(root, "src/main/java/example/Changed.java", "line 1\n")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            write_source(root, "src/main/java/example/Changed.java", "changed\n")

            findings = check.run_rules(
                {
                    "line_count": [
                        {
                            "name": "source-line-count",
                            "max_lines": 1,
                            "paths": ["src/main/java"],
                            "include": ["**/*.java"],
                            "exclude": [],
                        }
                    ]
                },
                root,
            )

            self.assertEqual([], findings)

    def test_force_full_keeps_file_local_rules_authoritative(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_git_repo(root)
            write_source(root, "src/main/java/example/TooLarge.java", "line 1\nline 2\n")
            write_source(root, "src/main/java/example/Changed.java", "line 1\n")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            write_source(root, "src/main/java/example/Changed.java", "changed\n")

            findings = check.run_rules(
                {
                    "line_count": [
                        {
                            "name": "source-line-count",
                            "max_lines": 1,
                            "paths": ["src/main/java"],
                            "include": ["**/*.java"],
                            "exclude": [],
                        }
                    ]
                },
                root,
                force_full=True,
            )

            self.assertEqual(1, len(findings))
            self.assertEqual(Path("src/main/java/example/TooLarge.java"), findings[0].path)

    def test_cross_file_java_package_rules_still_scan_full_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_git_repo(root)
            write_java_files(root, "src/main/java/example", count=8)
            write_source(root, "src/main/java/other/Changed.java", "package other;\nfinal class Changed {}\n")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            write_source(root, "src/main/java/other/Changed.java", "package other;\nfinal class Changed { }\n")

            findings = check.run_rules(java_package_count_config(max_classes=7), root)

            self.assertEqual(1, len(findings))
            self.assertEqual(Path("src/main/java/example"), findings[0].path)

    def test_cli_full_flag_scans_all_matching_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_git_repo(root)
            write_source(root, "src/main/java/example/TooLarge.java", "line 1\nline 2\n")
            write_source(root, "src/main/java/example/Changed.java", "line 1\n")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            write_source(root, "src/main/java/example/Changed.java", "changed\n")
            config_path = root / "supermeta-rules.json"
            config_path.write_text(
                """{
  "line_count": [
    {
      "name": "source-line-count",
      "max_lines": 1,
      "paths": ["src/main/java"],
      "include": ["**/*.java"],
      "exclude": []
    }
  ]
}
""",
                encoding="utf-8",
            )

            exit_code = check.main(["--config", str(config_path), "--root", str(root), "--full"])

            self.assertEqual(1, exit_code)

    def test_dirty_config_file_forces_full_scan(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_git_repo(root)
            write_source(root, "src/main/java/example/TooLarge.java", "line 1\nline 2\n")
            config_path = root / "supermeta-rules.json"
            config_path.write_text(
                """{
  "line_count": [
    {
      "name": "source-line-count",
      "max_lines": 100,
      "paths": ["src/main/java"],
      "include": ["**/*.java"],
      "exclude": []
    }
  ]
}
""",
                encoding="utf-8",
            )
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            config_path.write_text(
                """{
  "line_count": [
    {
      "name": "source-line-count",
      "max_lines": 1,
      "paths": ["src/main/java"],
      "include": ["**/*.java"],
      "exclude": []
    }
  ]
}
""",
                encoding="utf-8",
            )

            exit_code = check.main(["--config", str(config_path), "--root", str(root)])

            self.assertEqual(1, exit_code)


def rust_module_item_count_config(max_items: int = 7) -> dict[str, object]:
    return {
        "rust_module_item_count": [
            {
                "name": "rust-module-size",
                "max_items": max_items,
                "paths": ["src"],
                "include": ["**/*.rs"],
                "exclude": ["**/generated/**"],
            }
        ]
    }


def rust_panic_boundary_config(allow_tests: bool = True) -> dict[str, object]:
    return {
        "rust_panic_boundary": [
            {
                "name": "rust-panic-boundary",
                "paths": ["src"],
                "include": ["**/*.rs"],
                "exclude": ["**/generated/**"],
                "allow_tests": allow_tests,
            }
        ]
    }


def write_rust_functions(root: Path, count: int) -> None:
    source = "\n".join(f"pub fn item_{index}() -> usize {{ {index} }}" for index in range(count))
    write_source(root, "src/big.rs", f"{source}\n")


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


class RustModuleItemCountRuleTest(unittest.TestCase):
    def test_allows_module_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_rust_functions(root, count=7)

            findings = check.run_rules(rust_module_item_count_config(max_items=7), root)

            self.assertEqual([], findings)

    def test_fails_module_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_rust_functions(root, count=8)

            findings = check.run_rules(rust_module_item_count_config(max_items=7), root)

            self.assertEqual(1, len(findings))
            self.assertEqual("rust-module-size", findings[0].rule)
            self.assertEqual(Path("src/big.rs"), findings[0].path)
            self.assertIn("8 Rust top-level items exceeds module limit of 7", findings[0].message)
            assert_domain_split_warning(self, findings[0].message)

    def test_ignores_test_module_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/lib.rs",
                """pub fn production() -> bool {
    true
}

#[cfg(test)]
mod tests {
    fn helper_0() {}
    fn helper_1() {}
    fn helper_2() {}
    fn helper_3() {}
    fn helper_4() {}
    fn helper_5() {}
    fn helper_6() {}
    fn helper_7() {}
}
""",
            )

            findings = check.run_rules(rust_module_item_count_config(max_items=7), root)

            self.assertEqual([], findings)


class RustPanicBoundaryRuleTest(unittest.TestCase):
    def test_rejects_unwrap_expect_and_debug_macros(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main.rs",
                """fn main() {
    let value = Some(\"ok\").unwrap();
    let _other = Some(value).expect(\"value should exist\");
    dbg!(_other);
    todo!(\"replace starter behavior\");
}
""",
            )

            findings = check.run_rules(rust_panic_boundary_config(), root)

            self.assertEqual(4, len(findings))
            self.assertTrue(all(finding.rule == "rust-panic-boundary" for finding in findings))
            self.assertIn("panic-prone construct `.unwrap(`", findings[0].message)
            self.assertIn("panic-prone construct `.expect(`", findings[1].message)
            self.assertIn("panic-prone construct `dbg!`", findings[2].message)
            self.assertIn("panic-prone construct `todo!`", findings[3].message)

    def test_ignores_panic_constructs_in_cfg_test_modules_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/lib.rs",
                """pub fn production() -> Option<&'static str> {
    Some(\"ok\")
}

#[cfg(test)]
mod tests {
    #[test]
    fn allows_test_unwraps() {
        let value = production().unwrap();
        assert_eq!(\"ok\", value);
    }
}
""",
            )

            findings = check.run_rules(rust_panic_boundary_config(), root)

            self.assertEqual([], findings)

    def test_ignores_cfg_test_modules_with_raw_strings_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/lib.rs",
                """pub fn production() -> Option<&'static str> {
    Some("ok")
}

#[cfg(test)]
mod tests {
    #[test]
    fn allows_raw_fixture_and_test_expect() {
        let fixture = r#""}}""#;
        let value = production().expect("test-only assert");
        assert_eq!(Some(fixture), value);
    }
}
""",
            )

            findings = check.run_rules(rust_panic_boundary_config(), root)

            self.assertEqual([], findings)

    def test_can_scan_cfg_test_modules_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/lib.rs",
                """#[cfg(test)]
mod tests {
    #[test]
    fn rejects_test_unwraps() {
        let value = Some(\"ok\").unwrap();
        assert_eq!(\"ok\", value);
    }
}
""",
            )

            findings = check.run_rules(rust_panic_boundary_config(allow_tests=False), root)

            self.assertEqual(1, len(findings))
            self.assertIn("panic-prone construct `.unwrap(`", findings[0].message)


class JavaPackageClassCountRuleTest(unittest.TestCase):
    def test_allows_package_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_files(root, "src/main/java/example", count=7)

            findings = check.run_rules(java_package_count_config(max_classes=7), root)

            self.assertEqual([], findings)

    def test_fails_package_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_files(root, "src/main/java/example", count=8)

            findings = check.run_rules(java_package_count_config(max_classes=7), root)

            self.assertEqual(1, len(findings))
            self.assertEqual("java-package-size", findings[0].rule)
            self.assertEqual(Path("src/main/java/example"), findings[0].path)
            self.assertIn("8 Java top-level types exceeds package layer limit of 7", findings[0].message)
            self.assertIn(
                "refactor this layer into cohesive subpackages based on the system context",
                findings[0].message,
            )

    def test_counts_multiple_top_level_classes_in_one_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/MixedTypes.java",
                """package example;

final class Type0 {}
final class Type1 {}
final class Type2 {}
final class Type3 {}
final class Type4 {}
final class Type5 {}
final class Type6 {}
final class Type7 {}
""",
            )

            findings = check.run_rules(java_package_count_config(max_classes=7), root)

            self.assertEqual(1, len(findings))
            self.assertIn("8 Java top-level types", findings[0].message)

    def test_ignores_nested_classes_when_counting_package_layer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/App.java",
                """package example;

final class App {
    static final class Nested0 {}
    static final class Nested1 {}
    static final class Nested2 {}
    static final class Nested3 {}
    static final class Nested4 {}
    static final class Nested5 {}
    static final class Nested6 {}
    static final class Nested7 {}
}
""",
            )

            findings = check.run_rules(java_package_count_config(max_classes=7), root)

            self.assertEqual([], findings)

    def test_counts_subpackages_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_java_files(root, "src/main/java/example", count=7)
            write_java_files(root, "src/main/java/example/nested", count=7)

            findings = check.run_rules(java_package_count_config(max_classes=7), root)

            self.assertEqual([], findings)


class JavaImportStyleRuleTest(unittest.TestCase):
    def test_allows_wildcard_imports(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/App.java",
                """package example;

import java.util.*;
import static org.junit.jupiter.api.Assertions.*;

final class App {}
""",
            )

            findings = check.run_rules(java_import_style_config(), root)

            self.assertEqual([], findings)

    def test_rejects_explicit_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/App.java",
                """package example;

import java.util.List;

final class App {}
""",
            )

            findings = check.run_rules(java_import_style_config(), root)

            self.assertEqual(1, len(findings))
            self.assertEqual("java-wildcard-imports", findings[0].rule)
            self.assertEqual(Path("src/main/java/example/App.java"), findings[0].path)
            self.assertIn("explicit import java.util.List", findings[0].message)
            self.assertIn("use java.util.*", findings[0].message)

    def test_rejects_explicit_static_import(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/test/java/example/AppTest.java",
                """package example;

import static org.junit.jupiter.api.Assertions.assertEquals;

final class AppTest {}
""",
            )

            findings = check.run_rules(java_import_style_config(paths=["src/test/java"]), root)

            self.assertEqual(1, len(findings))
            self.assertEqual(Path("src/test/java/example/AppTest.java"), findings[0].path)
            self.assertIn("explicit import static org.junit.jupiter.api.Assertions.assertEquals", findings[0].message)
            self.assertIn("use static org.junit.jupiter.api.Assertions.*", findings[0].message)

    def test_allows_explicit_import_when_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/App.java",
                """package example;

import java.util.List;
import static org.junit.jupiter.api.Assertions.assertEquals;

final class App {}
""",
            )

            findings = check.run_rules(
                java_import_style_config(
                    allow_explicit=[
                        "java.util.List",
                        "static org.junit.jupiter.api.Assertions.assertEquals",
                    ]
                ),
                root,
            )

            self.assertEqual([], findings)

    def test_honors_import_exclusions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/generated/GeneratedThing.java",
                """package generated;

import java.util.List;

final class GeneratedThing {}
""",
            )

            findings = check.run_rules(java_import_style_config(exclude=["**/generated/**"]), root)

            self.assertEqual([], findings)


class JavaLombokBoilerplateRuleTest(unittest.TestCase):
    def test_rejects_simple_getter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
final class Person {
    private final String name;

    String getName() {
        return name;
    }
}
""",
            )

            findings = check.run_rules(java_lombok_boilerplate_config(), root)

            self.assertEqual(1, len(findings))
            self.assertEqual("java-lombok-boilerplate", findings[0].rule)
            self.assertIn("getName() is Lombok boilerplate", findings[0].message)
            self.assertIn("use Lombok", findings[0].message)

    def test_rejects_boolean_getter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
final class Person {
    private boolean active;

    boolean isActive() {
        return active;
    }
}
""",
            )

            findings = check.run_rules(java_lombok_boilerplate_config(), root)

            self.assertEqual(1, len(findings))
            self.assertIn("isActive() is Lombok boilerplate", findings[0].message)

    def test_rejects_simple_setter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
final class Person {
    private String name;

    void setName(String name) {
        this.name = name;
    }
}
""",
            )

            findings = check.run_rules(java_lombok_boilerplate_config(), root)

            self.assertEqual(1, len(findings))
            self.assertIn("setName() is Lombok boilerplate", findings[0].message)

    def test_allows_override_accessors_as_interface_contract(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
interface Named {
    String getName();

    void setName(String name);
}

final class Person implements Named {
    private String name;

    @Override
    public String getName() {
        return name;
    }

    @Override
    public void setName(String name) {
        this.name = name;
    }
}
""",
            )

            findings = check.run_rules(java_lombok_boilerplate_config(), root)

            self.assertEqual([], findings)

    def test_rejects_fluent_setter(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
final class Person {
    private String name;

    Person name(String name) {
        this.name = name;
        return this;
    }
}
""",
            )

            findings = check.run_rules(java_lombok_boilerplate_config(), root)

            self.assertEqual(1, len(findings))
            self.assertIn("name() is Lombok boilerplate", findings[0].message)

    def test_allows_non_trivial_method(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
final class Person {
    private String name;

    String getName() {
        if (name == null || name.isBlank()) {
            return "unknown";
        }
        return name.strip();
    }
}
""",
            )

            findings = check.run_rules(java_lombok_boilerplate_config(), root)

            self.assertEqual([], findings)

    def test_rejects_nested_builder_pattern(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
final class Person {
    private final String name;

    Person(String name) {
        this.name = name;
    }

    static Builder builder() {
        return new Builder();
    }

    static final class Builder {
        private String name;

        Builder name(String name) {
            this.name = name;
            return this;
        }

        Person build() {
            return new Person(name);
        }
    }
}
""",
            )

            findings = check.run_rules(java_lombok_boilerplate_config(), root)

            self.assertGreaterEqual(len(findings), 1)
            self.assertTrue(any("builder" in finding.message.lower() for finding in findings))

    def test_rejects_records_without_lombok_builder_when_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
record CliResult(int exitCode, String out, String err) {
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertEqual("java-lombok-boilerplate", findings[0].rule)
            self.assertIn("should use Lombok @Builder", findings[0].message)
            self.assertIn("use Lombok", findings[0].message)

    def test_allows_records_with_lombok_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
@Builder
record CliResult(int exitCode, String out, String err) {
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual([], findings)

    def test_rejects_record_constructor_calls_when_builder_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/Person.java",
                """package example;

record CliResult(int exitCode, String out, String err) {
}

final class Caller {
    CliResult run() {
        return new CliResult(0, "", "");
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertGreaterEqual(len(findings), 2)
            self.assertTrue(
                any("should be built with CliResult.builder() for readability" in finding.message for finding in findings)
            )
            self.assertTrue(
                any("CliResult is a record and should use Lombok @Builder" in finding.message for finding in findings)
            )

    def test_rejects_record_constructor_calls_even_when_record_has_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/Person.java",
                """package example;

@Builder
record CliResult(int exitCode, String out, String err) {
}

final class Caller {
    CliResult run() {
        return new CliResult(0, "", "");
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertIn("should be built with CliResult.builder() for readability", findings[0].message)

    def test_rejects_record_constructor_calls_in_different_file_when_builder_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/model/CliResult.java",
                """package example.model;

record CliResult(int exitCode, String out, String err) {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Caller.java",
                """package example.service;

import example.model.CliResult;

final class Caller {
    CliResult run() {
        return new CliResult(0, "", "");
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertGreaterEqual(len(findings), 2)
            self.assertTrue(
                any(
                    "should be built with CliResult.builder() for readability" in finding.message
                    for finding in findings
                )
            )
            self.assertTrue(
                any(
                    "CliResult is a record and should use Lombok @Builder" in finding.message
                    for finding in findings
                )
            )

    def test_rejects_qualified_and_generic_record_constructor_calls_when_builder_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/model/Box.java",
                """package example.model;

@Builder
record Box<T>(T value) {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Caller.java",
                """package example.service;

final class Caller {
    example.model.Box<String> runQualified() {
        return new example.model.Box<String>("");
    }

    example.model.Box<String> runDiamond() {
        return new example.model.Box<>("");
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual(2, len(findings))
            self.assertTrue(
                all("should be built with Box.builder() for readability" in finding.message for finding in findings)
            )

    def test_rejects_explicit_constructor_type_arguments_when_builder_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/model/Box.java",
                """package example.model;

@Builder
record Box<T>(T value) {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Caller.java",
                """package example.service;

import example.model.Box;

final class Caller {
    Box<String> runSimple() {
        return new <String> Box<>("");
    }

    Box<String> runQualified() {
        return new <String> example.model.Box<>("");
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual(2, len(findings))
            self.assertTrue(
                all("should be built with Box.builder() for readability" in finding.message for finding in findings)
            )

    def test_rejects_nested_record_constructor_calls_when_builder_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/LoggingConfig.java",
                """package example;

final class LoggingConfig {
    @Builder
    record Config(String level, String format) {
    }
}
""",
            )
            write_source(
                root,
                "src/main/java/example/Caller.java",
                """package example;

final class Caller {
    LoggingConfig.Config run() {
        return new LoggingConfig.Config("info", "json");
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertIn("should be built with Config.builder() for readability", findings[0].message)

    def test_rejects_imported_nested_record_constructor_calls_when_builder_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/LoggingConfig.java",
                """package example;

final class LoggingConfig {
    @Builder
    record Config(String level, String format) {
    }
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Caller.java",
                """package example.service;

import example.LoggingConfig.Config;

final class Caller {
    Config run() {
        return new Config("info", "json");
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertIn("should be built with Config.builder() for readability", findings[0].message)

    def test_allows_non_record_constructor_with_nested_record_simple_name_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/LoggingConfig.java",
                """package example;

final class LoggingConfig {
    @Builder
    record Config(String level, String format) {
    }
}
""",
            )
            write_source(
                root,
                "src/main/java/example/Config.java",
                """package example;

final class Config {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/Caller.java",
                """package example;

final class Caller {
    Config run() {
        return new Config();
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual([], findings)

    def test_rejects_record_constructor_references_when_builder_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/model/CliResult.java",
                """package example.model;

@Builder
record CliResult(int exitCode, String out, String err) {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Caller.java",
                """package example.service;

import example.model.CliResult;

interface ResultFactory {
    CliResult create(int exitCode, String out, String err);
}

final class Caller {
    ResultFactory factory() {
        return CliResult::new;
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertIn("constructor references should use CliResult.builder()", findings[0].message)

    def test_rejects_constructor_reference_type_arguments_when_builder_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/model/Box.java",
                """package example.model;

@Builder
record Box<T>(T value) {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Caller.java",
                """package example.service;

import example.model.Box;

interface BoxFactory<T> {
    Box<T> create(T value);
}

final class Caller {
    BoxFactory<String> factory() {
        return Box::<String>new;
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertIn("constructor references should use Box.builder()", findings[0].message)

    def test_rejects_wildcard_imported_record_constructor_calls_when_builder_required(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/model/CliResult.java",
                """package example.model;

@Builder
record CliResult(int exitCode, String out, String err) {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Caller.java",
                """package example.service;

import example.model.*;

final class Caller {
    CliResult run() {
        return new CliResult(0, "", "");
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertIn("should be built with CliResult.builder() for readability", findings[0].message)

    def test_allows_non_record_constructor_with_record_name_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/model/Result.java",
                """package example.model;

@Builder
record Result(int exitCode) {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/other/Result.java",
                """package example.other;

final class Result {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Caller.java",
                """package example.service;

import example.other.Result;

final class Caller {
    Result run() {
        return new Result();
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual([], findings)

    def test_allows_same_simple_constructor_without_record_import_or_package_match(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/model/Result.java",
                """package example.model;

@Builder
record Result(int exitCode) {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Result.java",
                """package example.service;

final class Result {
}
""",
            )
            write_source(
                root,
                "src/main/java/example/service/Caller.java",
                """package example.service;

final class Caller {
    Result run() {
        return new Result();
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual([], findings)

    def test_allows_record_constructor_calls_with_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/Person.java",
                """package example;

@Builder
record CliResult(int exitCode, String out, String err) {
}

final class Caller {
    CliResult run() {
        return CliResult.builder()
            .exitCode(0)
            .out("")
            .err("")
            .build();
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(require_record_builder=True),
                root,
            )

            self.assertEqual([], findings)

    def test_method_ignore_annotation_suppresses_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
final class Person {
    private final String name;

    @ManualBoilerplate
    String getName() {
        return name;
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(ignore_annotations=["ManualBoilerplate"]),
                root,
            )

            self.assertEqual([], findings)

    def test_class_ignore_annotation_suppresses_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
@ManualBoilerplate
final class Person {
    private final String name;

    String getName() {
        return name;
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(ignore_annotations=["ManualBoilerplate"]),
                root,
            )

            self.assertEqual([], findings)

    def test_fully_qualified_ignore_annotation_suppresses_finding(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
@com.acme.ManualBoilerplate
final class Person {
    private final String name;

    String getName() {
        return name;
    }
}
""",
            )

            findings = check.run_rules(
                java_lombok_boilerplate_config(ignore_annotations=["com.acme.ManualBoilerplate"]),
                root,
            )

            self.assertEqual([], findings)

    def test_allow_methods_suppresses_named_method(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(
                root,
                """
final class Person {
    private final String name;

    String getName() {
        return name;
    }
}
""",
            )

            findings = check.run_rules(java_lombok_boilerplate_config(allow_methods=["getName"]), root)

            self.assertEqual([], findings)

    def test_rejects_invalid_ignore_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(root, "final class Person {}")
            config = java_lombok_boilerplate_config(ignore_annotations=[""])

            with self.assertRaisesRegex(ValueError, "ignore_annotations must be an array of non-empty strings"):
                check.run_rules(config, root)

    def test_rejects_invalid_require_record_builder(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_lombok_sample(root, "record CliResult(int exitCode, String out, String err) {}")

            config = java_lombok_boilerplate_config()
            config["java_lombok_boilerplate"][0]["require_record_builder"] = "yes"

            with self.assertRaisesRegex(ValueError, "require_record_builder must be a boolean"):
                check.run_rules(config, root)


def write_source(root: Path, relative_path: str, source: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def init_git_repo(root: Path) -> None:
    git(root, "init")
    git(root, "config", "user.email", "agent@example.invalid")
    git(root, "config", "user.name", "Agent")


def git(root: Path, *args: str) -> None:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{result.stdout}")


def assert_domain_split_warning(test_case: unittest.TestCase, message: str) -> None:
    test_case.assertIn("Do not satisfy this by creating numbered split files", message)
    test_case.assertIn("real, concrete, appropriate domain separation", message)
    test_case.assertIn("coherent responsibilities", message)


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


def java_package_count_config(max_classes: int) -> dict[str, object]:
    return {
        "java_package_class_count": [
            {
                "name": "java-package-size",
                "max_classes": max_classes,
                "paths": ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": ["**/generated/**"],
            }
        ]
    }


def repeated_helper_config(language: str = "java") -> dict[str, object]:
    return {
        "repeated_helper_methods": [
            {
                "name": "repeated-helper-methods",
                "language": language,
                "groups": [
                    {
                        "name": "main",
                        "paths": ["src/main/java"],
                        "include": ["**/*.java"],
                        "exclude": ["**/generated/**"],
                    },
                    {
                        "name": "test",
                        "paths": ["src/test/java"],
                        "include": ["**/*.java"],
                        "exclude": ["**/generated/**"],
                    },
                ],
                "min_statements": 3,
                "near_match_threshold": 0.86,
                "advisory_near_matches": True,
                "ignore_annotations": ["Generated", "ManualDuplication"],
                "allow_methods": [],
            }
        ]
    }


def java_import_style_config(
    paths: list[str] | None = None,
    exclude: list[str] | None = None,
    allow_explicit: list[str] | None = None,
) -> dict[str, object]:
    return {
        "java_import_style": [
            {
                "name": "java-wildcard-imports",
                "paths": paths or ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": exclude or [],
                "allow_explicit": allow_explicit or [],
            }
        ]
    }


def write_lombok_sample(root: Path, class_body: str) -> Path:
    return write_source(
        root,
        "src/main/java/example/Person.java",
        f"""package example;

{class_body.strip()}
""",
    )


def java_lombok_boilerplate_config(
    ignore_annotations: list[str] | None = None,
    allow_methods: list[str] | None = None,
    require_record_builder: bool = False,
) -> dict[str, object]:
    return {
        "java_lombok_boilerplate": [
            {
                "name": "java-lombok-boilerplate",
                "paths": ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": ["**/generated/**"],
                "ignore_annotations": [] if ignore_annotations is None else ignore_annotations,
                "allow_methods": [] if allow_methods is None else allow_methods,
                "require_record_builder": require_record_builder,
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
