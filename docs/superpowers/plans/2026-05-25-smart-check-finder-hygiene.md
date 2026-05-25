# Smart Check Finder Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add repo-scoped Finder-copy hygiene to `agent-smart-check` so exact duplicate copies are removed automatically and divergent copies stop the agent loop for review.

**Architecture:** Keep `tools/supermeta-check/check.py` as the CLI, policy, and lane-selection owner, and add a focused `tools/supermeta-check/hygiene.py` module for duplicate detection, hashing, quarantine, and Trash fallback. Smart-check runs hygiene before selecting lanes unless disabled, reports the actions in human and JSON output, and exits with `3` when review is needed before tests should run.

**Tech Stack:** Python 3 standard library, `unittest`, Git status porcelain output, template JSON manifests, generated Bootstrap docs.

---

## File Structure

- Create `tools/supermeta-check/hygiene.py`: Finder-copy candidate parsing, file hashing, directory manifests, action planning, quarantine and Trash moves.
- Create `tools/supermeta-check/hygiene_test.py`: focused unit tests for parsing, classification, manifest equality, quarantine, Trash fallback, and mutation safety.
- Modify `tools/supermeta-check/check.py`: add `--no-hygiene` and `--hygiene-only`, call hygiene preflight before lane selection, update JSON and human output, and preserve existing behavior when disabled.
- Modify `tools/supermeta-check/check_test.py`: CLI integration tests for plan-only, JSON output, review-needed exit `3`, `--no-hygiene`, and `--hygiene-only`.
- Modify `tools/supermeta-check/README.md`: document hygiene behavior and flags.
- Modify `tools/bootstrap/velocity.py`: generated README, AGENTS, and operations docs mention smart-check hygiene and review-needed behavior.
- Modify `README.md`: root velocity tooling docs mention hygiene.
- Modify `.gitignore` and every `templates/*/.gitignore`: ignore `.codex-bootstrap/cleanup-quarantine/`.
- Modify every `templates/*/bootstrap-template.json`: add `tools/supermeta-check/hygiene.py` and `tools/supermeta-check/hygiene_test.py` to the `velocity-tools` managed file set.
- Modify `tools/bootstrap/bootstrap_test.py`: assert generated projects ignore quarantine, copy the new hygiene helper, include it in sync metadata, and expose hygiene data from generated smart-check JSON.

## Task 1: Add Hygiene Candidate Parsing and Manifest Primitives

**Files:**
- Create: `tools/supermeta-check/hygiene.py`
- Create: `tools/supermeta-check/hygiene_test.py`

- [ ] **Step 1: Write failing candidate parsing tests**

Add this file with the initial tests:

```python
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

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
```

- [ ] **Step 2: Run the failing parsing tests**

Run:

```bash
python3 -m unittest tools/supermeta-check/hygiene_test.py
```

Expected: FAIL with `ModuleNotFoundError: No module named 'hygiene'` or missing `infer_finder_copy_candidate`.

- [ ] **Step 3: Implement the candidate parsing types and function**

Create `tools/supermeta-check/hygiene.py`:

```python
#!/usr/bin/env python3
"""Repo-scoped Finder-copy hygiene for Supermeta smart-check."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REVIEW_NEEDED_EXIT_CODE = 3
QUARANTINE_ROOT = Path(".codex-bootstrap/cleanup-quarantine")
SKIPPED_DIR_NAMES = {
    ".git",
    ".gradle",
    ".idea",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "obj",
    "out",
    "target",
}
NUMBERED_COPY_PATTERN = re.compile(r"^(?P<stem>.+) (?P<number>[2-9][0-9]*)(?P<suffix>(?:\.[^./]+)*)$")
COPY_SUFFIX_PATTERN = re.compile(r"^(?P<stem>.+) copy(?P<suffix>(?:\.[^./]+)*)$")


@dataclass(frozen=True)
class FinderCopyCandidate:
    duplicate_path: str
    original_path: str | None
    kind: str
    reason: str


def infer_finder_copy_candidate(root: Path, relative_path: str) -> FinderCopyCandidate | None:
    normalized = normalize_relative_path(relative_path)
    path = root / normalized
    name = path.name
    match = NUMBERED_COPY_PATTERN.match(name) or COPY_SUFFIX_PATTERN.match(name)
    if match is None:
        return None
    original_name = f"{match.group('stem')}{match.group('suffix')}"
    original = path.with_name(original_name)
    kind = path_kind(path)
    if not original.exists():
        return FinderCopyCandidate(
            duplicate_path=normalized,
            original_path=None,
            kind=kind,
            reason="ambiguous-original",
        )
    if path.is_dir() and not original.is_dir():
        return FinderCopyCandidate(normalized, None, kind, "kind-mismatch")
    if path.is_file() and not original.is_file():
        return FinderCopyCandidate(normalized, None, kind, "kind-mismatch")
    return FinderCopyCandidate(
        duplicate_path=normalized,
        original_path=normalize_relative_path(str(original.relative_to(root))),
        kind=kind,
        reason="single-original",
    )


def normalize_relative_path(path: str) -> str:
    return path.replace("\\", "/").strip("/")


def path_kind(path: Path) -> str:
    if path.is_dir():
        return "directory"
    return "file"
```

