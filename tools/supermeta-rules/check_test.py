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


def write_source(root: Path, relative_path: str, source: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


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
            }
        ]
    }


if __name__ == "__main__":
    unittest.main()
