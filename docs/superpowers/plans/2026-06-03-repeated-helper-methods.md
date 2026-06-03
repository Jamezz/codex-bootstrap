# Repeated Helper Methods Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Java V1 Supermeta rule that flags repeated helper methods, fails exact normalized duplicates, and reports fuzzy near matches as advisory guidance.

**Architecture:** Keep `tools/supermeta-rules/check.py` as the CLI dispatcher, but put parser-backed extraction, normalization, clustering, and fuzzy scoring in a new `tools/supermeta-rules/repeated_helpers.py` module. Add a small finding severity extension so advisory near matches can be printed without failing the process. Enable Java in the Java Gradle starter with a local Supermeta venv for Tree-sitter dependencies; leave other language templates disabled but ready to receive the shared helper module.

**Tech Stack:** Python 3, `unittest`, Tree-sitter Python bindings (`tree-sitter==0.25.2`, `tree-sitter-java==0.23.5`), JSON Supermeta config, Gradle Kotlin DSL, Java Gradle template verification through `scripts/agent-gradle`.

---

## File Structure

- Create `tools/supermeta-rules/requirements.txt`: parser dependency manifest for parser-backed Supermeta rules.
- Create `tools/supermeta-rules/repeated_helpers.py`: Java adapter, helper candidate model, config model, normalization, duplicate clustering, and fuzzy scoring.
- Create `tools/supermeta-rules/repeated_helpers_test.py`: focused parser and fuzzy-comparison behavior tests.
- Modify `tools/supermeta-rules/check.py`: add `Finding.severity`, advisory output, `repeated_helper_methods` dispatch, unknown-key support, invalidator paths, and light config bridging.
- Modify `tools/supermeta-rules/check_test.py`: add CLI severity tests, rule-dispatch integration tests, config validation tests, and missing parser dependency tests.
- Modify `tools/supermeta-rules/README.md`: document `repeated_helper_methods`, parser dependencies, advisory findings, and cross-language adapter path.
- Modify `templates/java-gradle-cli/supermeta-rules.json`: enable `repeated_helper_methods` for `main` and `test` Java groups.
- Modify `templates/java-gradle-cli/build.gradle.kts`: create a project-local Supermeta Python venv, install `tools/supermeta-rules/requirements.txt`, and run `verifySupermetaRules` with that venv Python.
- Modify `templates/java-gradle-cli/README.md` and `templates/java-gradle-cli/AGENTS.md`: document repeated-helper enforcement and parser dependency behavior.
- Modify every `templates/*/bootstrap-template.json`: add new Supermeta support files to the `supermeta-tools` managed set so generated projects can sync them.
- Modify `tools/bootstrap/bootstrap.py`: update generated Java README and AGENTS text with repeated-helper guidance.
- Modify `tools/bootstrap/bootstrap_test.py`: assert generated Java projects contain the rule config, dependency manifest, helper module, Gradle venv hook, generated docs, and managed-file entries.
- Modify catalog docs where reusable Supermeta checks are summarized: `README.md`, `environments/supermeta/README.md`, and `environments/supermeta/AGENTS.md`.

## Task 1: Advisory Finding Severity

**Files:**
- Modify: `tools/supermeta-rules/check_test.py`
- Modify: `tools/supermeta-rules/check.py`

- [ ] **Step 1: Add failing CLI tests for advisory findings**

Insert this test class near the existing CLI/main tests in `tools/supermeta-rules/check_test.py`:

```python
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
```

Add this import at the top of `tools/supermeta-rules/check_test.py`:

```python
import contextlib
```

- [ ] **Step 2: Run the failing tests**

Run:

```bash
python3 -m unittest tools/supermeta-rules/check_test.py -k FindingSeverityTest
```

Expected: FAIL because `Finding` has no `severity` field and `main()` treats every finding as a violation.

- [ ] **Step 3: Implement severity-aware findings**

Update `Finding` in `tools/supermeta-rules/check.py`:

```python
@dataclass(frozen=True)
class Finding:
    rule: str
    path: Path
    message: str
    severity: str = "error"
```

Add this helper near `main()`:

```python
def print_findings(title: str, findings: list[Finding]) -> None:
    print(title)
    for finding in findings:
        print(f"- [{finding.rule}] {finding.path}: {finding.message}")
```

Replace the existing `if findings:` block in `main()` with:

```python
    errors = [finding for finding in findings if finding.severity == "error"]
    advisories = [finding for finding in findings if finding.severity == "advisory"]
    unknown_severities = sorted({finding.severity for finding in findings} - {"error", "advisory"})
    if unknown_severities:
        print(f"supermeta-rules: unknown finding severities: {', '.join(unknown_severities)}", file=sys.stderr)
        return 2

    if errors:
        print_findings("Supermeta rule violations:", errors)
        if advisories:
            print_findings("Supermeta rule advisories:", advisories)
        return 1

    if advisories:
        print_findings("Supermeta rule advisories:", advisories)

    print("Supermeta rules passed.")
    return 0
```

- [ ] **Step 4: Verify severity tests pass**

Run:

```bash
python3 -m unittest tools/supermeta-rules/check_test.py -k FindingSeverityTest
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/supermeta-rules/check.py tools/supermeta-rules/check_test.py
git commit -m "Add advisory Supermeta findings"
```

## Task 2: Dependency Manifest And Config Skeleton

**Files:**
- Create: `tools/supermeta-rules/requirements.txt`
- Create: `tools/supermeta-rules/repeated_helpers.py`
- Create: `tools/supermeta-rules/repeated_helpers_test.py`
- Modify: `tools/supermeta-rules/check.py`
- Modify: `tools/supermeta-rules/check_test.py`

- [ ] **Step 1: Add parser dependency manifest**

Create `tools/supermeta-rules/requirements.txt`:

```text
tree-sitter==0.25.2
tree-sitter-java==0.23.5
```

- [ ] **Step 2: Install parser dependencies for local test execution**

Run:

```bash
python3 -m pip install -r tools/supermeta-rules/requirements.txt
```

Expected: `tree-sitter` and `tree-sitter-java` are installed for the Python used by the test command.

- [ ] **Step 3: Add failing config validation tests**

