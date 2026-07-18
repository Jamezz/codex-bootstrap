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
- generated-project contract changes, including docs, Beads, scripts,
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

### Beads Migration

- Replaced Beans with pinned Beads 1.1.0 wrappers, native `prime` and `ready --json` workflows, tracked JSONL seed graphs, and ignored embedded-Dolt state across every starter and existing-repo adoption.
- Added sync schema 2 and template contract 3 with the fail-closed `beans-to-beads-v1` migration, preserving issue fields, hierarchy, blockers, timestamps, tags, priorities, and archived outcomes before retiring Beans tooling.

### Generated Contract

- Java Gradle generated projects now receive the capsule-aware Supermeta Gradle
  harness, `scripts/supermeta-cache`, expanded harness diagnostics, generated
  output hygiene, and sync-managed entries for the new Gradle helper modules.
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
- Bootstrap sync now records the actual source branch when applying from
  `--source-dir`, and accepts `--source-ref` for explicit beta-branch syncs.
- `--source-ref` now selects the remote ref to fetch instead of only relabeling
  metadata, and sync plans print a follow-up dry-run command when the candidate
  ref differs from the recorded source ref.
- Bootstrap sync now refreshes managed-file hashes without conflict when a
  downstream-edited file already matches the regenerated upstream candidate.
- Generated templates now ignore `.codex-bootstrap/nag-state.json`, and the
  sync contract is version 2 with `language-checks` marked manual opt-in for
  existing repos.
- Added the velocity tooling contract for generated projects:
  `scripts/agent-smart-check`, `scripts/agent-fix-loop`, PowerShell wrappers,
  `tools/supermeta-check/`, `tools/supermeta-fix/`, generated
  `.codex-bootstrap/checks.json`, and the `velocity-tools` sync managed set.
- Extended generated smart-check lanes with `cost`, `tags`, `requires`, and
  `timeoutSeconds` metadata so agents can select cheaper lanes and fail fast on
  missing tools before subprocess launch.
- Kept the generated `agent-nags` operations region stable across the
  260e1d8-to-contract-v2 hop so older helpers do not perform multiple region
  writes against the same file during that transition.

### Pages / Installer

- Extended `templates.json` with sync capability metadata so catalog consumers
  can tell which templates support downstream resync.

### Tooling

- Upstreamed Supermeta Gradle build capsules into shared template tooling:
  capsule-local `GRADLE_USER_HOME`, build cache, logs, locks, `--status`, `--repair`,
  generated-output hygiene, strict included-build materialization, and Supermeta
  rules cache cleaning.
- Adjusted Supermeta Gradle generated-output hygiene to quarantine classpath
  duplicate outputs with size-only manifests while removing generated report and
  test-result copies without content hashing.
- Added `min_package_depth` to the JavaScript/TypeScript package-size rule so
  templates can reject files placed directly at configured source roots.
- Added focused verification lane selection and deterministic failure
  classification helpers for faster agent inner loops while keeping full checks
  as the handoff gate.
- Added smart-check `--self-test`, `--fast-only`, `--tag`, and `--timeout`
  controls, plus per-command timeout support.
- Added fix-loop command timeouts, diagnostic-aware retries, and richer JSON
  reports with attempt counts, evidence lines, diagnostics, and log paths.
- Split velocity doc and check-policy generation from
  `tools/bootstrap/bootstrap.py` into `tools/bootstrap/velocity.py`.
- Made `tools/supermeta-check` and `tools/supermeta-fix` importable so root
  `python3 -m unittest discover -s tools -p '*_test.py'` includes their tests.

### Verification

- `python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'`
- `python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'`
- `python3 -m unittest discover -s tools/supermeta-gradle -p '*_test.py'`
- `PYTHONPATH=tools/supermeta-bootstrap python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'`
- `python3 -m unittest discover -s tools/bootstrap -p '*_test.py'`
- `python3 -m unittest discover -s tools/pages -p '*_test.py'`
- `python3 -m unittest discover -s tools -p '*_test.py'`
- `./scripts/agent-gradle templates/java-gradle-cli check`
