from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import capsule


class CapsuleTest(unittest.TestCase):
    def test_explicit_capsule_id_wins(self) -> None:
        project = Path("/workspace/sample-app")
        env = {
            "CODEX_BUILD_CAPSULE_ID": "codex-session-17",
            "SUPERMETA_BUILD_CAPSULE_ID": "supermeta-explicit",
        }

        resolved = capsule.resolve_capsule(project, env)

        self.assertEqual("supermeta-explicit", resolved.capsule_id)
        self.assertEqual(project / ".gradle" / "agent-capsules" / "supermeta-explicit", resolved.root)
        self.assertEqual(resolved.root / "gradle-user-home", resolved.gradle_user_home)
        self.assertEqual(resolved.root / "build-cache", resolved.build_cache)

    def test_project_specific_capsule_id_wins_over_generic_explicit_id(self) -> None:
        project = Path("/workspace/sample-app")
        env = {
            "SAMPLE_APP_BUILD_CAPSULE_ID": "project-specific",
            "SUPERMETA_BUILD_CAPSULE_ID": "supermeta-explicit",
        }

        resolved = capsule.resolve_capsule(project, env)

        self.assertEqual("project-specific", resolved.capsule_id)

    def test_project_specific_capsule_env_name_is_derived_from_project_name(self) -> None:
        self.assertEqual(
            "SAMPLE_APP_BUILD_CAPSULE_ID",
            capsule.build_capsule_env_name(Path("/workspace/sample-app")),
        )

    def test_session_id_is_used_when_explicit_id_is_absent(self) -> None:
        resolved = capsule.resolve_capsule(
            Path("/workspace/sample-app"),
            {"CODEX_SESSION_ID": "session 42"},
        )

        self.assertEqual("session-42", resolved.capsule_id)

    def test_worktree_path_hash_is_stable_and_short(self) -> None:
        first = capsule.resolve_capsule(Path("/workspace/sample-app/.worktrees/a"), {})
        second = capsule.resolve_capsule(Path("/workspace/sample-app/.worktrees/a"), {})

        self.assertEqual(first.capsule_id, second.capsule_id)
        self.assertRegex(first.capsule_id, r"^worktree-[0-9a-f]{12}$")

    def test_env_exports_gradle_state_and_build_cache(self) -> None:
        resolved = capsule.resolve_capsule(Path("/workspace/sample-app"), {"SUPERMETA_BUILD_CAPSULE_ID": "agent-1"})

        exports = resolved.gradle_environment()

        self.assertEqual(str(resolved.gradle_user_home), exports["GRADLE_USER_HOME"])
        self.assertEqual(str(resolved.build_cache), exports["SUPERMETA_GRADLE_BUILD_CACHE"])

    def test_build_cache_init_script_points_gradle_at_capsule_cache(self) -> None:
        with tempfile.TemporaryDirectory(prefix="capsule-test-") as temp_dir:
            resolved = capsule.resolve_capsule(Path(temp_dir), {"SUPERMETA_BUILD_CAPSULE_ID": "agent-1"})

            init_script = resolved.write_build_cache_init_script()

            self.assertEqual(resolved.root / "init.d" / "capsule-build-cache.gradle.kts", init_script)
            self.assertIn(str(resolved.build_cache), init_script.read_text(encoding="utf-8"))

    def test_summary_payload_is_json_serializable_shape(self) -> None:
        resolved = capsule.resolve_capsule(Path("/workspace/sample-app"), {"SUPERMETA_BUILD_CAPSULE_ID": "agent-1"})

        payload = resolved.summary_payload()

        self.assertEqual("agent-1", payload["capsuleId"])
        self.assertEqual(str(resolved.root), payload["capsuleRoot"])
        self.assertIn("gradleUserHome", payload)


if __name__ == "__main__":
    unittest.main()