Add this class to `tools/supermeta-rules/check_test.py`:

```python
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
```

Add this helper near the other config helpers:

```python
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
```

- [ ] **Step 4: Run the failing config tests**

Run:

```bash
python3 -m unittest tools/supermeta-rules/check_test.py -k RepeatedHelperMethodRuleConfigTest
```

Expected: FAIL with `ValueError: unknown rule keys: repeated_helper_methods`.

- [ ] **Step 5: Create the module skeleton**

Create `tools/supermeta-rules/repeated_helpers.py`:

```python
"""Detect repeated helper methods with parser-backed language adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_LANGUAGES = ("java",)


@dataclass(frozen=True)
class SourceGroup:
    name: str
    paths: tuple[str, ...]
    include: tuple[str, ...]
    exclude: tuple[str, ...]


@dataclass(frozen=True)
class RepeatedHelperConfig:
    name: str
    language: str
    groups: tuple[SourceGroup, ...]
    min_statements: int
    near_match_threshold: float
    advisory_near_matches: bool
    ignore_annotations: tuple[str, ...]
    allow_methods: frozenset[str]


@dataclass(frozen=True)
class GroupSourceFile:
    group: str
    path: Path
    source: str


@dataclass(frozen=True)
class HelperCandidate:
    group: str
    path: Path
    line: int
    name: str
    normalized_tokens: tuple[str, ...]
    structure: tuple[str, ...]
    statement_count: int


@dataclass(frozen=True)
class HelperFinding:
    path: Path
    message: str
    severity: str = "error"
```

- [ ] **Step 6: Wire validation and no-op dispatch**

In `tools/supermeta-rules/check.py`, add this import near `import workspace`:

```python
import repeated_helpers
```

Add `Path(__file__).with_name("repeated_helpers.py")` and `Path(__file__).with_name("requirements.txt")` to the `scan_invalidator_paths` list in `main()`.

Add this function near the other rule runners:

```python
def run_repeated_helper_method_rules(
    rules: Any,
    root: Path,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("repeated_helper_methods must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"repeated_helper_methods[{index}]")
        if not rule_is_enabled(rule):
            continue
        config = parse_repeated_helper_config(rule, f"repeated_helper_methods[{index}]")
        group_files: list[repeated_helpers.GroupSourceFile] = []
        for group in config.groups:
            for source_file in iter_rule_files(
                config.name,
                root,
                list(group.paths),
                list(group.include),
                list(group.exclude),
                progress,
                scan_context=scan_context,
                narrow_to_working_set=False,
            ):
                group_files.append(
                    repeated_helpers.GroupSourceFile(
                        group=group.name,
                        path=source_file.relative_to(root),
                        source=source_file.read_text(encoding="utf-8"),
                    )
                )
        for helper_finding in repeated_helpers.find_repeated_helpers(config, group_files):
            add_finding(
                findings,
                Finding(
                    rule=config.name,
                    path=helper_finding.path,
                    message=helper_finding.message,
                    severity=helper_finding.severity,
                ),
                progress,
            )
    return findings
```

Add this parser near the config helpers:

```python
def parse_repeated_helper_config(rule: dict[str, Any], field: str) -> repeated_helpers.RepeatedHelperConfig:
    name = require_string(rule, "name", default=field)
    language = require_string(rule, "language")
    if language not in repeated_helpers.SUPPORTED_LANGUAGES:
        raise ValueError(f"language must be one of: {', '.join(repeated_helpers.SUPPORTED_LANGUAGES)}")
    groups = parse_repeated_helper_groups(rule.get("groups"))
    min_statements = require_positive_int(rule, "min_statements")
    near_match_threshold = require_probability(rule, "near_match_threshold")
    advisory_near_matches = require_bool(rule, "advisory_near_matches", default=True)
    ignore_annotations = tuple(require_string_list(rule, "ignore_annotations", default=[]))
    allow_methods = frozenset(require_string_list(rule, "allow_methods", default=[]))
    return repeated_helpers.RepeatedHelperConfig(
        name=name,
        language=language,
        groups=groups,
        min_statements=min_statements,
        near_match_threshold=near_match_threshold,
        advisory_near_matches=advisory_near_matches,
        ignore_annotations=ignore_annotations,
        allow_methods=allow_methods,
    )


def parse_repeated_helper_groups(value: Any) -> tuple[repeated_helpers.SourceGroup, ...]:
    if not isinstance(value, list):
        raise ValueError("groups must be an array")
    if not value:
        raise ValueError("groups must contain at least one group")
    groups: list[repeated_helpers.SourceGroup] = []
    seen: set[str] = set()
    for index, raw_group in enumerate(value):
        group = require_object(raw_group, f"groups[{index}]")
        name = require_string(group, "name")
        if name in seen:
            raise ValueError(f"groups[{index}] duplicates group name {name}")
        seen.add(name)
        groups.append(
            repeated_helpers.SourceGroup(
                name=name,
                paths=tuple(require_string_list(group, "paths")),
                include=tuple(require_string_list(group, "include", default=["**/*.java"])),
                exclude=tuple(require_string_list(group, "exclude", default=[])),
            )
        )
    return tuple(groups)


def require_probability(rule: dict[str, Any], key: str) -> float:
    value = rule.get(key)
    if not isinstance(value, int | float) or isinstance(value, bool) or value <= 0 or value > 1:
        raise ValueError(f"{key} must be greater than 0 and at most 1")
    return float(value)
```

In `run_rules()`, extend `findings` with `run_repeated_helper_method_rules(config.get("repeated_helper_methods", []), ...)`.

Add `"repeated_helper_methods"` to the unknown-rule allowlist.

In `tools/supermeta-rules/repeated_helpers.py`, add the no-op function:

```python
def find_repeated_helpers(
    config: RepeatedHelperConfig,
    source_files: list[GroupSourceFile],
) -> list[HelperFinding]:
    _ = (config, source_files)
    return []
```

- [ ] **Step 7: Verify config tests pass**

Run:

```bash
python3 -m unittest tools/supermeta-rules/check_test.py -k RepeatedHelperMethodRuleConfigTest
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tools/supermeta-rules/check.py tools/supermeta-rules/check_test.py tools/supermeta-rules/repeated_helpers.py tools/supermeta-rules/requirements.txt
git commit -m "Add repeated helper rule skeleton"
```

