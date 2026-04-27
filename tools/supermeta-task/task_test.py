from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import ModuleType
from unittest.mock import patch


TASK_MODULE_PATH = Path(__file__).resolve().parent / "task.py"


def load_task_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("supermeta_task", TASK_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module from {TASK_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


task = load_task_module()


class TaskDiagnosticsTest(unittest.TestCase):
    def test_command_matches_any_pattern(self) -> None:
        self.assertTrue(task.command_matches("node ./scripts/build.js", ["gradle", "node"]))
        self.assertTrue(task.command_matches("JAVA GradleDaemon", ["gradledaemon"]))
        self.assertFalse(task.command_matches("python app.py", ["gradle", "npm"]))

    def test_ps_is_best_effort_when_process_listing_is_denied(self) -> None:
        with patch.object(task, "list_matching_processes", side_effect=task.ProcessListingError("denied")):
            output = StringIO()
            with redirect_stdout(output):
                exit_code = task.print_matching_processes(["gradle"], "matching task processes", True)

        self.assertEqual(0, exit_code)
        self.assertIn("process listing unavailable", output.getvalue())

    def test_kill_requires_explicit_match(self) -> None:
        with patch.object(sys, "argv", ["agent-task", "kill"]):
            output = StringIO()
            with redirect_stdout(output), redirect_stderr(output):
                exit_code = task.main()

        self.assertEqual(2, exit_code)

    def test_logs_lists_recent_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            log_dir = Path(temp_dir)
            first = log_dir / "first.log"
            second = log_dir / "second.log"
            first.write_text("first", encoding="utf-8")
            second.write_text("second", encoding="utf-8")

            output = StringIO()
            with redirect_stdout(output):
                exit_code = task.print_recent_logs(log_dir, 10)

        self.assertEqual(0, exit_code)
        self.assertIn("first.log", output.getvalue())
        self.assertIn("second.log", output.getvalue())


if __name__ == "__main__":
    unittest.main()
