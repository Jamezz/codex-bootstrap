# Java Heuristic Scans Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add hard Java Supermeta gates that reject explicit imports and handwritten getter, setter, and builder boilerplate unless a project deliberately configures an exception.

**Architecture:** Extend the shared `tools/supermeta-rules/check.py` scanner with two Java rule families, then enable them in the Java Gradle template contract. Keep the implementation source-level and conservative: wildcard import enforcement is exact, Lombok boilerplate detection uses comment/string stripping plus brace-aware method and class scans.

**Tech Stack:** Python 3 standard library, `unittest`, JSON Supermeta config, Gradle Checkstyle integration through `scripts/agent-gradle`.

---

## File Structure

- Modify `tools/supermeta-rules/check.py`: add `java_import_style` and `java_lombok_boilerplate` rule dispatch, config validation, Java source stripping, import scanning, and Lombok boilerplate heuristics.
- Modify `tools/supermeta-rules/check_test.py`: add focused unit tests for import style, Lombok boilerplate detection, allowlists, exclusions, and ignore annotations.
- Modify `templates/java-gradle-cli/supermeta-rules.json`: enable both Java hard gates for main and test Java source.
- Modify `templates/java-gradle-cli/src/main/java/com/example/LoggingConfig.java`: replace explicit imports with wildcard imports or fully qualified references where wildcard imports would create type ambiguity.
- Modify `templates/java-gradle-cli/README.md` and `templates/java-gradle-cli/AGENTS.md`: document that wildcard imports and Lombok boilerplate rules are enforced, not preferences.
- Modify `tools/bootstrap/bootstrap.py`: update generated Java README and AGENTS text so bootstrapped projects inherit the enforced convention.
- Modify `tools/bootstrap/bootstrap_test.py`: assert generated Java projects include the new rule config and generated docs mention the enforced policy.
- Modify `README.md`, `environments/supermeta/README.md`, and `environments/supermeta/AGENTS.md`: update catalog-level guidance from preference language to reusable Supermeta rule enforcement.

## Task 1: Import Style Tests

**Files:**
- Modify: `tools/supermeta-rules/check_test.py`

- [ ] **Step 1: Add failing tests for `java_import_style`**

Insert this test class after `JavaPackageFileCountRuleTest` and before the helper functions:

```python
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
```

Add these helpers near the existing helper functions:

```python
def write_source(root: Path, relative_path: str, source: str) -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


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
```

- [ ] **Step 2: Run the import tests and verify they fail for the missing rule**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'
```

Expected: FAIL with `ValueError: unknown rule keys: java_import_style`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tools/supermeta-rules/check_test.py
git commit -m "test: cover Java wildcard import rule"
```

## Task 2: Import Style Rule

**Files:**
- Modify: `tools/supermeta-rules/check.py`
- Test: `tools/supermeta-rules/check_test.py`

- [ ] **Step 1: Add the `re` import and Java helper records**

Modify the import block:

```python
import os
import re
import shlex
```

Add these records and constants after `Finding`:

```python
@dataclass(frozen=True)
class JavaClassBlock:
    name: str
    start: int
    end: int
    annotations: tuple[str, ...]


@dataclass(frozen=True)
class JavaMethodBlock:
    name: str
    return_type: str
    params: str
    body: str
    start: int
    end: int
    annotations: tuple[str, ...]


JAVA_IMPORT_RE = re.compile(r"^\s*import\s+(?P<static>static\s+)?(?P<target>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\.\*)?)\s*;\s*$")
JAVA_CLASS_RE = re.compile(r"\b(?:class|record|interface|enum)\s+(?P<name>[A-Za-z_$][\w$]*)[^{]*\{")
JAVA_METHOD_RE = re.compile(
    r"(?P<return>[A-Za-z_$][\w$<>\[\].?,\s]*?)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"\((?P<params>[^()]*)\)\s*"
    r"(?:throws\s+[^{]+)?\{",
    re.MULTILINE,
)
JAVA_CONTROL_NAMES = {"catch", "for", "if", "switch", "synchronized", "try", "while"}
```

- [ ] **Step 2: Dispatch the new rule**

Update `run_rules()`:

