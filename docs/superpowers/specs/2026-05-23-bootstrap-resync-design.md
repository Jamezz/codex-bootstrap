# Bootstrap Resync Design

Date: 2026-05-23
Status: Approved design

## Purpose

Downstream projects created from Codex Bootstrap need a stable way to pull later bootstrap improvements without rerunning the destructive launcher or manually rediscovering every template contract change.

The current bootstrap flow intentionally creates a standalone project: it stages one template, rewrites project identity, removes catalog machinery, deletes cloned Git metadata, initializes fresh Git, and leaves no upstream remote. Resync is therefore a new generated-project product surface, not a small extension of `./bootstrap`.

V1 should make future bootstrap features practical to adopt while staying honest about project ownership. It should update bootstrap-owned files and explicitly managed regions, surface risky changes as migration notes, and avoid pretending arbitrary application source can be safely merged.

## Scope

V1 adds a managed-file and managed-region resync contract for newly generated projects.

The contract covers:

- generated metadata under `.codex-bootstrap/`;
- a repo-local `scripts/agent-bootstrap` and `scripts/agent-bootstrap.ps1` sync entrypoint;
- template manifest metadata that declares syncable managed sets;
- whole-file updates for bootstrap-owned support files;
- managed-region updates for selected generated sections inside otherwise project-owned files;
- dry-run and apply flows with conflict reporting;
- generated docs and agent instructions for the resync workflow;
- test coverage for metadata generation, dry-run behavior, managed updates, conflicts, and docs.

## Non-Goals

- Do not rerun the destructive launcher inside an existing downstream project.
- Do not keep the generated project connected to the bootstrap repository as a Git remote.
- Do not blindly merge arbitrary files under `src/` or `tests/`.
- Do not implement adoption for old generated projects in V1. Adoption should be a separate explicit command because older projects lack known baseline hashes and managed-region state.
- Do not auto-apply human migrations. The sync command should surface migration notes and stop where the edit is not mechanically safe.

## Architecture

Generated projects receive a small bootstrap control plane:

- `.codex-bootstrap/sync.json`: durable sync state.
- `.codex-bootstrap/reports/`: JSON reports from apply runs.
- `scripts/agent-bootstrap`: Unix entrypoint for dry-run and apply.
- `scripts/agent-bootstrap.ps1`: Windows PowerShell entrypoint with equivalent behavior.
- `tools/supermeta-bootstrap/`: shared implementation copied from the catalog.

The sync implementation fetches or clones the configured bootstrap source into a temporary directory, checks out the requested ref, regenerates the same template with the downstream project identity, and compares that generated tree against the current downstream checkout using the recorded sync state.

The generated tree is only a comparison input. The downstream checkout is updated through declared managed sets, never by replacing the whole project.

## Metadata Contract

Every sync-capable generated project should contain `.codex-bootstrap/sync.json`:

```json
{
  "schemaVersion": 1,
  "source": {
    "repository": "https://github.com/Jamezz/codex-bootstrap.git",
    "ref": "main",
    "commit": "0123456789abcdef0123456789abcdef01234567"
  },
  "template": {
    "id": "java-gradle-cli",
    "contractVersion": 1
  },
  "identity": {
    "projectName": "my-service",
    "javaPackage": "com.acme.myservice"
  },
  "managedSets": [
    "agent-scripts",
    "supermeta-tools",
    "generated-docs",
    "language-checks"
  ],
  "optOut": [],
  "managedFiles": {},
  "managedRegions": {}
}
```

Required semantics:

- `schemaVersion` gates parser behavior and future migrations.
- `source.repository` and `source.ref` define where sync fetches updates from.
- `source.commit` records the upstream commit last applied.
- `template.id` identifies the template to regenerate.
- `template.contractVersion` records the template sync contract version last applied.
- `identity` stores bootstrap inputs needed to regenerate the template. Java includes `javaPackage`; other templates only need `projectName` in V1.
- `managedSets` records the sets accepted when the project was generated or later opted into.
- `optOut` records intentionally disabled managed sets or targets.
- `managedFiles` records hashes for whole-file managed targets.
- `managedRegions` records hashes and marker metadata for managed regions.