- [ ] **Step 4: Run parsing tests**

Run:

```bash
python3 -m unittest tools/supermeta-check/hygiene_test.py
```

Expected: PASS for the candidate parsing tests.

- [ ] **Step 5: Add failing file and directory manifest tests**

Append to `tools/supermeta-check/hygiene_test.py`:

```python
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
```

- [ ] **Step 6: Run the failing manifest tests**

Run:

```bash
python3 -m unittest tools/supermeta-check/hygiene_test.py
```

Expected: FAIL with missing `hash_file` or `directory_manifest`.

- [ ] **Step 7: Implement file hashing and directory manifests**

Append to `tools/supermeta-check/hygiene.py`:

```python
def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_manifest(path: Path) -> dict[str, Any]:
    entries: dict[str, dict[str, Any]] = {}
    for child in sorted(path.rglob("*")):
        relative = normalize_relative_path(str(child.relative_to(path)))
        if should_skip_manifest_path(relative):
            continue
        if child.is_symlink():
            entries[relative] = {
                "kind": "symlink",
                "target": os.readlink(child),
            }
            continue
        if child.is_dir():
            entries[relative] = {"kind": "directory"}
            continue
        if child.is_file():
            entries[relative] = {
                "kind": "file",
                "size": child.stat().st_size,
                "sha256": hash_file(child),
            }
    return {"entries": entries}


def should_skip_manifest_path(relative_path: str) -> bool:
    parts = relative_path.split("/")
    return any(part in SKIPPED_DIR_NAMES for part in parts)
```

- [ ] **Step 8: Run hygiene primitive tests**

Run:

```bash
python3 -m unittest tools/supermeta-check/hygiene_test.py
```

Expected: PASS.

- [ ] **Step 9: Commit the hygiene primitives**

Run:

```bash
git add tools/supermeta-check/hygiene.py tools/supermeta-check/hygiene_test.py
git commit -m "Add smart-check hygiene primitives"
```

## Task 2: Add Hygiene Classification, Quarantine, and Trash Actions

**Files:**
- Modify: `tools/supermeta-check/hygiene.py`
- Modify: `tools/supermeta-check/hygiene_test.py`

- [ ] **Step 1: Write failing action planning tests**

Append to `tools/supermeta-check/hygiene_test.py`:

```python
class HygieneActionTest(unittest.TestCase):
    def test_exact_duplicate_file_plans_trash_on_macos(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-trash-plan-") as temp_dir:
            root = Path(temp_dir)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App {}\n", encoding="utf-8")
            config = hygiene.HygieneConfig(platform_name="darwin", trash_root=root / ".Trash")

            result = hygiene.plan_hygiene(root, ("App 2.java",), {"App 2.java": "??"}, config)

            self.assertFalse(result.review_needed)
            self.assertEqual("trash", result.actions[0].action)
            self.assertEqual("exact-file-duplicate", result.actions[0].reason)

    def test_divergent_duplicate_file_plans_quarantine_and_review(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-quarantine-plan-") as temp_dir:
            root = Path(temp_dir)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App2 {}\n", encoding="utf-8")
            config = hygiene.HygieneConfig(platform_name="darwin", trash_root=root / ".Trash")

            result = hygiene.plan_hygiene(root, ("App 2.java",), {"App 2.java": "??"}, config)

            self.assertTrue(result.review_needed)
            self.assertEqual("quarantine", result.actions[0].action)
            self.assertEqual("divergent-file-duplicate", result.actions[0].reason)

    def test_exact_duplicate_directory_plans_trash(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-dir-trash-") as temp_dir:
            root = Path(temp_dir)
            (root / "src").mkdir()
            (root / "src 2").mkdir()
            (root / "src" / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "src 2" / "App.java").write_text("class App {}\n", encoding="utf-8")
            config = hygiene.HygieneConfig(platform_name="darwin", trash_root=root / ".Trash")

            result = hygiene.plan_hygiene(root, ("src 2",), {"src 2": "??"}, config)

            self.assertFalse(result.review_needed)
            self.assertEqual("trash", result.actions[0].action)
            self.assertEqual("exact-directory-duplicate", result.actions[0].reason)

    def test_ambiguous_candidate_reports_and_requires_review(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-report-") as temp_dir:
            root = Path(temp_dir)
            (root / "App 2.java").write_text("class App2 {}\n", encoding="utf-8")
            config = hygiene.HygieneConfig(platform_name="darwin", trash_root=root / ".Trash")

            result = hygiene.plan_hygiene(root, ("App 2.java",), {"App 2.java": "??"}, config)

            self.assertTrue(result.review_needed)
            self.assertEqual("report", result.actions[0].action)
            self.assertEqual("ambiguous-original", result.actions[0].reason)
```