## Task 3: Java Parser Extraction And Normalization

**Files:**
- Modify: `tools/supermeta-rules/repeated_helpers_test.py`
- Modify: `tools/supermeta-rules/repeated_helpers.py`

- [ ] **Step 1: Add failing Java extraction tests**

Create `tools/supermeta-rules/repeated_helpers_test.py`:

```python
from __future__ import annotations

import unittest
from pathlib import Path

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
```

- [ ] **Step 2: Run the failing extraction tests**

Run:

```bash
python3 -m unittest tools/supermeta-rules/repeated_helpers_test.py -k JavaHelperExtractionTest
```

Expected: FAIL with `AttributeError: module 'repeated_helpers' has no attribute 'extract_java_helpers'`.

- [ ] **Step 3: Implement Java parser loading and extraction helpers**

Add these imports to `tools/supermeta-rules/repeated_helpers.py`:

```python
from collections import Counter
from difflib import SequenceMatcher
from typing import Iterable
```

Add parser setup and node helpers:

```python
JAVA_METHOD_NODE_TYPES = {"method_declaration"}
JAVA_TYPE_NODE_TYPES = {"class_declaration", "enum_declaration", "interface_declaration", "record_declaration"}
JAVA_DECLARATION_STATEMENTS = {
    "local_variable_declaration",
    "expression_statement",
    "return_statement",
    "if_statement",
    "for_statement",
    "enhanced_for_statement",
    "while_statement",
    "do_statement",
    "switch_expression",
    "switch_statement",
    "try_statement",
    "throw_statement",
    "synchronized_statement",
}
JAVA_LITERAL_NODE_TYPES = {
    "character_literal": "literal:string",
    "decimal_floating_point_literal": "literal:number",
    "decimal_integer_literal": "literal:number",
    "false": "literal:boolean",
    "hex_floating_point_literal": "literal:number",
    "hex_integer_literal": "literal:number",
    "null_literal": "literal:null",
    "string_literal": "literal:string",
    "text_block": "literal:string",
    "true": "literal:boolean",
}


def java_parser():
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_java
    except ImportError as error:
        raise ValueError(
            "repeated_helper_methods requires parser dependencies; install "
            "tools/supermeta-rules/requirements.txt"
        ) from error

    parser = Parser()
    parser.language = Language(tree_sitter_java.language())
    return parser


def node_text(source: bytes, node) -> str:
    return source[node.start_byte : node.end_byte].decode("utf-8")


def iter_named_nodes(node) -> Iterable[object]:
    if node.is_named:
        yield node
    for child in node.children:
        yield from iter_named_nodes(child)


def child_by_type(node, node_type: str):
    for child in node.children:
        if child.type == node_type:
            return child
    return None


def modifier_tokens(method_node) -> set[str]:
    modifiers = child_by_type(method_node, "modifiers")
    if modifiers is None:
        return set()
    return {child.type for child in modifiers.children if child.type != "marker_annotation"}


def annotation_names(source: bytes, node) -> tuple[str, ...]:
    modifiers = child_by_type(node, "modifiers")
    if modifiers is None:
        return ()
    names: list[str] = []
    for annotation in modifiers.children:
        if annotation.type not in {"annotation", "marker_annotation"}:
            continue
        name = annotation.child_by_field_name("name")
        if name is not None:
            names.append(node_text(source, name))
    return tuple(names)
```

- [ ] **Step 4: Implement helper eligibility and normalization**

Add this code to `tools/supermeta-rules/repeated_helpers.py`:

```python
def extract_java_helpers(config: RepeatedHelperConfig, source_file: GroupSourceFile) -> list[HelperCandidate]:
    parser = java_parser()
    source_bytes = source_file.source.encode("utf-8")
    tree = parser.parse(source_bytes)
    if tree.root_node.has_error:
        raise ValueError(f"{source_file.path}: Java parser reported syntax errors")

    candidates: list[HelperCandidate] = []
    ignored_type_ranges = java_ignored_type_ranges(source_bytes, tree.root_node, config.ignore_annotations)
    for method in iter_named_nodes(tree.root_node):
        if method.type not in JAVA_METHOD_NODE_TYPES:
            continue
        name_node = method.child_by_field_name("name")
        body = method.child_by_field_name("body")
        if name_node is None or body is None:
            continue
        name = node_text(source_bytes, name_node)
        if name in config.allow_methods:
            continue
        if position_is_inside_any_range(method.start_byte, ignored_type_ranges):
            continue
        annotations = annotation_names(source_bytes, method)
        if annotations_match_any(annotations, ("Override", *config.ignore_annotations)):
            continue
        modifiers = modifier_tokens(method)
        if not is_java_helper_eligible(source_file.group, modifiers):
            continue
        statement_count = count_java_statements(body)
        if statement_count < config.min_statements:
            continue
        local_names = java_local_names(source_bytes, method)
        tokens = tuple(normalize_java_tokens(source_bytes, body, local_names))
        structure = tuple(structural_tokens(body))
        candidates.append(
            HelperCandidate(
                group=source_file.group,
                path=source_file.path,
                line=method.start_point.row + 1,
                name=name,
                normalized_tokens=tokens,
                structure=structure,
                statement_count=statement_count,
            )
        )
    return candidates


def java_ignored_type_ranges(source: bytes, root_node, ignore_annotations: tuple[str, ...]) -> tuple[tuple[int, int], ...]:
    ranges: list[tuple[int, int]] = []
    if not ignore_annotations:
        return ()
    for node in iter_named_nodes(root_node):
        if node.type not in JAVA_TYPE_NODE_TYPES:
            continue
        if annotations_match_any(annotation_names(source, node), ignore_annotations):
            ranges.append((node.start_byte, node.end_byte))
    return tuple(ranges)


def position_is_inside_any_range(position: int, ranges: tuple[tuple[int, int], ...]) -> bool:
    return any(start <= position <= end for start, end in ranges)


def is_java_helper_eligible(group: str, modifiers: set[str]) -> bool:
    if "abstract" in modifiers or "public" in modifiers or "protected" in modifiers:
        return False
    if group == "main":
        return "private" in modifiers or "static" in modifiers
    if group == "test":
        return True
    return "private" in modifiers or "static" in modifiers


def count_java_statements(body) -> int:
    return sum(1 for node in body.children if node.is_named and node.type in JAVA_DECLARATION_STATEMENTS)


def java_local_names(source: bytes, method) -> dict[str, str]:
    names: list[str] = []
    parameters = method.child_by_field_name("parameters")
    if parameters is not None:
        for parameter in iter_named_nodes(parameters):
            if parameter.type not in {"formal_parameter", "spread_parameter"}:
                continue
            name = parameter.child_by_field_name("name")
            if name is not None:
                names.append(node_text(source, name))
    for node in iter_named_nodes(method):
        if node.type != "variable_declarator":
            continue
        name = node.child_by_field_name("name")
        if name is not None:
            names.append(node_text(source, name))
    return {name: f"local:{index}" for index, name in enumerate(dict.fromkeys(names))}


def normalize_java_tokens(source: bytes, node, local_names: dict[str, str]) -> list[str]:
    tokens: list[str] = []
    for child in node.children:
        if child.type in {"{", "}", ";", ","}:
            continue
        if child.type in JAVA_LITERAL_NODE_TYPES:
            tokens.append(JAVA_LITERAL_NODE_TYPES[child.type])
            continue
        if child.type == "identifier":
            text = node_text(source, child)
            tokens.append(local_names.get(text, f"id:{text}"))
            continue
        if child.is_named:
            tokens.append(f"node:{child.type}")
            tokens.extend(normalize_java_tokens(source, child, local_names))
        elif child.type.strip():
            tokens.append(f"token:{child.type}")
    return tokens


def structural_tokens(node) -> list[str]:
    tokens: list[str] = []
    for child in node.children:
        if child.is_named and child.type in JAVA_DECLARATION_STATEMENTS:
            tokens.append(child.type)
        if child.is_named:
            tokens.extend(structural_tokens(child))
    return tokens


def annotations_match_any(actual_annotations: tuple[str, ...], configured_annotations: tuple[str, ...]) -> bool:
    return any(
        annotation_matches(actual, configured)
        for actual in actual_annotations
        for configured in configured_annotations
    )


def annotation_matches(actual: str, configured: str) -> bool:
    if "." in configured:
        return actual == configured
    return actual == configured or actual.endswith(f".{configured}")
```

