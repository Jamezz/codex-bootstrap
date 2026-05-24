from __future__ import annotations

import json
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
            self.assertEqual((("uv", "run", "--no-editable", "pytest"),), policy.lanes["python-test"].commands)

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
            self.assertEqual((("uv", "run", "--no-editable", "pytest", "tests/test_cli.py"),), policy.lanes["python-test"].commands)
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
                    commands=(("uv", "run", "--no-editable", "pytest"),),
                    escalates_to="full",
                    stop_on_failure=True,
                ),
                "full": check.CheckLane(
                    lane_id="full",
                    description="Full check",
                    triggers=check.CheckTriggers(paths=()),
                    commands=(("./scripts/check",),),
                    escalates_to=None,
                    stop_on_failure=True,
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
                "triggers": {"paths": ["src/**/*.py", "tests/**/*.py"]},
                "commands": [["uv", "run", "--no-editable", "pytest"]],
                "escalatesTo": "full",
            },
            {
                "id": "full",
                "description": "Full check",
                "commands": [["./scripts/check"]],
            },
        ],
    }


def default_policy() -> check.CheckPolicy:
    raw = default_policy_json()
    return check.parse_policy(raw, generated=True)


if __name__ == "__main__":
    unittest.main()
