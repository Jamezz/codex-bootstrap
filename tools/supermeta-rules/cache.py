"""Persistent per-file analysis cache for Supermeta rule scans."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


@dataclass
class CacheStats:
    hits: int = 0
    misses: int = 0
    stale: int = 0
    puts: int = 0
    evicted: int = 0

    def summary(self) -> str:
        return (
            f"cache hits={self.hits} misses={self.misses} stale={self.stale} "
            f"puts={self.puts} evicted={self.evicted}"
        )


class RuleAnalysisCache:
    def __init__(self, entries: dict[str, Any] | None = None) -> None:
        self.entries = entries if entries is not None else {}
        self.stats = CacheStats()

    @classmethod
    def empty(cls) -> "RuleAnalysisCache":
        return cls()

    def lookup(
        self,
        path: Path,
        digest: str,
        rule_key: str,
        config_fingerprint: str,
        tool_fingerprint: str,
    ) -> Any | None:
        entry = self.entries.get(normalize_path(path))
        if not isinstance(entry, dict):
            self.stats.misses += 1
            return None
        if entry.get("digest") != digest:
            self.stats.misses += 1
            return None
        facts = entry.get("facts")
        if not isinstance(facts, dict):
            self.stats.misses += 1
            return None
        fact = facts.get(rule_key)
        if not isinstance(fact, dict):
            self.stats.misses += 1
            return None
        if (
            fact.get("configFingerprint") != config_fingerprint
            or fact.get("toolFingerprint") != tool_fingerprint
        ):
            self.stats.stale += 1
            return None
        self.stats.hits += 1
        return fact.get("value")

    def put(
        self,
        path: Path,
        digest: str,
        rule_key: str,
        config_fingerprint: str,
        tool_fingerprint: str,
        value: Any,
    ) -> None:
        normalized_path = normalize_path(path)
        entry = self.entries.setdefault(normalized_path, {"digest": digest, "facts": {}})
        if not isinstance(entry, dict):
            entry = {"digest": digest, "facts": {}}
            self.entries[normalized_path] = entry
        entry["digest"] = digest
        facts = entry.setdefault("facts", {})
        if not isinstance(facts, dict):
            facts = {}
            entry["facts"] = facts
        facts[rule_key] = {
            "configFingerprint": config_fingerprint,
            "toolFingerprint": tool_fingerprint,
            "value": value,
        }
        self.stats.puts += 1

    def evict_missing(self, existing_paths: set[Path]) -> None:
        existing = {normalize_path(path) for path in existing_paths}
        for path in list(self.entries):
            if path not in existing:
                del self.entries[path]
                self.stats.evicted += 1

    def write_atomic(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": SCHEMA_VERSION,
            "entries": self.entries,
        }
        temporary = path.with_name(f".{path.name}.tmp")
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)


def load_cache(path: Path) -> RuleAnalysisCache:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return RuleAnalysisCache.empty()
    if not isinstance(payload, dict):
        return RuleAnalysisCache.empty()
    if payload.get("schemaVersion") != SCHEMA_VERSION:
        return RuleAnalysisCache.empty()
    entries = payload.get("entries")
    if not isinstance(entries, dict):
        return RuleAnalysisCache.empty()
    return RuleAnalysisCache(entries)


def normalize_path(path: Path) -> str:
    return path.as_posix().strip("/")
