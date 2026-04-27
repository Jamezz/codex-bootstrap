# Python uv CLI Template

This template is a minimal Python command-line application with uv, pytest, Ruff, mypy, and a Codex-friendly verification path.

It can be materialized from the catalog root with:

```bash
./bootstrap --template python-uv-cli --name my-service
```

After materialization, the generated project is standalone and uses:

```bash
./scripts/check
uv run my-service
```

## Prerequisites

- `uv` on PATH;
- network access on first run so uv can download development dependencies.

The template supports Python 3.9 and newer so it can run on a broad set of developer machines while still using a modern typed `src/` layout.

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
uv run pytest
```

Run Python lint and format checks directly:

```bash
uv run ruff format --check src tests
uv run ruff check src tests
uv run mypy src tests
```

Run the app:

```bash
uv run python-uv-cli
uv run python-uv-cli "Ada Lovelace"
```

Run the module entrypoint:

```bash
uv run python -m python_uv_cli
uv run python -m python_uv_cli "Ada Lovelace"
```

Stuck-task diagnostics from the repository root:

```bash
./scripts/agent-task ps --match uv
./scripts/agent-task ps --match pytest
```

## Conventions

- production source files under `src/` are checked for a 1000-line maximum;
- Ruff owns formatting and linting;
- mypy owns static type checking;
- pytest owns behavior checks;
- reusable checks and project callouts live in `supermeta-rules.json` and the shared `tools/supermeta-rules/check.py` helper.

`bootstrap-template.json` declares the generated-project inputs, local support paths, and verification commands used by the root launcher.

## Project Shape

```text
src/python_uv_cli/cli.py
src/python_uv_cli/__main__.py
tests/test_cli.py
```

Replace the sample CLI behavior before starting real product work.
