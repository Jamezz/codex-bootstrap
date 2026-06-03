from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import repeated_helpers


class JavaHelperExtractionTest(unittest.TestCase):
    def test_extracts_private_helper_with_normalized_local_names(self) -> None:
        source = """package example;

final class App {
    private int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""
        config = helper_config()

        candidates = repeated_helpers.extract_java_helpers(
            config,
            repeated_helpers.GroupSourceFile(
                group="main",
                path=Path("src/main/java/example/App.java"),
                source=source,
            ),
        )

        self.assertEqual(1, len(candidates))
        self.assertEqual("checksum", candidates[0].name)
        self.assertEqual(4, candidates[0].line)
        self.assertEqual("main", candidates[0].group)
        self.assertIn("local:0", candidates[0].normalized_tokens)
        self.assertIn("literal:number", candidates[0].normalized_tokens)
        self.assertNotIn("total", candidates[0].normalized_tokens)
        self.assertNotIn("name", candidates[0].normalized_tokens)
        self.assertGreaterEqual(candidates[0].statement_count, 2)

    def test_ignores_public_production_method(self) -> None:
        source = """package example;

public final class App {
    public int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""
        candidates = repeated_helpers.extract_java_helpers(
            helper_config(),
            repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/App.java"), source),
        )

        self.assertEqual([], candidates)

    def test_allows_package_private_test_helper(self) -> None:
        source = """package example;

final class AppTest {
    int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""
        candidates = repeated_helpers.extract_java_helpers(
            helper_config(),
            repeated_helpers.GroupSourceFile("test", Path("src/test/java/example/AppTest.java"), source),
        )

        self.assertEqual(["checksum"], [candidate.name for candidate in candidates])

    def test_ignores_annotated_test_method_but_allows_unannotated_test_helper(self) -> None:
        source = """package example;

final class AppTest {
    @Test
    void calculates() {
        int total = 1;
        assertEquals(1, total);
    }

    int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""
        candidates = repeated_helpers.extract_java_helpers(
            helper_config(),
            repeated_helpers.GroupSourceFile("test", Path("src/test/java/example/AppTest.java"), source),
        )

        self.assertEqual(["checksum"], [candidate.name for candidate in candidates])

    def test_counts_nested_control_flow_statements(self) -> None:
        source = """package example;

final class App {
    private void nested(boolean ready) {
        if (ready) {
            first();
            second();
        }
    }
}
"""
        candidates = repeated_helpers.extract_java_helpers(
            helper_config(min_statements=2),
            repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/App.java"), source),
        )

        self.assertEqual(["nested"], [candidate.name for candidate in candidates])
        self.assertGreaterEqual(candidates[0].statement_count, 2)

    def test_normalizes_lambda_and_catch_parameter_names(self) -> None:
        source = """package example;

final class App {
    private void consume(List<String> items) {
        items.forEach(item -> {
            sink(item);
        });
        try {
            risky();
        } catch (IllegalStateException problem) {
            sink(problem.getMessage());
        }
    }
}
"""
        candidates = repeated_helpers.extract_java_helpers(
            helper_config(),
            repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/App.java"), source),
        )

        self.assertEqual(1, len(candidates))
        self.assertIn("local:1", candidates[0].normalized_tokens)
        self.assertIn("local:2", candidates[0].normalized_tokens)
        self.assertNotIn("id:item", candidates[0].normalized_tokens)
        self.assertNotIn("id:problem", candidates[0].normalized_tokens)

    def test_ignores_override_and_configured_annotations(self) -> None:
        source = """package example;

final class App {
    @Override
    private String toText() {
        String value = "x";
        return value.trim();
    }

    @ManualDuplication
    private String manual() {
        String value = "x";
        return value.trim();
    }
}
"""
        candidates = repeated_helpers.extract_java_helpers(
            helper_config(ignore_annotations=("ManualDuplication",)),
            repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/App.java"), source),
        )

        self.assertEqual([], candidates)