```python
    findings.extend(run_line_count_rules(config.get("line_count", []), root))
    findings.extend(run_java_package_file_count_rules(config.get("java_package_file_count", []), root))
    findings.extend(run_java_import_style_rules(config.get("java_import_style", []), root))
```

Update `unknown_rules`:

```python
    unknown_rules = sorted(
        set(config)
        - {
            "java_import_style",
            "java_package_file_count",
            "line_count",
            "project_callouts",
        }
    )
```

- [ ] **Step 3: Add import style implementation**

Add this code after `run_java_package_file_count_rules()`:

```python
def run_java_import_style_rules(rules: Any, root: Path) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("java_import_style must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"java_import_style[{index}]")
        name = require_string(rule, "name", default=f"java_import_style[{index}]")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.java"])
        exclude = require_string_list(rule, "exclude", default=[])
        allow_explicit = set(require_string_list(rule, "allow_explicit", default=[]))

        for source_file in iter_matching_files(root, paths, include, exclude):
            stripped_source = strip_java_comments_and_strings(source_file.read_text(encoding="utf-8"))
            for import_line in stripped_source.splitlines():
                normalized = normalize_java_import(import_line)
                if normalized is None or normalized in allow_explicit or normalized.endswith(".*"):
                    continue
                findings.append(
                    Finding(
                        rule=name,
                        path=source_file.relative_to(root),
                        message=(
                            f"explicit import {normalized}; use "
                            f"{suggest_java_wildcard_import(normalized)} unless allowlisted"
                        ),
                    )
                )

    return findings


def normalize_java_import(line: str) -> str | None:
    match = JAVA_IMPORT_RE.match(line)
    if match is None:
        return None
    prefix = "static " if match.group("static") else ""
    return f"{prefix}{match.group('target')}"


def suggest_java_wildcard_import(normalized_import: str) -> str:
    static_prefix = "static " if normalized_import.startswith("static ") else ""
    target = normalized_import.removeprefix("static ")
    package_or_type = target.rsplit(".", 1)[0]
    return f"{static_prefix}{package_or_type}.*"
```

- [ ] **Step 4: Add the shared Java source stripper**

Add this helper near `count_lines()`:

```python
def strip_java_comments_and_strings(source: str) -> str:
    result: list[str] = []
    index = 0
    state = "code"
    while index < len(source):
        char = source[index]
        next_two = source[index : index + 2]
        next_three = source[index : index + 3]

        if state == "code":
            if next_two == "//":
                result.extend("  ")
                index += 2
                state = "line_comment"
                continue
            if next_two == "/*":
                result.extend("  ")
                index += 2
                state = "block_comment"
                continue
            if next_three == '"""':
                result.extend("   ")
                index += 3
                state = "text_block"
                continue
            if char == '"':
                result.append(" ")
                index += 1
                state = "string"
                continue
            if char == "'":
                result.append(" ")
                index += 1
                state = "char"
                continue
            result.append(char)
            index += 1
            continue

        if state == "line_comment":
            if char == "\n":
                result.append("\n")
                state = "code"
            else:
                result.append(" ")
            index += 1
            continue

        if state == "block_comment":
            if next_two == "*/":
                result.extend("  ")
                index += 2
                state = "code"
                continue
            result.append("\n" if char == "\n" else " ")
            index += 1
            continue

        if state == "text_block":
            if next_three == '"""':
                result.extend("   ")
                index += 3
                state = "code"
                continue
            result.append("\n" if char == "\n" else " ")
            index += 1
            continue

        if state == "string":
            if char == "\\" and index + 1 < len(source):
                result.extend("  ")
                index += 2
                continue
            result.append("\n" if char == "\n" else " ")
            if char == '"':
                state = "code"
            index += 1
            continue

        if state == "char":
            if char == "\\" and index + 1 < len(source):
                result.extend("  ")
                index += 2
                continue
            result.append("\n" if char == "\n" else " ")
            if char == "'":
                state = "code"
            index += 1

    return "".join(result)
```

- [ ] **Step 5: Run the Supermeta tests and verify import tests pass**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 6: Commit the import rule**

