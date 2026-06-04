# Supermeta Smart Check

`check.py` selects focused verification lanes from changed files in Codex Bootstrap generated projects. It also runs repo-scoped Finder-copy hygiene before verification unless disabled.

```bash
./scripts/agent-smart-check --plan-only
./scripts/agent-smart-check --since HEAD~1
./scripts/agent-smart-check --changed src/example.py tests/test_example.py
./scripts/agent-smart-check --json
./scripts/agent-smart-check --full
./scripts/agent-smart-check --fast-only
./scripts/agent-smart-check --tag test
./scripts/agent-smart-check --timeout 120
./scripts/agent-smart-check --self-test
./scripts/agent-smart-check --hygiene-only
./scripts/agent-smart-check --no-hygiene
```

Generated policy lives in `.codex-bootstrap/checks.json`. Local override policy lives in `.codex-bootstrap/checks.local.json` and merges lanes by `id`.

Finder-copy hygiene scans Git-visible dirty paths for names such as `Foo 2.java`, `Foo copy.java`, and `src 2/`. Exact duplicates are moved to macOS Trash when available. Divergent or ambiguous copies are moved to `.codex-bootstrap/cleanup-quarantine/` or reported, and verification stops with exit code `3` so an agent can review the evidence.

Use `--plan-only` to see hygiene actions without mutation. Use `--hygiene-only` to clean before selecting lanes. Use `--no-hygiene` when raw verification is required.

Lanes can declare `cost`, `tags`, `requires`, lane-level `timeoutSeconds`, and per-command `timeoutSeconds`. `--self-test` validates the lane graph before a subprocess is launched, and missing `requires` fail with exit `127`.

During execution, human output reports when the file scan is complete, which lane command is running, and a 30-second still-running heartbeat for long commands.

Focused lanes are an inner-loop accelerator. Run the template full check before handoff.
