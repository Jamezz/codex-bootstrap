from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import generated_hygiene


class GeneratedHygieneTest(unittest.TestCase):
    def test_exact_generated_duplicate_is_removed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generated-hygiene-") as temp_dir:
            root = Path(temp_dir)
            build = root / "sample-api" / "build" / "classes" / "java" / "test" / "io" / "sample"
            build.mkdir(parents=True)
            original = build / "ExampleTest.class"
            duplicate = build / "ExampleTest 2.class"
            original.write_bytes(b"class-bytes")
            duplicate.write_bytes(b"class-bytes")

            result = generated_hygiene.run_generated_hygiene(root, root / ".gradle" / "capsule" / "hygiene")

            self.assertFalse(duplicate.exists())
            self.assertFalse(result.review_needed)
            self.assertEqual("remove-exact-generated-duplicate", result.actions[0].reason)

    def test_divergent_generated_duplicate_is_quarantined(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generated-hygiene-") as temp_dir:
            root = Path(temp_dir)
            build = root / "sample-api" / "build" / "classes" / "java" / "test"
            build.mkdir(parents=True)
            original = build / "ExampleTest.class"
            duplicate = build / "ExampleTest 2.class"
            original.write_bytes(b"original")
            duplicate.write_bytes(b"divergent")

            result = generated_hygiene.run_generated_hygiene(root, root / ".gradle" / "capsule" / "hygiene")

            self.assertFalse(duplicate.exists())
            self.assertTrue(result.review_needed)
            self.assertEqual("quarantine-divergent-generated-duplicate", result.actions[0].reason)
            self.assertTrue(Path(result.actions[0].manifest_path).exists())

    def test_source_duplicate_is_not_touched(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generated-hygiene-") as temp_dir:
            root = Path(temp_dir)
            source = root / "sample-api" / "src" / "test" / "java" / "ExampleTest 2.java"
            source.parent.mkdir(parents=True)
            source.write_text("class ExampleTest2 {}\n", encoding="utf-8")

            result = generated_hygiene.run_generated_hygiene(root, root / ".gradle" / "capsule" / "hygiene")

            self.assertTrue(source.exists())
            self.assertEqual((), result.actions)

    def test_copy_suffix_generated_duplicate_is_removed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generated-hygiene-") as temp_dir:
            root = Path(temp_dir)
            build = root / "module" / "build" / "classes"
            build.mkdir(parents=True)
            original = build / "Worker.class"
            duplicate = build / "Worker copy.class"
            original.write_bytes(b"same")
            duplicate.write_bytes(b"same")

            result = generated_hygiene.run_generated_hygiene(root, root / ".gradle" / "capsule" / "hygiene")

            self.assertFalse(duplicate.exists())
            self.assertFalse(result.review_needed)

    def test_report_duplicate_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generated-hygiene-") as temp_dir:
            root = Path(temp_dir)
            reports = root / "build" / "reports" / "problems"
            reports.mkdir(parents=True)
            duplicate = reports / "problems-report 2.html"
            duplicate.write_text("<html>report</html>", encoding="utf-8")

            result = generated_hygiene.run_generated_hygiene(root, root / ".gradle" / "capsule" / "hygiene")

            self.assertTrue(duplicate.exists())
            self.assertEqual((), result.actions)

    def test_test_result_duplicate_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generated-hygiene-") as temp_dir:
            root = Path(temp_dir)
            test_results = root / "build" / "test-results" / "test"
            test_results.mkdir(parents=True)
            original = test_results / "TEST-Example.xml"
            duplicate = test_results / "TEST-Example 2.xml"
            original.write_text("<testsuite />\n", encoding="utf-8")
            duplicate.write_text("<testsuite failures=\"1\" />\n", encoding="utf-8")

            result = generated_hygiene.run_generated_hygiene(root, root / ".gradle" / "capsule" / "hygiene")

            self.assertTrue(duplicate.exists())
            self.assertEqual((), result.actions)

    def test_nested_worktree_duplicate_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generated-hygiene-") as temp_dir:
            root = Path(temp_dir)
            build = root / ".worktrees" / "feature" / "module" / "build" / "classes"
            build.mkdir(parents=True)
            original = build / "Worker.class"
            duplicate = build / "Worker 2.class"
            original.write_bytes(b"original")
            duplicate.write_bytes(b"divergent")

            result = generated_hygiene.run_generated_hygiene(root, root / ".gradle" / "capsule" / "hygiene")

            self.assertTrue(duplicate.exists())
            self.assertEqual((), result.actions)

    def test_nested_swift_and_artifact_outputs_are_ignored(self) -> None:
        with tempfile.TemporaryDirectory(prefix="generated-hygiene-") as temp_dir:
            root = Path(temp_dir)
            for skipped_dir in (".build", "artifacts"):
                build = root / skipped_dir / "sample-app" / "build" / "classes"
                build.mkdir(parents=True)
                original = build / "Worker.class"
                duplicate = build / "Worker 2.class"
                original.write_bytes(b"original")
                duplicate.write_bytes(b"divergent")

            result = generated_hygiene.run_generated_hygiene(root, root / ".gradle" / "capsule" / "hygiene")

            self.assertEqual((), result.actions)
            self.assertTrue((root / ".build" / "sample-app" / "build" / "classes" / "Worker 2.class").exists())
            self.assertTrue((root / "artifacts" / "sample-app" / "build" / "classes" / "Worker 2.class").exists())


if __name__ == "__main__":
    unittest.main()
