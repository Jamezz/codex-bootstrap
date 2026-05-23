from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.pages.build_pages import build_pages


REPO_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = REPO_ROOT / "site" / "install.sh"
WINDOWS_INSTALLER = REPO_ROOT / "site" / "install.ps1"


class PagesBuildTest(unittest.TestCase):
    def test_builds_static_pages_artifacts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-pages-") as temp_dir:
            output = Path(temp_dir) / "pages"

            build_pages(output)

            self.assertTrue((output / "index.html").is_file())
            self.assertTrue((output / "install.sh").is_file())
            self.assertTrue((output / "install.ps1").is_file())
            self.assertTrue((output / "templates.json").is_file())
            self.assertTrue((output / "install.sh.sha256").is_file())
            self.assertTrue((output / "install.ps1.sha256").is_file())
            self.assertTrue((output / "checksums.txt").is_file())

            templates = json.loads((output / "templates.json").read_text(encoding="utf-8"))
            self.assertEqual("java-gradle-cli", templates["defaultTemplate"])
            self.assertEqual(
                "https://jamezz.github.io/codex-bootstrap/install.ps1",
                templates["windowsInstallUrl"],
            )
            manifest_ids = sorted(
                path.parent.name
                for path in (REPO_ROOT / "templates").glob("*/bootstrap-template.json")
            )
            self.assertEqual(
                manifest_ids,
                [template["id"] for template in templates["templates"]],
            )
            java_template = next(
                template for template in templates["templates"] if template["id"] == "java-gradle-cli"
            )
            self.assertTrue(java_template["syncCapable"])
            self.assertEqual(1, java_template["syncContractVersion"])
            self.assertIn("agent-scripts", java_template["managedSets"])

            checksums = (output / "checksums.txt").read_text(encoding="utf-8")
            self.assertIn("  install.sh\n", checksums)
            self.assertIn("  install.ps1\n", checksums)
            self.assertIn("  templates.json\n", checksums)
            self.assertIn("  index.html\n", checksums)


class InstallerTest(unittest.TestCase):
    def test_installer_shell_syntax_and_help(self) -> None:
        run_checked(["bash", "-n", str(INSTALLER)])
        help_result = run_checked([str(INSTALLER), "--help"])

        self.assertIn("Codex Bootstrap installer", help_result.stdout)
        self.assertIn("--list-templates", help_result.stdout)

    def test_windows_installer_static_contract(self) -> None:
        installer = WINDOWS_INSTALLER.read_text(encoding="utf-8")

        self.assertIn("Codex Bootstrap Windows installer", installer)
        self.assertIn("param(", installer)
        self.assertIn("Install-CodexBootstrap", installer)
        self.assertIn("git clone --depth 1", installer)
        self.assertIn("python", installer)
        self.assertIn("bootstrap", installer)

    def test_lists_templates_from_generated_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-pages-") as temp_dir:
            output = Path(temp_dir) / "pages"
            build_pages(output)

            result = run_checked(
                [
                    str(INSTALLER),
                    "--list-templates",
                    "--templates-file",
                    str(output / "templates.json"),
                ]
            )

            self.assertIn("java-gradle-cli: Java Gradle CLI", result.stdout)
            self.assertIn("csharp-dotnet-cli: C# .NET CLI", result.stdout)
            self.assertIn("python-uv-cli: Python uv CLI", result.stdout)
            self.assertIn("typescript-bun-cli: TypeScript Bun CLI", result.stdout)
            self.assertIn(
                "typescript-bun-mcp-server: TypeScript Bun MCP Server",
                result.stdout,
            )

    def test_dry_run_prints_local_clone_plan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-install-") as temp_dir:
            result = run_checked(
                [
                    str(INSTALLER),
                    "sample-app",
                    "--template",
                    "python-uv-cli",
                    "--repo",
                    f"file://{REPO_ROOT}",
                    "--ref",
                    "HEAD",
                    "--dir",
                    temp_dir,
                    "--dry-run",
                ]
            )

            self.assertIn("Install plan:", result.stdout)
            self.assertIn("template: python-uv-cli", result.stdout)
            self.assertIn(f"target: {Path(temp_dir) / 'sample-app'}", result.stdout)
            self.assertFalse((Path(temp_dir) / "sample-app").exists())

    @unittest.skipIf(shutil.which("git") is None, "git is required for installer smoke test")
    def test_installs_each_template_from_local_repo(self) -> None:
        cases = [
            ("csharp-dotnet-cli", "csharp-app"),
            ("java-gradle-cli", "java-app"),
            ("python-uv-cli", "python-app"),
            ("typescript-bun-cli", "typescript-app"),
            ("typescript-bun-mcp-server", "mcp-app"),
        ]
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-install-") as temp_dir:
            temp_root = Path(temp_dir)
            source_repo = temp_root / "source"
            install_root = temp_root / "installs"
            copy_bootstrap_source(source_repo)
            initialize_source_repo(source_repo)

            for template, slug in cases:
                with self.subTest(template=template):
                    run_checked(
                        [
                            str(INSTALLER),
                            slug,
                            "--template",
                            template,
                            "--repo",
                            f"file://{source_repo}",
                            "--ref",
                            "HEAD",
                            "--dir",
                            str(install_root),
                        ],
                        timeout=180,
                    )

                    checkout = install_root / slug
                    self.assertTrue((checkout / ".git").is_dir())
                    self.assertFalse((checkout / "bootstrap").exists())
                    self.assertFalse((checkout / "templates").exists())
                    self.assertFalse((checkout / ".github").exists())
                    self.assertFalse((checkout / "site").exists())
                    self.assertTrue((checkout / "README.md").is_file())

            self.assertTrue(
                (install_root / "csharp-app" / "src" / "CsharpApp" / "CsharpApp.csproj").is_file()
            )
            self.assertTrue(
                (
                    install_root
                    / "java-app"
                    / "src"
                    / "main"
                    / "java"
                    / "com"
                    / "generated"
                    / "javaapp"
                    / "App.java"
                ).is_file()
            )
            self.assertTrue(
                (install_root / "python-app" / "src" / "python_app" / "cli.py").is_file()
            )
            self.assertTrue((install_root / "typescript-app" / "src" / "cli.ts").is_file())
            self.assertTrue((install_root / "mcp-app" / "src" / "mcp.ts").is_file())


def run_checked(
    command: list[str],
    timeout: int = 60,
    cwd: Path = REPO_ROOT,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(
            f"command failed with exit {result.returncode}: {' '.join(command)}\n{result.stdout}"
    )
    return result


def copy_bootstrap_source(destination: Path) -> None:
    shutil.copytree(
        REPO_ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".bun",
            ".dotnet",
            ".gradle",
            ".mypy_cache",
            ".nuget",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "build",
            "coverage",
            "dist",
            "node_modules",
            "*.pyc",
            "*.tsbuildinfo",
        ),
    )


def initialize_source_repo(source_repo: Path) -> None:
    run_checked(["git", "init"], cwd=source_repo)
    run_checked(["git", "add", "."], cwd=source_repo)
    run_checked(
        [
            "git",
            "-c",
            "user.name=Codex Bootstrap Test",
            "-c",
            "user.email=codex-bootstrap@example.invalid",
            "commit",
            "-m",
            "snapshot",
        ],
        cwd=source_repo,
    )
