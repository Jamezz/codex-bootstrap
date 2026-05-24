# Supermeta Bootstrap Sync

`bootstrap_sync.py` is copied into generated projects and updates only Codex
Bootstrap managed files and managed regions.

Use dry-run first:

```bash
./scripts/agent-bootstrap sync --dry-run
```

When testing from a local Codex Bootstrap checkout, `--source-dir` records that checkout's current branch as the next `source.ref`. Use `--source-ref <ref>` to override it explicitly.

Apply when the plan has no conflicts:

```bash
./scripts/agent-bootstrap sync --apply
```

## Upstream Suggestions

Generated project docs include a copy/paste report template for downstream
agents that find a Bootstrap-owned bug or improvement. Use it for starter
defaults, managed docs, agent wrappers, Supermeta tools, verification commands,
sync behavior, or managed-set contract changes.

Before handing the blob to an upstream `codex-bootstrap` agent, read
`.codex-bootstrap/sync.json` and include `./scripts/agent-bootstrap sync
--dry-run` output when the issue affects sync.
