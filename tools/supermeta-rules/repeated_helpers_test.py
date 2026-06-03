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