- [ ] **Step 2: Run the failing action planning tests**

Run:

```bash
python3 -m unittest tools/supermeta-check/hygiene_test.py
```

Expected: FAIL with missing `HygieneConfig` or `plan_hygiene`.

- [ ] **Step 3: Implement action planning**

Append to `tools/supermeta-check/hygiene.py`:

```python
@dataclass(frozen=True)
class HygieneConfig:
    platform_name: str = platform.system().lower()
    quarantine_root: Path = QUARANTINE_ROOT
    trash_root: Path | None = None
    run_id: str | None = None


@dataclass(frozen=True)
class HygieneAction:
    action: str
    reason: str
    duplicate_path: str
    original_path: str | None = None
    destination_path: str | None = None
    manifest_path: str | None = None
    review_needed: bool = False


@dataclass(frozen=True)
class HygieneResult:
    enabled: bool
    review_needed: bool
    actions: tuple[HygieneAction, ...]


def plan_hygiene(
    root: Path,
    changed_files: tuple[str, ...],
    git_status: dict[str, str],
    config: HygieneConfig,
) -> HygieneResult:
    actions: list[HygieneAction] = []
    for changed_file in changed_files:
        normalized = normalize_relative_path(changed_file)
        if not is_mutable_status(git_status.get(normalized, "")):
            continue
        if should_skip_candidate_path(normalized):
            continue
        candidate = infer_finder_copy_candidate(root, normalized)
        if candidate is None:
            continue
        actions.append(classify_candidate(root, candidate, config))
    return HygieneResult(
        enabled=True,
        review_needed=any(action.review_needed for action in actions),
        actions=tuple(actions),
    )


def is_mutable_status(status: str) -> bool:
    return status in {"??", "A ", "AM", "AD", "A"}


def should_skip_candidate_path(relative_path: str) -> bool:
    parts = relative_path.split("/")
    if ".codex-bootstrap" in parts and "cleanup-quarantine" in parts:
        return True
    return any(part in SKIPPED_DIR_NAMES for part in parts)


def classify_candidate(root: Path, candidate: FinderCopyCandidate, config: HygieneConfig) -> HygieneAction:
    if candidate.original_path is None:
        return HygieneAction(
            action="report",
            reason=candidate.reason,
            duplicate_path=candidate.duplicate_path,
            review_needed=True,
        )
    duplicate = root / candidate.duplicate_path
    original = root / candidate.original_path
    if candidate.kind == "directory":
        duplicate_manifest = directory_manifest(duplicate)
        original_manifest = directory_manifest(original)
        if duplicate_manifest == original_manifest:
            return trash_or_quarantine_exact(candidate, config, "exact-directory-duplicate")
        return HygieneAction(
            action="quarantine",
            reason="divergent-directory-duplicate",
            duplicate_path=candidate.duplicate_path,
            original_path=candidate.original_path,
            review_needed=True,
        )
    if hash_file(duplicate) == hash_file(original):
        return trash_or_quarantine_exact(candidate, config, "exact-file-duplicate")
    return HygieneAction(
        action="quarantine",
        reason="divergent-file-duplicate",
        duplicate_path=candidate.duplicate_path,
        original_path=candidate.original_path,
        review_needed=True,
    )


def trash_or_quarantine_exact(
    candidate: FinderCopyCandidate,
    config: HygieneConfig,
    reason: str,
) -> HygieneAction:
    if supports_trash(config):
        return HygieneAction(
            action="trash",
            reason=reason,
            duplicate_path=candidate.duplicate_path,
            original_path=candidate.original_path,
            review_needed=False,
        )
    return HygieneAction(
        action="quarantine",
        reason=f"{reason}-trash-unavailable",
        duplicate_path=candidate.duplicate_path,
        original_path=candidate.original_path,
        review_needed=False,
    )


def supports_trash(config: HygieneConfig) -> bool:
    platform_name = config.platform_name.lower()
    if platform_name not in {"darwin", "macos"}:
        return False
    trash_root = config.trash_root or (Path.home() / ".Trash")
    return trash_root.exists() or trash_root.parent.exists()
```

- [ ] **Step 4: Run action planning tests**

Run:

```bash
python3 -m unittest tools/supermeta-check/hygiene_test.py
```

Expected: PASS.

- [ ] **Step 5: Write failing apply-action tests**

Append to `tools/supermeta-check/hygiene_test.py`:

