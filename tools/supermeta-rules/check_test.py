from __future__ import annotations

import contextlib
import io
import importlib.util
import json
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
repeated_helpers = check.repeated_helpers


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
                    "source_policy_coverage": [{"enabled": False}],
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

    def test_missing_parser_dependency_reports_install_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/Foo.java",
                """package example;
final class Foo {
    private int value() {
        int total = 1;
        return total;
    }
}
""",
            )
            with patch.object(
                repeated_helpers,
                "java_parser",
                side_effect=ValueError(
                    "repeated_helper_methods requires parser dependencies; install "
                    "tools/supermeta-rules/requirements.txt"
                ),
            ):
                with self.assertRaisesRegex(ValueError, "requires parser dependencies"):
                    check.run_rules(repeated_helper_config(), root, force_full=True)

    def test_rule_dispatch_reports_exact_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/Alpha.java",
                """package example;

final class Alpha {
    private int checksum(String name) {
        int total = name.length();
        total = total + 7;
        return total;
    }
}
""",
            )
            write_source(
                root,
                "src/main/java/example/Beta.java",
                """package example;

final class Beta {
    private int otherChecksum(String label) {
        int result = label.length();
        result = result + 7;
        return result;
    }
}
""",
            )

            findings = check.run_rules(repeated_helper_config(), root)

            self.assertEqual(1, len(findings))
            self.assertEqual("repeated-helper-methods", findings[0].rule)
            self.assertEqual("error", findings[0].severity)
            self.assertIn("duplicates helper body", findings[0].message)

    def test_generated_excludes_are_honored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/generated/Alpha.java",
                """package generated;

final class Alpha {
    private int checksum(String name) {
        int total = name.length();
        total = total + 7;
        return total;
    }
}
""",
            )
            write_source(
                root,
                "src/main/java/generated/Beta.java",
                """package generated;

final class Beta {
    private int otherChecksum(String label) {
        int result = label.length();
        result = result + 7;
        return result;
    }
}
""",
            )

            findings = check.run_rules(repeated_helper_config(), root)

            self.assertEqual([], findings)

    def test_near_duplicate_does_not_fail_main(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/test/java/example/AlphaTest.java",
                """package example;

final class AlphaTest {
    int checksum(String name) {
        int total = name.length();
        total = total + adjustment();
        return total;
    }
}
""",
            )
            write_source(
                root,
                "src/test/java/example/BetaTest.java",
                """package example;

final class BetaTest {
    int otherChecksum(String name) {
        int total = name.length();
        total = total + offset();
        return total;
    }
}
""",
            )
            config_path = root / "supermeta-rules.json"
            config_path.write_text(json.dumps(repeated_helper_config()), encoding="utf-8")

            output = io.StringIO()
            error = io.StringIO()
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                exit_code = check.main(["--config", str(config_path), "--root", str(root), "--full"])

            self.assertEqual(0, exit_code)
            self.assertIn("Supermeta rule advisories:", output.getvalue())
            self.assertIn("Supermeta rules passed.", output.getvalue())


