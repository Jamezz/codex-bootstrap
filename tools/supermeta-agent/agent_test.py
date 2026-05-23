from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from io import StringIO
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agent


class StateHomeTest(unittest.TestCase):
    def test_uses_override_state_home(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-home-") as temp_dir:
            env = {"CODEX_AGENT_COORD_HOME": temp_dir}

            self.assertEqual(Path(temp_dir), agent.resolve_state_home(env, platform_name="linux"))

    def test_resolves_linux_state_home_from_xdg(self) -> None:
        env = {"XDG_STATE_HOME": "/tmp/state-home"}

        self.assertEqual(Path("/tmp/state-home/codex-bootstrap/agents"), agent.resolve_state_home(env, platform_name="linux"))

    def test_resolves_linux_state_home_fallback(self) -> None:
        env = {"HOME": "/home/alice"}

        self.assertEqual(Path("/home/alice/.local/state/codex-bootstrap/agents"), agent.resolve_state_home(env, platform_name="linux"))

    def test_resolves_macos_state_home(self) -> None:
        env = {"HOME": "/Users/alice"}

        self.assertEqual(
            Path("/Users/alice/Library/Application Support/codex-bootstrap/agents"),
            agent.resolve_state_home(env, platform_name="darwin"),
        )

    def test_resolves_windows_state_home(self) -> None:
        env = {"LOCALAPPDATA": r"C:\Users\alice\AppData\Local"}

        self.assertEqual(
            Path(r"C:\Users\alice\AppData\Local\CodexBootstrap\agents"),
            agent.resolve_state_home(env, platform_name="win32"),
        )


class IdentityTest(unittest.TestCase):
    def test_agent_id_prefers_cli_value(self) -> None:
        identity = agent.resolve_agent_identity(
            agent_id="cli-agent",
            env={"CODEX_AGENT_ID": "env-agent"},
            cwd=Path("/tmp/repo"),
            host="host",
            user="alice",
        )

        self.assertEqual("cli-agent", identity)

    def test_agent_id_uses_codex_agent_id(self) -> None:
        identity = agent.resolve_agent_identity(
            agent_id=None,
            env={"CODEX_AGENT_ID": "env-agent"},
            cwd=Path("/tmp/repo"),
            host="host",
            user="alice",
        )

        self.assertEqual("env-agent", identity)

    def test_agent_id_uses_codex_session_id(self) -> None:
        identity = agent.resolve_agent_identity(
            agent_id=None,
            env={"CODEX_SESSION_ID": "session-123"},
            cwd=Path("/tmp/repo"),
            host="host",
            user="alice",
        )

        self.assertEqual("session-123", identity)

    def test_fallback_agent_id_is_stable_for_checkout(self) -> None:
        first = agent.resolve_agent_identity(
            agent_id=None,
            env={},
            cwd=Path("/tmp/my-service"),
            host="host",
            user="alice",
        )
        second = agent.resolve_agent_identity(
            agent_id=None,
            env={},
            cwd=Path("/tmp/my-service"),
            host="host",
            user="alice",
        )

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("host-alice-my-service-"))

    def test_rejects_unsafe_agent_id(self) -> None:
        with self.assertRaisesRegex(agent.CoordinationError, "invalid agent id"):
            agent.validate_agent_id("../bad")


class ResourceValidationTest(unittest.TestCase):
    def test_accepts_recommended_resource_names(self) -> None:
        for value in ("perf", "perf:exclusive", "cpu:heavy", "memory:heavy", "docker", "hazeldisk:perf-cluster"):
            with self.subTest(value=value):
                self.assertEqual(value, agent.validate_resource_name(value))

    def test_rejects_unsafe_resource_names(self) -> None:
        for value in ("", "../perf", "perf/exclusive", "perf exclusive", "perf*", ".hidden"):
            with self.subTest(value=value):
                with self.assertRaisesRegex(agent.CoordinationError, "invalid resource"):
                    agent.validate_resource_name(value)

    def test_resource_file_name_is_safe_for_windows(self) -> None:
        self.assertEqual("resource-268dbe08db0de18b979c784d.json", agent.resource_file_name("perf:exclusive"))
        self.assertNotIn(":", agent.resource_file_name("perf:exclusive"))


