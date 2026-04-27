from __future__ import annotations

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
    TemplateManifest,
    UsageError,
    assert_safe_clear_path,
    java_package_to_path,
    python_module_from_slug,
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


class ManifestTest(unittest.TestCase):
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
                "scripts/agent-beans",
                "scripts/agent-task",
                "tools/supermeta-gradle",
                "tools/supermeta-beans",
                "tools/supermeta-task",
                "tools/supermeta-rules",
            ],
            [path.source for path in manifest.support_paths],
        )

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
                "scripts/agent-beans",
                "scripts/agent-task",
                "tools/supermeta-beans",
                "tools/supermeta-task",
                "tools/supermeta-rules",
            ],
            [path.source for path in manifest.support_paths],
        )

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
                "scripts/agent-beans",
                "scripts/agent-task",
                "tools/supermeta-beans",
                "tools/supermeta-task",
                "tools/supermeta-rules",
            ],
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
            self.assertFalse((checkout / ".github").exists())
            self.assertFalse((checkout / "site").exists())
            self.assertFalse((checkout / "bootstrap").exists())
            self.assertFalse((checkout / "tools" / "bootstrap").exists())
            self.assertTrue((checkout / "scripts" / "agent-gradle").is_file())
            self.assertTrue((checkout / "scripts" / "agent-beans").is_file())
            self.assertTrue((checkout / "scripts" / "agent-task").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-gradle" / "gradle.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-beans" / "beans.py").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-task" / "task.py").is_file())
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
            self.assertIn("org.projectlombok:lombok", read_text(checkout / "build.gradle.kts"))
            self.assertIn("lombokVersion=1.18.44", read_text(checkout / "gradle.properties"))
            self.assertIn("slf4jVersion=2.0.17", read_text(checkout / "gradle.properties"))
            self.assertIn("logbackVersion=1.5.32", read_text(checkout / "gradle.properties"))
            self.assertIn("logstashLogbackEncoderVersion=9.0", read_text(checkout / "gradle.properties"))
            self.assertIn("checkstyle", read_text(checkout / "build.gradle.kts"))
            self.assertIn("org.slf4j:slf4j-api", read_text(checkout / "build.gradle.kts"))
            self.assertIn("ch.qos.logback:logback-classic", read_text(checkout / "build.gradle.kts"))
            self.assertIn("net.logstash.logback:logstash-logback-encoder", read_text(checkout / "build.gradle.kts"))
            self.assertTrue((checkout / "config" / "checkstyle" / "checkstyle.xml").is_file())
            rules_config = read_text(checkout / "supermeta-rules.json")
            self.assertIn('"java_package_file_count"', rules_config)
            self.assertIn('"project_callouts"', rules_config)
            self.assertIn('"command": ["./scripts/agent-gradle", ".", "checkstyleMain", "checkstyleTest"]', rules_config)

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
            self.assertIn("./scripts/agent-beans prime", readme)
            self.assertIn("./scripts/agent-task ps --match gradle", readme)
            self.assertIn("./scripts/agent-task logs .gradle/supermeta-gradle/logs", readme)
            self.assertIn('./scripts/agent-gradle . run --args="Ada Lovelace"', readme)
            self.assertIn("LOG_LEVEL=info LOG_FORMAT=json", readme)
            self.assertIn("docs/ARCHITECTURE.md", readme)
            self.assertIn("update `application.mainClass` in `build.gradle.kts`", readme)
            self.assertIn("# Sample App Agent Notes", agents)
            self.assertIn('./scripts/agent-gradle . run --args="example"', agents)
            self.assertIn("LOG_LEVEL=info ./scripts/agent-gradle . run", agents)
            self.assertIn("./scripts/agent-beans prime", agents)
            self.assertIn("./scripts/agent-task ps --match gradle", agents)
            self.assertIn("./scripts/agent-task logs .gradle/supermeta-gradle/logs", agents)
            self.assertIn("./scripts/agent-gradle . --ps", agents)
            self.assertIn("./scripts/agent-gradle . --logs", agents)
            self.assertIn("./scripts/agent-gradle . --stop", agents)
            self.assertNotIn("codex-bootstrap", readme.lower())
            self.assertNotIn("codex-bootstrap", agents.lower())
            assert_generated_operational_baseline(self, checkout)
            self.assertIn(
                "src/main/java/com/acme/sample/App.java",
                read_text(checkout / "docs" / "ARCHITECTURE.md"),
            )

            run_checked(["./scripts/agent-gradle", ".", "check"], cwd=checkout, timeout=360)
            run_checked(
                ["./scripts/agent-task", "logs", ".gradle/supermeta-gradle/logs"],
                cwd=checkout,
                timeout=120,
            )
            run_checked(["./scripts/agent-task", "ps", "--match", "gradle"], cwd=checkout, timeout=120)
            run_checked(["./scripts/agent-gradle", ".", "--logs"], cwd=checkout, timeout=120)
            run_checked(["./scripts/agent-gradle", ".", "--ps"], cwd=checkout, timeout=120)
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
            self.assertTrue((checkout / "scripts" / "agent-task").is_file())
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
            self.assertIn("uv run --no-editable sample-app", readme)
            self.assertIn("uv run --no-editable python -m sample_app", readme)
            self.assertIn("LOG_LEVEL=info LOG_FORMAT=json", readme)
            self.assertIn("./scripts/agent-beans prime", readme)
            self.assertIn("# Sample App Agent Notes", agents)
            self.assertIn("uv run --no-editable sample-app", agents)
            self.assertIn("LOG_LEVEL=info uv run --no-editable sample-app", agents)
            self.assertIn("./scripts/agent-beans prime", agents)
            self.assertNotIn("codex-bootstrap", readme.lower())
            self.assertNotIn("codex-bootstrap", agents.lower())
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
            self.assertTrue((checkout / "scripts" / "agent-task").is_file())
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
            self.assertIn("bun run src/main.ts", readme)
            self.assertIn("LOG_LEVEL=info LOG_FORMAT=json", readme)
            self.assertIn("./scripts/agent-beans prime", readme)
            self.assertIn("# Sample App Agent Notes", agents)
            self.assertIn("Bun is the only package-manager/runtime contract", agents)
            self.assertIn("LOG_LEVEL=info bun run src/main.ts", agents)
            self.assertIn("./scripts/agent-beans prime", agents)
            self.assertNotIn("codex-bootstrap", readme.lower())
            self.assertNotIn("codex-bootstrap", agents.lower())
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


def copy_bootstrap_checkout(destination: Path) -> None:
    shutil.copytree(
        REPO_ROOT,
        destination,
        ignore=shutil.ignore_patterns(
            ".git",
            ".bun",
            ".gradle",
            ".mypy_cache",
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
