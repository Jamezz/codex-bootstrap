# Agent Nag System Design

Date: 2026-05-23
Status: Approved design

## Purpose

Generated Codex Bootstrap projects should be able to remind agents about project hygiene and follow-up work at the moments where agents are most likely to forget: session start, before a wrapped command, after a wrapped command, after sync, and before handoff.

The immediate use case is upstream bootstrap update awareness. The broader product shape is a generic advisory nag system that future generated-project tools can hook into. It should be able to say "a newer bootstrap version is available" or "wrapped execution completed; run the backlog/context command before handoff" without hard-coding those behaviors into every wrapper.

V1 should make nags visible, configurable, throttleable, and safe. It should not turn generated projects into a background-managed environment or make wrappers hide the real result of the command they ran.

## Scope

V1 adds a shared generated-project nag engine:

- Unix entrypoint: `scripts/agent-nag`.
- Windows PowerShell entrypoint: `scripts/agent-nag.ps1`.
- Shared Python implementation: `tools/supermeta-nag/nag.py`.
- Managed default policy: `.codex-bootstrap/nags.json`.
- Local override policy: `.codex-bootstrap/nags.local.json`.
- Local state: `.codex-bootstrap/nag-state.json`.
- Hook calls from wrapper commands that own a meaningful lifecycle event.
- Generated README, `AGENTS.md`, and operations snippets.
- Template manifest support paths and sync-contract entries for every starter.
- Test coverage for policy parsing, hook evaluation, cadence, state writes, update checks, wrapper failure isolation, generated metadata, and docs.

The first hook producer should be `agent-coord run` because it already owns wrapped execution. Bootstrap sync should become a nag action rather than a separate one-off update warning.

## Non-Goals

- Do not start a background daemon.
- Do not apply bootstrap updates automatically.
- Do not run arbitrary follow-up commands automatically by default.
- Do not let nag failures change a wrapped command's exit code.
- Do not require network access for normal checks.
- Do not make normal `scripts/check` commands block on nag state.
- Do not replace Beans, Beads, task diagnostics, coordination, or sync tools.
- Do not implement a general workflow engine, scheduler, or notification service in V1.
- Do not add adoption for old generated projects in this design. Adoption can be handled through the bootstrap sync adoption story later.

## Architecture

Each generated project receives a small advisory policy layer:

```text
scripts/
  agent-nag
  agent-nag.ps1
tools/
  supermeta-nag/
    __init__.py
    nag.py
    nag_test.py
    README.md
.codex-bootstrap/
  nags.json
  nags.local.json
  nag-state.json
```

`nags.json` is generated and managed by bootstrap sync. It contains default reminders that every generated project should inherit. `nags.local.json` is intentionally not managed by sync; downstream projects can add, disable, or tune reminders without conflicting with upstream updates.

`nag-state.json` is local runtime state. It stores last-shown times, snoozes, acknowledgements, last update-check results, and command failure metadata. State is written atomically and should be ignored by sync ownership checks.

The nag engine is stdlib-only Python. It reads default policy, overlays local policy, evaluates hook context, updates state when a nag is shown or checked, and prints short agent-facing reminders.

## Hook Model

Wrappers and agents call hooks explicitly:

```bash
./scripts/agent-nag run-hook session-start
./scripts/agent-nag run-hook pre-run --wrapper agent-coord --command "./scripts/check"
./scripts/agent-nag run-hook post-run --wrapper agent-coord --exit-code 0 --command "./scripts/check"
./scripts/agent-nag run-hook post-success --wrapper agent-coord --command "./scripts/check"
./scripts/agent-nag run-hook post-failure --wrapper agent-coord --exit-code 1 --command "./scripts/check"
./scripts/agent-nag run-hook post-sync-apply
./scripts/agent-nag run-hook pre-handoff
```

PowerShell wrappers expose the same commands:

```powershell
.\scripts\agent-nag.ps1 run-hook post-run --wrapper agent-coord --exit-code 0 --command ".\scripts\check.ps1"
```

V1 hook names:

- `session-start`: advisory check at the start of an agent session.
- `pre-run`: before a wrapper starts child execution.
- `post-run`: after a wrapper finishes child execution, regardless of exit code.
- `post-success`: after a wrapped command exits with status 0.
- `post-failure`: after a wrapped command exits non-zero.
- `post-sync-apply`: after bootstrap sync applies managed updates.
- `pre-handoff`: before an agent reports work as complete.

Hook context is simple key-value data. V1 should support:

- `wrapper`
- `command`
- `exitCode`
- `templateId`
- `sourceRepository`
- `sourceRef`
- `sourceCommit`

Template and source fields are read from `.codex-bootstrap/sync.json` when present.

## Policy Contract

