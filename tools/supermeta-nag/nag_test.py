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
                            "commands": [["./scripts/agent-beans", "check"]],
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
                (("./scripts/agent-beans", "check"),),
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
                    "commands": [["./scripts/agent-beans", "check"]],
                }
            ],
        },
    )


def write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
