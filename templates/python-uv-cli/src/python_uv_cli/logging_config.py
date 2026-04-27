from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final, TextIO

APP_LOGGER_NAME: Final = "python-uv-cli"
DEFAULT_LOG_LEVEL: Final = "warn"
DEFAULT_LOG_FORMAT: Final = "text"
TRACE_LEVEL: Final = 5
OFF_LEVEL: Final = logging.CRITICAL + 10

LOG_LEVELS: Final[dict[str, int]] = {
    "trace": TRACE_LEVEL,
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "off": OFF_LEVEL,
}
LOG_FORMATS: Final = {"text", "json"}
STANDARD_RECORD_FIELDS: Final = frozenset(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)

logging.addLevelName(TRACE_LEVEL, "TRACE")


class LoggingConfigurationError(ValueError):
    """Raised when LOG_LEVEL or LOG_FORMAT is invalid."""


@dataclass(frozen=True)
class LoggingConfig:
    level_name: str
    level: int
    format_name: str


def parse_logging_config(env: Mapping[str, str] | None = None) -> LoggingConfig:
    source = os.environ if env is None else env
    level_name = normalized_env_value(source, "LOG_LEVEL", DEFAULT_LOG_LEVEL)
    format_name = normalized_env_value(source, "LOG_FORMAT", DEFAULT_LOG_FORMAT)

    if level_name not in LOG_LEVELS:
        raise LoggingConfigurationError(
            f"invalid LOG_LEVEL {source.get('LOG_LEVEL')!r}; expected one of: "
            f"{', '.join(LOG_LEVELS)}"
        )
    if format_name not in LOG_FORMATS:
        raise LoggingConfigurationError(
            f"invalid LOG_FORMAT {source.get('LOG_FORMAT')!r}; expected one of: "
            f"{', '.join(sorted(LOG_FORMATS))}"
        )

    return LoggingConfig(level_name, LOG_LEVELS[level_name], format_name)


def configure_logging(
    config: LoggingConfig | None = None,
    stream: TextIO | None = None,
    logger_name: str = APP_LOGGER_NAME,
) -> logging.Logger:
    actual_config = parse_logging_config() if config is None else config
    logger = logging.getLogger(logger_name)
    logger.handlers.clear()
    logger.propagate = False
    logger.setLevel(actual_config.level)

    handler = logging.StreamHandler(stream)
    handler.setLevel(actual_config.level)
    if actual_config.format_name == "json":
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(TextLogFormatter())

    logger.addHandler(handler)
    return logger


def normalized_env_value(source: Mapping[str, str], name: str, default: str) -> str:
    value = source.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower()


class TextLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        fields = extra_fields(record)
        field_text = "".join(f" {key}={value}" for key, value in sorted(fields.items()))
        return (
            f"{format_timestamp(record.created)} {record.levelname.lower()} "
            f"{record.name} - {record.getMessage()}{field_text}"
        )


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": format_timestamp(record.created),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        payload.update(extra_fields(record))
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def extra_fields(record: logging.LogRecord) -> dict[str, object]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in STANDARD_RECORD_FIELDS and not key.startswith("_")
    }


def format_timestamp(created: float) -> str:
    return (
        datetime.fromtimestamp(created, UTC)
        .isoformat(timespec="milliseconds")
        .replace(
            "+00:00",
            "Z",
        )
    )
