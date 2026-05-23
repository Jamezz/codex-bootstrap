#!/usr/bin/env python3
"""In-place bootstrap launcher for Codex-ready project starters."""

from __future__ import annotations

import argparse
import json
import keyword
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
SUPPORTED_TEMPLATE_TYPES = {
    "csharp-dotnet-cli",
    "java-gradle-cli",
    "python-uv-cli",
    "typescript-bun-cli",
    "typescript-bun-mcp-server",
}
CATALOG_TOP_LEVEL_PATHS = {
    ".git",
    ".github",
    ".gitattributes",
    ".gitignore",
    "AGENTS.md",
    "README.md",
    "bootstrap",
    "bootstrap.ps1",
    "docs",
    "environments",
    "scripts",
    "site",
    "templates",
    "tools",
}
IGNORED_TOP_LEVEL_PATHS = {
    ".DS_Store",
    ".bun",
    ".dotnet",
    ".gradle",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tsbuildinfo",
    ".venv",
    ".nuget",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
}
IGNORED_COPY_NAMES = {
    ".bun",
    ".dotnet",
    ".gradle",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tsbuildinfo",
    ".venv",
    ".nuget",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    TEMPLATE_MANIFEST,
}
TEXT_SUFFIXES = {
    ".bat",
    ".cjs",
    ".cs",
    ".csproj",
    ".cts",
    ".editorconfig",
    ".props",
    ".gitignore",
    ".java",
    ".js",
    ".json",
    ".jsonc",
    ".kts",
    ".lock",
    ".md",
    ".mjs",
    ".mts",
    ".properties",
    ".ps1",
    ".py",
    ".sh",
    ".slnx",
    ".targets",
    ".txt",
    ".toml",
    ".ts",
    ".tsx",
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
CSHARP_KEYWORDS = {
    "abstract",
    "as",
    "base",
    "bool",
    "break",
    "byte",
    "case",
    "catch",
    "char",
    "checked",
    "class",
    "const",
    "continue",
    "decimal",
    "default",
    "delegate",
    "do",
    "double",
    "else",
    "enum",
    "event",
    "explicit",
    "extern",
    "false",
    "finally",
    "fixed",
    "float",
    "for",
    "foreach",
    "goto",
    "if",
    "implicit",
    "in",
    "int",
    "interface",
    "internal",
    "is",
    "lock",
    "long",
    "namespace",
    "new",
    "null",
    "object",
    "operator",
    "out",
    "override",
    "params",
    "private",
    "protected",
    "public",
    "readonly",
    "ref",
    "return",
    "sbyte",
    "sealed",
    "short",
    "sizeof",
    "stackalloc",
    "static",
    "string",
    "struct",
    "switch",
    "this",
    "throw",
    "true",
    "try",
    "typeof",
    "uint",
    "ulong",
    "unchecked",
    "unsafe",
    "ushort",
    "using",
    "virtual",
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
class GeneratedDocs:
    summary: str
    runtime: str
    entrypoints: tuple[str, ...]
    source_roots: tuple[str, ...]
    test_roots: tuple[str, ...]
    verification_commands: tuple[str, ...]
    run_commands: tuple[str, ...]
    first_useful_edit: str


@dataclass(frozen=True)
class ManagedFileSpec:
    path: str
    managed_set: str


@dataclass(frozen=True)
class ManagedRegionSpec:
    path: str
    region_id: str
    managed_set: str

    @property
    def key(self) -> str:
        return f"{self.path}:{self.region_id}"


@dataclass(frozen=True)
class ManagedSetSpec:
    managed_set: str
    description: str
    files: tuple[ManagedFileSpec, ...]
    regions: tuple[ManagedRegionSpec, ...]


@dataclass(frozen=True)
class SyncContract:
    version: int
    managed_sets: dict[str, ManagedSetSpec]
    verification_commands: tuple[str, ...]
    migration_notes: tuple[str, ...]

    @property
    def managed_files(self) -> dict[str, ManagedFileSpec]:
        result: dict[str, ManagedFileSpec] = {}
        for managed_set in self.managed_sets.values():
            for spec in managed_set.files:
                result[spec.path] = spec
        return result

    @property
    def managed_regions(self) -> dict[str, ManagedRegionSpec]:
        result: dict[str, ManagedRegionSpec] = {}
        for managed_set in self.managed_sets.values():
            for spec in managed_set.regions:
                result[spec.key] = spec
        return result


@dataclass(frozen=True)
class TemplateManifest:
    template_id: str
    display_name: str
    description: str
    template_type: str
    required_inputs: tuple[str, ...]
    support_paths: tuple[SupportPath, ...]
    verification_commands: tuple[str, ...]
    generated_docs: GeneratedDocs
    sync_contract: SyncContract

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
        generated_docs = parse_generated_docs(raw.get("generatedDocs"))
        sync_contract = parse_sync_contract(raw.get("syncContract"))

        return cls(
            template_id=manifest_id,
            display_name=require_string(raw, "displayName"),
            description=require_string(raw, "description"),
            template_type=require_string(raw, "type"),
            required_inputs=required_inputs,
            support_paths=support_paths,
            verification_commands=verification_commands,
            generated_docs=generated_docs,
            sync_contract=sync_contract,
        )


@dataclass(frozen=True)
class BootstrapConfig:
    template_id: str
    project_name: str
    package_name: str | None
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
    if manifest.template_type not in SUPPORTED_TEMPLATE_TYPES:
        raise UsageError(f"unsupported template type '{manifest.template_type}'")

    project_name = args.name or prompt_required("Project slug", "sample-app")
    validate_project_name(project_name)

    package_name = None
    if manifest.template_type == "java-gradle-cli":
        package_name = args.package_name or prompt_required("Java package", "com.example.sample")
        validate_java_package(package_name)
    elif manifest.template_type == "python-uv-cli":
        python_module_from_slug(project_name)
        if args.package_name:
            raise UsageError("--package is only supported by Java templates")
    elif manifest.template_type == "csharp-dotnet-cli":
        csharp_project_name_from_slug(project_name)
        if args.package_name:
            raise UsageError("--package is only supported by Java templates")
    elif args.package_name:
        raise UsageError("--package is only supported by Java templates")

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
    rewriter = {
        "csharp-dotnet-cli": rewrite_csharp_template,
        "java-gradle-cli": rewrite_java_template,
        "python-uv-cli": rewrite_python_template,
        "typescript-bun-cli": rewrite_typescript_template,
        "typescript-bun-mcp-server": rewrite_typescript_template,
    }.get(plan.manifest.template_type)
    if rewriter is None:
        raise UsageError(f"unsupported template type '{plan.manifest.template_type}'")
    rewriter(plan, staged_root)
    write_sync_metadata(plan, staged_root)


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
    if plan.config.package_name is None:
        raise UsageError("Java template requires --package")

    move_java_package(staged_root, "com.example", plan.config.package_name)

    replacements = common_replacements(plan) | {
        "java-gradle-cli": plan.config.project_name,
        "Java Gradle CLI Template": plan.project_title,
        "com.example": plan.config.package_name,
        "Hello from java-gradle-cli!": f"Hello from {plan.config.project_name}!",
    }
    rewrite_text_files(staged_root, replacements)
    write_generated_docs(plan, staged_root)


def rewrite_python_template(plan: BootstrapPlan, staged_root: Path) -> None:
    module_name = python_module_from_slug(plan.config.project_name)
    move_python_module(staged_root, "python_uv_cli", module_name)

    replacements = common_replacements(plan) | {
        "python-uv-cli": plan.config.project_name,
        "Python uv CLI Template": plan.project_title,
        "python_uv_cli": module_name,
    }
    rewrite_text_files(staged_root, replacements)
    write_generated_docs(plan, staged_root)


def rewrite_csharp_template(plan: BootstrapPlan, staged_root: Path) -> None:
    project_name = csharp_project_name_from_slug(plan.config.project_name)
    move_csharp_project(staged_root, "CsharpDotnetCli", project_name)

    replacements = common_replacements(plan) | {
        "csharp-dotnet-cli": plan.config.project_name,
        "csharpdotnetcli": project_name.lower(),
        "C# .NET CLI Template": plan.project_title,
        "CsharpDotnetCli": project_name,
    }
    rewrite_text_files(staged_root, replacements)
    write_generated_docs(plan, staged_root)


def rewrite_typescript_template(plan: BootstrapPlan, staged_root: Path) -> None:
    replacements = common_replacements(plan) | {
        plan.manifest.template_id: plan.config.project_name,
        f"{plan.manifest.display_name} Template": plan.project_title,
    }
    rewrite_text_files(staged_root, replacements)
    write_generated_docs(plan, staged_root)


def common_replacements(plan: BootstrapPlan) -> dict[str, str]:
    return {
        "../../scripts/agent-gradle .": "./scripts/agent-gradle .",
        "../../scripts/agent-gradle": "./scripts/agent-gradle",
        "../../scripts/agent-dotnet .": "./scripts/agent-dotnet .",
        "../../scripts/agent-dotnet": "./scripts/agent-dotnet",
        "../../scripts/agent-beans": "./scripts/agent-beans",
        "../../scripts/agent-task": "./scripts/agent-task",
        "../../tools/supermeta-rules/check.py": "tools/supermeta-rules/check.py",
    }


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
        move_package_directory(source, destination)
        prune_empty_parents(source.parent, java_root)


def move_package_directory(source: Path, destination: Path) -> None:
    if is_relative_to(destination, source):
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-package-") as temp_dir:
            temp_source = Path(temp_dir) / source.name
            shutil.move(str(source), str(temp_source))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(temp_source), str(destination))
        return

    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(destination))


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
    except ValueError:
        return False
    return True


