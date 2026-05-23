# Changelog

This file is the merge ledger for Codex Bootstrap. Future agents syncing a
long-running branch to `main` should read the entries after their branch point,
then merge the affected launcher, template, generated-project, Pages, CI, and
verification surfaces intentionally.

## How To Use This

Add one entry for every meaningful repo change. Keep entries compact, but make
the merge impact obvious enough that another agent can reconcile conflicts
without rediscovering the whole change.

Each entry should cover:

- what changed;
- which surfaces moved, such as `tools/bootstrap/`, `templates/<name>/`,
  `tools/pages/`, `site/`, `.github/`, `scripts/`, or `tools/supermeta-*`;
- generated-project contract changes, including docs, Beans, scripts,
  manifest fields, or verification commands;
- compatibility breaks or migration notes;
- verification commands that passed.

Use these buckets inside dated entries when they help:

- `Launcher`
- `Templates`
- `Generated Contract`
- `Pages / Installer`
- `Tooling`
- `Docs`
- `Verification`
- `Merge Notes`

## Unreleased

### Generated Contract

- Added the bootstrap resync contract for newly generated projects:
  `.codex-bootstrap/sync.json`, `scripts/agent-bootstrap`,
  `scripts/agent-bootstrap.ps1`, `tools/supermeta-bootstrap/`, managed-file
  hashes, managed-region hashes, and generated sync instructions.
- Added a generated downstream-to-upstream suggestion workflow with a
  copy/paste report blob for Bootstrap-owned bugs and improvements discovered
  inside generated projects.
- Added a generated-project agent nag contract with reusable lifecycle hooks,
  bootstrap update reminders, post-run follow-up suggestions, local override
  policy, and `agent-coord run` hook integration.
- Bootstrap generation now rewrites template-owned files before copying shared
  support tools, so generated project names no longer corrupt managed
  `tools/supermeta-*` helper code or tests.
- Bootstrap sync now auto-enables newly introduced managed sets unless opted
  out or marked manual opt-in, appends missing generated doc regions/files
  during that migration, applies multiple same-file region changes
  cumulatively, and records enabled sets in sync reports and metadata.
- Generated templates now ignore `.codex-bootstrap/nag-state.json`, and the
  sync contract is version 2 with `language-checks` marked manual opt-in for
  existing repos.
- Kept the generated `agent-nags` operations region stable across the
  260e1d8-to-contract-v2 hop so older helpers do not perform multiple region
  writes against the same file during that transition.

### Pages / Installer

- Extended `templates.json` with sync capability metadata so catalog consumers
  can tell which templates support downstream resync.

### Verification

- `PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'`
- `python3 -m unittest discover -s tools/bootstrap -p '*_test.py'`
- `python3 -m unittest discover -s tools/pages -p '*_test.py'`
- `python3 -m unittest discover -s tools -p '*_test.py'`
- `./scripts/agent-gradle templates/java-gradle-cli check`
