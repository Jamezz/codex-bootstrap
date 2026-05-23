# Supermeta Bootstrap Sync

`bootstrap_sync.py` is copied into generated projects and updates only Codex
Bootstrap managed files and managed regions.

Use dry-run first:

```bash
./scripts/agent-bootstrap sync --dry-run
```

Apply when the plan has no conflicts:

```bash
./scripts/agent-bootstrap sync --apply
```