- [ ] **Step 5: Run extraction tests**

Run:

```bash
python3 -m unittest tools/supermeta-rules/repeated_helpers_test.py -k JavaHelperExtractionTest
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tools/supermeta-rules/repeated_helpers.py tools/supermeta-rules/repeated_helpers_test.py
git commit -m "Extract Java helper method candidates"
```

## Task 4: Exact Duplicate Findings

**Files:**
- Modify: `tools/supermeta-rules/repeated_helpers_test.py`
- Modify: `tools/supermeta-rules/repeated_helpers.py`
- Modify: `tools/supermeta-rules/check_test.py`

- [ ] **Step 1: Add failing exact duplicate tests**

Add this class to `tools/supermeta-rules/repeated_helpers_test.py`:

```python
class RepeatedHelperExactDuplicateTest(unittest.TestCase):
    def test_exact_normalized_duplicate_fails(self) -> None:
        config = helper_config()
        sources = [
            repeated_helpers.GroupSourceFile(
                "main",
                Path("src/main/java/example/Foo.java"),
                """package example;
final class Foo {
    private int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
""",
            ),
            repeated_helpers.GroupSourceFile(
                "main",
                Path("src/main/java/example/Bar.java"),
                """package example;
final class Bar {
    private int checksum(String label) {
        int result = label.length();
        return result + 7;
    }
}
""",
            ),
        ]

        findings = repeated_helpers.find_repeated_helpers(config, sources)

        self.assertEqual(1, len(findings))
        self.assertEqual("error", findings[0].severity)
        self.assertEqual(Path("src/main/java/example/Foo.java"), findings[0].path)
        self.assertIn("duplicates helper body", findings[0].message)
        self.assertIn("src/main/java/example/Bar.java", findings[0].message)
        self.assertIn("factor this helper into common code", findings[0].message)

    def test_does_not_compare_main_and_test_groups(self) -> None:
        config = helper_config()
        body = """private int checksum(String name) {
        int total = name.length();
        return total + 7;
    }"""
        sources = [
            repeated_helpers.GroupSourceFile(
                "main",
                Path("src/main/java/example/Foo.java"),
                f"package example; final class Foo {{ {body} }}",
            ),
            repeated_helpers.GroupSourceFile(
                "test",
                Path("src/test/java/example/FooTest.java"),
                f"package example; final class FooTest {{ {body} }}",
            ),
        ]

        findings = repeated_helpers.find_repeated_helpers(config, sources)

        self.assertEqual([], findings)
```

Add this integration test to `RepeatedHelperMethodRuleConfigTest` in `tools/supermeta-rules/check_test.py`:

```python
    def test_rule_dispatch_reports_exact_duplicate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/example/Foo.java",
                """package example;
final class Foo {
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
                "src/main/java/example/Bar.java",
                """package example;
final class Bar {
    private int checksum(String label) {
        int result = label.length();
        result = result + 7;
        return result;
    }
}
""",
            )

            findings = check.run_rules(repeated_helper_config(), root, force_full=True)

            self.assertEqual(1, len(findings))
            self.assertEqual("repeated-helper-methods", findings[0].rule)
            self.assertEqual("error", findings[0].severity)
            self.assertIn("duplicates helper body", findings[0].message)

    def test_generated_excludes_are_honored(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/main/java/generated/Foo.java",
                """package generated;
final class Foo {
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
                "src/main/java/generated/Bar.java",
                """package generated;
final class Bar {
    private int checksum(String label) {
        int result = label.length();
        result = result + 7;
        return result;
    }
}
""",
            )

            findings = check.run_rules(repeated_helper_config(), root, force_full=True)

            self.assertEqual([], findings)
```

- [ ] **Step 2: Run the failing exact duplicate tests**

Run:

```bash
python3 -m unittest tools/supermeta-rules/repeated_helpers_test.py -k RepeatedHelperExactDuplicateTest
python3 -m unittest tools/supermeta-rules/check_test.py -k test_rule_dispatch_reports_exact_duplicate
```

Expected: FAIL because `find_repeated_helpers()` still returns no findings.

- [ ] **Step 3: Implement exact duplicate clustering**

Replace `find_repeated_helpers()` in `tools/supermeta-rules/repeated_helpers.py`:

```python
def find_repeated_helpers(
    config: RepeatedHelperConfig,
    source_files: list[GroupSourceFile],
) -> list[HelperFinding]:
    candidates = extract_helpers(config, source_files)
    findings: list[HelperFinding] = []
    findings.extend(exact_duplicate_findings(candidates))
    findings.extend(near_duplicate_findings(config, candidates, exact_duplicate_keys(candidates)))
    return findings


def extract_helpers(config: RepeatedHelperConfig, source_files: list[GroupSourceFile]) -> list[HelperCandidate]:
    if config.language != "java":
        raise ValueError(f"language must be one of: {', '.join(SUPPORTED_LANGUAGES)}")
    candidates: list[HelperCandidate] = []
    for source_file in source_files:
        candidates.extend(extract_java_helpers(config, source_file))
    return candidates


def exact_duplicate_keys(candidates: list[HelperCandidate]) -> set[tuple[str, tuple[str, ...]]]:
    counts = Counter((candidate.group, candidate.normalized_tokens) for candidate in candidates)
    return {key for key, count in counts.items() if count > 1}


def exact_duplicate_findings(candidates: list[HelperCandidate]) -> list[HelperFinding]:
    grouped: dict[tuple[str, tuple[str, ...]], list[HelperCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.group, candidate.normalized_tokens), []).append(candidate)

    findings: list[HelperFinding] = []
    for duplicates in grouped.values():
        if len(duplicates) < 2:
            continue
        ordered = sorted(duplicates, key=lambda item: (item.path.as_posix(), item.line, item.name))
        first = ordered[0]
        others = ", ".join(f"{item.path}:{item.line} {item.name}()" for item in ordered[1:])
        findings.append(
            HelperFinding(
                path=first.path,
                message=(
                    f"{first.name}() duplicates helper body also found at {others}; "
                    "factor this helper into common code in the nearest appropriate package, support class, "
                    "test fixture helper, or shared module"
                ),
            )
        )
    return findings
```

Add the temporary near-duplicate stub below it. Task 5 replaces it:

```python
def near_duplicate_findings(
    config: RepeatedHelperConfig,
    candidates: list[HelperCandidate],
    exact_keys: set[tuple[str, tuple[str, ...]]],
) -> list[HelperFinding]:
    _ = (config, candidates, exact_keys)
    return []
```

- [ ] **Step 4: Run exact duplicate tests**

Run:

```bash
python3 -m unittest tools/supermeta-rules/repeated_helpers_test.py -k RepeatedHelperExactDuplicateTest
python3 -m unittest tools/supermeta-rules/check_test.py -k test_rule_dispatch_reports_exact_duplicate
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/supermeta-rules/repeated_helpers.py tools/supermeta-rules/repeated_helpers_test.py tools/supermeta-rules/check_test.py
git commit -m "Detect exact repeated Java helpers"
```

## Task 5: Fuzzy Near-Match Advisories

**Files:**
- Modify: `tools/supermeta-rules/repeated_helpers_test.py`
- Modify: `tools/supermeta-rules/repeated_helpers.py`
- Modify: `tools/supermeta-rules/check_test.py`

- [ ] **Step 1: Add failing near-match tests**

Add this class to `tools/supermeta-rules/repeated_helpers_test.py`:

```python
class RepeatedHelperNearMatchTest(unittest.TestCase):
    def test_near_duplicate_is_advisory_by_default(self) -> None:
        config = helper_config()
        sources = [
            repeated_helpers.GroupSourceFile(
                "test",
                Path("src/test/java/example/FooTest.java"),
                """package example;
final class FooTest {
    int checksum(String name) {
        int total = name.length();
        total = total + 7;
        return total;
    }
}
""",
            ),
            repeated_helpers.GroupSourceFile(
                "test",
                Path("src/test/java/example/BarTest.java"),
                """package example;
final class BarTest {
    int checksum(String label) {
        int total = label.length();
        total = total + 8;
        return total;
    }
}
""",
            ),
        ]

        findings = repeated_helpers.find_repeated_helpers(config, sources)

        self.assertEqual(1, len(findings))
        self.assertEqual("advisory", findings[0].severity)
        self.assertIn("is similar to", findings[0].message)
        self.assertIn("review these helpers for shared", findings[0].message)

    def test_structurally_different_helpers_are_not_near_matches(self) -> None:
        config = helper_config()
        sources = [
            repeated_helpers.GroupSourceFile(
                "main",
                Path("src/main/java/example/Foo.java"),
                """package example;
final class Foo {
    private int checksum(String name) {
        int total = name.length();
        return total + 7;
    }
}
""",
            ),
            repeated_helpers.GroupSourceFile(
                "main",
                Path("src/main/java/example/Bar.java"),
                """package example;
final class Bar {
    private int checksum(String label) {
        if (label.isBlank()) {
            return 0;
        }
        return label.length();
    }
}
""",
            ),
        ]

        findings = repeated_helpers.find_repeated_helpers(config, sources)

        self.assertEqual([], findings)
```

Add this CLI integration test to `RepeatedHelperMethodRuleConfigTest`:

```python
    def test_near_duplicate_does_not_fail_main(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_source(
                root,
                "src/test/java/example/FooTest.java",
                """package example;
final class FooTest {
    int checksum(String name) {
        int total = name.length();
        total = total + 7;
        return total;
    }
}
""",
            )
            write_source(
                root,
                "src/test/java/example/BarTest.java",
                """package example;
final class BarTest {
    int checksum(String label) {
        int total = label.length();
        total = total + 8;
        return total;
    }
}
""",
            )
            config_path = root / "supermeta-rules.json"
            config_path.write_text(json.dumps(repeated_helper_config()), encoding="utf-8")
            output = io.StringIO()

            with contextlib.redirect_stdout(output):
                exit_code = check.main(["--config", str(config_path), "--root", str(root), "--full"])

            self.assertEqual(0, exit_code)
            self.assertIn("Supermeta rule advisories:", output.getvalue())
            self.assertIn("Supermeta rules passed.", output.getvalue())
```

