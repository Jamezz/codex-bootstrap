#!/usr/bin/env python3
"""Run simple Supermeta rules for bootstrap templates."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Finding:
    rule: str
    path: Path
    message: str


@dataclass(frozen=True)
class JavaClassBlock:
    kind: str
    name: str
    start: int
    end: int
    annotations: tuple[str, ...]


@dataclass(frozen=True)
class JavaRecordType:
    package_name: str
    name: str
    qualified_type_name: str


@dataclass(frozen=True)
class JavaSourceContext:
    relative_path: Path
    source: str
    class_blocks: list[JavaClassBlock]
    package_name: str
    explicit_imports: frozenset[str]
    wildcard_imports: frozenset[str]
    declared_record_names: frozenset[str]


@dataclass(frozen=True)
class JavaMethodBlock:
    name: str
    return_type: str
    params: str
    body: str
    start: int
    end: int
    annotations: tuple[str, ...]


JAVA_IMPORT_RE = re.compile(
    r"^\s*import\s+(?P<static>static\s+)?"
    r"(?P<target>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*(?:\.\*)?)\s*;\s*$"
)
JAVA_PACKAGE_RE = re.compile(
    r"^\s*package\s+(?P<name>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*;",
    re.MULTILINE,
)
JAVA_CLASS_RE = re.compile(
    r"\b(?P<kind>class|record|interface|enum)\s+(?P<name>[A-Za-z_$][\w$]*)[^{]*\{"
)
JAVA_METHOD_RE = re.compile(
    r"(?P<return>[A-Za-z_$][\w$<>\[\].?,\s]*?)\s+"
    r"(?P<name>[A-Za-z_$][\w$]*)\s*"
    r"\((?P<params>[^()]*)\)\s*"
    r"(?:throws\s+[^{]+)?\{",
    re.MULTILINE,
)
JAVA_CONTROL_NAMES = {"catch", "for", "if", "switch", "synchronized", "try", "while"}
JAVA_MODIFIERS = {
    "abstract",
    "final",
    "native",
    "private",
    "protected",
    "public",
    "static",
    "strictfp",
    "synchronized",
}
JAVA_CONSTRUCTOR_TYPE_ARGS_RE = r"(?:<[^()\n;{}]*>)?"
JAVA_NEW_TYPE_ARGS_RE = r"(?:<[^()\n;{}]*>\s*)?"
JAVA_REFERENCE_TYPE_ARGS_RE = r"(?:<[^()\n;{}]*>\s*)?"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = args.config.resolve()
    root = args.root.resolve() if args.root else config_path.parent

    try:
        config = load_config(config_path)
        findings = run_rules(config, root, skip_callouts=args.skip_callouts)
    except ValueError as error:
        print(f"supermeta-rules: {error}", file=sys.stderr)
        return 2

    if findings:
        print("Supermeta rule violations:")
        for finding in findings:
            print(f"- [{finding.rule}] {finding.path}: {finding.message}")
        return 1

    print("Supermeta rules passed.")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Supermeta template rules.")
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a Supermeta rules JSON file.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        help="Root directory used to resolve rule paths. Defaults to the config directory.",
    )
    parser.add_argument(
        "--skip-callouts",
        action="store_true",
        help="Skip project callouts that invoke language-specific tooling.",
    )
    return parser.parse_args(argv)


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.is_file():
        raise ValueError(f"config file does not exist: {config_path}")

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON in {config_path}: {error}") from error

    if not isinstance(data, dict):
        raise ValueError("config root must be a JSON object")

    return data


def run_rules(config: dict[str, Any], root: Path, skip_callouts: bool = False) -> list[Finding]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"root directory does not exist: {root}")

    findings: list[Finding] = []
    findings.extend(run_line_count_rules(config.get("line_count", []), root))
    findings.extend(run_java_package_class_count_rules(config.get("java_package_class_count", []), root))
    findings.extend(run_java_import_style_rules(config.get("java_import_style", []), root))
    findings.extend(run_java_lombok_boilerplate_rules(config.get("java_lombok_boilerplate", []), root))
    findings.extend(
        run_project_callout_rules(
            config.get("project_callouts", []),
            root,
            execute=not project_callouts_are_skipped(skip_callouts),
        )
    )

    unknown_rules = sorted(
        set(config)
        - {
            "java_import_style",
            "java_lombok_boilerplate",
            "java_package_class_count",
            "line_count",
            "project_callouts",
        }
    )
    if unknown_rules:
        raise ValueError(f"unknown rule keys: {', '.join(unknown_rules)}")
    return findings


def run_line_count_rules(rules: Any, root: Path) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("line_count must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"line_count[{index}]")
        name = require_string(rule, "name", default=f"line_count[{index}]")
        max_lines = require_positive_int(rule, "max_lines")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*"])
        exclude = require_string_list(rule, "exclude", default=[])

        for source_file in iter_matching_files(root, paths, include, exclude):
            line_count = count_lines(source_file)
            if line_count > max_lines:
                findings.append(
                    Finding(
                        rule=name,
                        path=source_file.relative_to(root),
                        message=f"{line_count} lines exceeds limit of {max_lines}",
                    )
                )

    return findings


def run_java_package_class_count_rules(rules: Any, root: Path) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("java_package_class_count must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"java_package_class_count[{index}]")
        name = require_string(rule, "name", default=f"java_package_class_count[{index}]")
        max_classes = require_positive_int(rule, "max_classes")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.java"])
        exclude = require_string_list(rule, "exclude", default=[])

        classes_by_package: dict[Path, list[str]] = {}
        for source_file in iter_matching_files(root, paths, include, exclude):
            stripped_source = strip_java_comments_and_strings(source_file.read_text(encoding="utf-8"))
            type_names = top_level_java_type_names(stripped_source)
            classes_by_package.setdefault(source_file.parent, []).extend(type_names)

        for package_dir, type_names in sorted(classes_by_package.items()):
            type_count = len(type_names)
            if type_count > max_classes:
                findings.append(
                    Finding(
                        rule=name,
                        path=package_dir.relative_to(root),
                        message=(
                            f"{type_count} Java top-level types exceeds package layer limit "
                            f"of {max_classes}; refactor this layer into cohesive subpackages "
                            "based on the system context"
                        ),
                    )
                )

    return findings


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


def java_package_name(source: str) -> str:
    match = JAVA_PACKAGE_RE.search(source)
    if match is None:
        return ""
    return match.group("name")


def java_imports(source: str) -> tuple[set[str], set[str]]:
    explicit_imports: set[str] = set()
    wildcard_imports: set[str] = set()
    for import_line in source.splitlines():
        normalized = normalize_java_import(import_line)
        if normalized is None or normalized.startswith("static "):
            continue
        if normalized.endswith(".*"):
            wildcard_imports.add(normalized.removesuffix(".*"))
        else:
            explicit_imports.add(normalized)
    return explicit_imports, wildcard_imports


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

        source_files = list(iter_matching_files(root, paths, include, exclude))
        source_contexts: list[JavaSourceContext] = []
        record_types: set[JavaRecordType] = set()
        require_record_builder = require_bool(rule, "require_record_builder", default=False)

        for source_file in source_files:
            stripped_source = strip_java_comments_and_strings(source_file.read_text(encoding="utf-8"))
            class_blocks = iter_java_class_blocks(stripped_source)
            package_name = java_package_name(stripped_source)
            explicit_imports, wildcard_imports = java_imports(stripped_source)
            declared_record_types = java_record_types(package_name, class_blocks, ignore_annotations)
            declared_record_names = {record_type.name for record_type in declared_record_types}
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
            source_contexts.append(
                JavaSourceContext(
                    relative_path=source_file.relative_to(root),
                    source=stripped_source,
                    class_blocks=class_blocks,
                    package_name=package_name,
                    explicit_imports=frozenset(explicit_imports),
                    wildcard_imports=frozenset(wildcard_imports),
                    declared_record_names=frozenset(declared_record_names),
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
            if require_record_builder:
                findings.extend(
                    find_lombok_record_builder_requirement(
                        name, source_file.relative_to(root), class_blocks, ignore_annotations
                    )
                )
                record_types.update(declared_record_types)

        if require_record_builder and record_types:
            for source_context in source_contexts:
                findings.extend(
                    find_lombok_record_constructor_calls(
                        name,
                        source_context,
                        ignore_annotations,
                        record_types,
                    )
                )

    return findings


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

        is_accessor = is_simple_java_getter(method) or is_simple_java_setter(method) or is_fluent_java_setter(method)
        if is_accessor and is_override_accessor_contract_method(method):
            continue

        if is_accessor:
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


def find_lombok_record_builder_requirement(
    rule_name: str,
    relative_path: Path,
    class_blocks: list[JavaClassBlock],
    ignore_annotations: tuple[str, ...],
) -> list[Finding]:
    findings: list[Finding] = []
    for class_block in class_blocks:
        if class_block.kind != "record":
            continue
        if annotations_match_any(class_block.annotations, ignore_annotations):
            continue
        if annotations_match_any(class_block.annotations, ("Builder",)):
            continue
        findings.append(
            Finding(
                rule=rule_name,
                path=relative_path,
                message=(
                    f"{class_block.name} is a record and should use Lombok @Builder for readability; "
                    f"{lombok_suggestion(ignore_annotations)}"
                ),
            )
        )
    return findings


def find_lombok_record_constructor_calls(
    rule_name: str,
    source_context: JavaSourceContext,
    ignore_annotations: tuple[str, ...],
    record_types: set[JavaRecordType],
) -> list[Finding]:
    if not record_types:
        return []

    findings: list[Finding] = []
    accessible_names = accessible_record_names(source_context, record_types)
    for name in sorted(accessible_names):
        findings.extend(
            find_record_constructor_pattern(
                rule_name,
                source_context,
                ignore_annotations,
                rf"\bnew\s+{JAVA_NEW_TYPE_ARGS_RE}{re.escape(name)}\s*{JAVA_CONSTRUCTOR_TYPE_ARGS_RE}\s*\(",
                f"{name} instances should be built with {name}.builder() for readability; "
                f"{lombok_suggestion(ignore_annotations)}",
            )
        )
        findings.extend(
            find_record_constructor_pattern(
                rule_name,
                source_context,
                ignore_annotations,
                rf"(?<![.\w$]){re.escape(name)}\s*{JAVA_CONSTRUCTOR_TYPE_ARGS_RE}"
                rf"\s*::\s*{JAVA_REFERENCE_TYPE_ARGS_RE}new\b",
                f"{name} constructor references should use {name}.builder() for readability; "
                f"{lombok_suggestion(ignore_annotations)}",
            )
        )
    for record_name, qualified_name in sorted(qualified_record_constructor_targets(source_context, record_types)):
        findings.extend(
            find_record_constructor_pattern(
                rule_name,
                source_context,
                ignore_annotations,
                rf"\bnew\s+{JAVA_NEW_TYPE_ARGS_RE}{re.escape(qualified_name)}\s*{JAVA_CONSTRUCTOR_TYPE_ARGS_RE}\s*\(",
                f"{record_name} instances should be built with {record_name}.builder() for readability; "
                f"{lombok_suggestion(ignore_annotations)}",
            )
        )
        findings.extend(
            find_record_constructor_pattern(
                rule_name,
                source_context,
                ignore_annotations,
                rf"\b{re.escape(qualified_name)}\s*{JAVA_CONSTRUCTOR_TYPE_ARGS_RE}"
                rf"\s*::\s*{JAVA_REFERENCE_TYPE_ARGS_RE}new\b",
                f"{record_name} constructor references should use {record_name}.builder() for readability; "
                f"{lombok_suggestion(ignore_annotations)}",
            )
        )
    return findings


def find_record_constructor_pattern(
    rule_name: str,
    source_context: JavaSourceContext,
    ignore_annotations: tuple[str, ...],
    pattern: str,
    message: str,
) -> list[Finding]:
    findings: list[Finding] = []
    for match in re.finditer(pattern, source_context.source):
        if is_position_inside_ignored_class(match.start(), source_context.class_blocks, ignore_annotations):
            continue
        findings.append(
            Finding(
                rule=rule_name,
                path=source_context.relative_path,
                message=message,
            )
        )
    return findings


def accessible_record_names(source_context: JavaSourceContext, record_types: set[JavaRecordType]) -> set[str]:
    names = set(source_context.declared_record_names)
    explicit_imports_by_name = {
        import_name.rsplit(".", 1)[-1]: import_name
        for import_name in source_context.explicit_imports
    }
    for record_type in record_types:
        qualified_name = qualified_java_name(record_type.package_name, record_type.qualified_type_name)
        explicitly_imported_type = explicit_imports_by_name.get(record_type.name)
        if explicitly_imported_type == qualified_name:
            names.add(record_type.name)
            continue
        if explicitly_imported_type is not None:
            continue
        if record_type.qualified_type_name == record_type.name:
            if record_type.package_name == source_context.package_name:
                names.add(record_type.name)
            elif record_type.package_name in source_context.wildcard_imports:
                names.add(record_type.name)
            continue
        owner_qualified_name = qualified_java_name(
            record_type.package_name,
            record_type.qualified_type_name.rsplit(".", 1)[0],
        )
        if owner_qualified_name in source_context.wildcard_imports:
            names.add(record_type.name)
    return names


def qualified_record_constructor_targets(
    source_context: JavaSourceContext,
    record_types: set[JavaRecordType],
) -> set[tuple[str, str]]:
    targets: set[tuple[str, str]] = set()
    for record_type in record_types:
        canonical_name = qualified_java_name(record_type.package_name, record_type.qualified_type_name)
        if canonical_name != record_type.name:
            targets.add((record_type.name, canonical_name))
        if record_type.qualified_type_name == record_type.name:
            continue
        if record_type_package_type_is_visible(source_context, record_type):
            targets.add((record_type.name, record_type.qualified_type_name))
    return targets


def record_type_package_type_is_visible(source_context: JavaSourceContext, record_type: JavaRecordType) -> bool:
    if record_type.package_name == source_context.package_name:
        return True
    if record_type.package_name in source_context.wildcard_imports:
        return True
    owner_name = record_type.qualified_type_name.split(".", 1)[0]
    owner_qualified_name = qualified_java_name(record_type.package_name, owner_name)
    return owner_qualified_name in source_context.explicit_imports


def qualified_java_name(package_name: str, type_name: str) -> str:
    if not package_name:
        return type_name
    return f"{package_name}.{type_name}"


def java_record_types(
    package_name: str,
    class_blocks: list[JavaClassBlock],
    ignore_annotations: tuple[str, ...],
) -> set[JavaRecordType]:
    record_types: set[JavaRecordType] = set()
    for class_block in class_blocks:
        if class_block.kind != "record":
            continue
        if annotations_match_any(class_block.annotations, ignore_annotations):
            continue
        enclosing_type_names = [
            candidate.name
            for candidate in sorted(class_blocks, key=lambda item: item.start)
            if candidate.start < class_block.start and class_block.end <= candidate.end
        ]
        record_types.add(
            JavaRecordType(
                package_name=package_name,
                name=class_block.name,
                qualified_type_name=".".join([*enclosing_type_names, class_block.name]),
            )
        )
    return record_types


def iter_java_class_blocks(source: str) -> list[JavaClassBlock]:
    blocks: list[JavaClassBlock] = []
    for match in JAVA_CLASS_RE.finditer(source):
        open_brace = source.find("{", match.start())
        close_brace = find_matching_brace(source, open_brace)
        if open_brace == -1 or close_brace == -1:
            continue
        blocks.append(
            JavaClassBlock(
                kind=match.group("kind"),
                name=match.group("name"),
                start=match.start(),
                end=close_brace + 1,
                annotations=annotations_before(source, match.start()),
            )
        )
    return blocks


def top_level_java_type_names(source: str) -> list[str]:
    names: list[str] = []
    for match in JAVA_CLASS_RE.finditer(source):
        if java_brace_depth_before(source, match.start()) == 0:
            names.append(match.group("name"))
    return names


def java_brace_depth_before(source: str, index: int) -> int:
    depth = 0
    for char in source[:index]:
        if char == "{":
            depth += 1
        elif char == "}" and depth > 0:
            depth -= 1
    return depth


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


def annotations_before(source: str, index: int) -> tuple[str, ...]:
    annotations: list[str] = []
    cursor = index
    while cursor > 0:
        line_start = source.rfind("\n", 0, cursor - 1) + 1
        line = source[line_start:cursor].strip()
        if not line:
            cursor = line_start
            continue
        if line == "@":
            line_end = source.find("\n", cursor)
            if line_end == -1:
                line_end = len(source)
            annotation_line = source[line_start:line_end].strip()
            annotation_name = annotation_line[1:].split("(", 1)[0].strip()
            if annotation_name:
                annotations.append(annotation_name)
            cursor = line_start
            continue
        if not line.startswith("@"):
            if all(token in JAVA_MODIFIERS for token in line.split()):
                cursor = line_start
                continue
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


def is_position_inside_ignored_class(
    position: int,
    class_blocks: list[JavaClassBlock],
    ignore_annotations: tuple[str, ...],
) -> bool:
    return any(
        class_block.start <= position <= class_block.end
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


def is_override_accessor_contract_method(method: JavaMethodBlock) -> bool:
    return annotations_match_any(method.annotations, ("Override",))


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


def run_project_callout_rules(rules: Any, root: Path, execute: bool = True) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("project_callouts must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"project_callouts[{index}]")
        name = require_string(rule, "name", default=f"project_callouts[{index}]")
        language = require_string(rule, "language")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*"])
        exclude = require_string_list(rule, "exclude", default=[])
        command = require_non_empty_string_list(rule, "command")

        if not execute or not iter_matching_files(root, paths, include, exclude):
            continue

        try:
            result = subprocess.run(
                command,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
        except OSError as error:
            findings.append(
                Finding(
                    rule=name,
                    path=Path("."),
                    message=f"{language} callout could not start: {shlex.join(command)}\n{error}",
                )
            )
            continue
        if result.returncode != 0:
            findings.append(
                Finding(
                    rule=name,
                    path=Path("."),
                    message=(
                        f"{language} callout failed with exit {result.returncode}: "
                        f"{shlex.join(command)}\n{trim_output(result.stdout)}"
                    ),
                )
            )

    return findings


def project_callouts_are_skipped(skip_callouts: bool) -> bool:
    return skip_callouts or os.environ.get("SUPERMETA_SKIP_PROJECT_CALLOUTS") in {
        "1",
        "true",
        "yes",
    }


def iter_matching_files(
    root: Path,
    paths: list[str],
    include: list[str],
    exclude: list[str],
) -> list[Path]:
    matches: set[Path] = set()
    for configured_path in paths:
        base_path = resolve_under_root(root, configured_path)
        if base_path.is_file():
            candidates = [base_path]
        elif base_path.is_dir():
            candidates = [path for path in base_path.rglob("*") if path.is_file()]
        else:
            continue

        for candidate in candidates:
            relative_path = candidate.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(relative_path, pattern) for pattern in include) and not any(
                fnmatch.fnmatch(relative_path, pattern) for pattern in exclude
            ):
                matches.add(candidate)

    return sorted(matches)


def resolve_under_root(root: Path, configured_path: str) -> Path:
    root = root.resolve()
    candidate = (root / configured_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"path escapes root: {configured_path}") from error
    return candidate


def count_lines(path: Path) -> int:
    with path.open("r", encoding="utf-8") as source:
        return sum(1 for _ in source)


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


def trim_output(output: str, max_characters: int = 4000) -> str:
    stripped = output.strip()
    if len(stripped) <= max_characters:
        return stripped
    return f"{stripped[:max_characters]}... [truncated]"


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be an object")
    return value


def require_string(rule: dict[str, Any], key: str, default: str | None = None) -> str:
    value = rule.get(key, default)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def require_positive_int(rule: dict[str, Any], key: str) -> int:
    value = rule.get(key)
    if not isinstance(value, int) or value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value


def require_string_list(
    rule: dict[str, Any],
    key: str,
    default: list[str] | None = None,
) -> list[str]:
    value = rule.get(key, default)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{key} must be an array of non-empty strings")
    return value


def require_bool(rule: dict[str, Any], key: str, default: bool = False) -> bool:
    value = rule.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def require_non_empty_string_list(rule: dict[str, Any], key: str) -> list[str]:
    value = require_string_list(rule, key)
    if not value:
        raise ValueError(f"{key} must contain at least one string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
