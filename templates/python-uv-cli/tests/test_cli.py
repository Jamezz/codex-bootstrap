from pytest import CaptureFixture

from python_uv_cli.cli import CliResult, main, render


def test_greets_default_project_name() -> None:
    assert render([]) == CliResult(0, "Hello from python-uv-cli!", "")


def test_greets_provided_name() -> None:
    assert render(["Ada", "Lovelace"]) == CliResult(0, "Hello from Ada Lovelace!", "")


def test_renders_help() -> None:
    assert render(["--help"]) == CliResult(0, "Usage: python-uv-cli [name]", "")


def test_rejects_blank_name() -> None:
    assert render([" "]) == CliResult(2, "", "Usage: python-uv-cli [name]")


def test_main_writes_stdout(capsys: CaptureFixture[str]) -> None:
    exit_code = main(["Grace", "Hopper"])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert captured.out == "Hello from Grace Hopper!\n"
    assert captured.err == ""