- [ ] **Step 2: Run the failing near-match tests**

Run:

```bash
python3 -m unittest tools/supermeta-rules/repeated_helpers_test.py -k RepeatedHelperNearMatchTest
python3 -m unittest tools/supermeta-rules/check_test.py -k test_near_duplicate_does_not_fail_main
```

Expected: FAIL because near matching is not implemented.

- [ ] **Step 3: Implement conservative fuzzy scoring**

Replace the `near_duplicate_findings()` stub in `tools/supermeta-rules/repeated_helpers.py`:

```python
def near_duplicate_findings(
    config: RepeatedHelperConfig,
    candidates: list[HelperCandidate],
    exact_keys: set[tuple[str, tuple[str, ...]]],
) -> list[HelperFinding]:
    findings: list[HelperFinding] = []
    ordered = sorted(candidates, key=lambda item: (item.group, item.path.as_posix(), item.line, item.name))
    for left_index, left in enumerate(ordered):
        if (left.group, left.normalized_tokens) in exact_keys:
            continue
        for right in ordered[left_index + 1 :]:
            if left.group != right.group:
                continue
            if (right.group, right.normalized_tokens) in exact_keys:
                continue
            if left.structure != right.structure:
                continue
            similarity = token_similarity(left.normalized_tokens, right.normalized_tokens)
            if similarity < config.near_match_threshold:
                continue
            severity = "advisory" if config.advisory_near_matches else "error"
            findings.append(
                HelperFinding(
                    path=left.path,
                    message=(
                        f"{left.name}() at {left.path}:{left.line} is similar to "
                        f"{right.name}() at {right.path}:{right.line} "
                        f"({similarity:.2f} similarity); review these helpers for shared extraction"
                    ),
                    severity=severity,
                )
            )
    return findings


def token_similarity(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    return SequenceMatcher(a=left, b=right, autojunk=False).ratio()
```

- [ ] **Step 4: Run near-match tests**

Run:

```bash
python3 -m unittest tools/supermeta-rules/repeated_helpers_test.py -k RepeatedHelperNearMatchTest
python3 -m unittest tools/supermeta-rules/check_test.py -k test_near_duplicate_does_not_fail_main
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/supermeta-rules/repeated_helpers.py tools/supermeta-rules/repeated_helpers_test.py tools/supermeta-rules/check_test.py
git commit -m "Report near repeated Java helpers"
```

## Task 6: Missing Parser Dependency And Syntax Errors

**Files:**
- Modify: `tools/supermeta-rules/repeated_helpers_test.py`
- Modify: `tools/supermeta-rules/repeated_helpers.py`
- Modify: `tools/supermeta-rules/check_test.py`

- [ ] **Step 1: Add failing dependency and syntax error tests**

Add these tests to `JavaHelperExtractionTest` in `tools/supermeta-rules/repeated_helpers_test.py`:

```python
    def test_syntax_error_names_file(self) -> None:
        with self.assertRaisesRegex(ValueError, "src/main/java/example/Broken.java: Java parser reported syntax errors"):
            repeated_helpers.extract_java_helpers(
                helper_config(),
                repeated_helpers.GroupSourceFile(
                    "main",
                    Path("src/main/java/example/Broken.java"),
                    "package example; final class Broken { private int value( { return 1; } }",
                ),
            )
```

Add this test to `RepeatedHelperMethodRuleConfigTest` in `tools/supermeta-rules/check_test.py`:

```python
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
                    "repeated_helper_methods requires parser dependencies; install tools/supermeta-rules/requirements.txt"
                ),
            ):
                with self.assertRaisesRegex(ValueError, "requires parser dependencies"):
                    check.run_rules(repeated_helper_config(), root, force_full=True)
```

Add this line immediately after `check = load_check_module()` in `tools/supermeta-rules/check_test.py`:

```python
repeated_helpers = check.repeated_helpers
```

- [ ] **Step 2: Run dependency and syntax tests**

Run:

```bash
python3 -m unittest tools/supermeta-rules/repeated_helpers_test.py -k test_syntax_error_names_file
python3 -m unittest tools/supermeta-rules/check_test.py -k test_missing_parser_dependency_reports_install_guidance
```

Expected: PASS if Task 3 already implemented syntax and parser dependency errors. If either test fails, adjust only the error message path or exception propagation.

- [ ] **Step 3: Commit**

```bash
git add tools/supermeta-rules/repeated_helpers.py tools/supermeta-rules/repeated_helpers_test.py tools/supermeta-rules/check_test.py
git commit -m "Harden repeated helper parser errors"
```

## Task 7: Java Template Rule And Gradle Venv

**Files:**
- Modify: `templates/java-gradle-cli/supermeta-rules.json`
- Modify: `templates/java-gradle-cli/build.gradle.kts`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add failing bootstrap assertions for Java template wiring**

In `tools/bootstrap/bootstrap_test.py`, extend the Java bootstrap smoke test near the existing `rules_config` assertions:

```python
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "requirements.txt").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "repeated_helpers.py").is_file())
            self.assertIn('"repeated_helper_methods"', rules_config)
            self.assertIn('"name": "repeated-helper-methods"', rules_config)
            self.assertIn('"near_match_threshold": 0.86', rules_config)
            self.assertIn('"advisory_near_matches": true', rules_config)
            self.assertIn("installSupermetaRuleDependencies", read_text(checkout / "build.gradle.kts"))
            self.assertIn("tools/supermeta-rules/requirements.txt", read_text(checkout / "build.gradle.kts"))
```