def move_python_module(staged_root: Path, old_module: str, new_module: str) -> None:
    source = staged_root / "src" / old_module
    if not source.exists() or old_module == new_module:
        return

    destination = staged_root / "src" / new_module
    if destination.exists():
        raise UsageError(f"destination Python module already exists: {destination}")
    shutil.move(str(source), str(destination))


def move_csharp_project(staged_root: Path, old_name: str, new_name: str) -> None:
    if old_name == new_name:
        return

    moves = (
        (staged_root / f"{old_name}.slnx", staged_root / f"{new_name}.slnx"),
        (staged_root / "src" / old_name, staged_root / "src" / new_name),
        (staged_root / "tests" / f"{old_name}.Tests", staged_root / "tests" / f"{new_name}.Tests"),
    )
    for source, destination in moves:
        if not source.exists():
            continue
        if destination.exists():
            raise UsageError(f"destination C# project path already exists: {destination}")
        shutil.move(str(source), str(destination))

    source_project = staged_root / "src" / new_name / f"{old_name}.csproj"
    if source_project.exists():
        source_project.rename(staged_root / "src" / new_name / f"{new_name}.csproj")

    test_project = staged_root / "tests" / f"{new_name}.Tests" / f"{old_name}.Tests.csproj"
    if test_project.exists():
        test_project.rename(staged_root / "tests" / f"{new_name}.Tests" / f"{new_name}.Tests.csproj")


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
    return path.suffix in TEXT_SUFFIXES or path.name in {
        "check",
        "gradlew",
        ".gitignore",
        ".editorconfig",
    }


def write_generated_docs(plan: BootstrapPlan, staged_root: Path) -> None:
    (staged_root / "README.md").write_text(generated_readme(plan), encoding="utf-8")
    (staged_root / "AGENTS.md").write_text(generated_agents(plan), encoding="utf-8")
    docs_dir = staged_root / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "ARCHITECTURE.md").write_text(generated_architecture(plan), encoding="utf-8")
    (docs_dir / "OPERATIONS.md").write_text(generated_operations(plan), encoding="utf-8")
    (docs_dir / "DECISIONS.md").write_text(generated_decisions(plan), encoding="utf-8")
    write_generated_beans(plan, staged_root)


def generated_project_docs_section() -> str:
    return """## Project Docs

- `docs/ARCHITECTURE.md`: runtime shape, entrypoints, and code layout.
- `docs/OPERATIONS.md`: verification, run, troubleshooting, and backlog commands.
- `docs/DECISIONS.md`: active decisions only; superseded decision history belongs in completed or archived Beans.

## Backlog

This project starts with a small Beans backlog for replacing the starter behavior, locking architecture decisions, and adding CI or release verification.

If the pinned Beans CLI is installed, inspect project task context with:

```bash
./scripts/agent-beans prime
./scripts/agent-beans list
./scripts/agent-beans check
```
"""


def generated_bootstrap_sync_region(check_command: str) -> str:
    return f"""<!-- codex-bootstrap:begin generated-docs/bootstrap-sync -->
## Bootstrap Sync

This project can resync Codex Bootstrap managed files and generated doc regions from the recorded bootstrap source.

Preview managed updates first:

```bash
./scripts/agent-bootstrap sync --dry-run
```

Apply only when the plan has no conflicts:

```bash
./scripts/agent-bootstrap sync --apply
{check_command}
```
<!-- codex-bootstrap:end generated-docs/bootstrap-sync -->
"""


def generated_agent_sync_region(check_command: str) -> str:
    return f"""<!-- codex-bootstrap:begin generated-docs/bootstrap-sync -->
## Bootstrap Sync

- Run `./scripts/agent-bootstrap sync --dry-run` before applying bootstrap updates.
- Inspect conflicts instead of forcing over local edits.
- Apply managed updates with `./scripts/agent-bootstrap sync --apply` only when the plan is clean.
- After apply, run `{check_command}` and any extra verification commands printed by sync.
- If this repo has `CHANGELOG.md`, update it when sync changes merge-relevant behavior.
<!-- codex-bootstrap:end generated-docs/bootstrap-sync -->
"""


def check_command(plan: BootstrapPlan) -> str:
    if plan.manifest.template_type == "java-gradle-cli":
        return "./scripts/agent-gradle . check"
    return "./scripts/check"


