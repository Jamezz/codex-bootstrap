# Agent Nag System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generated-project advisory nag system with reusable lifecycle hooks, bootstrap update checks, post-run reminders, local overrides, and wrapper integration.

**Architecture:** Add a stdlib-only Python nag engine under `tools/supermeta-nag` with managed default policy, local overrides, local state, cadence, snooze, acknowledgement, and bootstrap update actions. Expose it through Unix and PowerShell wrappers, integrate the first hook producer into `agent-coord run`, delegate `agent-bootstrap check-updates` to the nag engine, and update the bootstrap generator plus template manifests so every generated starter inherits the same contract.

**Tech Stack:** Python 3 standard library, `unittest`, shell wrappers, PowerShell wrappers, JSON policy files, existing template manifests, existing bootstrap smoke tests, existing Pages metadata tests.

---

## File Structure

- Create `tools/supermeta-nag/__init__.py`: package marker for the copied generated-project nag helper.
- Create `tools/supermeta-nag/nag.py`: nag CLI, policy parser, local override merger, hook evaluator, cadence/state manager, bootstrap update checker, and command rendering.
- Create `tools/supermeta-nag/nag_test.py`: unit tests for policy loading, local overrides, state, cadence, hook matching, CLI commands, and update checks.
- Create `tools/supermeta-nag/README.md`: generated-project operator docs for `agent-nag`.
- Create `scripts/agent-nag`: Unix wrapper that invokes `tools/supermeta-nag/nag.py`.
- Create `scripts/agent-nag.ps1`: PowerShell wrapper that locates Python and invokes `tools/supermeta-nag/nag.py`.
- Modify `scripts/agent-bootstrap`: delegate `check-updates` to `scripts/agent-nag` when present.
- Modify `scripts/agent-bootstrap.ps1`: delegate `check-updates` to `scripts/agent-nag.ps1` when present.
- Modify `tools/supermeta-agent/agent.py`: call nag hooks around `agent-coord run` while preserving child exit codes.
- Modify `tools/supermeta-agent/agent_test.py`: assert hook calls and exit-code preservation.
- Modify `tools/bootstrap/bootstrap.py`: copy nag support paths, emit `.codex-bootstrap/nags.json` and `.codex-bootstrap/nags.local.json`, generate managed nag docs regions, and include nag files in sync metadata hashing.
- Modify `tools/bootstrap/bootstrap_test.py`: assert generated nag files, docs, manifests, sync contracts, and generated-project wrapper behavior.
- Modify every `templates/*/bootstrap-template.json`: add nag wrappers and `tools/supermeta-nag` support paths; add the `agent-nags` managed set.
- Modify generated template docs only through `tools/bootstrap/bootstrap.py` unless a template-local source doc also needs pre-bootstrap wording.
- Modify `tools/pages/pages_test.py`: assert Pages metadata exposes `agent-nags` through existing managed-set summaries.
- Modify `README.md`: document the generated-project nag surface at the catalog level.
- Modify `CHANGELOG.md`: add an unreleased entry for the agent nag contract.

## Task 1: Nag Policy And State Tests

**Files:**
- Create: `tools/supermeta-nag/__init__.py`
- Create: `tools/supermeta-nag/nag_test.py`

- [ ] **Step 1: Add package marker and failing policy/state tests**

Create `tools/supermeta-nag/__init__.py`:

```python
"""Codex Bootstrap generated-project nag helpers."""
```

Create `tools/supermeta-nag/nag_test.py`:

```python
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import nag


FIXED_NOW = datetime(2026, 5, 23, 20, 0, tzinfo=timezone.utc)


class PolicyLoadingTest(unittest.TestCase):
    def test_loads_managed_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-policy-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "nags.json",
                {
                    "schemaVersion": 1,
                    "nags": [
                        {
                            "id": "post-run-backlog-check",
                            "enabled": True,
                            "hook": "post-run",
                            "cadence": "per-run",
                            "action": "suggest-command",
                            "message": "Refresh task context before handoff.",
                            "commands": [["./scripts/agent-beads", "ready", "--json"]],
                        }
                    ],
                },
            )

            policy, warnings = nag.load_effective_policy(root)

            self.assertEqual((), warnings)
            self.assertEqual(1, policy.schema_version)
            self.assertEqual(("post-run-backlog-check",), tuple(policy.nags))
            self.assertEqual("post-run", policy.nags["post-run-backlog-check"].hook)
            self.assertEqual(
                (("./scripts/agent-beads", "ready", "--json"),),
                policy.nags["post-run-backlog-check"].commands,
            )

    def test_merges_local_override_by_id(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-local-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)
            write_json(
                root / ".codex-bootstrap" / "nags.local.json",
                {
                    "schemaVersion": 1,
                    "nags": [
                        {
                            "id": "post-run-backlog-check",
                            "enabled": False,
                            "message": "Local override message.",
                        },
                        {
                            "id": "local-beads-check",
                            "enabled": True,
                            "hook": "pre-handoff",
                            "cadence": "once",
                            "action": "suggest-command",
                            "message": "Run local beads before handoff.",
                            "commands": [["beads", "check"]],
                        },
                    ],
                },
            )

            policy, warnings = nag.load_effective_policy(root)

            self.assertEqual((), warnings)
            self.assertFalse(policy.nags["post-run-backlog-check"].enabled)
            self.assertEqual("post-run", policy.nags["post-run-backlog-check"].hook)
            self.assertEqual("Local override message.", policy.nags["post-run-backlog-check"].message)
            self.assertEqual(("local-beads-check", "post-run-backlog-check"), tuple(sorted(policy.nags)))

    def test_invalid_local_policy_warns_and_uses_managed_policy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-invalid-local-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)
            local_path = root / ".codex-bootstrap" / "nags.local.json"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            local_path.write_text("{not json", encoding="utf-8")

            policy, warnings = nag.load_effective_policy(root)

            self.assertIn("ignored invalid local nag policy", warnings[0])
            self.assertEqual(("post-run-backlog-check",), tuple(policy.nags))

    def test_invalid_managed_policy_raises(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-invalid-managed-") as temp_dir:
            root = Path(temp_dir)
            write_json(root / ".codex-bootstrap" / "nags.json", {"schemaVersion": 1, "nags": "bad"})

            with self.assertRaisesRegex(nag.NagError, "nags must be an array"):
                nag.load_effective_policy(root)


class StateAndCadenceTest(unittest.TestCase):
    def test_per_run_cadence_always_shows(self) -> None:
        definition = nag.NagDefinition(
            nag_id="post-run-backlog-check",
            enabled=True,
            hook="post-run",
            cadence="per-run",
            action="message",
            message="Refresh context.",
            commands=(),
            when={},
        )
        state = nag.NagState(schema_version=1, nags={})

        self.assertTrue(nag.should_show(definition, state, FIXED_NOW))
        self.assertTrue(nag.should_show(definition, state, FIXED_NOW + timedelta(minutes=1)))

    def test_duration_cadence_suppresses_until_interval_passes(self) -> None:
        definition = nag.NagDefinition(
            nag_id="bootstrap-update-check",
            enabled=True,
            hook="session-start",
            cadence="24h",
            action="message",
            message="Update available.",
            commands=(),
            when={},
        )
        state = nag.NagState(
            schema_version=1,
            nags={
                "bootstrap-update-check": nag.NagRuntimeState(
                    last_shown_at=FIXED_NOW,
                    last_checked_at=None,
                    last_seen_value=None,
                    snoozed_until=None,
                    acknowledged=False,
                )
            },
        )

        self.assertFalse(nag.should_show(definition, state, FIXED_NOW + timedelta(hours=23)))
        self.assertTrue(nag.should_show(definition, state, FIXED_NOW + timedelta(hours=25)))

    def test_snoozed_nag_stays_quiet_until_expiry(self) -> None:
        definition = nag.NagDefinition(
            nag_id="post-run-backlog-check",
            enabled=True,
            hook="post-run",
            cadence="per-run",
            action="message",
            message="Refresh context.",
            commands=(),
            when={},
        )
        state = nag.NagState(
            schema_version=1,
            nags={
                "post-run-backlog-check": nag.NagRuntimeState(
                    last_shown_at=None,
                    last_checked_at=None,
                    last_seen_value=None,
                    snoozed_until=FIXED_NOW + timedelta(days=7),
                    acknowledged=False,
                )
            },
        )

        self.assertFalse(nag.should_show(definition, state, FIXED_NOW + timedelta(days=1)))
        self.assertTrue(nag.should_show(definition, state, FIXED_NOW + timedelta(days=8)))

    def test_corrupt_state_moves_aside(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-corrupt-state-") as temp_dir:
            root = Path(temp_dir)
            state_path = root / ".codex-bootstrap" / "nag-state.json"
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text("{bad json", encoding="utf-8")
            stderr = StringIO()

            with redirect_stderr(stderr):
                state = nag.load_state(root)

            self.assertEqual({}, state.nags)
            self.assertIn("agent-nag: moved corrupt nag state", stderr.getvalue())
            self.assertTrue(any(path.name.startswith("nag-state.json.corrupt") for path in state_path.parent.iterdir()))


def write_default_policy(root: Path) -> None:
    write_json(
        root / ".codex-bootstrap" / "nags.json",
        {
            "schemaVersion": 1,
            "nags": [
                {
                    "id": "post-run-backlog-check",
                    "enabled": True,
                    "hook": "post-run",
                    "cadence": "per-run",
                    "action": "suggest-command",
                    "message": "Refresh task context before handoff.",
                    "commands": [["./scripts/agent-beads", "ready", "--json"]],
                }
            ],
        },
    )


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

- [ ] **Step 2: Run tests and verify the expected import failure**

Run:

```bash
PYTHONPATH=tools/supermeta-nag python3 -m unittest discover -s tools/supermeta-nag -p '*_test.py'
```

Expected: FAIL with `ModuleNotFoundError: No module named 'nag'`.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tools/supermeta-nag/__init__.py tools/supermeta-nag/nag_test.py
git commit -m "test: cover agent nag policy model"
```

