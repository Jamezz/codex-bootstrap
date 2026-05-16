# Python uv CLI Template

This template is a minimal Python command-line application with uv, pytest, Ruff, mypy, and a Codex-friendly verification path.
It includes first-class runtime logging through Python's standard `logging` package with quiet text logs by default and JSON logs available through environment configuration.

It can be materialized from the catalog root with:

```bash
./bootstrap --template python-uv-cli --name my-service
```

After materialization, the generated project is standalone and uses:

```bash
./scripts/check
uv run --no-editable my-service
```

## Prerequisites

- `uv` on PATH;
- network access on first run so uv can download development dependencies.

The template targets Python 3.14 and uses a typed `src/` layout.

## Usage

Install the locked project environment:

```bash
uv sync --locked
```

Run the full check lifecycle:

```bash
./scripts/check
```

Run tests:

```bash
uv run --no-editable pytest
```

Run Python lint and format checks directly:

```bash
uv run --no-editable ruff format --check src tests
uv run --no-editable ruff check src tests
uv run --no-editable mypy src tests
```

Run the app:

```bash
uv run --no-editable python-uv-cli
uv run --no-editable python-uv-cli "Ada Lovelace"
```

Enable runtime logs:

```bash
LOG_LEVEL=info uv run --no-editable python-uv-cli
LOG_LEVEL=info LOG_FORMAT=json uv run --no-editable python-uv-cli
```

`LOG_LEVEL` accepts `trace`, `debug`, `info`, `warn`, `error`, or `off`. `LOG_FORMAT` accepts `text` or `json`. Logs always go to stderr, and normal command output stays on stdout unless the CLI is reporting a user-facing error.

Run the module entrypoint:

```bash
uv run --no-editable python -m python_uv_cli
uv run --no-editable python -m python_uv_cli "Ada Lovelace"
```

Stuck-task diagnostics from the repository root:

```bash
./scripts/agent-task ps --match uv
./scripts/agent-task ps --match pytest
```

PowerShell entrypoints are available for Windows agents:

```powershell
cd templates/python-uv-cli
.\scripts\check.ps1
uv run --no-editable python-uv-cli
.\..\..\scripts\agent-task.ps1 ps --match uv
```

Generated projects also include a pinned Beans wrapper and seeded starter backlog:

```bash
./scripts/agent-beans prime
./scripts/agent-beans list --ready
./scripts/agent-beans check
```

## Conventions

- production source files under `src/` are checked for a 1000-line maximum;
- Ruff owns formatting and linting;
- mypy owns static type checking;
- pytest owns behavior checks;
- reusable checks and project callouts live in `supermeta-rules.json` and the shared `tools/supermeta-rules/check.py` helper.

`bootstrap-template.json` declares the generated-project inputs, local support paths, and verification commands used by the root launcher.

The manifest also declares generated-doc metadata used to write `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/DECISIONS.md` after bootstrap.

## Project Shape

```text
src/python_uv_cli/cli.py
src/python_uv_cli/__main__.py
src/python_uv_cli/logging_config.py
tests/test_cli.py
```

Replace the sample CLI behavior before starting real product work.
