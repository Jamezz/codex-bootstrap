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


BEANS_MODULE_PATH = Path(__file__).resolve().parent / "beans.py"


def load_beans_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("supermeta_beans", BEANS_MODULE_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load module from {BEANS_MODULE_PATH}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


beans = load_beans_module()


class BeansWrapperTest(unittest.TestCase):
    def test_accepts_pinned_version_and_passes_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_path = root / "args.txt"
            fake = write_fake_beans(root, "beans 0.4.2 (abc123) built 2026-01-01", log_path)

            with configured_beans(fake):
                exit_code = beans.main(["list", "--ready"])

            self.assertEqual(0, exit_code)
            self.assertEqual("list --ready", log_path.read_text(encoding="utf-8"))

    def test_accepts_version_with_v_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            log_path = root / "args.txt"
            fake = write_fake_beans(root, "beans v0.4.2 (abc123) built 2026-01-01", log_path)

            with configured_beans(fake):
                exit_code = beans.main(["check"])

            self.assertEqual(0, exit_code)
            self.assertEqual("check", log_path.read_text(encoding="utf-8"))

    def test_rejects_missing_binary(self) -> None:
        with configured_beans(Path("/missing/beans")):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = beans.main(["list"])

        self.assertEqual(2, exit_code)
        self.assertIn("was not found", stderr.getvalue())

    def test_rejects_wrong_version(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fake = write_fake_beans(root, "beans 0.5.0 (abc123) built 2026-01-01", root / "args.txt")

            stderr = io.StringIO()
            with configured_beans(fake), contextlib.redirect_stderr(stderr):
                exit_code = beans.main(["list"])

        self.assertEqual(2, exit_code)
        self.assertIn("0.4.2 is required", stderr.getvalue())
        self.assertIn("0.5.0", stderr.getvalue())


@contextlib.contextmanager
def configured_beans(path: Path):
    previous = os.environ.get("SUPERMETA_BEANS_BIN")
    os.environ["SUPERMETA_BEANS_BIN"] = str(path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("SUPERMETA_BEANS_BIN", None)
        else:
            os.environ["SUPERMETA_BEANS_BIN"] = previous


def write_fake_beans(root: Path, version: str, log_path: Path) -> Path:
    fake = root / "beans"
    fake.write_text(
        f"""#!/bin/sh
set -eu
if [ "${{1:-}}" = "version" ]; then
  echo "{version}"
  exit 0
fi
printf "%s" "$*" > "{log_path}"
""",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    return fake


if __name__ == "__main__":
    unittest.main()