    def test_ignores_configured_enclosing_type_annotation(self) -> None:
        source = """package example;

@ManualDuplication
final class App {
    private String manual() {
        String value = "x";
        return value.trim();
    }
}
"""
        candidates = repeated_helpers.extract_java_helpers(
            helper_config(ignore_annotations=("ManualDuplication",)),
            repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/App.java"), source),
        )

        self.assertEqual([], candidates)

    def test_allow_methods_suppresses_named_helper(self) -> None:
        source = """package example;

final class App {
    private String manual() {
        String value = "x";
        return value.trim();
    }
}
"""
        config = helper_config()
        config = repeated_helpers.RepeatedHelperConfig(
            name=config.name,
            language=config.language,
            groups=config.groups,
            min_statements=config.min_statements,
            near_match_threshold=config.near_match_threshold,
            advisory_near_matches=config.advisory_near_matches,
            ignore_annotations=config.ignore_annotations,
            allow_methods=frozenset({"manual"}),
        )

        candidates = repeated_helpers.extract_java_helpers(
            config,
            repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/App.java"), source),
        )

        self.assertEqual([], candidates)

    def test_ignores_non_static_package_private_production_method(self) -> None:
        source = """package example;

final class App {
    int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""
        candidates = repeated_helpers.extract_java_helpers(
            helper_config(),
            repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/App.java"), source),
        )

        self.assertEqual([], candidates)

    def test_ignores_tiny_helpers(self) -> None:
        source = """package example;

final class App {
    private int value() {
        return 7;
    }
}
"""
        candidates = repeated_helpers.extract_java_helpers(
            helper_config(min_statements=2),
            repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/App.java"), source),
        )

        self.assertEqual([], candidates)

    def test_syntax_error_names_file(self) -> None:
        with self.assertRaisesRegex(
            ValueError,
            "src/main/java/example/Broken.java: Java parser reported syntax errors",
        ):
            repeated_helpers.extract_java_helpers(
                helper_config(),
                repeated_helpers.GroupSourceFile(
                    "main",
                    Path("src/main/java/example/Broken.java"),
                    "package example; final class Broken { private int value( { return 1; } }",
                ),
            )


class RepeatedHelperExactDuplicateTest(unittest.TestCase):
    def test_exact_normalized_duplicate_between_main_helpers_fails_once(self) -> None:
        source_a = """package example;

final class Alpha {
    private int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""
        source_b = """package example;

final class Beta {
    private int otherChecksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""

        findings = repeated_helpers.find_repeated_helpers(
            helper_config(),
            [
                repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/Alpha.java"), source_a),
                repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/Beta.java"), source_b),
            ],
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("error", findings[0].severity)
        self.assertEqual(Path("src/main/java/example/Alpha.java"), findings[0].path)
        self.assertIn("duplicates helper body", findings[0].message)
        self.assertIn("src/main/java/example/Beta.java", findings[0].message)
        self.assertIn("factor this helper into common code", findings[0].message)

    def test_renamed_locals_and_parameters_normalize_to_same_duplicate(self) -> None:
        source_a = """package example;

final class Alpha {
    private int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""
        source_b = """package example;

final class Beta {
    private int checksum(String label) {
        int result = label.length();
        return result + 7;
    }
}
"""

        findings = repeated_helpers.find_repeated_helpers(
            helper_config(),
            [
                repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/Alpha.java"), source_a),
                repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/Beta.java"), source_b),
            ],
        )

        self.assertEqual(1, len(findings))
        self.assertIn("duplicates helper body", findings[0].message)

    def test_finding_path_is_first_sorted_duplicate_path(self) -> None:
        source_a = """package example;

final class Zeta {
    private int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""
        source_b = """package example;

final class Alpha {
    private int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""

        findings = repeated_helpers.find_repeated_helpers(
            helper_config(),
            [
                repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/Zeta.java"), source_a),
                repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/Alpha.java"), source_b),
            ],
        )

        self.assertEqual(1, len(findings))
        self.assertEqual(Path("src/main/java/example/Alpha.java"), findings[0].path)

