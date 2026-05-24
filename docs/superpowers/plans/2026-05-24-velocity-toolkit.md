# Velocity Toolkit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the v1 Codex Bootstrap velocity toolkit: `agent-smart-check` for focused verification selection and `agent-fix-loop` for failure capture/classification.

**Architecture:** Add two stdlib-first helper packages under `tools/supermeta-check/` and `tools/supermeta-fix/`, thin Unix/PowerShell wrappers under `scripts/`, generated `.codex-bootstrap/checks.json`, and a `velocity-tools` sync managed set across all runnable templates. Existing full checks remain authoritative; the new tools accelerate the inner loop and feed actionable diagnostics.

**Tech Stack:** Python 3 stdlib, shell wrappers, PowerShell wrappers, JSON config, existing `tools/bootstrap/bootstrap.py` generator, existing `tools/pages/build_pages.py` metadata builder, `unittest`.

---

## File Structure

Create:

- `scripts/agent-smart-check`: Unix wrapper that invokes `tools/supermeta-check/check.py`.
- `scripts/agent-smart-check.ps1`: PowerShell wrapper equivalent.
- `scripts/agent-fix-loop`: Unix wrapper that invokes `tools/supermeta-fix/fix.py`.
- `scripts/agent-fix-loop.ps1`: PowerShell wrapper equivalent.
- `tools/supermeta-check/README.md`: CLI contract and config examples.
- `tools/supermeta-check/check.py`: smart-check config loading, lane selection, execution, and JSON output.
- `tools/supermeta-check/check_test.py`: focused unit tests for smart-check behavior.
- `tools/supermeta-fix/README.md`: CLI contract and classifier examples.
- `tools/supermeta-fix/fix.py`: fix-loop command runner, log capture, classification, diagnostics, and JSON output.
- `tools/supermeta-fix/fix_test.py`: focused unit tests for fix-loop behavior.

Modify:

- `tools/bootstrap/bootstrap.py`: generate `.codex-bootstrap/checks.json`, velocity docs regions, checks metadata, and sync hashes.
- `tools/bootstrap/bootstrap_test.py`: assert manifests, staged projects, generated docs, sync metadata, and smart-check smoke behavior.
- `tools/pages/pages_test.py`: assert Pages metadata exposes `velocity-tools`.
- `README.md`: document root-level velocity tool contract after implementation.
- `AGENTS.md`: add root working rule for velocity tools and full-check gate after implementation.
- `CHANGELOG.md`: record generated contract impact and verification.
- `templates/*/bootstrap-template.json`: add support paths, `velocity-tools` managed set, `.codex-bootstrap/checks.json`, and generated doc regions.

No existing product source files under `templates/*/src` should need behavior changes.

---

### Task 1: Smart Check Core

**Files:**
- Create: `tools/supermeta-check/check.py`
- Create: `tools/supermeta-check/check_test.py`
- Create: `tools/supermeta-check/README.md`

- [ ] **Step 1: Write failing config-loading and lane-selection tests**

Add `tools/supermeta-check/check_test.py`:

```python
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
```

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'
```

Expected: FAIL with `ModuleNotFoundError: No module named 'check'`.

- [ ] **Step 3: Implement policy parsing and lane selection**

Create `tools/supermeta-check/check.py` with this public structure:

```python
#!/usr/bin/env python3
"""Focused verification lane selection for Codex Bootstrap generated projects."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CHECKS_POLICY = Path(".codex-bootstrap/checks.json")
LOCAL_POLICY = Path(".codex-bootstrap/checks.local.json")
SCHEMA_VERSION = 1


class SmartCheckError(Exception):
    pass


@dataclass(frozen=True)
class CheckTriggers:
    paths: tuple[str, ...]


@dataclass(frozen=True)
class CheckLane:
    lane_id: str
    description: str
    triggers: CheckTriggers
    commands: tuple[tuple[str, ...], ...]
    escalates_to: str | None
    stop_on_failure: bool


@dataclass(frozen=True)
class CheckPolicy:
    schema_version: int
    template_id: str
    lanes: dict[str, CheckLane]


@dataclass(frozen=True)
class PlanItem:
    lane: CheckLane
    reason: str


@dataclass(frozen=True)
class CheckPlan:
    items: tuple[PlanItem, ...]


def load_effective_policy(root: Path) -> tuple[CheckPolicy, tuple[str, ...]]:
    generated = parse_policy(load_json(root / CHECKS_POLICY), generated=True)
    local_path = root / LOCAL_POLICY
    if not local_path.exists():
        return generated, ()
    try:
        local = parse_policy(load_json(local_path), generated=False, template_id=generated.template_id)
    except (SmartCheckError, OSError, json.JSONDecodeError) as error:
        return generated, (f"ignored invalid local check policy {LOCAL_POLICY}: {error}",)
    return merge_policy(generated, local), ()


def parse_policy(raw: dict[str, Any], generated: bool, template_id: str | None = None) -> CheckPolicy:
    schema_version = require_int(raw, "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise SmartCheckError(f"unsupported checks schema {schema_version}")
    policy_template_id = require_string(raw, "templateId") if generated else (optional_string(raw, "templateId") or template_id or "")
    raw_lanes = raw.get("lanes")
    if not isinstance(raw_lanes, list):
        raise SmartCheckError("lanes must be an array")
    lanes: dict[str, CheckLane] = {}
    for index, item in enumerate(raw_lanes):
        if not isinstance(item, dict):
            raise SmartCheckError(f"lanes[{index}] must be an object")
        lane_id = require_string(item, "id")
        if lane_id in lanes:
            raise SmartCheckError(f"duplicate lane id: {lane_id}")
        lanes[lane_id] = parse_lane(item, generated)
    if generated and "full" not in lanes:
        raise SmartCheckError("generated checks policy must define full lane")
    return CheckPolicy(schema_version=schema_version, template_id=policy_template_id, lanes=lanes)


def parse_lane(raw: dict[str, Any], generated: bool) -> CheckLane:
    triggers_raw = raw.get("triggers", {})
    if not isinstance(triggers_raw, dict):
        raise SmartCheckError("lane triggers must be an object")
    commands_raw = raw.get("commands", [] if not generated else None)
    if not isinstance(commands_raw, list):
        raise SmartCheckError("lane commands must be an array")
    return CheckLane(
        lane_id=require_string(raw, "id"),
        description=optional_string(raw, "description") or "",
        triggers=CheckTriggers(paths=tuple(require_string_list(triggers_raw, "paths", allow_missing=True))),
        commands=parse_commands(commands_raw),
        escalates_to=optional_nullable_string(raw, "escalatesTo"),
        stop_on_failure=optional_bool(raw, "stopOnFailure", True),
    )


def merge_policy(generated: CheckPolicy, local: CheckPolicy) -> CheckPolicy:
    lanes = dict(generated.lanes)
    for lane_id, override in local.lanes.items():
        base = lanes.get(lane_id)
        if base is None:
            lanes[lane_id] = override
            continue
        lanes[lane_id] = CheckLane(
            lane_id=lane_id,
            description=override.description or base.description,
            triggers=override.triggers if override.triggers.paths else base.triggers,
            commands=override.commands if override.commands else base.commands,
            escalates_to=override.escalates_to if override.escalates_to is not None else base.escalates_to,
            stop_on_failure=override.stop_on_failure,
        )
    return CheckPolicy(schema_version=generated.schema_version, template_id=generated.template_id, lanes=lanes)


def select_lanes(policy: CheckPolicy, changed_files: tuple[str, ...], force_full: bool) -> CheckPlan:
    if force_full:
        return CheckPlan((PlanItem(require_lane(policy, "full"), "forced full lane"),))
    if not changed_files:
        return CheckPlan((PlanItem(require_lane(policy, "full"), "no changed files; using full lane"),))
    selected: list[PlanItem] = []
    seen: set[str] = set()
    for lane in policy.lanes.values():
        if lane.lane_id == "full":
            continue
        reason = match_reason(lane, changed_files)
        if reason:
            add_lane(policy, lane.lane_id, reason, selected, seen)
            if lane.escalates_to:
                add_lane(policy, lane.escalates_to, f"escalated from {lane.lane_id}", selected, seen)
    if not selected:
        add_lane(policy, "full", "no lane matched changed files", selected, seen)
    return CheckPlan(tuple(selected))


def add_lane(policy: CheckPolicy, lane_id: str, reason: str, selected: list[PlanItem], seen: set[str]) -> None:
    if lane_id in seen:
        return
    selected.append(PlanItem(require_lane(policy, lane_id), reason))
    seen.add(lane_id)


def require_lane(policy: CheckPolicy, lane_id: str) -> CheckLane:
    try:
        return policy.lanes[lane_id]
    except KeyError as error:
        raise SmartCheckError(f"missing lane: {lane_id}") from error


def match_reason(lane: CheckLane, changed_files: tuple[str, ...]) -> str | None:
    for changed_file in changed_files:
        normalized = changed_file.replace("\\", "/")
        for pattern in lane.triggers.paths:
            if fnmatch.fnmatch(normalized, pattern):
                return f"matched {normalized} with {pattern}"
    return None
```

Also include `load_json`, `require_string`, `optional_string`, `optional_nullable_string`, `require_int`, `optional_bool`, `require_string_list`, and `parse_commands` helpers following the style in `tools/supermeta-nag/nag.py`.

- [ ] **Step 4: Run tests and verify Task 1 passes**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 5: Add smart-check README**

Create `tools/supermeta-check/README.md`:

```markdown
# Supermeta Smart Check

`check.py` selects focused verification lanes from changed files in Codex Bootstrap generated projects.

```bash
./scripts/agent-smart-check --plan-only
./scripts/agent-smart-check --since HEAD~1
./scripts/agent-smart-check --changed src/example.py tests/test_example.py
./scripts/agent-smart-check --json
./scripts/agent-smart-check --full
```

Generated policy lives in `.codex-bootstrap/checks.json`. Local override policy lives in `.codex-bootstrap/checks.local.json` and merges lanes by `id`.

Focused lanes are an inner-loop accelerator. Run the template full check before handoff.
```

- [ ] **Step 6: Commit Task 1**

```bash
git add tools/supermeta-check
git commit -m "feat: add smart check lane planner"
```

---

### Task 2: Smart Check CLI, Git Detection, Execution, And Wrappers

**Files:**
- Modify: `tools/supermeta-check/check.py`
- Modify: `tools/supermeta-check/check_test.py`
- Create: `scripts/agent-smart-check`
- Create: `scripts/agent-smart-check.ps1`

- [ ] **Step 1: Add failing CLI, Git, JSON, and execution tests**

Append tests to `tools/supermeta-check/check_test.py`:

```python
class GitChangedFilesTest(unittest.TestCase):
    def test_explicit_changed_files_bypass_git(self) -> None:
        args = check.parse_args(["--changed", "src/app.py", "tests/test_app.py", "--plan-only"])

        self.assertEqual(("src/app.py", "tests/test_app.py"), tuple(args.changed))


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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'
```

Expected: FAIL because `parse_args`, `run_cli`, and `CapturedOutput` are not implemented.

- [ ] **Step 3: Implement CLI and execution**

Add to `tools/supermeta-check/check.py`:

```python
@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    output: str


class CapturedOutput:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> None:
        self.parts.append(text)

    def text(self) -> str:
        return "".join(self.parts)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run focused Codex Bootstrap verification lanes.")
    parser.add_argument("--since", default="")
    parser.add_argument("--changed", nargs="*", default=[])
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--full", action="store_true")
    return parser.parse_args(argv)


def run_cli(argv: list[str], cwd: Path | None = None, stdout=None, command_runner=None) -> int:
    args = parse_args(argv)
    root = (cwd or Path.cwd()).resolve()
    output = stdout or sys.stdout
    runner = command_runner or run_command
    try:
        policy, warnings = load_effective_policy(root)
        for warning in warnings:
            print(f"agent-smart-check: {warning}", file=sys.stderr)
        changed_files = tuple(args.changed) if args.changed else detect_changed_files(root, args.since)
        plan = select_lanes(policy, changed_files, force_full=args.full)
        results: list[CommandResult] = []
        exit_code = 0
        if not args.plan_only:
            for item in plan.items:
                for command in item.lane.commands:
                    result = runner(list(command), root)
                    results.append(result)
                    if result.output:
                        output.write(result.output)
                    if result.exit_code != 0:
                        exit_code = result.exit_code
                        if item.lane.stop_on_failure:
                            return print_result(plan, results, args.json, True, exit_code, output)
        return print_result(plan, results, args.json, not args.plan_only, exit_code, output)
    except SmartCheckError as error:
        print(f"agent-smart-check: {error}", file=sys.stderr)
        return 2


def detect_changed_files(root: Path, since: str) -> tuple[str, ...]:
    if since:
        result = subprocess.run(
            ["git", "diff", "--name-only", since, "--"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return tuple(line for line in result.stdout.splitlines() if line)
    status = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        return ()
    changed: list[str] = []
    for line in status.stdout.splitlines():
        if not line:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        changed.append(path)
    return tuple(changed)


def run_command(command: list[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return CommandResult(command=tuple(command), exit_code=completed.returncode, output=completed.stdout)


def print_result(
    plan: CheckPlan,
    results: list[CommandResult],
    as_json: bool,
    executed: bool,
    exit_code: int,
    output,
) -> int:
    if as_json:
        output.write(json.dumps(result_payload(plan, results, executed, exit_code), indent=2, sort_keys=True) + "\n")
        return exit_code
    for item in plan.items:
        output.write(f"agent-smart-check: selected {item.lane.lane_id}\n")
        output.write(f"  reason: {item.reason}\n")
        output.write("  commands:\n")
        for command in item.lane.commands:
            output.write(f"    {' '.join(command)}\n")
    return exit_code


def result_payload(plan: CheckPlan, results: list[CommandResult], executed: bool, exit_code: int) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "executed": executed,
        "exitCode": exit_code,
        "plan": [
            {
                "id": item.lane.lane_id,
                "description": item.lane.description,
                "reason": item.reason,
                "commands": [list(command) for command in item.lane.commands],
            }
            for item in plan.items
        ],
        "results": [
            {"command": list(result.command), "exitCode": result.exit_code}
            for result in results
        ],
    }


def main() -> int:
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Add wrappers**

Create `scripts/agent-smart-check`:

```sh
#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd "$script_dir/.." && pwd)

exec python3 "$repo_root/tools/supermeta-check/check.py" "$@"
```

Create `scripts/agent-smart-check.ps1`:

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-PythonChecked {
    $PythonArgs = @($args)

    $python = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        exit $LASTEXITCODE
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        exit $LASTEXITCODE
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 @PythonArgs
        exit $LASTEXITCODE
    }

    [Console]::Error.WriteLine("scripts/agent-smart-check.ps1: python3, python, or py is required")
    exit 2
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$smartCheckScript = Join-Path $repoRoot "tools/supermeta-check/check.py"
$pythonArgs = @($smartCheckScript)
$pythonArgs += $args
Invoke-PythonChecked @pythonArgs
```

Run:

```bash
chmod +x scripts/agent-smart-check
```

- [ ] **Step 5: Run Task 2 tests**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'
./scripts/agent-smart-check --changed docs/superpowers/specs/2026-05-24-velocity-toolkit-design.md --plan-only
```

Expected: unit tests PASS. The wrapper may report missing generated check policy in the catalog until Task 5 wires root/catalog support; that is acceptable only if the unit tests pass. If the wrapper exits with usage or Python errors, fix the wrapper now.

- [ ] **Step 6: Commit Task 2**

```bash
git add scripts/agent-smart-check scripts/agent-smart-check.ps1 tools/supermeta-check
git commit -m "feat: add smart check CLI"
```

---

### Task 3: Fix Loop Core

**Files:**
- Create: `tools/supermeta-fix/fix.py`
- Create: `tools/supermeta-fix/fix_test.py`
- Create: `tools/supermeta-fix/README.md`

- [ ] **Step 1: Write failing fix-loop tests**

Create `tools/supermeta-fix/fix_test.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'
```

Expected: FAIL with `ModuleNotFoundError: No module named 'fix'`.

- [ ] **Step 3: Implement fix-loop core**

Create `tools/supermeta-fix/fix.py`:

```python
#!/usr/bin/env python3
"""Failure capture and next-action hints for Codex Bootstrap generated projects."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