```python
class HygieneApplyTest(unittest.TestCase):
    def test_apply_trash_moves_duplicate_to_trash_root(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-apply-trash-") as temp_dir:
            root = Path(temp_dir)
            trash_root = root / ".Trash"
            trash_root.mkdir()
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            duplicate = root / "App 2.java"
            duplicate.write_text("class App {}\n", encoding="utf-8")
            config = hygiene.HygieneConfig(platform_name="darwin", trash_root=trash_root, run_id="run")
            result = hygiene.plan_hygiene(root, ("App 2.java",), {"App 2.java": "??"}, config)

            applied = hygiene.apply_hygiene_actions(root, result, config, dry_run=False)

            self.assertFalse(duplicate.exists())
            self.assertTrue((trash_root / "App 2.java").exists())
            self.assertEqual("trash", applied.actions[0].action)
            self.assertEqual("App 2.java", applied.actions[0].destination_path)

    def test_apply_quarantine_moves_duplicate_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-apply-quarantine-") as temp_dir:
            root = Path(temp_dir)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            duplicate = root / "App 2.java"
            duplicate.write_text("class App2 {}\n", encoding="utf-8")
            config = hygiene.HygieneConfig(platform_name="darwin", trash_root=root / ".Trash", run_id="run")
            result = hygiene.plan_hygiene(root, ("App 2.java",), {"App 2.java": "??"}, config)

            applied = hygiene.apply_hygiene_actions(root, result, config, dry_run=False)

            self.assertFalse(duplicate.exists())
            manifest = root / applied.actions[0].manifest_path
            self.assertTrue(manifest.exists())
            self.assertIn("App 2.java", manifest.read_text(encoding="utf-8"))

    def test_dry_run_does_not_mutate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="hygiene-dry-run-") as temp_dir:
            root = Path(temp_dir)
            trash_root = root / ".Trash"
            trash_root.mkdir()
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            duplicate = root / "App 2.java"
            duplicate.write_text("class App {}\n", encoding="utf-8")
            config = hygiene.HygieneConfig(platform_name="darwin", trash_root=trash_root, run_id="run")
            result = hygiene.plan_hygiene(root, ("App 2.java",), {"App 2.java": "??"}, config)

            hygiene.apply_hygiene_actions(root, result, config, dry_run=True)

            self.assertTrue(duplicate.exists())
            self.assertFalse((trash_root / "App 2.java").exists())
```

- [ ] **Step 6: Run the failing apply-action tests**

Run:

```bash
python3 -m unittest tools/supermeta-check/hygiene_test.py
```

Expected: FAIL with missing `apply_hygiene_actions`.

- [ ] **Step 7: Implement mutation, collision-safe destinations, and manifests**

Append to `tools/supermeta-check/hygiene.py`:

```python
def apply_hygiene_actions(
    root: Path,
    result: HygieneResult,
    config: HygieneConfig,
    dry_run: bool,
) -> HygieneResult:
    applied: list[HygieneAction] = []
    for action in result.actions:
        if dry_run or action.action == "report":
            applied.append(action)
            continue
        if action.action == "trash":
            applied.append(move_to_trash(root, action, config))
            continue
        if action.action == "quarantine":
            applied.append(move_to_quarantine(root, action, config))
            continue
        applied.append(action)
    return HygieneResult(result.enabled, result.review_needed, tuple(applied))


def move_to_trash(root: Path, action: HygieneAction, config: HygieneConfig) -> HygieneAction:
    trash_root = config.trash_root or (Path.home() / ".Trash")
    trash_root.mkdir(parents=True, exist_ok=True)
    source = root / action.duplicate_path
    destination = unique_destination(trash_root / source.name)
    shutil.move(str(source), str(destination))
    return replace_action(action, destination_path=normalize_relative_path(str(destination.relative_to(trash_root))))


def move_to_quarantine(root: Path, action: HygieneAction, config: HygieneConfig) -> HygieneAction:
    run_id = config.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    source = root / action.duplicate_path
    quarantine_dir = root / config.quarantine_root / run_id / short_path_hash(action.duplicate_path)
    quarantine_dir.mkdir(parents=True, exist_ok=True)
    destination = unique_destination(quarantine_dir / source.name)
    shutil.move(str(source), str(destination))
    manifest_path = write_quarantine_manifest(root, quarantine_dir, action, destination)
    return replace_action(
        action,
        destination_path=normalize_relative_path(str(destination.relative_to(root))),
        manifest_path=normalize_relative_path(str(manifest_path.relative_to(root))),
    )


def write_quarantine_manifest(root: Path, quarantine_dir: Path, action: HygieneAction, destination: Path) -> Path:
    manifest_path = quarantine_dir / "manifest.json"
    payload = {
        "action": action.action,
        "reason": action.reason,
        "duplicatePath": action.duplicate_path,
        "originalPath": action.original_path,
        "destinationPath": normalize_relative_path(str(destination.relative_to(root))),
        "reviewNeeded": action.review_needed,
    }
    if action.original_path is not None:
        original = root / action.original_path
        if original.is_dir():
            payload["originalManifest"] = directory_manifest(original)
        elif original.is_file():
            payload["originalSha256"] = hash_file(original)
    if destination.is_dir():
        payload["duplicateManifest"] = directory_manifest(destination)
    elif destination.is_file():
        payload["duplicateSha256"] = hash_file(destination)
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    parent = destination.parent
    index = 2
    while True:
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def short_path_hash(path: str) -> str:
    return hashlib.sha256(path.encode("utf-8")).hexdigest()[:8]


def replace_action(action: HygieneAction, **changes: object) -> HygieneAction:
    payload = asdict(action)
    payload.update(changes)
    return HygieneAction(**payload)
```