```bash
git add tools/supermeta-rules/check.py
git commit -m "feat: enforce Java wildcard imports"
```

## Task 3: Lombok Boilerplate Tests

**Files:**
- Modify: `tools/supermeta-rules/check_test.py`

- [ ] **Step 1: Add failing tests for `java_lombok_boilerplate`**

Insert this test class after `JavaImportStyleRuleTest`:

```python
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
```

Add these helpers near the existing config helpers:

```python
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
```

- [ ] **Step 2: Run the Lombok tests and verify they fail for the missing rule implementation**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'
```

Expected: FAIL with `ValueError: unknown rule keys: java_lombok_boilerplate`.

- [ ] **Step 3: Commit the failing Lombok tests**

```bash
git add tools/supermeta-rules/check_test.py
git commit -m "test: cover Java Lombok boilerplate rule"
```

## Task 4: Lombok Boilerplate Rule

**Files:**
- Modify: `tools/supermeta-rules/check.py`
- Test: `tools/supermeta-rules/check_test.py`

- [ ] **Step 1: Dispatch the Lombok rule**

Update `run_rules()`:

```python
    findings.extend(run_line_count_rules(config.get("line_count", []), root))
    findings.extend(run_java_package_file_count_rules(config.get("java_package_file_count", []), root))
    findings.extend(run_java_import_style_rules(config.get("java_import_style", []), root))
    findings.extend(run_java_lombok_boilerplate_rules(config.get("java_lombok_boilerplate", []), root))
```

Update `unknown_rules`:

```python
    unknown_rules = sorted(
        set(config)
        - {
            "java_import_style",
            "java_lombok_boilerplate",
            "java_package_file_count",
            "line_count",
            "project_callouts",
        }
    )
