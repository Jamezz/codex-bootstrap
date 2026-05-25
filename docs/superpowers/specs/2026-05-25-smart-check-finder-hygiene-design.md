# Smart Check Finder Hygiene Design

Date: 2026-05-25
Status: Draft for review

## Purpose

Mac Finder copy artifacts such as `Foo 2.java`, `Bar copy.md`, and `src 2/`
create noisy, confusing repo state for agents. Codex Bootstrap should help
generated projects keep agentic coding loops clean without forcing users to
manually inspect every duplicate-looking file.

The feature belongs in `agent-smart-check`, not a standalone cleanup command.
Smart-check is already the normal inner-loop harness for selecting and running
focused verification. Repo hygiene that removes known-safe Finder copies before
tests run makes that loop faster and prevents agents from debugging stale copied
files as if they were intentional source.

## Scope

V1 adds a hygiene preflight to `tools/supermeta-check/check.py` and the
generated `scripts/agent-smart-check` command surface.

In scope:

- repo-scoped scanning from Git-visible dirty paths;
- Finder-style file and directory copy names;
- exact hash or recursive manifest comparison against a single inferred
  original sibling;
- automatic Trash for exact macOS duplicates;
- repo-local quarantine for divergent copies, ambiguous Trash fallback, and
  non-macOS exact duplicates;
- loud review-needed output before tests run when a candidate cannot be safely
  removed;
- JSON output that records all hygiene actions.

Out of scope:

- broad filesystem cleanup outside the current Git checkout;
- deduplicating arbitrary files that do not look like Finder copies;
- mutating tracked committed files;
- chasing symlinks while comparing copied directories;
- integrating with external cleanup daemons or background watchers.

## Command Contract

Existing smart-check commands continue to work:

```bash
./scripts/agent-smart-check
./scripts/agent-smart-check --plan-only
./scripts/agent-smart-check --json
./scripts/agent-smart-check --full
./scripts/agent-smart-check --fast-only
```

New flags:

```bash
./scripts/agent-smart-check --no-hygiene
./scripts/agent-smart-check --hygiene-only
```

`--no-hygiene` preserves the current lane-selection and execution behavior.

`--hygiene-only` runs the hygiene preflight, prints or emits its result, and
does not select or execute verification lanes.

`--plan-only` never mutates files. It reports hygiene actions that would be
taken and then prints the selected verification lanes.

## Architecture

Smart-check gains a preflight phase before lane selection:

1. Load check policy.
2. Detect changed files from explicit `--changed`, `--since`, or Git status.
3. Run hygiene preflight unless `--no-hygiene`.
4. Stop early if hygiene found review-needed items.
5. Select lanes from the updated changed-file set.
6. Execute selected lanes unless `--plan-only` or `--hygiene-only`.

The implementation should stay inside `tools/supermeta-check/check.py` for V1
unless it becomes large enough to justify a focused helper module. The code
should use small internal data shapes:

- `HygieneConfig`: enabled state, quarantine path, Trash policy, candidate
  patterns.
- `FinderCopyCandidate`: duplicate path, inferred original path, candidate kind,
  and confidence.
- `HygieneAction`: action type, reason, original path, duplicate path, and
  destination path when relevant.
- `scan_hygiene(root, changed_files)`: finds candidate copy files and
  directories from dirty paths.
- `classify_hygiene_candidate(...)`: hashes files or creates recursive directory
  manifests.
- `apply_hygiene_actions(...)`: applies mutations only when not `--plan-only`.
- `write_quarantine_manifest(...)`: records review evidence.

## Matching Rules

V1 recognizes conservative Finder-copy forms:

- `name 2.ext`;
- `name 3.ext` and higher numbered variants;
- `name copy.ext`;
- the same suffix forms for directories.

The inferred original must be exactly one plausible sibling. If the tool cannot
infer one original, it reports the candidate and leaves it in place.

The preflight only mutates files or directories that are untracked or newly
added duplicate candidates. It must not mutate normal tracked committed files.

Directory comparison uses a recursive manifest of relative paths, file sizes,
and file hashes. It skips symlink traversal and records symlinks as review
evidence rather than following them.

