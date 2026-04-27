#!/usr/bin/env python3
"""Build the static GitHub Pages installer surface."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "build" / "pages"
SITE_SOURCE = REPO_ROOT / "site"
TEMPLATE_MANIFEST = "bootstrap-template.json"
PAGES_BASE_URL = "https://jamezz.github.io/codex-bootstrap"
SOURCE_REPOSITORY = "https://github.com/Jamezz/codex-bootstrap.git"
DEFAULT_TEMPLATE = "java-gradle-cli"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    output = args.output.resolve()
    build_pages(output)
    print(f"Built GitHub Pages site at {output}")
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the Codex Bootstrap Pages site.")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output directory. Defaults to {DEFAULT_OUTPUT}.",
    )
    return parser.parse_args(argv)


def build_pages(output: Path) -> None:
    if not SITE_SOURCE.is_dir():
        raise FileNotFoundError(f"missing site source: {SITE_SOURCE}")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    for source in sorted(SITE_SOURCE.iterdir()):
        if source.is_file():
            shutil.copy2(source, output / source.name)

    templates_json = build_templates_payload()
    (output / "templates.json").write_text(
        json.dumps(templates_json, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    write_checksums(output)


def build_templates_payload() -> dict[str, Any]:
    templates = []
    for manifest_path in sorted((REPO_ROOT / "templates").glob(f"*/{TEMPLATE_MANIFEST}")):
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        templates.append(
            {
                "id": require_string(raw, "id", manifest_path),
                "displayName": require_string(raw, "displayName", manifest_path),
                "description": require_string(raw, "description", manifest_path),
                "type": require_string(raw, "type", manifest_path),
                "requiredInputs": require_string_list(raw, "requiredInputs", manifest_path),
                "verificationCommands": require_string_list(
                    raw, "verificationCommands", manifest_path
                ),
            }
        )

    if not templates:
        raise ValueError("no template manifests found")

    return {
        "defaultTemplate": DEFAULT_TEMPLATE,
        "installUrl": f"{PAGES_BASE_URL}/install.sh",
        "pagesUrl": PAGES_BASE_URL,
        "sourceRepository": SOURCE_REPOSITORY,
        "templates": templates,
    }


def require_string(raw: dict[str, Any], key: str, path: Path) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path}: expected non-empty string field {key}")
    return value


def require_string_list(raw: dict[str, Any], key: str, path: Path) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path}: expected string list field {key}")
    return value


def write_checksums(output: Path) -> None:
    checksummed = ["index.html", "install.sh", "templates.json"]
    lines = []
    for name in checksummed:
        path = output / name
        if not path.is_file():
            raise FileNotFoundError(f"missing Pages artifact: {path}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(f"{digest}  {name}")

    (output / "install.sh.sha256").write_text(
        next(line for line in lines if line.endswith("  install.sh")) + "\n",
        encoding="utf-8",
    )
    (output / "checksums.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