- [ ] **Step 2: Run the failing bootstrap test**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py -k java
```

Expected: FAIL because the Java template does not yet include the repeated helper config or Gradle venv hook.

- [ ] **Step 3: Enable the Java rule in template config**

In `templates/java-gradle-cli/supermeta-rules.json`, insert this top-level rule before `project_callouts`:

```json
  "repeated_helper_methods": [
    {
      "name": "repeated-helper-methods",
      "language": "java",
      "groups": [
        {
          "name": "main",
          "paths": ["src/main/java"],
          "include": ["**/*.java"],
          "exclude": ["**/generated/**"]
        },
        {
          "name": "test",
          "paths": ["src/test/java"],
          "include": ["**/*.java"],
          "exclude": ["**/generated/**"]
        }
      ],
      "min_statements": 3,
      "near_match_threshold": 0.86,
      "advisory_near_matches": true,
      "ignore_annotations": ["Generated", "ManualDuplication"],
      "allow_methods": []
    }
  ],
```

- [ ] **Step 4: Add Gradle venv dependency installation**

In `templates/java-gradle-cli/build.gradle.kts`, add these values near `supermetaRulesScript`:

```kotlin
val supermetaRulesRequirements = layout.projectDirectory.file("tools/supermeta-rules/requirements.txt")
val supermetaRulesVenv = layout.projectDirectory.dir(".gradle/supermeta-rules-venv")
val supermetaRulesPython = providers.provider {
    val executable = if (System.getProperty("os.name").lowercase().contains("windows")) {
        "Scripts/python.exe"
    } else {
        "bin/python"
    }
    supermetaRulesVenv.file(executable).asFile.absolutePath
}
```

Add this task before `verifySupermetaRules`:

```kotlin
tasks.register<Exec>("installSupermetaRuleDependencies") {
    description = "Installs parser dependencies for shared Supermeta rules."
    group = "verification"

    inputs.file(supermetaRulesRequirements)
    outputs.dir(supermetaRulesVenv)

    commandLine("python3", "-m", "venv", supermetaRulesVenv.asFile.absolutePath)

    doLast {
        exec {
            commandLine(
                supermetaRulesPython.get(),
                "-m",
                "pip",
                "install",
                "--quiet",
                "-r",
                supermetaRulesRequirements.asFile.absolutePath,
            )
        }
    }
}
```

Update `verifySupermetaRules`:

```kotlin
tasks.register<Exec>("verifySupermetaRules") {
    description = "Runs shared Supermeta rules for this template."
    group = "verification"

    dependsOn("installSupermetaRuleDependencies")

    inputs.file("supermeta-rules.json")
    inputs.file(supermetaRulesScript)
    inputs.file(supermetaRulesRequirements)
    inputs.files(fileTree("tools/supermeta-rules"))
    inputs.files(fileTree("src/main"))
    inputs.files(fileTree("src/test"))

    commandLine(
        supermetaRulesPython.get(),
        supermetaRulesScript.asFile.absolutePath,
        "--config",
        layout.projectDirectory.file("supermeta-rules.json").asFile.absolutePath,
        "--root",
        layout.projectDirectory.asFile.absolutePath,
        "--skip-callouts",
    )
}
```

- [ ] **Step 5: Run Java template Supermeta rule directly**

Run:

```bash
python3 tools/supermeta-rules/check.py --config templates/java-gradle-cli/supermeta-rules.json --root templates/java-gradle-cli --skip-callouts --full
```

Expected: PASS with `Supermeta rules passed.` and no repeated-helper exact duplicates.

- [ ] **Step 6: Run bootstrap Java assertions**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py -k java
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add templates/java-gradle-cli/supermeta-rules.json templates/java-gradle-cli/build.gradle.kts tools/bootstrap/bootstrap_test.py
git commit -m "Enable repeated helper rule for Java template"
```

## Task 8: Managed Support Files Across Templates

**Files:**
- Modify: `templates/java-gradle-cli/bootstrap-template.json`
- Modify: `templates/python-uv-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-mcp-server/bootstrap-template.json`
- Modify: `templates/rust-cargo-cli/bootstrap-template.json`
- Modify: `templates/csharp-dotnet-cli/bootstrap-template.json`
- Modify: `templates/existing-repo-control/bootstrap-template.json`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add failing manifest assertions**

In `assert_generated_manifest_has_common_support()` or the nearest common manifest helper in `tools/bootstrap/bootstrap_test.py`, add:

```python
    test_case.assertIn("tools/supermeta-rules/repeated_helpers.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-rules/repeated_helpers_test.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-rules/requirements.txt", manifest.sync_contract.managed_files)
```

- [ ] **Step 2: Run the failing manifest tests**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py -k manifest
```

Expected: FAIL because the new files are not listed in template managed sets.

- [ ] **Step 3: Add managed files to every template manifest**

In each `templates/*/bootstrap-template.json`, add these entries to the `supermeta-tools` managed set immediately after `tools/supermeta-rules/check.py`:

```json
          {
            "path": "tools/supermeta-rules/repeated_helpers.py",
            "mode": "whole-file"
          },
          {
            "path": "tools/supermeta-rules/repeated_helpers_test.py",
            "mode": "whole-file"
          },
          {
            "path": "tools/supermeta-rules/requirements.txt",
            "mode": "whole-file"
          },
```

- [ ] **Step 4: Verify manifest tests**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py -k manifest
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add templates/*/bootstrap-template.json tools/bootstrap/bootstrap_test.py
git commit -m "Propagate repeated helper support files"
```

## Task 9: Docs And Generated Java Guidance

**Files:**
- Modify: `tools/supermeta-rules/README.md`
- Modify: `templates/java-gradle-cli/README.md`
- Modify: `templates/java-gradle-cli/AGENTS.md`
- Modify: `tools/bootstrap/bootstrap.py`
- Modify: `tools/bootstrap/bootstrap_test.py`
- Modify: `README.md`
- Modify: `environments/supermeta/README.md`
- Modify: `environments/supermeta/AGENTS.md`

- [ ] **Step 1: Add failing generated-doc assertions**

In `tools/bootstrap/bootstrap_test.py`, extend the Java generated README and AGENTS assertions:

```python
            self.assertIn("Supermeta flags repeated Java helper methods", readme)
            self.assertIn("exact repeated helpers fail", readme)
            self.assertIn("near matches are advisory", readme)
            self.assertIn("Supermeta flags repeated Java helper methods", agents)
            self.assertIn("factor repeated helpers into common code", agents)
```

- [ ] **Step 2: Run failing generated-doc test**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py -k java
```