def windows_check_command(plan: BootstrapPlan) -> str:
    if plan.manifest.template_type == "java-gradle-cli":
        return ".\\scripts\\agent-gradle.ps1 . check"
    return ".\\scripts\\check.ps1"


def windows_run_command(plan: BootstrapPlan) -> str:
    if plan.manifest.template_type == "csharp-dotnet-cli":
        project_name = csharp_project_name_from_slug(plan.config.project_name)
        return f".\\scripts\\agent-dotnet.ps1 . run --project src/{project_name}/{project_name}.csproj --"
    if plan.manifest.template_type == "java-gradle-cli":
        return ".\\scripts\\agent-gradle.ps1 . run"
    if plan.manifest.template_type == "typescript-bun-mcp-server":
        return "bun run src/main.ts --help"
    if plan.manifest.template_type == "typescript-bun-cli":
        return "bun run src/main.ts"
    return f"uv run --no-editable {plan.config.project_name}"


def windows_run_with_args_command(plan: BootstrapPlan) -> str:
    if plan.manifest.template_type == "csharp-dotnet-cli":
        return f"{windows_run_command(plan)} \"example\""
    if plan.manifest.template_type == "java-gradle-cli":
        return ".\\scripts\\agent-gradle.ps1 . run --args=\"example\""
    if plan.manifest.template_type == "typescript-bun-mcp-server":
        return "bun run src/main.ts --transport http"
    if plan.manifest.template_type == "typescript-bun-cli":
        return "bun run src/main.ts \"example\""
    return f"uv run --no-editable {plan.config.project_name} \"example\""


def windows_setup_command(plan: BootstrapPlan) -> str | None:
    if plan.manifest.template_type == "csharp-dotnet-cli":
        return ".\\scripts\\agent-dotnet.ps1 . restore --locked-mode"
    return None


def windows_process_match(plan: BootstrapPlan) -> str:
    if plan.manifest.template_type == "csharp-dotnet-cli":
        return "dotnet"
    if plan.manifest.template_type == "java-gradle-cli":
        return "gradle"
    if plan.manifest.template_type == "python-uv-cli":
        return "uv"
    return "bun"


def generated_windows_readme_section(plan: BootstrapPlan) -> str:
    setup_command = windows_setup_command(plan)
    setup_line = f"{setup_command}\n" if setup_command else ""
    return f"""## Windows

PowerShell entrypoints mirror the Unix scripts:

```powershell
{setup_line}{windows_check_command(plan)}
{windows_run_command(plan)}
.\\scripts\\agent-beans.ps1 prime
.\\scripts\\agent-task.ps1 ps --match {windows_process_match(plan)}
```
"""


def generated_windows_agent_section(plan: BootstrapPlan) -> str:
    return f"""## Windows

- Verify: `{windows_check_command(plan)}`
- Run: `{windows_run_command(plan)}`
- Run with app args: `{windows_run_with_args_command(plan)}`
- Beans prime: `.\\scripts\\agent-beans.ps1 prime`
- Inspect task processes: `.\\scripts\\agent-task.ps1 ps --match {windows_process_match(plan)}`
"""


def generated_agent_beans_section() -> str:
    return """## Beans

- Before substantial work, run `./scripts/agent-beans prime` and follow its project-task context.
- Use `./scripts/agent-beans list --ready` to inspect ready work.
- Keep the seeded Beans current as starter behavior is replaced.
- If `./scripts/agent-beans` reports a missing or wrong Beans CLI version, tell the user instead of bypassing the wrapper.
"""


def generated_logging_readme_section() -> str:
    return """## Logging

Runtime logs are quiet by default and become visible when `LOG_LEVEL` enables them:

```bash
LOG_LEVEL=info LOG_FORMAT=text <run-command>
LOG_LEVEL=info LOG_FORMAT=json <run-command>
```

`LOG_LEVEL` accepts `trace`, `debug`, `info`, `warn`, `error`, or `off`. `LOG_FORMAT` accepts `text` or `json`. Logs always go to stderr; normal command output stays on stdout unless the CLI is reporting a user-facing error.
"""


def generated_logging_agent_rules() -> str:
    return """- Keep runtime logging behind `LOG_LEVEL` and `LOG_FORMAT`.
- Keep default logging quiet: `LOG_LEVEL=warn` and `LOG_FORMAT=text`.
- Keep logs on stderr and normal command output on stdout.
- Fail fast with exit code 2 when logging configuration is invalid."""


def generated_readme(plan: BootstrapPlan) -> str:
    if plan.manifest.template_type == "csharp-dotnet-cli":
        return generated_csharp_readme(plan)
    if plan.manifest.template_type == "python-uv-cli":
        return generated_python_readme(plan)
    if plan.manifest.template_type == "typescript-bun-mcp-server":
        return generated_typescript_mcp_readme(plan)
    if plan.manifest.template_type == "typescript-bun-cli":
        return generated_typescript_readme(plan)
    return generated_java_readme(plan)


def generated_java_readme(plan: BootstrapPlan) -> str:
    title = plan.project_title
    if plan.config.package_name is None:
        raise UsageError("Java template requires --package")
    package_name = plan.config.package_name
    return f"""# {title}

{title} is a compact Java Gradle command-line project with tests, first-class runtime logging, agent notes, and a deterministic verification path.

## Prerequisites

- a shell environment that can run the Gradle wrapper;
- network access on first run so Gradle can download its distribution and dependencies.

The project defaults to Java 21 source/API compatibility and uses the installed JDK by default to avoid slow toolchain provisioning during agent runs.

## Usage

Run the app:

```bash
./scripts/agent-gradle . run
```

Pass application arguments:

```bash
./scripts/agent-gradle . run --args="Ada Lovelace"
```

Run tests:

```bash
./scripts/agent-gradle . test
```

Run the full verification lifecycle:

```bash
./scripts/agent-gradle . check
```

{generated_logging_readme_section().replace("<run-command>", "./scripts/agent-gradle . run")}

Inspect stuck task state:

```bash
./scripts/agent-task ps --match gradle
./scripts/agent-task logs .gradle/supermeta-gradle/logs
./scripts/agent-gradle . --stop
```

{generated_windows_readme_section(plan)}
## Customization

- Change the Java baseline in `gradle.properties`.
- Change the Lombok baseline in `gradle.properties`.
- Change the SLF4J, Logback, and logstash-logback-encoder baselines in `gradle.properties`.
- Leave `useExactJavaToolchain=false` for normal agent runs unless the runtime JDK version itself is under test.
- Product source lives under `src/main/java/{package_name.replace(".", "/")}`.
- Test source lives under `src/test/java/{package_name.replace(".", "/")}`.
- If you rename `App`, update `application.mainClass` in `build.gradle.kts`.
- Keep each Java package layer to 7 top-level types or fewer; split larger layers into context-shaped subpackages.
- Supermeta enforces wildcard imports for Java source; configure `allow_explicit` only for deliberate exceptions.
- Supermeta rejects handwritten getter, setter, and builder boilerplate; use Lombok annotations or a configured `ignore_annotations` escape hatch for rare intentional exceptions.
- Java lint runs through Gradle Checkstyle, with configuration in `config/checkstyle/checkstyle.xml`.
- Keep reusable project checks in `tools/supermeta-rules/` and wire them through the build.

## First Useful Edit

Extend the CLI behavior in `App.java`, update `AppTest.java` first or in the same change, then run:

```bash
./scripts/agent-gradle . check
./scripts/agent-gradle . run --args='example'
```

{generated_project_docs_section()}
{generated_bootstrap_sync_region(check_command(plan))}
## Agent Workflow

Agents should start by reading `AGENTS.md`, then run:

```bash
./scripts/agent-gradle . check
```
"""