Managed default policy uses JSON:

```json
{
  "schemaVersion": 1,
  "nags": [
    {
      "id": "bootstrap-update-check",
      "enabled": true,
      "hook": "session-start",
      "cadence": "24h",
      "action": "check-bootstrap-update",
      "message": "A newer Codex Bootstrap version is available. Run sync when convenient."
    },
    {
      "id": "post-run-backlog-check",
      "enabled": true,
      "hook": "post-run",
      "when": {
        "exitCode": 0
      },
      "cadence": "per-run",
      "action": "suggest-command",
      "message": "Wrapped execution completed. Refresh task context before handoff.",
      "commands": [
        ["./scripts/agent-beans", "check"]
      ]
    },
    {
      "id": "post-failure-diagnostics",
      "enabled": true,
      "hook": "post-failure",
      "cadence": "per-run",
      "action": "suggest-command",
      "message": "Command failed. Inspect task state before retrying.",
      "commands": [
        ["./scripts/agent-task", "ps"],
        ["./scripts/agent-beans", "list", "--ready"]
      ]
    }
  ]
}
```

The command list is intentionally generic. A future project can replace or extend it with `beads`, `beans`, a repo-specific script, or another CLI without changing wrapper code.

Local overrides use the same shape and merge by `id`. Rules:

- `enabled: false` disables a managed nag.
- A local nag with a new `id` adds a downstream-only reminder.
- A local nag with an existing `id` overrides explicit fields and inherits omitted fields.
- Managed policy must remain valid without the local file.
- Invalid local policy should be reported as a warning and ignored; invalid managed policy is a generated-project contract failure.

## Actions

V1 supports these actions:

- `message`: print the configured message.
- `suggest-command`: print the message plus one or more suggested commands.
- `check-bootstrap-update`: compare the synced upstream commit with the current upstream ref and print an upgrade reminder only when a newer commit is available.

`check-bootstrap-update` behavior:

- Read `.codex-bootstrap/sync.json`.
- Use `git ls-remote <source.repository> <source.ref>` to resolve the latest commit.
- Compare the latest commit with `source.commit`.
- On a newer commit, print a concise notice with current commit, latest commit, and suggested sync commands.
- On no update, print nothing during hook-triggered quiet checks.
- On network, Git, or metadata failure, print nothing by default and record the failure in nag state.
- With `--verbose`, print why the update check could not run.

Suggested update output:

```text
agent-nag: bootstrap-update-check
  A newer Codex Bootstrap version is available.
  current: 0123456789abcdef0123456789abcdef01234567
  latest:  89abcdef0123456789abcdef0123456789abcdef
  Suggested:
    ./scripts/agent-bootstrap sync --dry-run
    ./scripts/agent-bootstrap sync --apply
```

Nags are advisory. The engine prints reminders and exits 0 unless command usage or managed policy is invalid.

## Cadence And State

Supported cadences:

- `per-run`: show every time the hook matches.
- `once`: show until acknowledged, then stay quiet.
- duration strings such as `1h`, `24h`, and `7d`.

State file shape:

```json
{
  "schemaVersion": 1,
  "nags": {
    "bootstrap-update-check": {
      "lastShownAt": "2026-05-23T20:00:00Z",
      "lastCheckedAt": "2026-05-23T20:00:00Z",
      "lastSeenValue": "89abcdef0123456789abcdef0123456789abcdef",
      "snoozedUntil": null,
      "acknowledged": false
    }
  }
}
```

State rules:

- Last-shown timestamps are updated only when a nag prints.
- Last-checked timestamps may update when an action performs a quiet check.
- Snoozed nags do not print until the snooze expires.
- Acknowledged `once` nags do not print again unless policy changes the nag id.
- State writes are atomic and tolerate missing parent directories.
- Corrupt state is moved aside to a `.corrupt` file and rebuilt from empty state.

## Commands

Primary command:

```bash
./scripts/agent-nag run-hook <hook> [context flags]
```

Management commands:

```bash
./scripts/agent-nag status
./scripts/agent-nag list
./scripts/agent-nag ack <nag-id>
./scripts/agent-nag snooze <nag-id> --for 7d
./scripts/agent-nag reset <nag-id>
./scripts/agent-nag check-updates
```

`check-updates` is a convenience alias for the bootstrap update action. It should support:

```bash
./scripts/agent-nag check-updates --quiet
./scripts/agent-nag check-updates --verbose
```

For compatibility with the sync wrapper, `agent-bootstrap` may expose:

```bash
./scripts/agent-bootstrap check-updates
```

That command should delegate to `agent-nag check-updates` when the nag engine is present. The source of truth remains the nag policy.

## Wrapper Integration

V1 integration should start with `agent-coord run`:

1. Run `agent-nag run-hook pre-run --wrapper agent-coord --command <child-command>`.
2. Acquire leases and run the child command as today.
3. Capture the child exit code.
4. Run `agent-nag run-hook post-run --wrapper agent-coord --exit-code <code> --command <child-command>`.
5. If the code is 0, run `post-success`.
6. If the code is non-zero, run `post-failure`.
7. Release leases and return the original child exit code.

Nag hook failures must not replace the child exit code. If a hook fails because Python is missing, policy is invalid, or local files are corrupt, the wrapper should print the nag failure to stderr and continue returning the child result.

Later wrappers can adopt the same hooks:

- `agent-bootstrap sync --apply`: `post-sync-apply`.
- Language check wrappers: `pre-run`, `post-run`, `post-success`, `post-failure`.
- Human handoff scripts, if added later: `pre-handoff`.

## Generated Contract

Every runnable template should copy:

- `scripts/agent-nag`
- `scripts/agent-nag.ps1`
- `tools/supermeta-nag/`

Every runnable template should generate:

- `.codex-bootstrap/nags.json`
- `.codex-bootstrap/nags.local.json` as an empty valid local policy
- generated README and `AGENTS.md` sections explaining hook behavior, snooze, ack, and local overrides

Template manifests should add an `agent-nags` sync managed set:

```json
{
  "id": "agent-nags",
  "description": "Agent reminder policy, nag wrappers, and hook implementation.",
  "files": [
    { "path": "scripts/agent-nag", "mode": "whole-file" },
    { "path": "scripts/agent-nag.ps1", "mode": "whole-file" },
    { "path": "tools/supermeta-nag/nag.py", "mode": "whole-file" },
    { "path": "tools/supermeta-nag/nag_test.py", "mode": "whole-file" },
    { "path": "tools/supermeta-nag/README.md", "mode": "whole-file" },
    { "path": ".codex-bootstrap/nags.json", "mode": "whole-file" }
  ],
  "regions": [
    { "path": "README.md", "id": "generated-docs/agent-nags" },
    { "path": "AGENTS.md", "id": "generated-docs/agent-nags" },
    { "path": "docs/OPERATIONS.md", "id": "generated-docs/agent-nags" }
  ]
}
```

`nags.local.json` and `nag-state.json` are intentionally not managed sync targets.

Generated `AGENTS.md` should tell agents:

- Run `./scripts/agent-nag run-hook session-start` near the start of substantial work.
- Treat nags as advisory unless the user or repo policy says otherwise.
- Do not let a nag recommendation overwrite the real result of a build, test, or sync command.
- Use `ack` or `snooze` for noisy reminders instead of deleting managed policy.
- Put repo-specific reminders in `.codex-bootstrap/nags.local.json`.

## Error Handling

Exit behavior:

- Valid hook evaluation exits 0 whether or not a nag is printed.
- Invalid command usage exits 2.
- Invalid managed policy exits 2.
- Invalid local override policy warns and continues with managed policy.
- Quiet update-check failures exit 0 and record the failure.
- Verbose update-check failures exit 1 after explaining the failure.

Wrapper behavior:

- Wrapper hook failures are non-fatal.
- Wrapped command exit code is preserved.
- Hook output should be short and prefixed with `agent-nag:` so it is easy to scan in logs.
- Repeated reminders should respect cadence and snooze state.

## Testing

Add focused unit tests under `tools/supermeta-nag/nag_test.py`:

- loads managed policy;
- merges local overrides by id;
- rejects invalid managed policy;
- warns and ignores invalid local policy;
- evaluates `when.exitCode`;
- enforces `per-run`, `once`, and duration cadence;
- writes state atomically;
- moves corrupt state aside;
- prints suggested commands;
- runs quiet and verbose bootstrap update checks with mocked `git ls-remote`;
- does not print update notices when commits match;
- prints update notices when upstream moved.

Add integration tests around `agent-coord run`:

- invokes `pre-run` and `post-run` hooks;
- invokes `post-success` on status 0;
- invokes `post-failure` on non-zero status;
- returns the child exit code when nag hooks succeed;
- returns the child exit code when nag hooks fail.

Add bootstrap generator tests:

- generated projects include nag wrappers, implementation, default policy, and docs;
- `agent-nags` is present in template sync contracts;
- `.codex-bootstrap/nags.local.json` and `nag-state.json` are not managed sync targets;
- generated `AGENTS.md`, README, and operations docs contain managed nag regions.

Verification commands:

```bash
python3 -m unittest discover -s tools/supermeta-nag -p '*_test.py'
python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
python3 -m unittest discover -s tools/pages -p '*_test.py'
```

Template checks remain the same as the generated starter contract requires.
