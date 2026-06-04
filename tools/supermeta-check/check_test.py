from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


class PolicyLoadingTest(unittest.TestCase):
    def test_loads_generated_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-policy-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "checks.json",
                {
                    "schemaVersion": 1,
                    "templateId": "python-uv-cli",
                    "lanes": [
                        {
                            "id": "python-test",
                            "description": "Python tests",
                            "triggers": {"paths": ["src/**/*.py", "tests/**/*.py"]},
                            "commands": [["uv", "run", "--no-editable", "pytest"]],
                        },
                        {
                            "id": "full",
                            "description": "Full check",
                            "commands": [["./scripts/check"]],
                        },
                    ],
                },
            )

            policy, warnings = check.load_effective_policy(root)

            self.assertEqual((), warnings)
            self.assertEqual("python-uv-cli", policy.template_id)
            self.assertEqual(("python-test", "full"), tuple(policy.lanes))
            self.assertEqual((("uv", "run", "--no-editable", "pytest"),), tuple(command.argv for command in policy.lanes["python-test"].commands))

    def test_loads_lane_metadata_and_command_timeouts(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-metadata-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "checks.json",
                {
                    "schemaVersion": 1,
                    "templateId": "python-uv-cli",
                    "lanes": [
                        {
                            "id": "python-test",
                            "description": "Python tests",
                            "cost": "fast",
                            "tags": ["test", "python"],
                            "requires": ["uv"],
                            "timeoutSeconds": 45,
                            "triggers": {"paths": ["src/**/*.py"]},
                            "commands": [
                                {
                                    "argv": ["uv", "run", "--no-editable", "pytest"],
                                    "timeoutSeconds": 12,
                                }
                            ],
                        },
                        {"id": "full", "description": "Full check", "commands": [["./scripts/check"]]},
                    ],
                },
            )

            policy, warnings = check.load_effective_policy(root)
            lane = policy.lanes["python-test"]

            self.assertEqual((), warnings)
            self.assertEqual("fast", lane.cost)
            self.assertEqual(("test", "python"), lane.tags)
            self.assertEqual(("uv",), lane.requires)
            self.assertEqual(45, lane.timeout_seconds)
            self.assertEqual(12, lane.commands[0].timeout_seconds)

    def test_merges_local_override_by_lane_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-local-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)
            write_json(
                root / ".codex-bootstrap" / "checks.local.json",
                {
                    "schemaVersion": 1,
                    "lanes": [
                        {
                            "id": "python-test",
                            "commands": [["uv", "run", "--no-editable", "pytest", "tests/test_cli.py"]],
                        },
                        {
                            "id": "docs",
                            "description": "Docs only",
                            "triggers": {"paths": ["docs/**/*.md"]},
                            "commands": [["python3", "-m", "doctest", "README.md"]],
                        },
                    ],
                },
            )

            policy, warnings = check.load_effective_policy(root)

            self.assertEqual((), warnings)
            self.assertEqual((("uv", "run", "--no-editable", "pytest", "tests/test_cli.py"),), tuple(command.argv for command in policy.lanes["python-test"].commands))
            self.assertEqual(("docs", "full", "python-test"), tuple(sorted(policy.lanes)))

    def test_invalid_local_override_warns_and_uses_generated_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-bad-local-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)
            local_path = root / ".codex-bootstrap" / "checks.local.json"
            local_path.write_text("{not json", encoding="utf-8")

            policy, warnings = check.load_effective_policy(root)

            self.assertIn("ignored invalid local check policy", warnings[0])
            self.assertEqual(("python-test", "full"), tuple(policy.lanes))

    def test_invalid_generated_lane_falls_back_to_full_when_possible(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-bad-generated-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "checks.json",
                {
                    "schemaVersion": 1,
                    "templateId": "python-uv-cli",
                    "lanes": [
                        {"id": "broken", "commands": "not an array"},
                        {"id": "full", "description": "Full check", "commands": [["./scripts/check"]]},
                    ],
                },
            )
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--changed", "src/app.py", "--plan-only", "--json"], cwd=root, stdout=output)

            self.assertEqual(0, exit_code)
            payload = json.loads(output.text())
            self.assertEqual(["full"], [item["id"] for item in payload["plan"]])
            self.assertIn("invalid generated check policy", payload["warnings"][0])