- [ ] **Step 8: Run hygiene action tests**

Run:

```bash
python3 -m unittest tools/supermeta-check/hygiene_test.py
```

Expected: PASS.

- [ ] **Step 9: Commit hygiene actions**

Run:

```bash
git add tools/supermeta-check/hygiene.py tools/supermeta-check/hygiene_test.py
git commit -m "Add smart-check hygiene actions"
```

## Task 3: Integrate Hygiene into Smart Check CLI

**Files:**
- Modify: `tools/supermeta-check/check.py`
- Modify: `tools/supermeta-check/check_test.py`

- [ ] **Step 1: Write failing CLI argument tests**

Add to `GitChangedFilesTest` in `tools/supermeta-check/check_test.py`:

```python
    def test_hygiene_flags_parse(self) -> None:
        args = check.parse_args(["--hygiene-only", "--no-hygiene"])

        self.assertTrue(args.hygiene_only)
        self.assertTrue(args.no_hygiene)
```

- [ ] **Step 2: Run the failing CLI argument test**

Run:

```bash
python3 -m unittest tools/supermeta-check/check_test.py
```

Expected: FAIL because `hygiene_only` and `no_hygiene` are not defined.

- [ ] **Step 3: Add imports, constants, flags, and Git status parsing**

Modify `tools/supermeta-check/check.py`:

```python
import hygiene
```

Add near existing constants:

```python
HYGIENE_REVIEW_EXIT_CODE = hygiene.REVIEW_NEEDED_EXIT_CODE
```

Add to `parse_args`:

```python
    parser.add_argument("--no-hygiene", action="store_true")
    parser.add_argument("--hygiene-only", action="store_true")
```

Add near `detect_changed_files`:

```python
def detect_git_status(root: Path) -> dict[str, str]:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    if status.returncode != 0:
        return {}
    entries: dict[str, str] = {}
    for line in status.stdout.splitlines():
        if not line:
            continue
        code = line[:2]
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries[path.replace("\\", "/")] = code
    return entries
```

- [ ] **Step 4: Run the CLI argument test**

Run:

```bash
python3 -m unittest tools/supermeta-check/check_test.py
```

Expected: PASS or fail later due to no hygiene integration.

- [ ] **Step 5: Write failing CLI integration tests**

Add to `CliExecutionTest` in `tools/supermeta-check/check_test.py`:

```python
    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_plan_only_reports_hygiene_without_mutating(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-hygiene-plan-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--plan-only"], cwd=root, stdout=output)

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "App 2.java").exists())
            self.assertIn("hygiene would trash exact duplicate App 2.java", output.text())

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_json_includes_hygiene_actions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-hygiene-json-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--plan-only", "--json"], cwd=root, stdout=output)

            self.assertEqual(0, exit_code)
            payload = json.loads(output.text())
            self.assertTrue(payload["hygiene"]["enabled"])
            self.assertFalse(payload["hygiene"]["reviewNeeded"])
            self.assertEqual("trash", payload["hygiene"]["actions"][0]["action"])

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_divergent_duplicate_blocks_verification(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-hygiene-block-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App2 {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            def fail_if_called(command: list[str], cwd: Path, timeout_seconds: float | None = None) -> check.CommandResult:
                raise AssertionError(f"verification should not run: {command}")

            exit_code = check.run_cli([], cwd=root, stdout=output, command_runner=fail_if_called)

            self.assertEqual(3, exit_code)
            self.assertFalse((root / "App 2.java").exists())
            self.assertTrue((root / ".codex-bootstrap" / "cleanup-quarantine").exists())
            self.assertIn("hygiene needs review; verification skipped", output.text())

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_no_hygiene_preserves_existing_behavior(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-no-hygiene-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App2 {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            exit_code = check.run_cli(["--no-hygiene", "--plan-only"], cwd=root, stdout=output)

            self.assertEqual(0, exit_code)
            self.assertTrue((root / "App 2.java").exists())
            self.assertNotIn("hygiene", output.text())

    @unittest.skipIf(shutil.which("git") is None, "git is required")
    def test_hygiene_only_runs_no_verification_commands(self) -> None:
        with tempfile.TemporaryDirectory(prefix="smart-check-hygiene-only-") as temp_dir:
            root = Path(temp_dir)
            run_git(root, "init")
            write_default_policy(root)
            (root / "App.java").write_text("class App {}\n", encoding="utf-8")
            (root / "App 2.java").write_text("class App {}\n", encoding="utf-8")
            output = check.CapturedOutput()

            def fail_if_called(command: list[str], cwd: Path, timeout_seconds: float | None = None) -> check.CommandResult:
                raise AssertionError(f"verification should not run: {command}")

            exit_code = check.run_cli(["--hygiene-only"], cwd=root, stdout=output, command_runner=fail_if_called)

            self.assertEqual(0, exit_code)
            self.assertIn("hygiene", output.text())
```