## Task 2: Nag Policy And State Implementation

**Files:**
- Create: `tools/supermeta-nag/nag.py`
- Test: `tools/supermeta-nag/nag_test.py`

- [ ] **Step 1: Implement policy dataclasses and JSON parsing**

Create `tools/supermeta-nag/nag.py`:

```python
#!/usr/bin/env python3
"""Advisory nag hooks for Codex Bootstrap generated projects."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
NAGS_POLICY = Path(".codex-bootstrap/nags.json")
LOCAL_POLICY = Path(".codex-bootstrap/nags.local.json")
NAG_STATE = Path(".codex-bootstrap/nag-state.json")
SYNC_METADATA = Path(".codex-bootstrap/sync.json")
DEFAULT_TIMEOUT_SECONDS = 30


class NagError(Exception):
    """Raised for user-facing nag failures."""


@dataclass(frozen=True)
class NagDefinition:
    nag_id: str
    enabled: bool
    hook: str
    cadence: str
    action: str
    message: str
    commands: tuple[tuple[str, ...], ...]
    when: dict[str, Any]


@dataclass(frozen=True)
class NagPolicy:
    schema_version: int
    nags: dict[str, NagDefinition]


@dataclass(frozen=True)
class NagRuntimeState:
    last_shown_at: datetime | None
    last_checked_at: datetime | None
    last_seen_value: str | None
    snoozed_until: datetime | None
    acknowledged: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "lastShownAt": format_time(self.last_shown_at),
            "lastCheckedAt": format_time(self.last_checked_at),
            "lastSeenValue": self.last_seen_value,
            "snoozedUntil": format_time(self.snoozed_until),
            "acknowledged": self.acknowledged,
        }


@dataclass(frozen=True)
class NagState:
    schema_version: int
    nags: dict[str, NagRuntimeState]

    def to_json(self) -> dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "nags": {
                nag_id: state.to_json()
                for nag_id, state in sorted(self.nags.items())
            },
        }


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def format_time(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(normalized)


def load_effective_policy(root: Path) -> tuple[NagPolicy, tuple[str, ...]]:
    managed = parse_policy(load_json(root / NAGS_POLICY), managed=True)
    warnings: list[str] = []
    local_path = root / LOCAL_POLICY
    if not local_path.is_file():
        return managed, ()
    try:
        local = parse_policy(load_json(local_path), managed=False)
    except (NagError, OSError, json.JSONDecodeError) as error:
        warnings.append(f"ignored invalid local nag policy {LOCAL_POLICY}: {error}")
        return managed, tuple(warnings)
    return merge_policy(managed, local), tuple(warnings)


def parse_policy(raw: dict[str, Any], managed: bool) -> NagPolicy:
    schema_version = require_int(raw, "schemaVersion")
    if schema_version != SCHEMA_VERSION:
        raise NagError(f"unsupported nag policy schema {schema_version}")
    raw_nags = raw.get("nags")
    if not isinstance(raw_nags, list):
        raise NagError("nags must be an array")
    nags: dict[str, NagDefinition] = {}
    for index, item in enumerate(raw_nags):
        if not isinstance(item, dict):
            raise NagError(f"nags[{index}] must be an object")
        nag_id = require_string(item, "id")
        existing = nags.get(nag_id)
        if existing is not None:
            raise NagError(f"duplicate nag id: {nag_id}")
        if managed:
            nags[nag_id] = NagDefinition(
                nag_id=nag_id,
                enabled=require_bool(item, "enabled"),
                hook=require_string(item, "hook"),
                cadence=require_string(item, "cadence"),
                action=require_string(item, "action"),
                message=require_string(item, "message"),
                commands=parse_commands(item.get("commands", [])),
                when=parse_when(item.get("when", {})),
            )
        else:
            nags[nag_id] = NagDefinition(
                nag_id=nag_id,
                enabled=optional_bool(item, "enabled", True),
                hook=optional_string(item, "hook", ""),
                cadence=optional_string(item, "cadence", ""),
                action=optional_string(item, "action", ""),
                message=optional_string(item, "message", ""),
                commands=parse_commands(item.get("commands", [])),
                when=parse_when(item.get("when", {})),
            )
    return NagPolicy(schema_version=schema_version, nags=nags)


def merge_policy(managed: NagPolicy, local: NagPolicy) -> NagPolicy:
    result = dict(managed.nags)
    for nag_id, override in local.nags.items():
        base = result.get(nag_id)
        if base is None:
            result[nag_id] = override
            continue
        result[nag_id] = NagDefinition(
            nag_id=nag_id,
            enabled=override.enabled,
            hook=override.hook or base.hook,
            cadence=override.cadence or base.cadence,
            action=override.action or base.action,
            message=override.message or base.message,
            commands=override.commands or base.commands,
            when=override.when or base.when,
        )
    return NagPolicy(schema_version=managed.schema_version, nags=result)


def load_state(root: Path) -> NagState:
    path = root / NAG_STATE
    if not path.is_file():
        return NagState(schema_version=SCHEMA_VERSION, nags={})
    try:
        raw = load_json(path)
        if require_int(raw, "schemaVersion") != SCHEMA_VERSION:
            raise NagError("unsupported nag state schema")
        raw_nags = raw.get("nags")
        if not isinstance(raw_nags, dict):
            raise NagError("state nags must be an object")
        return NagState(
            schema_version=SCHEMA_VERSION,
            nags={
                nag_id: NagRuntimeState(
                    last_shown_at=parse_time(optional_nullable_string(value, "lastShownAt")),
                    last_checked_at=parse_time(optional_nullable_string(value, "lastCheckedAt")),
                    last_seen_value=optional_nullable_string(value, "lastSeenValue"),
                    snoozed_until=parse_time(optional_nullable_string(value, "snoozedUntil")),
                    acknowledged=optional_bool(value, "acknowledged", False),
                )
                for nag_id, value in raw_nags.items()
                if isinstance(nag_id, str) and isinstance(value, dict)
            },
        )
    except (NagError, OSError, json.JSONDecodeError):
        corrupt = path.with_name(f"{path.name}.corrupt-{int(utc_now().timestamp())}")
        shutil.move(str(path), corrupt)
        print(f"agent-nag: moved corrupt nag state to {corrupt}", file=sys.stderr)
        return NagState(schema_version=SCHEMA_VERSION, nags={})


def should_show(definition: NagDefinition, state: NagState, now: datetime) -> bool:
    if not definition.enabled:
        return False
    runtime = state.nags.get(definition.nag_id)
    if runtime is None:
        return True
    if runtime.snoozed_until is not None and runtime.snoozed_until > now:
        return False
    if definition.cadence == "per-run":
        return True
    if definition.cadence == "once":
        return not runtime.acknowledged
    duration = parse_duration(definition.cadence)
    if runtime.last_shown_at is None:
        return True
    return runtime.last_shown_at + duration <= now


def parse_duration(value: str) -> timedelta:
    if value.endswith("h"):
        return timedelta(hours=int(value[:-1]))
    if value.endswith("d"):
        return timedelta(days=int(value[:-1]))
    if value.endswith("m"):
        return timedelta(minutes=int(value[:-1]))
    if value.endswith("s"):
        return timedelta(seconds=int(value[:-1]))
    raise NagError(f"invalid duration: {value}")
```