def generated_agents(plan: BootstrapPlan) -> str:
    if plan.manifest.template_type == "csharp-dotnet-cli":
        return generated_csharp_agents(plan)
    if plan.manifest.template_type == "python-uv-cli":
        return generated_python_agents(plan)
    if plan.manifest.template_type == "typescript-bun-mcp-server":
        return generated_typescript_mcp_agents(plan)
    if plan.manifest.template_type == "typescript-bun-cli":
        return generated_typescript_agents(plan)
    return generated_java_agents(plan)


def generated_java_agents(plan: BootstrapPlan) -> str:
    title = plan.project_title
    return f"""# {title} Agent Notes

This is a standalone Java Gradle CLI project. Keep it compact, test-covered, and easy for the next agent to verify.

## Commands

- Verify: `./scripts/agent-gradle . check`
- Test: `./scripts/agent-gradle . test`
- Run: `./scripts/agent-gradle . run`
- Run with app args: `./scripts/agent-gradle . run --args="example"`
- Run with text logs: `LOG_LEVEL=info ./scripts/agent-gradle . run`
- Run with JSON logs: `LOG_LEVEL=info LOG_FORMAT=json ./scripts/agent-gradle . run`
- Beans prime: `./scripts/agent-beans prime`
- Beans check: `./scripts/agent-beans check`
- Ready backlog: `./scripts/agent-beans list --ready`
- Inspect generic task processes: `./scripts/agent-task ps --match gradle`
- List generic task logs: `./scripts/agent-task logs .gradle/supermeta-gradle/logs`
- Inspect stuck Gradle processes: `./scripts/agent-gradle . --ps`
- List harness logs: `./scripts/agent-gradle . --logs`
- Stop scoped Gradle daemon: `./scripts/agent-gradle . --stop`
- If debugging raw Gradle behavior only: `./gradlew check`

{generated_windows_agent_section(plan)}
{generated_agent_beans_section()}
{generated_agent_sync_region(check_command(plan))}
## Rules

- Keep Java version changes in `gradle.properties`.
- Keep Lombok version changes in `gradle.properties`.
- Keep SLF4J, Logback, and logstash-logback-encoder version changes in `gradle.properties`.
- If you rename `App`, update `application.mainClass` in `build.gradle.kts`.
{generated_logging_agent_rules()}
- Keep Java package layers to 7 top-level types or fewer before nesting into context-shaped subpackages.
- Keep product source files under `src/main` at 1000 lines or less.
- Supermeta enforces wildcard imports for Java source; use `allow_explicit` only for deliberate exceptions.
- Supermeta rejects handwritten getter, setter, and builder boilerplate; use Lombok annotations or a configured `ignore_annotations` escape hatch for rare intentional exceptions.
- Keep Lombok as compile-only plus annotation-processor wiring.
- Keep Java lint in Gradle Checkstyle and project callouts in `supermeta-rules.json`.
- Route reusable checks through `tools/supermeta-rules/`.
- Use `scripts/agent-gradle` for agent verification unless debugging raw Gradle behavior.
- Preserve the Gradle wrapper so the project is runnable without a global Gradle install.
- Extend the sample CLI into real behavior early, and keep tests updated with that change.
- Prefer clean new-project conventions over compatibility with starter mistakes.
"""


def generated_csharp_readme(plan: BootstrapPlan) -> str:
    title = plan.project_title
    project_name = csharp_project_name_from_slug(plan.config.project_name)
    project_path = f"src/{project_name}/{project_name}.csproj"
    solution_path = f"{project_name}.slnx"
    run_command = f"./scripts/agent-dotnet . run --project {project_path} --"
    return f"""# {title}

{title} is a compact C# .NET command-line project with xUnit tests, first-class runtime logging, agent notes, and a deterministic verification path.

## Prerequisites

- .NET SDK 10 on PATH;
- network access on first run so NuGet can restore test dependencies.

The project targets `net10.0`.

## Usage

Restore locked dependencies:

```bash
./scripts/agent-dotnet . restore --locked-mode
```

Run the full verification lifecycle:

```bash
./scripts/check
```

Run tests directly:

```bash
./scripts/agent-dotnet . test {solution_path} --configuration Release
```

Run the app:

```bash
{run_command}
{run_command} "Ada Lovelace"
```

{generated_logging_readme_section().replace("<run-command>", run_command)}

Inspect stuck task state:

```bash
./scripts/agent-task ps --match dotnet
```

{generated_windows_readme_section(plan)}
## Customization

- Product source lives under `src/{project_name}`.
- Test source lives under `tests/{project_name}.Tests`.
- CLI behavior starts in `src/{project_name}/App.cs`.
- Runtime logging lives in `src/{project_name}/LoggingConfig.cs`.
- The process entrypoint is `src/{project_name}/Program.cs`.
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable project checks in `tools/supermeta-rules/` and wire them through `scripts/check`.
- Keep formatting in `dotnet format`, build checks in `dotnet build`, and behavior checks in xUnit.
- Keep package versions in `Directory.Packages.props` and lock files checked in.

## First Useful Edit

Extend the CLI behavior in `App.cs`, update `AppTests.cs` first or in the same change, then run:

```bash
./scripts/check
{run_command} example
```

{generated_project_docs_section()}
{generated_bootstrap_sync_region(check_command(plan))}
## Agent Workflow

Agents should start by reading `AGENTS.md`, then run:

```bash
./scripts/check
```
"""


