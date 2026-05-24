from __future__ import annotations

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

    def test_requires_child_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fix-loop-no-child-") as temp_dir:
            output = fix.CapturedOutput()

            exit_code = fix.run_cli([], cwd=Path(temp_dir), stdout=output)

            self.assertEqual(2, exit_code)


if __name__ == "__main__":
    unittest.main()