Expected: FAIL because the generated docs do not yet mention repeated helper methods.

- [ ] **Step 3: Document the rule in `tools/supermeta-rules/README.md`**

Add this section after `java_lombok_boilerplate`:

```markdown
### `repeated_helper_methods`

Checks for helper methods that have been copied instead of factored into common code. Java is the first supported language. The rule uses Tree-sitter, so enabled Java projects must install `tools/supermeta-rules/requirements.txt`.

Exact normalized duplicates are blocking findings. Near matches are advisory by default and do not fail the run.

```json
{
  "repeated_helper_methods": [
    {
      "name": "repeated-helper-methods",
      "language": "java",
      "groups": [
        {
          "name": "main",
          "paths": ["src/main/java"],
          "include": ["**/*.java"],
          "exclude": ["**/generated/**"]
        },
        {
          "name": "test",
          "paths": ["src/test/java"],
          "include": ["**/*.java"],
          "exclude": ["**/generated/**"]
        }
      ],
      "min_statements": 3,
      "near_match_threshold": 0.86,
      "advisory_near_matches": true,
      "ignore_annotations": ["Generated", "ManualDuplication"],
      "allow_methods": []
    }
  ]
}
```

Groups compare independently, so production helpers do not compare with test helpers. Future Python, TypeScript, Rust, and C# adapters should reuse the same config shape and shared fuzzy-comparison pipeline.
```

- [ ] **Step 4: Update Java template README and AGENTS**

In `templates/java-gradle-cli/README.md`, add to the customization or checks section:

```markdown
- Supermeta flags repeated Java helper methods. Exact repeated helpers fail and should be factored into common code; near matches are advisory and should be reviewed before extracting shared support.
```

In `templates/java-gradle-cli/AGENTS.md`, add to the rules section:

```markdown
- Supermeta flags repeated Java helper methods; factor repeated helpers into common code instead of copying local utilities.
```

- [ ] **Step 5: Update generated Java docs in `tools/bootstrap/bootstrap.py`**

In the generated Java README customization bullet list, add:

```python
"- Supermeta flags repeated Java helper methods. Exact repeated helpers fail and should be factored into common code; near matches are advisory and should be reviewed before extracting shared support."
```

In the generated Java AGENTS rules list, add:

```python
"- Supermeta flags repeated Java helper methods; factor repeated helpers into common code instead of copying local utilities."
```

- [ ] **Step 6: Update catalog docs**

In `README.md`, update the `tools/supermeta-rules/` summary to mention repeated helper detection:

```markdown
- `tools/supermeta-rules/`: a reusable rule checker for generated projects, including source-size rules, Java policy checks, Rust safety checks, and Java repeated-helper detection.
```

In `environments/supermeta/README.md`, add:

```markdown
`repeated_helper_methods` is the Java V1 parser-backed rule for copied helper methods. Exact normalized duplicates fail; fuzzy near matches are advisory guidance for common-code extraction.
```

In `environments/supermeta/AGENTS.md`, add:

```markdown
- enforce Java repeated-helper detection through `tools/supermeta-rules/`; exact duplicates should be factored into common code and near matches should be reviewed before extraction;
```

- [ ] **Step 7: Run docs/bootstrap tests**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py -k java
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add tools/supermeta-rules/README.md templates/java-gradle-cli/README.md templates/java-gradle-cli/AGENTS.md tools/bootstrap/bootstrap.py tools/bootstrap/bootstrap_test.py README.md environments/supermeta/README.md environments/supermeta/AGENTS.md
git commit -m "Document repeated helper method rule"
```

## Task 10: Full Rule Regression

**Files:**
- Test: `tools/supermeta-rules/check_test.py`
- Test: `tools/supermeta-rules/repeated_helpers_test.py`

- [ ] **Step 1: Run all Supermeta rule tests**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'
```

Expected: PASS. If a test fails because parser dependencies are missing, rerun:

```bash
python3 -m pip install -r tools/supermeta-rules/requirements.txt
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'
```

Expected after install: PASS.

- [ ] **Step 2: Run direct Java template Supermeta check**

Run:

```bash
python3 tools/supermeta-rules/check.py --config templates/java-gradle-cli/supermeta-rules.json --root templates/java-gradle-cli --skip-callouts --full
```

Expected: PASS with `Supermeta rules passed.`

- [ ] **Step 3: Commit any fixes from the regression**

If Step 1 or Step 2 required source changes, commit them:

```bash
git add tools/supermeta-rules templates/java-gradle-cli/supermeta-rules.json
git commit -m "Fix repeated helper rule regressions"
```

If no source changes were needed, do not create an empty commit.

## Task 11: Bootstrap And Java Template Verification

**Files:**
- Test: `tools/bootstrap/bootstrap_test.py`
- Test: `templates/java-gradle-cli`

- [ ] **Step 1: Run bootstrap tests**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 2: Run Java template check**

Run:

```bash
./scripts/agent-gradle templates/java-gradle-cli check
```

Expected: PASS. The first run may create `.gradle/supermeta-rules-venv` and install Tree-sitter dependencies.

- [ ] **Step 3: Run Java template app**

Run:

```bash
./scripts/agent-gradle templates/java-gradle-cli run
```

Expected: PASS and the app prints the starter greeting.

- [ ] **Step 4: Run whitespace check**

Run:

```bash
git diff --check
```

Expected: no output and exit code 0.

- [ ] **Step 5: Commit verification fixes**

If verification required source changes, commit them:

```bash
git add .
git commit -m "Verify repeated helper method rollout"
```

If no source changes were needed, do not create an empty commit.

## Task 12: Final Status

**Files:**
- Inspect only: repository state

- [ ] **Step 1: Confirm clean status**

Run:

```bash
git status --short --branch
```

Expected: no unstaged or staged changes. The branch may be ahead of `origin/main` if commits have not been pushed.

- [ ] **Step 2: Summarize verification evidence**

Record these exact commands and results in the final handoff:

```text
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'  # PASS
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'        # PASS
./scripts/agent-gradle templates/java-gradle-cli check                # PASS
./scripts/agent-gradle templates/java-gradle-cli run                  # PASS
git diff --check                                                      # PASS
```
