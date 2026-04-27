#!/usr/bin/env python3
"""Pinned Beans CLI wrapper for generated projects."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys


EXPECTED_VERSION = "0.4.2"
BEANS_REPO_URL = "https://github.com/hmans/beans"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    beans_bin = resolve_beans_binary()
    if beans_bin is None:
        print_install_help("Beans CLI was not found on PATH.")
        return 2

    version_result = subprocess.run(
        [beans_bin, "version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if version_result.returncode != 0:
        print_install_help(
            f"`beans version` failed with exit {version_result.returncode}:\n"
            f"{version_result.stdout.strip()}"
        )
        return 2

    actual_version = parse_version(version_result.stdout)
    if actual_version != EXPECTED_VERSION:
        found = actual_version or version_result.stdout.strip() or "unknown"
        print_install_help(f"Beans CLI {EXPECTED_VERSION} is required; found {found}.")
        return 2

    result = subprocess.run([beans_bin, *args], check=False)
    return result.returncode


def resolve_beans_binary() -> str | None:
    configured = os.environ.get("SUPERMETA_BEANS_BIN")
    if configured:
        return configured if os.path.isfile(configured) and os.access(configured, os.X_OK) else None
    return shutil.which("beans")


def parse_version(output: str) -> str | None:
    match = re.search(r"\bbeans\s+v?([0-9]+(?:\.[0-9]+){2})\b", output)
    if match:
        return match.group(1)
    match = re.search(r"^v?([0-9]+(?:\.[0-9]+){2})\b", output.strip())
    if match:
        return match.group(1)
    return None


def print_install_help(reason: str) -> None:
    print(f"agent-beans: {reason}", file=sys.stderr)
    print(f"agent-beans: install Beans {EXPECTED_VERSION} with one of:", file=sys.stderr)
    print(f"  go install github.com/hmans/beans@v{EXPECTED_VERSION}", file=sys.stderr)
    print("  brew install hmans/beans/beans", file=sys.stderr)
    print(f"agent-beans: releases: {BEANS_REPO_URL}/releases", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