Resync should refuse to run when `.codex-bootstrap/sync.json` is missing. A future `adopt` command can create this file for older projects, but that is not part of V1.

Paths in sync metadata are slash-normalized paths relative to the project root. Content hashes are SHA-256 hashes over the exact UTF-8 file bytes for whole files and the exact region body bytes between markers for managed regions.

## Manifest Contract

Template manifests should grow a `syncContract` section. The manifest remains the source of truth for what a template owns during resync.

Example shape:

```json
{
  "syncContract": {
    "version": 1,
    "managedSets": [
      {
        "id": "agent-scripts",
        "description": "Agent wrapper scripts and bootstrap sync entrypoints.",
        "files": [
          {
            "path": "scripts/agent-bootstrap",
            "mode": "whole-file"
          },
          {
            "path": "scripts/agent-bootstrap.ps1",
            "mode": "whole-file"
          }
        ]
      }
    ],
    "verificationCommands": [
      "./scripts/agent-bootstrap sync --dry-run",
      "./scripts/check"
    ],
    "migrationNotes": []
  }
}
```

Managed sets are named units that users and downstream agents can reason about. V1 should define these shared set names:

- `agent-scripts`: `scripts/agent-*` wrappers, including bootstrap sync wrappers.
- `supermeta-tools`: copied `tools/supermeta-*` support packages.
- `generated-docs`: generated docs and generated sections in `README.md`, `AGENTS.md`, and `docs/`.
- `language-checks`: language-specific check wiring, rule configs, and verification command snippets.

Templates may add template-specific managed sets when the name is clear and documented.

## Managed Ownership

V1 supports two update modes.

### Whole-File Managed Targets

Whole-file targets are files owned by bootstrap. Examples include `scripts/agent-gradle`, `scripts/agent-task`, `scripts/agent-bootstrap`, and `tools/supermeta-task/task.py`.

For each target, sync stores the hash of the last generated content. During apply:

- if the downstream file still matches the recorded hash, replace it with the newly generated file;
- if the downstream file differs from the recorded hash, mark the target conflicted and leave it unchanged;
- if the downstream file is missing, recreate it only when the set is still enabled;
- if an untracked file would be overwritten, mark a conflict and leave it unchanged.

### Managed Regions

Managed regions are explicit generated sections inside otherwise project-owned files. They use stable comments appropriate for the file format.

Markdown example:

```markdown
<!-- codex-bootstrap:begin generated-docs/verification -->
Generated verification commands live here.
<!-- codex-bootstrap:end generated-docs/verification -->
```

Properties example:

```properties
# codex-bootstrap:begin language-checks/java-baselines
slf4jVersion=2.0.17
logbackVersion=1.5.32
# codex-bootstrap:end language-checks/java-baselines
```

During apply:

- both begin and end markers must exist exactly once;
- the current region content must match the recorded hash before replacement;
- missing, duplicated, nested, or modified regions are conflicts;
- content outside markers is never changed.

Managed regions are the only V1 mechanism allowed to update selected starter runtime helpers or dependency baselines inside files that a downstream project may otherwise own.

## Command Behavior

Primary command:

```bash
./scripts/agent-bootstrap sync --dry-run
./scripts/agent-bootstrap sync --apply
```

PowerShell equivalents:

```powershell
.\scripts\agent-bootstrap.ps1 sync --dry-run
.\scripts\agent-bootstrap.ps1 sync --apply
```

Default behavior should be dry-run. A plain `sync` should behave like `sync --dry-run`.

Dry-run prints:

- configured source repository and ref;
- current synced commit and candidate upstream commit;
- template id and contract version movement;
- managed sets enabled, disabled, added, or removed;
- whole files that would update;
- managed regions that would update;
- conflicts with file paths and reasons;
- migration notes from skipped or changed contracts;
- verification commands to run after apply.

Apply behavior:

- require a Git worktree;
- require a clean worktree unless `--allow-dirty` is passed;
- never overwrite untracked files;
- apply only non-conflicted managed updates;
- write `.codex-bootstrap/reports/<timestamp>.json`;
- update `.codex-bootstrap/sync.json` with the new commit, contract version, hashes, and verification commands only after successful writes.

If dry-run finds conflicts, apply should fail unless the conflicting managed targets are explicitly opted out or resolved.

## Generated Contract

New bootstrap output should include:

- `.codex-bootstrap/sync.json`;
- `.codex-bootstrap/reports/.gitignore`;
- `scripts/agent-bootstrap`;
- `scripts/agent-bootstrap.ps1`;
- `tools/supermeta-bootstrap/`;
- generated README and `AGENTS.md` sections documenting dry-run, apply, conflicts, and verification.

Generated `AGENTS.md` should tell agents:

- run `./scripts/agent-bootstrap sync --dry-run` before applying bootstrap updates;
- inspect conflicts instead of forcing over local edits;
- run `./scripts/agent-bootstrap sync --apply` only for managed updates;
- run the verification commands printed by sync;
- update downstream `CHANGELOG.md` when the downstream repo has one and the sync changes merge-relevant behavior.

The existing destructive bootstrap path remains the initial creation flow. It gains sync metadata and support paths, but it does not preserve the bootstrap Git remote.

## Pages And Installer

`tools/pages/build_pages.py` should expose sync-capable contract metadata in `templates.json` so installers and future catalog UIs can show whether a template supports resync.

The Pages installer should continue to clone the bootstrap repo, run `./bootstrap`, and move the generated project into place. The generated project then carries the sync contract for future updates.

Installer flags should not grow sync behavior in V1. Sync belongs inside the generated project after creation.

## Error Handling

Sync errors should be explicit and actionable:

- missing `.codex-bootstrap/sync.json`: refuse and suggest future adoption workflow;
- unsupported schema version: refuse and report the supported range;
- unknown template id: refuse and show configured source/ref;
- missing managed target in regenerated template: report as a contract conflict;
- dirty worktree: refuse unless `--allow-dirty`;
- untracked overwrite risk: refuse the target;
- hash mismatch: conflict, not overwrite;
- marker mismatch: conflict, not overwrite;
- fetch or checkout failure: report the source repository and ref.

Exit codes:

- `0`: dry-run or apply completed with no conflicts.
- `1`: conflicts found or apply refused for project state.
- `2`: invalid command usage or invalid sync metadata.

## Testing

Add focused tests around the new sync contract:

- bootstrap smoke output includes `.codex-bootstrap/sync.json`, `scripts/agent-bootstrap`, `scripts/agent-bootstrap.ps1`, and `tools/supermeta-bootstrap`;
- generated sync metadata records source repository, source ref, template id, project identity, managed sets, and initial hashes;
- dry-run with no upstream changes exits cleanly and reports no changes;
- whole-file update applies when the downstream file still matches the recorded hash;
- whole-file update conflicts when the downstream file was edited;
- whole-file update refuses to overwrite an untracked file;
- managed-region update applies when markers and recorded hashes match;
- missing marker conflicts;
- duplicated marker conflicts;
- edited managed-region content conflicts;
- apply writes a report and updates sync metadata after successful writes;
- generated README and `AGENTS.md` document the sync workflow;
- Pages metadata includes sync contract fields;
- PowerShell wrapper text is copied and referenced by generated docs.

Run these verification commands after implementation:

```sh
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
python3 -m unittest discover -s tools/pages -p '*_test.py'
python3 -m unittest discover -s tools/supermeta-bootstrap -p '*_test.py'
python3 -m unittest discover -s tools -p '*_test.py'
```

Template-specific verification should still run when a sync contract change affects a language starter.

## Future Work

Future iterations can add:

- `./scripts/agent-bootstrap adopt` for older generated projects;
- opt-in new managed sets during sync;
- signed or checksum-verified Pages metadata;
- richer changelog rendering from upstream bootstrap releases;
- a machine-readable migration-note catalog for risky human edits.
