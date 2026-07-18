#!/usr/bin/env python3
"""Non-destructive Bootstrap control-plane adoption for existing repositories."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 2
DEFAULT_TEMPLATE = "existing-repo-control"
MANIFEST_NAME = "bootstrap-template.json"
SYNC_METADATA = Path(".codex-bootstrap/sync.json")
IGNORED_COPY_NAMES = {
    ".bun",
    ".dotnet",
    ".gradle",
    ".mypy_cache",
    ".nuget",
    ".pytest_cache",
    ".ruff_cache",
    ".tsbuildinfo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
}


class AdoptError(Exception):
    """Raised for user-facing adoption failures."""


@dataclass(frozen=True)
class CopyPlanItem:
    source: Path
    destination: Path
    display_path: str
    mode: int


@dataclass(frozen=True)
class AdoptPlan:
    target: Path
    template_id: str
    project_name: str
    copy_items: tuple[CopyPlanItem, ...]
    generated_files: dict[str, str]
    conflicts: tuple[str, ...]
    verification_commands: tuple[str, ...]

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        catalog_root = resolve_catalog_root(args.source_dir)
        target = args.target.resolve()
        manifest = load_manifest(catalog_root, args.template)
        project_name = args.name or target.name
        validate_project_name(project_name)
        verification_commands = tuple(args.verification_command) or tuple(
            manifest.get("verificationCommands", [])
        )
        plan = build_adopt_plan(
            catalog_root=catalog_root,
            target=target,
            manifest=manifest,
            project_name=project_name,
            repository=args.repository,
            source_ref=args.source_ref,
            source_commit=args.source_commit,
            verification_commands=verification_commands,
            force=args.force,
        )
        print_plan(plan, apply=args.apply)
        if plan.has_conflicts:
            return 1
        if args.apply:
            apply_plan(plan)
        return 0
    except AdoptError as error:
        print(f"agent-bootstrap adopt: {error}", file=sys.stderr)
        return 2


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Adopt an existing repository into the Codex Bootstrap control plane."
    )
    parser.add_argument("--target", type=Path, required=True, help="Existing repository root to adopt.")
    parser.add_argument("--name", help="Project slug for sync metadata. Defaults to target directory name.")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help=f"Control-plane template id. Defaults to {DEFAULT_TEMPLATE}.")
    parser.add_argument("--source-dir", type=Path, help="Codex Bootstrap catalog checkout. Defaults to this script's checkout.")
    parser.add_argument("--source-ref", help="Source ref to record in sync metadata. Defaults to the catalog branch.")
    parser.add_argument("--source-commit", help="Source commit to record in sync metadata. Defaults to catalog HEAD.")
    parser.add_argument("--repository", help="Source repository URL to record in sync metadata. Defaults to catalog origin URL.")
    parser.add_argument(
        "--verification-command",
        action="append",
        default=[],
        help="Project verification command to record. Repeatable; shell-style strings are preserved in sync metadata.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite conflicting managed files.")
    parser.add_argument("--apply", action="store_true", help="Write files. Without this flag, only print the plan.")
    return parser.parse_args(argv)


def resolve_catalog_root(source_dir: Path | None) -> Path:
    if source_dir is not None:
        root = source_dir.resolve()
    else:
        root = Path(__file__).resolve().parents[2]
    if not (root / "templates").is_dir() or not (root / "scripts" / "agent-bootstrap").is_file():
        raise AdoptError(f"not a codex-bootstrap catalog checkout: {root}")
    return root


def load_manifest(catalog_root: Path, template_id: str) -> dict[str, Any]:
    manifest_path = catalog_root / "templates" / template_id / MANIFEST_NAME
    if not manifest_path.is_file():
        raise AdoptError(f"unknown adoption template: {template_id}")
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if raw.get("type") != "existing-repo-control":
        raise AdoptError(f"template {template_id} is not an existing-repo-control template")
    return raw


def validate_project_name(value: str) -> None:
    if not value or value.startswith("-") or value.endswith("-") or "--" in value:
        raise AdoptError("project name must be a lowercase hyphenated slug")
    allowed = set("abcdefghijklmnopqrstuvwxyz0123456789-")
    if any(character not in allowed for character in value) or not value[0].isalpha():
        raise AdoptError("project name must be a lowercase hyphenated slug")


def build_adopt_plan(
    catalog_root: Path,
    target: Path,
    manifest: dict[str, Any],
    project_name: str,
    repository: str | None,
    source_ref: str | None,
    source_commit: str | None,
    verification_commands: tuple[str, ...],
    force: bool,
) -> AdoptPlan:
    if not target.is_dir():
        raise AdoptError(f"target repository does not exist: {target}")
    if target.parent == target or len(target.parts) < 3:
        raise AdoptError(f"refusing unsafe target path: {target}")
    if (target / SYNC_METADATA).exists() and not force:
        raise AdoptError(f"{SYNC_METADATA} already exists; use --force to refresh adoption files")

    copy_items = collect_support_files(catalog_root, manifest, target)
    generated_files = generated_control_files(
        catalog_root=catalog_root,
        target=target,
        manifest=manifest,
        project_name=project_name,
        repository=repository,
        source_ref=source_ref,
        source_commit=source_commit,
        verification_commands=verification_commands,
    )
    conflicts = detect_conflicts(target, copy_items, generated_files, force=force)
    return AdoptPlan(
        target=target,
        template_id=str(manifest["id"]),
        project_name=project_name,
        copy_items=tuple(copy_items),
        generated_files=generated_files,
        conflicts=tuple(conflicts),
        verification_commands=verification_commands,
    )


def collect_support_files(catalog_root: Path, manifest: dict[str, Any], target: Path) -> list[CopyPlanItem]:
    items: list[CopyPlanItem] = []
    for support in manifest.get("supportPaths", []):
        source = (catalog_root / support["source"]).resolve()
        destination = target / support["destination"]
        if source.is_dir():
            for child in sorted(source.rglob("*")):
                if not child.is_file() or ignored(child):
                    continue
                relative = child.relative_to(source)
                items.append(
                    CopyPlanItem(
                        source=child,
                        destination=destination / relative,
                        display_path=normalize(destination.relative_to(target) / relative),
                        mode=child.stat().st_mode & 0o777,
                    )
                )
        elif source.is_file():
            items.append(
                CopyPlanItem(
                    source=source,
                    destination=destination,
                    display_path=normalize(destination.relative_to(target)),
                    mode=source.stat().st_mode & 0o777,
                )
            )
        else:
            raise AdoptError(f"support path does not exist: {support['source']}")
    return items


def ignored(path: Path) -> bool:
    return any(part in IGNORED_COPY_NAMES for part in path.parts)


def generated_control_files(
    catalog_root: Path,
    target: Path,
    manifest: dict[str, Any],
    project_name: str,
    repository: str | None,
    source_ref: str | None,
    source_commit: str | None,
    verification_commands: tuple[str, ...],
) -> dict[str, str]:
    files: dict[str, str] = {
        ".codex-bootstrap/reports/.gitignore": "*\n!.gitignore\n",
        ".codex-bootstrap/nags.json": default_nag_policy_json(),
        ".codex-bootstrap/nags.local.json": '{\n  "nags": [],\n  "schemaVersion": 1\n}\n',
        ".codex-bootstrap/checks.json": json.dumps(
            default_checks_policy(str(manifest["id"]), verification_commands),
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    if not (target / ".beads").exists():
        files.update(
            {
                ".beads/.gitignore": "dolt/\nembeddeddolt/\n*.lock\n.local_version\nlast-touched\nexport-state.json\nexport-state/\nbackup/\n",
                ".beads/README.md": "# Beads Workspace\n\nRun `./scripts/agent-beads prime` before substantial work.\n",
                ".beads/config.yaml": f"issue-prefix: {project_name}\nexport:\n  auto: true\n  git-add: true\n",
                ".beads/interactions.jsonl": "",
                ".beads/issues.jsonl": "",
                ".beads/metadata.json": json.dumps(
                    {
                        "backend": "dolt",
                        "database": "dolt",
                        "dolt_database": project_name.replace("-", "_"),
                        "dolt_mode": "embedded",
                        "project_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"codex-bootstrap:{project_name}")),
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
            }
        )
    metadata = sync_metadata(
        catalog_root=catalog_root,
        target=target,
        manifest=manifest,
        project_name=project_name,
        repository=repository,
        source_ref=source_ref,
        source_commit=source_commit,
        verification_commands=verification_commands,
        generated_files=files,
    )
    files[str(SYNC_METADATA)] = json.dumps(metadata, indent=2, sort_keys=True) + "\n"
    return files


def sync_metadata(
    catalog_root: Path,
    target: Path,
    manifest: dict[str, Any],
    project_name: str,
    repository: str | None,
    source_ref: str | None,
    source_commit: str | None,
    verification_commands: tuple[str, ...],
    generated_files: dict[str, str],
) -> dict[str, Any]:
    contract = manifest["syncContract"]
    managed_files = managed_file_hashes(catalog_root, target, manifest, generated_files)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "source": {
            "repository": repository or git_output(catalog_root, ["git", "config", "--get", "remote.origin.url"], "local"),
            "ref": source_ref or git_output(catalog_root, ["git", "branch", "--show-current"], "main"),
            "commit": source_commit or git_output(catalog_root, ["git", "rev-parse", "HEAD"], "unknown"),
        },
        "template": {
            "id": manifest["id"],
            "contractVersion": contract["version"],
        },
        "identity": {"projectName": project_name},
        "managedSets": sorted(item["id"] for item in contract["managedSets"] if item.get("autoEnable", True)),
        "optOut": [],
        "managedFiles": managed_files,
        "managedRegions": {},
        "verificationCommands": list(verification_commands),
        "appliedMigrations": ["beans-to-beads-v1"],
    }


def managed_file_hashes(
    catalog_root: Path,
    target: Path,
    manifest: dict[str, Any],
    generated_files: dict[str, str],
) -> dict[str, dict[str, str]]:
    managed: dict[str, dict[str, str]] = {}
    for managed_set in manifest["syncContract"]["managedSets"]:
        set_id = managed_set["id"]
        if not managed_set.get("autoEnable", True):
            continue
        for file_spec in managed_set.get("files", []):
            path = normalize(Path(file_spec["path"]))
            if path in generated_files:
                digest = sha256_text(generated_files[path])
            else:
                source = source_for_managed_path(catalog_root, target, manifest, path)
                if source is None:
                    continue
                digest = sha256_bytes(source.read_bytes())
            managed[path] = {"set": set_id, "sha256": digest}
    return managed


def source_for_managed_path(catalog_root: Path, target: Path, manifest: dict[str, Any], path: str) -> Path | None:
    for support in manifest.get("supportPaths", []):
        destination = Path(support["destination"])
        source = catalog_root / support["source"]
        managed_path = Path(path)
        try:
            relative = managed_path.relative_to(destination)
        except ValueError:
            continue
        candidate = source / relative if source.is_dir() else source
        if candidate.is_file():
            return candidate
    candidate = target / path
    return candidate if candidate.is_file() else None


def detect_conflicts(
    target: Path,
    copy_items: list[CopyPlanItem],
    generated_files: dict[str, str],
    force: bool,
) -> list[str]:
    if force:
        return []
    conflicts: list[str] = []
    for item in copy_items:
        if item.destination.exists() and item.destination.read_bytes() != item.source.read_bytes():
            conflicts.append(f"{item.display_path} already exists with different content")
    for path, text in generated_files.items():
        destination = target / path
        if destination.exists() and destination.read_text(encoding="utf-8") != text:
            conflicts.append(f"{path} already exists with different content")
    return conflicts


def print_plan(plan: AdoptPlan, apply: bool) -> None:
    print("Bootstrap adoption plan:")
    print(f"  target: {plan.target}")
    print(f"  template: {plan.template_id}")
    print(f"  project: {plan.project_name}")
    for item in plan.copy_items:
        print(f"  copy-file: {item.display_path}")
    for path in sorted(plan.generated_files):
        print(f"  write-file: {path}")
    for command in plan.verification_commands:
        print(f"  verify: {command}")
    for conflict in plan.conflicts:
        print(f"  conflict: {conflict}")
    print(f"  action: {'apply adoption' if apply else 'dry-run only'}")


def apply_plan(plan: AdoptPlan) -> None:
    for item in plan.copy_items:
        item.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item.source, item.destination)
        os.chmod(item.destination, item.mode)
    for path, text in plan.generated_files.items():
        destination = plan.target / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text, encoding="utf-8")


def default_checks_policy(template_id: str, verification_commands: tuple[str, ...]) -> dict[str, Any]:
    commands = [shlex.split(command) for command in verification_commands]
    return {
        "schemaVersion": 1,
        "templateId": template_id,
        "lanes": [
            {
                "id": "full",
                "description": "Project-specific full verification for this adopted repository.",
                "cost": "full",
                "tags": ["full"],
                "requires": [],
                "timeoutSeconds": 1800,
                "commands": commands,
            }
        ],
    }


def default_nag_policy_json() -> str:
    return """{
  "nags": [
    {
      "action": "check-bootstrap-update",
      "cadence": "24h",
      "enabled": true,
      "hook": "session-start",
      "id": "bootstrap-update-check",
      "message": "A newer Codex Bootstrap version is available. Run sync when convenient."
    },
    {
      "action": "suggest-command",
      "cadence": "per-run",
      "commands": [["./scripts/agent-beads", "ready", "--json"]],
      "enabled": true,
      "hook": "post-run",
      "id": "post-run-backlog-check",
      "message": "Wrapped execution completed. Refresh task context before handoff.",
      "when": {
        "exitCode": 0
      }
    },
    {
      "action": "suggest-command",
      "cadence": "per-run",
      "commands": [
        ["./scripts/agent-task", "ps"],
        ["./scripts/agent-beads", "ready", "--json"]
      ],
      "enabled": true,
      "hook": "post-failure",
      "id": "post-failure-diagnostics",
      "message": "Command failed. Inspect task state before retrying."
    }
  ],
  "schemaVersion": 1
}
"""


def git_output(cwd: Path, command: list[str], fallback: str) -> str:
    result = subprocess.run(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 and result.stdout.strip() else fallback


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(path: Path) -> str:
    return path.as_posix()


if __name__ == "__main__":
    raise SystemExit(main())