```

- [ ] **Step 2: Add Lombok rule implementation**

Add this code after `run_java_import_style_rules()`:

```python
def run_java_lombok_boilerplate_rules(rules: Any, root: Path) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("java_lombok_boilerplate must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"java_lombok_boilerplate[{index}]")
        name = require_string(rule, "name", default=f"java_lombok_boilerplate[{index}]")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.java"])
        exclude = require_string_list(rule, "exclude", default=[])
        ignore_annotations = tuple(require_string_list(rule, "ignore_annotations", default=[]))
        allow_methods = set(require_string_list(rule, "allow_methods", default=[]))

        for source_file in iter_matching_files(root, paths, include, exclude):
            stripped_source = strip_java_comments_and_strings(source_file.read_text(encoding="utf-8"))
            class_blocks = list(iter_java_class_blocks(stripped_source))
            findings.extend(
                find_lombok_method_boilerplate(
                    name,
                    source_file.relative_to(root),
                    stripped_source,
                    class_blocks,
                    ignore_annotations,
                    allow_methods,
                )
            )
            findings.extend(
                find_lombok_builder_boilerplate(
                    name,
                    source_file.relative_to(root),
                    stripped_source,
                    class_blocks,
                    ignore_annotations,
                )
            )

    return findings
```

- [ ] **Step 3: Add method and builder finding helpers**

Add this code below `run_java_lombok_boilerplate_rules()`:

```python
def find_lombok_method_boilerplate(
    rule_name: str,
    relative_path: Path,
    source: str,
    class_blocks: list[JavaClassBlock],
    ignore_annotations: tuple[str, ...],
    allow_methods: set[str],
) -> list[Finding]:
    findings: list[Finding] = []
    for method in iter_java_method_blocks(source):
        if method.name in JAVA_CONTROL_NAMES or method.name in allow_methods:
            continue
        if annotations_match_any(method.annotations, ignore_annotations):
            continue
        if method_is_inside_ignored_class(method, class_blocks, ignore_annotations):
            continue

        if is_simple_java_getter(method) or is_simple_java_setter(method) or is_fluent_java_setter(method):
            findings.append(
                Finding(
                    rule=rule_name,
                    path=relative_path,
                    message=f"{method.name}() is Lombok boilerplate; {lombok_suggestion(ignore_annotations)}",
                )
            )
        elif is_builder_factory(method):
            findings.append(
                Finding(
                    rule=rule_name,
                    path=relative_path,
                    message=f"{method.name}() is Lombok builder boilerplate; {lombok_suggestion(ignore_annotations)}",
                )
            )

    return findings


def find_lombok_builder_boilerplate(
    rule_name: str,
    relative_path: Path,
    source: str,
    class_blocks: list[JavaClassBlock],
    ignore_annotations: tuple[str, ...],
) -> list[Finding]:
    findings: list[Finding] = []
    for class_block in class_blocks:
        if class_block.name != "Builder":
            continue
        if annotations_match_any(class_block.annotations, ignore_annotations):
            continue
        class_source = source[class_block.start : class_block.end]
        compact = normalize_java_body(class_source)
        if " build(" in compact and "return this;" in compact:
            findings.append(
                Finding(
                    rule=rule_name,
                    path=relative_path,
                    message=f"Builder class is Lombok builder boilerplate; {lombok_suggestion(ignore_annotations)}",
                )
            )
    return findings
```

- [ ] **Step 4: Add Java block iteration helpers**

Add this code below the finding helpers:

```python
def iter_java_class_blocks(source: str) -> list[JavaClassBlock]:
    blocks: list[JavaClassBlock] = []
    for match in JAVA_CLASS_RE.finditer(source):
        open_brace = source.find("{", match.start())
        close_brace = find_matching_brace(source, open_brace)
        if open_brace == -1 or close_brace == -1:
            continue
        blocks.append(
            JavaClassBlock(
                name=match.group("name"),
                start=match.start(),
                end=close_brace + 1,
                annotations=annotations_before(source, match.start()),
            )
        )
    return blocks


def iter_java_method_blocks(source: str) -> list[JavaMethodBlock]:
    blocks: list[JavaMethodBlock] = []
    for match in JAVA_METHOD_RE.finditer(source):
        method_name = match.group("name")
        if method_name in JAVA_CONTROL_NAMES:
            continue
        open_brace = source.find("{", match.start())
        close_brace = find_matching_brace(source, open_brace)
        if open_brace == -1 or close_brace == -1:
            continue
        blocks.append(
            JavaMethodBlock(
                name=method_name,
                return_type=" ".join(match.group("return").split()),
                params=match.group("params").strip(),
                body=source[open_brace + 1 : close_brace],
                start=match.start(),
                end=close_brace + 1,
                annotations=annotations_before(source, match.start()),
            )
        )
    return blocks


def find_matching_brace(source: str, open_brace: int) -> int:
    if open_brace < 0 or open_brace >= len(source) or source[open_brace] != "{":
        return -1
    depth = 0
    for index in range(open_brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return index
    return -1
```

- [ ] **Step 5: Add annotation and method-shape helpers**

Add this code below the block helpers:

```python
def annotations_before(source: str, index: int) -> tuple[str, ...]:
    annotations: list[str] = []
    cursor = index
    while cursor > 0:
        line_start = source.rfind("\n", 0, cursor - 1) + 1
        line = source[line_start:cursor].strip()
        if not line:
            cursor = line_start
            continue
        if not line.startswith("@"):
            break
        annotation_name = line[1:].split("(", 1)[0].strip()
        annotations.append(annotation_name)
        cursor = line_start
    return tuple(reversed(annotations))


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


def method_is_inside_ignored_class(
    method: JavaMethodBlock,
    class_blocks: list[JavaClassBlock],
    ignore_annotations: tuple[str, ...],
) -> bool:
    return any(
        class_block.start <= method.start <= class_block.end
        and annotations_match_any(class_block.annotations, ignore_annotations)
        for class_block in class_blocks
    )


def normalize_java_body(body: str) -> str:
    return " ".join(body.split())


def java_param_names(params: str) -> list[str]:
    if not params.strip():
        return []
    names: list[str] = []
    for param in params.split(","):
        cleaned = re.sub(r"@\S+(?:\([^)]*\))?", "", param)
        cleaned = cleaned.replace("final ", "").replace("...", " ")
        parts = [part for part in cleaned.strip().split() if part]
        if not parts:
            continue
        names.append(parts[-1].replace("[]", ""))
    return names
```

- [ ] **Step 6: Add boilerplate predicate helpers**

Add this code below the annotation helpers:

```python
def is_simple_java_getter(method: JavaMethodBlock) -> bool:
    if method.params.strip():
        return False
    if not (
        method.name.startswith("get")
        and len(method.name) > 3
        and method.name[3].isupper()
        or method.name.startswith("is")
        and len(method.name) > 2
        and method.name[2].isupper()
    ):
        return False
    return re.fullmatch(r"return\s+(?:this\.)?[A-Za-z_$][\w$]*\s*;", normalize_java_body(method.body)) is not None


def is_simple_java_setter(method: JavaMethodBlock) -> bool:
    if not (method.name.startswith("set") and len(method.name) > 3 and method.name[3].isupper()):
        return False
    param_names = java_param_names(method.params)
    if len(param_names) != 1:
        return False
    param_name = re.escape(param_names[0])
    return (
        re.fullmatch(
            rf"(?:this\.)?[A-Za-z_$][\w$]*\s*=\s*{param_name}\s*;",
            normalize_java_body(method.body),
        )
        is not None
    )


def is_fluent_java_setter(method: JavaMethodBlock) -> bool:
    param_names = java_param_names(method.params)
    if len(param_names) != 1:
        return False
    param_name = re.escape(param_names[0])
    return (
        re.fullmatch(
            rf"(?:this\.)?[A-Za-z_$][\w$]*\s*=\s*{param_name}\s*;\s*return\s+this\s*;",
            normalize_java_body(method.body),
        )
        is not None
    )


def is_builder_factory(method: JavaMethodBlock) -> bool:
    return (
        method.name == "builder"
        and not method.params.strip()
        and re.fullmatch(r"return\s+new\s+[A-Za-z_$][\w$]*Builder?\s*\(\s*\)\s*;", normalize_java_body(method.body))
        is not None
    )


def lombok_suggestion(ignore_annotations: tuple[str, ...]) -> str:
    if ignore_annotations:
        return (
            "use Lombok or annotate the method/class with "
            f"{ignore_annotations[0]} if this is intentionally handwritten"
        )
    return "use Lombok"
```

- [ ] **Step 7: Run the Supermeta tests and verify Lombok tests pass**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 8: Commit the Lombok rule**

```bash
git add tools/supermeta-rules/check.py
git commit -m "feat: detect Java Lombok boilerplate"
```

## Task 5: Java Template Rule Contract

**Files:**
- Modify: `templates/java-gradle-cli/supermeta-rules.json`
- Modify: `templates/java-gradle-cli/src/main/java/com/example/LoggingConfig.java`
- Test: `tools/supermeta-rules/check.py`
- Test: `templates/java-gradle-cli/build.gradle.kts`

- [ ] **Step 1: Enable the two Java rules in the template config**

Replace `templates/java-gradle-cli/supermeta-rules.json` with:

```json
{
  "line_count": [
    {
      "name": "product-source",
      "max_lines": 1000,
      "paths": ["src/main"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"]
    }
  ],
  "java_package_file_count": [
    {
      "name": "java-package-size",
      "max_files": 8,
      "paths": ["src/main/java", "src/test/java"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"]
    }
  ],
  "java_import_style": [
    {
      "name": "java-wildcard-imports",
      "paths": ["src/main/java", "src/test/java"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"],
      "allow_explicit": []
    }
  ],
  "java_lombok_boilerplate": [
    {
      "name": "java-lombok-boilerplate",
      "paths": ["src/main/java", "src/test/java"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"],
      "ignore_annotations": [],
      "allow_methods": []
    }
  ],
  "project_callouts": [
    {
      "name": "java-checkstyle",
      "language": "java",
      "paths": ["src/main/java", "src/test/java"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"],
      "command": ["../../scripts/agent-gradle", ".", "checkstyleMain", "checkstyleTest"]
    }
  ]
}
```

- [ ] **Step 2: Run the shared rules against the Java template and verify imports now fail**

Run:

```bash
python3 tools/supermeta-rules/check.py --config templates/java-gradle-cli/supermeta-rules.json --root templates/java-gradle-cli --skip-callouts
```

Expected: FAIL with explicit import findings in `src/main/java/com/example/LoggingConfig.java`.

- [ ] **Step 3: Convert `LoggingConfig.java` away from explicit imports**

Replace the import block with:

```java
import java.util.*;

import ch.qos.logback.classic.encoder.*;
import ch.qos.logback.classic.spi.*;
import ch.qos.logback.core.*;
import ch.qos.logback.core.encoder.*;
import net.logstash.logback.encoder.*;
import net.logstash.logback.fieldnames.*;
import org.slf4j.*;
```

Update the `Level` and `LoggerContext` references so no explicit `ch.qos.logback.classic.*` import is needed:

```java
        ch.qos.logback.classic.Level level = switch (levelName) {
            case "trace" -> ch.qos.logback.classic.Level.TRACE;
            case "debug" -> ch.qos.logback.classic.Level.DEBUG;
            case "info" -> ch.qos.logback.classic.Level.INFO;
            case "warn" -> ch.qos.logback.classic.Level.WARN;
            case "error" -> ch.qos.logback.classic.Level.ERROR;
            case "off" -> ch.qos.logback.classic.Level.OFF;
```

Update the `configure`, encoder helpers, and record signatures:

```java
    public static void configure(Config config) {
        ch.qos.logback.classic.LoggerContext context =
            (ch.qos.logback.classic.LoggerContext) LoggerFactory.getILoggerFactory();
```

```java
    private static Encoder<ILoggingEvent> textEncoder(ch.qos.logback.classic.LoggerContext context) {
```

```java
    private static Encoder<ILoggingEvent> jsonEncoder(ch.qos.logback.classic.LoggerContext context) {
```

```java
    record Config(ch.qos.logback.classic.Level level, LogFormat format) {
    }
```

- [ ] **Step 4: Run the shared rules and Java template check**

Run:

```bash
python3 tools/supermeta-rules/check.py --config templates/java-gradle-cli/supermeta-rules.json --root templates/java-gradle-cli --skip-callouts
./scripts/agent-gradle templates/java-gradle-cli check
```

Expected: both PASS.

- [ ] **Step 5: Commit the template rule contract**

```bash
git add templates/java-gradle-cli/supermeta-rules.json templates/java-gradle-cli/src/main/java/com/example/LoggingConfig.java
git commit -m "feat: enable Java heuristic gates in template"
```

## Task 6: Documentation And Bootstrap Contract

**Files:**
- Modify: `templates/java-gradle-cli/README.md`
- Modify: `templates/java-gradle-cli/AGENTS.md`
- Modify: `tools/bootstrap/bootstrap.py`
- Modify: `tools/bootstrap/bootstrap_test.py`
- Modify: `README.md`
- Modify: `environments/supermeta/README.md`
- Modify: `environments/supermeta/AGENTS.md`
- Test: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Update Java template README conventions**

In `templates/java-gradle-cli/README.md`, replace the Java convention bullets with:

```markdown
- production source files under `src/main` are checked for a 1000-line maximum;
- Java package directories are checked for an 8-source-file maximum before they should be split into subpackages;
- wildcard imports are enforced for Java source by Supermeta; use explicit imports only through `allow_explicit` in `supermeta-rules.json`;
- Lombok boilerplate checks reject handwritten getters, setters, and builder patterns; use Lombok annotations or a configured `ignore_annotations` escape hatch for rare intentional exceptions;
- if you rename `App`, update `application.mainClass` in `build.gradle.kts`.
```

- [ ] **Step 2: Update Java template AGENTS rules**

In `templates/java-gradle-cli/AGENTS.md`, replace:

```markdown
- Use wildcard imports where feasible.
- Use Lombok where it keeps Java source compact; preserve compile-only and annotation-processor wiring.
```

with:

```markdown
- Supermeta enforces wildcard imports for Java source; use `allow_explicit` only for deliberate exceptions.
- Supermeta rejects handwritten getter, setter, and builder boilerplate; use Lombok annotations or a configured `ignore_annotations` escape hatch for rare intentional exceptions.
- Preserve Lombok compile-only and annotation-processor wiring.
```

- [ ] **Step 3: Update generated Java README and AGENTS text**

In `tools/bootstrap/bootstrap.py`, add these bullets to the generated Java README customization section after the Java package-size bullet:

```markdown
- Supermeta enforces wildcard imports for Java source; configure `allow_explicit` only for deliberate exceptions.
- Supermeta rejects handwritten getter, setter, and builder boilerplate; use Lombok annotations or a configured `ignore_annotations` escape hatch for rare intentional exceptions.
```

In `generated_java_agents()`, replace:

```markdown
- Use wildcard imports where feasible.
- Use Lombok where it keeps Java source compact, and keep it as compile-only plus annotation-processor wiring.
```

with:

```markdown
- Supermeta enforces wildcard imports for Java source; use `allow_explicit` only for deliberate exceptions.
- Supermeta rejects handwritten getter, setter, and builder boilerplate; use Lombok annotations or a configured `ignore_annotations` escape hatch for rare intentional exceptions.
- Keep Lombok as compile-only plus annotation-processor wiring.
```

- [ ] **Step 4: Update catalog-level wording**

In `README.md`, replace the wildcard import guidance with:

```markdown
- route language-specific lint and reusable heuristic gates through `tools/supermeta-rules/` project callouts;
- enforce wildcard imports for Java source unless a project explicitly allowlists an import;
- enforce Lombok over handwritten getter, setter, and builder boilerplate for Java source unless a project configures an ignore annotation.
```

In `environments/supermeta/README.md`, replace the rule guidance bullets with:

```markdown
- language-specific lint and reusable heuristic gates should be routed through `tools/supermeta-rules/` project callouts;
- Java source should enforce wildcard imports and Lombok-backed data boilerplate through shared Supermeta rules.
```

In `environments/supermeta/AGENTS.md`, replace the wildcard import bullet with:

```markdown
- enforce Java wildcard imports and Lombok-backed getter, setter, and builder boilerplate through `tools/supermeta-rules/`;
```

- [ ] **Step 5: Add bootstrap contract assertions**

In `tools/bootstrap/bootstrap_test.py`, after the existing `rules_config` assertions for `"java_package_file_count"` and `"project_callouts"`, add:

```python
            self.assertIn('"java_import_style"', rules_config)
            self.assertIn('"java_lombok_boilerplate"', rules_config)
            self.assertIn('"allow_explicit": []', rules_config)
            self.assertIn('"ignore_annotations": []', rules_config)
```

After the existing README and AGENTS assertions, add:

```python
            self.assertIn("Supermeta enforces wildcard imports", readme)
            self.assertIn("Supermeta rejects handwritten getter, setter, and builder boilerplate", readme)
            self.assertIn("Supermeta enforces wildcard imports", agents)
            self.assertIn("Supermeta rejects handwritten getter, setter, and builder boilerplate", agents)
```

- [ ] **Step 6: Run bootstrap tests and verify generated contract**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 7: Commit docs and bootstrap contract**

```bash
git add README.md environments/supermeta/README.md environments/supermeta/AGENTS.md templates/java-gradle-cli/README.md templates/java-gradle-cli/AGENTS.md tools/bootstrap/bootstrap.py tools/bootstrap/bootstrap_test.py
git commit -m "docs: document enforced Java heuristic gates"
```

## Task 7: Final Verification

**Files:**
- Verify: entire repository change set

- [ ] **Step 1: Run Supermeta rule tests**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 2: Run bootstrap launcher tests**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 3: Run Java template verification**

Run:

```bash
./scripts/agent-gradle templates/java-gradle-cli check
```

Expected: PASS with `Supermeta rules passed.` in the Gradle output.

- [ ] **Step 4: Run final hygiene checks**

Run:

```bash
git diff --check
git status --short
```

Expected: `git diff --check` exits 0. `git status --short` shows no uncommitted implementation files after the final commit.

- [ ] **Step 5: Resolve any verification failure in its owning task**

If verification fails, return to the task that owns the failing file, make the smallest fix there, rerun that task's test command, and amend or create the task's listed commit. Do not create a broad cleanup commit from final verification.

Expected: this step is skipped when Task 1 through Task 6 commits already leave the worktree clean.
