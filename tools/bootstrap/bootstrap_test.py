from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from tools.bootstrap.bootstrap import (  # noqa: E402
    TemplateManifest,
    UsageError,
    assert_safe_clear_path,
    java_package_to_path,
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


class ManifestTest(unittest.TestCase):
    def test_loads_java_template_manifest(self) -> None:
        manifest = TemplateManifest.load(REPO_ROOT, "java-gradle-cli")

        self.assertEqual("java-gradle-cli", manifest.template_id)
        self.assertEqual("java-gradle-cli", manifest.template_type)
        self.assertEqual(("name", "package"), manifest.required_inputs)
        self.assertIn("./scripts/agent-gradle . check", manifest.verification_commands)
        self.assertEqual(
            ["scripts/agent-gradle", "tools/supermeta-gradle", "tools/supermeta-rules"],
            [path.source for path in manifest.support_paths],
        )


class SafetyTest(unittest.TestCase):
    def test_refuses_to_clear_filesystem_root(self) -> None:
        with self.assertRaises(UsageError):
            assert_safe_clear_path(Path("/"))


class BootstrapSmokeTest(unittest.TestCase):
    @unittest.skipIf(shutil.which("git") is None, "git is required for bootstrap smoke test")
    def test_bootstrap_rewrites_checkout_into_standalone_project(self) -> None:
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
            self.assertFalse((checkout / "bootstrap").exists())
            self.assertFalse((checkout / "tools" / "bootstrap").exists())
            self.assertTrue((checkout / "scripts" / "agent-gradle").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-gradle" / "gradle.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-rules" / "check.py").is_file())

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
                'layout.projectDirectory.file("tools/supermeta-rules/check.py")',
                read_text(checkout / "build.gradle.kts"),
            )
            self.assertIn("checkstyle", read_text(checkout / "build.gradle.kts"))
            self.assertTrue((checkout / "config" / "checkstyle" / "checkstyle.xml").is_file())
            rules_config = read_text(checkout / "supermeta-rules.json")
            self.assertIn('"java_package_file_count"', rules_config)
            self.assertIn('"project_callouts"', rules_config)
            self.assertIn('"command": ["./scripts/agent-gradle", ".", "checkstyleMain", "checkstyleTest"]', rules_config)

            app_source = checkout / "src" / "main" / "java" / "com" / "acme" / "sample" / "App.java"
            test_source = checkout / "src" / "test" / "java" / "com" / "acme" / "sample" / "AppTest.java"
            self.assertTrue(app_source.is_file())
            self.assertTrue(test_source.is_file())
            self.assertIn("package com.acme.sample;", read_text(app_source))
            self.assertIn('DEFAULT_NAME = "sample-app"', read_text(app_source))
            self.assertIn("Usage: sample-app [name]", read_text(app_source))
            self.assertIn("package com.acme.sample;", read_text(test_source))

            readme = read_text(checkout / "README.md")
            agents = read_text(checkout / "AGENTS.md")
            self.assertIn("# Sample App", readme)
            self.assertIn("./scripts/agent-gradle . check", readme)
            self.assertIn('./scripts/agent-gradle . run --args="Ada Lovelace"', readme)
            self.assertIn("update `application.mainClass` in `build.gradle.kts`", readme)
            self.assertIn("# Sample App Agent Notes", agents)
            self.assertIn('./scripts/agent-gradle . run --args="example"', agents)
            self.assertNotIn("codex-bootstrap", readme.lower())
            self.assertNotIn("codex-bootstrap", agents.lower())

            run_checked(["./scripts/agent-gradle", ".", "check"], cwd=checkout, timeout=360)
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

            write_example_cli(checkout)
            run_checked(["./scripts/agent-gradle", ".", "check"], cwd=checkout, timeout=360)
            example_run = run_checked(
                ["./scripts/agent-gradle", ".", "run", "--args=Ada"],
                cwd=checkout,
                timeout=360,
            )
            self.assertIn("Hello, Ada!", example_run.stdout)


def copy_bootstrap_checkout(destination: Path) -> None:
    shutil.copytree(
        REPO_ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".gradle",
            "__pycache__",
            "build",
            "*.pyc",
        ),
    )


def initialize_fake_origin(checkout: Path) -> None:
    run_checked(["git", "init"], cwd=checkout)
    run_checked(["git", "remote", "add", "origin", "https://example.com/bootstrap.git"], cwd=checkout)


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


def run_checked(command: list[str], cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
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


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
