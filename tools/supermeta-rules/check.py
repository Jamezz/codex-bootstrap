#!/usr/bin/env python3
"""Run simple Supermeta rules for bootstrap templates."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import math
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, TextIO

import cache as rule_cache
import repeated_helpers
import workspace


DOMAIN_SPLIT_WARNING = (
    "Do not satisfy this by creating numbered split files. "
    "Refactor with real, concrete, appropriate domain separation: split around "
    "coherent responsibilities and use names that describe the domain boundary."
)
STRUCTURAL_POLICY_RULE_KEYS = frozenset(
    {
        "java_import_style",
        "java_lombok_boilerplate",
        "java_package_class_count",
        "javascript_package_file_count",
        "line_count",
        "repeated_helper_methods",
        "rust_module_item_count",
        "rust_panic_boundary",
    }
)
KNOWN_RULE_KEYS = STRUCTURAL_POLICY_RULE_KEYS | frozenset({"project_callouts", "source_policy_coverage"})
SOURCE_POLICY_FILENAMES = frozenset({"CMakeLists.txt", "Dockerfile", "Makefile"})
SOURCE_POLICY_EXTENSIONS = frozenset(
    {
        ".bat",
        ".bash",
        ".c",
        ".cc",
        ".cjs",
        ".cmake",
        ".cpp",
        ".css",
        ".g4",
        ".gradle",
        ".groovy",
        ".h",
        ".hpp",
        ".html",
        ".java",
        ".js",
        ".jsx",
        ".kt",
        ".kts",
        ".mjs",
        ".proto",
        ".ps1",
        ".py",
        ".rs",
        ".scss",
        ".sh",
        ".sql",
        ".swift",
        ".ts",
        ".tsx",
        ".zsh",
    }
)


@dataclass(frozen=True)
class Finding:
    rule: str
    path: Path
    message: str
    severity: str = "error"
    fixability: str = "notify-only"
    repair_hint: str = ""


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
class JavaConstructorUsage:
    target: str
    kind: str
    start: int


@dataclass(frozen=True)
class JavaSourceContext:
    relative_path: Path
    source: str
    class_blocks: list[JavaClassBlock]
    package_name: str
    explicit_imports: frozenset[str]
    wildcard_imports: frozenset[str]
    declared_record_names: frozenset[str]
    constructor_usages: tuple[JavaConstructorUsage, ...]


@dataclass(frozen=True)
class JavaMethodBlock:
    name: str
    return_type: str
    params: str
    body: str
    start: int
    end: int
    annotations: tuple[str, ...]


@dataclass
class FileSnapshot:
    relative_path: Path
    source_bytes: bytes
    digest: str
    _source_text: str | None = None

    def source_text(self) -> str:
        if self._source_text is None:
            self._source_text = self.source_bytes.decode("utf-8")
        return self._source_text


@dataclass(frozen=True)
class JavaSourceFacts:
    stripped_source: str
    class_blocks: list[JavaClassBlock]
    package_name: str
    explicit_imports: frozenset[str]
    wildcard_imports: frozenset[str]
    normalized_imports: tuple[str, ...]
    top_level_type_names: tuple[str, ...]
    constructor_usages: tuple[JavaConstructorUsage, ...]


class RuleProgress:
    def __init__(
        self,
        stream: TextIO,
        file_interval: int = 100,
        time_interval_seconds: float = 10.0,
    ) -> None:
        self.stream = stream
        self.file_interval = file_interval
        self.time_interval_seconds = time_interval_seconds
        self.last_emit = 0.0

    def rule_start(self, rule_name: str, paths: list[str], include: list[str]) -> None:
        self.emit(
            f"supermeta-rules: {rule_name}: scanning paths={format_patterns(paths)} "
            f"include={format_patterns(include)}",
            force=True,
        )

    def file(self, rule_name: str, relative_path: Path, count: int) -> None:
        now = time.monotonic()
        if count == 1 or count % self.file_interval == 0 or now - self.last_emit >= self.time_interval_seconds:
            self.emit(
                f"supermeta-rules: {rule_name}: scanned {count} files; latest={relative_path}",
                force=True,
                now=now,
            )

    def finding(self, finding: Finding) -> None:
        self.emit(
            f"supermeta-rules: finding [{finding.rule}] {finding.path}: {finding.message}",
            force=True,
        )

    def rule_end(self, rule_name: str, count: int) -> None:
        self.emit(f"supermeta-rules: {rule_name}: scanned {count} matching files", force=True)

    def scan_mode(self, working_set: workspace.WorkingSet) -> None:
        self.emit(f"supermeta-rules: {working_set.mode} scan: {working_set.reason}", force=True)

    def cache_report(self, stats: rule_cache.CacheStats) -> None:
        self.emit(f"supermeta-rules: {stats.summary()}", force=True)

    def emit(self, message: str, force: bool = False, now: float | None = None) -> None:
        timestamp = time.monotonic() if now is None else now
        if force or timestamp - self.last_emit >= self.time_interval_seconds:
            print(message, file=self.stream, flush=True)
            self.last_emit = timestamp


class RuleScanContext:
    def __init__(
        self,
        root: Path,
        working_set: workspace.WorkingSet,
        analysis_cache: rule_cache.RuleAnalysisCache | None = None,
        cache_file: Path | None = None,
        cache_enabled: bool = False,
        config_fingerprint: str = "",
        tool_fingerprint: str = "",
    ) -> None:
        self.root = root
        self.working_set = working_set
        self.file_match_cache: dict[tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], bool], list[Path]] = {}
        self.analysis_cache = analysis_cache
        self.cache_file = cache_file
        self.cache_enabled = cache_enabled and analysis_cache is not None
        self.config_fingerprint = config_fingerprint
        self.tool_fingerprint = tool_fingerprint
        self.file_digests: dict[Path, str] = {}
        self.file_snapshots: dict[Path, FileSnapshot] = {}
        self.seen_files: set[Path] = set()

    def iter_matching_files(
        self,
        paths: list[str],
        include: list[str],
        exclude: list[str],
        narrow_to_working_set: bool,
    ) -> Iterator[Path]:
        use_working_set = narrow_to_working_set and self.working_set.narrows_scan()
        key = (tuple(paths), tuple(include), tuple(exclude), use_working_set)
        cached = self.file_match_cache.get(key)
        if cached is not None:
            for source_file in cached:
                self.seen_files.add(source_file.relative_to(self.root))
                yield source_file
            return

        matches: list[Path] = []
        self.file_match_cache[key] = matches
        source = (
            iter_matching_changed_files(self.root, self.working_set.files, paths, include, exclude)
            if use_working_set
            else iter_matching_files(self.root, paths, include, exclude, prefer_git_visible=True)
        )
        for source_file in source:
            self.seen_files.add(source_file.relative_to(self.root))
            matches.append(source_file)
            yield source_file

    def repeated_helper_candidates(
        self,
        config: repeated_helpers.RepeatedHelperConfig,
        group: str,
        source_file: Path,
    ) -> list[repeated_helpers.HelperCandidate]:
        relative_path = self.relative_path_for(source_file)
        digest = self.digest_for(relative_path)
        rule_key = f"repeated_helper_methods:{config.name}:{group}"
        cached = (
            self.analysis_cache.lookup(
                relative_path,
                digest,
                rule_key,
                self.config_fingerprint,
                self.tool_fingerprint,
            )
            if self.cache_enabled and self.analysis_cache is not None
            else None
        )
        if cached is not None:
            try:
                return [helper_candidate_from_cache(item) for item in cached]
            except ValueError:
                if self.analysis_cache is not None:
                    self.analysis_cache.stats.stale += 1

        candidates = repeated_helpers.extract_java_helpers(
            config,
            repeated_helpers.GroupSourceFile(
                group=group,
                path=relative_path,
                source=self.source_text_for(relative_path),
            ),
        )
        if self.cache_enabled and self.analysis_cache is not None:
            self.analysis_cache.put(
                relative_path,
                digest,
                rule_key,
                self.config_fingerprint,
                self.tool_fingerprint,
                [helper_candidate_to_cache(candidate) for candidate in candidates],
            )
        return candidates

    def repeated_helper_findings(
        self,
        config: repeated_helpers.RepeatedHelperConfig,
        candidates: list[repeated_helpers.HelperCandidate],
    ) -> list[repeated_helpers.HelperFinding]:
        aggregate_path = Path(".supermeta-cache") / "repeated-helper-findings" / config.name
        self.seen_files.add(aggregate_path)
        candidate_digest = repeated_helper_candidate_digest(candidates)
        cached = (
            self.analysis_cache.lookup(
                aggregate_path,
                candidate_digest,
                f"repeated_helper_findings:{config.name}",
                self.config_fingerprint,
                self.tool_fingerprint,
            )
            if self.cache_enabled and self.analysis_cache is not None
            else None
        )
        if cached is not None:
            try:
                return [helper_finding_from_cache(item) for item in cached]
            except ValueError:
                if self.analysis_cache is not None:
                    self.analysis_cache.stats.stale += 1

        exact_keys = repeated_helpers.exact_duplicate_keys(candidates)
        findings = [
            *repeated_helpers.exact_duplicate_findings(candidates, exact_keys),
            *repeated_helpers.near_duplicate_findings(config, candidates, exact_keys),
        ]
        if self.cache_enabled and self.analysis_cache is not None:
            self.analysis_cache.put(
                aggregate_path,
                candidate_digest,
                f"repeated_helper_findings:{config.name}",
                self.config_fingerprint,
                self.tool_fingerprint,
                [helper_finding_to_cache(finding) for finding in findings],
            )
        return findings

    def line_count(self, path: Path) -> int:
        relative_path = self.relative_path_for(path)
        return self.cached_fact(
            relative_path,
            "line_count:v1",
            lambda: line_count_from_source(self.source_text_for(relative_path)),
            int_from_cache,
        )

    def java_facts(self, path: Path) -> JavaSourceFacts:
        relative_path = self.relative_path_for(path)
        return self.cached_fact(
            relative_path,
            "java_source_facts:v1",
            lambda: compute_java_source_facts(self.source_text_for(relative_path)),
            java_source_facts_from_cache,
            java_source_facts_to_cache,
        )

    def rust_stripped_source(self, path: Path, allow_tests: bool) -> str:
        relative_path = self.relative_path_for(path)
        fact_key = f"rust_stripped_source:v1:allow_tests={allow_tests}"

        def compute() -> str:
            source = self.source_text_for(relative_path)
            test_filtered_source = strip_rust_cfg_test_modules(source) if allow_tests else source
            return strip_rust_comments_and_strings(test_filtered_source)

        return self.cached_fact(relative_path, fact_key, compute, string_from_cache)

    def cached_fact(
        self,
        relative_path: Path,
        fact_key: str,
        compute: Any,
        from_cache: Any,
        to_cache: Any | None = None,
    ) -> Any:
        digest = self.digest_for(relative_path)
        cached = (
            self.analysis_cache.lookup(
                relative_path,
                digest,
                fact_key,
                self.config_fingerprint,
                self.tool_fingerprint,
            )
            if self.cache_enabled and self.analysis_cache is not None
            else None
        )
        if cached is not None:
            try:
                return from_cache(cached)
            except ValueError:
                if self.analysis_cache is not None:
                    self.analysis_cache.stats.stale += 1
        value = compute()
        if self.cache_enabled and self.analysis_cache is not None:
            self.analysis_cache.put(
                relative_path,
                digest,
                fact_key,
                self.config_fingerprint,
                self.tool_fingerprint,
                to_cache(value) if to_cache is not None else value,
            )
        return value

    def digest_for(self, relative_path: Path) -> str:
        relative_path = self.relative_path_for(relative_path)
        cached = self.file_digests.get(relative_path)
        if cached is not None:
            return cached
        digest = self.snapshot_for(relative_path).digest
        self.file_digests[relative_path] = digest
        return digest

    def source_text_for(self, path: Path) -> str:
        return self.snapshot_for(path).source_text()

    def snapshot_for(self, path: Path) -> FileSnapshot:
        relative_path = self.relative_path_for(path)
        cached = self.file_snapshots.get(relative_path)
        if cached is not None:
            return cached
        source_bytes = (self.root / relative_path).read_bytes()
        digest = hashlib.sha256(source_bytes).hexdigest()
        snapshot = FileSnapshot(relative_path=relative_path, source_bytes=source_bytes, digest=digest)
        self.file_snapshots[relative_path] = snapshot
        return snapshot

    def relative_path_for(self, path: Path) -> Path:
        if path.is_absolute():
            return path.resolve().relative_to(self.root)
        return Path(path.as_posix())

    def finish(self, progress: RuleProgress | None = None, cache_report: bool = False) -> None:
        if not self.cache_enabled or self.analysis_cache is None or self.cache_file is None:
            return
        self.analysis_cache.evict_missing(self.seen_files)
        self.analysis_cache.write_atomic(self.cache_file)
        if cache_report and progress is not None:
            progress.cache_report(self.analysis_cache.stats)


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
JAVA_CONSTRUCTOR_USAGE_RE = re.compile(
    rf"\bnew\s+{JAVA_NEW_TYPE_ARGS_RE}"
    r"(?P<target>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)"
    rf"\s*{JAVA_CONSTRUCTOR_TYPE_ARGS_RE}\s*\("
)
JAVA_CONSTRUCTOR_REFERENCE_USAGE_RE = re.compile(
    r"(?<![.\w$])"
    r"(?P<target>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)"
    rf"\s*{JAVA_CONSTRUCTOR_TYPE_ARGS_RE}\s*::\s*{JAVA_REFERENCE_TYPE_ARGS_RE}new\b"
)
RUST_ITEM_RE = re.compile(
    r"^\s*(?:pub(?:\([^)]*\))?\s+)?"
    r"(?:async\s+)?(?:unsafe\s+)?"
    r"(?P<kind>fn|struct|enum|trait|type|const|static|mod)\s+"
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)\b",
)
RUST_PANIC_RE = re.compile(r"(?P<pattern>\.(?:unwrap|expect)\s*\(|\b(?:todo|unimplemented|dbg)\s*!)")
RUST_CFG_TEST_RE = re.compile(r"#\s*\[\s*cfg\s*\(\s*test\s*\)\s*\]")
RUST_TEST_MODULE_RE = re.compile(r"\bmod\s+tests\b")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config_path = args.config.resolve()
    root = args.root.resolve() if args.root else config_path.parent

    try:
        config = load_config(config_path)
        progress = RuleProgress(sys.stderr) if progress_is_enabled() else None
        findings = run_rules(
            config,
            root,
            skip_callouts=args.skip_callouts,
            force_full=args.full,
            cache_file=resolve_cache_file(root, args.cache_file),
            no_cache=args.no_cache,
            cache_report=args.cache_report,
            scan_invalidator_paths=relative_paths_under_root(
                root,
                [
                    config_path,
                    Path(__file__),
                    Path(__file__).with_name("workspace.py"),
                    Path(__file__).with_name("repeated_helpers.py"),
                    Path(__file__).with_name("requirements.txt"),
                ],
            ),
            progress=progress,
        )
    except ValueError as error:
        print(f"supermeta-rules: {error}", file=sys.stderr)
        return 2

    errors = [finding for finding in findings if finding.severity == "error"]
    advisories = [finding for finding in findings if finding.severity == "advisory"]
    unknown_severities = sorted({finding.severity for finding in findings} - {"error", "advisory"})
    if unknown_severities:
        print(f"supermeta-rules: unknown finding severities: {', '.join(unknown_severities)}", file=sys.stderr)
        return 2

    if args.json:
        print_json_result(findings, errors, advisories)
        return 1 if errors else 0

    if errors:
        print_findings("Supermeta rule violations:", errors)
        if advisories:
            print_findings("Supermeta rule advisories:", advisories)
        return 1

    if advisories:
        print_findings("Supermeta rule advisories:", advisories)

    print("Supermeta rules passed.")
    return 0


def print_findings(title: str, findings: list[Finding]) -> None:
    print(title)
    for finding in findings:
        print(f"- [{finding.rule}] {finding.path}: {finding.message}")


def print_json_result(findings: list[Finding], errors: list[Finding], advisories: list[Finding]) -> None:
    print(
        json.dumps(
            {
                "schemaVersion": 1,
                "exitCode": 1 if errors else 0,
                "summary": {
                    "findingCount": len(findings),
                    "errorCount": len(errors),
                    "advisoryCount": len(advisories),
                },
                "findings": [finding_payload(finding) for finding in findings],
            },
            indent=2,
            sort_keys=True,
        )
    )


def finding_payload(finding: Finding) -> dict[str, object]:
    return {
        "rule": finding.rule,
        "path": finding.path.as_posix(),
        "message": finding.message,
        "severity": finding.severity,
        "fixability": finding.fixability,
        "repairHint": finding.repair_hint,
    }


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
    parser.add_argument(
        "--full",
        action="store_true",
        help="Disable automatic Git working-set narrowing and scan all matching files.",
    )
    parser.add_argument(
        "--cache-file",
        type=Path,
        help="Persistent source-analysis cache file. Defaults to SUPERMETA_RULES_CACHE_FILE or .gradle/supermeta-rules/cache-v1.json.",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Disable persistent source-analysis cache reads and writes.",
    )
    parser.add_argument(
        "--cache-report",
        action="store_true",
        help="Print source-analysis cache hit/miss stats.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print structured findings with fixability metadata.",
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


def run_rules(
    config: dict[str, Any],
    root: Path,
    skip_callouts: bool = False,
    force_full: bool = False,
    scan_invalidator_paths: tuple[Path, ...] = (),
    progress: RuleProgress | None = None,
    cache_file: Path | None = None,
    no_cache: bool = False,
    cache_report: bool = False,
    tool_fingerprint: str | None = None,
) -> list[Finding]:
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"root directory does not exist: {root}")

    findings: list[Finding] = []
    working_set = workspace.detect_working_set(root, force_full=force_full)
    if working_set.narrows_scan() and scan_invalidators_changed(working_set, scan_invalidator_paths):
        working_set = workspace.full_working_set("scan-control file changed")
    working_set = workspace.apply_periodic_full_scan(root, working_set)
    if progress is not None:
        progress.scan_mode(working_set)
    resolved_cache_file = cache_file.resolve() if cache_file is not None else None
    analysis_cache = None if no_cache or resolved_cache_file is None else rule_cache.load_cache(resolved_cache_file)
    scan_context = RuleScanContext(
        root,
        working_set,
        analysis_cache=analysis_cache,
        cache_file=resolved_cache_file,
        cache_enabled=analysis_cache is not None,
        config_fingerprint=fingerprint_json(config),
        tool_fingerprint=tool_fingerprint or default_tool_fingerprint(root),
    )
    findings.extend(run_line_count_rules(config.get("line_count", []), root, progress=progress, scan_context=scan_context))
    findings.extend(
        run_java_package_class_count_rules(
            config.get("java_package_class_count", []),
            root,
            progress=progress,
            scan_context=scan_context,
        )
    )
    findings.extend(
        run_javascript_package_file_count_rules(
            config.get("javascript_package_file_count", []),
            root,
            progress=progress,
            scan_context=scan_context,
        )
    )
    findings.extend(
        run_java_import_style_rules(
            config.get("java_import_style", []),
            root,
            progress=progress,
            scan_context=scan_context,
        )
    )
    findings.extend(
        run_java_lombok_boilerplate_rules(
            config.get("java_lombok_boilerplate", []),
            root,
            progress=progress,
            scan_context=scan_context,
        )
    )
    findings.extend(
        run_rust_module_item_count_rules(
            config.get("rust_module_item_count", []),
            root,
            progress=progress,
            scan_context=scan_context,
        )
    )
    findings.extend(
        run_rust_panic_boundary_rules(
            config.get("rust_panic_boundary", []),
            root,
            progress=progress,
            scan_context=scan_context,
        )
    )
    findings.extend(
        run_repeated_helper_method_rules(
            config.get("repeated_helper_methods", []),
            root,
            progress=progress,
            scan_context=scan_context,
        )
    )
    findings.extend(
        run_source_policy_coverage_rules(
            config.get("source_policy_coverage", []),
            config,
            root,
            progress=progress,
            scan_context=scan_context,
        )
    )
    findings.extend(
        run_project_callout_rules(
            config.get("project_callouts", []),
            root,
            execute=not project_callouts_are_skipped(skip_callouts),
            progress=progress,
            scan_context=scan_context,
        )
    )

    unknown_rules = sorted(set(config) - KNOWN_RULE_KEYS)
    if unknown_rules:
        raise ValueError(f"unknown rule keys: {', '.join(unknown_rules)}")
    scan_context.finish(progress=progress, cache_report=cache_report)
    return findings


def run_rust_module_item_count_rules(
    rules: Any,
    root: Path,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("rust_module_item_count must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"rust_module_item_count[{index}]")
        if not rule_is_enabled(rule):
            continue
        name = require_string(rule, "name", default=f"rust_module_item_count[{index}]")
        max_items = require_positive_int(rule, "max_items")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.rs"])
        exclude = require_string_list(rule, "exclude", default=[])

        for source_file in iter_rule_files(name, root, paths, include, exclude, progress, scan_context=scan_context):
            stripped_source = (
                scan_context.rust_stripped_source(source_file, allow_tests=False)
                if scan_context is not None
                else strip_rust_comments_and_strings(source_file.read_text(encoding="utf-8"))
            )
            items = top_level_rust_items(stripped_source)
            item_count = len(items)
            if item_count > max_items:
                add_finding(
                    findings,
                    Finding(
                        rule=name,
                        path=source_file.relative_to(root),
                        message=(
                            f"{item_count} Rust top-level items exceeds module limit of {max_items}; "
                            f"{DOMAIN_SPLIT_WARNING}"
                        ),
                    ),
                    progress,
                )

    return findings


def run_rust_panic_boundary_rules(
    rules: Any,
    root: Path,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("rust_panic_boundary must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"rust_panic_boundary[{index}]")
        if not rule_is_enabled(rule):
            continue
        name = require_string(rule, "name", default=f"rust_panic_boundary[{index}]")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.rs"])
        exclude = require_string_list(rule, "exclude", default=[])
        allow_tests = require_boolean(rule, "allow_tests", default=True)

        for source_file in iter_rule_files(name, root, paths, include, exclude, progress, scan_context=scan_context):
            if scan_context is not None:
                scanned_source = scan_context.rust_stripped_source(source_file, allow_tests=allow_tests)
            else:
                source = source_file.read_text(encoding="utf-8")
                test_filtered_source = strip_rust_cfg_test_modules(source) if allow_tests else source
                scanned_source = strip_rust_comments_and_strings(test_filtered_source)
            for match in RUST_PANIC_RE.finditer(scanned_source):
                line = scanned_source.count("\n", 0, match.start()) + 1
                add_finding(
                    findings,
                    Finding(
                        rule=name,
                        path=source_file.relative_to(root),
                        message=(
                            f"panic-prone construct `{match.group('pattern').strip()}` at line {line}; "
                            "return a Result, handle the Option, or isolate panic behavior in tests"
                        ),
                    ),
                    progress,
                )

    return findings


def strip_rust_comments_and_strings(source: str) -> str:
    result: list[str] = []
    index = 0
    block_depth = 0
    in_line_comment = False
    in_string = False
    in_char = False
    while index < len(source):
        current = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""

        if in_line_comment:
            if current == "\n":
                in_line_comment = False
                result.append(current)
            else:
                result.append(" ")
            index += 1
            continue

        if block_depth > 0:
            if current == "/" and following == "*":
                block_depth += 1
                result.extend("  ")
                index += 2
                continue
            if current == "*" and following == "/":
                block_depth -= 1
                result.extend("  ")
                index += 2
                continue
            result.append("\n" if current == "\n" else " ")
            index += 1
            continue

        if in_string:
            if current == "\\":
                result.extend("  ")
                index += 2
                continue
            if current == '"':
                in_string = False
            result.append("\n" if current == "\n" else " ")
            index += 1
            continue

        if in_char:
            if current == "\\":
                result.extend("  ")
                index += 2
                continue
            if current == "'":
                in_char = False
            result.append("\n" if current == "\n" else " ")
            index += 1
            continue

        if current == "/" and following == "/":
            in_line_comment = True
            result.extend("  ")
            index += 2
            continue
        if current == "/" and following == "*":
            block_depth = 1
            result.extend("  ")
            index += 2
            continue
        raw_string_end = rust_raw_string_end(source, index)
        if raw_string_end is not None:
            append_rust_blank(result, source[index:raw_string_end])
            index = raw_string_end
            continue
        if current == '"':
            in_string = True
            result.append(" ")
            index += 1
            continue
        if current == "'" and looks_like_rust_char_literal(source, index):
            in_char = True
            result.append(" ")
            index += 1
            continue

        result.append(current)
        index += 1

    return "".join(result)


def append_rust_blank(result: list[str], text: str) -> None:
    result.extend("\n" if character == "\n" else " " for character in text)


def rust_raw_string_end(source: str, index: int) -> int | None:
    if source.startswith("br", index):
        prefix_length = 2
    elif source[index] == "r":
        prefix_length = 1
    else:
        return None

    delimiter_start = index + prefix_length
    delimiter_end = delimiter_start
    while delimiter_end < len(source) and source[delimiter_end] == "#":
        delimiter_end += 1
    if delimiter_end >= len(source) or source[delimiter_end] != '"':
        return None

    closing_delimiter = '"' + ("#" * (delimiter_end - delimiter_start))
    content_start = delimiter_end + 1
    closing_start = source.find(closing_delimiter, content_start)
    if closing_start == -1:
        return len(source)
    return closing_start + len(closing_delimiter)


def require_boolean(raw_rule: dict[str, Any], key: str, default: bool) -> bool:
    value = raw_rule.get(key, default)
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def looks_like_rust_char_literal(source: str, index: int) -> bool:
    if index + 2 >= len(source):
        return False
    if source[index + 1] == "\\":
        return index + 3 < len(source) and source[index + 3] == "'"
    return source[index + 2] == "'"


def top_level_rust_items(source: str) -> list[str]:
    items: list[str] = []
    brace_depth = 0
    for line in source.splitlines():
        if brace_depth == 0:
            match = RUST_ITEM_RE.match(line)
            if match is not None and match.group("name") != "tests":
                items.append(f"{match.group('kind')} {match.group('name')}")
        brace_depth += line.count("{") - line.count("}")
        brace_depth = max(brace_depth, 0)
    return items


def strip_rust_cfg_test_modules(source: str) -> str:
    lines = source.splitlines(keepends=True)
    structural_lines = strip_rust_comments_and_strings(source).splitlines(keepends=True)
    result: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        structural_line = structural_lines[index]
        if RUST_CFG_TEST_RE.search(structural_line) is None:
            result.append(line)
            index += 1
            continue

        result.append("\n" if line.endswith("\n") else "")
        index += 1
        while index < len(lines) and RUST_TEST_MODULE_RE.search(structural_lines[index]) is None:
            result.append("\n" if lines[index].endswith("\n") else "")
            index += 1
        if index >= len(lines):
            continue

        brace_depth = 0
        module_started = False
        while index < len(lines):
            current_line = lines[index]
            structural_line = structural_lines[index]
            brace_depth += structural_line.count("{") - structural_line.count("}")
            module_started = module_started or "{" in structural_line
            result.append("\n" if current_line.endswith("\n") else "")
            index += 1
            if module_started and brace_depth <= 0:
                break

    return "".join(result)


def run_line_count_rules(
    rules: Any,
    root: Path,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("line_count must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"line_count[{index}]")
        if not rule_is_enabled(rule):
            continue
        name = require_string(rule, "name", default=f"line_count[{index}]")
        max_lines = require_positive_int(rule, "max_lines")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*"])
        exclude = require_string_list(rule, "exclude", default=[])
        narrow_to_working_set = require_bool(rule, "narrow_to_working_set", default=True)

        for source_file in iter_rule_files(
            name,
            root,
            paths,
            include,
            exclude,
            progress,
            scan_context=scan_context,
            narrow_to_working_set=narrow_to_working_set,
        ):
            line_count = scan_context.line_count(source_file) if scan_context is not None else count_lines(source_file)
            if line_count > max_lines:
                add_finding(
                    findings,
                    Finding(
                        rule=name,
                        path=source_file.relative_to(root),
                        message=(
                            f"{line_count} lines exceeds limit of {max_lines}; "
                            f"{DOMAIN_SPLIT_WARNING}"
                        ),
                        repair_hint="Split the file around a real domain boundary.",
                    ),
                    progress,
                )

    return findings


def run_java_package_class_count_rules(
    rules: Any,
    root: Path,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("java_package_class_count must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"java_package_class_count[{index}]")
        if not rule_is_enabled(rule):
            continue
        name = require_string(rule, "name", default=f"java_package_class_count[{index}]")
        max_classes = require_positive_int(rule, "max_classes")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.java"])
        exclude = require_string_list(rule, "exclude", default=[])

        classes_by_package: dict[Path, list[str]] = {}
        for source_file in iter_rule_files(
            name,
            root,
            paths,
            include,
            exclude,
            progress,
            scan_context=scan_context,
            narrow_to_working_set=False,
        ):
            if scan_context is not None:
                type_names = list(scan_context.java_facts(source_file).top_level_type_names)
            else:
                stripped_source = strip_java_comments_and_strings(source_file.read_text(encoding="utf-8"))
                type_names = top_level_java_type_names(stripped_source)
            classes_by_package.setdefault(source_file.parent, []).extend(type_names)

        for package_dir, type_names in sorted(classes_by_package.items()):
            type_count = len(type_names)
            if type_count > max_classes:
                add_finding(
                    findings,
                    Finding(
                        rule=name,
                        path=package_dir.relative_to(root),
                        message=(
                            f"{type_count} Java top-level types exceeds package layer limit "
                            f"of {max_classes}; refactor this layer into cohesive subpackages "
                            "based on the system context"
                        ),
                        repair_hint="Move types into cohesive subpackages instead of applying a mechanical rename.",
                    ),
                    progress,
                )

    return findings


def run_javascript_package_file_count_rules(
    rules: Any,
    root: Path,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("javascript_package_file_count must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"javascript_package_file_count[{index}]")
        if not rule_is_enabled(rule):
            continue
        name = require_string(rule, "name", default=f"javascript_package_file_count[{index}]")
        max_files = require_positive_int(rule, "max_files")
        min_package_depth = require_non_negative_int(rule, "min_package_depth", default=0)
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx"])
        exclude = require_string_list(rule, "exclude", default=[])

        files_by_package: dict[Path, list[Path]] = {}
        for source_file in iter_rule_files(
            name,
            root,
            paths,
            include,
            exclude,
            progress,
            scan_context=scan_context,
            narrow_to_working_set=False,
        ):
            package_depth = javascript_package_depth(source_file, root, paths)
            if package_depth < min_package_depth:
                package_unit = "directory" if min_package_depth == 1 else "directories"
                add_finding(
                    findings,
                    Finding(
                        rule=name,
                        path=source_file.relative_to(root),
                        message=(
                            "JavaScript/TypeScript file is at the package root; "
                            f"nest it at least {min_package_depth} package "
                            f"{package_unit} deep "
                            "using a cohesive domain subpackage"
                        ),
                        repair_hint="Move the file into a cohesive domain subpackage.",
                    ),
                    progress,
                )
            files_by_package.setdefault(source_file.parent, []).append(source_file)

        for package_dir, source_files in sorted(files_by_package.items()):
            file_count = len(source_files)
            if file_count > max_files:
                add_finding(
                    findings,
                    Finding(
                        rule=name,
                        path=package_dir.relative_to(root),
                        message=(
                            f"{file_count} JavaScript/TypeScript files exceeds package layer limit "
                            f"of {max_files}; refactor this layer into cohesive subpackages "
                            "based on the system context"
                        ),
                        repair_hint="Move related files into cohesive subpackages.",
                    ),
                    progress,
                )

    return findings


def javascript_package_depth(source_file: Path, root: Path, paths: list[str]) -> int:
    parent = source_file.parent.resolve()
    depths: list[int] = []
    for configured_path in paths:
        base_path = resolve_under_root(root, configured_path)
        try:
            relative_parent = parent.relative_to(base_path)
        except ValueError:
            continue
        depths.append(len(relative_parent.parts))
    return min(depths) if depths else 0


@dataclass(frozen=True)
class SourcePolicyCoverageSpec:
    rule_type: str
    name: str
    paths: tuple[str, ...]
    include: tuple[str, ...]
    exclude: tuple[str, ...]


def run_source_policy_coverage_rules(
    rules: Any,
    config: dict[str, Any],
    root: Path,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("source_policy_coverage must be an array")

    structural_specs = structural_policy_coverage_specs(config)
    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"source_policy_coverage[{index}]")
        if not rule_is_enabled(rule):
            continue
        name = require_string(rule, "name", default=f"source_policy_coverage[{index}]")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*"])
        exclude = require_string_list(rule, "exclude", default=[])

        for source_file in iter_rule_files(
            name,
            root,
            paths,
            include,
            exclude,
            progress,
            scan_context=scan_context,
            narrow_to_working_set=False,
        ):
            if not is_source_policy_candidate(source_file):
                continue
            if structural_policy_covers_file(root, source_file, structural_specs):
                continue
            add_finding(
                findings,
                Finding(
                    rule=name,
                    path=source_file.relative_to(root),
                    message=(
                        "source file is not covered by an enabled structural Supermeta rule; "
                        "add it to line_count/package/import/repeated-helper policy, or exclude it only "
                        "when it is generated, vendored, or otherwise not first-party source"
                    ),
                    repair_hint="Add structural Supermeta coverage for this source family.",
                ),
                progress,
            )

    return findings


def structural_policy_coverage_specs(config: dict[str, Any]) -> list[SourcePolicyCoverageSpec]:
    specs: list[SourcePolicyCoverageSpec] = []
    for rule_type in sorted(STRUCTURAL_POLICY_RULE_KEYS):
        entries = config.get(rule_type, [])
        if not isinstance(entries, list):
            continue
        if rule_type == "repeated_helper_methods":
            specs.extend(repeated_helper_coverage_specs(entries))
            continue
        for index, raw_rule in enumerate(entries):
            rule = require_object(raw_rule, f"{rule_type}[{index}]")
            if not rule_is_enabled(rule):
                continue
            specs.append(
                SourcePolicyCoverageSpec(
                    rule_type=rule_type,
                    name=require_string(rule, "name", default=rule_type),
                    paths=tuple(require_string_list(rule, "paths")),
                    include=tuple(require_string_list(rule, "include", default=default_include_for_rule(rule_type))),
                    exclude=tuple(require_string_list(rule, "exclude", default=[])),
                )
            )
    return specs


def repeated_helper_coverage_specs(rules: list[Any]) -> list[SourcePolicyCoverageSpec]:
    specs: list[SourcePolicyCoverageSpec] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"repeated_helper_methods[{index}]")
        if not rule_is_enabled(rule):
            continue
        repeated_helper_config = parse_repeated_helper_config(rule, index)
        for group in repeated_helper_config.groups:
            specs.append(
                SourcePolicyCoverageSpec(
                    rule_type="repeated_helper_methods",
                    name=f"{repeated_helper_config.name}:{group.name}",
                    paths=group.paths,
                    include=group.include,
                    exclude=group.exclude,
                )
            )
    return specs


def default_include_for_rule(rule_type: str) -> list[str]:
    if rule_type in {"java_import_style", "java_lombok_boilerplate", "java_package_class_count"}:
        return ["**/*.java"]
    if rule_type == "javascript_package_file_count":
        return ["**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx"]
    if rule_type in {"rust_module_item_count", "rust_panic_boundary"}:
        return ["**/*.rs"]
    return ["**/*"]


def structural_policy_covers_file(root: Path, source_file: Path, specs: list[SourcePolicyCoverageSpec]) -> bool:
    return any(matches_rule_spec(root, source_file, spec.paths, spec.include, spec.exclude) for spec in specs)


def matches_rule_spec(
    root: Path,
    source_file: Path,
    paths: tuple[str, ...],
    include: tuple[str, ...],
    exclude: tuple[str, ...],
) -> bool:
    relative_path = source_file.relative_to(root).as_posix()
    return (
        matches_configured_paths(root, source_file, list(paths))
        and any(fnmatch.fnmatch(relative_path, pattern) for pattern in include)
        and not any(fnmatch.fnmatch(relative_path, pattern) for pattern in exclude)
    )


def is_source_policy_candidate(source_file: Path) -> bool:
    if source_file.name in SOURCE_POLICY_FILENAMES:
        return True
    if source_file.suffix in SOURCE_POLICY_EXTENSIONS:
        return True
    try:
        with source_file.open("rb") as handle:
            return handle.read(2) == b"#!"
    except OSError:
        return False


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
        repeated_helper_config = parse_repeated_helper_config(rule, index)
        candidates: list[repeated_helpers.HelperCandidate] = []
        for group in repeated_helper_config.groups:
            for source_file in iter_rule_files(
                repeated_helper_config.name,
                root,
                list(group.paths),
                list(group.include),
                list(group.exclude),
                progress,
                scan_context=scan_context,
                narrow_to_working_set=False,
            ):
                if scan_context is not None:
                    candidates.extend(scan_context.repeated_helper_candidates(repeated_helper_config, group.name, source_file))
                else:
                    group_source_file = repeated_helpers.GroupSourceFile(
                        group=group.name,
                        path=source_file.relative_to(root),
                        source=source_file.read_text(encoding="utf-8"),
                    )
                    candidates.extend(repeated_helpers.extract_java_helpers(repeated_helper_config, group_source_file))

        if scan_context is not None:
            helper_findings = scan_context.repeated_helper_findings(repeated_helper_config, candidates)
        else:
            exact_keys = repeated_helpers.exact_duplicate_keys(candidates)
            helper_findings = [
                *repeated_helpers.exact_duplicate_findings(candidates, exact_keys),
                *repeated_helpers.near_duplicate_findings(repeated_helper_config, candidates, exact_keys),
            ]
        for finding in helper_findings:
            add_finding(
                findings,
                Finding(
                    rule=repeated_helper_config.name,
                    path=finding.path,
                    message=finding.message,
                    severity=finding.severity,
                    fixability="patch-only",
                    repair_hint="Extract or reuse a shared helper instead of keeping duplicated helper bodies.",
                ),
                progress,
            )

    return findings


def parse_repeated_helper_config(rule: dict[str, Any], index: int) -> repeated_helpers.RepeatedHelperConfig:
    name = require_string(rule, "name", default=f"repeated_helper_methods[{index}]")
    language = require_string(rule, "language")
    if language not in repeated_helpers.SUPPORTED_LANGUAGES:
        raise ValueError(f"language must be one of: {', '.join(repeated_helpers.SUPPORTED_LANGUAGES)}")
    return repeated_helpers.RepeatedHelperConfig(
        name=name,
        language=language,
        groups=parse_repeated_helper_groups(rule),
        min_statements=require_positive_int(rule, "min_statements"),
        near_match_threshold=require_probability(rule, "near_match_threshold"),
        advisory_near_matches=require_bool(rule, "advisory_near_matches", default=True),
        ignore_annotations=tuple(require_string_list(rule, "ignore_annotations", default=[])),
        allow_methods=frozenset(require_string_list(rule, "allow_methods", default=[])),
    )


def parse_repeated_helper_groups(rule: dict[str, Any]) -> tuple[repeated_helpers.SourceGroup, ...]:
    raw_groups = rule.get("groups")
    if not isinstance(raw_groups, list):
        raise ValueError("groups must be an array")
    if not raw_groups:
        raise ValueError("groups must contain at least one group")

    groups: list[repeated_helpers.SourceGroup] = []
    for index, raw_group in enumerate(raw_groups):
        group = require_object(raw_group, f"groups[{index}]")
        groups.append(
            repeated_helpers.SourceGroup(
                name=require_string(group, "name"),
                paths=tuple(require_non_empty_string_list(group, "paths")),
                include=tuple(require_string_list(group, "include", default=["**/*.java"])),
                exclude=tuple(require_string_list(group, "exclude", default=[])),
            )
        )
    return tuple(groups)


def run_java_import_style_rules(
    rules: Any,
    root: Path,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("java_import_style must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"java_import_style[{index}]")
        if not rule_is_enabled(rule):
            continue
        name = require_string(rule, "name", default=f"java_import_style[{index}]")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.java"])
        exclude = require_string_list(rule, "exclude", default=[])
        allow_explicit = set(require_string_list(rule, "allow_explicit", default=[]))

        for source_file in iter_rule_files(name, root, paths, include, exclude, progress, scan_context=scan_context):
            normalized_imports = (
                scan_context.java_facts(source_file).normalized_imports
                if scan_context is not None
                else normalized_java_imports(strip_java_comments_and_strings(source_file.read_text(encoding="utf-8")))
            )
            for normalized in normalized_imports:
                if normalized in allow_explicit or normalized.endswith(".*"):
                    continue
                add_finding(
                    findings,
                    Finding(
                        rule=name,
                        path=source_file.relative_to(root),
                        message=(
                            f"explicit import {normalized}; use "
                            f"{suggest_java_wildcard_import(normalized)} unless allowlisted"
                        ),
                        fixability="auto",
                        repair_hint="Supermeta can rewrite explicit Java imports to the configured wildcard import.",
                    ),
                    progress,
                )

    return findings


def normalize_java_import(line: str) -> str | None:
    match = JAVA_IMPORT_RE.match(line)
    if match is None:
        return None
    prefix = "static " if match.group("static") else ""
    return f"{prefix}{match.group('target')}"


def normalized_java_imports(source: str) -> tuple[str, ...]:
    imports: list[str] = []
    for import_line in source.splitlines():
        normalized = normalize_java_import(import_line)
        if normalized is not None:
            imports.append(normalized)
    return tuple(imports)


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


def run_java_lombok_boilerplate_rules(
    rules: Any,
    root: Path,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("java_lombok_boilerplate must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"java_lombok_boilerplate[{index}]")
        if not rule_is_enabled(rule):
            continue
        name = require_string(rule, "name", default=f"java_lombok_boilerplate[{index}]")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.java"])
        exclude = require_string_list(rule, "exclude", default=[])
        ignore_annotations = tuple(require_string_list(rule, "ignore_annotations", default=[]))
        allow_methods = set(require_string_list(rule, "allow_methods", default=[]))

        source_contexts: list[JavaSourceContext] = []
        record_types: set[JavaRecordType] = set()
        require_record_builder = require_bool(rule, "require_record_builder", default=False)

        for source_file in iter_rule_files(
            name,
            root,
            paths,
            include,
            exclude,
            progress,
            scan_context=scan_context,
            narrow_to_working_set=False,
        ):
            if scan_context is not None:
                facts = scan_context.java_facts(source_file)
                stripped_source = facts.stripped_source
                class_blocks = facts.class_blocks
                package_name = facts.package_name
                explicit_imports = set(facts.explicit_imports)
                wildcard_imports = set(facts.wildcard_imports)
                constructor_usages = facts.constructor_usages
            else:
                stripped_source = strip_java_comments_and_strings(source_file.read_text(encoding="utf-8"))
                class_blocks = iter_java_class_blocks(stripped_source)
                package_name = java_package_name(stripped_source)
                explicit_imports, wildcard_imports = java_imports(stripped_source)
                constructor_usages = java_constructor_usages(stripped_source)
            declared_record_types = java_record_types(package_name, class_blocks, ignore_annotations)
            declared_record_names = {record_type.name for record_type in declared_record_types}
            extend_findings(
                findings,
                find_lombok_method_boilerplate(
                    name,
                    source_file.relative_to(root),
                    stripped_source,
                    class_blocks,
                    ignore_annotations,
                    allow_methods,
                ),
                progress,
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
                    constructor_usages=constructor_usages,
                )
            )
            extend_findings(
                findings,
                find_lombok_builder_boilerplate(
                    name,
                    source_file.relative_to(root),
                    stripped_source,
                    class_blocks,
                    ignore_annotations,
                ),
                progress,
            )
            if require_record_builder:
                extend_findings(
                    findings,
                    find_lombok_record_builder_requirement(
                        name, source_file.relative_to(root), class_blocks, ignore_annotations
                    ),
                    progress,
                )
                record_types.update(declared_record_types)

        if require_record_builder and record_types:
            for source_context in source_contexts:
                extend_findings(
                    findings,
                    find_lombok_record_constructor_calls(
                        name,
                        source_context,
                        ignore_annotations,
                        record_types,
                    ),
                    progress,
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
                    fixability="patch-only",
                    repair_hint="Replace hand-written boilerplate with the appropriate Lombok annotation.",
                )
            )
        elif is_builder_factory(method):
            findings.append(
                Finding(
                    rule=rule_name,
                    path=relative_path,
                    message=f"{method.name}() is Lombok builder boilerplate; {lombok_suggestion(ignore_annotations)}",
                    fixability="patch-only",
                    repair_hint="Replace the hand-written builder factory with Lombok builder support.",
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
                    fixability="patch-only",
                    repair_hint="Replace the builder class with Lombok builder support.",
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
                fixability="patch-only",
                repair_hint="Add Lombok builder support and update constructor call sites deliberately.",
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
    target_messages: dict[tuple[str, str], list[str]] = {}
    accessible_names = accessible_record_names(source_context, record_types)
    for name in sorted(accessible_names):
        target_messages.setdefault(("constructor", name), []).append(
            f"{name} instances should be built with {name}.builder() for readability; "
            f"{lombok_suggestion(ignore_annotations)}"
        )
        target_messages.setdefault(("reference", name), []).append(
            f"{name} constructor references should use {name}.builder() for readability; "
            f"{lombok_suggestion(ignore_annotations)}"
        )
    for record_name, qualified_name in sorted(qualified_record_constructor_targets(source_context, record_types)):
        target_messages.setdefault(("constructor", qualified_name), []).append(
            f"{record_name} instances should be built with {record_name}.builder() for readability; "
            f"{lombok_suggestion(ignore_annotations)}"
        )
        target_messages.setdefault(("reference", qualified_name), []).append(
            f"{record_name} constructor references should use {record_name}.builder() for readability; "
            f"{lombok_suggestion(ignore_annotations)}"
        )
    if not target_messages:
        return []

    for usage in source_context.constructor_usages:
        messages = target_messages.get((usage.kind, usage.target))
        if not messages:
            continue
        if is_position_inside_ignored_class(usage.start, source_context.class_blocks, ignore_annotations):
            continue
        for message in messages:
            findings.append(
                Finding(
                    rule=rule_name,
                    path=source_context.relative_path,
                    message=message,
                    fixability="patch-only",
                    repair_hint="Convert constructor call sites to builder calls with source review.",
                )
            )
    return findings


def java_constructor_usages(source: str) -> tuple[JavaConstructorUsage, ...]:
    usages: list[JavaConstructorUsage] = []
    for match in JAVA_CONSTRUCTOR_USAGE_RE.finditer(source):
        usages.append(JavaConstructorUsage(target=match.group("target"), kind="constructor", start=match.start()))
    for match in JAVA_CONSTRUCTOR_REFERENCE_USAGE_RE.finditer(source):
        usages.append(JavaConstructorUsage(target=match.group("target"), kind="reference", start=match.start()))
    return tuple(sorted(usages, key=lambda usage: (usage.start, usage.kind, usage.target)))


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


def run_project_callout_rules(
    rules: Any,
    root: Path,
    execute: bool = True,
    progress: RuleProgress | None = None,
    scan_context: RuleScanContext | None = None,
) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("project_callouts must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"project_callouts[{index}]")
        if not rule_is_enabled(rule):
            continue
        name = require_string(rule, "name", default=f"project_callouts[{index}]")
        language = require_string(rule, "language")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*"])
        exclude = require_string_list(rule, "exclude", default=[])
        command = require_non_empty_string_list(rule, "command")

        if not execute:
            continue
        if progress is not None:
            progress.rule_start(name, paths, include)
        has_match = has_matching_file(root, paths, include, exclude, scan_context=scan_context)
        if progress is not None:
            progress.rule_end(name, 1 if has_match else 0)
        if not has_match:
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
            add_finding(
                findings,
                Finding(
                    rule=name,
                    path=Path("."),
                    message=f"{language} callout could not start: {shlex.join(command)}\n{error}",
                ),
                progress,
            )
            continue
        if result.returncode != 0:
            add_finding(
                findings,
                Finding(
                    rule=name,
                    path=Path("."),
                    message=(
                        f"{language} callout failed with exit {result.returncode}: "
                        f"{shlex.join(command)}\n{trim_output(result.stdout)}"
                    ),
                ),
                progress,
            )

    return findings


def project_callouts_are_skipped(skip_callouts: bool) -> bool:
    return skip_callouts or os.environ.get("SUPERMETA_SKIP_PROJECT_CALLOUTS") in {
        "1",
        "true",
        "yes",
    }


def progress_is_enabled() -> bool:
    return os.environ.get("SUPERMETA_RULES_QUIET") not in {"1", "true", "yes"}


def resolve_cache_file(root: Path, explicit_cache_file: Path | None) -> Path:
    if explicit_cache_file is not None:
        return explicit_cache_file
    env_cache_file = os.environ.get("SUPERMETA_RULES_CACHE_FILE")
    if env_cache_file:
        return Path(env_cache_file)
    return root / ".gradle" / "supermeta-rules" / "cache-v1.json"


def fingerprint_json(data: Any) -> str:
    encoded = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def default_tool_fingerprint(root: Path) -> str:
    paths = [
        Path(__file__),
        Path(__file__).with_name("workspace.py"),
        Path(__file__).with_name("repeated_helpers.py"),
        Path(__file__).with_name("requirements.txt"),
    ]
    digest = hashlib.sha256()
    for path in paths:
        try:
            relative_name = path.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            relative_name = path.name
        digest.update(relative_name.encode("utf-8"))
        digest.update(b"\0")
        if path.is_file():
            digest.update(hash_file(path).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def line_count_from_source(source: str) -> int:
    return len(source.splitlines())


def int_from_cache(data: Any) -> int:
    if isinstance(data, bool) or not isinstance(data, int):
        raise ValueError("cached value is not an integer")
    return data


def string_from_cache(data: Any) -> str:
    if not isinstance(data, str):
        raise ValueError("cached value is not a string")
    return data


def compute_java_source_facts(source: str) -> JavaSourceFacts:
    stripped_source = strip_java_comments_and_strings(source)
    class_blocks = iter_java_class_blocks(stripped_source)
    explicit_imports, wildcard_imports = java_imports(stripped_source)
    return JavaSourceFacts(
        stripped_source=stripped_source,
        class_blocks=class_blocks,
        package_name=java_package_name(stripped_source),
        explicit_imports=frozenset(explicit_imports),
        wildcard_imports=frozenset(wildcard_imports),
        normalized_imports=normalized_java_imports(stripped_source),
        top_level_type_names=tuple(top_level_java_type_names(stripped_source)),
        constructor_usages=java_constructor_usages(stripped_source),
    )


def java_source_facts_to_cache(facts: JavaSourceFacts) -> dict[str, Any]:
    return {
        "strippedSource": facts.stripped_source,
        "classBlocks": [java_class_block_to_cache(block) for block in facts.class_blocks],
        "packageName": facts.package_name,
        "explicitImports": sorted(facts.explicit_imports),
        "wildcardImports": sorted(facts.wildcard_imports),
        "normalizedImports": list(facts.normalized_imports),
        "topLevelTypeNames": list(facts.top_level_type_names),
        "constructorUsages": [java_constructor_usage_to_cache(usage) for usage in facts.constructor_usages],
    }


def java_source_facts_from_cache(data: Any) -> JavaSourceFacts:
    if not isinstance(data, dict):
        raise ValueError("cached Java facts must be an object")
    return JavaSourceFacts(
        stripped_source=required_cached_string(data, "strippedSource"),
        class_blocks=[java_class_block_from_cache(item) for item in required_cached_list(data, "classBlocks")],
        package_name=required_cached_string(data, "packageName"),
        explicit_imports=frozenset(required_cached_string_list(data, "explicitImports")),
        wildcard_imports=frozenset(required_cached_string_list(data, "wildcardImports")),
        normalized_imports=tuple(required_cached_string_list(data, "normalizedImports")),
        top_level_type_names=tuple(required_cached_string_list(data, "topLevelTypeNames")),
        constructor_usages=tuple(
            java_constructor_usage_from_cache(item) for item in required_cached_list(data, "constructorUsages")
        ),
    )


def java_constructor_usage_to_cache(usage: JavaConstructorUsage) -> dict[str, Any]:
    return {
        "target": usage.target,
        "kind": usage.kind,
        "start": usage.start,
    }


def java_constructor_usage_from_cache(data: Any) -> JavaConstructorUsage:
    if not isinstance(data, dict):
        raise ValueError("cached Java constructor usage must be an object")
    kind = required_cached_string(data, "kind")
    if kind not in {"constructor", "reference"}:
        raise ValueError("cached Java constructor usage kind is invalid")
    return JavaConstructorUsage(
        target=required_cached_string(data, "target"),
        kind=kind,
        start=required_cached_int(data, "start"),
    )


def java_class_block_to_cache(block: JavaClassBlock) -> dict[str, Any]:
    return {
        "kind": block.kind,
        "name": block.name,
        "start": block.start,
        "end": block.end,
        "annotations": list(block.annotations),
    }


def java_class_block_from_cache(data: Any) -> JavaClassBlock:
    if not isinstance(data, dict):
        raise ValueError("cached Java class block must be an object")
    return JavaClassBlock(
        kind=required_cached_string(data, "kind"),
        name=required_cached_string(data, "name"),
        start=required_cached_int(data, "start"),
        end=required_cached_int(data, "end"),
        annotations=tuple(required_cached_string_list(data, "annotations")),
    )


def required_cached_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise ValueError(f"cached field {key} must be a string")
    return value


def required_cached_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"cached field {key} must be an integer")
    return value


def required_cached_list(data: dict[str, Any], key: str) -> list[Any]:
    value = data.get(key)
    if not isinstance(value, list):
        raise ValueError(f"cached field {key} must be a list")
    return value


def required_cached_string_list(data: dict[str, Any], key: str) -> list[str]:
    values = required_cached_list(data, key)
    if not all(isinstance(value, str) for value in values):
        raise ValueError(f"cached field {key} must contain strings")
    return values


def helper_candidate_to_cache(candidate: repeated_helpers.HelperCandidate) -> dict[str, Any]:
    return {
        "group": candidate.group,
        "path": candidate.path.as_posix(),
        "line": candidate.line,
        "name": candidate.name,
        "normalizedTokens": list(candidate.normalized_tokens),
        "structure": list(candidate.structure),
        "statementCount": candidate.statement_count,
    }


def repeated_helper_candidate_digest(candidates: list[repeated_helpers.HelperCandidate]) -> str:
    payload = sorted(
        (helper_candidate_to_cache(candidate) for candidate in candidates),
        key=lambda item: (item["group"], item["path"], item["line"], item["name"]),
    )
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def helper_candidate_from_cache(data: Any) -> repeated_helpers.HelperCandidate:
    if not isinstance(data, dict):
        raise ValueError("invalid repeated helper cache entry")
    return repeated_helpers.HelperCandidate(
        group=require_cached_string(data, "group"),
        path=Path(require_cached_string(data, "path")),
        line=require_cached_int(data, "line"),
        name=require_cached_string(data, "name"),
        normalized_tokens=tuple(require_cached_string_list(data, "normalizedTokens")),
        structure=tuple(require_cached_string_list(data, "structure")),
        statement_count=require_cached_int(data, "statementCount"),
    )


def helper_finding_to_cache(finding: repeated_helpers.HelperFinding) -> dict[str, Any]:
    return {
        "path": finding.path.as_posix(),
        "message": finding.message,
        "severity": finding.severity,
    }


def helper_finding_from_cache(data: Any) -> repeated_helpers.HelperFinding:
    if not isinstance(data, dict):
        raise ValueError("invalid repeated helper finding cache entry")
    return repeated_helpers.HelperFinding(
        path=Path(require_cached_string(data, "path")),
        message=require_cached_string(data, "message"),
        severity=require_cached_string(data, "severity"),
    )


def require_cached_string(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"invalid cached helper field: {key}")
    return value


def require_cached_int(data: dict[str, Any], key: str) -> int:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid cached helper field: {key}")
    return value


def require_cached_string_list(data: dict[str, Any], key: str) -> list[str]:
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"invalid cached helper field: {key}")
    return value


def relative_paths_under_root(root: Path, paths: list[Path]) -> tuple[Path, ...]:
    root = root.resolve()
    relatives: list[Path] = []
    for path in paths:
        try:
            relatives.append(path.resolve().relative_to(root))
        except ValueError:
            continue
    return tuple(relatives)


def scan_invalidators_changed(working_set: workspace.WorkingSet, scan_invalidator_paths: tuple[Path, ...]) -> bool:
    changed = {normalize_relative_path(path) for path in working_set.files}
    return any(normalize_relative_path(path) in changed for path in scan_invalidator_paths)


def normalize_relative_path(path: Path) -> str:
    return path.as_posix().strip("/")


def format_patterns(patterns: list[str]) -> str:
    return "[" + ", ".join(patterns) + "]"


def iter_rule_files(
    rule_name: str,
    root: Path,
    paths: list[str],
    include: list[str],
    exclude: list[str],
    progress: RuleProgress | None,
    scan_context: RuleScanContext | None = None,
    narrow_to_working_set: bool = True,
) -> Iterator[Path]:
    if progress is not None:
        progress.rule_start(rule_name, paths, include)

    count = 0
    source_files = (
        scan_context.iter_matching_files(paths, include, exclude, narrow_to_working_set)
        if scan_context is not None
        else iter_matching_files(root, paths, include, exclude)
    )
    for source_file in source_files:
        count += 1
        if progress is not None:
            progress.file(rule_name, source_file.relative_to(root), count)
        yield source_file

    if progress is not None:
        progress.rule_end(rule_name, count)


def add_finding(findings: list[Finding], finding: Finding, progress: RuleProgress | None) -> None:
    findings.append(finding)
    if progress is not None:
        progress.finding(finding)


def extend_findings(
    findings: list[Finding],
    new_findings: list[Finding],
    progress: RuleProgress | None,
) -> None:
    for finding in new_findings:
        add_finding(findings, finding, progress)


def iter_matching_files(
    root: Path,
    paths: list[str],
    include: list[str],
    exclude: list[str],
    prefer_git_visible: bool = False,
) -> Iterator[Path]:
    root = root.resolve()
    if prefer_git_visible:
        git_visible_files = workspace.git_visible_files(root, paths)
        if git_visible_files is not None:
            yield from iter_matching_candidate_files(root, git_visible_files, paths, include, exclude)
            return

    seen: set[Path] = set()
    for configured_path in paths:
        base_path = resolve_under_root(root, configured_path)
        if base_path.is_file():
            candidates = [base_path]
        elif base_path.is_dir():
            candidates = iter_included_files(base_path, configured_path, include)
        else:
            continue

        for candidate in candidates:
            relative_path = candidate.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(relative_path, pattern) for pattern in include) and not any(
                fnmatch.fnmatch(relative_path, pattern) for pattern in exclude
            ):
                if candidate not in seen:
                    seen.add(candidate)
                    yield candidate


def iter_matching_candidate_files(
    root: Path,
    relative_candidates: set[Path],
    paths: list[str],
    include: list[str],
    exclude: list[str],
) -> Iterator[Path]:
    seen: set[Path] = set()
    for relative_candidate in sorted(relative_candidates):
        candidate = resolve_under_root(root, relative_candidate.as_posix())
        if not candidate.is_file() or candidate in seen:
            continue
        relative_path = candidate.relative_to(root).as_posix()
        if not matches_configured_paths(root, candidate, paths):
            continue
        if any(fnmatch.fnmatch(relative_path, pattern) for pattern in include) and not any(
            fnmatch.fnmatch(relative_path, pattern) for pattern in exclude
        ):
            seen.add(candidate)
            yield candidate


def iter_matching_changed_files(
    root: Path,
    changed_files: frozenset[Path],
    paths: list[str],
    include: list[str],
    exclude: list[str],
) -> Iterator[Path]:
    root = root.resolve()
    seen: set[Path] = set()
    for relative_candidate in sorted(changed_files):
        candidate = resolve_under_root(root, relative_candidate.as_posix())
        if not candidate.is_file() or candidate in seen:
            continue
        relative_path = candidate.relative_to(root).as_posix()
        if not matches_configured_paths(root, candidate, paths):
            continue
        if any(fnmatch.fnmatch(relative_path, pattern) for pattern in include) and not any(
            fnmatch.fnmatch(relative_path, pattern) for pattern in exclude
        ):
            seen.add(candidate)
            yield candidate


def iter_included_files(base_path: Path, configured_path: str, include: list[str]) -> Iterator[Path]:
    seen: set[Path] = set()
    for include_pattern in include:
        search_pattern = include_glob_for_base(configured_path, include_pattern)
        if search_pattern is None:
            continue
        for candidate in sorted(base_path.glob(search_pattern)):
            if candidate.is_file() and candidate not in seen:
                seen.add(candidate)
                yield candidate


def has_matching_file(
    root: Path,
    paths: list[str],
    include: list[str],
    exclude: list[str],
    scan_context: RuleScanContext | None = None,
    narrow_to_working_set: bool = True,
) -> bool:
    source_files = (
        scan_context.iter_matching_files(paths, include, exclude, narrow_to_working_set)
        if scan_context is not None
        else iter_matching_files(root, paths, include, exclude)
    )
    return next(source_files, None) is not None


def matches_configured_paths(root: Path, candidate: Path, paths: list[str]) -> bool:
    return any(matches_configured_path(root, candidate, configured_path) for configured_path in paths)


def matches_configured_path(root: Path, candidate: Path, configured_path: str) -> bool:
    base_path = resolve_under_root(root, configured_path)
    if candidate == base_path:
        return True
    try:
        candidate.relative_to(base_path)
    except ValueError:
        return False
    return True


def include_glob_for_base(configured_path: str, include_pattern: str) -> str | None:
    normalized_path = normalize_rule_path(configured_path)
    normalized_pattern = normalize_rule_path(include_pattern)
    if any(part == ".." for part in normalized_pattern.split("/")):
        return None

    if normalized_path:
        path_prefix = f"{normalized_path}/"
        if normalized_pattern.startswith(path_prefix):
            normalized_pattern = normalized_pattern[len(path_prefix) :]
        elif normalized_pattern == normalized_path:
            normalized_pattern = "**/*"

    if not normalized_pattern:
        return "**/*"
    if "/" not in normalized_pattern and any(marker in normalized_pattern for marker in "*?["):
        return f"**/{normalized_pattern}"
    return normalized_pattern


def normalize_rule_path(path: str) -> str:
    normalized = path.replace("\\", "/").strip("/")
    if normalized in {"", "."}:
        return ""
    return normalized


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


def require_non_negative_int(rule: dict[str, Any], key: str, default: int = 0) -> int:
    value = rule.get(key, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{key} must be a non-negative integer")
    return value


def require_probability(rule: dict[str, Any], key: str) -> float:
    value = rule.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{key} must be greater than 0 and at most 1")
    numeric_value = float(value)
    if not math.isfinite(numeric_value) or numeric_value <= 0 or numeric_value > 1:
        raise ValueError(f"{key} must be greater than 0 and at most 1")
    return numeric_value


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


def rule_is_enabled(rule: dict[str, Any]) -> bool:
    return require_bool(rule, "enabled", default=True)


def require_non_empty_string_list(rule: dict[str, Any], key: str) -> list[str]:
    value = require_string_list(rule, key)
    if not value:
        raise ValueError(f"{key} must contain at least one string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
