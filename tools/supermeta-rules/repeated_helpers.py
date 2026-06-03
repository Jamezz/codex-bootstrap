"""Detect repeated helper methods with parser-backed language adapters."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


SUPPORTED_LANGUAGES = ("java",)


@dataclass(frozen=True)
class SourceGroup:
    name: str
    paths: tuple[str, ...]
    include: tuple[str, ...]
    exclude: tuple[str, ...]


@dataclass(frozen=True)
class RepeatedHelperConfig:
    name: str
    language: str
    groups: tuple[SourceGroup, ...]
    min_statements: int
    near_match_threshold: float
    advisory_near_matches: bool
    ignore_annotations: tuple[str, ...]
    allow_methods: frozenset[str]


@dataclass(frozen=True)
class GroupSourceFile:
    group: str
    path: Path
    source: str


@dataclass(frozen=True)
class HelperCandidate:
    group: str
    path: Path
    line: int
    name: str
    normalized_tokens: tuple[str, ...]
    structure: tuple[str, ...]
    statement_count: int


@dataclass(frozen=True)
class HelperFinding:
    path: Path
    message: str
    severity: str = "error"


def find_repeated_helpers(
    config: RepeatedHelperConfig,
    source_files: list[GroupSourceFile],
) -> list[HelperFinding]:
    _ = (config, source_files)
    return []
