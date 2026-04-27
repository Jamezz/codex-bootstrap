from __future__ import annotations

import sys
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TextIO

DEFAULT_NAME = "python-uv-cli"
USAGE = "Usage: python-uv-cli [name]"


@dataclass(frozen=True)
class CliResult:
    exit_code: int
    stdout: str
    stderr: str


def render(args: Sequence[str], default_name: str = DEFAULT_NAME) -> CliResult:
    if args and args[0] == "--help":
        return CliResult(0, USAGE, "")

    name = default_name if not args else " ".join(args).strip()
    if not name:
        return CliResult(2, "", USAGE)

    return CliResult(0, f"Hello from {name}!", "")


def write_result(result: CliResult, stdout: TextIO, stderr: TextIO) -> None:
    if result.stdout:
        print(result.stdout, file=stdout)
    if result.stderr:
        print(result.stderr, file=stderr)


def main(argv: Sequence[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    result = render(args)
    write_result(result, sys.stdout, sys.stderr)
    return result.exit_code