LAST_LOG = Path(".codex-bootstrap/fix-loop/last.log")
SCHEMA_VERSION = 1


class FixLoopError(Exception):
    pass


@dataclass(frozen=True)
class FailureClassification:
    classification_id: str
    summary: str
    next_actions: tuple[str, ...]
    diagnostics: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    output: str


class CapturedOutput:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> None:
        self.parts.append(text)

    def text(self) -> str:
        return "".join(self.parts)


def classify_failure(output: str) -> FailureClassification:
    lowered = output.lower()
    if "command not found" in lowered or "no such file or directory" in lowered:
        return FailureClassification(
            "missing-tool",
            "A required tool or executable is missing.",
            ("Install the missing tool or use the repo wrapper that provides it.", "./scripts/agent-task ps"),
        )
    if "address already in use" in lowered or "port is already allocated" in lowered:
        return FailureClassification(
            "port-busy",
            "A local port is already in use.",
            ("Inspect running processes before retrying.", "./scripts/agent-task ps"),
            (("./scripts/agent-task", "ps"),),
        )
    if "could not execute test class" in lowered and " 2" in output:
        return FailureClassification(
            "gradle-stale-class",
            "Gradle may be seeing a stale compiled duplicate test class.",
            ("Run a clean test for the affected module.", "./scripts/agent-gradle . clean test"),
            (("./scripts/agent-gradle", ".", "--logs"),),
        )
    if "checkstyle" in lowered or "ruff" in lowered or "biome" in lowered or "lint" in lowered:
        return FailureClassification(
            "style-check",
            "Formatter or linter verification failed.",
            ("Read the reported file and line, apply the smallest source fix, then rerun smart-check.",),
        )
    if "mypy" in lowered or "typecheck" in lowered or "tsc" in lowered or "cs" in lowered and "error" in lowered:
        return FailureClassification(
            "typecheck",
            "Static type checking failed.",
            ("Fix the named type error, then rerun smart-check.",),
        )
    if "assert" in lowered or "failed" in lowered and "test" in lowered:
        return FailureClassification(
            "unit-test",
            "A unit test failed.",
            ("Read the first failing test and assertion, fix behavior or test expectation, then rerun smart-check.",),
        )
    if "timed out" in lowered or "timeout" in lowered:
        return FailureClassification(
            "timeout",
            "The command timed out or appears hung.",
            ("Inspect task processes and recent logs before retrying.", "./scripts/agent-task ps"),
            (("./scripts/agent-task", "ps"),),
        )
    if "bootstrap sync" in lowered and "conflict" in lowered or "managed region" in lowered and "conflict" in lowered:
        return FailureClassification(
            "sync-conflict",
            "Bootstrap sync reported a managed file or region conflict.",
            ("Run ./scripts/agent-bootstrap sync --dry-run and inspect the named managed target.",),
            (("./scripts/agent-bootstrap", "sync", "--dry-run"),),
        )
    return FailureClassification(
        "unknown",
        "Could not classify this failure.",
        ("Inspect .codex-bootstrap/fix-loop/last.log.", "./scripts/agent-task ps"),
        (("./scripts/agent-task", "ps"),),
    )
