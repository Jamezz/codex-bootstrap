from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.bootstrap.bootstrap import (  # noqa: E402
    BootstrapConfig,
    BootstrapPlan,
    TemplateManifest,
    UsageError,
    assert_safe_clear_path,
    csharp_project_name_from_slug,
    generated_nag_docs_region,
    java_package_to_path,
    python_module_from_slug,
    stage_template,
    title_from_slug,
    validate_java_package,
    validate_project_name,
)


class ValidationTest(unittest.TestCase):
    def test_validates_project_name_slug(self) -> None:
        validate_project_name("sample-app")
        validate_project_name("a1-service2")
        self.assertEqual("Sample App", title_from_slug("sample-app"))

    def test_rejects_invalid_project_names(self) -> None:
        for value in ("SampleApp", "sample_app", "sample--app", "1sample", "sample-"):
            with self.subTest(value=value):
                with self.assertRaises(UsageError):
                    validate_project_name(value)

    def test_validates_java_package(self) -> None:
        validate_java_package("com.acme.sample")
        self.assertEqual(Path("com/acme/sample"), java_package_to_path("com.acme.sample"))

    def test_rejects_invalid_java_packages(self) -> None:
        for value in ("sample", "com.Acme", "com.acme-service", "com.int.sample", "com.1acme"):
            with self.subTest(value=value):
                with self.assertRaises(UsageError):
                    validate_java_package(value)

    def test_derives_python_module_from_project_name(self) -> None:
        self.assertEqual("sample_app", python_module_from_slug("sample-app"))
        self.assertEqual("a1_service2", python_module_from_slug("a1-service2"))

    def test_rejects_python_keyword_module_names(self) -> None:
        with self.assertRaises(UsageError):
            python_module_from_slug("class")

    def test_derives_csharp_project_name_from_project_name(self) -> None:
        self.assertEqual("SampleApp", csharp_project_name_from_slug("sample-app"))
        self.assertEqual("A1Service2", csharp_project_name_from_slug("a1-service2"))
        self.assertEqual("ClassApp", csharp_project_name_from_slug("class"))


