from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cache


class RuleAnalysisCacheTest(unittest.TestCase):
    def test_lookup_hits_when_file_config_tool_and_schema_match(self) -> None:
        rule_cache = cache.RuleAnalysisCache.empty()

        rule_cache.put(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-a", {"lines": 3})

        self.assertEqual(
            {"lines": 3},
            rule_cache.lookup(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-a"),
        )
        self.assertEqual(1, rule_cache.stats.hits)

    def test_changed_digest_misses_only_that_path(self) -> None:
        rule_cache = cache.RuleAnalysisCache.empty()
        rule_cache.put(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-a", {"lines": 3})
        rule_cache.put(Path("src/Other.java"), "digest-b", "rule-a", "config-a", "tool-a", {"lines": 1})

        self.assertIsNone(rule_cache.lookup(Path("src/App.java"), "digest-new", "rule-a", "config-a", "tool-a"))
        self.assertEqual(
            {"lines": 1},
            rule_cache.lookup(Path("src/Other.java"), "digest-b", "rule-a", "config-a", "tool-a"),
        )

    def test_config_and_tool_fingerprint_changes_invalidate_entry(self) -> None:
        rule_cache = cache.RuleAnalysisCache.empty()
        rule_cache.put(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-a", {"lines": 3})

        self.assertIsNone(rule_cache.lookup(Path("src/App.java"), "digest-a", "rule-a", "config-b", "tool-a"))
        self.assertIsNone(rule_cache.lookup(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-b"))
        self.assertEqual(2, rule_cache.stats.stale)

    def test_evict_missing_removes_deleted_files(self) -> None:
        rule_cache = cache.RuleAnalysisCache.empty()
        rule_cache.put(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-a", {"lines": 3})
        rule_cache.put(Path("src/Deleted.java"), "digest-b", "rule-a", "config-a", "tool-a", {"lines": 1})

        rule_cache.evict_missing({Path("src/App.java")})

        self.assertEqual(
            {"lines": 3},
            rule_cache.lookup(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-a"),
        )
        self.assertIsNone(
            rule_cache.lookup(Path("src/Deleted.java"), "digest-b", "rule-a", "config-a", "tool-a")
        )
        self.assertEqual(1, rule_cache.stats.evicted)

    def test_corrupt_cache_file_is_ignored_and_rewritten(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "cache.json"
            cache_path.write_text("{not-json", encoding="utf-8")

            rule_cache = cache.load_cache(cache_path)
            rule_cache.put(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-a", {"lines": 3})
            rule_cache.write_atomic(cache_path)

            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            self.assertEqual(cache.SCHEMA_VERSION, payload["schemaVersion"])

    def test_write_atomic_creates_parent_and_round_trips(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            cache_path = Path(temp_dir) / "nested" / "cache.json"
            rule_cache = cache.RuleAnalysisCache.empty()
            rule_cache.put(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-a", {"lines": 3})

            rule_cache.write_atomic(cache_path)
            loaded = cache.load_cache(cache_path)

            self.assertEqual(
                {"lines": 3},
                loaded.lookup(Path("src/App.java"), "digest-a", "rule-a", "config-a", "tool-a"),
            )


if __name__ == "__main__":
    unittest.main()