class RegistryLifecycleTest(unittest.TestCase):
    def test_announces_and_reads_live_agent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-registry-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)

            record = store.announce(
                agent_id="agent-1",
                cwd=Path("/tmp/sample-app"),
                task="perf pass",
                tags=("hazeldisk",),
                resources=("cpu:heavy", "perf"),
                ttl_seconds=900,
                now=now,
                pid=123,
                host="host",
                platform_name="linux",
                user="alice",
            )

            self.assertEqual("agent-1", record.agent_id)
            live_agents, corrupt = store.read_live_agents(now=now + timedelta(seconds=5))
            self.assertEqual([], corrupt)
            self.assertEqual(("agent-1",), tuple(item.agent_id for item in live_agents))
            self.assertEqual(("cpu:heavy", "perf"), live_agents[0].resources)

    def test_stale_agent_records_are_removed_during_cleanup(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-stale-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            old = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            store.announce(
                agent_id="stale-agent",
                cwd=Path("/tmp/sample-app"),
                task="old work",
                tags=(),
                resources=("perf",),
                ttl_seconds=10,
                now=old,
                pid=123,
                host="host",
                platform_name="linux",
                user="alice",
            )

            removed = store.cleanup_expired(now=old + timedelta(seconds=30))

            self.assertEqual(("stale-agent",), tuple(removed))
            self.assertFalse((Path(temp_dir) / "registry" / "stale-agent.json").exists())

    def test_corrupt_registry_record_is_ignored_and_moved(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-corrupt-") as temp_dir:
            root = Path(temp_dir)
            registry = root / "registry"
            registry.mkdir(parents=True)
            (registry / "bad.json").write_text("{not json", encoding="utf-8")
            store = agent.CoordinationStore(root)

            live_agents, corrupt = store.read_live_agents(now=datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc))

            self.assertEqual([], live_agents)
            self.assertEqual(("bad.json",), tuple(item.name for item in corrupt))
            self.assertTrue(any(path.name.startswith("bad.json") for path in (root / "corrupt").iterdir()))


def read_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


class LeaseLifecycleTest(unittest.TestCase):
    def test_acquires_free_exclusive_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-lease-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)

            lease = store.acquire_once(
                resource="perf:exclusive",
                agent_id="agent-1",
                cwd=Path("/tmp/sample-app"),
                task="perf pass",
                ttl_seconds=900,
                now=now,
                pid=123,
                host="host",
                user="alice",
            )

            self.assertEqual("perf:exclusive", lease.resource)
            self.assertEqual("agent-1", lease.agent_id)

    def test_reentrant_acquire_by_same_agent_refreshes_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-reentrant-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            first = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            second = first + timedelta(seconds=30)
            store.acquire_once("docker", "agent-1", Path("/tmp/sample-app"), "docker work", 900, first, 123, "host", "alice")

            lease = store.acquire_once("docker", "agent-1", Path("/tmp/sample-app"), "docker work", 900, second, 123, "host", "alice")

            self.assertEqual(agent.format_time(second), lease.updatedAt)

    def test_live_lease_blocks_other_agent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-blocked-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            store.acquire_once("perf:exclusive", "agent-1", Path("/tmp/one"), "first", 900, now, 123, "host", "alice")

            with self.assertRaisesRegex(agent.LeaseUnavailable, "perf:exclusive is held by agent-1"):
                store.acquire_once("perf:exclusive", "agent-2", Path("/tmp/two"), "second", 900, now, 456, "host", "alice")

    def test_expired_lease_is_reclaimed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-expired-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            first = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            second = first + timedelta(seconds=30)
            store.acquire_once("perf:exclusive", "agent-1", Path("/tmp/one"), "first", 10, first, 123, "host", "alice")

            lease = store.acquire_once("perf:exclusive", "agent-2", Path("/tmp/two"), "second", 900, second, 456, "host", "alice")

            self.assertEqual("agent-2", lease.agent_id)

    def test_release_removes_owned_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-release-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            store.acquire_once("docker", "agent-1", Path("/tmp/sample-app"), "docker work", 900, now, 123, "host", "alice")

            released = store.release(("docker",), "agent-1")

            self.assertEqual(("docker",), tuple(released))
            self.assertFalse((Path(temp_dir) / "leases" / agent.resource_file_name("docker")).exists())

    def test_release_all_removes_all_owned_leases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-release-all-") as temp_dir:
            store = agent.CoordinationStore(Path(temp_dir))
            now = datetime(2026, 5, 23, 19, 0, tzinfo=timezone.utc)
            store.acquire_once("docker", "agent-1", Path("/tmp/sample-app"), "work", 900, now, 123, "host", "alice")
            store.acquire_once("perf:exclusive", "agent-1", Path("/tmp/sample-app"), "work", 900, now, 123, "host", "alice")

            released = store.release_all("agent-1")

            self.assertEqual(("docker", "perf:exclusive"), tuple(sorted(released)))


