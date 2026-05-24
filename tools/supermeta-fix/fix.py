#!/usr/bin/env python3
"""Failure capture and next-action hints for Codex Bootstrap generated projects."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


LAST_LOG = Path(".codex-bootstrap/fix-loop/last.log")
SCHEMA_VERSION = 1


class FixLoopError(Exception):
    pass


@dataclass(frozen=True)
class FailureClassification:
    classification_id: str
    summary: str
    next_actions: tuple[str, ...]
    diagnostics: tuple[tuple[str, ...], ...] = ()


@dataclass(frozen=True)
class CommandResult:
    command: tuple[str, ...]
    exit_code: int
    output: str


class CapturedOutput:
    def __init__(self) -> None:
        self.parts: list[str] = []

    def write(self, text: str) -> None:
        self.parts.append(text)

    def text(self) -> str:
        return "".join(self.parts)


def classify_failure(output: str) -> FailureClassification:
    lowered = output.lower()
    if "command not found" in lowered or "no such file or directory" in lowered:
        return FailureClassification(
            "missing-tool",
            "A required tool or executable is missing.",
            ("Install the missing tool or use the repo wrapper that provides it.", "./scripts/agent-task ps"),
        )
    if "address already in use" in lowered or "port is already allocated" in lowered:
        return FailureClassification(
            "port-busy",
            "A local port is already in use.",
            ("Inspect running processes before retrying.", "./scripts/agent-task ps"),
            (("./scripts/agent-task", "ps"),),
        )
    if "could not execute test class" in lowered and " 2" in output:
        return FailureClassification(
            "gradle-stale-class",
            "Gradle may be seeing a stale compiled duplicate test class.",
            ("Run a clean test for the affected module.", "./scripts/agent-gradle . clean test"),
            (("./scripts/agent-gradle", ".", "--logs"),),
        )
    if "checkstyle" in lowered or "ruff" in lowered or "biome" in lowered or "lint" in lowered:
        return FailureClassification(
            "style-check",
            "Formatter or linter verification failed.",
            ("Read the reported file and line, apply the smallest source fix, then rerun smart-check.",),
        )
    if "mypy" in lowered or "typecheck" in lowered or "tsc" in lowered or ("cs" in lowered and "error" in lowered):
        return FailureClassification(
            "typecheck",
            "Static type checking failed.",
            ("Fix the named type error, then rerun smart-check.",),
        )
    if "assert" in lowered or ("failed" in lowered and "test" in lowered):
        return FailureClassification(
            "unit-test",
            "A unit test failed.",
            ("Read the first failing test and assertion, fix behavior or test expectation, then rerun smart-check.",),
        )
    if "timed out" in lowered or "timeout" in lowered:
        return FailureClassification(
            "timeout",
            "The command timed out or appears hung.",
            ("Inspect task processes and recent logs before retrying.", "./scripts/agent-task ps"),
            (("./scripts/agent-task", "ps"),),
        )
    if ("bootstrap sync" in lowered and "conflict" in lowered) or ("managed region" in lowered and "conflict" in lowered):
        return FailureClassification(
            "sync-conflict",
            "Bootstrap sync reported a managed file or region conflict.",
            ("Run ./scripts/agent-bootstrap sync --dry-run and inspect the named managed target.",),
            (("./scripts/agent-bootstrap", "sync", "--dry-run"),),
        )
    return FailureClassification(
        "unknown",
        "Could not classify this failure.",
        (".codex-bootstrap/fix-loop/last.log", "./scripts/agent-task ps"),
        (("./scripts/agent-task", "ps"),),
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Capture command failures and print next diagnostic actions.")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--run-diagnostics", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=1)
    parser.add_argument("child_command", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def run_cli(argv: list[str], cwd: Path | None = None, stdout=None, diagnostic_runner=None) -> int:
    args = parse_args(argv)
    root = (cwd or Path.cwd()).resolve()
    output = stdout or sys.stdout
    child_command = tuple(args.child_command[1:] if args.child_command[:1] == ["--"] else args.child_command)
    if not child_command:
        error_output = output if stdout is not None else sys.stderr
        print("agent-fix-loop: child command is required after --", file=error_output)
        return 2
    result = run_with_attempts(child_command, root, max(args.max_attempts, 1))
    write_last_log(root, result.output)
    if result.exit_code == 0:
        if args.json:
            output.write(json.dumps(success_payload(result), indent=2, sort_keys=True) + "\n")
        else:
            if result.output:
                output.write(result.output)
            output.write("agent-fix-loop: command passed\n")
        return 0
    classification = classify_failure(result.output)
    diagnostics = maybe_run_diagnostics(root, classification, args.run_diagnostics, diagnostic_runner or run_child)
    if args.json:
        output.write(json.dumps(failure_payload(result, classification, diagnostics), indent=2, sort_keys=True) + "\n")
    else:
        print_classification(classification, diagnostics, output)
    return result.exit_code


def run_with_attempts(command: tuple[str, ...], cwd: Path, max_attempts: int) -> CommandResult:
    outputs: list[str] = []
    result = CommandResult(command=command, exit_code=1, output="")
    for attempt in range(1, max_attempts + 1):
        result = run_child(command, cwd)
        outputs.append(result.output)
        if result.exit_code == 0:
            break
        if attempt < max_attempts:
            outputs.append(f"\nagent-fix-loop: retrying command after failed attempt {attempt}\n")
    return CommandResult(command=result.command, exit_code=result.exit_code, output="".join(outputs))


def run_child(command: tuple[str, ...] | list[str], cwd: Path) -> CommandResult:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
    )
    return CommandResult(command=tuple(command), exit_code=completed.returncode, output=completed.stdout)


def write_last_log(root: Path, output: str) -> Path:
    destination = root / LAST_LOG
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(output, encoding="utf-8")
    return destination


def maybe_run_diagnostics(root: Path, classification: FailureClassification, enabled: bool, runner) -> tuple[CommandResult, ...]:
    if not enabled:
        return ()
    results: list[CommandResult] = []
    for command in classification.diagnostics:
        results.append(runner(command, root))
    return tuple(results)


def print_classification(classification: FailureClassification, diagnostics: tuple[CommandResult, ...], output) -> None:
    output.write(f"agent-fix-loop: {classification.classification_id}\n")
    output.write(f"  {classification.summary}\n")
    output.write("  next actions:\n")
    for action in classification.next_actions:
        output.write(f"    {action}\n")
    for diagnostic in diagnostics:
        output.write(f"  diagnostic {' '.join(diagnostic.command)} exited {diagnostic.exit_code}\n")
        if diagnostic.output:
            output.write(diagnostic.output)


def success_payload(result: CommandResult) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "command": list(result.command),
        "exitCode": result.exit_code,
        "logPath": str(LAST_LOG),
    }


def failure_payload(
    result: CommandResult,
    classification: FailureClassification,
    diagnostics: tuple[CommandResult, ...],
) -> dict[str, object]:
    return {
        "schemaVersion": SCHEMA_VERSION,
        "command": list(result.command),
        "exitCode": result.exit_code,
        "logPath": str(LAST_LOG),
        "classification": {
            "id": classification.classification_id,
            "summary": classification.summary,
            "nextActions": list(classification.next_actions),
        },
        "diagnostics": [
            {
                "command": list(diagnostic.command),
                "exitCode": diagnostic.exit_code,
                "output": diagnostic.output,
            }
            for diagnostic in diagnostics
        ],
    }


def main() -> int:
    return run_cli(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
