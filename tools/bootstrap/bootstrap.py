#!/usr/bin/env python3
"""In-place bootstrap launcher for Codex-ready project starters."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_TEMPLATE = "java-gradle-cli"
TEMPLATE_MANIFEST = "bootstrap-template.json"
CATALOG_TOP_LEVEL_PATHS = {
    ".git",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "bootstrap",
    "environments",
    "scripts",
    "templates",
    "tools",
}
IGNORED_TOP_LEVEL_PATHS = {
    ".DS_Store",
    ".gradle",
    "__pycache__",
    "build",
}
IGNORED_COPY_NAMES = {
    ".gradle",
    "__pycache__",
    "build",
    TEMPLATE_MANIFEST,
}
TEXT_SUFFIXES = {
    ".bat",
    ".editorconfig",
    ".gitignore",
    ".java",
    ".json",
    ".kts",
    ".md",
    ".properties",
    ".py",
    ".sh",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
JAVA_KEYWORDS = {
    "abstract",
    "assert",
    "boolean",
    "break",
    "byte",
    "case",
    "catch",
    "char",
    "class",
    "const",
    "continue",
    "default",
    "do",
    "double",
    "else",
    "enum",
    "extends",
    "final",
    "finally",
    "float",
    "for",
    "goto",
    "if",
    "implements",
    "import",
    "instanceof",
    "int",
    "interface",
    "long",
    "native",
    "new",
    "package",
    "private",
    "protected",
    "public",
    "return",
    "short",
    "static",
    "strictfp",
    "super",
    "switch",
    "synchronized",
    "this",
    "throw",
    "throws",
    "transient",
    "try",
    "void",
    "volatile",
    "while",
}


class BootstrapError(Exception):
    """Base error for user-facing bootstrap failures."""


class UsageError(BootstrapError):
    """Raised when command input or environment is invalid."""


@dataclass(frozen=True)
class SupportPath:
    source: str
    destination: str


@dataclass(frozen=True)
class TemplateManifest:
    template_id: str
    display_name: str
    description: str
    template_type: str
    required_inputs: tuple[str, ...]
    support_paths: tuple[SupportPath, ...]
    verification_commands: tuple[str, ...]

    @classmethod
    def load(cls, repo_root: Path, template_id: str) -> "TemplateManifest":
        manifest_path = repo_root / "templates" / template_id / TEMPLATE_MANIFEST
        if not manifest_path.is_file():
            raise UsageError(f"unknown template '{template_id}'")

        try:
            raw = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            raise UsageError(f"invalid template manifest {manifest_path}: {error}") from error

        if not isinstance(raw, dict):
            raise UsageError(f"template manifest must be an object: {manifest_path}")

        manifest_id = require_string(raw, "id")
        if manifest_id != template_id:
            raise UsageError(
                f"template manifest id mismatch: expected '{template_id}', found '{manifest_id}'"
            )

        required_inputs = tuple(require_string_list(raw, "requiredInputs"))
        support_paths = tuple(parse_support_paths(raw.get("supportPaths", [])))
        verification_commands = tuple(require_string_list(raw, "verificationCommands"))

        return cls(
            template_id=manifest_id,
            display_name=require_string(raw, "displayName"),
            description=require_string(raw, "description"),
            template_type=require_string(raw, "type"),
            required_inputs=required_inputs,
            support_paths=support_paths,
            verification_commands=verification_commands,
        )


@dataclass(frozen=True)
class BootstrapConfig:
    template_id: str
    project_name: str
    package_name: str
    yes: bool
    dry_run: bool
    force: bool


@dataclass(frozen=True)
class BootstrapPlan:
    repo_root: Path
    manifest: TemplateManifest
    config: BootstrapConfig

    @property
    def template_dir(self) -> Path:
        return self.repo_root / "templates" / self.manifest.template_id

    @property
    def project_title(self) -> str:
        return title_from_slug(self.config.project_name)


def main(repo_root: Path | None = None, argv: list[str] | None = None) -> int:
    actual_root = (repo_root or Path.cwd()).resolve()
    args = parse_args(argv)

    try:
        manifest = TemplateManifest.load(actual_root, args.template)
        config = build_config(args, manifest)
        plan = BootstrapPlan(actual_root, manifest, config)
        validate_plan(plan)
        if plan.config.dry_run:
            print_plan(plan)
            print("No files changed because --dry-run was set.")
            return 0
        confirm_or_abort(plan)
        execute_plan(plan)
    except BootstrapError as error:
        print(f"bootstrap: {error}", file=sys.stderr)
        return 2

    print_success(plan)
    return 0


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rewrite this checkout into a fresh standalone project."
    )
    parser.add_argument(
        "--template",
        default=DEFAULT_TEMPLATE,
        help=f"Template id to materialize. Defaults to {DEFAULT_TEMPLATE}.",
    )
    parser.add_argument("--name", help="Lowercase hyphenated project slug.")
    parser.add_argument("--package", dest="package_name", help="Java package name.")
    parser.add_argument("--yes", action="store_true", help="Skip destructive confirmation.")
    parser.add_argument("--dry-run", action="store_true", help="Show the rewrite plan only.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Allow unexpected top-level files in the bootstrap checkout.",
    )
    return parser.parse_args(argv)


def build_config(args: argparse.Namespace, manifest: TemplateManifest) -> BootstrapConfig:
    if manifest.template_type != "java-gradle-cli":
        raise UsageError(f"unsupported template type '{manifest.template_type}'")

    project_name = args.name or prompt_required("Project slug", "sample-app")
    package_name = args.package_name or prompt_required("Java package", "com.example.sample")

    validate_project_name(project_name)
    validate_java_package(package_name)

    return BootstrapConfig(
        template_id=manifest.template_id,
        project_name=project_name,
        package_name=package_name,
        yes=args.yes,
        dry_run=args.dry_run,
        force=args.force,
    )


def prompt_required(label: str, example: str) -> str:
    if not sys.stdin.isatty():
        raise UsageError(f"missing required value: {label}; pass it as a flag")

    value = input(f"{label} [{example}]: ").strip()
    if value:
        return value
    return example


def validate_plan(plan: BootstrapPlan) -> None:
    assert_safe_project_root(plan.repo_root)

    unexpected = unexpected_top_level_paths(plan.repo_root)
    if unexpected and not plan.config.force:
        joined = ", ".join(path.name for path in unexpected)
        raise UsageError(f"unexpected top-level paths found ({joined}); pass --force to replace them")

    if shutil.which("git") is None:
        raise UsageError("git is required to initialize the generated project")

    for support_path in plan.manifest.support_paths:
        source = resolve_under_root(plan.repo_root, support_path.source)
        if not source.exists():
            raise UsageError(f"support path does not exist: {support_path.source}")


def assert_safe_project_root(root: Path) -> None:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise UsageError(f"project root does not exist: {resolved}")
    if resolved.parent == resolved:
        raise UsageError("refusing to bootstrap filesystem root")
    if len(resolved.parts) < 3:
        raise UsageError(f"refusing to bootstrap unsafe shallow path: {resolved}")
    if not (resolved / "templates").is_dir() or not (resolved / "AGENTS.md").is_file():
        raise UsageError(f"not a codex-bootstrap checkout: {resolved}")


def unexpected_top_level_paths(root: Path) -> list[Path]:
    unexpected: list[Path] = []
    for child in root.iterdir():
        if child.name in CATALOG_TOP_LEVEL_PATHS or child.name in IGNORED_TOP_LEVEL_PATHS:
            continue
        unexpected.append(child)
    return sorted(unexpected)


def confirm_or_abort(plan: BootstrapPlan) -> None:
    if plan.config.yes:
        return
    if not sys.stdin.isatty():
        raise UsageError("refusing destructive rewrite without --yes in a non-interactive shell")

    print_plan(plan)
    answer = input("Replace this checkout with the generated project? Type 'yes' to continue: ")
    if answer.strip().lower() != "yes":
        raise UsageError("aborted")


def execute_plan(plan: BootstrapPlan) -> None:
    with tempfile.TemporaryDirectory(prefix="codex-bootstrap-") as temp_dir:
        staged_root = Path(temp_dir) / plan.config.project_name
        stage_template(plan, staged_root)
        clear_directory(plan.repo_root)
        copy_directory_contents(staged_root, plan.repo_root)
    initialize_git(plan.repo_root)


def stage_template(plan: BootstrapPlan, staged_root: Path) -> None:
    copy_template(plan.template_dir, staged_root)
    copy_support_paths(plan, staged_root)
    rewrite_java_template(plan, staged_root)


def copy_template(template_dir: Path, staged_root: Path) -> None:
    shutil.copytree(
        template_dir,
        staged_root,
        ignore=lambda _path, names: sorted(name for name in names if name in IGNORED_COPY_NAMES),
    )


def copy_support_paths(plan: BootstrapPlan, staged_root: Path) -> None:
    for support_path in plan.manifest.support_paths:
        source = resolve_under_root(plan.repo_root, support_path.source)
        destination = resolve_under_root(staged_root, support_path.destination)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if source.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination, ignore=ignore_runtime_names)
        else:
            shutil.copy2(source, destination)


def ignore_runtime_names(_path: str, names: list[str]) -> list[str]:
    return sorted(name for name in names if name in IGNORED_COPY_NAMES)


def rewrite_java_template(plan: BootstrapPlan, staged_root: Path) -> None:
    move_java_package(staged_root, "com.example", plan.config.package_name)

    replacements = {
        "java-gradle-cli": plan.config.project_name,
        "Java Gradle CLI Template": plan.project_title,
        "com.example": plan.config.package_name,
        "Hello from java-gradle-cli!": f"Hello from {plan.config.project_name}!",
        "../../tools/supermeta-rules/check.py": "tools/supermeta-rules/check.py",
        "../../scripts/agent-gradle .": "./scripts/agent-gradle .",
    }
    rewrite_text_files(staged_root, replacements)
    write_generated_docs(plan, staged_root)


def move_java_package(staged_root: Path, old_package: str, new_package: str) -> None:
    old_path = java_package_to_path(old_package)
    new_path = java_package_to_path(new_package)
    if old_path == new_path:
        return

    for source_set in ("main", "test"):
        java_root = staged_root / "src" / source_set / "java"
        source = java_root / old_path
        if not source.exists():
            continue
        destination = java_root / new_path
        if destination.exists():
            raise UsageError(f"destination package path already exists: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        prune_empty_parents(source.parent, java_root)


def prune_empty_parents(path: Path, stop_at: Path) -> None:
    current = path
    stop = stop_at.resolve()
    while current.resolve() != stop and current.exists():
        try:
            current.rmdir()
        except OSError:
            return
        current = current.parent


def rewrite_text_files(root: Path, replacements: dict[str, str]) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or not should_rewrite_text(path):
            continue
        try:
            original = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        rewritten = original
        for old, new in replacements.items():
            rewritten = rewritten.replace(old, new)

        if rewritten != original:
            path.write_text(rewritten, encoding="utf-8")


def should_rewrite_text(path: Path) -> bool:
    return path.suffix in TEXT_SUFFIXES or path.name in {"gradlew", ".gitignore", ".editorconfig"}


def write_generated_docs(plan: BootstrapPlan, staged_root: Path) -> None:
    (staged_root / "README.md").write_text(generated_readme(plan), encoding="utf-8")
    (staged_root / "AGENTS.md").write_text(generated_agents(plan), encoding="utf-8")


def generated_readme(plan: BootstrapPlan) -> str:
    title = plan.project_title
    package_name = plan.config.package_name
    return f"""# {title}