The scanner skips `.git/`, `.codex-bootstrap/cleanup-quarantine/`, build
directories, dependency directories, and ignored files unless Git status reports
the path as explicitly dirty.

## Action Policy

For files:

- If the duplicate and inferred original have identical hashes, move the
  duplicate to Trash on macOS and record a `trash` action.
- If hashes differ, move the duplicate to
  `.codex-bootstrap/cleanup-quarantine/<run-id>/...`, write a manifest, record a
  `quarantine` action, and stop before tests with a review-needed exit code.
- If no single original exists, record a `report` action and stop before tests.

For directories:

- If recursive manifests match exactly, move the duplicate directory to Trash on
  macOS and record a `trash` action.
- If manifests differ, quarantine the duplicate directory, write the manifest
  diff, record a `quarantine` action, and stop before tests.
- If no single original exists, record a `report` action and stop before tests.

If macOS Trash is unavailable, exact duplicates fall back to quarantine with a
clear reason. On non-macOS platforms, exact duplicates quarantine instead of
pretending to have Finder Trash semantics.

Quarantine paths use a run identifier and a short hash to avoid collisions.
Generated projects should ignore `.codex-bootstrap/cleanup-quarantine/`.

## Output and Exit Codes

Human output stays short and explicit:

```text
agent-smart-check: hygiene trashed exact duplicate src/App 2.java
agent-smart-check: hygiene quarantined divergent duplicate src/App 2.java
  original: src/App.java
  review: .codex-bootstrap/cleanup-quarantine/20260525T120000Z-a1b2c3d4/manifest.json
agent-smart-check: hygiene needs review; verification skipped
```

JSON output includes:

- `hygiene.enabled`;
- `hygiene.reviewNeeded`;
- `hygiene.actions`;
- each action's type, reason, original path, duplicate path, destination path,
  and manifest path when available.

Exit codes:

- `0`: hygiene passed and selected verification passed, or `--hygiene-only`
  found only handled exact matches.
- `2`: smart-check policy, argument, or tool errors.
- `3`: hygiene found review-needed candidates and skipped verification.
- existing command failure codes remain unchanged for verification failures.

## Testing

Focused tests belong in `tools/supermeta-check/check_test.py`.

Coverage should include:

- exact duplicate file is planned without mutation under `--plan-only`;
- exact duplicate file is moved to Trash on macOS when Trash is available;
- exact duplicate file falls back to quarantine outside macOS or when Trash is
  unavailable;
- divergent duplicate file is quarantined and blocks verification with exit
  code `3`;
- exact duplicate directory uses recursive manifest equality;
- divergent duplicate directory writes a manifest diff;
- ambiguous candidates report only and block verification;
- `--json` includes hygiene actions and review-needed status;
- `--no-hygiene` preserves current smart-check behavior;
- `--hygiene-only` runs no verification commands;
- generated-project manifests and docs copy the updated helper and ignore the
  quarantine directory.

## Generated Project Updates

All templates that copy `tools/supermeta-check` should receive the updated
smart-check behavior through their existing support-path declarations.

Generated docs should describe hygiene as part of the velocity loop. They should
make the mutation boundary explicit: exact duplicates are cleaned automatically,
divergent duplicates are quarantined for agent review, and ambiguous candidates
are reported without movement.

The generated ignore set should include:

```text
.codex-bootstrap/cleanup-quarantine/
```

## Risks

The primary risk is deleting or moving an intentional file that happens to look
like a Finder copy. V1 mitigates this by requiring a single inferred original,
mutating only untracked or newly added duplicate candidates, using exact hashes
or manifests for automatic cleanup, and using quarantine or report-only behavior
for every uncertain case.

The second risk is hiding a useful user edit inside a duplicate copy. Divergent
content is never trashed; it is quarantined with a manifest and blocks
verification until an agent reviews it.

The third risk is making smart-check feel surprising because it mutates before
tests. The output and JSON payload must state exactly what moved and why, and
`--no-hygiene` remains available for raw verification.