- [ ] **Step 6: Run failing smart-check integration tests**

Run:

```bash
python3 -m unittest tools/supermeta-check/check_test.py
```

Expected: FAIL because hygiene is not yet run from `run_cli`.

- [ ] **Step 7: Integrate hygiene into `run_cli`**

In `run_cli`, after `changed_files` is computed and before `select_lanes`, insert:

```python
        hygiene_result = disabled_hygiene_result()
        if not args.no_hygiene:
            git_status = detect_git_status(root)
            planned_hygiene = hygiene.plan_hygiene(
                root,
                changed_files,
                git_status,
                hygiene.HygieneConfig(),
            )
            hygiene_result = hygiene.apply_hygiene_actions(
                root,
                planned_hygiene,
                hygiene.HygieneConfig(),
                dry_run=args.plan_only,
            )
        if args.hygiene_only:
            return print_hygiene_only_result(hygiene_result, args.json, output)
        if hygiene_result.review_needed and not args.plan_only:
            print_hygiene_human(hygiene_result, output, dry_run=False)
            output.write("agent-smart-check: hygiene needs review; verification skipped\n")
            return HYGIENE_REVIEW_EXIT_CODE
```

Update the later `print_result(...)` calls to pass `hygiene_result`.

Add helper functions near `print_result`:

```python
def disabled_hygiene_result() -> hygiene.HygieneResult:
    return hygiene.HygieneResult(enabled=False, review_needed=False, actions=())


def print_hygiene_only_result(result: hygiene.HygieneResult, as_json: bool, output) -> int:
    if as_json:
        output.write(json.dumps({"schemaVersion": SCHEMA_VERSION, "hygiene": hygiene_payload(result)}, indent=2, sort_keys=True) + "\n")
    else:
        print_hygiene_human(result, output, dry_run=False)
    return HYGIENE_REVIEW_EXIT_CODE if result.review_needed else 0


def print_hygiene_human(result: hygiene.HygieneResult, output, dry_run: bool) -> None:
    if not result.enabled:
        return
    prefix = "would " if dry_run else ""
    for action in result.actions:
        if action.action == "trash":
            output.write(f"agent-smart-check: hygiene {prefix}trash exact duplicate {action.duplicate_path}\n")
        elif action.action == "quarantine":
            output.write(f"agent-smart-check: hygiene {prefix}quarantine duplicate {action.duplicate_path}\n")
            if action.original_path:
                output.write(f"  original: {action.original_path}\n")
            if action.manifest_path:
                output.write(f"  review: {action.manifest_path}\n")
        elif action.action == "report":
            output.write(f"agent-smart-check: hygiene needs review for {action.duplicate_path}: {action.reason}\n")


def hygiene_payload(result: hygiene.HygieneResult) -> dict[str, Any]:
    return {
        "enabled": result.enabled,
        "reviewNeeded": result.review_needed,
        "actions": [
            {
                "action": action.action,
                "reason": action.reason,
                "duplicatePath": action.duplicate_path,
                "originalPath": action.original_path,
                "destinationPath": action.destination_path,
                "manifestPath": action.manifest_path,
                "reviewNeeded": action.review_needed,
            }
            for action in result.actions
        ],
    }
```

Change `print_result` and `result_payload` signatures:

```python
def print_result(
    plan: CheckPlan,
    results: list[CommandResult],
    as_json: bool,
    executed: bool,
    exit_code: int,
    output,
    warnings: tuple[str, ...] = (),
    hygiene_result: hygiene.HygieneResult | None = None,
) -> int:
```

At the start of non-JSON output inside `print_result`, add:

```python
    if hygiene_result is not None:
        print_hygiene_human(hygiene_result, output, dry_run=not executed)
```

In `result_payload`, add:

```python
        "hygiene": hygiene_payload(hygiene_result or disabled_hygiene_result()),
```

- [ ] **Step 8: Run smart-check integration tests**

Run:

```bash
python3 -m unittest tools/supermeta-check -p '*_test.py'
```

Expected: PASS after resolving any exact output wording mismatches by updating the implementation, not by weakening the tests.

- [ ] **Step 9: Commit smart-check integration**

Run:

```bash
git add tools/supermeta-check/check.py tools/supermeta-check/check_test.py
git commit -m "Run Finder hygiene before smart checks"
```