```

Add these concrete functions to the same file:

```python
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture command failures and print next diagnostic actions.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--run-diagnostics", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("child_command", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def run_cli(argv: list[str], cwd: Path | None = None, stdout=None, diagnostic_runner=None) -> int:
    args = parse_args(argv)
    root = (cwd or Path.cwd()).resolve()
    output = stdout or sys.stdout
    child_command = tuple(args.child_command[1:] if args.child_command[:1] == ["--"] else args.child_command)
    if not child_command:
        print("agent-fix-loop: child command is required after --", file=sys.stderr)
        return 2
    result = run_child(child_command, root)
    write_last_log(root, result.output)
    if result.exit_code == 0:
        if args.json:
            output.write(json.dumps(success_payload(result), indent=2, sort_keys=True) + "\n")
        else:
            output.write("agent-fix-loop: command passed\n")
        return 0
    classification = classify_failure(result.output)
    diagnostics = maybe_run_diagnostics(root, classification, args.run_diagnostics, diagnostic_runner or run_child)
    if args.json:
        output.write(json.dumps(failure_payload(result, classification, diagnostics), indent=2, sort_keys=True) + "\n")
    else:
        print_classification(classification, diagnostics, output)
    return result.exit_code


def run_child(command: tuple[str, ...] | list[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return CommandResult(command=tuple(command), exit_code=completed.returncode, output=completed.stdout)


def write_last_log(root: Path, output: str) -> Path:
    destination = root / LAST_LOG
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(output, encoding="utf-8")
    return destination


def maybe_run_diagnostics(root: Path, classification: FailureClassification, enabled: bool, runner) -> tuple[CommandResult, ...]:
    if not enabled:
        return ()
    results: list[CommandResult] = []
    for command in classification.diagnostics:
        results.append(runner(command, root))
    return tuple(results)


def print_classification(classification: FailureClassification, diagnostics: tuple[CommandResult, ...], output) -> None:
    output.write(f"agent-fix-loop: {classification.classification_id}\n")
    output.write(f"  {classification.summary}\n")
    output.write("  next actions:\n")
    for action in classification.next_actions:
        output.write(f"    {action}\n")
    for diagnostic in diagnostics:
        output.write(f"  diagnostic {' '.join(diagnostic.command)} exited {diagnostic.exit_code}\n")
        if diagnostic.output:
            output.write(diagnostic.output)
```

Also add `success_payload`, `failure_payload`, and `main` helpers. `failure_payload` must include `schemaVersion`, `command`, `exitCode`, `logPath`, `classification.id`, `classification.summary`, `classification.nextActions`, and `diagnostics`.

- [ ] **Step 4: Run tests and verify Task 3 passes**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 5: Add fix-loop README**

Create `tools/supermeta-fix/README.md`:

```markdown
# Supermeta Fix Loop

`fix.py` wraps a command, captures combined output, classifies common failures, and prints next diagnostic actions.

```bash
./scripts/agent-fix-loop -- ./scripts/agent-smart-check
./scripts/agent-fix-loop --max-attempts 2 -- ./scripts/check
```

The last captured output is written to `.codex-bootstrap/fix-loop/last.log`.

V1 does not edit source, generated files, or lockfiles. It only captures output, classifies known failure shapes, and may run read-only diagnostics.
```

- [ ] **Step 6: Commit Task 3**

```bash
git add tools/supermeta-fix
git commit -m "feat: add fix loop diagnostics"
```

---

### Task 4: Fix Loop CLI Wrappers And Integration

**Files:**
- Modify: `tools/supermeta-fix/fix.py`
- Modify: `tools/supermeta-fix/fix_test.py`
- Create: `scripts/agent-fix-loop`
- Create: `scripts/agent-fix-loop.ps1`

- [ ] **Step 1: Add failing diagnostics and JSON tests**

Append tests to `tools/supermeta-fix/fix_test.py`:

```python
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
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'
```

Expected: FAIL until JSON and injectable diagnostic runner support are implemented.

- [ ] **Step 3: Finish fix-loop CLI features**

Ensure `tools/supermeta-fix/fix.py` has:

```python
def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture command failures and print next diagnostic actions.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--run-diagnostics", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("child_command", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)
```

In `run_cli`, strip a leading `--` from `child_command`, require at least one command token, run the child up to `max_attempts`, classify non-zero output, write `last.log`, print human-readable or JSON output, and preserve the child exit code.

The JSON payload shape must be:

```json
{
  "schemaVersion": 1,
  "command": ["./scripts/check"],
  "exitCode": 1,
  "logPath": ".codex-bootstrap/fix-loop/last.log",
  "classification": {
    "id": "unit-test",
    "summary": "A unit test failed.",
    "nextActions": ["Read the first failing test and assertion, fix behavior or test expectation, then rerun smart-check."]
  }
}
```

- [ ] **Step 4: Add wrappers**

Create `scripts/agent-fix-loop`:

```sh
#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd "$script_dir/.." && pwd)

exec python3 "$repo_root/tools/supermeta-fix/fix.py" "$@"
```

Create `scripts/agent-fix-loop.ps1`:

```powershell
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-PythonChecked {
    $PythonArgs = @($args)

    $python = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        exit $LASTEXITCODE
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        & $python.Source @PythonArgs
        exit $LASTEXITCODE
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        & $py.Source -3 @PythonArgs
        exit $LASTEXITCODE
    }

    [Console]::Error.WriteLine("scripts/agent-fix-loop.ps1: python3, python, or py is required")
    exit 2
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$fixLoopScript = Join-Path $repoRoot "tools/supermeta-fix/fix.py"
$pythonArgs = @($fixLoopScript)
$pythonArgs += $args
Invoke-PythonChecked @pythonArgs
```

Run:

```bash
chmod +x scripts/agent-fix-loop
```

- [ ] **Step 5: Run Task 4 tests and wrapper smoke**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'
./scripts/agent-fix-loop -- python3 -c "print('ok')"
```

Expected: tests PASS; wrapper exits 0 and writes `.codex-bootstrap/fix-loop/last.log`.

- [ ] **Step 6: Commit Task 4**

```bash
git add scripts/agent-fix-loop scripts/agent-fix-loop.ps1 tools/supermeta-fix
git commit -m "feat: add fix loop CLI"
```

---

### Task 5: Generate Checks Metadata And Velocity Docs

**Files:**
- Modify: `tools/bootstrap/bootstrap.py`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add failing bootstrap generator tests**

Modify `tools/bootstrap/bootstrap_test.py`:

1. Import any new generator helper if needed, such as `generated_velocity_docs_region`.
2. In `test_bootstrap_rewrites_checkout_into_standalone_project`, add:

```python
self.assertTrue((checkout / "scripts" / "agent-smart-check").is_file())
self.assertTrue((checkout / "scripts" / "agent-smart-check.ps1").is_file())
self.assertTrue((checkout / "scripts" / "agent-fix-loop").is_file())
self.assertTrue((checkout / "scripts" / "agent-fix-loop.ps1").is_file())
self.assertTrue((checkout / "tools" / "supermeta-check" / "check.py").is_file())
self.assertTrue((checkout / "tools" / "supermeta-fix" / "fix.py").is_file())
self.assertTrue((checkout / ".codex-bootstrap" / "checks.json").is_file())
checks = json.loads((checkout / ".codex-bootstrap" / "checks.json").read_text(encoding="utf-8"))
self.assertEqual(1, checks["schemaVersion"])
self.assertEqual("java-gradle-cli", checks["templateId"])
self.assertIn("full", [lane["id"] for lane in checks["lanes"]])
self.assertIn("velocity-tools", sync_metadata["managedSets"])
self.assertIn(".codex-bootstrap/checks.json", sync_metadata["managedFiles"])
self.assertIn("README.md:generated-docs/velocity-tools", sync_metadata["managedRegions"])
self.assertIn("AGENTS.md:generated-docs/velocity-tools", sync_metadata["managedRegions"])
self.assertIn("docs/OPERATIONS.md:generated-docs/velocity-tools", sync_metadata["managedRegions"])
self.assertIn("agent-fix-loop", read_text(checkout / "README.md"))
self.assertIn("agent-smart-check", read_text(checkout / "AGENTS.md"))
self.assertIn("checks.local.json", read_text(checkout / "docs" / "OPERATIONS.md"))
```

3. In each manifest load test, add expected support paths and managed file assertions for the new velocity tools.

- [ ] **Step 2: Run bootstrap tests and verify they fail**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: FAIL because generator and manifests do not yet include velocity tooling.

- [ ] **Step 3: Add checks metadata rendering**

Modify `tools/bootstrap/bootstrap.py`:

1. In `write_generated_docs`, call a new `write_checks_policy_file(plan, staged_root)` after `write_nag_policy_files`.
2. Add:

```python
def write_checks_policy_file(plan: BootstrapPlan, staged_root: Path) -> None:
    codex_dir = staged_root / ".codex-bootstrap"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "checks.json").write_text(
        json.dumps(default_checks_policy(plan), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
```

3. Add `default_checks_policy(plan)` with exact lane arrays for each template type. Use these command arrays:

```python
JAVA_CHECK_LANES = [
    {
        "id": "java-test",
        "description": "Java source or tests changed.",
        "triggers": {"paths": ["src/main/java/**/*.java", "src/test/java/**/*.java"]},
        "commands": [["./scripts/agent-gradle", ".", "test"]],
        "escalatesTo": "full",
    },
    {
        "id": "java-style",
        "description": "Java style or Checkstyle config changed.",
        "triggers": {"paths": ["src/main/java/**/*.java", "src/test/java/**/*.java", "config/checkstyle/**/*.xml"]},
        "commands": [["./scripts/agent-gradle", ".", "checkstyleMain", "checkstyleTest"]],
        "escalatesTo": "full",
    },
    {"id": "full", "description": "Complete Java verification.", "commands": [["./scripts/agent-gradle", ".", "check"]]},
]
```

Use equivalent arrays:

- Python: `python-test` runs `["uv", "run", "--no-editable", "pytest"]`; `python-quality` runs `["uv", "run", "ruff", "check", "src", "tests"]` then `["uv", "run", "mypy", "src", "tests"]`; `full` runs `["./scripts/check"]`.
- TypeScript CLI: `typescript-test` runs `["bun", "test"]`; `typescript-quality` runs `["bun", "run", "typecheck"]` then `["bun", "run", "lint"]`; `full` runs `["./scripts/check"]`.
- TypeScript MCP: `typescript-test` runs `["bun", "test"]`; `typescript-quality` runs `["bun", "run", "typecheck"]` then `["bun", "run", "lint"]`; `full` runs `["./scripts/check"]`.
- TypeScript MCP: same as TypeScript CLI with path triggers covering `src/mcp.ts`, `src/http.ts`, `src/stdio.ts`, `src/state.ts`, and `src/config.ts`.
- C#: `dotnet-test` runs `["./scripts/agent-dotnet", ".", "test"]`; `dotnet-quality` runs `["./scripts/check"]`; `full` runs `["./scripts/check"]`.

If a focused command is not present in the template's package scripts, use the template's existing full check for that lane rather than inventing a broken command.

- [ ] **Step 4: Add velocity doc regions**

Modify `tools/bootstrap/bootstrap.py` with:

```python
def generated_velocity_readme_region(check_command_text: str) -> str:
    return f"""<!-- codex-bootstrap:begin generated-docs/velocity-tools -->
## Velocity Tools

Use the fast inner-loop verifier during development:

```bash
./scripts/agent-smart-check --plan-only
./scripts/agent-fix-loop -- ./scripts/agent-smart-check
```

Run the full gate before handoff:

```bash
{check_command_text}
```

Generated lanes live in `.codex-bootstrap/checks.json`. Downstream-only lanes belong in `.codex-bootstrap/checks.local.json`.
<!-- codex-bootstrap:end generated-docs/velocity-tools -->
"""
```

Add matching `generated_velocity_agent_region(check_command_text)` and `generated_velocity_operations_region(check_command_text)` sections. Include these exact AGENTS rules:

```markdown
- Use `./scripts/agent-fix-loop -- ./scripts/agent-smart-check` for fast inner-loop verification.
- Use `<check command>` before handoff; focused lanes are not a release gate.
- Put downstream-only smart-check lanes in `.codex-bootstrap/checks.local.json`.
- Do not let `agent-fix-loop` mutate source or lockfiles in v1.
```

Insert regions into all generated README, AGENTS, and operations renderers near existing coordination/nag sections.

- [ ] **Step 5: Ensure sync metadata hashes checks policy**

Because `.codex-bootstrap/checks.json` will be a managed whole file in manifests after Task 6, `managed_file_hashes` will include it automatically. Do not special-case it.

- [ ] **Step 6: Run bootstrap tests again**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: still FAIL until manifests include support paths and sync contract entries in Task 6.

- [ ] **Step 7: Commit generator work if tests fail only due to manifest expectations**

Run:

```bash
git add tools/bootstrap/bootstrap.py tools/bootstrap/bootstrap_test.py
git commit -m "feat: generate velocity tool contract"
```

Expected: Commit is acceptable with bootstrap tests still failing only for missing manifest/support path wiring that Task 6 immediately addresses. If failures are Python syntax or generator logic failures, fix them before committing.

---

### Task 6: Template Manifests, Sync Contracts, And Pages Metadata

**Files:**
- Modify: `templates/java-gradle-cli/bootstrap-template.json`
- Modify: `templates/python-uv-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-mcp-server/bootstrap-template.json`
- Modify: `templates/csharp-dotnet-cli/bootstrap-template.json`
- Modify: `tools/bootstrap/bootstrap_test.py`
- Modify: `tools/pages/pages_test.py`

- [ ] **Step 1: Add velocity support paths to every template manifest**

In each `templates/*/bootstrap-template.json`, add these support paths after the existing `agent-task` entries:

```json
{
  "source": "scripts/agent-smart-check",
  "destination": "scripts/agent-smart-check"
},
{
  "source": "scripts/agent-smart-check.ps1",
  "destination": "scripts/agent-smart-check.ps1"
},
{
  "source": "scripts/agent-fix-loop",
  "destination": "scripts/agent-fix-loop"
},
{
  "source": "scripts/agent-fix-loop.ps1",
  "destination": "scripts/agent-fix-loop.ps1"
},
{
  "source": "tools/supermeta-check",
  "destination": "tools/supermeta-check"
},
{
  "source": "tools/supermeta-fix",
  "destination": "tools/supermeta-fix"
}
```

Keep ordering consistent across manifests.

- [ ] **Step 2: Add `velocity-tools` managed set to every sync contract**

In each manifest's `syncContract.managedSets`, add:

```json
{
  "id": "velocity-tools",
  "description": "Focused verification and failure-diagnostic helpers for fast agent inner loops.",
  "files": [
    { "path": "scripts/agent-smart-check", "mode": "whole-file" },
    { "path": "scripts/agent-smart-check.ps1", "mode": "whole-file" },
    { "path": "scripts/agent-fix-loop", "mode": "whole-file" },
    { "path": "scripts/agent-fix-loop.ps1", "mode": "whole-file" },
    { "path": "tools/supermeta-check/check.py", "mode": "whole-file" },
    { "path": "tools/supermeta-check/check_test.py", "mode": "whole-file" },
    { "path": "tools/supermeta-check/README.md", "mode": "whole-file" },
    { "path": "tools/supermeta-fix/fix.py", "mode": "whole-file" },
    { "path": "tools/supermeta-fix/fix_test.py", "mode": "whole-file" },
    { "path": "tools/supermeta-fix/README.md", "mode": "whole-file" },
    { "path": ".codex-bootstrap/checks.json", "mode": "whole-file" }
  ],
  "regions": [
    { "path": "README.md", "id": "generated-docs/velocity-tools" },
    { "path": "AGENTS.md", "id": "generated-docs/velocity-tools" },
    { "path": "docs/OPERATIONS.md", "id": "generated-docs/velocity-tools" }
  ]
}
```

Leave `autoEnable` omitted so downstream sync auto-enables this set for current generated projects unless they opt out.

- [ ] **Step 3: Update manifest expectations in bootstrap tests**

In each manifest test in `tools/bootstrap/bootstrap_test.py`, add expected support path names:

```python
"scripts/agent-smart-check",
"scripts/agent-smart-check.ps1",
"scripts/agent-fix-loop",
"scripts/agent-fix-loop.ps1",
"tools/supermeta-check",
"tools/supermeta-fix",
```

Add sync assertions:

```python
self.assertIn("velocity-tools", manifest.sync_contract.managed_sets)
self.assertIn("scripts/agent-smart-check", manifest.sync_contract.managed_files)
self.assertIn("scripts/agent-fix-loop", manifest.sync_contract.managed_files)
self.assertIn("tools/supermeta-check/check.py", manifest.sync_contract.managed_files)
self.assertIn("tools/supermeta-fix/fix.py", manifest.sync_contract.managed_files)
self.assertIn(".codex-bootstrap/checks.json", manifest.sync_contract.managed_files)
self.assertIn("README.md:generated-docs/velocity-tools", manifest.sync_contract.managed_regions)
```

- [ ] **Step 4: Update Pages test**

Modify `tools/pages/pages_test.py`:

```python
self.assertIn("velocity-tools", java_template["managedSets"])
```

- [ ] **Step 5: Run manifest/generator/Page tests**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
python3 -m unittest discover -s tools/pages -p '*_test.py'
```

Expected: PASS. If failures mention unsupported command arrays in generated checks, adjust `default_checks_policy(plan)` to only use commands that exist in template scripts.

- [ ] **Step 6: Commit Task 6**

```bash
git add templates/*/bootstrap-template.json tools/bootstrap/bootstrap_test.py tools/pages/pages_test.py
git commit -m "feat: wire velocity tools into templates"
```

---

### Task 7: Root Docs, Changelog, And Generated Smoke

**Files:**
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `CHANGELOG.md`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add root README section**

In `README.md`, add `agent-smart-check` and `agent-fix-loop` to the shipped tool list near existing `agent-nag` and `agent-task` bullets:

```markdown
- `scripts/agent-smart-check` and `scripts/agent-smart-check.ps1`: focused verification lane selection from changed files.
- `scripts/agent-fix-loop` and `scripts/agent-fix-loop.ps1`: failure capture and deterministic next-action diagnostics around any command.
- `tools/supermeta-check/`: the generated-project smart-check helper copied into generated projects.
- `tools/supermeta-fix/`: the generated-project fix-loop helper copied into generated projects.
```

Add a section after "Agent Nags":

```markdown
## Velocity Tools

Generated projects include focused verification and failure-diagnostic helpers:

```bash
./scripts/agent-smart-check --plan-only
./scripts/agent-fix-loop -- ./scripts/agent-smart-check
```

`agent-smart-check` reads `.codex-bootstrap/checks.json` and optional `.codex-bootstrap/checks.local.json` to pick focused lanes from changed files. Focused lanes are for inner-loop work; run the template full check before handoff.

`agent-fix-loop` captures command output to `.codex-bootstrap/fix-loop/last.log`, classifies common failures, and prints next diagnostic actions without mutating source or lockfiles in v1.
```

- [ ] **Step 2: Add root AGENTS rule**

In `AGENTS.md`, add to Working Rules:

```markdown
- Keep velocity tooling practical and conservative: `agent-smart-check` accelerates inner loops, `agent-fix-loop` captures and classifies failures, and full template checks remain the handoff gate.
```

In Verification, add:

```markdown
- Velocity helper tests: `python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'` and `python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'`
```

- [ ] **Step 3: Update changelog**

In `CHANGELOG.md` under `## Unreleased`, add:

```markdown
### Generated Contract

- Added the velocity tooling contract for generated projects: `scripts/agent-smart-check`, `scripts/agent-fix-loop`, PowerShell wrappers, `tools/supermeta-check/`, `tools/supermeta-fix/`, generated `.codex-bootstrap/checks.json`, and the `velocity-tools` sync managed set.

### Tooling

- Added focused verification lane selection and deterministic failure classification helpers for faster agent inner loops while keeping full checks as the handoff gate.

### Verification

- `python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'`
- `python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'`
```

If existing `Generated Contract` and `Verification` sections are already present, append bullets there rather than duplicating section headings.

- [ ] **Step 4: Add generated-project smoke for smart-check**

In `tools/bootstrap/bootstrap_test.py`, inside `test_bootstrap_rewrites_checkout_into_standalone_project`, after generated files are asserted, add:

```python
smart_check = run_checked(
    ["./scripts/agent-smart-check", "--changed", "src/main/java/com/acme/sample/App.java", "--plan-only", "--json"],
    cwd=checkout,
)
smart_payload = json.loads(smart_check.stdout)
self.assertFalse(smart_payload["executed"])
self.assertIn("full", [item["id"] for item in smart_payload["plan"]])
fix_loop = run_checked(
    ["./scripts/agent-fix-loop", "--", "./scripts/agent-smart-check", "--changed", "src/main/java/com/acme/sample/App.java", "--plan-only"],
    cwd=checkout,
)
self.assertIn("agent-smart-check", fix_loop.stdout)
```

- [ ] **Step 5: Run docs and smoke tests**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
python3 -m unittest discover -s tools/pages -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 6: Commit Task 7**

```bash
git add README.md AGENTS.md CHANGELOG.md tools/bootstrap/bootstrap_test.py
git commit -m "docs: document velocity tooling"
```

---

### Task 8: Full Verification And Final Hardening

**Files:**
- Modify only files touched in Tasks 1-7, and only when a verification command in this task names a concrete failure.

- [ ] **Step 1: Run focused helper suites**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'
python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 2: Run bootstrap and Pages suites**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
python3 -m unittest discover -s tools/pages -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 3: Run all helper tests**

Run:

```bash
python3 -m unittest discover -s tools -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 4: Run Java template check**

Run:

```bash
./scripts/agent-gradle templates/java-gradle-cli check
```

Expected: PASS.

- [ ] **Step 5: Run root velocity smoke**

Run:

```bash
./scripts/agent-smart-check --changed tools/supermeta-check/check.py --plan-only --json
./scripts/agent-fix-loop -- ./scripts/agent-smart-check --changed tools/supermeta-check/check.py --plan-only
```

Expected: Both commands exit 0. The first prints JSON. The second prints smart-check output and writes `.codex-bootstrap/fix-loop/last.log`.

- [ ] **Step 6: Inspect generated contract diff**

Run:

```bash
git diff --stat
git diff --check
```

Expected: Diff contains only velocity-tool implementation, generated contract wiring, docs, and tests. `git diff --check` prints nothing.

- [ ] **Step 7: Commit final fixes if any**

If Step 1-6 required edits, commit them:

```bash
git add .
git commit -m "fix: harden velocity toolkit contract"
```

If no edits were required, do not create an empty commit.

---

## Spec Coverage Self-Review

- V1 scope is covered by Tasks 1-7: smart-check, fix-loop, wrappers, generated policy, docs, manifests, sync set, Pages metadata, and smoke tests.
- Non-goals are enforced by Task 3 and Task 4 tests: fix-loop captures output and diagnostics without source mutation; full checks remain the documented handoff gate.
- `.codex-bootstrap/checks.json` and local override behavior are covered by Task 1 and Task 5.
- Starter defaults are implemented in Task 5 and verified through generated smoke in Task 7.
- Error handling and JSON output are covered by Task 2 and Task 4.
- Rollout verification is covered by Task 8.

No implementation task should touch template product behavior under `templates/*/src`.
