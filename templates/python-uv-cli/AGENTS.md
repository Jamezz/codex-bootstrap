# Python uv CLI Agent Notes

This is a copyable starter, not a long-lived framework.

## Commands

- Install locked environment from repo root: `cd templates/python-uv-cli && uv sync --locked`
- Verify from repo root: `cd templates/python-uv-cli && ./scripts/check`
- Test from repo root: `cd templates/python-uv-cli && uv run --no-editable pytest`
- Format check from repo root: `cd templates/python-uv-cli && uv run --no-editable ruff format --check src tests`
- Lint from repo root: `cd templates/python-uv-cli && uv run --no-editable ruff check src tests`
- Type check from repo root: `cd templates/python-uv-cli && uv run --no-editable mypy src tests`
- Run from repo root: `cd templates/python-uv-cli && uv run --no-editable python-uv-cli`
- Run with app args from repo root: `cd templates/python-uv-cli && uv run --no-editable python-uv-cli "Ada Lovelace"`
- Run module entrypoint from repo root: `cd templates/python-uv-cli && uv run --no-editable python -m python_uv_cli "Ada Lovelace"`
- Beans prime after materialization: `./scripts/agent-beans prime`
- Beans check after materialization: `./scripts/agent-beans check`
- Inspect task processes: `./scripts/agent-task ps --match uv`
- Inspect pytest processes: `./scripts/agent-task ps --match pytest`

## Rules

- Keep runtime dependencies in `pyproject.toml`; keep dev-only tools in the dev dependency group.
- Keep the Python baseline at 3.14 unless the project intentionally chooses a different runtime floor.
- Keep CLI behavior in `src/python_uv_cli/cli.py` and entrypoint glue in `src/python_uv_cli/__main__.py`.
- Keep product source files under `src/` at 1000 lines or less.
- Preserve `py.typed` so the package advertises inline types.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Keep generated-doc metadata and Beans support paths aligned in `bootstrap-template.json`.
- Route Python lint through Ruff, type checking through mypy, and behavior checks through pytest.
- Use `./scripts/check` for agent verification unless debugging one tool directly.
- Keep `bootstrap-template.json` aligned with generated-project support paths and verification commands.
- Keep the sample CLI small and test-covered.
- Rename `python_uv_cli` through the bootstrap flow before turning this into a real project.
- Prefer breaking the template contract cleanly over keeping weak starter conventions.
