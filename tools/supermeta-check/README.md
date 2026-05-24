# Supermeta Smart Check

`check.py` selects focused verification lanes from changed files in Codex Bootstrap generated projects.

```bash
./scripts/agent-smart-check --plan-only
./scripts/agent-smart-check --since HEAD~1
./scripts/agent-smart-check --changed src/example.py tests/test_example.py
./scripts/agent-smart-check --json
./scripts/agent-smart-check --full
```

Generated policy lives in `.codex-bootstrap/checks.json`. Local override policy lives in `.codex-bootstrap/checks.local.json` and merges lanes by `id`.

Focused lanes are an inner-loop accelerator. Run the template full check before handoff.
