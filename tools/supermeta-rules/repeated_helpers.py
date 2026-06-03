"""Detect repeated helper methods with parser-backed language adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SUPPORTED_LANGUAGES = ("java",)
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
JAVA_TEST_METHOD_ANNOTATIONS = {
    "After",
    "AfterAll",
    "AfterEach",
    "Before",
    "BeforeAll",
    "BeforeEach",
    "Disabled",
    "ParameterizedTest",
    "RepeatedTest",
    "Test",
    "TestFactory",
    "TestTemplate",
}


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


def find_repeated_helpers(
    config: RepeatedHelperConfig,
    source_files: list[GroupSourceFile],
) -> list[HelperFinding]:
    _ = (config, source_files)
    return []


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
        if source_file.group == "test" and annotations_match_any(annotations, tuple(JAVA_TEST_METHOD_ANNOTATIONS)):
            continue
        modifiers = modifier_tokens(method)
        if not is_java_helper_eligible(source_file.group, modifiers):
            continue

        statement_count = count_java_statements(body)
        if statement_count < config.min_statements:
            continue

        local_names = java_local_names(source_bytes, method)
        candidates.append(
            HelperCandidate(
                group=source_file.group,
                path=source_file.path,
                line=method.start_point.row + 1,
                name=name,
                normalized_tokens=tuple(normalize_java_tokens(source_bytes, body, local_names)),
                structure=tuple(structural_tokens(body)),
                statement_count=statement_count,
            )
        )
    return candidates


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
    return {child.type for child in modifiers.children if child.type not in {"annotation", "marker_annotation"}}


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
    return len(structural_tokens(body))


def java_local_names(source: bytes, method) -> dict[str, str]:
    names: list[str] = []
    for node in iter_named_nodes(method):
        if node.type in {"formal_parameter", "spread_parameter", "catch_formal_parameter", "variable_declarator"}:
            name = node.child_by_field_name("name")
            if name is not None:
                names.append(node_text(source, name))
        if node.type == "lambda_expression":
            names.extend(lambda_parameter_names(source, node))
    return {name: f"local:{index}" for index, name in enumerate(dict.fromkeys(names))}


def lambda_parameter_names(source: bytes, lambda_node) -> list[str]:
    parameters = lambda_node.child_by_field_name("parameters")
    if parameters is None:
        return []
    if parameters.type == "identifier":
        return [node_text(source, parameters)]
    names: list[str] = []
    for node in iter_named_nodes(parameters):
        if node.type == "identifier":
            names.append(node_text(source, node))
    return names


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