class LaneSelectionTest(unittest.TestCase):
    def test_selects_matching_lane_and_full_escalation(self) -> None:
        policy = check.CheckPolicy(
            schema_version=1,
            template_id="python-uv-cli",
            lanes={
                "python-test": check.CheckLane(
                    lane_id="python-test",
                    description="Python tests",
                    triggers=check.CheckTriggers(paths=("src/**/*.py", "tests/**/*.py")),
                    commands=(check.CheckCommand(argv=("uv", "run", "--no-editable", "pytest"), timeout_seconds=None),),
                    escalates_to="full",
                    stop_on_failure=True,
                    cost="fast",
                    tags=("test",),
                    requires=("uv",),
                    timeout_seconds=None,
                ),
                "full": check.CheckLane(
                    lane_id="full",
                    description="Full check",
                    triggers=check.CheckTriggers(paths=()),
                    commands=(check.CheckCommand(argv=("./scripts/check",), timeout_seconds=None),),
                    escalates_to=None,
                    stop_on_failure=True,
                    cost="full",
                    tags=("full",),
                    requires=(),
                    timeout_seconds=None,
                ),
            },
        )

        plan = check.select_lanes(policy, ("src/python_uv_cli/cli.py",), force_full=False)

        self.assertEqual(("python-test", "full"), tuple(item.lane.lane_id for item in plan.items))
        self.assertIn("matched src/python_uv_cli/cli.py", plan.items[0].reason)

    def test_no_changes_falls_back_to_full(self) -> None:
        policy = default_policy()

        plan = check.select_lanes(policy, (), force_full=False)

        self.assertEqual(("full",), tuple(item.lane.lane_id for item in plan.items))
        self.assertEqual("no changed files; using full lane", plan.items[0].reason)

    def test_full_flag_forces_full_lane(self) -> None:
        policy = default_policy()

        plan = check.select_lanes(policy, ("src/python_uv_cli/cli.py",), force_full=True)

        self.assertEqual(("full",), tuple(item.lane.lane_id for item in plan.items))
        self.assertEqual("forced full lane", plan.items[0].reason)

    def test_fast_only_filters_out_non_fast_lanes(self) -> None:
        policy = default_policy()

        plan = check.select_lanes(policy, ("src/python_uv_cli/cli.py",), force_full=False, fast_only=True, tags=())

        self.assertEqual(("python-test",), tuple(item.lane.lane_id for item in plan.items))

    def test_tag_filter_selects_matching_lanes(self) -> None:
        policy = default_policy()

        plan = check.select_lanes(policy, ("src/python_uv_cli/cli.py",), force_full=False, fast_only=False, tags=("test",))

        self.assertEqual(("python-test", "full"), tuple(item.lane.lane_id for item in plan.items))