## Task 4: Update Docs, Ignores, and Generated Velocity Text

**Files:**
- Modify: `tools/supermeta-check/README.md`
- Modify: `tools/bootstrap/velocity.py`
- Modify: `README.md`
- Modify: `.gitignore`
- Modify: `templates/csharp-dotnet-cli/.gitignore`
- Modify: `templates/existing-repo-control/.gitignore`
- Modify: `templates/java-gradle-cli/.gitignore`
- Modify: `templates/python-uv-cli/.gitignore`
- Modify: `templates/rust-cargo-cli/.gitignore`
- Modify: `templates/typescript-bun-cli/.gitignore`
- Modify: `templates/typescript-bun-mcp-server/.gitignore`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Write failing generated ignore/docs tests**

In `tools/bootstrap/bootstrap_test.py`, add assertions to the generated checkout test near the existing fix-loop ignore assertions:

```python
            self.assertIn(".codex-bootstrap/cleanup-quarantine/", read_text(checkout / ".gitignore"))
```

Near existing velocity docs assertions, add:

```python
            self.assertIn("Finder-copy hygiene", readme)
            self.assertIn("--no-hygiene", agents)
            self.assertIn("cleanup-quarantine", operations)
```

- [ ] **Step 2: Run the failing bootstrap tests**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py
```

Expected: FAIL because the generated docs and ignores do not mention hygiene yet.

- [ ] **Step 3: Update ignores**

Add this line to `.gitignore` and every `templates/*/.gitignore`:

```text
.codex-bootstrap/cleanup-quarantine/
```

Keep it next to the existing `.codex-bootstrap/fix-loop/` entry in each file.

- [ ] **Step 4: Update smart-check README**

Replace `tools/supermeta-check/README.md` with:

```markdown
# Supermeta Smart Check

`check.py` selects focused verification lanes from changed files in Codex Bootstrap generated projects. It also runs repo-scoped Finder-copy hygiene before verification unless disabled.

```bash
./scripts/agent-smart-check --plan-only
./scripts/agent-smart-check --since HEAD~1
./scripts/agent-smart-check --changed src/example.py tests/test_example.py
./scripts/agent-smart-check --json
./scripts/agent-smart-check --full
./scripts/agent-smart-check --fast-only
./scripts/agent-smart-check --tag test
./scripts/agent-smart-check --timeout 120
./scripts/agent-smart-check --self-test
./scripts/agent-smart-check --hygiene-only
./scripts/agent-smart-check --no-hygiene
```

Generated policy lives in `.codex-bootstrap/checks.json`. Local override policy lives in `.codex-bootstrap/checks.local.json` and merges lanes by `id`.

Finder-copy hygiene scans Git-visible dirty paths for names such as `Foo 2.java`, `Foo copy.java`, and `src 2/`. Exact duplicates are moved to macOS Trash when available. Divergent or ambiguous copies are moved to `.codex-bootstrap/cleanup-quarantine/` or reported, and verification stops with exit code `3` so an agent can review the evidence.

Use `--plan-only` to see hygiene actions without mutation. Use `--hygiene-only` to clean before selecting lanes. Use `--no-hygiene` when raw verification is required.

Lanes can declare `cost`, `tags`, `requires`, lane-level `timeoutSeconds`, and per-command `timeoutSeconds`. `--self-test` validates the lane graph before a subprocess is launched, and missing `requires` fail with exit `127`.

Focused lanes are an inner-loop accelerator. Run the template full check before handoff.
```

- [ ] **Step 5: Update generated velocity docs**

In `tools/bootstrap/velocity.py`, update `generated_velocity_readme_region` to include:

```markdown
Smart-check also runs Finder-copy hygiene before verification. Exact duplicate copies are cleaned automatically; divergent or ambiguous copies stop the run for review under `.codex-bootstrap/cleanup-quarantine/`.
```

Update `generated_velocity_agent_region` to include bullets:

```markdown
- Let smart-check run Finder-copy hygiene by default; use `--no-hygiene` only for raw verification.
- Review `.codex-bootstrap/cleanup-quarantine/` when smart-check exits with hygiene review code `3`.
```

Update `generated_velocity_operations_region` to include:

```markdown
Run only the hygiene preflight:

```bash
./scripts/agent-smart-check --hygiene-only
```
```

- [ ] **Step 6: Update root README velocity docs**

In `README.md`, update the `Velocity Tools` section so the `agent-smart-check` paragraph says:

```markdown
`agent-smart-check` reads `.codex-bootstrap/checks.json` and optional `.codex-bootstrap/checks.local.json` to pick focused lanes from changed files. It runs Finder-copy hygiene first by default: exact duplicate copies are cleaned automatically, divergent or ambiguous copies are quarantined or reported, and verification stops with exit code `3` for review. Lanes can declare `cost`, `tags`, `requires`, and `timeoutSeconds`; use `--fast-only`, `--tag`, `--timeout`, `--hygiene-only`, `--no-hygiene`, and `--self-test` to keep the local loop tight.
```

- [ ] **Step 7: Run docs/bootstrap tests**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py
```

Expected: PASS.

- [ ] **Step 8: Commit docs and ignore updates**

Run:

```bash
git add README.md .gitignore templates/*/.gitignore tools/supermeta-check/README.md tools/bootstrap/velocity.py tools/bootstrap/bootstrap_test.py
git commit -m "Document smart-check Finder hygiene"
```

## Task 5: Update Template Sync Contracts for the New Helper Files

**Files:**
- Modify: `templates/csharp-dotnet-cli/bootstrap-template.json`
- Modify: `templates/existing-repo-control/bootstrap-template.json`
- Modify: `templates/java-gradle-cli/bootstrap-template.json`
- Modify: `templates/python-uv-cli/bootstrap-template.json`
- Modify: `templates/rust-cargo-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-cli/bootstrap-template.json`
- Modify: `templates/typescript-bun-mcp-server/bootstrap-template.json`
- Modify: `tools/bootstrap/bootstrap_test.py`

- [ ] **Step 1: Write failing manifest assertions**

In `assert_template_manifest_has_sync_support_paths` in `tools/bootstrap/bootstrap_test.py`, add:

```python
    test_case.assertIn("tools/supermeta-check/hygiene.py", manifest.sync_contract.managed_files)
    test_case.assertIn("tools/supermeta-check/hygiene_test.py", manifest.sync_contract.managed_files)