class CliBehaviorTest(unittest.TestCase):
    def test_status_json_reports_agents_and_leases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-status-") as temp_dir:
            output = agent.run_cli(
                [
                    "--state-home",
                    temp_dir,
                    "--agent-id",
                    "agent-1",
                    "announce",
                    "--task",
                    "perf pass",
                    "--resource",
                    "perf",
                ],
                cwd=Path(temp_dir),
                env={},
                stdout=agent.CapturedOutput(),
            )
            self.assertEqual(0, output)

            captured = agent.CapturedOutput()
            exit_code = agent.run_cli(["--state-home", temp_dir, "status", "--json"], cwd=Path(temp_dir), env={}, stdout=captured)

            self.assertEqual(0, exit_code)
            payload = json.loads(captured.text)
            self.assertEqual(["agent-1"], [item["agentId"] for item in payload["agents"]])
            self.assertEqual([], payload["leases"])

    def test_acquire_timeout_returns_75(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-timeout-") as temp_dir:
            first = agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-1", "acquire", "--resource", "docker"],
                cwd=Path(temp_dir),
                env={},
                stdout=agent.CapturedOutput(),
            )
            with redirect_stderr(StringIO()):
                second = agent.run_cli(
                    ["--state-home", temp_dir, "--agent-id", "agent-2", "acquire", "--resource", "docker", "--timeout", "0s"],
                    cwd=Path(temp_dir),
                    env={},
                    stdout=agent.CapturedOutput(),
                )

            self.assertEqual(0, first)
            self.assertEqual(agent.ACQUIRE_TIMEOUT_EXIT, second)

    def test_leave_removes_agent_and_owned_leases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-leave-") as temp_dir:
            agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-1", "announce", "--task", "work", "--resource", "docker"],
                cwd=Path(temp_dir),
                env={},
                stdout=agent.CapturedOutput(),
            )
            agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-1", "acquire", "--resource", "docker"],
                cwd=Path(temp_dir),
                env={},
                stdout=agent.CapturedOutput(),
            )

            exit_code = agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-1", "leave"],
                cwd=Path(temp_dir),
                env={},
                stdout=agent.CapturedOutput(),
            )

            self.assertEqual(0, exit_code)
            self.assertFalse((Path(temp_dir) / "registry" / "agent-1.json").exists())
            self.assertFalse((Path(temp_dir) / "leases" / agent.resource_file_name("docker")).exists())

    def test_run_returns_child_exit_code_and_releases_lease(self) -> None:
        with tempfile.TemporaryDirectory(prefix="agent-coord-run-") as temp_dir:
            command = [
                sys.executable,
                "-c",
                "import sys; sys.exit(7)",
            ]

            exit_code = agent.run_cli(
                ["--state-home", temp_dir, "--agent-id", "agent-1", "run", "--resource", "perf:exclusive", "--", *command],
                cwd=Path(temp_dir),
                env={},
                stdout=agent.CapturedOutput(),
            )

            self.assertEqual(7, exit_code)
            self.assertFalse((Path(temp_dir) / "leases" / agent.resource_file_name("perf:exclusive")).exists())


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