class GitChangedFilesTest(unittest.TestCase):
    def test_explicit_changed_files_bypass_git(self) -> None:
        args = check.parse_args(["--changed", "src/app.py", "tests/test_app.py", "--plan-only", "--timeout", "9", "--tag", "test"])

        self.assertEqual(("src/app.py", "tests/test_app.py"), tuple(args.changed))
        self.assertEqual(9, args.timeout)
        self.assertEqual(("test",), tuple(args.tag))

    def test_hygiene_flags_parse(self) -> None:
        args = check.parse_args(["--hygiene-only", "--no-hygiene"])

        self.assertTrue(args.hygiene_only)
        self.assertTrue(args.no_hygiene)

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_detects_staged_unstaged_and_untracked_files(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-git-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            run_git(root, "config", "user.email", "agent@example.invalid")
            run_git(root, "config", "user.name", "Agent")
            (root / "tracked.py").write_text("print('old')\n", encoding="utf-8")
            (root / "staged.py").write_text("print('old')\n", encoding="utf-8")
            run_git(root, "add", ".")
            run_git(root, "commit", "-m", "initial")
            (root / "tracked.py").write_text("print('new')\n", encoding="utf-8")
            (root / "staged.py").write_text("print('new')\n", encoding="utf-8")
            (root / "untracked.py").write_text("print('new')\n", encoding="utf-8")
            run_git(root, "add", "staged.py")

            changed = check.detect_changed_files(root, since="")

            self.assertEqual(("staged.py", "tracked.py", "untracked.py"), tuple(sorted(changed)))

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_since_uses_git_diff_name_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-since-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            run_git(root, "config", "user.email", "agent@example.invalid")
            run_git(root, "config", "user.name", "Agent")
            (root / "first.py").write_text("print('first')\n", encoding="utf-8")
            run_git(root, "add", ".")
            run_git(root, "commit", "-m", "first")
            base = run_git(root, "rev-parse", "HEAD").stdout.strip()
            (root / "second.py").write_text("print('second')\n", encoding="utf-8")
            run_git(root, "add", ".")
            run_git(root, "commit", "-m", "second")

            changed = check.detect_changed_files(root, since=base)

            self.assertEqual(("second.py",), changed)


class CliExecutionTest(unittest.TestCase):
    def test_plan_only_prints_selected_lanes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-cli-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--changed", "src/python_uv_cli/cli.py", "--plan-only"], cwd=root, stdout=output)

            self.assertEqual(0, exit_code)
            self.assertIn("agent-smart-check: selected python-test", output.text())
            self.assertIn("uv run --no-editable pytest", output.text())

    def test_json_plan_only_outputs_machine_readable_plan(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-json-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)
            output = check.CapturedOutput()

            exit_code = check.run_cli(
                ["--changed", "src/python_uv_cli/cli.py", "--plan-only", "--json"],
                cwd=root,
                stdout=output,
            )

            self.assertEqual(0, exit_code)
            payload = json.loads(output.text())
            self.assertEqual(["python-test", "full"], [item["id"] for item in payload["plan"]])
            self.assertFalse(payload["executed"])
            self.assertEqual("fast", payload["plan"][0]["cost"])
            self.assertIn("test", payload["plan"][0]["tags"])

    def test_executes_commands_and_returns_first_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-exec-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "checks.json",
                {
                    "schemaVersion": 1,
                    "templateId": "python-uv-cli",
                    "lanes": [
                        {
                            "id": "python-test",
                            "description": "Python tests",
                            "triggers": {"paths": ["src/**/*.py"]},
                            "commands": [["python3", "-c", "import sys; sys.exit(7)"]],
                            "stopOnFailure": True,
                        },
                        {"id": "full", "description": "Full", "commands": [["python3", "-c", "print('full')"]]},
                    ],
                },
            )
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--changed", "src/app.py"], cwd=root, stdout=output)

            self.assertEqual(7, exit_code)
            self.assertIn("python-test", output.text())

    def test_execution_reports_progress_and_heartbeat(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-progress-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)
            output = check.CapturedOutput()
            clock = FakeClock()

            def slow_runner(
                command: list[str],
                cwd: Path,
                timeout_seconds: float | None = None,
                progress: check.CommandProgress | None = None,
            ) -> check.CommandResult:
                self.assertIsNotNone(progress)
                clock.advance(30)
                progress.maybe_emit_heartbeat()
                return check.CommandResult(command=tuple(command), exit_code=0, output="command output\n")

            exit_code = check.run_cli(
                ["--changed", "unmatched.txt"],
                cwd=root,
                stdout=output,
                command_runner=slow_runner,
                progress_clock=clock,
            )

            text = output.text()
            self.assertEqual(0, exit_code)
            self.assertIn("agent-smart-check: file scan complete; selected 1 lane and 1 command", text)
            self.assertIn("agent-smart-check: running full command 1/1: ./scripts/check", text)
            self.assertIn("agent-smart-check: still running after 30s: full command 1/1: ./scripts/check", text)
            self.assertIn("agent-smart-check: finished full command 1/1 after 30s with exit code 0", text)
            self.assertLess(text.index("file scan complete"), text.index("command output"))

    def test_missing_required_tool_fails_before_command_execution(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-requires-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "checks.json",
                {
                    "schemaVersion": 1,
                    "templateId": "python-uv-cli",
                    "lanes": [
                        {
                            "id": "python-test",
                            "description": "Python tests",
                            "triggers": {"paths": ["src/**/*.py"]},
                            "requires": ["__missing_codex_tool__"],
                            "commands": [["python3", "-c", "print('should not run')"]],
                        },
                        {"id": "full", "description": "Full", "commands": [["python3", "-c", "print('full')"]]},
                    ],
                },
            )
            output = check.CapturedOutput()

            def fail_if_called(command: list[str], cwd: Path, timeout_seconds: float | None = None) -> check.CommandResult:
                raise AssertionError(f"command should not run: {command}")

            exit_code = check.run_cli(
                ["--changed", "src/app.py"],
                cwd=root,
                stdout=output,
                command_runner=fail_if_called,
            )

            self.assertEqual(127, exit_code)
            self.assertIn("missing required tool", output.text())

    def test_command_timeout_returns_timeout_exit_code(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-timeout-") as temp_dir:
            root = Path(temp_dir)
            result = check.run_command(
                ["python3", "-c", "import time; time.sleep(2)"],
                root,
                timeout_seconds=0.1,
            )

            self.assertEqual(124, result.exit_code)
            self.assertIn("timed out", result.output)

    def test_self_test_reports_invalid_escalation_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-self-test-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "checks.json",
                {
                    "schemaVersion": 1,
                    "templateId": "python-uv-cli",
                    "lanes": [
                        {
                            "id": "python-test",
                            "description": "Python tests",
                            "triggers": {"paths": ["src/**/*.py"]},
                            "commands": [["python3", "-m", "unittest"]],
                            "escalatesTo": "missing",
                        },
                        {"id": "full", "description": "Full", "commands": [["./scripts/check"]]},
                    ],
                },
            )
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--self-test", "--json"], cwd=root, stdout=output)

            self.assertEqual(2, exit_code)
            payload = json.loads(output.text())
            self.assertIn("unknown escalatesTo target missing", payload["errors"][0])

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_plan_only_reports_hygiene_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-hygiene-plan-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--plan-only"], cwd=root, stdout=output)

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "App 2.java").exists())
            self.assertIn("hygiene would trash exact duplicate App 2.java", output.text())

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_json_includes_hygiene_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-hygiene-json-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--plan-only", "--json"], cwd=root, stdout=output)

            self.assertEqual(0, exit_code)
            payload = json.loads(output.text())
            self.assertTrue(payload["hygiene"]["enabled"])
            self.assertFalse(payload["hygiene"]["reviewNeeded"])
            self.assertEqual("trash", payload["hygiene"]["actions"][0]["action"])

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_divergent_duplicate_blocks_verification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-hygiene-block-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App2 {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            def fail_if_called(command: list[str], cwd: Path, timeout_seconds: float | None = None) -> check.CommandResult:
                raise AssertionError(f"verification should not run: {command}")

            exit_code = check.run_cli([], cwd=root, stdout=output, command_runner=fail_if_called)

            self.assertEqual(3, exit_code)
            self.assertFalse((root / "App 2.java").exists())
            self.assertTrue((root / ".codex-bootstrap" / "cleanup-quarantine").exists())
            self.assertIn("destination: .codex-bootstrap/cleanup-quarantine/", output.text())
            self.assertIn("review: .codex-bootstrap/cleanup-quarantine/", output.text())
            self.assertIn("hygiene needs review; verification skipped", output.text())

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_no_hygiene_preserves_existing_behavior(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-no-hygiene-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App2 {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--no-hygiene", "--plan-only"], cwd=root, stdout=output)

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "App 2.java").exists())
            self.assertNotIn("hygiene", output.text())

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_hygiene_only_runs_no_verification_commands(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-hygiene-only-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            def fail_if_called(command: list[str], cwd: Path, timeout_seconds: float | None = None) -> check.CommandResult:
                raise AssertionError(f"verification should not run: {command}")

            exit_code = check.run_cli(["--hygiene-only"], cwd=root, stdout=output, command_runner=fail_if_called)

            self.assertEqual(0, exit_code)
            self.assertIn("hygiene", output.text())


def write_default_policy(root: Path) -> None:
    write_json(root / ".codex-bootstrap" / "checks.json", default_policy_json())


def default_policy_json() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "templateId": "python-uv-cli",
        "lanes": [
            {
                "id": "python-test",
                "description": "Python tests",
                "cost": "fast",
                "tags": ["test", "python"],
                "requires": ["uv"],
                "triggers": {"paths": ["src/**/*.py", "tests/**/*.py"]},
                "commands": [["uv", "run", "--no-editable", "pytest"]],
                "escalatesTo": "full",
            },
            {
                "id": "full",
                "description": "Full check",
                "cost": "full",
                "tags": ["full"],
                "commands": [["./scripts/check"]],
            },
        ],
    }


def default_policy() -> check.CheckPolicy:
    raw = default_policy_json()
    return check.parse_policy(raw, generated=True)


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed:\n{result.stdout}")
    return result


class FakeClock:
    def __init__(self) -> None:
        self.current = 0.0

    def __call__(self) -> float:
        return self.current

    def advance(self, seconds: float) -> None:
        self.current += seconds


if __name__ == "__main__":
    unittest.main()
