from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fix


class ClassificationTest(unittest.TestCase):
    def test_classifies_missing_tool(self) -> None:
        classification = fix.classify_failure("sh: uv: command not found\n")

        self.assertEqual("missing-tool", classification.classification_id)
        self.assertIn("./scripts/agent-task ps", classification.next_actions)

    def test_classifies_port_busy(self) -> None:
        classification = fix.classify_failure("OSError: address already in use: 127.0.0.1:8080\n")

        self.assertEqual("port-busy", classification.classification_id)
        self.assertIn("./scripts/agent-task ps", classification.next_actions)

    def test_classifies_gradle_stale_test_class(self) -> None:
        classification = fix.classify_failure("Could not execute test class 'com.acme.AppTest 2'\n")

        self.assertEqual("gradle-stale-class", classification.classification_id)
        self.assertIn("./scripts/agent-gradle . clean test", classification.next_actions)

    def test_classifies_style_type_unit_timeout_and_sync_failures(self) -> None:
        cases = {
            "biome check failed": "style-check",
            "mypy error: incompatible type": "typecheck",
            "FAILED tests/test_app.py::test_cli": "unit-test",
            "command timed out after 30s": "timeout",
            "Bootstrap sync conflict: managed region changed": "sync-conflict",
            "waiting for Gradle home lock": "lock-contention",
        }

        for output, expected in cases.items():
            with self.subTest(output=output):
                self.assertEqual(expected, fix.classify_failure(output).classification_id)

    def test_unknown_failure_has_log_action(self) -> None:
        classification = fix.classify_failure("surprising failure")

        self.assertEqual("unknown", classification.classification_id)
        self.assertIn(".codex-bootstrap/fix-loop/last.log", classification.next_actions)


class FixLoopCliTest(unittest.TestCase):
    def test_captures_child_output_and_preserves_exit_code(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fix-loop-cli-") as temp_dir:
            root = Path(temp_dir)
            output = fix.CapturedOutput()

            exit_code = fix.run_cli(
                ["--", "python3", "-c", "import sys; print('bad typecheck'); sys.exit(6)"],
                cwd=root,
                stdout=output,
            )

            self.assertEqual(6, exit_code)
            log_text = (root / ".codex-bootstrap" / "fix-loop" / "last.log").read_text(encoding="utf-8")
            self.assertIn("bad typecheck", log_text)
            self.assertIn("agent-fix-loop:", output.text())

    def test_missing_executable_is_captured_and_classified(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fix-loop-missing-exec-") as temp_dir:
            root = Path(temp_dir)
            output = fix.CapturedOutput()

            exit_code = fix.run_cli(["--", "__definitely_missing_codex_tool__"], cwd=root, stdout=output)

            self.assertEqual(127, exit_code)
            self.assertIn("missing-tool", output.text())
            self.assertIn("__definitely_missing_codex_tool__", (root / ".codex-bootstrap" / "fix-loop" / "last.log").read_text(encoding="utf-8"))

    def test_log_write_failure_returns_usage_error(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fix-loop-log-failure-") as temp_dir:
            root = Path(temp_dir)
            codex_path = root / ".codex-bootstrap"
            codex_path.write_text("not a directory", encoding="utf-8")
            output = fix.CapturedOutput()

            exit_code = fix.run_cli(["--", "python3", "-c", "print('cannot log')"], cwd=root, stdout=output)

            self.assertEqual(2, exit_code)
            self.assertIn("could not write", output.text())

    def test_does_not_mutate_source_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fix-loop-no-mutate-") as temp_dir:
            root = Path(temp_dir)
            source = root / "src.py"
            source.write_text("VALUE = 1\n", encoding="utf-8")
            before = source.read_text(encoding="utf-8")

            fix.run_cli(
                ["--", "python3", "-c", "import sys; print('FAILED test'); sys.exit(3)"],
                cwd=root,
                stdout=fix.CapturedOutput(),
            )

            self.assertEqual(before, source.read_text(encoding="utf-8"))
            self.assertFalse(os.path.exists(root / "src.py.tmp"))

    def test_requires_child_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fix-loop-no-child-") as temp_dir:
            output = fix.CapturedOutput()

            exit_code = fix.run_cli([], cwd=Path(temp_dir), stdout=output)

            self.assertEqual(2, exit_code)

    def test_success_preserves_child_output(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fix-loop-success-output-") as temp_dir:
            output = fix.CapturedOutput()

            exit_code = fix.run_cli(
                ["--", "python3", "-c", "print('selected fast lane')"],
                cwd=Path(temp_dir),
                stdout=output,
            )

            self.assertEqual(0, exit_code)
            self.assertIn("selected fast lane", output.text())


class FixLoopDiagnosticsTest(unittest.TestCase):
    def test_json_output_reports_classification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fix-loop-json-") as temp_dir:
            root = Path(temp_dir)
            output = fix.CapturedOutput()

            exit_code = fix.run_cli(
                ["--json", "--", "python3", "-c", "import sys; print('address already in use'); sys.exit(4)"],
                cwd=root,
                stdout=output,
            )

            self.assertEqual(4, exit_code)
            payload = json.loads(output.text())
            self.assertEqual("port-busy", payload["classification"]["id"])
            self.assertEqual(4, payload["exitCode"])

    def test_read_only_diagnostic_failure_does_not_replace_child_exit_code(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fix-loop-diag-") as temp_dir:
            root = Path(temp_dir)
            output = fix.CapturedOutput()

            exit_code = fix.run_cli(
                ["--run-diagnostics", "--", "python3", "-c", "import sys; print('address already in use'); sys.exit(4)"],
                cwd=root,
                stdout=output,
                diagnostic_runner=lambda command, cwd: fix.CommandResult(tuple(command), 99, "diagnostic failed"),
            )

            self.assertEqual(4, exit_code)
            self.assertIn("diagnostic failed", output.text())


if __name__ == "__main__":
    unittest.main()
