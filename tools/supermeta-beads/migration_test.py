from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import migration


class BeansMigrationTest(unittest.TestCase):
    def test_maps_fields_and_relationships(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_bean(root, "app-m1--milestone.md", "Ship", "completed", "milestone", "critical", "order: a\ntags: [release]\n")
            write_bean(root, "app-t1--task.md", "Work", "in-progress", "task", "high", "parent: app-m1\nblocked_by: [app-b1]\n")
            write_bean(root, "app-b1--bug.md", "Blocker", "todo", "bug", "normal", "blocking: [app-t1]\n")
            result = migration.migrate_repository(root)
            records = {record["id"]: record for record in migration.parse_jsonl(result.jsonl)}
            self.assertEqual("epic", records["app-m1"]["issue_type"])
            self.assertEqual("closed", records["app-m1"]["status"])
            self.assertEqual(["beans-milestone", "release"], records["app-m1"]["labels"])
            self.assertEqual({"beans": {"order": "a"}}, records["app-m1"]["metadata"])
            dependencies = records["app-t1"]["dependencies"]
            self.assertIn({"issue_id": "app-t1", "depends_on_id": "app-m1", "type": "parent-child"}, dependencies)
            self.assertEqual(1, sum(item["type"] == "blocks" for item in dependencies))

    def test_preserves_dates_and_scrapped_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_bean(root, "app-t1.md", "Old", "scrapped", "task", "deferred", "created_at: 2026-01-01T00:00:00Z\nupdated_at: 2026-02-01T00:00:00Z\n")
            record = migration.parse_jsonl(migration.migrate_repository(root).jsonl)[0]
            self.assertEqual("closed", record["status"])
            self.assertEqual(4, record["priority"])
            self.assertEqual(["beans-scrapped"], record["labels"])
            self.assertEqual("2026-01-01T00:00:00Z", record["created_at"])

    def test_fails_on_missing_reference_cycle_nested_yaml_and_collision(self) -> None:
        cases = (
            "parent: missing\n",
            "blocked_by: [app-t1]\n",
            "custom:\n  nested: value\n",
        )
        for extra in cases:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                write_bean(root, "app-t1.md", "Task", "todo", "task", "normal", extra)
                with self.assertRaises(migration.MigrationError):
                    migration.migrate_repository(root)
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_bean(root, "app-t1.md", "Task", "todo", "task", "normal", "")
            (root / ".beads").mkdir()
            (root / ".beads" / "issues.jsonl").write_text(json.dumps({"id": "app-t1", "title": "Different"}) + "\n", encoding="utf-8")
            with self.assertRaises(migration.MigrationError):
                migration.migrate_repository(root)


def write_bean(root: Path, name: str, title: str, status: str, issue_type: str, priority: str, extra: str) -> None:
    directory = root / ".beans"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text(
        f"---\ntitle: {title}\nstatus: {status}\ntype: {issue_type}\npriority: {priority}\n{extra}---\n\nBody for {title}.\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    unittest.main()