class RepeatedHelperMethodCacheTest(unittest.TestCase):
    def test_java_rules_share_one_source_snapshot_per_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = write_source(
                root,
                "src/main/java/example/App.java",
                """package example;

import java.util.List;

final class App {
    private String name;

    private int compute() {
        int total = 1;
        total += 2;
        return total;
    }

    String getName() {
        return name;
    }
}
""",
            ).resolve()
            read_bytes_calls: list[Path] = []
            original_read_bytes = Path.read_bytes
            original_read_text = Path.read_text

            def counted_read_bytes(path: Path) -> bytes:
                if path.resolve() == source_file:
                    read_bytes_calls.append(path.resolve())
                return original_read_bytes(path)

            def fail_source_read_text(path: Path, *args: object, **kwargs: object) -> str:
                if path.resolve() == source_file:
                    raise AssertionError("rule source reads should go through the shared file snapshot")
                return original_read_text(path, *args, **kwargs)

            with (
                patch.object(Path, "read_bytes", counted_read_bytes),
                patch.object(Path, "read_text", fail_source_read_text),
            ):
                check.run_rules(java_file_fact_config(), root, force_full=True)

            self.assertEqual([source_file], read_bytes_calls)

    def test_unchanged_file_reuses_cached_file_facts_across_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source_file = write_source(
                root,
                "src/main/java/example/App.java",
                """package example;

import java.util.List;

final class App {
    private String name;

    private int compute() {
        int total = 1;
        total += 2;
        return total;
    }

    String getName() {
        return name;
    }
}
""",
            ).resolve()
            cache_file = root / ".gradle" / "supermeta-rules" / "cache-v1.json"
            check.run_rules(java_file_fact_config(), root, force_full=True, cache_file=cache_file)

            original_read_bytes = Path.read_bytes
            original_read_text = Path.read_text
            read_bytes_calls: list[Path] = []

            def counted_read_bytes(path: Path) -> bytes:
                if path.resolve() == source_file:
                    read_bytes_calls.append(path.resolve())
                return original_read_bytes(path)

            def fail_source_read_text(path: Path, *args: object, **kwargs: object) -> str:
                if path.resolve() == source_file:
                    raise AssertionError("cached fact lookup should not call Path.read_text for source files")
                return original_read_text(path, *args, **kwargs)

            with (
                patch.object(Path, "read_bytes", counted_read_bytes),
                patch.object(Path, "read_text", fail_source_read_text),
                patch.object(check, "count_lines", side_effect=AssertionError("line count should be cached")),
                patch.object(
                    check,
                    "strip_java_comments_and_strings",
                    side_effect=AssertionError("stripped Java source should be cached"),
                ),
                patch.object(
                    repeated_helpers,
                    "extract_java_helpers",
                    side_effect=AssertionError("helper candidates should be cached"),
                ),
            ):
                check.run_rules(java_file_fact_config(), root, force_full=True, cache_file=cache_file)

            self.assertEqual([source_file], read_bytes_calls)

    def test_record_constructor_usage_index_is_built_once_per_source_and_cached(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            record_count = 24
            records = "\n\n".join(
                f"""@Builder
record Event{i}(int value) {{
}}"""
                for i in range(record_count)
            )
            factories = "\n".join(
                f"    IntFactory<Event{i}> factory{i}() {{ return Event{i}::new; }}"
                for i in range(record_count)
            )
            constructors = "\n".join(
                f"    Event{i} create{i}() {{ return new Event{i}({i}); }}"
                for i in range(record_count)
            )
            write_source(
                root,
                "src/main/java/example/Records.java",
                f"""package example;

{records}
""",
            )
            write_source(
                root,
                "src/main/java/example/Caller.java",
                f"""package example;

interface IntFactory<T> {{
    T create(int value);
}}

final class Caller {{
{constructors}

{factories}
}}
""",
            )
            cache_file = root / ".gradle" / "supermeta-rules" / "cache-v1.json"
            constructor_usage_calls: list[str] = []
            original_constructor_usages = check.java_constructor_usages

            def counted_constructor_usages(source: str) -> tuple[object, ...]:
                constructor_usage_calls.append(source)
                return original_constructor_usages(source)

            with patch.object(check, "java_constructor_usages", side_effect=counted_constructor_usages):
                first = check.run_rules(
                    java_lombok_boilerplate_config(require_record_builder=True),
                    root,
                    force_full=True,
                    cache_file=cache_file,
                )

            constructor_findings = [
                finding
                for finding in first
                if "should be built with" in finding.message or "constructor references should use" in finding.message
            ]
            self.assertEqual(record_count * 2, len(constructor_findings))
            self.assertEqual(2, len(constructor_usage_calls))

            with patch.object(
                check,
                "java_constructor_usages",
                side_effect=AssertionError("unchanged Java constructor usages should be cached"),
            ):
                second = check.run_rules(
                    java_lombok_boilerplate_config(require_record_builder=True),
                    root,
                    force_full=True,
                    cache_file=cache_file,
                )

            second_constructor_findings = [
                finding
                for finding in second
                if "should be built with" in finding.message or "constructor references should use" in finding.message
            ]
            self.assertEqual(record_count * 2, len(second_constructor_findings))

    def test_unchanged_files_reuse_cached_helper_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "src/main/java/example/Alpha.java", helper_source("Alpha", "same"))
            write_source(root, "src/main/java/example/Beta.java", helper_source("Beta", "same"))
            cache_file = root / ".gradle" / "supermeta-rules" / "cache-v1.json"
            calls: list[str] = []

            def fake_extract(config: object, source_file: object) -> list[object]:
                calls.append(source_file.path.as_posix())
                return [helper_candidate(source_file.group, source_file.path, tuple(["same"]))]

            with patch.object(repeated_helpers, "extract_java_helpers", side_effect=fake_extract):
                first = check.run_rules(repeated_helper_config(), root, force_full=True, cache_file=cache_file)

            self.assertEqual(1, len(first))
            self.assertEqual(
                ["src/main/java/example/Alpha.java", "src/main/java/example/Beta.java"],
                sorted(calls),
            )

            calls.clear()
            with patch.object(
                repeated_helpers,
                "extract_java_helpers",
                side_effect=AssertionError("unchanged files should use cached candidates"),
            ):
                second = check.run_rules(repeated_helper_config(), root, force_full=True, cache_file=cache_file)

            self.assertEqual(1, len(second))
            self.assertEqual([], calls)

    def test_changed_file_reanalyzes_only_that_file_and_keeps_cross_file_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            alpha = write_source(root, "src/main/java/example/Alpha.java", helper_source("Alpha", "same"))
            beta = write_source(root, "src/main/java/example/Beta.java", helper_source("Beta", "different"))
            cache_file = root / ".gradle" / "supermeta-rules" / "cache-v1.json"
            calls: list[str] = []

            def fake_extract(config: object, source_file: object) -> list[object]:
                calls.append(source_file.path.as_posix())
                token = "same" if "same" in source_file.source else source_file.path.stem
                return [helper_candidate(source_file.group, source_file.path, tuple([token]))]

            with patch.object(repeated_helpers, "extract_java_helpers", side_effect=fake_extract):
                first = check.run_rules(repeated_helper_config(), root, force_full=True, cache_file=cache_file)

            self.assertEqual([], first)
            self.assertEqual({alpha.relative_to(root).as_posix(), beta.relative_to(root).as_posix()}, set(calls))

            beta.write_text(helper_source("Beta", "same"), encoding="utf-8")
            calls.clear()
            with patch.object(repeated_helpers, "extract_java_helpers", side_effect=fake_extract):
                second = check.run_rules(repeated_helper_config(), root, force_full=True, cache_file=cache_file)

            self.assertEqual(["src/main/java/example/Beta.java"], calls)
            self.assertEqual(1, len(second))
            self.assertIn("duplicates helper body", second[0].message)

    def test_no_cache_forces_reanalysis(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "src/main/java/example/Alpha.java", helper_source("Alpha", "same"))
            cache_file = root / ".gradle" / "supermeta-rules" / "cache-v1.json"
            calls: list[str] = []

            def fake_extract(config: object, source_file: object) -> list[object]:
                calls.append(source_file.path.as_posix())
                return [helper_candidate(source_file.group, source_file.path, tuple(["same"]))]

            with patch.object(repeated_helpers, "extract_java_helpers", side_effect=fake_extract):
                check.run_rules(repeated_helper_config(), root, force_full=True, cache_file=cache_file)
                check.run_rules(
                    repeated_helper_config(),
                    root,
                    force_full=True,
                    cache_file=cache_file,
                    no_cache=True,
                )

            self.assertEqual(["src/main/java/example/Alpha.java", "src/main/java/example/Alpha.java"], calls)

    def test_cache_report_includes_hit_and_miss_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "src/main/java/example/Alpha.java", helper_source("Alpha", "same"))
            cache_file = root / ".gradle" / "supermeta-rules" / "cache-v1.json"
            stream = io.StringIO()

            def fake_extract(config: object, source_file: object) -> list[object]:
                return [helper_candidate(source_file.group, source_file.path, tuple(["same"]))]

            with patch.object(repeated_helpers, "extract_java_helpers", side_effect=fake_extract):
                check.run_rules(repeated_helper_config(), root, force_full=True, cache_file=cache_file)
                check.run_rules(
                    repeated_helper_config(),
                    root,
                    force_full=True,
                    cache_file=cache_file,
                    cache_report=True,
                    progress=check.RuleProgress(stream, file_interval=1, time_interval_seconds=999),
                )

            self.assertIn("cache hits=2", stream.getvalue())

    def test_unchanged_candidate_set_reuses_cached_repeated_helper_findings(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "src/main/java/example/Alpha.java", helper_source("Alpha", "same"))
            write_source(root, "src/main/java/example/Beta.java", helper_source("Beta", "different"))
            cache_file = root / ".gradle" / "supermeta-rules" / "cache-v1.json"

            def fake_extract(config: object, source_file: object) -> list[object]:
                token = "same" if "same" in source_file.source else "different"
                return [helper_candidate(source_file.group, source_file.path, tuple([token]))]

            with patch.object(repeated_helpers, "extract_java_helpers", side_effect=fake_extract):
                first = check.run_rules(repeated_helper_config(), root, force_full=True, cache_file=cache_file)

            self.assertEqual([], first)
            with (
                patch.object(
                    repeated_helpers,
                    "extract_java_helpers",
                    side_effect=AssertionError("helper candidates should be cached"),
                ),
                patch.object(
                    repeated_helpers,
                    "near_duplicate_findings",
                    side_effect=AssertionError("near-match comparison findings should be cached"),
                ),
            ):
                second = check.run_rules(repeated_helper_config(), root, force_full=True, cache_file=cache_file)

            self.assertEqual([], second)


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

    def test_json_output_reports_fixability_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_path = root / "supermeta-rules.json"
            config_path.write_text("{}", encoding="utf-8")
            with patch.object(
                check,
                "run_rules",
                return_value=[
                    check.Finding(
                        rule="java-wildcard-imports",
                        path=Path("src/main/java/example/App.java"),
                        message="explicit import java.util.List",
                        fixability="auto",
                        repair_hint="rewrite import",
                    )
                ],
            ):
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    exit_code = check.main(["--json", "--config", str(config_path), "--root", str(root), "--full"])

            payload = json.loads(output.getvalue())
            self.assertEqual(1, exit_code)
            self.assertEqual(1, payload["summary"]["errorCount"])
            self.assertEqual("auto", payload["findings"][0]["fixability"])
            self.assertEqual("rewrite import", payload["findings"][0]["repairHint"])


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
                            "max_lines": 2,
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

    def test_line_count_rule_can_opt_out_of_working_set_narrowing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_git_repo(root)
            write_source(root, "src/styles/too-large.css", "line 1\nline 2\n")
            write_source(root, "src/styles/changed.css", "line 1\n")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            write_source(root, "src/styles/changed.css", "changed\n")

            findings = check.run_rules(
                {
                    "line_count": [
                        {
                            "name": "layout-source",
                            "max_lines": 1,
                            "paths": ["src/styles"],
                            "include": ["**/*.css"],
                            "exclude": [],
                            "narrow_to_working_set": False,
                        }
                    ]
                },
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertEqual(Path("src/styles/too-large.css"), findings[0].path)

    def test_full_scan_uses_git_visible_files_and_ignores_build_noise(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_git_repo(root)
            write_source(root, ".gitignore", "build/\n")
            write_source(root, "src/main/java/example/App.java", "package example;\nfinal class App {}\n")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            write_source(root, "src/main/java/example/NewFile.java", "package example;\nfinal class NewFile {}\n")
            write_source(root, "build/generated/TooLarge.java", "line 1\nline 2\n")

            findings = check.run_rules(
                {
                    "line_count": [
                        {
                            "name": "source-line-count",
                            "max_lines": 2,
                            "paths": ["."],
                            "include": ["**/*.java"],
                            "exclude": [],
                        }
                    ]
                },
                root,
                force_full=True,
            )

            self.assertEqual([], findings)

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

    def test_periodic_full_scan_runs_after_configured_fast_scans(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_git_repo(root)
            write_source(root, "src/main/java/example/TooLarge.java", "line 1\nline 2\n")
            write_source(root, "src/main/java/example/Changed.java", "line 1\n")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            write_source(root, "src/main/java/example/Changed.java", "changed\n")
            config = {
                "line_count": [
                    {
                        "name": "source-line-count",
                        "max_lines": 1,
                        "paths": ["src/main/java"],
                        "include": ["**/*.java"],
                        "exclude": [],
                    }
                ]
            }

            with patch.dict(os.environ, {"SUPERMETA_RULES_FAST_SCAN_INTERVAL": "2"}):
                first = check.run_rules(config, root)
                second = check.run_rules(config, root)
                third = check.run_rules(config, root)

            self.assertEqual([], first)
            self.assertEqual([], second)
            self.assertEqual(1, len(third))
            self.assertEqual(Path("src/main/java/example/TooLarge.java"), third[0].path)


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


class SourcePolicyCoverageRuleTest(unittest.TestCase):
    def test_structural_rule_coverage_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "src/main/java/example/App.java", "package example;\nfinal class App {}\n")

            findings = check.run_rules(source_policy_config(), root, skip_callouts=True)

            self.assertEqual([], findings)

    def test_callout_only_source_is_not_considered_covered(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "src/main/java/example/App.java", "package example;\nfinal class App {}\n")
            config = {
                "project_callouts": [
                    {
                        "name": "java-checkstyle",
                        "language": "java",
                        "paths": ["src/main/java"],
                        "include": ["**/*.java"],
                        "exclude": [],
                        "command": [sys.executable, "-c", "pass"],
                    }
                ],
                "source_policy_coverage": [source_policy_rule()],
            }

            findings = check.run_rules(config, root, skip_callouts=True)

            self.assertEqual(1, len(findings))
            self.assertEqual("source-policy-coverage", findings[0].rule)
            self.assertEqual(Path("src/main/java/example/App.java"), findings[0].path)

    def test_generated_source_can_be_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "src/generated/java/example/App.java", "package example;\nfinal class App {}\n")
            config = {
                "source_policy_coverage": [
                    {
                        **source_policy_rule(),
                        "exclude": ["**/generated/**"],
                    }
                ]
            }

            findings = check.run_rules(config, root)

            self.assertEqual([], findings)

    def test_shebang_scripts_are_source_candidates(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "scripts/verify-tools", "#!/usr/bin/env bash\necho ok\n")

            findings = check.run_rules({"source_policy_coverage": [source_policy_rule()]}, root)

            self.assertEqual(1, len(findings))
            self.assertEqual(Path("scripts/verify-tools"), findings[0].path)

    def test_non_source_files_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(root, "README.md", "# docs\n")

            findings = check.run_rules({"source_policy_coverage": [source_policy_rule()]}, root)

            self.assertEqual([], findings)


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


class JavascriptPackageFileCountRuleTest(unittest.TestCase):
    def test_allows_package_at_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_javascript_files(root, "src/tui/session", count=7)

            findings = check.run_rules(javascript_package_count_config(max_files=7), root)

            self.assertEqual([], findings)

    def test_allows_nested_package_when_min_depth_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_javascript_files(root, "src/tui/session", count=7)

            findings = check.run_rules(
                javascript_package_count_config(max_files=7, min_package_depth=1),
                root,
            )

            self.assertEqual([], findings)

    def test_fails_source_root_files_when_min_depth_is_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_javascript_files(root, "src", count=1)

            findings = check.run_rules(
                javascript_package_count_config(max_files=7, min_package_depth=1),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertEqual("javascript-package-size", findings[0].rule)
            self.assertEqual(Path("src/module-0.ts"), findings[0].path)
            self.assertIn("JavaScript/TypeScript file is at the package root", findings[0].message)
            self.assertIn("at least 1 package directory deep", findings[0].message)

    def test_fails_package_over_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_javascript_files(root, "src/tui/session", count=8)

            findings = check.run_rules(javascript_package_count_config(max_files=7), root)

            self.assertEqual(1, len(findings))
            self.assertEqual("javascript-package-size", findings[0].rule)
            self.assertEqual(Path("src/tui/session"), findings[0].path)
            self.assertIn(
                "8 JavaScript/TypeScript files exceeds package layer limit of 7",
                findings[0].message,
            )
            self.assertIn(
                "refactor this layer into cohesive subpackages based on the system context",
                findings[0].message,
            )

    def test_counts_subpackages_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_javascript_files(root, "src/tui/session", count=7)
            write_javascript_files(root, "src/tui/session/actions", count=7)

            findings = check.run_rules(javascript_package_count_config(max_files=7), root)

            self.assertEqual([], findings)

    def test_cross_file_javascript_package_rules_still_scan_full_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_git_repo(root)
            write_source(root, "src/too-flat.ts", "export const flat = true;\n")
            write_source(root, "src/other/changed.ts", "export const changed = 1;\n")
            git(root, "add", ".")
            git(root, "commit", "-m", "baseline")
            write_source(root, "src/other/changed.ts", "export const changed = 2;\n")

            findings = check.run_rules(
                javascript_package_count_config(max_files=7, min_package_depth=1),
                root,
            )

            self.assertEqual(1, len(findings))
            self.assertEqual(Path("src/too-flat.ts"), findings[0].path)

    def test_ignores_disabled_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_javascript_files(root, "src/tui/session", count=8)
            config = javascript_package_count_config(max_files=7)
            config["javascript_package_file_count"][0]["enabled"] = False

            findings = check.run_rules(config, root)

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


def write_javascript_files(root: Path, package_path: str, count: int) -> None:
    package_dir = root / package_path
    package_dir.mkdir(parents=True, exist_ok=True)
    for index in range(count):
        (package_dir / f"module-{index}.ts").write_text(
            f"export const value{index} = {index};\n",
            encoding="utf-8",
        )


def helper_source(class_name: str, marker: str) -> str:
    return f"""package example;

final class {class_name} {{
    private int checksum(String name) {{
        int total = name.length();
        total = total + "{marker}".length();
        return total;
    }}
}}
"""


def helper_candidate(group: str, path: Path, normalized_tokens: tuple[str, ...]) -> object:
    return repeated_helpers.HelperCandidate(
        group=group,
        path=path,
        line=4,
        name="checksum",
        normalized_tokens=normalized_tokens,
        structure=("local_variable_declaration", "expression_statement", "return_statement"),
        statement_count=3,
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


def javascript_package_count_config(max_files: int, min_package_depth: int | None = None) -> dict[str, object]:
    rule: dict[str, object] = {
        "name": "javascript-package-size",
        "max_files": max_files,
        "paths": ["src"],
        "include": ["**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx"],
        "exclude": ["**/generated/**"],
    }
    if min_package_depth is not None:
        rule["min_package_depth"] = min_package_depth
    return {
        "javascript_package_file_count": [rule]
    }


def source_policy_rule() -> dict[str, object]:
    return {
        "name": "source-policy-coverage",
        "paths": ["."],
        "include": ["**/*"],
        "exclude": [],
    }


def source_policy_config() -> dict[str, object]:
    return {
        "line_count": [
            {
                "name": "java-source",
                "max_lines": 1000,
                "paths": ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": [],
            }
        ],
        "source_policy_coverage": [source_policy_rule()],
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


def java_file_fact_config() -> dict[str, object]:
    config: dict[str, object] = {
        "line_count": [
            {
                "name": "source-line-count",
                "max_lines": 1,
                "paths": ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": [],
            }
        ],
        "java_package_class_count": [
            {
                "name": "java-package-class-count",
                "max_classes": 5,
                "paths": ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": [],
            }
        ],
        "java_import_style": [
            {
                "name": "java-wildcard-imports",
                "paths": ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": [],
                "allow_explicit": [],
            }
        ],
        "java_lombok_boilerplate": [
            {
                "name": "java-lombok-boilerplate",
                "paths": ["src/main/java"],
                "include": ["**/*.java"],
                "exclude": [],
                "ignore_annotations": ["Generated", "ManualDuplication"],
                "allow_methods": [],
            }
        ],
    }
    config.update(repeated_helper_config())
    return config


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