def generated_csharp_agents(plan: BootstrapPlan) -> str:
    title = plan.project_title
    project_name = csharp_project_name_from_slug(plan.config.project_name)
    project_path = f"src/{project_name}/{project_name}.csproj"
    solution_path = f"{project_name}.slnx"
    run_command = f"./scripts/agent-dotnet . run --project {project_path} --"
    return f"""# {title} Agent Notes

This is a standalone C# .NET CLI project. Keep it compact, test-covered, and easy for the next agent to verify.

## Commands

- Restore locked dependencies: `./scripts/agent-dotnet . restore --locked-mode`
- Verify: `./scripts/check`
- Format check: `./scripts/agent-dotnet . format {solution_path} --verify-no-changes --no-restore`
- Build: `./scripts/agent-dotnet . build {solution_path} --configuration Release --no-restore`
- Test: `./scripts/agent-dotnet . test {solution_path} --configuration Release --no-build`
- Run: `{run_command}`
- Run with app args: `{run_command} "example"`
- Run with text logs: `LOG_LEVEL=info {run_command}`
- Run with JSON logs: `LOG_LEVEL=info LOG_FORMAT=json {run_command}`
- Beans prime: `./scripts/agent-beans prime`
- Beans check: `./scripts/agent-beans check`
- Ready backlog: `./scripts/agent-beans list --ready`
- Inspect dotnet processes: `./scripts/agent-task ps --match dotnet`

{generated_windows_agent_section(plan)}
{generated_agent_beans_section()}
{generated_agent_sync_region(check_command(plan))}
## Rules

- Target .NET 10 through `net10.0` unless the project intentionally chooses a different runtime floor.
- Keep runtime and test dependency versions centralized in `Directory.Packages.props`.
- Keep package lock files checked in and use locked restore for verification.
- Keep CLI behavior in `App.cs` and entrypoint glue in `Program.cs`.
- Keep runtime logging in `LoggingConfig.cs`.
{generated_logging_agent_rules()}
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Route formatting through `dotnet format`, build through `dotnet build`, and behavior checks through xUnit.
- Use `scripts/agent-dotnet` for agent verification unless debugging raw dotnet behavior.
- Extend the sample CLI into real behavior early, and keep tests updated with that change.
- Prefer clean new-project conventions over compatibility with starter mistakes.
"""


def generated_python_readme(plan: BootstrapPlan) -> str:
    title = plan.project_title
    module_name = python_module_from_slug(plan.config.project_name)
    return f"""# {title}

{title} is a compact Python uv command-line project with tests, type checking, first-class runtime logging, agent notes, and a deterministic verification path.

## Prerequisites

- `uv` on PATH;
- network access on first run so uv can resolve and download development dependencies.

The project targets Python 3.14.

## Usage

Install the locked project environment:

```bash
uv sync --locked
```

Run the full verification lifecycle:

```bash
./scripts/check
```

Run tests directly:

```bash
uv run --no-editable pytest
```

Run the app through the console script:

```bash
uv run --no-editable {plan.config.project_name}
uv run --no-editable {plan.config.project_name} "Ada Lovelace"
```

Run the app through the module entrypoint:

```bash
uv run --no-editable python -m {module_name}
uv run --no-editable python -m {module_name} "Ada Lovelace"
```

{generated_logging_readme_section().replace("<run-command>", f"uv run --no-editable {plan.config.project_name}")}

{generated_windows_readme_section(plan)}
## Customization

- Product source lives under `src/{module_name}`.
- Test source lives under `tests/`.
- CLI behavior starts in `src/{module_name}/cli.py`.
- Runtime logging lives in `src/{module_name}/logging_config.py`.
- The console script is declared in `pyproject.toml`.
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable project checks in `tools/supermeta-rules/` and wire them through `scripts/check`.
- Keep Python lint and formatting in Ruff, type checking in mypy, and behavior checks in pytest.

## First Useful Edit

Extend the CLI behavior in `cli.py`, update `tests/test_cli.py` first or in the same change, then run:

```bash
./scripts/check
uv run --no-editable {plan.config.project_name} example
```

{generated_project_docs_section()}
{generated_bootstrap_sync_region(check_command(plan))}
"""


def generated_python_agents(plan: BootstrapPlan) -> str:
    title = plan.project_title
    module_name = python_module_from_slug(plan.config.project_name)
    return f"""# {title} Agent Notes

This is a standalone Python uv CLI project. Keep it compact, typed, test-covered, and easy for the next agent to verify.

## Commands

- Install locked environment: `uv sync --locked`
- Verify: `./scripts/check`
- Test: `uv run --no-editable pytest`
- Format check: `uv run --no-editable ruff format --check src tests`
- Lint: `uv run --no-editable ruff check src tests`
- Type check: `uv run --no-editable mypy src tests`
- Run: `uv run --no-editable {plan.config.project_name}`
- Run with app args: `uv run --no-editable {plan.config.project_name} "example"`
- Run module entrypoint: `uv run --no-editable python -m {module_name} "example"`
- Run with text logs: `LOG_LEVEL=info uv run --no-editable {plan.config.project_name}`
- Run with JSON logs: `LOG_LEVEL=info LOG_FORMAT=json uv run --no-editable {plan.config.project_name}`
- Beans prime: `./scripts/agent-beans prime`
- Beans check: `./scripts/agent-beans check`
- Ready backlog: `./scripts/agent-beans list --ready`
- Inspect task processes: `./scripts/agent-task ps --match uv`
- Inspect pytest processes: `./scripts/agent-task ps --match pytest`

{generated_windows_agent_section(plan)}
{generated_agent_beans_section()}
{generated_agent_sync_region(check_command(plan))}
## Rules

- Keep runtime dependencies in `pyproject.toml`; keep dev-only tools in the dev dependency group.
- Keep the Python baseline at 3.14 unless the project intentionally chooses a different runtime floor.
- Keep CLI behavior in `src/{module_name}/cli.py` and entrypoint glue in `src/{module_name}/__main__.py`.
- Keep runtime logging in `src/{module_name}/logging_config.py`.
{generated_logging_agent_rules()}
- Keep product source files under `src/` at 1000 lines or less.
- Preserve `py.typed` so the package advertises inline types.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Route Python lint through Ruff, type checking through mypy, and behavior checks through pytest.
- Use `./scripts/check` for agent verification unless debugging one tool directly.
- Extend the sample CLI into real behavior early, and keep tests updated with that change.
- Prefer clean new-project conventions over compatibility with starter mistakes.
"""


def generated_typescript_readme(plan: BootstrapPlan) -> str:
    title = plan.project_title
    return f"""# {title}

{title} is a compact TypeScript Bun command-line project with tests, type checking, first-class runtime logging, agent notes, and a deterministic verification path.

## Prerequisites

- `bun` on PATH;
- network access on first run so Bun can install development dependencies.

## Usage

Install locked dependencies:

```bash
bun install --frozen-lockfile
```

Run the full verification lifecycle:

```bash
./scripts/check
```

Run tests directly:

```bash
bun test
```

Run the app:

```bash
bun run src/main.ts
bun run src/main.ts "Ada Lovelace"
```

{generated_logging_readme_section().replace("<run-command>", "bun run src/main.ts")}

{generated_windows_readme_section(plan)}
## Customization

- Product source lives under `src/`.
- Test source lives under `tests/`.
- CLI behavior starts in `src/cli.ts`.
- Runtime logging lives in `src/logging.ts`.
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable project checks in `tools/supermeta-rules/` and wire them through `scripts/check`.
- Keep formatting and linting in Biome, type checking in `tsc --noEmit`, and behavior checks in `bun test`.
- Keep TypeScript and Biome package scripts invoked through Bun so the project does not depend on a separate Node install.

## First Useful Edit

Extend the CLI behavior in `src/cli.ts`, update `tests/cli.test.ts` first or in the same change, then run:

```bash
./scripts/check
bun run src/main.ts example
```

{generated_project_docs_section()}
{generated_bootstrap_sync_region(check_command(plan))}
"""


