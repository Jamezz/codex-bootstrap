# Supermeta Agent Nag

`nag.py` is copied into generated projects and evaluates advisory agent reminders
from `.codex-bootstrap/nags.json` plus optional local overrides in
`.codex-bootstrap/nags.local.json`.

Run session-start checks:

```bash
./scripts/agent-nag run-hook session-start
```

Check for upstream Codex Bootstrap updates:

```bash
./scripts/agent-nag check-updates --quiet
```

Manage noisy reminders:

```bash
./scripts/agent-nag list
./scripts/agent-nag ack post-run-backlog-check
./scripts/agent-nag snooze post-run-backlog-check --for 7d
```

Nags are advisory. Hook failures must not replace the exit code of a wrapped
build, test, sync, or diagnostic command.
