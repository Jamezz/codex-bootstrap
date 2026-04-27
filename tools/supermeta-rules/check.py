#!/usr/bin/env python3
"""Run simple Supermeta rules for bootstrap templates."""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
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
    findings.extend(run_java_package_file_count_rules(config.get("java_package_file_count", []), root))
    findings.extend(
        run_project_callout_rules(
            config.get("project_callouts", []),
            root,
            execute=not project_callouts_are_skipped(skip_callouts),
        )
    )

    unknown_rules = sorted(set(config) - {"java_package_file_count", "line_count", "project_callouts"})
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


def run_java_package_file_count_rules(rules: Any, root: Path) -> list[Finding]:
    if not isinstance(rules, list):
        raise ValueError("java_package_file_count must be an array")

    findings: list[Finding] = []
    for index, raw_rule in enumerate(rules):
        rule = require_object(raw_rule, f"java_package_file_count[{index}]")
        name = require_string(rule, "name", default=f"java_package_file_count[{index}]")
        max_files = require_positive_int(rule, "max_files")
        paths = require_string_list(rule, "paths")
        include = require_string_list(rule, "include", default=["**/*.java"])
        exclude = require_string_list(rule, "exclude", default=[])

        files_by_package: dict[Path, list[Path]] = {}
        for source_file in iter_matching_files(root, paths, include, exclude):
            files_by_package.setdefault(source_file.parent, []).append(source_file)

        for package_dir, source_files in sorted(files_by_package.items()):
            if len(source_files) > max_files:
                findings.append(
                    Finding(
                        rule=name,
                        path=package_dir.relative_to(root),
                        message=(
                            f"{len(source_files)} Java source files exceeds package limit "
                            f"of {max_files}; split the package into subpackages"
                        ),
                    )
                )

    return findings


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


def require_non_empty_string_list(rule: dict[str, Any], key: str) -> list[str]:
    value = require_string_list(rule, key)
    if not value:
        raise ValueError(f"{key} must contain at least one string")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