{title} is a compact Java Gradle command-line project with tests, agent notes, and a deterministic verification path.

## Prerequisites

- a shell environment that can run the Gradle wrapper;
- network access on first run so Gradle can download its distribution and dependencies.

The project defaults to Java 21 source/API compatibility and uses the installed JDK by default to avoid slow toolchain provisioning during agent runs.

## Usage

Run the app:

```bash
./scripts/agent-gradle . run
```

Run tests:

```bash
./scripts/agent-gradle . test
```

Run the full verification lifecycle:

```bash
./scripts/agent-gradle . check
```

## Customization

- Change the Java baseline in `gradle.properties`.
- Leave `useExactJavaToolchain=false` for normal agent runs unless the runtime JDK version itself is under test.
- Product source lives under `src/main/java/{package_name.replace(".", "/")}`.
- Test source lives under `src/test/java/{package_name.replace(".", "/")}`.
- Keep reusable project checks in `tools/supermeta-rules/` and wire them through the build.

## Agent Workflow

Agents should start by reading `AGENTS.md`, then run:

```bash
./scripts/agent-gradle . check
```
"""


def generated_agents(plan: BootstrapPlan) -> str:
    title = plan.project_title
    return f"""# {title} Agent Notes

This is a standalone Java Gradle CLI project. Keep it compact, test-covered, and easy for the next agent to verify.