def generated_typescript_agents(plan: BootstrapPlan) -> str:
    title = plan.project_title
    return f"""# {title} Agent Notes

This is a standalone TypeScript Bun CLI project. Keep it compact, typed, test-covered, and easy for the next agent to verify.

## Commands

- Install locked dependencies: `bun install --frozen-lockfile`
- Verify: `./scripts/check`
- Type check: `bun run typecheck`
- Lint and format check: `bun run lint`
- Test: `bun test`
- Run: `bun run src/main.ts`
- Run with app args: `bun run src/main.ts "example"`
- Run with text logs: `LOG_LEVEL=info bun run src/main.ts`
- Run with JSON logs: `LOG_LEVEL=info LOG_FORMAT=json bun run src/main.ts`
- Beans prime: `./scripts/agent-beans prime`
- Beans check: `./scripts/agent-beans check`
- Ready backlog: `./scripts/agent-beans list --ready`
- Inspect Bun processes: `./scripts/agent-task ps --match bun`
- Inspect TypeScript processes: `./scripts/agent-task ps --match tsc`

{generated_windows_agent_section(plan)}
{generated_agent_beans_section()}
{generated_agent_sync_region(check_command(plan))}
## Rules

- Bun is the only package-manager/runtime contract for this project; do not add npm, pnpm, or Yarn fallback paths.
- Keep runtime and dev dependencies in `package.json`, with the resolved lock in `bun.lock`.
- Keep CLI behavior in `src/cli.ts` and entrypoint glue in `src/main.ts`.
- Keep runtime logging in `src/logging.ts`.
{generated_logging_agent_rules()}
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Route formatting and linting through Biome, type checking through `tsc --noEmit`, and behavior checks through `bun test`.
- Keep the `typecheck`, `lint`, and `format` package scripts Bun-invoked so a stale global Node install cannot break verification.
- Use `./scripts/check` for agent verification unless debugging one tool directly.
- Extend the sample CLI into real behavior early, and keep tests updated with that change.
- Prefer clean new-project conventions over compatibility with starter mistakes.
"""


def generated_typescript_mcp_readme(plan: BootstrapPlan) -> str:
    title = plan.project_title
    return f"""# {title}

{title} is a compact TypeScript Bun MCP server with stdio, Streamable HTTP, typed state stores, tests, type checking, first-class runtime logging, agent notes, and a deterministic verification path.

## Prerequisites

- `bun` on PATH;
- network access on first run so Bun can install dependencies.

## Usage

Install locked dependencies:

```bash
bun install --frozen-lockfile
```

Run the full verification lifecycle:

```bash
./scripts/check
```

Run tests directly:

```bash
bun test
```

Show server options:

```bash
bun run src/main.ts --help
```

Run the local stdio MCP server:

```bash
bun run src/main.ts
```

Run the HTTP MCP server:

```bash
bun run src/main.ts --transport http
```

Use JSON file state:

```bash
bun run src/main.ts --state file --state-file .mcp/state.json
```

{generated_logging_readme_section().replace("<run-command>", "bun run src/main.ts --transport http")}

{generated_windows_readme_section(plan)}
## Customization

- MCP tool, prompt, and resource registration lives in `src/mcp.ts`.
- Transport startup lives in `src/stdio.ts`, `src/http.ts`, and `src/main.ts`.
- State behavior lives behind the `StateStore` interface in `src/state.ts`.
- Runtime logging lives in `src/logging.ts`.
- Keep stdio output clean: logs and diagnostics go to stderr, never stdout.
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable project checks in `tools/supermeta-rules/` and wire them through `scripts/check`.
- Keep formatting and linting in Biome, type checking in `tsc --noEmit`, and behavior checks in `bun test`.
- Keep TypeScript and Biome package scripts invoked through Bun so the project does not depend on a separate Node install.

## First Useful Edit

Replace or extend the stub tools in `src/mcp.ts`, update the protocol tests first or in the same change, then run:

```bash
./scripts/check
bun run src/main.ts --help
```

{generated_project_docs_section()}
{generated_bootstrap_sync_region(check_command(plan))}
"""


def generated_typescript_mcp_agents(plan: BootstrapPlan) -> str:
    title = plan.project_title
    return f"""# {title} Agent Notes

This is a standalone TypeScript Bun MCP server. Keep it compact, typed, test-covered, and easy for the next agent to verify.

## Commands

- Install locked dependencies: `bun install --frozen-lockfile`
- Verify: `./scripts/check`
- Type check: `bun run typecheck`
- Lint and format check: `bun run lint`
- Test: `bun test`
- Show server help: `bun run src/main.ts --help`
- Run stdio server: `bun run src/main.ts`
- Run HTTP server: `bun run src/main.ts --transport http`
- Run with file state: `bun run src/main.ts --state file --state-file .mcp/state.json`
- Run with text logs: `LOG_LEVEL=info bun run src/main.ts --transport http`
- Run with JSON logs: `LOG_LEVEL=info LOG_FORMAT=json bun run src/main.ts --transport http`
- Beans prime: `./scripts/agent-beans prime`
- Beans check: `./scripts/agent-beans check`
- Ready backlog: `./scripts/agent-beans list --ready`
- Inspect Bun processes: `./scripts/agent-task ps --match bun`
- Inspect TypeScript processes: `./scripts/agent-task ps --match tsc`

{generated_windows_agent_section(plan)}
{generated_agent_beans_section()}
{generated_agent_sync_region(check_command(plan))}
## Rules

- Bun is the only package-manager/runtime contract for this project; do not add npm, pnpm, or Yarn fallback paths.
- Keep runtime and dev dependencies in `package.json`, with the resolved lock in `bun.lock`.
- Keep MCP tool, prompt, and resource registration in `src/mcp.ts`.
- Keep transport startup out of `src/mcp.ts` so protocol tests can exercise the server without stdio or HTTP.
- Keep state behind `StateStore`; do not bind tool handlers directly to a persistence implementation.
- Keep stdio output clean: logs and diagnostics go to stderr, never stdout.
- Keep runtime logging in `src/logging.ts`.
{generated_logging_agent_rules()}
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Route formatting and linting through Biome, type checking through `tsc --noEmit`, and behavior checks through `bun test`.
- Keep the `typecheck`, `lint`, and `format` package scripts Bun-invoked so a stale global Node install cannot break verification.
- Use `./scripts/check` for agent verification unless debugging one tool directly.
- Replace the stub MCP capabilities with real product behavior early, and keep tests updated with that change.
- Prefer clean new-project conventions over compatibility with starter mistakes.
"""


def logging_runtime_implementation(plan: BootstrapPlan) -> str:
    if plan.manifest.template_type == "csharp-dotnet-cli":
        return "C# uses the starter `LoggingConfig` and `RuntimeLogger` implementation."
    if plan.manifest.template_type == "java-gradle-cli":
        return "Java uses SLF4J with Logback configured by `LoggingConfig`."
    if plan.manifest.template_type == "python-uv-cli":
        return "Python uses the standard `logging` package configured by `logging_config.py`."
    return "TypeScript uses Pino configured by `src/logging.ts`."


