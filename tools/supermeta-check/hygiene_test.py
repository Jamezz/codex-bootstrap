from __future__ import annotations

import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import hygiene


class CandidateParsingTest(unittest.TestCase):
    def test_recognizes_numbered_file_copy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-candidate-") as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            original = root / "src" / "App.java"
            duplicate = root / "src" / "App 2.java"
            original.write_text("class App {}\n", encoding="utf-8")
            duplicate.write_text("class App {}\n", encoding="utf-8")

            candidate = hygiene.infer_finder_copy_candidate(root, "src/App 2.java")

            self.assertIsNotNone(candidate)
            assert candidate is not None
            self.assertEqual("src/App 2.java", candidate.duplicate_path)
            self.assertEqual("src/App.java", candidate.original_path)
            self.assertEqual("file", candidate.kind)

    def test_recognizes_copy_suffix_file(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-copy-suffix-") as temp_dir:
            root = Path(temp_dir)
            original = root / "README.md"
            duplicate = root / "README copy.md"
            original.write_text("docs\n", encoding="utf-8")
            duplicate.write_text("docs\n", encoding="utf-8")

            candidate = hygiene.infer_finder_copy_candidate(root, "README copy.md")

            self.assertIsNotNone(candidate)
            assert candidate is not None
            self.assertEqual("README.md", candidate.original_path)

    def test_recognizes_numbered_directory_copy(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-dir-") as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src 2").mkdir()

            candidate = hygiene.infer_finder_copy_candidate(root, "src 2")

            self.assertIsNotNone(candidate)
            assert candidate is not None
            self.assertEqual("src", candidate.original_path)
            self.assertEqual("directory", candidate.kind)

    def test_ignores_non_finder_copy_name(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-ignore-") as temp_dir:
            root = Path(temp_dir)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")

            candidate = hygiene.infer_finder_copy_candidate(root, "App.java")

            self.assertIsNone(candidate)

    def test_ambiguous_candidate_has_no_original(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-ambiguous-") as temp_dir:
            root = Path(temp_dir)
            (root / "App 2.java").write_text("class App2 {}\n", encoding="utf-8")

            candidate = hygiene.infer_finder_copy_candidate(root, "App 2.java")

            self.assertIsNotNone(candidate)
            assert candidate is not None
            self.assertIsNone(candidate.original_path)
            self.assertEqual("ambiguous-original", candidate.reason)


class ManifestTest(unittest.TestCase):
    def test_hash_file_detects_equal_content(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-hash-") as temp_dir:
            root = Path(temp_dir)
            left = root / "left.txt"
            right = root / "right.txt"
            left.write_text("same\n", encoding="utf-8")
            right.write_text("same\n", encoding="utf-8")

            self.assertEqual(hygiene.hash_file(left), hygiene.hash_file(right))

    def test_directory_manifest_uses_relative_paths_sizes_and_hashes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-manifest-") as temp_dir:
            root = Path(temp_dir)
            original = root / "src"
            duplicate = root / "src 2"
            (original / "nested").mkdir(parents=True)
            (duplicate / "nested").mkdir(parents=True)
            (original / "nested" / "App.java").write_text("class App {}\n", encoding="utf-8")
            (duplicate / "nested" / "App.java").write_text("class App {}\n", encoding="utf-8")

            self.assertEqual(
                hygiene.directory_manifest(original),
                hygiene.directory_manifest(duplicate),
            )

    def test_directory_manifest_records_symlink_without_following(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-symlink-") as temp_dir:
            root = Path(temp_dir)
            directory = root / "src"
            directory.mkdir()
            target = root / "target.txt"
            target.write_text("target\n", encoding="utf-8")
            (directory / "link.txt").symlink_to(target)

            manifest = hygiene.directory_manifest(directory)

            self.assertEqual("symlink", manifest["entries"]["link.txt"]["kind"])
            self.assertNotIn("sha256", manifest["entries"]["link.txt"])


if __name__ == "__main__":
    unittest.main()