- [ ] **Step 2: Add parsing helpers to `nag.py`**

Append these helper functions:

```python
def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def require_string(raw: dict[str, Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise NagError(f"{key} must be a non-empty string")
    return value


def optional_string(raw: dict[str, Any], key: str, default: str) -> str:
    value = raw.get(key, default)
    if not isinstance(value, str):
        raise NagError(f"{key} must be a string")
    return value


def optional_nullable_string(raw: dict[str, Any], key: str) -> str | None:
    value = raw.get(key)
    if value is None or isinstance(value, str):
        return value
    raise NagError(f"{key} must be a string or null")


def require_bool(raw: dict[str, Any], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise NagError(f"{key} must be a boolean")
    return value


def optional_bool(raw: dict[str, Any], key: str, default: bool) -> bool:
    value = raw.get(key, default)
    if not isinstance(value, bool):
        raise NagError(f"{key} must be a boolean")
    return value


def require_int(raw: dict[str, Any], key: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int):
        raise NagError(f"{key} must be an integer")
    return value


def parse_commands(value: object) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list):
        raise NagError("commands must be an array")
    commands: list[tuple[str, ...]] = []
    for index, item in enumerate(value):
        if not isinstance(item, list) or not all(isinstance(part, str) and part for part in item):
            raise NagError(f"commands[{index}] must be a non-empty string array")
        commands.append(tuple(item))
    return tuple(commands)


def parse_when(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NagError("when must be an object")
    allowed = {"exitCode", "wrapper", "command"}
    for key in value:
        if key not in allowed:
            raise NagError(f"unsupported when key: {key}")
    return dict(value)
```

- [ ] **Step 3: Run model tests and verify they pass**

Run:

```bash
PYTHONPATH=tools/supermeta-nag python3 -m unittest discover -s tools/supermeta-nag -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 4: Commit the policy/state implementation**

```bash
git add tools/supermeta-nag/nag.py tools/supermeta-nag/nag_test.py
git commit -m "feat: add agent nag policy model"
```

## Task 3: Hook Evaluation, CLI, And Update Check

**Files:**
- Modify: `tools/supermeta-nag/nag_test.py`
- Modify: `tools/supermeta-nag/nag.py`

- [ ] **Step 1: Add failing hook, CLI, and update-check tests**

Append these tests to `tools/supermeta-nag/nag_test.py`:

```python
class HookEvaluationTest(unittest.TestCase):
    def test_run_hook_prints_suggested_command_and_records_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-hook-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)
            output = StringIO()

            exit_code = nag.run_cli(
                ["--project-root", str(root), "run-hook", "post-run", "--wrapper", "agent-coord", "--exit-code", "0"],
                stdout=output,
                now=FIXED_NOW,
            )

            self.assertEqual(0, exit_code)
            self.assertIn("agent-nag: post-run-backlog-check", output.getvalue())
            self.assertIn("./scripts/agent-beads ready --json", output.getvalue())
            state = json.loads((root / ".codex-bootstrap" / "nag-state.json").read_text(encoding="utf-8"))
            self.assertEqual("2026-05-23T20:00:00Z", state["nags"]["post-run-backlog-check"]["lastShownAt"])

    def test_run_hook_respects_exit_code_condition(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-hook-condition-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)
            output = StringIO()

            exit_code = nag.run_cli(
                ["--project-root", str(root), "run-hook", "post-run", "--wrapper", "agent-coord", "--exit-code", "1"],
                stdout=output,
                now=FIXED_NOW,
            )

            self.assertEqual(0, exit_code)
            self.assertEqual("", output.getvalue())
            self.assertFalse((root / ".codex-bootstrap" / "nag-state.json").exists())

    def test_ack_suppresses_once_nag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-ack-") as temp_dir:
            root = Path(temp_dir)
            write_json(
                root / ".codex-bootstrap" / "nags.json",
                {
                    "schemaVersion": 1,
                    "nags": [
                        {
                            "id": "handoff-once",
                            "enabled": True,
                            "hook": "pre-handoff",
                            "cadence": "once",
                            "action": "message",
                            "message": "Check handoff state.",
                        }
                    ],
                },
            )

            self.assertEqual(0, nag.run_cli(["--project-root", str(root), "ack", "handoff-once"], now=FIXED_NOW))
            output = StringIO()
            self.assertEqual(
                0,
                nag.run_cli(["--project-root", str(root), "run-hook", "pre-handoff"], stdout=output, now=FIXED_NOW),
            )
            self.assertEqual("", output.getvalue())

    def test_snooze_suppresses_matching_nag(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-snooze-") as temp_dir:
            root = Path(temp_dir)
            write_default_policy(root)

            self.assertEqual(
                0,
                nag.run_cli(["--project-root", str(root), "snooze", "post-run-backlog-check", "--for", "7d"], now=FIXED_NOW),
            )
            output = StringIO()
            self.assertEqual(
                0,
                nag.run_cli(
                    ["--project-root", str(root), "run-hook", "post-run", "--exit-code", "0"],
                    stdout=output,
                    now=FIXED_NOW + timedelta(days=1),
                ),
            )
            self.assertEqual("", output.getvalue())

    def test_check_updates_prints_when_upstream_moved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-update-") as temp_dir:
            root = Path(temp_dir)
            write_update_policy(root)
            write_sync_metadata(root, commit="0" * 40)
            output = StringIO()

            def fake_run(command: list[str], cwd: Path | None = None) -> nag.CommandResult:
                self.assertEqual(["git", "ls-remote", "https://example.test/bootstrap.git", "main"], command)
                return nag.CommandResult(0, "1111111111111111111111111111111111111111\trefs/heads/main\n")

            exit_code = nag.run_cli(
                ["--project-root", str(root), "check-updates", "--quiet"],
                stdout=output,
                now=FIXED_NOW,
                command_runner=fake_run,
            )

            self.assertEqual(0, exit_code)
            self.assertIn("A newer Codex Bootstrap version is available.", output.getvalue())
            self.assertIn("./scripts/agent-bootstrap sync --dry-run", output.getvalue())

    def test_check_updates_quiet_noops_when_commits_match(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-update-same-") as temp_dir:
            root = Path(temp_dir)
            write_update_policy(root)
            write_sync_metadata(root, commit="1" * 40)
            output = StringIO()

            def fake_run(command: list[str], cwd: Path | None = None) -> nag.CommandResult:
                return nag.CommandResult(0, "1111111111111111111111111111111111111111\trefs/heads/main\n")

            exit_code = nag.run_cli(
                ["--project-root", str(root), "check-updates", "--quiet"],
                stdout=output,
                now=FIXED_NOW,
                command_runner=fake_run,
            )

            self.assertEqual(0, exit_code)
            self.assertEqual("", output.getvalue())

    def test_verbose_update_check_reports_git_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-nag-update-failure-") as temp_dir:
            root = Path(temp_dir)
            write_update_policy(root)
            write_sync_metadata(root, commit="1" * 40)
            stderr = StringIO()

            def fake_run(command: list[str], cwd: Path | None = None) -> nag.CommandResult:
                return nag.CommandResult(128, "network unavailable\n")

            with redirect_stderr(stderr):
                exit_code = nag.run_cli(
                    ["--project-root", str(root), "check-updates", "--verbose"],
                    now=FIXED_NOW,
                    command_runner=fake_run,
                )

            self.assertEqual(1, exit_code)
            self.assertIn("agent-nag: update check failed", stderr.getvalue())


def write_update_policy(root: Path) -> None:
    write_json(
        root / ".codex-bootstrap" / "nags.json",
        {
            "schemaVersion": 1,
            "nags": [
                {
                    "id": "bootstrap-update-check",
                    "enabled": True,
                    "hook": "session-start",
                    "cadence": "24h",
                    "action": "check-bootstrap-update",
                    "message": "A newer Codex Bootstrap version is available.",
                }
            ],
        },
    )


def write_sync_metadata(root: Path, commit: str) -> None:
    write_json(
        root / ".codex-bootstrap" / "sync.json",
        {
            "schemaVersion": 1,
            "source": {
                "repository": "https://example.test/bootstrap.git",
                "ref": "main",
                "commit": commit,
            },
            "template": {"id": "python-uv-cli", "contractVersion": 1},
            "identity": {"projectName": "sample-app"},
            "managedSets": [],
            "optOut": [],
            "managedFiles": {},
            "managedRegions": {},
            "verificationCommands": [],
        },
    )
```

- [ ] **Step 2: Run tests and verify CLI failures**

Run:

```bash
PYTHONPATH=tools/supermeta-nag python3 -m unittest discover -s tools/supermeta-nag -p '*_test.py'
```

Expected: FAIL with missing `run_cli` or `CommandResult`.

- [ ] **Step 3: Implement hook evaluation, state writes, and CLI commands**

Append these functions and dataclass to `tools/supermeta-nag/nag.py`:

```python
@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str


def run_cli(
    argv: list[str],
    stdout=None,
    now: datetime | None = None,
    command_runner=None,
) -> int:
    args = parse_args(argv)
    output = stdout or sys.stdout
    current_time = now or utc_now()
    runner = command_runner or run_unchecked
    root = args.project_root.resolve()
    try:
        if args.command == "run-hook":
            return run_hook_command(root, args, output, current_time, runner)
        if args.command == "check-updates":
            return check_updates_command(root, args.quiet, args.verbose, output, current_time, runner)
        if args.command == "ack":
            state = set_acknowledged(load_state(root), args.nag_id, True)
            write_state(root, state)
            return 0
        if args.command == "snooze":
            state = set_snooze(load_state(root), args.nag_id, current_time + parse_duration(args.duration))
            write_state(root, state)
            return 0
        if args.command == "reset":
            state = clear_runtime_state(load_state(root), args.nag_id)
            write_state(root, state)
            return 0
        if args.command == "list":
            policy, warnings = load_effective_policy(root)
            print_warnings(warnings)
            for nag_id in sorted(policy.nags):
                output.write(f"{nag_id}\n")
            return 0
        if args.command == "status":
            policy, warnings = load_effective_policy(root)
            print_warnings(warnings)
            state = load_state(root)
            output.write(json.dumps(status_payload(policy, state), indent=2, sort_keys=True) + "\n")
            return 0
    except NagError as error:
        print(f"agent-nag: {error}", file=sys.stderr)
        return 2
    return 2


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Codex Bootstrap agent nags.")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)

    hook = subparsers.add_parser("run-hook")
    hook.add_argument("hook")
    hook.add_argument("--wrapper", default="")
    hook.add_argument("--command", default="")
    hook.add_argument("--exit-code", type=int)

    updates = subparsers.add_parser("check-updates")
    updates.add_argument("--quiet", action="store_true")
    updates.add_argument("--verbose", action="store_true")

    subparsers.add_parser("list")
    subparsers.add_parser("status")

    ack = subparsers.add_parser("ack")
    ack.add_argument("nag_id")

    snooze = subparsers.add_parser("snooze")
    snooze.add_argument("nag_id")
    snooze.add_argument("--for", dest="duration", required=True)

    reset = subparsers.add_parser("reset")
    reset.add_argument("nag_id")

    return parser.parse_args(argv)


def run_hook_command(root: Path, args: argparse.Namespace, output, now: datetime, command_runner) -> int:
    policy, warnings = load_effective_policy(root)
    print_warnings(warnings)
    state = load_state(root)
    context = hook_context(root, args)
    changed = False
    for definition in sorted(policy.nags.values(), key=lambda item: item.nag_id):
        if definition.hook != args.hook or not matches_when(definition, context):
            continue
        if definition.action == "check-bootstrap-update":
            shown, state = evaluate_bootstrap_update(root, definition, state, now, output, command_runner, quiet=True, verbose=False)
            changed = changed or shown
            continue
        if should_show(definition, state, now):
            print_nag(definition, output)
            state = mark_shown(state, definition.nag_id, now)
            changed = True
    if changed:
        write_state(root, state)
    return 0


def matches_when(definition: NagDefinition, context: dict[str, Any]) -> bool:
    for key, expected in definition.when.items():
        if context.get(key) != expected:
            return False
    return True


def hook_context(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    context: dict[str, Any] = {
        "wrapper": getattr(args, "wrapper", ""),
        "command": getattr(args, "command", ""),
    }
    exit_code = getattr(args, "exit_code", None)
    if exit_code is not None:
        context["exitCode"] = exit_code
    sync = read_sync_metadata(root)
    context.update(sync)
    return context


def print_nag(definition: NagDefinition, output) -> None:
    output.write(f"agent-nag: {definition.nag_id}\n")
    output.write(f"  {definition.message}\n")
    if definition.commands:
        output.write("  Suggested:\n")
        for command in definition.commands:
            output.write(f"    {' '.join(command)}\n")


def mark_shown(state: NagState, nag_id: str, now: datetime) -> NagState:
    current = state.nags.get(nag_id, empty_runtime_state())
    updated = dataclasses.replace(current, last_shown_at=now)
    return replace_runtime_state(state, nag_id, updated)


def set_acknowledged(state: NagState, nag_id: str, acknowledged: bool) -> NagState:
    current = state.nags.get(nag_id, empty_runtime_state())
    return replace_runtime_state(state, nag_id, dataclasses.replace(current, acknowledged=acknowledged))


def set_snooze(state: NagState, nag_id: str, snoozed_until: datetime) -> NagState:
    current = state.nags.get(nag_id, empty_runtime_state())
    return replace_runtime_state(state, nag_id, dataclasses.replace(current, snoozed_until=snoozed_until))


def clear_runtime_state(state: NagState, nag_id: str) -> NagState:
    nags = dict(state.nags)
    nags.pop(nag_id, None)
    return NagState(schema_version=state.schema_version, nags=nags)


def replace_runtime_state(state: NagState, nag_id: str, runtime: NagRuntimeState) -> NagState:
    nags = dict(state.nags)
    nags[nag_id] = runtime
    return NagState(schema_version=state.schema_version, nags=nags)


def empty_runtime_state() -> NagRuntimeState:
    return NagRuntimeState(
        last_shown_at=None,
        last_checked_at=None,
        last_seen_value=None,
        snoozed_until=None,
        acknowledged=False,
    )


def write_state(root: Path, state: NagState) -> None:
    destination = root / NAG_STATE
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=destination.parent, delete=False) as temp_file:
        json.dump(state.to_json(), temp_file, indent=2, sort_keys=True)
        temp_file.write("\n")
        temp_file.flush()
        os.fsync(temp_file.fileno())
        temp_name = temp_file.name
    os.replace(temp_name, destination)
```

- [ ] **Step 4: Implement bootstrap update action**

Append these functions to `tools/supermeta-nag/nag.py`:

```python
def check_updates_command(root: Path, quiet: bool, verbose: bool, output, now: datetime, command_runner) -> int:
    policy, warnings = load_effective_policy(root)
    print_warnings(warnings)
    state = load_state(root)
    definition = policy.nags.get("bootstrap-update-check")
    if definition is None:
        definition = NagDefinition(
            nag_id="bootstrap-update-check",
            enabled=True,
            hook="session-start",
            cadence="per-run",
            action="check-bootstrap-update",
            message="A newer Codex Bootstrap version is available.",
            commands=(),
            when={},
        )
    try:
        shown, state = evaluate_bootstrap_update(root, definition, state, now, output, command_runner, quiet=quiet, verbose=verbose)
        write_state(root, state)
        return 0 if shown or quiet else 0
    except NagError as error:
        if verbose:
            print(f"agent-nag: update check failed: {error}", file=sys.stderr)
            return 1
        state = mark_checked(state, definition.nag_id, now, f"error:{error}")
        write_state(root, state)
        return 0


def evaluate_bootstrap_update(
    root: Path,
    definition: NagDefinition,
    state: NagState,
    now: datetime,
    output,
    command_runner,
    quiet: bool,
    verbose: bool,
) -> tuple[bool, NagState]:
    if not should_show(definition, state, now):
        return False, state
    sync = read_required_sync_metadata(root)
    result = command_runner(["git", "ls-remote", sync["sourceRepository"], sync["sourceRef"]], cwd=root)
    if result.returncode != 0:
        raise NagError(result.stdout.strip() or "git ls-remote failed")
    latest = parse_ls_remote_commit(result.stdout)
    current = sync["sourceCommit"]
    checked_state = mark_checked(state, definition.nag_id, now, latest)
    if latest == current:
        if verbose and not quiet:
            output.write("agent-nag: bootstrap-update-check\n  Codex Bootstrap is current.\n")
        return False, checked_state
    output.write(f"agent-nag: {definition.nag_id}\n")
    output.write(f"  {definition.message}\n")
    output.write(f"  current: {current}\n")
    output.write(f"  latest:  {latest}\n")
    output.write("  Suggested:\n")
    output.write("    ./scripts/agent-bootstrap sync --dry-run\n")
    output.write("    ./scripts/agent-bootstrap sync --apply\n")
    return True, mark_shown(checked_state, definition.nag_id, now)


def mark_checked(state: NagState, nag_id: str, now: datetime, value: str) -> NagState:
    current = state.nags.get(nag_id, empty_runtime_state())
    return replace_runtime_state(
        state,
        nag_id,
        dataclasses.replace(current, last_checked_at=now, last_seen_value=value),
    )


def read_sync_metadata(root: Path) -> dict[str, str]:
    path = root / SYNC_METADATA
    if not path.is_file():
        return {}
    try:
        return read_required_sync_metadata(root)
    except (NagError, OSError, json.JSONDecodeError):
        return {}


def read_required_sync_metadata(root: Path) -> dict[str, str]:
    raw = load_json(root / SYNC_METADATA)
    source = raw.get("source")
    template = raw.get("template")
    if not isinstance(source, dict) or not isinstance(template, dict):
        raise NagError("sync metadata is missing source or template")
    return {
        "sourceRepository": require_string(source, "repository"),
        "sourceRef": require_string(source, "ref"),
        "sourceCommit": require_string(source, "commit"),
        "templateId": require_string(template, "id"),
    }


def parse_ls_remote_commit(output: str) -> str:
    for line in output.splitlines():
        commit, separator, _ref = line.partition("\t")
        if separator and len(commit) == 40:
            return commit
    raise NagError("git ls-remote did not return a commit")


def run_unchecked(command: list[str], cwd: Path | None = None) -> CommandResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=DEFAULT_TIMEOUT_SECONDS,
        check=False,
    )
    return CommandResult(completed.returncode, completed.stdout)


def status_payload(policy: NagPolicy, state: NagState) -> dict[str, Any]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "nags": {
            nag_id: {
                "enabled": definition.enabled,
                "hook": definition.hook,
                "cadence": definition.cadence,
                "state": state.nags.get(nag_id, empty_runtime_state()).to_json(),
            }
            for nag_id, definition in sorted(policy.nags.items())
        },
    }


