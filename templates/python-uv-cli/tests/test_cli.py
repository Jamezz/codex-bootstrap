import json

from pytest import CaptureFixture, MonkeyPatch

from python_uv_cli.cli import CliResult, main, render
from python_uv_cli.logging_config import (
    LoggingConfigurationError,
    parse_logging_config,
)


def test_greets_default_project_name() -> None:
    assert render([]) == CliResult(0, "Hello from python-uv-cli!", "")


def test_greets_provided_name() -> None:
    assert render(["Ada", "Lovelace"]) == CliResult(0, "Hello from Ada Lovelace!", "")


def test_renders_help() -> None:
    assert render(["--help"]) == CliResult(0, "Usage: python-uv-cli [name]", "")


def test_rejects_blank_name() -> None:
    assert render([" "]) == CliResult(2, "", "Usage: python-uv-cli [name]")


def test_main_writes_stdout(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)

    exit_code = main(["Grace", "Hopper"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "Hello from Grace Hopper!\n"
    assert captured.err == ""


def test_logging_config_defaults_to_quiet_text() -> None:
    config = parse_logging_config({})

    assert config.level_name == "warn"
    assert config.format_name == "text"


def test_logging_config_parses_case_insensitive_values() -> None:
    config = parse_logging_config({"LOG_LEVEL": "INFO", "LOG_FORMAT": "JSON"})

    assert config.level_name == "info"
    assert config.format_name == "json"


def test_logging_config_rejects_invalid_level() -> None:
    try:
        parse_logging_config({"LOG_LEVEL": "verbose"})
    except LoggingConfigurationError as error:
        assert "LOG_LEVEL" in str(error)
    else:
        raise AssertionError("expected invalid LOG_LEVEL to fail")


def test_logging_config_rejects_invalid_format() -> None:
    try:
        parse_logging_config({"LOG_FORMAT": "yaml"})
    except LoggingConfigurationError as error:
        assert "LOG_FORMAT" in str(error)
    else:
        raise AssertionError("expected invalid LOG_FORMAT to fail")


def test_main_writes_text_log_when_info_enabled(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "info")
    monkeypatch.setenv("LOG_FORMAT", "text")

    exit_code = main(["Grace", "Hopper"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "Hello from Grace Hopper!\n"
    assert "info python-uv-cli - command completed exitCode=0" in captured.err


def test_main_writes_json_log_when_json_enabled(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "info")
    monkeypatch.setenv("LOG_FORMAT", "json")

    exit_code = main(["Grace", "Hopper"])
    captured = capsys.readouterr()

    assert exit_code == 0
    event = json.loads(captured.err)
    assert event["level"] == "info"
    assert event["logger"] == "python-uv-cli"
    assert event["message"] == "command completed"
    assert event["exitCode"] == 0


def test_main_fails_fast_on_invalid_logging_config(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "verbose")

    exit_code = main(["Grace", "Hopper"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert "Logging configuration error: invalid LOG_LEVEL" in captured.err