    def test_identical_helper_body_in_main_and_test_groups_does_not_compare(self) -> None:
        source_a = """package example;

final class App {
    private int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""
        source_b = """package example;

final class AppTest {
    int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
"""

        findings = repeated_helpers.find_repeated_helpers(
            helper_config(),
            [
                repeated_helpers.GroupSourceFile("main", Path("src/main/java/example/App.java"), source_a),
                repeated_helpers.GroupSourceFile("test", Path("src/test/java/example/AppTest.java"), source_b),
            ],
        )

        self.assertEqual([], findings)


class RepeatedHelperNearMatchTest(unittest.TestCase):
    def test_near_duplicate_in_test_group_reports_one_advisory_by_default(self) -> None:
        source_a = """package example;

final class AlphaTest {
    int checksum(String name) {
        int total = name.length();
        total = total + 7;
        return total;
    }
}
"""
        source_b = """package example;

final class BetaTest {
    int otherChecksum(String name) {
        int total = name.length();
        total = total + 8;
        return total;
    }
}
"""

        findings = repeated_helpers.find_repeated_helpers(
            helper_config(),
            [
                repeated_helpers.GroupSourceFile("test", Path("src/test/java/example/AlphaTest.java"), source_a),
                repeated_helpers.GroupSourceFile("test", Path("src/test/java/example/BetaTest.java"), source_b),
            ],
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("advisory", findings[0].severity)
        self.assertIn("is similar to", findings[0].message)
        self.assertIn("review these helpers for shared", findings[0].message)

    def test_structurally_different_helpers_do_not_report_near_match(self) -> None:
        source_a = """package example;

final class AlphaTest {
    int checksum(String name) {
        int total = name.length();
        total = total + 7;
        return total;
    }
}
"""
        source_b = """package example;

final class BetaTest {
    int guardedChecksum(String name) {
        int total = name.length();
        if (total > 0) {
            total = total + 8;
        }
        return total;
    }
}
"""

        findings = repeated_helpers.find_repeated_helpers(
            helper_config(),
            [
                repeated_helpers.GroupSourceFile("test", Path("src/test/java/example/AlphaTest.java"), source_a),
                repeated_helpers.GroupSourceFile("test", Path("src/test/java/example/BetaTest.java"), source_b),
            ],
        )

        self.assertEqual([], findings)

    def test_exact_duplicates_do_not_also_report_near_match_advisory(self) -> None:
        source_a = """package example;

final class AlphaTest {
    int checksum(String name) {
        int total = name.length();
        total = total + 7;
        return total;
    }
}
"""
        source_b = """package example;

final class BetaTest {
    int otherChecksum(String label) {
        int result = label.length();
        result = result + 7;
        return result;
    }
}
"""

        findings = repeated_helpers.find_repeated_helpers(
            helper_config(),
            [
                repeated_helpers.GroupSourceFile("test", Path("src/test/java/example/AlphaTest.java"), source_a),
                repeated_helpers.GroupSourceFile("test", Path("src/test/java/example/BetaTest.java"), source_b),
            ],
        )

        self.assertEqual(1, len(findings))
        self.assertEqual("error", findings[0].severity)
        self.assertIn("duplicates helper body", findings[0].message)


def helper_config(
    min_statements: int = 2,
    ignore_annotations: tuple[str, ...] = (),
) -> repeated_helpers.RepeatedHelperConfig:
    return repeated_helpers.RepeatedHelperConfig(
        name="repeated-helper-methods",
        language="java",
        groups=(
            repeated_helpers.SourceGroup(
                name="main",
                paths=("src/main/java",),
                include=("**/*.java",),
                exclude=("**/generated/**",),
            ),
            repeated_helpers.SourceGroup(
                name="test",
                paths=("src/test/java",),
                include=("**/*.java",),
                exclude=("**/generated/**",),
            ),
        ),
        min_statements=min_statements,
        near_match_threshold=0.86,
        advisory_near_matches=True,
        ignore_annotations=ignore_annotations,
        allow_methods=frozenset(),
    )


if __name__ == "__main__":
    unittest.main()