def print_warnings(warnings: tuple[str, ...]) -> None:
    for warning in warnings:
        print(f"agent-nag: {warning}", file=sys.stderr)


def main() -> int:
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run nag tests**

Run:

```bash
PYTHONPATH=tools/supermeta-nag python3 -m unittest discover -s tools/supermeta-nag -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 6: Commit the CLI and update-check behavior**

```bash
git add tools/supermeta-nag/nag.py tools/supermeta-nag/nag_test.py
git commit -m "feat: add agent nag hooks and update checks"
```

## Task 4: Nag Wrappers And Bootstrap Delegation

**Files:**
- Create: `scripts/agent-nag`
- Create: `scripts/agent-nag.ps1`
- Create: `tools/supermeta-nag/README.md`
- Modify: `scripts/agent-bootstrap`
- Modify: `scripts/agent-bootstrap.ps1`
- Modify: `tools/supermeta-nag/nag_test.py`

- [ ] **Step 1: Add failing wrapper static tests**

Append these tests to `tools/supermeta-nag/nag_test.py`:

```python
class WrapperStaticTest(unittest.TestCase):
    def test_unix_wrapper_routes_to_nag_script(self) -> None:
        wrapper = (Path(__file__).resolve().parents[2] / "scripts" / "agent-nag").read_text(encoding="utf-8")

        self.assertIn("tools/supermeta-nag/nag.py", wrapper)
        self.assertIn('exec python3 "$repo_root/tools/supermeta-nag/nag.py" "$@"', wrapper)

    def test_powershell_wrapper_routes_to_nag_script(self) -> None:
        wrapper = (Path(__file__).resolve().parents[2] / "scripts" / "agent-nag.ps1").read_text(encoding="utf-8")

        self.assertIn("tools/supermeta-nag/nag.py", wrapper)
        self.assertIn("Invoke-PythonChecked", wrapper)

    def test_agent_bootstrap_delegates_check_updates(self) -> None:
        root = Path(__file__).resolve().parents[2]
        wrapper = (root / "scripts" / "agent-bootstrap").read_text(encoding="utf-8")
        windows = (root / "scripts" / "agent-bootstrap.ps1").read_text(encoding="utf-8")

        self.assertIn("check-updates", wrapper)
        self.assertIn("agent-nag", wrapper)
        self.assertIn("check-updates", windows)
        self.assertIn("agent-nag.ps1", windows)