## Commands

- Verify: `./scripts/agent-gradle . check`
- Test: `./scripts/agent-gradle . test`
- Run: `./scripts/agent-gradle . run`
- If debugging raw Gradle behavior only: `./gradlew check`

## Rules

- Keep Java version changes in `gradle.properties`.
- Keep product source files under `src/main` at 1000 lines or less.
- Use wildcard imports where feasible.
- Route reusable checks through `tools/supermeta-rules/`.
- Use `scripts/agent-gradle` for agent verification unless debugging raw Gradle behavior.
- Preserve the Gradle wrapper so the project is runnable without a global Gradle install.
- Keep the sample app small and test-covered until real product behavior replaces it.
- Prefer clean new-project conventions over compatibility with starter mistakes.
"""


def clear_directory(root: Path) -> None:
    assert_safe_clear_path(root)
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def assert_safe_clear_path(root: Path) -> None:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise UsageError(f"cannot clear missing directory: {resolved}")
    if resolved.parent == resolved:
        raise UsageError("refusing to clear filesystem root")
    if len(resolved.parts) < 3:
        raise UsageError(f"refusing to clear unsafe shallow path: {resolved}")


def copy_directory_contents(source: Path, destination: Path) -> None:
    for child in source.iterdir():
        target = destination / child.name
        if child.is_dir() and not child.is_symlink():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def initialize_git(root: Path) -> None:
    subprocess.run(["git", "init"], cwd=root, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def print_plan(plan: BootstrapPlan) -> None:
    print("Bootstrap plan:")
    print(f"  template: {plan.manifest.template_id} ({plan.manifest.display_name})")
    print(f"  project: {plan.config.project_name}")
    print(f"  package: {plan.config.package_name}")
    print(f"  root: {plan.repo_root}")
    print("  action: replace this checkout with the generated project")
    print("  git: delete existing Git metadata and run git init")
    print("  verification:")
    for command in plan.manifest.verification_commands:
        print(f"    {command}")


def print_success(plan: BootstrapPlan) -> None:
    print(f"Bootstrapped {plan.config.project_name}.")
    print("Next commands:")
    for command in plan.manifest.verification_commands:
        print(f"  {command}")


def validate_project_name(value: str) -> None:
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", value):
        raise UsageError(
            "project name must be lowercase hyphenated, starting with a letter "
            "(example: my-service)"
        )


def validate_java_package(value: str) -> None:
    parts = value.split(".")
    if len(parts) < 2:
        raise UsageError("Java package must contain at least two dot-separated segments")
    for part in parts:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", part):
            raise UsageError(f"invalid Java package segment '{part}'")
        if part in JAVA_KEYWORDS:
            raise UsageError(f"Java package segment cannot be a keyword: '{part}'")


def java_package_to_path(package_name: str) -> Path:
    validate_java_package(package_name)
    return Path(*package_name.split("."))


def title_from_slug(slug: str) -> str:
    validate_project_name(slug)
    return " ".join(part.capitalize() for part in slug.split("-"))


def resolve_under_root(root: Path, configured_path: str) -> Path:
    candidate = (root / configured_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as error:
        raise UsageError(f"path escapes root: {configured_path}") from error
    return candidate


def parse_support_paths(raw: Any) -> list[SupportPath]:
    if not isinstance(raw, list):
        raise UsageError("supportPaths must be an array")

    support_paths: list[SupportPath] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise UsageError(f"supportPaths[{index}] must be an object")
        support_paths.append(
            SupportPath(
                source=require_string(item, "source"),
                destination=require_string(item, "destination"),
            )
        )
    return support_paths


def require_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise UsageError(f"{key} must be a non-empty string")
    return value


def require_string_list(raw: dict[str, Any], key: str) -> list[str]:
    value = raw.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise UsageError(f"{key} must be an array of non-empty strings")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
