#!/usr/bin/env python3
"""Pinned Beads CLI wrapper for generated projects."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


EXPECTED_VERSION = "1.1.0"
BEADS_REPO_URL = "https://github.com/gastownhall/beads"
INITIALIZED_DIRS = ("embeddeddolt", "dolt")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    beads_bin = resolve_beads_binary()
    if beads_bin is None:
        print_install_help("Beads CLI `bd` was not found on PATH.")
        return 2

    version_result = run([beads_bin, "version"])
    if version_result.returncode != 0:
        print_install_help(
            f"`bd version` failed with exit {version_result.returncode}:\n"
            f"{version_result.stdout.strip()}"
        )
        return 2

    actual_version = parse_version(version_result.stdout)
    if actual_version != EXPECTED_VERSION:
        found = actual_version or version_result.stdout.strip() or "unknown"
        print_install_help(f"Beads CLI {EXPECTED_VERSION} is required; found {found}.")
        return 2

    if args and args[0] == "version":
        return forward(beads_bin, args)

    root = repository_root()
    initialization_error = ensure_initialized(beads_bin, root)
    if initialization_error is not None:
        return initialization_error
    return forward(beads_bin, args, cwd=root)


def ensure_initialized(beads_bin: str, root: Path) -> int | None:
    beads_dir = root / ".beads"
    if any((beads_dir / name).exists() for name in INITIALIZED_DIRS):
        return None
    issues = beads_dir / "issues.jsonl"
    if not issues.is_file():
        print(
            "agent-beads: no local Beads database or tracked .beads/issues.jsonl was found",
            file=sys.stderr,
        )
        return 2
    env = dict(os.environ)
    env.setdefault("BEADS_ACTOR", "codex-bootstrap")
    result = run(
        [
            beads_bin,
            "init",
            "--init-if-missing",
            "--from-jsonl",
            "--non-interactive",
            "--skip-agents",
            "--skip-hooks",
            "--quiet",
        ],
        cwd=root,
        env=env,
    )
    if result.returncode != 0:
        print(
            f"agent-beads: first-use initialization failed with exit {result.returncode}:\n"
            f"{result.stdout.strip()}",
            file=sys.stderr,
        )
        return result.returncode or 2
    return None


def run(
    command: list[str], cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )


def forward(beads_bin: str, args: list[str], cwd: Path | None = None) -> int:
    return subprocess.run([beads_bin, *args], cwd=cwd, check=False).returncode


def repository_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_beads_binary() -> str | None:
    configured = os.environ.get("SUPERMETA_BEADS_BIN")
    if configured:
        return configured if os.path.isfile(configured) and os.access(configured, os.X_OK) else None
    return shutil.which("bd")


def parse_version(output: str) -> str | None:
    match = re.search(r"\bbd\s+version\s+v?([0-9]+(?:\.[0-9]+){2})\b", output)
    if match:
        return match.group(1)
    match = re.search(r"\b(?:beads|bd)\s+v?([0-9]+(?:\.[0-9]+){2})\b", output)
    return match.group(1) if match else None


def print_install_help(reason: str) -> None:
    print(f"agent-beads: {reason}", file=sys.stderr)
    print(f"agent-beads: install Beads {EXPECTED_VERSION} with one of:", file=sys.stderr)
    print("  brew install beads", file=sys.stderr)
    print(f"  npm install -g @beads/bd@{EXPECTED_VERSION}", file=sys.stderr)
    print(f"  bun install -g --trust @beads/bd@{EXPECTED_VERSION}", file=sys.stderr)
    print(f"  PowerShell: irm {BEADS_REPO_URL}/raw/v{EXPECTED_VERSION}/install.ps1 | iex", file=sys.stderr)
    print(f"agent-beads: releases: {BEADS_REPO_URL}/releases/tag/v{EXPECTED_VERSION}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