```

- [ ] **Step 2: Run failing manifest tests**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py
```

Expected: FAIL because template manifests do not list the new helper files.

- [ ] **Step 3: Add hygiene files to each velocity-tools managed set**

In every `templates/*/bootstrap-template.json`, find the managed set with `"id": "velocity-tools"`. In its `"files"` list, immediately after the existing `tools/supermeta-check/check_test.py` item, add:

```json
            {
              "path": "tools/supermeta-check/hygiene.py",
              "mode": "whole-file"
            },
            {
              "path": "tools/supermeta-check/hygiene_test.py",
              "mode": "whole-file"
            },
```

Keep JSON indentation consistent with the surrounding file.

- [ ] **Step 4: Run manifest tests**

Run:

```bash
python3 -m unittest tools/bootstrap/bootstrap_test.py
```

Expected: PASS.

- [ ] **Step 5: Commit manifest updates**

Run:

```bash
git add templates/*/bootstrap-template.json tools/bootstrap/bootstrap_test.py
git commit -m "Sync smart-check hygiene helper files"
```

## Task 6: Full Verification

**Files:**
- Verify only; no planned source edits.

- [ ] **Step 1: Run focused smart-check helper tests**

Run:

```bash
python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 2: Run bootstrap launcher and generated-project smoke tests**

Run:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Expected: PASS.

- [ ] **Step 3: Run full Python tool test sweep**

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

- [ ] **Step 5: Run smart-check self-test**

Run:

```bash
./scripts/agent-smart-check --self-test --json
```

Expected: JSON output has `"ok": true`.

- [ ] **Step 6: Run smart-check plan-only JSON**

Run:

```bash
./scripts/agent-smart-check --plan-only --json
```

Expected: JSON output includes `hygiene.enabled`, `hygiene.reviewNeeded`, and `plan`.

- [ ] **Step 7: Run diff hygiene**

Run:

```bash
git diff --check
```

Expected: no output and exit code `0`.

- [ ] **Step 8: Commit verification fixes only when they exist**

If verification revealed implementation bugs, inspect the changed files:

```bash
git status --short
```

Stage only files changed while fixing those verification failures. For this
feature, the expected fix files are limited to:

```bash
git add tools/supermeta-check/check.py tools/supermeta-check/check_test.py tools/supermeta-check/hygiene.py tools/supermeta-check/hygiene_test.py tools/bootstrap/bootstrap_test.py tools/bootstrap/velocity.py README.md .gitignore templates/*/.gitignore templates/*/bootstrap-template.json
git commit -m "Fix smart-check hygiene verification"
```

Do not run the commit command if `git status --short` is clean.

## Self-Review

- Spec coverage: The plan covers repo-scoped scanning, Finder-style file and directory names, exact hash and recursive manifest comparison, macOS Trash with quarantine fallback, divergent quarantine with manifests, review-needed exit `3`, JSON output, `--no-hygiene`, `--hygiene-only`, generated ignores, docs, template sync manifests, and verification.
- Placeholder scan: No placeholders remain; every implementation step names concrete files, functions, tests, and commands.
- Type consistency: The plan consistently uses `FinderCopyCandidate`, `HygieneConfig`, `HygieneAction`, `HygieneResult`, `plan_hygiene`, `apply_hygiene_actions`, and `REVIEW_NEEDED_EXIT_CODE`.
