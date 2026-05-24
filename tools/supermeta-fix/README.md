# Supermeta Fix Loop

`fix.py` wraps a command, captures combined output, classifies common failures, and prints next diagnostic actions.

```bash
./scripts/agent-fix-loop -- ./scripts/agent-smart-check
./scripts/agent-fix-loop --max-attempts 2 -- ./scripts/check
./scripts/agent-fix-loop --timeout 600 --run-diagnostics --max-attempts 2 -- ./scripts/agent-smart-check
```

The last captured output is written to `.codex-bootstrap/fix-loop/last.log`. JSON output includes attempt count, evidence lines, diagnostics, and the log path.

V1 does not edit source, generated files, or lockfiles. It only captures output, classifies known failure shapes, and may run read-only diagnostics between failed attempts.
