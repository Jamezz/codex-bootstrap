from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType


MODULE_PATH = Path(__file__).resolve().parent / "beads.py"


def load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("supermeta_beads", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module from {MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


beads = load_module()


class BeadsWrapperTest(unittest.TestCase):
    def test_parse_version(self) -> None:
        self.assertEqual("1.1.0", beads.parse_version("bd version 1.1.0 (abc123)"))
        self.assertEqual("1.1.0", beads.parse_version("beads v1.1.0"))

    def test_initializes_from_jsonl_then_forwards(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".beads").mkdir()
            (root / ".beads" / "issues.jsonl").write_text("", encoding="utf-8")
            log = root / "args.txt"
            fake = write_fake_bd(root, log)
            with configured_binary(fake), mock_root(root):
                self.assertEqual(0, beads.main(["ready", "--json"]))
            calls = log.read_text(encoding="utf-8").splitlines()
            self.assertIn("init --init-if-missing --from-jsonl --non-interactive --skip-agents --skip-hooks --quiet", calls)
            self.assertEqual("ready --json", calls[-1])

    def test_existing_database_skips_initialization(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / ".beads" / "embeddeddolt").mkdir(parents=True)
            log = root / "args.txt"
            fake = write_fake_bd(root, log)
            with configured_binary(fake), mock_root(root):
                self.assertEqual(0, beads.main(["prime"]))
            self.assertNotIn("init", log.read_text(encoding="utf-8"))

    def test_rejects_missing_or_wrong_binary(self) -> None:
        with configured_binary(Path("/missing/bd")), contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(2, beads.main(["ready"]))
            self.assertIn("not found", stderr.getvalue())
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake = write_fake_bd(root, root / "args.txt", version="1.0.4")
            with configured_binary(fake), contextlib.redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(2, beads.main(["ready"]))
                self.assertIn("1.1.0 is required", stderr.getvalue())


@contextlib.contextmanager
def configured_binary(path: Path):
    previous = os.environ.get("SUPERMETA_BEADS_BIN")
    os.environ["SUPERMETA_BEADS_BIN"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SUPERMETA_BEADS_BIN", None)
        else:
            os.environ["SUPERMETA_BEADS_BIN"] = previous


@contextlib.contextmanager
def mock_root(root: Path):
    previous = beads.repository_root
    beads.repository_root = lambda: root
    try:
        yield
    finally:
        beads.repository_root = previous


def write_fake_bd(root: Path, log: Path, version: str = "1.1.0") -> Path:
    fake = root / "bd"
    fake.write_text(
        f'''#!/bin/sh
set -eu
if [ "${{1:-}}" = version ]; then
  echo "bd version {version} (abc123)"
  exit 0
fi
printf '%s\\n' "$*" >> "{log}"
if [ "${{1:-}}" = init ]; then
  mkdir -p .beads/embeddeddolt
fi
''',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


if __name__ == "__main__":
    unittest.main()