def generated_logging_contract(plan: BootstrapPlan) -> str:
    event_line = (
        "- The starter emits transport startup logs when info logging is enabled."
        if plan.manifest.template_type == "typescript-bun-mcp-server"
        else "- The starter emits an `info` log after command completion with `exitCode` when info logging is enabled."
    )
    return f"""{logging_runtime_implementation(plan)}

- `LOG_LEVEL`: `trace`, `debug`, `info`, `warn`, `error`, or `off`; default `warn`.
- `LOG_FORMAT`: `text` or `json`; default `text`.
- Logs are written to stderr and normal command output stays on stdout.
- Invalid logging configuration fails before command execution with exit code 2.
{event_line}"""


def generated_architecture(plan: BootstrapPlan) -> str:
    docs = plan.manifest.generated_docs
    return f"""# {plan.project_title} Architecture

## Runtime Shape

{render_doc_text(plan, docs.summary)}

{render_doc_text(plan, docs.runtime)}

## Runtime Logging

{generated_logging_contract(plan)}

## Entrypoints

{markdown_list(render_doc_items(plan, docs.entrypoints))}

## Code Layout

Product source:

{markdown_list(render_doc_items(plan, docs.source_roots))}

Tests:

{markdown_list(render_doc_items(plan, docs.test_roots))}

## Starter Boundary

The generated CLI is intentionally small. Replace the sample behavior early, keep the verification path green, and update this file when the runtime shape changes.
"""


def generated_operations(plan: BootstrapPlan) -> str:
    docs = plan.manifest.generated_docs
    return f"""# {plan.project_title} Operations

## Verify

{markdown_code_list(render_doc_items(plan, docs.verification_commands))}

## Run

{markdown_code_list(render_doc_items(plan, docs.run_commands))}

## Logging

{generated_logging_contract(plan)}

## Backlog

```bash
./scripts/agent-beans prime
./scripts/agent-beans list
./scripts/agent-beans check
./scripts/agent-beans roadmap
```

## Windows

```powershell
{windows_check_command(plan)}
{windows_run_command(plan)}
.\\scripts\\agent-beans.ps1 prime
```

{generated_agent_sync_region(check_command(plan))}
## Troubleshooting

Use `./scripts/agent-task ps` to inspect stuck build or test processes. Use the language-specific commands in `AGENTS.md` before killing processes directly.

If `./scripts/agent-beans` fails because Beans is absent or has the wrong version, install the pinned version shown by the wrapper and rerun the command.
"""


def generated_decisions(plan: BootstrapPlan) -> str:
    docs = plan.manifest.generated_docs
    first_useful_edit = render_doc_text(plan, docs.first_useful_edit)
    return f"""# {plan.project_title} Decisions

This file contains active project decisions only. When a decision is superseded, remove it from this file after a completed or archived Bean records the old decision, why it changed, and where the current rule lives.

## Active Decisions

### Bootstrap Baseline

- Status: active
- Decision: Start from the `{plan.manifest.template_id}` starter with its checked-in verification path, agent notes, docs pack, and Beans backlog.
- Reason: A generated project should be immediately runnable, inspectable, and ready for agent handoff.

### First Useful Edit

- Status: active
- Decision: {first_useful_edit}
- Reason: The starter exists to become real product code quickly; sample behavior should not survive longer than necessary.

### Runtime Logging Contract

- Status: active
- Decision: Runtime logs use `LOG_LEVEL` and `LOG_FORMAT`, default to quiet text logs on stderr, and fail fast with exit code 2 when logging configuration is invalid.
- Reason: Generated projects should start with production-shaped observability while preserving predictable CLI output.
"""


def write_generated_beans(plan: BootstrapPlan, staged_root: Path) -> None:
    beans_dir = staged_root / ".beans"
    beans_dir.mkdir(parents=True, exist_ok=True)
    (staged_root / ".beans.yml").write_text(generated_beans_config(plan), encoding="utf-8")
    (beans_dir / ".gitignore").write_text(
        "# Generated by beans init\n.worktrees/\n.conversations/\n",
        encoding="utf-8",
    )
    for filename, content in generated_seed_beans(plan).items():
        (beans_dir / filename).write_text(content, encoding="utf-8")