class ManifestTest(unittest.TestCase):
    def test_loads_existing_repo_control_manifest(self) -> None:
        manifest = TemplateManifest.load(REPO_ROOT, "existing-repo-control")

        self.assertEqual("existing-repo-control", manifest.template_id)
        self.assertEqual("existing-repo-control", manifest.template_type)
        self.assertEqual(("name",), manifest.required_inputs)
        self.assertIn("./scripts/agent-bootstrap sync --dry-run", manifest.verification_commands)
        self.assertIn("Existing Repo Control Plane", manifest.display_name)
        self.assertIn("tools/supermeta-bootstrap/bootstrap_adopt.py", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-rules/check.py", manifest.sync_contract.managed_files)
        self.assertEqual({}, manifest.sync_contract.managed_regions)
        self.assertIn("velocity-tools", manifest.sync_contract.managed_sets)
        self.assertIn(".codex-bootstrap/checks.json", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-rules/repeated_helpers.py", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-rules/repeated_helpers_test.py", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-rules/requirements.txt", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-rules/workspace.py", manifest.sync_contract.managed_files)

    def test_loads_csharp_template_manifest(self) -> None:
        manifest = TemplateManifest.load(REPO_ROOT, "csharp-dotnet-cli")

        self.assertEqual("csharp-dotnet-cli", manifest.template_id)
        self.assertEqual("csharp-dotnet-cli", manifest.template_type)
        self.assertEqual(("name",), manifest.required_inputs)
        self.assertIn("./scripts/check", manifest.verification_commands)
        self.assertIn("C# .NET", manifest.generated_docs.summary)
        self.assertIn("src/CsharpDotnetCli/App.cs", manifest.generated_docs.entrypoints)
        self.assertIn("src/CsharpDotnetCli/LoggingConfig.cs", manifest.generated_docs.entrypoints)
        self.assertEqual(
            [
                "scripts/agent-dotnet",
                "scripts/agent-dotnet.ps1",
                "scripts/agent-bootstrap",
                "scripts/agent-bootstrap.ps1",
                "scripts/agent-beans",
                "scripts/agent-beans.ps1",
                "scripts/agent-coord",
                "scripts/agent-coord.ps1",
                "scripts/agent-nag",
                "scripts/agent-nag.ps1",
                "scripts/agent-task",
                "scripts/agent-task.ps1",
                "scripts/agent-smart-check",
                "scripts/agent-smart-check.ps1",
                "scripts/agent-fix-loop",
                "scripts/agent-fix-loop.ps1",
                "tools/supermeta-check",
                "tools/supermeta-fix",
                "tools/supermeta-agent",
                "tools/supermeta-beans",
                "tools/supermeta-task",
                "tools/supermeta-rules",
                "tools/supermeta-bootstrap",
                "tools/supermeta-nag",
            ],
            [path.source for path in manifest.support_paths],
        )
        self.assertIn("scripts/agent-coord", manifest.sync_contract.managed_files)
        self.assertIn("scripts/agent-nag", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-agent/agent.py", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-nag/nag.py", manifest.sync_contract.managed_files)
        assert_velocity_manifest_contract(self, manifest)

    def test_stage_template_does_not_rewrite_copied_support_tools(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-stage-") as temp_dir:
            staged_root = Path(temp_dir) / "sample-app"
            plan = BootstrapPlan(
                repo_root=REPO_ROOT,
                manifest=TemplateManifest.load(REPO_ROOT, "java-gradle-cli"),
                config=BootstrapConfig(
                    template_id="java-gradle-cli",
                    project_name="sample-app",
                    package_name="com.acme.sample",
                    yes=True,
                    dry_run=False,
                    force=False,
                ),
            )

            stage_template(plan, staged_root)

            sync_test = read_text(staged_root / "tools" / "supermeta-bootstrap" / "bootstrap_sync_test.py")
            gradle_readme = read_text(staged_root / "tools" / "supermeta-gradle" / "README.md")
            rules_readme = read_text(staged_root / "tools" / "supermeta-rules" / "README.md")
            gradle_wrapper = read_text(staged_root / "scripts" / "agent-gradle")
            self.assertIn('template_id="java-gradle-cli"', sync_test)
            self.assertNotIn('template_id="sample-app"', sync_test)
            self.assertIn("example: scripts/agent-gradle . test", gradle_wrapper)
            self.assertIn("./scripts/agent-gradle . check", gradle_readme)
            self.assertIn(
                "python3 tools/supermeta-rules/check.py --config supermeta-rules.json --root .",
                rules_readme,
            )
            self.assertNotIn("templates/sample-app", gradle_readme)

    def test_nag_operations_region_stays_stable_for_old_helper_transition(self) -> None:
        region = generated_nag_docs_region()

        self.assertIn(
            "Project-specific reminders belong in `.codex-bootstrap/nags.local.json`. "
            "Runtime state lives in `.codex-bootstrap/nag-state.json`.\n",
            region,
        )
        self.assertNotIn("ignored by generated `.gitignore`", region)

    def test_loads_java_template_manifest(self) -> None:
        manifest = TemplateManifest.load(REPO_ROOT, "java-gradle-cli")

        self.assertEqual("java-gradle-cli", manifest.template_id)
        self.assertEqual("java-gradle-cli", manifest.template_type)
        self.assertEqual(("name", "package"), manifest.required_inputs)
        self.assertIn("./scripts/agent-gradle . check", manifest.verification_commands)
        self.assertIn("Java Gradle", manifest.generated_docs.summary)
        self.assertIn("src/main/java/com/example/App.java", manifest.generated_docs.entrypoints)
        self.assertIn("src/main/java/com/example/LoggingConfig.java", manifest.generated_docs.entrypoints)
        self.assertEqual(
            [
                "scripts/agent-gradle",
                "scripts/agent-gradle.ps1",
                "scripts/agent-bootstrap",
                "scripts/agent-bootstrap.ps1",
                "scripts/agent-beans",
                "scripts/agent-beans.ps1",
                "scripts/agent-coord",
                "scripts/agent-coord.ps1",
                "scripts/agent-nag",
                "scripts/agent-nag.ps1",
                "scripts/agent-task",
                "scripts/agent-task.ps1",
                "scripts/agent-smart-check",
                "scripts/agent-smart-check.ps1",
                "scripts/agent-fix-loop",
                "scripts/agent-fix-loop.ps1",
                "tools/supermeta-check",
                "tools/supermeta-fix",
                "tools/supermeta-gradle",
                "tools/supermeta-agent",
                "tools/supermeta-beans",
                "tools/supermeta-task",
                "tools/supermeta-rules",
                "tools/supermeta-bootstrap",
                "tools/supermeta-nag",
            ],
            [path.source for path in manifest.support_paths],
        )
        self.assertEqual(2, manifest.sync_contract.version)
        self.assertIn("agent-scripts", manifest.sync_contract.managed_sets)
        self.assertIn("agent-nags", manifest.sync_contract.managed_sets)
        self.assertFalse(manifest.sync_contract.managed_sets["language-checks"].auto_enable)
        self.assertIn("scripts/agent-bootstrap", manifest.sync_contract.managed_files)
        self.assertIn("scripts/agent-coord", manifest.sync_contract.managed_files)
        self.assertIn("scripts/agent-nag", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-agent/agent.py", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-nag/nag.py", manifest.sync_contract.managed_files)
        self.assertIn("AGENTS.md:generated-docs/bootstrap-sync", manifest.sync_contract.managed_regions)
        self.assertIn("README.md:generated-docs/agent-nags", manifest.sync_contract.managed_regions)
        assert_velocity_manifest_contract(self, manifest)

    def test_loads_python_template_manifest(self) -> None:
        manifest = TemplateManifest.load(REPO_ROOT, "python-uv-cli")

        self.assertEqual("python-uv-cli", manifest.template_id)
        self.assertEqual("python-uv-cli", manifest.template_type)
        self.assertEqual(("name",), manifest.required_inputs)
        self.assertIn("./scripts/check", manifest.verification_commands)
        self.assertIn("uv run --no-editable python-uv-cli", manifest.verification_commands)
        self.assertIn("Python uv", manifest.generated_docs.summary)
        self.assertIn("src/python_uv_cli/cli.py", manifest.generated_docs.entrypoints)
        self.assertIn("src/python_uv_cli/logging_config.py", manifest.generated_docs.entrypoints)
        self.assertEqual(
            [
                "scripts/agent-bootstrap",
                "scripts/agent-bootstrap.ps1",
                "scripts/agent-beans",
                "scripts/agent-beans.ps1",
                "scripts/agent-coord",
                "scripts/agent-coord.ps1",
                "scripts/agent-nag",
                "scripts/agent-nag.ps1",
                "scripts/agent-task",
                "scripts/agent-task.ps1",
                "scripts/agent-smart-check",
                "scripts/agent-smart-check.ps1",
                "scripts/agent-fix-loop",
                "scripts/agent-fix-loop.ps1",
                "tools/supermeta-check",
                "tools/supermeta-fix",
                "tools/supermeta-agent",
                "tools/supermeta-beans",
                "tools/supermeta-task",
                "tools/supermeta-rules",
                "tools/supermeta-bootstrap",
                "tools/supermeta-nag",
            ],
            [path.source for path in manifest.support_paths],
        )
        self.assertIn("scripts/agent-coord", manifest.sync_contract.managed_files)
        self.assertIn("scripts/agent-nag", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-agent/agent.py", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-nag/nag.py", manifest.sync_contract.managed_files)
        assert_velocity_manifest_contract(self, manifest)

    def test_loads_rust_template_manifest(self) -> None:
        manifest = TemplateManifest.load(REPO_ROOT, "rust-cargo-cli")

        self.assertEqual("rust-cargo-cli", manifest.template_id)
        self.assertEqual("rust-cargo-cli", manifest.template_type)
        self.assertEqual(("name",), manifest.required_inputs)
        self.assertIn("./scripts/check", manifest.verification_commands)
        self.assertIn("cargo run --quiet", manifest.verification_commands)
        self.assertIn("Rust Cargo", manifest.generated_docs.summary)
        self.assertIn("src/main.rs", manifest.generated_docs.entrypoints)
        self.assertIn("src/logging.rs", manifest.generated_docs.entrypoints)
        self.assertEqual(
            [
                "scripts/agent-bootstrap",
                "scripts/agent-bootstrap.ps1",
                "scripts/agent-beans",
                "scripts/agent-beans.ps1",
                "scripts/agent-coord",
                "scripts/agent-coord.ps1",
                "scripts/agent-nag",
                "scripts/agent-nag.ps1",
                "scripts/agent-task",
                "scripts/agent-task.ps1",
                "scripts/agent-smart-check",
                "scripts/agent-smart-check.ps1",
                "scripts/agent-fix-loop",
                "scripts/agent-fix-loop.ps1",
                "tools/supermeta-check",
                "tools/supermeta-fix",
                "tools/supermeta-agent",
                "tools/supermeta-beans",
                "tools/supermeta-task",
                "tools/supermeta-rules",
                "tools/supermeta-bootstrap",
                "tools/supermeta-nag",
            ],
            [path.source for path in manifest.support_paths],
        )
        self.assertIn("scripts/agent-coord", manifest.sync_contract.managed_files)
        self.assertIn("scripts/agent-nag", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-agent/agent.py", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-nag/nag.py", manifest.sync_contract.managed_files)
        assert_velocity_manifest_contract(self, manifest)

    def test_loads_typescript_template_manifest(self) -> None:
        manifest = TemplateManifest.load(REPO_ROOT, "typescript-bun-cli")

        self.assertEqual("typescript-bun-cli", manifest.template_id)
        self.assertEqual("typescript-bun-cli", manifest.template_type)
        self.assertEqual(("name",), manifest.required_inputs)
        self.assertIn("./scripts/check", manifest.verification_commands)
        self.assertIn("bun run src/main.ts", manifest.verification_commands)
        self.assertIn("TypeScript Bun", manifest.generated_docs.summary)
        self.assertIn("src/main.ts", manifest.generated_docs.entrypoints)
        self.assertIn("src/logging.ts", manifest.generated_docs.entrypoints)
        self.assertEqual(
            [
                "scripts/agent-bootstrap",
                "scripts/agent-bootstrap.ps1",
                "scripts/agent-beans",
                "scripts/agent-beans.ps1",
                "scripts/agent-coord",
                "scripts/agent-coord.ps1",
                "scripts/agent-nag",
                "scripts/agent-nag.ps1",
                "scripts/agent-task",
                "scripts/agent-task.ps1",
                "scripts/agent-smart-check",
                "scripts/agent-smart-check.ps1",
                "scripts/agent-fix-loop",
                "scripts/agent-fix-loop.ps1",
                "tools/supermeta-check",
                "tools/supermeta-fix",
                "tools/supermeta-agent",
                "tools/supermeta-beans",
                "tools/supermeta-task",
                "tools/supermeta-rules",
                "tools/supermeta-bootstrap",
                "tools/supermeta-nag",
            ],
            [path.source for path in manifest.support_paths],
        )
        self.assertIn("scripts/agent-coord", manifest.sync_contract.managed_files)
        self.assertIn("scripts/agent-nag", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-agent/agent.py", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-nag/nag.py", manifest.sync_contract.managed_files)
        assert_velocity_manifest_contract(self, manifest)

    def test_loads_typescript_mcp_server_template_manifest(self) -> None:
        manifest = TemplateManifest.load(REPO_ROOT, "typescript-bun-mcp-server")

        self.assertEqual("typescript-bun-mcp-server", manifest.template_id)
        self.assertEqual("typescript-bun-mcp-server", manifest.template_type)
        self.assertEqual(("name",), manifest.required_inputs)
        self.assertIn("./scripts/check", manifest.verification_commands)
        self.assertIn("bun run src/main.ts --help", manifest.verification_commands)
        self.assertIn("TypeScript Bun MCP", manifest.generated_docs.summary)
        self.assertIn("src/mcp.ts", manifest.generated_docs.entrypoints)
        self.assertIn("src/state.ts", manifest.generated_docs.entrypoints)
        self.assertEqual(
            [
                "scripts/agent-bootstrap",
                "scripts/agent-bootstrap.ps1",
                "scripts/agent-beans",
                "scripts/agent-beans.ps1",
                "scripts/agent-coord",
                "scripts/agent-coord.ps1",
                "scripts/agent-nag",
                "scripts/agent-nag.ps1",
                "scripts/agent-task",
                "scripts/agent-task.ps1",
                "scripts/agent-smart-check",
                "scripts/agent-smart-check.ps1",
                "scripts/agent-fix-loop",
                "scripts/agent-fix-loop.ps1",
                "tools/supermeta-check",
                "tools/supermeta-fix",
                "tools/supermeta-agent",
                "tools/supermeta-beans",
                "tools/supermeta-task",
                "tools/supermeta-rules",
                "tools/supermeta-bootstrap",
                "tools/supermeta-nag",
            ],
            [path.source for path in manifest.support_paths],
        )
        self.assertIn("scripts/agent-coord", manifest.sync_contract.managed_files)
        self.assertIn("scripts/agent-nag", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-agent/agent.py", manifest.sync_contract.managed_files)
        self.assertIn("tools/supermeta-nag/nag.py", manifest.sync_contract.managed_files)
        assert_velocity_manifest_contract(self, manifest)


class SafetyTest(unittest.TestCase):
    def test_refuses_to_clear_filesystem_root(self) -> None:
        with self.assertRaises(UsageError):
            assert_safe_clear_path(Path("/"))


class BootstrapSmokeTest(unittest.TestCase):
    @unittest.skipIf(shutil.which("git") is None, "git is required for bootstrap smoke test")
    def test_bootstrap_rewrites_java_template_checkout_into_standalone_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            checkout = temp_root / "sample-app"
            copy_bootstrap_checkout(checkout)
            initialize_fake_origin(checkout)

            run_checked(
                [
                    "./bootstrap",
                    "--template",
                    "java-gradle-cli",
                    "--name",
                    "sample-app",
                    "--package",
                    "com.acme.sample",
                    "--yes",
                ],
                cwd=checkout,
            )

            self.assertFalse((checkout / "templates").exists())
            self.assertFalse((checkout / "environments").exists())
            self.assertFalse((checkout / ".github").exists())
            self.assertFalse((checkout / "site").exists())
            self.assertFalse((checkout / "bootstrap").exists())
            self.assertFalse((checkout / "bootstrap.ps1").exists())
            self.assertFalse((checkout / "tools" / "bootstrap").exists())
            self.assertTrue((checkout / "scripts" / "agent-gradle").is_file())
            self.assertTrue((checkout / "scripts" / "agent-gradle.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-bootstrap").is_file())
            self.assertTrue((checkout / "scripts" / "agent-bootstrap.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-beans").is_file())
            self.assertTrue((checkout / "scripts" / "agent-beans.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-coord").is_file())
            self.assertTrue((checkout / "scripts" / "agent-coord.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-nag").is_file())
            self.assertTrue((checkout / "scripts" / "agent-nag.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-smart-check").is_file())
            self.assertTrue((checkout / "scripts" / "agent-smart-check.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-fix-loop").is_file())
            self.assertTrue((checkout / "scripts" / "agent-fix-loop.ps1").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-bootstrap" / "bootstrap_sync.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-gradle" / "gradle.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-agent" / "agent.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-nag" / "nag.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-beans" / "beans.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-task" / "task.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "check.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-check" / "check.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-fix" / "fix.py").is_file())
            self.assertTrue((checkout / ".codex-bootstrap" / "sync.json").is_file())
            self.assertTrue((checkout / ".codex-bootstrap" / "reports" / ".gitignore").is_file())
            self.assertTrue((checkout / ".codex-bootstrap" / "checks.json").is_file())
            self.assertTrue((checkout / ".codex-bootstrap" / "nags.json").is_file())
            self.assertTrue((checkout / ".codex-bootstrap" / "nags.local.json").is_file())
            self.assertFalse((checkout / ".codex-bootstrap" / "nag-state.json").exists())
            self.assertIn(".codex-bootstrap/nag-state.json", read_text(checkout / ".gitignore"))
            self.assertIn(".codex-bootstrap/fix-loop/", read_text(checkout / ".gitignore"))
            self.assertIn(".codex-bootstrap/cleanup-quarantine/", read_text(checkout / ".gitignore"))
            sync_metadata = json.loads(
                (checkout / ".codex-bootstrap" / "sync.json").read_text(encoding="utf-8")
            )
            checks = json.loads((checkout / ".codex-bootstrap" / "checks.json").read_text(encoding="utf-8"))
            nags = json.loads((checkout / ".codex-bootstrap" / "nags.json").read_text(encoding="utf-8"))
            self.assertEqual(1, sync_metadata["schemaVersion"])
            self.assertEqual("java-gradle-cli", sync_metadata["template"]["id"])
            self.assertEqual(2, sync_metadata["template"]["contractVersion"])
            self.assertEqual("sample-app", sync_metadata["identity"]["projectName"])
            self.assertEqual("com.acme.sample", sync_metadata["identity"]["javaPackage"])
            self.assertIn("agent-scripts", sync_metadata["managedSets"])
            self.assertIn("agent-nags", sync_metadata["managedSets"])
            self.assertIn("velocity-tools", sync_metadata["managedSets"])
            self.assertIn("scripts/agent-bootstrap", sync_metadata["managedFiles"])
            self.assertIn("scripts/agent-nag", sync_metadata["managedFiles"])
            self.assertIn(".codex-bootstrap/checks.json", sync_metadata["managedFiles"])
            self.assertIn(".codex-bootstrap/nags.json", sync_metadata["managedFiles"])
            self.assertNotIn(".codex-bootstrap/nags.local.json", sync_metadata["managedFiles"])
            self.assertIn("AGENTS.md:generated-docs/bootstrap-sync", sync_metadata["managedRegions"])
            self.assertIn("README.md:generated-docs/agent-nags", sync_metadata["managedRegions"])
            self.assertIn("README.md:generated-docs/velocity-tools", sync_metadata["managedRegions"])
            self.assertIn("AGENTS.md:generated-docs/velocity-tools", sync_metadata["managedRegions"])
            self.assertIn("docs/OPERATIONS.md:generated-docs/velocity-tools", sync_metadata["managedRegions"])
            self.assertEqual(1, checks["schemaVersion"])
            self.assertEqual("java-gradle-cli", checks["templateId"])
            lanes_by_id = {lane["id"]: lane for lane in checks["lanes"]}
            self.assertIn("full", lanes_by_id)
            self.assertEqual("fast", lanes_by_id["java-test"]["cost"])
            self.assertIn("test", lanes_by_id["java-test"]["tags"])
            self.assertEqual(["java"], lanes_by_id["java-test"]["requires"])
            self.assertEqual(180, lanes_by_id["java-test"]["timeoutSeconds"])
            self.assertEqual("full", lanes_by_id["full"]["cost"])
            self.assertEqual(600, lanes_by_id["full"]["timeoutSeconds"])
            self.assertEqual(1, nags["schemaVersion"])
            self.assertIn("bootstrap-update-check", [item["id"] for item in nags["nags"]])
            self.assertIn("post-run-backlog-check", [item["id"] for item in nags["nags"]])

            remotes = run_checked(["git", "remote"], cwd=checkout).stdout.strip()
            self.assertEqual("", remotes)
            head = subprocess.run(
                ["git", "rev-parse", "--verify", "HEAD"],
                cwd=checkout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
            )
            self.assertNotEqual(0, head.returncode)

            self.assertIn('rootProject.name = "sample-app"', read_text(checkout / "settings.gradle.kts"))
            self.assertIn(
                'supermetaRulesToolDir.file("check.py")',
                read_text(checkout / "build.gradle.kts"),
            )
            self.assertIn("org.projectlombok:lombok", read_text(checkout / "build.gradle.kts"))
            self.assertIn("lombokVersion=1.18.44", read_text(checkout / "gradle.properties"))
            self.assertIn("slf4jVersion=2.0.17", read_text(checkout / "gradle.properties"))
            self.assertIn("logbackVersion=1.5.32", read_text(checkout / "gradle.properties"))
            self.assertIn("logstashLogbackEncoderVersion=9.0", read_text(checkout / "gradle.properties"))
            self.assertIn("checkstyle", read_text(checkout / "build.gradle.kts"))
            self.assertIn("org.slf4j:slf4j-api", read_text(checkout / "build.gradle.kts"))
            self.assertIn("ch.qos.logback:logback-classic", read_text(checkout / "build.gradle.kts"))
            self.assertIn("net.logstash.logback:logstash-logback-encoder", read_text(checkout / "build.gradle.kts"))
            self.assertIn("maxWarnings = Int.MAX_VALUE", read_text(checkout / "build.gradle.kts"))
            self.assertTrue((checkout / "config" / "checkstyle" / "checkstyle.xml").is_file())
            checkstyle_config = read_text(checkout / "config" / "checkstyle" / "checkstyle.xml")
            self.assertIn('<module name="UnusedImports">', checkstyle_config)
            self.assertIn('<property name="severity" value="warning"/>', checkstyle_config)
            rules_config = read_text(checkout / "supermeta-rules.json")
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "requirements.txt").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "repeated_helpers.py").is_file())
            self.assertIn('"java_package_class_count"', rules_config)
            self.assertIn('"max_classes": 7', rules_config)
            self.assertIn('"java_import_style"', rules_config)
            self.assertIn('"java_lombok_boilerplate"', rules_config)
            self.assertIn('"repeated_helper_methods"', rules_config)
            self.assertIn('"name": "repeated-helper-methods"', rules_config)
            self.assertIn('"near_match_threshold": 0.86', rules_config)
            self.assertIn('"advisory_near_matches": true', rules_config)
            self.assertIn('"allow_explicit": []', rules_config)
            self.assertIn('"ignore_annotations": []', rules_config)
            self.assertIn('"project_callouts"', rules_config)
            self.assertIn('"command": ["./scripts/agent-gradle", ".", "checkstyleMain", "checkstyleTest"]', rules_config)
            generated_build = read_text(checkout / "build.gradle.kts")
            self.assertIn("installSupermetaRuleDependencies", generated_build)
            self.assertIn("supermetaRulesToolDir", generated_build)
            self.assertIn('layout.projectDirectory.dir("tools/supermeta-rules")', generated_build)
            self.assertIn('supermetaRulesToolDir.file("requirements.txt")', generated_build)
            self.assertIn("inputs.files(fileTree(supermetaRulesToolDir))", generated_build)

            app_source = checkout / "src" / "main" / "java" / "com" / "acme" / "sample" / "App.java"
            logging_source = checkout / "src" / "main" / "java" / "com" / "acme" / "sample" / "LoggingConfig.java"
            test_source = checkout / "src" / "test" / "java" / "com" / "acme" / "sample" / "AppTest.java"
            logging_test_source = checkout / "src" / "test" / "java" / "com" / "acme" / "sample" / "LoggingConfigTest.java"
            self.assertTrue(app_source.is_file())
            self.assertTrue(logging_source.is_file())
            self.assertTrue(test_source.is_file())
            self.assertTrue(logging_test_source.is_file())
            self.assertIn("package com.acme.sample;", read_text(app_source))
            self.assertIn("package com.acme.sample;", read_text(logging_source))
            self.assertIn("import lombok.*;", read_text(app_source))
            self.assertIn("@RequiredArgsConstructor", read_text(app_source))
            self.assertIn('DEFAULT_NAME = "sample-app"', read_text(app_source))
            self.assertIn("Usage: sample-app [name]", read_text(app_source))
            self.assertIn("package com.acme.sample;", read_text(test_source))
            self.assertIn("package com.acme.sample;", read_text(logging_test_source))

            readme = read_text(checkout / "README.md")
            agents = read_text(checkout / "AGENTS.md")
            self.assertIn("# Sample App", readme)
            self.assertIn("./scripts/agent-gradle . check", readme)
            self.assertIn(".\\scripts\\agent-gradle.ps1 . check", readme)
            self.assertIn("./scripts/agent-beans prime", readme)
            self.assertIn(".\\scripts\\agent-beans.ps1 prime", readme)
            self.assertIn("./scripts/agent-task ps --match gradle", readme)
            self.assertIn(".\\scripts\\agent-task.ps1 ps --match gradle", readme)
            self.assertIn("./scripts/agent-task logs .gradle/supermeta-gradle/logs", readme)
            self.assertIn("./scripts/agent-coord status", readme)
            self.assertIn("./scripts/agent-coord run --resource perf:exclusive -- ./scripts/agent-gradle . check", readme)
            self.assertIn(".\\scripts\\agent-coord.ps1 status", readme)
            self.assertIn("./scripts/agent-nag run-hook session-start", readme)
            self.assertIn('./scripts/agent-gradle . run --args="Ada Lovelace"', readme)
            self.assertIn("LOG_LEVEL=info LOG_FORMAT=json", readme)
            self.assertIn("docs/ARCHITECTURE.md", readme)
            self.assertIn("update `application.mainClass` in `build.gradle.kts`", readme)
            self.assertIn("Supermeta enforces wildcard imports", readme)
            self.assertIn("Supermeta rejects handwritten getter, setter, and builder boilerplate", readme)
            self.assertIn("Supermeta flags repeated Java helper methods", readme)
            self.assertIn("exact repeated helpers fail", readme)
            self.assertIn("near matches are advisory", readme)
            self.assertIn("Checkstyle reports unused imports as warnings", readme)
            self.assertIn("# Sample App Agent Notes", agents)
            self.assertIn('./scripts/agent-gradle . run --args="example"', agents)
            self.assertIn('.\\scripts\\agent-gradle.ps1 . run --args="example"', agents)
            self.assertIn("LOG_LEVEL=info ./scripts/agent-gradle . run", agents)
            self.assertIn("./scripts/agent-beans prime", agents)
            self.assertIn("./scripts/agent-task ps --match gradle", agents)
            self.assertIn("./scripts/agent-task logs .gradle/supermeta-gradle/logs", agents)
            self.assertIn("./scripts/agent-gradle . --ps", agents)
            self.assertIn("./scripts/agent-gradle . --logs", agents)
            self.assertIn("./scripts/agent-gradle . --stop", agents)
            self.assertIn("./scripts/agent-coord announce --task", agents)
            self.assertIn("./scripts/agent-coord status", agents)
            self.assertIn("./scripts/agent-coord run --resource perf:exclusive", agents)
            self.assertIn("Treat nags as advisory", agents)
            self.assertIn("Supermeta enforces wildcard imports", agents)
            self.assertIn("Supermeta rejects handwritten getter, setter, and builder boilerplate", agents)
            self.assertIn("Supermeta flags repeated Java helper methods", agents)
            self.assertIn("factor repeated helpers into common code", agents)
            self.assertIn("Treat unused-import Checkstyle findings as warnings", agents)
            self.assertIn("## Bootstrap Sync", readme)
            self.assertIn("## Bootstrap Sync", agents)
            self.assertIn("agent-fix-loop", readme)
            self.assertIn("agent-smart-check", agents)
            self.assertIn("--self-test", agents)
            self.assertIn("Finder-copy hygiene", readme)
            self.assertIn("--no-hygiene", agents)
            assert_generated_upstream_suggestion_contract(self, readme, agents)
            assert_generated_operational_baseline(self, checkout)
            self.assertIn(
                "src/main/java/com/acme/sample/App.java",
                read_text(checkout / "docs" / "ARCHITECTURE.md"),
            )
            operations = read_text(checkout / "docs" / "OPERATIONS.md")
            self.assertIn("## Agent Coordination", operations)
            self.assertIn("CODEX_AGENT_COORD_HOME", operations)
            self.assertIn("checks.local.json", operations)
            self.assertIn("cleanup-quarantine", operations)
            assert_generated_nag_docs(self, readme, agents, operations)

            smart_check = run_checked(
                [
                    "./scripts/agent-smart-check",
                    "--changed",
                    "src/main/java/com/acme/sample/App.java",
                    "--plan-only",
                    "--json",
                ],
                cwd=checkout,
            )
            smart_payload = json.loads(smart_check.stdout)
            self.assertFalse(smart_payload["executed"])
            self.assertIn("full", [item["id"] for item in smart_payload["plan"]])
            self.assertEqual("fast", smart_payload["plan"][0]["cost"])
            self.assertIn("java", smart_payload["plan"][0]["requires"])
            smart_self_test = run_checked(["./scripts/agent-smart-check", "--self-test", "--json"], cwd=checkout)
            self.assertTrue(json.loads(smart_self_test.stdout)["ok"])
            fix_loop = run_checked(
                [
                    "./scripts/agent-fix-loop",
                    "--",
                    "./scripts/agent-smart-check",
                    "--changed",
                    "src/main/java/com/acme/sample/App.java",
                    "--plan-only",
                ],
                cwd=checkout,
            )
            self.assertIn("agent-smart-check", fix_loop.stdout)

            run_checked(["./scripts/agent-gradle", ".", "check"], cwd=checkout, timeout=360)
            run_checked(
                ["./scripts/agent-task", "logs", ".gradle/supermeta-gradle/logs"],
                cwd=checkout,
                timeout=120,
            )
            run_checked(["./scripts/agent-task", "ps", "--match", "gradle"], cwd=checkout, timeout=120)
            run_checked(["./scripts/agent-gradle", ".", "--logs"], cwd=checkout, timeout=120)
            run_checked(["./scripts/agent-gradle", ".", "--ps"], cwd=checkout, timeout=120)
            coord_home = checkout / ".tmp-agent-coord"
            run_checked(
                [
                    "./scripts/agent-coord",
                    "--state-home",
                    str(coord_home),
                    "--agent-id",
                    "bootstrap-smoke",
                    "announce",
                    "--task",
                    "bootstrap smoke",
                    "--resource",
                    "cpu:heavy",
                ],
                cwd=checkout,
                timeout=120,
            )
            status = run_checked(
                [
                    "./scripts/agent-coord",
                    "--state-home",
                    str(coord_home),
                    "status",
                    "--json",
                ],
                cwd=checkout,
                timeout=120,
            )
            self.assertIn("bootstrap-smoke", status.stdout)
            run_checked(
                [
                    "./scripts/agent-coord",
                    "--state-home",
                    str(coord_home),
                    "--agent-id",
                    "bootstrap-smoke",
                    "leave",
                ],
                cwd=checkout,
                timeout=120,
            )
            run_checked(
                [
                    "python3",
                    "tools/supermeta-rules/check.py",
                    "--config",
                    "supermeta-rules.json",
                    "--root",
                    ".",
                ],
                cwd=checkout,
                timeout=360,
            )
            generated_run = run_checked(["./scripts/agent-gradle", ".", "run"], cwd=checkout, timeout=360)
            self.assertIn("Hello from sample-app!", generated_run.stdout)
            self.assertNotIn("command completed exitCode=0", generated_run.stdout)
            logged_run = run_checked(
                ["./scripts/agent-gradle", ".", "run"],
                cwd=checkout,
                timeout=360,
                env={"LOG_LEVEL": "info", "LOG_FORMAT": "json"},
            )
            self.assertIn('"exitCode":0', logged_run.stdout)
            self.assertIn('"message":"command completed exitCode=0"', logged_run.stdout)
            bad_log_config = run_unchecked(
                ["./scripts/agent-gradle", ".", "run"],
                cwd=checkout,
                timeout=360,
                env={"LOG_LEVEL": "verbose"},
            )
            self.assertNotEqual(0, bad_log_config.returncode)
            self.assertIn("Logging configuration error: invalid LOG_LEVEL", bad_log_config.stdout)

            write_example_cli(checkout)
            run_checked(["./scripts/agent-gradle", ".", "check"], cwd=checkout, timeout=360)
            example_run = run_checked(
                ["./scripts/agent-gradle", ".", "run", "--args=Ada"],
                cwd=checkout,
                timeout=360,
            )
            self.assertIn("Hello, Ada!", example_run.stdout)

    @unittest.skipIf(shutil.which("uv") is None, "uv is required for Python template smoke test")
    @unittest.skipIf(shutil.which("git") is None, "git is required for bootstrap smoke test")
    def test_bootstrap_rewrites_python_template_into_standalone_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-python-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            checkout = temp_root / "sample-app"
            copy_bootstrap_checkout(checkout)
            initialize_fake_origin(checkout)

            run_checked(
                [
                    "./bootstrap",
                    "--template",
                    "python-uv-cli",
                    "--name",
                    "sample-app",
                    "--yes",
                ],
                cwd=checkout,
            )

            assert_catalog_removed(self, checkout)
            self.assertTrue((checkout / "scripts" / "agent-beans").is_file())
            self.assertTrue((checkout / "scripts" / "agent-beans.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "check.ps1").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-beans" / "beans.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-task" / "task.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "check.py").is_file())

            self.assertIn('name = "sample-app"', read_text(checkout / "pyproject.toml"))
            self.assertIn('sample-app = "sample_app.cli:main"', read_text(checkout / "pyproject.toml"))
            self.assertIn('name = "sample-app"', read_text(checkout / "uv.lock"))
            self.assertTrue((checkout / "src" / "sample_app" / "cli.py").is_file())
            self.assertTrue((checkout / "src" / "sample_app" / "__main__.py").is_file())
            self.assertTrue((checkout / "src" / "sample_app" / "logging_config.py").is_file())
            self.assertTrue((checkout / "src" / "sample_app" / "py.typed").is_file())
            self.assertFalse((checkout / "src" / "python_uv_cli").exists())

            app_source = read_text(checkout / "src" / "sample_app" / "cli.py")
            logging_source = read_text(checkout / "src" / "sample_app" / "logging_config.py")
            test_source = read_text(checkout / "tests" / "test_cli.py")
            self.assertIn('DEFAULT_NAME = "sample-app"', app_source)
            self.assertIn("Usage: sample-app [name]", app_source)
            self.assertIn('APP_LOGGER_NAME: Final = "sample-app"', logging_source)
            self.assertIn("from sample_app.cli import", test_source)

            readme = read_text(checkout / "README.md")
            agents = read_text(checkout / "AGENTS.md")
            self.assertIn("# Sample App", readme)
            self.assertIn("uv sync --locked", readme)
            self.assertIn("./scripts/check", readme)
            self.assertIn(".\\scripts\\check.ps1", readme)
            self.assertIn("uv run --no-editable sample-app", readme)
            self.assertIn("uv run --no-editable python -m sample_app", readme)
            self.assertIn("LOG_LEVEL=info LOG_FORMAT=json", readme)
            self.assertIn("./scripts/agent-beans prime", readme)
            self.assertIn("# Sample App Agent Notes", agents)
            self.assertIn("uv run --no-editable sample-app", agents)
            self.assertIn(".\\scripts\\check.ps1", agents)
            self.assertIn("LOG_LEVEL=info uv run --no-editable sample-app", agents)
            self.assertIn("./scripts/agent-beans prime", agents)
            self.assertIn("## Bootstrap Sync", readme)
            self.assertIn("## Bootstrap Sync", agents)
            assert_generated_upstream_suggestion_contract(self, readme, agents)
            assert_generated_operational_baseline(self, checkout)
            self.assertIn("src/sample_app/cli.py", read_text(checkout / "docs" / "ARCHITECTURE.md"))
            self.assertIn(
                "uv run --no-editable sample-app",
                read_text(checkout / "docs" / "OPERATIONS.md"),
            )

            env = {"UV_CACHE_DIR": "/tmp/codex-bootstrap-uv-cache"}
            run_checked(["./scripts/check"], cwd=checkout, timeout=360, env=env)
            generated_run = run_checked(
                ["uv", "run", "--no-editable", "sample-app"],
                cwd=checkout,
                timeout=360,
                env=env,
            )
            self.assertIn("Hello from sample-app!", generated_run.stdout)
            self.assertNotIn("command completed", generated_run.stdout)
            logged_run = run_checked(
                ["uv", "run", "--no-editable", "sample-app"],
                cwd=checkout,
                timeout=360,
                env=env | {"LOG_LEVEL": "info", "LOG_FORMAT": "json"},
            )
            self.assertIn('"exitCode":0', logged_run.stdout)
            self.assertIn('"message":"command completed"', logged_run.stdout)
            bad_log_config = run_unchecked(
                ["uv", "run", "--no-editable", "sample-app"],
                cwd=checkout,
                timeout=360,
                env=env | {"LOG_LEVEL": "verbose"},
            )
            self.assertEqual(2, bad_log_config.returncode)
            self.assertIn("Logging configuration error: invalid LOG_LEVEL", bad_log_config.stdout)

            write_example_python_cli(checkout)
            run_checked(["./scripts/check"], cwd=checkout, timeout=360, env=env)
            example_run = run_checked(
                ["uv", "run", "--no-editable", "sample-app", "Ada"],
                cwd=checkout,
                timeout=360,
                env=env,
            )
            self.assertIn("Hello, Ada!", example_run.stdout)

    @unittest.skipIf(shutil.which("git") is None, "git is required for bootstrap sync smoke test")
    def test_generated_project_sync_dry_run_and_conflict(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-sync-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            source_repo = temp_root / "source"
            checkout = temp_root / "sample-app"
            copy_bootstrap_checkout(source_repo)
            initialize_source_repo(source_repo)
            run_checked(["git", "checkout", "-b", "codex/source-dir-beta"], cwd=source_repo)
            copy_bootstrap_checkout(checkout)
            initialize_fake_origin(checkout)

            run_checked(
                [
                    "./bootstrap",
                    "--template",
                    "python-uv-cli",
                    "--name",
                    "sample-app",
                    "--yes",
                ],
                cwd=checkout,
            )
            commit_generated_project(checkout)

            dry_run = run_checked(
                [
                    "./scripts/agent-bootstrap",
                    "sync",
                    "--dry-run",
                    "--source-dir",
                    str(source_repo),
                ],
                cwd=checkout,
                timeout=180,
            )
            self.assertIn("Bootstrap sync plan:", dry_run.stdout)
            self.assertIn("template: python-uv-cli", dry_run.stdout)
            self.assertIn("candidate-ref: codex/source-dir-beta", dry_run.stdout)
            self.assertIn(
                f"follow-up-dry-run: ./scripts/agent-bootstrap sync --dry-run --allow-dirty --source-dir {source_repo.resolve()} --source-ref codex/source-dir-beta",
                dry_run.stdout,
            )

            apply = run_checked(
                [
                    "./scripts/agent-bootstrap",
                    "sync",
                    "--apply",
                    "--source-dir",
                    str(source_repo),
                ],
                cwd=checkout,
                timeout=180,
            )
            self.assertIn("candidate-ref: codex/source-dir-beta", apply.stdout)
            self.assertIn(
                f"follow-up-dry-run: ./scripts/agent-bootstrap sync --dry-run --allow-dirty --source-dir {source_repo.resolve()} --source-ref codex/source-dir-beta",
                apply.stdout,
            )
            sync_metadata = json.loads((checkout / ".codex-bootstrap" / "sync.json").read_text(encoding="utf-8"))
            self.assertEqual("codex/source-dir-beta", sync_metadata["source"]["ref"])

            agent_task = checkout / "scripts" / "agent-task"
            agent_task.write_text(
                agent_task.read_text(encoding="utf-8") + "\n# local edit\n",
                encoding="utf-8",
            )
            conflict = run_unchecked(
                [
                    "./scripts/agent-bootstrap",
                    "sync",
                    "--apply",
                    "--allow-dirty",
                    "--source-dir",
                    str(source_repo),
                ],
                cwd=checkout,
                timeout=180,
            )
            self.assertEqual(1, conflict.returncode)
            self.assertIn("conflict: scripts/agent-task", conflict.stdout)

    @unittest.skipIf(shutil.which("cargo") is None, "cargo is required for Rust template smoke test")
    @unittest.skipIf(shutil.which("git") is None, "git is required for bootstrap smoke test")
    def test_bootstrap_rewrites_rust_template_into_standalone_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-rust-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            checkout = temp_root / "sample-app"
            copy_bootstrap_checkout(checkout)
            initialize_fake_origin(checkout)

            run_checked(
                [
                    "./bootstrap",
                    "--template",
                    "rust-cargo-cli",
                    "--name",
                    "sample-app",
                    "--yes",
                ],
                cwd=checkout,
            )

            assert_catalog_removed(self, checkout)
            self.assertTrue((checkout / "scripts" / "agent-beans").is_file())
            self.assertTrue((checkout / "scripts" / "agent-beans.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "check.ps1").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-beans" / "beans.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-task" / "task.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "check.py").is_file())

            self.assertIn('name = "sample-app"', read_text(checkout / "Cargo.toml"))
            self.assertIn('name = "sample-app"', read_text(checkout / "Cargo.lock"))
            self.assertTrue((checkout / "src" / "main.rs").is_file())
            self.assertTrue((checkout / "src" / "cli.rs").is_file())
            self.assertTrue((checkout / "src" / "logging.rs").is_file())
            self.assertIn("rust_module_item_count", read_text(checkout / "supermeta-rules.json"))
            self.assertIn("rust_panic_boundary", read_text(checkout / "supermeta-rules.json"))
            self.assertIn("Rust uses the dependency-free starter logger", read_text(checkout / "docs" / "ARCHITECTURE.md"))
            self.assertIn("cargo run --quiet", read_text(checkout / "README.md"))
            self.assertIn("Do not use `.unwrap()`", read_text(checkout / "AGENTS.md"))

            example_run = run_checked(["cargo", "run", "--quiet", "--", "Ada"], cwd=checkout, timeout=180)
            self.assertIn("Hello, Ada!", example_run.stdout)

    @unittest.skipIf(shutil.which("dotnet") is None, "dotnet is required for C# template smoke test")
    @unittest.skipIf(shutil.which("git") is None, "git is required for bootstrap smoke test")
    def test_bootstrap_rewrites_csharp_template_into_standalone_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-csharp-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            checkout = temp_root / "sample-app"
            copy_bootstrap_checkout(checkout)
            initialize_fake_origin(checkout)

            run_checked(
                [
                    "./bootstrap",
                    "--template",
                    "csharp-dotnet-cli",
                    "--name",
                    "sample-app",
                    "--yes",
                ],
                cwd=checkout,
            )

            assert_catalog_removed(self, checkout)
            self.assertTrue((checkout / "scripts" / "agent-dotnet").is_file())
            self.assertTrue((checkout / "scripts" / "agent-dotnet.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-beans").is_file())
            self.assertTrue((checkout / "scripts" / "agent-beans.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "check.ps1").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-beans" / "beans.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-task" / "task.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "check.py").is_file())

            self.assertTrue((checkout / "SampleApp.slnx").is_file())
            self.assertFalse((checkout / "CsharpDotnetCli.slnx").exists())
            self.assertTrue((checkout / "src" / "SampleApp" / "SampleApp.csproj").is_file())
            self.assertTrue((checkout / "src" / "SampleApp" / "App.cs").is_file())
            self.assertTrue((checkout / "src" / "SampleApp" / "LoggingConfig.cs").is_file())
            self.assertTrue((checkout / "src" / "SampleApp" / "Program.cs").is_file())
            self.assertTrue((checkout / "tests" / "SampleApp.Tests" / "SampleApp.Tests.csproj").is_file())
            self.assertTrue((checkout / "tests" / "SampleApp.Tests" / "AppTests.cs").is_file())
            self.assertTrue((checkout / "tests" / "SampleApp.Tests" / "LoggingConfigTests.cs").is_file())
            self.assertFalse((checkout / "src" / "CsharpDotnetCli").exists())
            self.assertFalse((checkout / "tests" / "CsharpDotnetCli.Tests").exists())

            solution = read_text(checkout / "SampleApp.slnx")
            project = read_text(checkout / "src" / "SampleApp" / "SampleApp.csproj")
            test_project = read_text(checkout / "tests" / "SampleApp.Tests" / "SampleApp.Tests.csproj")
            self.assertIn("src/SampleApp/SampleApp.csproj", solution)
            self.assertIn("tests/SampleApp.Tests/SampleApp.Tests.csproj", solution)
            self.assertIn("<AssemblyName>SampleApp</AssemblyName>", project)
            self.assertIn("<RootNamespace>Generated.SampleApp</RootNamespace>", project)
            self.assertIn("<TargetFramework>net10.0</TargetFramework>", project)
            self.assertIn("<RootNamespace>Generated.SampleApp.Tests</RootNamespace>", test_project)
            self.assertIn(r"..\..\src\SampleApp\SampleApp.csproj", test_project)
            self.assertIn(
                '"sampleapp":',
                read_text(checkout / "tests" / "SampleApp.Tests" / "packages.lock.json"),
            )
            check_powershell = read_text(checkout / "scripts" / "check.ps1")
            self.assertIn("SampleApp.slnx", check_powershell)
            self.assertIn("scripts/agent-dotnet.ps1", check_powershell)
            self.assertNotIn("CsharpDotnetCli.slnx", check_powershell)

            app_source = read_text(checkout / "src" / "SampleApp" / "App.cs")
            logging_source = read_text(checkout / "src" / "SampleApp" / "LoggingConfig.cs")
            test_source = read_text(checkout / "tests" / "SampleApp.Tests" / "AppTests.cs")
            self.assertIn("namespace Generated.SampleApp;", app_source)
            self.assertIn('DefaultName = "sample-app"', app_source)
            self.assertIn("Usage: sample-app [name]", app_source)
            self.assertIn('LoggerName = "sample-app"', logging_source)
            self.assertIn("namespace Generated.SampleApp.Tests;", test_source)

            rules_config = read_text(checkout / "supermeta-rules.json")
            self.assertIn('"csharp-format"', rules_config)
            self.assertIn('"command": ["./scripts/agent-dotnet", ".", "format", "SampleApp.slnx"', rules_config)

            readme = read_text(checkout / "README.md")
            agents = read_text(checkout / "AGENTS.md")
            self.assertIn("# Sample App", readme)
            self.assertIn("./scripts/check", readme)
            self.assertIn(".\\scripts\\check.ps1", readme)
            self.assertIn("./scripts/agent-dotnet . restore --locked-mode", readme)
            self.assertIn(".\\scripts\\agent-dotnet.ps1 . restore --locked-mode", readme)
            self.assertIn("./scripts/agent-dotnet . run --project src/SampleApp/SampleApp.csproj --", readme)
            self.assertIn("LOG_LEVEL=info LOG_FORMAT=json", readme)
            self.assertIn("./scripts/agent-task ps --match dotnet", readme)
            self.assertIn("# Sample App Agent Notes", agents)
            self.assertIn("Target .NET 10 through `net10.0`", agents)
            self.assertIn(".\\scripts\\check.ps1", agents)
            self.assertIn("LOG_LEVEL=info ./scripts/agent-dotnet . run --project src/SampleApp/SampleApp.csproj --", agents)
            self.assertIn("./scripts/agent-beans prime", agents)
            self.assertIn("## Bootstrap Sync", readme)
            self.assertIn("## Bootstrap Sync", agents)
            assert_generated_upstream_suggestion_contract(self, readme, agents)
            assert_generated_operational_baseline(self, checkout)
            self.assertIn("Generated.SampleApp", read_text(checkout / "docs" / "ARCHITECTURE.md"))
            self.assertIn("src/SampleApp/App.cs", read_text(checkout / "docs" / "ARCHITECTURE.md"))

            run_checked(["./scripts/check"], cwd=checkout, timeout=360)
            generated_run = run_checked(
                [
                    "./scripts/agent-dotnet",
                    ".",
                    "run",
                    "--project",
                    "src/SampleApp/SampleApp.csproj",
                    "--",
                ],
                cwd=checkout,
                timeout=360,
            )
            self.assertIn("Hello from sample-app!", generated_run.stdout)
            self.assertNotIn("command completed", generated_run.stdout)
            logged_run = run_checked(
                [
                    "./scripts/agent-dotnet",
                    ".",
                    "run",
                    "--project",
                    "src/SampleApp/SampleApp.csproj",
                    "--",
                ],
                cwd=checkout,
                timeout=360,
                env={"LOG_LEVEL": "info", "LOG_FORMAT": "json"},
            )
            self.assertIn('"exitCode":0', logged_run.stdout)
            self.assertIn('"message":"command completed"', logged_run.stdout)
            bad_log_config = run_unchecked(
                [
                    "./scripts/agent-dotnet",
                    ".",
                    "run",
                    "--project",
                    "src/SampleApp/SampleApp.csproj",
                    "--",
                ],
                cwd=checkout,
                timeout=360,
                env={"LOG_LEVEL": "verbose"},
            )
            self.assertEqual(2, bad_log_config.returncode)
            self.assertIn("Logging configuration error: invalid LOG_LEVEL", bad_log_config.stdout)

            write_example_csharp_cli(checkout)
            run_checked(["./scripts/check"], cwd=checkout, timeout=360)
            example_run = run_checked(
                [
                    "./scripts/agent-dotnet",
                    ".",
                    "run",
                    "--project",
                    "src/SampleApp/SampleApp.csproj",
                    "--",
                    "Ada",
                ],
                cwd=checkout,
                timeout=360,
            )
            self.assertIn("Hello, Ada!", example_run.stdout)

    @unittest.skipIf(shutil.which("git") is None, "git is required for bootstrap smoke test")
    def test_bootstrap_rewrites_typescript_template_into_standalone_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-typescript-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            checkout = temp_root / "sample-app"
            copy_bootstrap_checkout(checkout)
            initialize_fake_origin(checkout)

            run_checked(
                [
                    "./bootstrap",
                    "--template",
                    "typescript-bun-cli",
                    "--name",
                    "sample-app",
                    "--yes",
                ],
                cwd=checkout,
            )

            assert_catalog_removed(self, checkout)
            self.assertTrue((checkout / "scripts" / "agent-beans").is_file())
            self.assertTrue((checkout / "scripts" / "agent-beans.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "check.ps1").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-beans" / "beans.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-task" / "task.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "check.py").is_file())

            package_json = read_text(checkout / "package.json")
            self.assertIn('"name": "sample-app"', package_json)
            self.assertIn("bun node_modules/typescript/lib/tsc.js --noEmit", package_json)
            self.assertIn("bun node_modules/@biomejs/biome/bin/biome check .", package_json)
            self.assertIn('"pino": "10.3.1"', package_json)
            self.assertIn('"pino-pretty": "13.1.3"', package_json)
            self.assertIn('"name": "sample-app"', read_text(checkout / "bun.lock"))
            self.assertTrue((checkout / "src" / "cli.ts").is_file())
            self.assertTrue((checkout / "src" / "logging.ts").is_file())
            self.assertTrue((checkout / "src" / "main.ts").is_file())

            app_source = read_text(checkout / "src" / "cli.ts")
            logging_source = read_text(checkout / "src" / "logging.ts")
            test_source = read_text(checkout / "tests" / "cli.test.ts")
            self.assertIn('DEFAULT_NAME = "sample-app"', app_source)
            self.assertIn("Usage: sample-app [name]", app_source)
            self.assertIn('appName ?? "sample-app"', logging_source)
            self.assertIn('stdout: "Hello from sample-app!"', test_source)

            readme = read_text(checkout / "README.md")
            agents = read_text(checkout / "AGENTS.md")
            self.assertIn("# Sample App", readme)
            self.assertIn("bun install --frozen-lockfile", readme)
            self.assertIn("./scripts/check", readme)
            self.assertIn(".\\scripts\\check.ps1", readme)
            self.assertIn("bun run src/main.ts", readme)
            self.assertIn("LOG_LEVEL=info LOG_FORMAT=json", readme)
            self.assertIn("./scripts/agent-beans prime", readme)
            self.assertIn("# Sample App Agent Notes", agents)
            self.assertIn("Bun is the only package-manager/runtime contract", agents)
            self.assertIn(".\\scripts\\check.ps1", agents)
            self.assertIn("LOG_LEVEL=info bun run src/main.ts", agents)
            self.assertIn("./scripts/agent-beans prime", agents)
            self.assertIn("## Bootstrap Sync", readme)
            self.assertIn("## Bootstrap Sync", agents)
            assert_generated_upstream_suggestion_contract(self, readme, agents)
            assert_generated_operational_baseline(self, checkout)

            if shutil.which("bun") is None:
                self.skipTest("bun is required for TypeScript check/run verification")

            run_checked(["./scripts/check"], cwd=checkout, timeout=360)
            generated_run = run_checked(["bun", "run", "src/main.ts"], cwd=checkout, timeout=360)
            self.assertIn("Hello from sample-app!", generated_run.stdout)
            self.assertNotIn("command completed", generated_run.stdout)
            logged_run = run_checked(
                ["bun", "run", "src/main.ts"],
                cwd=checkout,
                timeout=360,
                env={"LOG_LEVEL": "info", "LOG_FORMAT": "json"},
            )
            self.assertIn('"exitCode":0', logged_run.stdout)
            self.assertIn('"message":"command completed"', logged_run.stdout)
            bad_log_config = run_unchecked(
                ["bun", "run", "src/main.ts"],
                cwd=checkout,
                timeout=360,
                env={"LOG_LEVEL": "verbose"},
            )
            self.assertEqual(2, bad_log_config.returncode)
            self.assertIn("Logging configuration error: invalid LOG_LEVEL", bad_log_config.stdout)

            write_example_typescript_cli(checkout)
            run_checked(["./scripts/check"], cwd=checkout, timeout=360)
            example_run = run_checked(
                ["bun", "run", "src/main.ts", "Ada"],
                cwd=checkout,
                timeout=360,
            )
            self.assertIn("Hello, Ada!", example_run.stdout)

    @unittest.skipIf(shutil.which("git") is None, "git is required for bootstrap smoke test")
    def test_bootstrap_rewrites_typescript_mcp_template_into_standalone_project(self) -> None:
        with tempfile.TemporaryDirectory(prefix="codex-bootstrap-typescript-mcp-smoke-") as temp_dir:
            temp_root = Path(temp_dir)
            checkout = temp_root / "sample-app"
            copy_bootstrap_checkout(checkout)
            initialize_fake_origin(checkout)

            run_checked(
                [
                    "./bootstrap",
                    "--template",
                    "typescript-bun-mcp-server",
                    "--name",
                    "sample-app",
                    "--yes",
                ],
                cwd=checkout,
            )

            assert_catalog_removed(self, checkout)
            self.assertTrue((checkout / "scripts" / "agent-beans").is_file())
            self.assertTrue((checkout / "scripts" / "agent-beans.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task.ps1").is_file())
            self.assertTrue((checkout / "scripts" / "check.ps1").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-beans" / "beans.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-task" / "task.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "check.py").is_file())

            package_json = read_text(checkout / "package.json")
            self.assertIn('"name": "sample-app"', package_json)
            self.assertIn('"@modelcontextprotocol/sdk": "^1.29.0"', package_json)
            self.assertIn('"zod": "^4.3.6"', package_json)
            self.assertIn('"name": "sample-app"', read_text(checkout / "bun.lock"))
            self.assertTrue((checkout / "src" / "config.ts").is_file())
            self.assertTrue((checkout / "src" / "http.ts").is_file())
            self.assertTrue((checkout / "src" / "mcp.ts").is_file())
            self.assertTrue((checkout / "src" / "state.ts").is_file())
            self.assertTrue((checkout / "src" / "stdio.ts").is_file())

            config_source = read_text(checkout / "src" / "config.ts")
            mcp_source = read_text(checkout / "src" / "mcp.ts")
            self.assertIn("Usage: sample-app [options]", config_source)
            self.assertIn('DEFAULT_SERVER_NAME = "sample-app"', mcp_source)

            readme = read_text(checkout / "README.md")
            agents = read_text(checkout / "AGENTS.md")
            self.assertIn("# Sample App", readme)
            self.assertIn("TypeScript Bun MCP server", readme)
            self.assertIn("./scripts/check", readme)
            self.assertIn(".\\scripts\\check.ps1", readme)
            self.assertIn("bun run src/main.ts --transport http", readme)
            self.assertIn("Keep stdio output clean", agents)
            self.assertIn(".\\scripts\\check.ps1", agents)
            self.assertIn("./scripts/agent-beans prime", agents)
            self.assertIn("## Bootstrap Sync", readme)
            self.assertIn("## Bootstrap Sync", agents)
            assert_generated_upstream_suggestion_contract(self, readme, agents)
            assert_generated_operational_baseline(self, checkout)

            if shutil.which("bun") is None:
                self.skipTest("bun is required for TypeScript MCP check/run verification")

            run_checked(["./scripts/check"], cwd=checkout, timeout=360)
            generated_help = run_checked(
                ["bun", "run", "src/main.ts", "--help"],
                cwd=checkout,
                timeout=360,
            )
            self.assertIn("Usage: sample-app [options]", generated_help.stdout)


def copy_bootstrap_checkout(destination: Path) -> None:
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


def initialize_fake_origin(checkout: Path) -> None:
    run_checked(["git", "init"], cwd=checkout)
    run_checked(["git", "remote", "add", "origin", "https://example.com/bootstrap.git"], cwd=checkout)


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


def commit_generated_project(checkout: Path) -> None:
    run_checked(["git", "add", "."], cwd=checkout)
    run_checked(
        [
            "git",
            "-c",
            "user.name=Codex Bootstrap Test",
            "-c",
            "user.email=codex-bootstrap@example.invalid",
            "commit",
            "-m",
            "generated project",
        ],
        cwd=checkout,
    )


def write_example_cli(checkout: Path) -> None:
    app_source = checkout / "src" / "main" / "java" / "com" / "acme" / "sample" / "App.java"
    test_source = checkout / "src" / "test" / "java" / "com" / "acme" / "sample" / "AppTest.java"

    app_source.write_text(
        """package com.acme.sample;

public final class App {
    private static final String USAGE = "Usage: sample-app <name>";

    private App() {
    }

    public static String render(String[] args) {
        if (args.length == 0) {
            return USAGE;
        }

        String name = String.join(" ", args).trim();
        if (name.isEmpty()) {
            return USAGE;
        }

        return "Hello, " + name + "!";
    }

    public static void main(String[] args) {
        System.out.println(render(args));
    }
}
""",
        encoding="utf-8",
    )
    test_source.write_text(
        """package com.acme.sample;

import static org.junit.jupiter.api.Assertions.*;

import org.junit.jupiter.api.*;

final class AppTest {
    @Test
    void rendersUsageWithoutName() {
        assertEquals("Usage: sample-app <name>", App.render(new String[0]));
    }

    @Test
    void greetsProvidedName() {
        assertEquals("Hello, Ada Lovelace!", App.render(new String[] {"Ada", "Lovelace"}));
    }
}
""",
        encoding="utf-8",
    )


def write_example_python_cli(checkout: Path) -> None:
    app_source = checkout / "src" / "sample_app" / "cli.py"
    test_source = checkout / "tests" / "test_cli.py"

    app_source.write_text(
        """from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

USAGE = "Usage: sample-app <name>"


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    stdout: str
    stderr: str


def render(args: Sequence[str]) -> CliResult:
    name = " ".join(args).strip()
    if not name:
        return CliResult(2, "", USAGE)
    return CliResult(0, f"Hello, {name}!", "")


def write_result(result: CliResult, stdout: TextIO, stderr: TextIO) -> None:
    if result.stdout:
        print(result.stdout, file=stdout)
    if result.stderr:
        print(result.stderr, file=stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    result = render(args)
    write_result(result, sys.stdout, sys.stderr)
    return result.exit_code
""",
        encoding="utf-8",
    )
    test_source.write_text(
        """from sample_app.cli import CliResult, render


def test_renders_usage_without_name() -> None:
    assert render([]) == CliResult(2, "", "Usage: sample-app <name>")


def test_greets_provided_name() -> None:
    assert render(["Ada", "Lovelace"]) == CliResult(0, "Hello, Ada Lovelace!", "")
""",
        encoding="utf-8",
    )


def write_example_csharp_cli(checkout: Path) -> None:
    app_source = checkout / "src" / "SampleApp" / "App.cs"
    test_source = checkout / "tests" / "SampleApp.Tests" / "AppTests.cs"

    app_source.write_text(
        """namespace Generated.SampleApp;

public sealed class App
{
    public const string DefaultName = "sample-app";
    public const string Usage = "Usage: sample-app <name>";

    private readonly string defaultName;

    public App(string defaultName)
    {
        this.defaultName = defaultName;
    }

    public int Run(IReadOnlyList<string> args, TextWriter stdout, TextWriter stderr)
    {
        CliResult result = args.Count == 0 && !string.IsNullOrEmpty(defaultName)
            ? new CliResult(2, string.Empty, Usage)
            : Render(args);
        if (!string.IsNullOrEmpty(result.Stdout))
        {
            stdout.WriteLine(result.Stdout);
        }
        if (!string.IsNullOrEmpty(result.Stderr))
        {
            stderr.WriteLine(result.Stderr);
        }
        return result.ExitCode;
    }

    public static CliResult Render(IReadOnlyList<string> args)
    {
        string name = string.Join(" ", args).Trim();
        if (string.IsNullOrEmpty(name))
        {
            return new CliResult(2, string.Empty, Usage);
        }
        return new CliResult(0, $"Hello, {name}!", string.Empty);
    }
}

public sealed record CliResult(int ExitCode, string Stdout, string Stderr);
""",
        encoding="utf-8",
    )
    test_source.write_text(
        """using Generated.SampleApp;

namespace Generated.SampleApp.Tests;

public sealed class AppTests
{
    [Fact]
    public void RendersUsageWithoutName()
    {
        Assert.Equal(new CliResult(2, string.Empty, "Usage: sample-app <name>"), App.Render([]));
    }

    [Fact]
    public void GreetsProvidedName()
    {
        Assert.Equal(new CliResult(0, "Hello, Ada Lovelace!", string.Empty), App.Render(["Ada", "Lovelace"]));
    }
}
""",
        encoding="utf-8",
    )


def write_example_typescript_cli(checkout: Path) -> None:
    app_source = checkout / "src" / "cli.ts"
    test_source = checkout / "tests" / "cli.test.ts"

    app_source.write_text(
        """export interface CliResult {
  readonly exitCode: number;
  readonly stdout: string;
  readonly stderr: string;
}

export const USAGE = "Usage: sample-app <name>";

export function render(args: readonly string[]): CliResult {
  const name = args.join(" ").trim();
  if (name.length === 0) {
    return {
      exitCode: 2,
      stdout: "",
      stderr: USAGE,
    };
  }
  return {
    exitCode: 0,
    stdout: `Hello, ${name}!`,
    stderr: "",
  };
}
""",
        encoding="utf-8",
    )
    test_source.write_text(
        """import { expect, test } from "bun:test";

import { render } from "../src/cli";

test("renders usage without name", () => {
  expect(render([])).toEqual({
    exitCode: 2,
    stdout: "",
    stderr: "Usage: sample-app <name>",
  });
});

test("greets provided name", () => {
  expect(render(["Ada", "Lovelace"])).toEqual({
    exitCode: 0,
    stdout: "Hello, Ada Lovelace!",
    stderr: "",
  });
});
""",
        encoding="utf-8",
    )


def assert_catalog_removed(test_case: unittest.TestCase, checkout: Path) -> None:
    test_case.assertFalse((checkout / "templates").exists())
    test_case.assertFalse((checkout / "environments").exists())
    test_case.assertFalse((checkout / ".github").exists())
    test_case.assertFalse((checkout / "site").exists())
    test_case.assertFalse((checkout / "bootstrap").exists())
    test_case.assertFalse((checkout / "bootstrap.ps1").exists())
    test_case.assertFalse((checkout / "tools" / "bootstrap").exists())

    remotes = run_checked(["git", "remote"], cwd=checkout).stdout.strip()
    test_case.assertEqual("", remotes)
    head = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"],
        cwd=checkout,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    test_case.assertNotEqual(0, head.returncode)


def assert_generated_operational_baseline(test_case: unittest.TestCase, checkout: Path) -> None:
    for doc_path in ("docs/ARCHITECTURE.md", "docs/OPERATIONS.md", "docs/DECISIONS.md"):
        test_case.assertTrue((checkout / doc_path).is_file(), doc_path)

    architecture = read_text(checkout / "docs" / "ARCHITECTURE.md")
    operations = read_text(checkout / "docs" / "OPERATIONS.md")
    decisions = read_text(checkout / "docs" / "DECISIONS.md")
    beans_config = read_text(checkout / ".beans.yml")

    test_case.assertIn("# Sample App Architecture", architecture)
    test_case.assertIn("## Runtime Shape", architecture)
    test_case.assertIn("## Runtime Logging", architecture)
    test_case.assertIn("LOG_LEVEL", architecture)
    test_case.assertIn("LOG_FORMAT", architecture)
    test_case.assertIn("# Sample App Operations", operations)
    test_case.assertIn("./scripts/agent-beans check", operations)
    test_case.assertIn("## Logging", operations)
    test_case.assertIn("LOG_LEVEL", operations)
    test_case.assertIn("# Sample App Decisions", decisions)
    test_case.assertIn("active project decisions only", decisions)
    test_case.assertIn("Runtime Logging Contract", decisions)
    test_case.assertIn("prefix: sample-app-", beans_config)
    test_case.assertIn("default_type: task", beans_config)
    test_case.assertEqual(
        "# Generated by beans init\n.worktrees/\n.conversations/\n",
        read_text(checkout / ".beans" / ".gitignore"),
    )

    bean_files = sorted(path.name for path in (checkout / ".beans").glob("*.md"))
    test_case.assertEqual(
        [
            "sample-app-f001--replace-starter-behavior.md",
            "sample-app-m001--ship-first-real-project-slice.md",
            "sample-app-t001--lock-architecture-and-decisions.md",
            "sample-app-t002--add-ci-and-release-verification.md",
        ],
        bean_files,
    )
    seed_bean = read_text(checkout / ".beans" / "sample-app-f001--replace-starter-behavior.md")
    test_case.assertIn("type: feature", seed_bean)
    test_case.assertIn("parent: sample-app-m001", seed_bean)


def assert_generated_upstream_suggestion_contract(
    test_case: unittest.TestCase, readme: str, agents: str
) -> None:
    for text in (readme, agents):
        test_case.assertIn("## Suggest Upstream Bootstrap Changes", text)
        test_case.assertIn("Upstream bootstrap suggestion", text)
        test_case.assertIn("Template id:", text)
        test_case.assertIn("Synced upstream commit:", text)
        test_case.assertIn("Why this belongs upstream:", text)
        test_case.assertIn("Verification that should pass:", text)
    test_case.assertIn("read `.codex-bootstrap/sync.json`", agents)
    test_case.assertIn("./scripts/agent-bootstrap sync --dry-run", agents)
    test_case.assertIn("./scripts/agent-bootstrap sync --dry-run --allow-dirty --source-ref <ref>", readme)
    test_case.assertIn("repairs stale metadata on apply", agents)


def assert_generated_nag_docs(
    test_case: unittest.TestCase,
    readme: str,
    agents: str,
    operations: str,
) -> None:
    for text in (readme, agents, operations):
        test_case.assertIn("codex-bootstrap:begin generated-docs/agent-nags", text)
        test_case.assertIn("./scripts/agent-nag run-hook session-start", text)
        test_case.assertIn("./scripts/agent-nag snooze post-run-backlog-check --for 7d", text)
    test_case.assertIn("Treat nags as advisory", agents)


def assert_velocity_manifest_contract(test_case: unittest.TestCase, manifest: TemplateManifest) -> None:
    test_case.assertIn("velocity-tools", manifest.sync_contract.managed_sets)
    test_case.assertIn("scripts/agent-smart-check", manifest.sync_contract.managed_files)
    test_case.assertIn("scripts/agent-fix-loop", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-check/__init__.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-check/check.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-check/hygiene.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-check/hygiene_test.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-fix/__init__.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-fix/fix.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-rules/repeated_helpers.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-rules/repeated_helpers_test.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-rules/requirements.txt", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-rules/workspace.py", manifest.sync_contract.managed_files)
    test_case.assertIn(".codex-bootstrap/checks.json", manifest.sync_contract.managed_files)
    test_case.assertIn("README.md:generated-docs/velocity-tools", manifest.sync_contract.managed_regions)
    test_case.assertIn("AGENTS.md:generated-docs/velocity-tools", manifest.sync_contract.managed_regions)
    test_case.assertIn("docs/OPERATIONS.md:generated-docs/velocity-tools", manifest.sync_contract.managed_regions)


def run_checked(
    command: list[str],
    cwd: Path,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env is not None:
        run_env.update(env)
    result = subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
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


def run_unchecked(
    command: list[str],
    cwd: Path,
    timeout: int = 120,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    run_env = os.environ.copy()
    if env is not None:
        run_env.update(env)
    return subprocess.run(
        command,
        cwd=cwd,
        env=run_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=timeout,
        check=False,
    )


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