```

- [ ] **Step 2: Run wrapper tests and verify missing file failures**

Run:

```bash
PYTHONPATH=tools/supermeta-nag python3 -m unittest discover -s tools/supermeta-nag -p '*_test.py'
```

Expected: FAIL with `FileNotFoundError` for `scripts/agent-nag`.

- [ ] **Step 3: Create Unix wrapper**

Create `scripts/agent-nag`:

```sh
#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd "$script_dir/.." && pwd)

exec python3 "$repo_root/tools/supermeta-nag/nag.py" "$@"
```

Mark it executable:

```bash
chmod +x scripts/agent-nag
```

- [ ] **Step 4: Create PowerShell wrapper**

Create `scripts/agent-nag.ps1`:

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

    [Console]::Error.WriteLine("scripts/agent-nag.ps1: python3, python, or py is required")
    exit 2
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$repoRoot = (Resolve-Path (Join-Path $scriptDir "..")).Path
$nagScript = Join-Path $repoRoot "tools/supermeta-nag/nag.py"
$pythonArgs = @($nagScript)
$pythonArgs += $args
Invoke-PythonChecked @pythonArgs
```

- [ ] **Step 5: Delegate `agent-bootstrap check-updates` on Unix**

Modify `scripts/agent-bootstrap` to check the first argument before invoking `bootstrap_sync.py`:

```sh
#!/bin/sh
set -eu

script_dir=$(CDPATH= cd "$(dirname "$0")" && pwd)
repo_root=$(CDPATH= cd "$script_dir/.." && pwd)

if [ "${1:-}" = "check-updates" ] && [ -x "$repo_root/scripts/agent-nag" ]; then
  shift
  exec "$repo_root/scripts/agent-nag" check-updates "$@"
fi

exec python3 "$repo_root/tools/supermeta-bootstrap/bootstrap_sync.py" "$@"
```

- [ ] **Step 6: Delegate `agent-bootstrap.ps1 check-updates` on Windows**

Insert this block after `$repoRoot` is resolved in `scripts/agent-bootstrap.ps1`:

```powershell
if ($args.Count -gt 0 -and $args[0] -eq "check-updates") {
    $nagWrapper = Join-Path $repoRoot "scripts/agent-nag.ps1"
    if (Test-Path $nagWrapper) {
        $remainingArgs = @()
        if ($args.Count -gt 1) {
            $remainingArgs = $args[1..($args.Count - 1)]
        }
        & $nagWrapper check-updates @remainingArgs
        exit $LASTEXITCODE
    }
}
```

- [ ] **Step 7: Add helper README**

Create `tools/supermeta-nag/README.md`:

```markdown
# Supermeta Agent Nag

`nag.py` is copied into generated projects and evaluates advisory agent reminders
from `.codex-bootstrap/nags.json` plus optional local overrides in
`.codex-bootstrap/nags.local.json`.

Run session-start checks:

```bash
./scripts/agent-nag run-hook session-start
```

Check for upstream Codex Bootstrap updates:

```bash
./scripts/agent-nag check-updates --quiet
```

Manage noisy reminders:

```bash
./scripts/agent-nag list
./scripts/agent-nag ack post-run-backlog-check
./scripts/agent-nag snooze post-run-backlog-check --for 7d
```

Nags are advisory. Hook failures must not replace the exit code of a wrapped
build, test, sync, or diagnostic command.
```

- [ ] **Step 8: Run wrapper tests**

Run:

```bash
bash -n scripts/agent-nag
bash -n scripts/agent-bootstrap
PYTHONPATH=tools/supermeta-nag python3 -m unittest discover -s tools/supermeta-nag -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 9: Commit wrappers and delegation**

```bash
git add scripts/agent-nag scripts/agent-nag.ps1 scripts/agent-bootstrap scripts/agent-bootstrap.ps1 tools/supermeta-nag
git commit -m "feat: add agent nag wrappers"
```

## Task 5: `agent-coord run` Hook Integration

**Files:**
- Modify: `tools/supermeta-agent/agent_test.py`
- Modify: `tools/supermeta-agent/agent.py`

- [ ] **Step 1: Add failing hook integration tests**

Append these tests to `tools/supermeta-agent/agent_test.py`:

```python
class RunNagHookIntegrationTest(unittest.TestCase):
    def test_run_invokes_pre_post_and_success_hooks(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-nag-success-") as temp_dir:
            root = Path(temp_dir)
            child = root / "child.py"
            child.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
            calls: list[tuple[str, int | None]] = []

            def fake_nag_hook(cwd: Path, hook: str, wrapper: str, command: list[str], exit_code: int | None) -> int:
                calls.append((hook, exit_code))
                return 0

            with patch.object(agent, "run_nag_hook", side_effect=fake_nag_hook):
                exit_code = agent.run_cli(
                    [
                        "--state-home",
                        str(root / "state"),
                        "--agent-id",
                        "agent-1",
                        "run",
                        "--resource",
                        "test:exclusive",
                        "--",
                        sys.executable,
                        str(child),
                    ],
                    cwd=root,
                )

            self.assertEqual(0, exit_code)
            self.assertEqual(
                [("pre-run", None), ("post-run", 0), ("post-success", 0)],
                calls,
            )

    def test_run_invokes_failure_hook_and_preserves_child_exit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-nag-failure-") as temp_dir:
            root = Path(temp_dir)
            child = root / "child.py"
            child.write_text("import sys\nsys.exit(7)\n", encoding="utf-8")
            calls: list[tuple[str, int | None]] = []

            def fake_nag_hook(cwd: Path, hook: str, wrapper: str, command: list[str], exit_code: int | None) -> int:
                calls.append((hook, exit_code))
                return 0

            with patch.object(agent, "run_nag_hook", side_effect=fake_nag_hook):
                exit_code = agent.run_cli(
                    [
                        "--state-home",
                        str(root / "state"),
                        "--agent-id",
                        "agent-1",
                        "run",
                        "--resource",
                        "test:exclusive",
                        "--",
                        sys.executable,
                        str(child),
                    ],
                    cwd=root,
                )

            self.assertEqual(7, exit_code)
            self.assertEqual(
                [("pre-run", None), ("post-run", 7), ("post-failure", 7)],
                calls,
            )

    def test_run_preserves_child_exit_when_nag_hook_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-nag-hook-fails-") as temp_dir:
            root = Path(temp_dir)
            child = root / "child.py"
            child.write_text("import sys\nsys.exit(5)\n", encoding="utf-8")

            with patch.object(agent, "run_nag_hook", return_value=2):
                exit_code = agent.run_cli(
                    [
                        "--state-home",
                        str(root / "state"),
                        "--agent-id",
                        "agent-1",
                        "run",
                        "--resource",
                        "test:exclusive",
                        "--",
                        sys.executable,
                        str(child),
                    ],
                    cwd=root,
                )

            self.assertEqual(5, exit_code)
```

- [ ] **Step 2: Run agent tests and verify missing hook failure**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
```

Expected: FAIL because `agent.run_nag_hook` does not exist.

- [ ] **Step 3: Add hook invocation helper to `agent.py`**

Add this function near `run_child_with_leases` in `tools/supermeta-agent/agent.py`:

```python
def run_nag_hook(
    cwd: Path,
    hook: str,
    wrapper: str,
    command: list[str],
    exit_code: int | None,
) -> int:
    nag_wrapper = cwd / "scripts" / ("agent-nag.ps1" if sys.platform.startswith("win") else "agent-nag")
    if not nag_wrapper.is_file():
        return 0
    args = [str(nag_wrapper), "run-hook", hook, "--wrapper", wrapper, "--command", " ".join(command)]
    if exit_code is not None:
        args.extend(["--exit-code", str(exit_code)])
    result = subprocess.run(args, cwd=cwd, check=False)
    if result.returncode != 0:
        print(f"agent-coord: agent-nag {hook} exited {result.returncode}", file=sys.stderr)
    return result.returncode
```

- [ ] **Step 4: Call nag hooks from `run_child_with_leases`**

Replace the child-process section inside `run_child_with_leases` with this structure:

```python
    child_exit = 1
    try:
        run_nag_hook(cwd, "pre-run", "agent-coord", child_command, None)
        process = subprocess.Popen(child_command, cwd=cwd)
        heartbeat_seconds = max(1.0, min(30.0, ttl_seconds / 3))
        while True:
            try:
                child_exit = process.wait(timeout=heartbeat_seconds)
                break
            except subprocess.TimeoutExpired:
                now = utc_now()
                for resource in args.resource:
                    store.acquire_once(
                        resource,
                        agent_id,
                        cwd,
                        args.task,
                        ttl_seconds,
                        now,
                        os.getpid(),
                        socket.gethostname(),
                        getpass.getuser(),
                    )
                store.announce(
                    agent_id,
                    cwd,
                    args.task,
                    (),
                    tuple(args.resource),
                    ttl_seconds,
                    now,
                    os.getpid(),
                    socket.gethostname(),
                    sys.platform,
                    getpass.getuser(),
                )
        run_nag_hook(cwd, "post-run", "agent-coord", child_command, child_exit)
        run_nag_hook(cwd, "post-success" if child_exit == 0 else "post-failure", "agent-coord", child_command, child_exit)
        return child_exit
    finally:
        store.release(tuple(args.resource), agent_id)
```

- [ ] **Step 5: Run coordination tests**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 6: Commit coordination hook integration**

```bash
git add tools/supermeta-agent/agent.py tools/supermeta-agent/agent_test.py
git commit -m "feat: call nag hooks from agent coordination runs"
```

## Task 6: Bootstrap Generator Nag Contract

**Files:**
- Modify: `tools/bootstrap/bootstrap.py`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Add failing generated-project contract tests**

In `tools/bootstrap/bootstrap_test.py`, extend the generated Java smoke assertions to include nag support:

```python
            self.assertTrue((checkout / "scripts" / "agent-nag").is_file())
            self.assertTrue((checkout / "scripts" / "agent-nag.ps1").is_file())
            self.assertTrue((checkout / "tools" / "supermeta-nag" / "nag.py").is_file())
            self.assertTrue((checkout / ".codex-bootstrap" / "nags.json").is_file())
            self.assertTrue((checkout / ".codex-bootstrap" / "nags.local.json").is_file())
            self.assertFalse((checkout / ".codex-bootstrap" / "nag-state.json").exists())
            nags = json.loads((checkout / ".codex-bootstrap" / "nags.json").read_text(encoding="utf-8"))
            self.assertEqual(1, nags["schemaVersion"])
            self.assertIn("bootstrap-update-check", [item["id"] for item in nags["nags"]])
            self.assertIn("post-run-backlog-check", [item["id"] for item in nags["nags"]])
            self.assertIn("agent-nags", sync_metadata["managedSets"])
            self.assertIn("scripts/agent-nag", sync_metadata["managedFiles"])
            self.assertIn(".codex-bootstrap/nags.json", sync_metadata["managedFiles"])
            self.assertNotIn(".codex-bootstrap/nags.local.json", sync_metadata["managedFiles"])
            self.assertIn("README.md:generated-docs/agent-nags", sync_metadata["managedRegions"])
```

Add a helper assertion for docs:

```python
def assert_generated_nag_docs(test_case: unittest.TestCase, readme: str, agents: str, operations: str) -> None:
    for text in (readme, agents, operations):
        test_case.assertIn("codex-bootstrap:begin generated-docs/agent-nags", text)
        test_case.assertIn("./scripts/agent-nag run-hook session-start", text)
        test_case.assertIn("./scripts/agent-nag snooze post-run-backlog-check --for 7d", text)
    test_case.assertIn("Treat nags as advisory", agents)
```

Call it from the existing generated docs smoke path:

```python
            assert_generated_nag_docs(
                self,
                read_text(checkout / "README.md"),
                read_text(checkout / "AGENTS.md"),
                read_text(checkout / "docs" / "OPERATIONS.md"),
            )
```

- [ ] **Step 2: Run bootstrap tests and verify missing nag failures**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: FAIL because generated projects do not yet contain `scripts/agent-nag` or `.codex-bootstrap/nags.json`.

- [ ] **Step 3: Add nag support path mapping**

In `tools/bootstrap/bootstrap.py`, extend the support-path source map near the existing `scripts/agent-*` mappings:

```python
        "../../scripts/agent-nag": "./scripts/agent-nag",
        "../../scripts/agent-nag.ps1": "./scripts/agent-nag.ps1",
        "../../tools/supermeta-nag": "./tools/supermeta-nag",
```

- [ ] **Step 4: Generate nag policy files**

Add these functions near `write_sync_metadata` in `tools/bootstrap/bootstrap.py`:

```python
def write_nag_policy_files(staged_root: Path) -> None:
    codex_dir = staged_root / ".codex-bootstrap"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "nags.json").write_text(
        json.dumps(default_nag_policy(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (codex_dir / "nags.local.json").write_text(
        json.dumps({"schemaVersion": 1, "nags": []}, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def default_nag_policy() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "nags": [
            {
                "id": "bootstrap-update-check",
                "enabled": True,
                "hook": "session-start",
                "cadence": "24h",
                "action": "check-bootstrap-update",
                "message": "A newer Codex Bootstrap version is available. Run sync when convenient.",
            },
            {
                "id": "post-run-backlog-check",
                "enabled": True,
                "hook": "post-run",
                "when": {"exitCode": 0},
                "cadence": "per-run",
                "action": "suggest-command",
                "message": "Wrapped execution completed. Refresh task context before handoff.",
                "commands": [["./scripts/agent-beads", "ready", "--json"]],
            },
            {
                "id": "post-failure-diagnostics",
                "enabled": True,
                "hook": "post-failure",
                "cadence": "per-run",
                "action": "suggest-command",
                "message": "Command failed. Inspect task state before retrying.",
                "commands": [
                    ["./scripts/agent-task", "ps"],
                    ["./scripts/agent-beads", "ready", "--json"],
                ],
            },
        ],
    }
```

Call `write_nag_policy_files(staged_root)` from `write_generated_project_docs_and_state` after `write_generated_beads(plan, staged_root)`.

- [ ] **Step 5: Generate managed nag docs regions**

Add these functions near the existing generated sync and coordination docs helpers:

```python
def generated_nag_docs_region() -> str:
    return """<!-- codex-bootstrap:begin generated-docs/agent-nags -->
## Agent Nags

This project includes advisory agent reminders for bootstrap updates, wrapped-command follow-up, and failure diagnostics.

Run session-start checks near the start of substantial work:

```bash
./scripts/agent-nag run-hook session-start
```

Manage noisy reminders without deleting managed policy:

```bash
./scripts/agent-nag list
./scripts/agent-nag snooze post-run-backlog-check --for 7d
./scripts/agent-nag ack post-run-backlog-check
```

Project-specific reminders belong in `.codex-bootstrap/nags.local.json`. Runtime state lives in `.codex-bootstrap/nag-state.json`.
<!-- codex-bootstrap:end generated-docs/agent-nags -->
"""


def generated_agent_nag_section() -> str:
    return """<!-- codex-bootstrap:begin generated-docs/agent-nags -->
## Agent Nags

- Run `./scripts/agent-nag run-hook session-start` near the start of substantial work.
- Treat nags as advisory unless the user or repo policy says otherwise.
- Do not let a nag recommendation overwrite the real result of a build, test, or sync command.
- Use `./scripts/agent-nag snooze post-run-backlog-check --for 7d` or `./scripts/agent-nag ack post-run-backlog-check` for noisy reminders.
- Put repo-specific reminders in `.codex-bootstrap/nags.local.json`.
<!-- codex-bootstrap:end generated-docs/agent-nags -->
"""
```

Insert `generated_nag_docs_region()` into generated README and operations docs, and insert `generated_agent_nag_section()` into generated `AGENTS.md`.

- [ ] **Step 6: Run bootstrap tests**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: PASS after the generated-project contract includes nag files and docs.

- [ ] **Step 7: Commit generator changes**

```bash
git add tools/bootstrap/bootstrap.py tools/bootstrap/bootstrap_test.py
git commit -m "feat: generate agent nag policy"
```

## Task 7: Template Manifests, Pages Assertion, And Catalog Docs

**Files:**
- Modify: `templates/csharp-dotnet-cli/bootstrap-template.json`
- Modify: `templates/java-gradle-cli/bootstrap-template.json`
- Modify: `templates/python-uv-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-mcp-server/bootstrap-template.json`
- Modify: `tools/pages/pages_test.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Add failing Pages managed-set assertion**

In `tools/pages/pages_test.py`, extend the Java template assertions:

```python
            self.assertIn("agent-nags", java_template["managedSets"])
```

- [ ] **Step 2: Run Pages tests and verify missing managed set**

Run:

```bash
python3 -m unittest discover -s tools/pages -p '*_test.py'
```

Expected: FAIL because template manifests do not yet include `agent-nags`.

- [ ] **Step 3: Add nag support paths to every template manifest**

In each `templates/*/bootstrap-template.json`, add these support path entries beside the other root support scripts:

```json
{
  "source": "scripts/agent-nag",
  "destination": "scripts/agent-nag"
},
{
  "source": "scripts/agent-nag.ps1",
  "destination": "scripts/agent-nag.ps1"
},
{
  "source": "tools/supermeta-nag",
  "destination": "tools/supermeta-nag"
}
```

- [ ] **Step 4: Add `agent-nags` managed set to every sync contract**

In each template manifest's `syncContract.managedSets`, add this managed set:

```json
{
  "id": "agent-nags",
  "description": "Agent reminder policy, nag wrappers, and hook implementation.",
  "files": [
    {
      "path": "scripts/agent-nag",
      "mode": "whole-file"
    },
    {
      "path": "scripts/agent-nag.ps1",
      "mode": "whole-file"
    },
    {
      "path": "tools/supermeta-nag/__init__.py",
      "mode": "whole-file"
    },
    {
      "path": "tools/supermeta-nag/nag.py",
      "mode": "whole-file"
    },
    {
      "path": "tools/supermeta-nag/nag_test.py",
      "mode": "whole-file"
    },
    {
      "path": "tools/supermeta-nag/README.md",
      "mode": "whole-file"
    },
    {
      "path": ".codex-bootstrap/nags.json",
      "mode": "whole-file"
    }
  ],
  "regions": [
    {
      "path": "README.md",
      "id": "generated-docs/agent-nags"
    },
    {
      "path": "AGENTS.md",
      "id": "generated-docs/agent-nags"
    },
    {
      "path": "docs/OPERATIONS.md",
      "id": "generated-docs/agent-nags"
    }
  ]
}
```

Do not add `.codex-bootstrap/nags.local.json` or `.codex-bootstrap/nag-state.json` to managed files.

- [ ] **Step 5: Update root README**

In `README.md`, add `scripts/agent-nag`, `scripts/agent-nag.ps1`, and `tools/supermeta-nag/` to the shipped component list and layout. Add this section after generated-project resync:

```markdown
## Agent Nags

Generated projects include advisory reminders for bootstrap updates and wrapped-command follow-up:

```bash
./scripts/agent-nag run-hook session-start
./scripts/agent-nag check-updates --quiet
./scripts/agent-nag snooze post-run-backlog-check --for 7d
```

Wrappers may call nag hooks before and after managed execution. Nags are advisory by default and must not hide the exit code from builds, tests, sync, or coordination runs. Project-specific reminders belong in `.codex-bootstrap/nags.local.json`.
```

- [ ] **Step 6: Update changelog**

Add this entry under the current unreleased section in `CHANGELOG.md`:

```markdown
- Added a generated-project agent nag contract with reusable lifecycle hooks, bootstrap update reminders, post-run follow-up suggestions, local override policy, and `agent-coord run` hook integration.
```

- [ ] **Step 7: Run Pages and bootstrap tests**

Run:

```bash
python3 -m unittest discover -s tools/pages -p '*_test.py'
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 8: Commit manifest and docs updates**

```bash
git add templates/*/bootstrap-template.json tools/pages/pages_test.py README.md CHANGELOG.md
git commit -m "feat: add agent nags to template contracts"
```

## Task 8: Full Verification And Generated-Project Smoke

**Files:**
- Test-only verification of all modified surfaces.

- [ ] **Step 1: Run nag tests**

Run:

```bash
PYTHONPATH=tools/supermeta-nag python3 -m unittest discover -s tools/supermeta-nag -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 2: Run coordination tests**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 3: Run bootstrap contract tests**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 4: Run Pages tests**

Run:

```bash
python3 -m unittest discover -s tools/pages -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 5: Run Java template check**

Run:

```bash
./scripts/agent-gradle templates/java-gradle-cli check
```

Expected: PASS.

- [ ] **Step 6: Run Java template app**

Run:

```bash
./scripts/agent-gradle templates/java-gradle-cli run
```

Expected: PASS with the generated CLI output from the Java starter.

- [ ] **Step 7: Inspect git status**

Run:

```bash
git status --short
```

Expected: only intended files from the final task are modified before the final commit.

- [ ] **Step 8: Commit any verification-only fixes**

If verification required fixes, commit them with a focused message:

```bash
git add tools/supermeta-nag tools/supermeta-agent tools/bootstrap tools/pages README.md CHANGELOG.md templates/*/bootstrap-template.json scripts/agent-nag scripts/agent-nag.ps1 scripts/agent-bootstrap scripts/agent-bootstrap.ps1
git commit -m "fix: stabilize agent nag verification"
```

If no fixes were needed, do not create an empty commit.