def write_sync_metadata(plan: BootstrapPlan, staged_root: Path) -> None:
    sync_dir = staged_root / ".codex-bootstrap"
    reports_dir = sync_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    (reports_dir / ".gitignore").write_text("*\n!.gitignore\n", encoding="utf-8")
    metadata = {
        "schemaVersion": 1,
        "source": {
            "repository": detect_source_repository(plan.repo_root),
            "ref": detect_source_ref(plan.repo_root),
            "commit": detect_source_commit(plan.repo_root),
        },
        "template": {
            "id": plan.manifest.template_id,
            "contractVersion": plan.manifest.sync_contract.version,
        },
        "identity": sync_identity(plan),
        "managedSets": sorted(plan.manifest.sync_contract.managed_sets),
        "optOut": [],
        "managedFiles": managed_file_hashes(plan, staged_root),
        "managedRegions": managed_region_hashes(plan, staged_root),
        "verificationCommands": list(plan.manifest.sync_contract.verification_commands),
    }
    (sync_dir / "sync.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sync_identity(plan: BootstrapPlan) -> dict[str, str]:
    identity = {"projectName": plan.config.project_name}
    if plan.config.package_name is not None:
        identity["javaPackage"] = plan.config.package_name
    return identity


def managed_file_hashes(plan: BootstrapPlan, staged_root: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for path, spec in sorted(plan.manifest.sync_contract.managed_files.items()):
        target = staged_root / path
        if not target.is_file():
            raise UsageError(f"sync managed file does not exist after bootstrap: {path}")
        result[path] = {"set": spec.managed_set, "sha256": sha256_file(target)}
    return result


def managed_region_hashes(plan: BootstrapPlan, staged_root: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for key, spec in sorted(plan.manifest.sync_contract.managed_regions.items()):
        target = staged_root / spec.path
        if not target.is_file():
            raise UsageError(f"sync managed region file does not exist after bootstrap: {spec.path}")
        body = extract_managed_region(target.read_text(encoding="utf-8"), spec.region_id)
        result[key] = {
            "set": spec.managed_set,
            "path": spec.path,
            "id": spec.region_id,
            "sha256": sha256_text(body),
        }
    return result


def extract_managed_region(text: str, region_id: str) -> str:
    begin = f"<!-- codex-bootstrap:begin {region_id} -->"
    end = f"<!-- codex-bootstrap:end {region_id} -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise UsageError(f"sync managed region {region_id} must have exactly one begin and end marker")
    begin_index = text.index(begin) + len(begin)
    end_index = text.index(end)
    if end_index < begin_index:
        raise UsageError(f"sync managed region {region_id} end marker appears before begin marker")
    body = text[begin_index:end_index]
    if body.startswith("\n"):
        body = body[1:]
    return body


def sha256_file(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def sha256_text(value: str) -> str:
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def detect_source_repository(repo_root: Path) -> str:
    return git_output_or(
        repo_root,
        ["git", "remote", "get-url", "origin"],
        "https://github.com/Jamezz/codex-bootstrap.git",
    )


def detect_source_ref(repo_root: Path) -> str:
    return git_output_or(repo_root, ["git", "branch", "--show-current"], "main") or "main"


def detect_source_commit(repo_root: Path) -> str:
    return git_output_or(repo_root, ["git", "rev-parse", "HEAD"], "unknown")


def git_output_or(repo_root: Path, command: list[str], fallback: str) -> str:
    result = subprocess.run(
        command,
        cwd=repo_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return fallback
    return result.stdout.strip() or fallback


def generated_beans_config(plan: BootstrapPlan) -> str:
    return f"""# Beans configuration
# See: https://github.com/hmans/beans
project:
  name: {plan.project_title}
beans:
  path: .beans
  prefix: {plan.config.project_name}-
  id_length: 4
  default_status: todo
  default_type: task
agent:
  enabled: true
  default_mode: act
"""


def generated_seed_beans(plan: BootstrapPlan) -> dict[str, str]:
    prefix = f"{plan.config.project_name}-"
    milestone = f"{prefix}m001"
    feature = f"{prefix}f001"
    architecture_task = f"{prefix}t001"
    ci_task = f"{prefix}t002"
    return {
        f"{milestone}--ship-first-real-project-slice.md": bean_markdown(
            "Ship first real project slice",
            "milestone",
            "A working first slice should replace the starter behavior, keep verification green, and leave the docs accurate.",
            order="a",
        ),
        f"{feature}--replace-starter-behavior.md": bean_markdown(
            "Replace starter behavior with real product behavior",
            "feature",
            "Turn the generated CLI into the first useful product path. Update tests before or with the behavior change.",
            parent=milestone,
            order="b",
        ),
        f"{architecture_task}--lock-architecture-and-decisions.md": bean_markdown(
            "Lock architecture and active decisions",
            "task",
            "Review `docs/ARCHITECTURE.md` and `docs/DECISIONS.md` after the first real behavior lands. Keep only active decisions in the docs.",
            parent=feature,
            order="c",
        ),
        f"{ci_task}--add-ci-and-release-verification.md": bean_markdown(
            "Add CI and release verification",
            "task",
            "Choose the project CI path and make the default verification command run there without hidden local state.",
            parent=feature,
            order="d",
        ),
    }


def bean_markdown(title: str, bean_type: str, body: str, order: str, parent: str = "") -> str:
    parent_line = f"parent: {parent}\n" if parent else ""
    return f"""---
title: {title}
status: todo
type: {bean_type}
priority: normal
order: {order}
{parent_line}---

{body}
"""


def markdown_list(items: tuple[str, ...]) -> str:
    return "\n".join(f"- `{item}`" for item in items)


def markdown_code_list(items: tuple[str, ...]) -> str:
    return "\n".join(f"```bash\n{item}\n```" for item in items)


def render_doc_items(plan: BootstrapPlan, items: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(render_doc_text(plan, item) for item in items)


def render_doc_text(plan: BootstrapPlan, text: str) -> str:
    replacements = {
        plan.manifest.template_id: plan.config.project_name,
    }
    if plan.config.package_name is not None:
        replacements["com.example"] = plan.config.package_name
        replacements["com/example"] = plan.config.package_name.replace(".", "/")
    if plan.manifest.template_type == "python-uv-cli":
        replacements["python_uv_cli"] = python_module_from_slug(plan.config.project_name)
    if plan.manifest.template_type == "csharp-dotnet-cli":
        project_name = csharp_project_name_from_slug(plan.config.project_name)
        replacements["csharpdotnetcli"] = project_name.lower()
        replacements["CsharpDotnetCli"] = project_name

    rendered = text
    for old, new in replacements.items():
        rendered = rendered.replace(old, new)
    return rendered


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
    if plan.config.package_name is not None:
        print(f"  package: {plan.config.package_name}")
    if plan.manifest.template_type == "python-uv-cli":
        print(f"  python module: {python_module_from_slug(plan.config.project_name)}")
    if plan.manifest.template_type == "csharp-dotnet-cli":
        print(f"  C# namespace: Generated.{csharp_project_name_from_slug(plan.config.project_name)}")
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


def python_module_from_slug(slug: str) -> str:
    validate_project_name(slug)
    module_name = slug.replace("-", "_")
    if keyword.iskeyword(module_name):
        raise UsageError(f"project name would create a Python keyword module: '{module_name}'")
    return module_name


def csharp_project_name_from_slug(slug: str) -> str:
    validate_project_name(slug)
    project_name = "".join(part[:1].upper() + part[1:] for part in slug.split("-"))
    if project_name.lower() in CSHARP_KEYWORDS:
        return f"{project_name}App"
    return project_name


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


def parse_generated_docs(raw: Any) -> GeneratedDocs:
    if not isinstance(raw, dict):
        raise UsageError("generatedDocs must be an object")
    return GeneratedDocs(
        summary=require_string(raw, "summary"),
        runtime=require_string(raw, "runtime"),
        entrypoints=tuple(require_string_list(raw, "entrypoints")),
        source_roots=tuple(require_string_list(raw, "sourceRoots")),
        test_roots=tuple(require_string_list(raw, "testRoots")),
        verification_commands=tuple(require_string_list(raw, "verificationCommands")),
        run_commands=tuple(require_string_list(raw, "runCommands")),
        first_useful_edit=require_string(raw, "firstUsefulEdit"),
    )


def parse_sync_contract(raw: Any) -> SyncContract:
    if not isinstance(raw, dict):
        raise UsageError("syncContract must be an object")
    managed_sets: dict[str, ManagedSetSpec] = {}
    for index, item in enumerate(require_object_list(raw, "managedSets")):
        managed_set = require_string(item, "id")
        files = tuple(
            ManagedFileSpec(
                path=require_string(file_item, "path"),
                managed_set=managed_set,
            )
            for file_item in require_object_list(item, "files", allow_missing=True)
            if require_string(file_item, "mode") == "whole-file"
        )
        regions = tuple(
            ManagedRegionSpec(
                path=require_string(region_item, "path"),
                region_id=require_string(region_item, "id"),
                managed_set=managed_set,
            )
            for region_item in require_object_list(item, "regions", allow_missing=True)
        )
        if managed_set in managed_sets:
            raise UsageError(f"syncContract managedSets[{index}] duplicates id {managed_set}")
        managed_sets[managed_set] = ManagedSetSpec(
            managed_set=managed_set,
            description=require_string(item, "description"),
            files=files,
            regions=regions,
        )
    return SyncContract(
        version=require_int(raw, "version"),
        managed_sets=managed_sets,
        verification_commands=tuple(require_string_list(raw, "verificationCommands")),
        migration_notes=tuple(require_string_list(raw, "migrationNotes")),
    )


def require_object_list(
    raw: dict[str, Any], key: str, allow_missing: bool = False
) -> list[dict[str, Any]]:
    value = raw.get(key, [] if allow_missing else None)
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise UsageError(f"{key} must be an array of objects")
    return value


def require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise UsageError(f"{key} must be an integer")
    return value


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
