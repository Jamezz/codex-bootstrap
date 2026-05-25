# Supermeta Bootstrap Sync

`bootstrap_sync.py` is copied into generated projects and updates only Codex
Bootstrap managed files and managed regions.

`bootstrap_adopt.py` seeds the same managed control plane into an existing
repository without rewriting product source. Run it through the catalog wrapper:

```bash
./scripts/agent-bootstrap adopt --target /path/to/existing-repo --name existing-repo
./scripts/agent-bootstrap adopt --target /path/to/existing-repo --name existing-repo --apply
```

Pass one or more `--verification-command` values for large existing repos so the
generated full smart-check lane points at the repository's real verification
entrypoint.

Use dry-run first:

```bash
./scripts/agent-bootstrap sync --dry-run
```

When testing from a local Codex Bootstrap checkout, `--source-dir` records that checkout's current branch as the next `source.ref`. Use `--source-ref <ref>` to override it explicitly; for remote syncs, the override also selects the ref to fetch.

If an older generated sync runner applied a beta source dir but left `.codex-bootstrap/sync.json` pointing at `main`, rerun the new helper with the branch override:

```bash
./scripts/agent-bootstrap sync --apply --allow-dirty --source-ref codex/branch-name
./scripts/agent-bootstrap sync --dry-run --allow-dirty --source-ref codex/branch-name
```

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
