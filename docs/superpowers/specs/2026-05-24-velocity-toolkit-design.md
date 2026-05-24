# Codex Bootstrap Velocity Toolkit Design

Date: 2026-05-24
Status: Approved design

## Purpose

Codex Bootstrap should make generated projects faster for agents to change, test,
debug, and extend. Existing starters already provide deterministic full checks,
agent coordination, task diagnostics, sync, nags, generated docs, and language
wrappers. The next leverage point is reducing the inner-loop cost of ordinary
development while keeping the full check as the final gate.

The velocity toolkit is a shared generated-project contract for practical agent
throughput. V1 ships two tools:

- `agent-smart-check`: choose and optionally run the smallest useful
  verification lane from the current file changes.
- `agent-fix-loop`: wrap a command, capture failure output, classify common
  failures, and print the next useful diagnostic actions.

The expected normal agent command becomes:

```bash
./scripts/agent-fix-loop -- ./scripts/agent-smart-check
```

`./scripts/check`, `./scripts/agent-gradle . check`, and equivalent template
full checks remain the canonical full verification gates.

## Scope

V1 adds a coherent velocity-tooling lane with these generated-project files:

```text
scripts/
  agent-smart-check
  agent-smart-check.ps1
  agent-fix-loop
  agent-fix-loop.ps1
tools/
  supermeta-check/
    check.py
    check_test.py
    README.md
  supermeta-fix/
    fix.py
    fix_test.py
    README.md
.codex-bootstrap/
  checks.json
```

The toolkit must work in the bootstrap catalog and in generated projects across
the Java Gradle CLI, Python uv CLI, TypeScript Bun CLI, TypeScript Bun MCP
server, and C# .NET CLI starters.

Future velocity tools are named now so the v1 contract has room to grow without
overloading the first implementation:

- `scripts/new`: source and test scaffolding for common project shapes.
- `agent-index`: fast local repo map for agents.
- `agent-bench`: small before/after benchmark runner.
- `agent-upgrade`: template-aware dependency upgrade helper.
- `agent-cleanup`: mechanical cleanup command.
- richer optional starter batteries such as HTTP, persistence, auth, workers,
  CLI subcommands, and MCP persistence.

V1 does not implement those future tools.

## Non-Goals

- Do not perform autonomous source edits in `agent-fix-loop`.
- Do not replace existing full verification commands.
- Do not infer a complete build graph.
- Do not start a daemon.
- Do not implement dependency upgrades.
- Do not implement benchmarking.
- Do not implement code scaffolding.
- Do not make normal checks depend on network access.
- Do not block ordinary checks on coordination state unless a configured lane
  explicitly uses `agent-coord run`.

## Architecture

The toolkit follows the existing generated-project support pattern:

- thin wrappers live under `scripts/`;
- stdlib-first Python implementations live under `tools/supermeta-*`;
- template manifests declare support paths and sync-managed files;
- generated docs explain the workflow;
- generated sync metadata makes downstream adoption mechanical.

`agent-smart-check` is the planner and optional executor. It reads changed
files, loads `.codex-bootstrap/checks.json`, merges local overrides when
present, selects matching lanes, and runs their commands unless `--plan-only`
is set.

`agent-fix-loop` is the failure wrapper. It runs a child command, captures
combined stdout and stderr into `.codex-bootstrap/fix-loop/last.log`, classifies
known failure patterns, and prints concise next actions. V1 diagnostics are
read-only or status-only.

The two tools should remain independent. `agent-smart-check` can be used alone
for quick planning or execution. `agent-fix-loop` can wrap any command, not only
`agent-smart-check`.

## Smart Check Command Contract

Primary commands:

```bash
./scripts/agent-smart-check
./scripts/agent-smart-check --since HEAD~1
./scripts/agent-smart-check --changed src/foo.py tests/test_foo.py
./scripts/agent-smart-check --plan-only
./scripts/agent-smart-check --json
./scripts/agent-smart-check --full
```

PowerShell wrappers expose the same flags:

```powershell
.\scripts\agent-smart-check.ps1 --plan-only
```

Behavior:

- Default changed-file source is Git. The tool reads staged, unstaged, and
  untracked files from Git status, using `HEAD` as the comparison point for
  tracked files.
- `--since <rev>` compares changed files against the revision.
- `--changed <paths...>` bypasses Git and is used by tests or callers that
  already know the affected paths.
- If there is no Git worktree, no changes, or invalid lane config, the tool
  falls back to the full lane.
- `--full` forces the full lane.
- Matching lanes are unioned, deduplicated, and ordered from cheapest to
  broadest.
- A lane may set `stopOnFailure`; default is `true`.
- `--plan-only` prints the selected lane plan and exits without execution.
- `--json` emits machine-readable plan and result data.
- The process returns the first failing command exit code, or `0` when all
  executed commands pass.

Human-readable output should be short:

```text
agent-smart-check: selected python-focused
  reason: Python source or tests changed
  commands:
    uv run --no-editable pytest
    ./scripts/check
```

## Checks Metadata

Generated projects receive `.codex-bootstrap/checks.json`:

```json
{
  "schemaVersion": 1,
  "templateId": "python-uv-cli",
  "lanes": [
    {
      "id": "python-focused",
      "description": "Python source or tests changed.",
      "triggers": {
        "paths": ["src/**/*.py", "tests/**/*.py", "pyproject.toml", "uv.lock"]
      },
      "commands": [
        ["uv", "run", "--no-editable", "pytest"],
        ["./scripts/check"]
      ],
      "escalatesTo": "full"
    },
    {
      "id": "full",
      "description": "Complete generated-project verification.",
      "commands": [["./scripts/check"]]
    }
  ]
}
```

Local projects may add `.codex-bootstrap/checks.local.json`. Local lanes merge
by `id`; new ids add downstream-only lanes, and existing ids override explicit
fields while inheriting omitted fields from the generated lane.

Example local lane:

```json
{
  "lanes": [
    {
      "id": "perf-sensitive",
      "triggers": {
        "paths": ["src/perf/**"]
      },
      "commands": [
        [
          "./scripts/agent-coord",
          "run",
          "--resource",
          "perf:exclusive",
          "--",
          "./scripts/check"
        ]
      ]
    }
  ],
  "schemaVersion": 1
}
```

Invalid local config should warn and be ignored. Invalid generated config is a
generated-project contract error, but `agent-smart-check` should still attempt
the full lane when it can identify the full verification command.

## Starter Lane Defaults

Java Gradle CLI:

- `java-test`: Java source or test changes run `./scripts/agent-gradle . test`.
- `java-style`: Java or Checkstyle config changes run
  `./scripts/agent-gradle . checkstyleMain checkstyleTest`.
- `full`: run `./scripts/agent-gradle . check`.

Python uv CLI:

- `python-test`: Python source or test changes run
  `uv run --no-editable pytest`.
- `python-quality`: `pyproject.toml`, `uv.lock`, source, or test changes run the
  relevant Ruff and mypy checks when available.
- `full`: run `./scripts/check`.

TypeScript Bun CLI:

- `typescript-test`: TypeScript source or test changes run Bun tests.
- `typescript-quality`: TypeScript source, test, config, or lockfile changes run
  typecheck and Biome checks when available.
- `full`: run `./scripts/check`.

TypeScript Bun MCP server:

- Same TypeScript lanes as the CLI starter.
- Protocol-affecting changes under MCP, HTTP, stdio, config, or state modules
  include MCP protocol tests through the template's existing test command.
- `full`: run `./scripts/check`.

C# .NET CLI:

- `dotnet-test`: C# source or test changes run `./scripts/agent-dotnet . test`.
- `dotnet-quality`: project, props, solution, package, or lockfile changes run
  the template check lane.
- `full`: run `./scripts/check`.

Exact command arrays should match the current template scripts at
implementation time. The design intent is that focused lanes run fast and full
lanes remain authoritative.

## Fix Loop Command Contract

Primary commands:

```bash
./scripts/agent-fix-loop -- ./scripts/agent-smart-check
./scripts/agent-fix-loop --max-attempts 2 -- ./scripts/check
```

PowerShell wrappers expose equivalent behavior:

```powershell
.\scripts\agent-fix-loop.ps1 -- .\scripts\agent-smart-check.ps1
```

Behavior:

- Run the child command and capture combined stdout and stderr to
  `.codex-bootstrap/fix-loop/last.log`.
- Preserve the child exit code unless `agent-fix-loop` usage or config is
  invalid.
- Classify common failures with deterministic regex/rule matching.
- Print a concise diagnosis and next actions.
- Optionally run configured read-only diagnostics.
- Do not modify source, generated files, lockfiles, or project state beyond the
  log file.
- `--max-attempts` may rerun the child after read-only diagnostics in v1, but it
  must not pretend a fix occurred.

V1 classifiers:

- formatter or linter failure;
- typecheck failure;
- unit test failure;
- Gradle stale compiled-class false failure;
- missing tool or dependency;
- port already in use;
- coordination or lock contention;
- timeout or likely hung process;
- generated-region or bootstrap sync conflict;
- unknown failure.

Useful read-only diagnostics include:

- `./scripts/agent-task ps`;
- language-specific task process checks such as `--match gradle`, `--match bun`,
  `--match pytest`, or `--match dotnet`;
- `./scripts/agent-gradle . --logs` for Gradle projects;
- `./scripts/agent-bootstrap sync --dry-run` for sync conflicts.

Unknown failures should print the path to `last.log` plus generic process and
log inspection commands.

## Generated Contract

Every runnable template should copy:

- `scripts/agent-smart-check`;
- `scripts/agent-smart-check.ps1`;
- `scripts/agent-fix-loop`;
- `scripts/agent-fix-loop.ps1`;
- `tools/supermeta-check/*`;
- `tools/supermeta-fix/*`.

Every runnable template should generate:

- `.codex-bootstrap/checks.json`;
- README velocity section;
- AGENTS velocity commands and rules;
- docs/OPERATIONS velocity section.

The sync contract should add a `velocity-tools` managed set. It owns:

- the new wrappers;
- `tools/supermeta-check/*`;
- `tools/supermeta-fix/*`;
- `.codex-bootstrap/checks.json`;
- generated doc regions for README, AGENTS, and docs/OPERATIONS.

Existing `scripts/check` and language wrappers remain outside this managed set
unless already managed by their existing sets.

## Error Handling

Both tools should fail clearly and conservatively:

- invalid CLI usage exits `2`;
- invalid generated config exits `2` only when no full-lane fallback is possible;
- invalid local override prints a warning and continues;
- missing Python from a wrapper exits `2`;
- missing Git falls back to full lane for smart-check;
- missing child command exits with the shell or subprocess failure code;
- read-only diagnostic failures are reported but do not replace the child exit
  code;
- log write failures are reported and return `2` because fix-loop cannot perform
  its core contract.

Machine-readable JSON output must include the selected lanes, commands, reasons,
executed command results, and failure classification when available.

## Documentation

Generated README should introduce:

```bash
./scripts/agent-smart-check --plan-only
./scripts/agent-fix-loop -- ./scripts/agent-smart-check
./scripts/check
```

Generated AGENTS should tell agents:

- use `agent-fix-loop -- agent-smart-check` for fast inner-loop verification;
- use full verification before handoff;
- do not treat a focused smart-check pass as a release gate;
- extend `.codex-bootstrap/checks.local.json` for downstream-only lanes.

Generated operations docs should explain:

- where `checks.json` and `checks.local.json` live;
- where fix-loop writes `last.log`;
- how to force the full lane;
- how to use `--json` for automation;
- how to fall back to existing full checks.

## Testing

`tools/supermeta-check/check_test.py` should cover:

- Git changed-file detection;
- `--since`;
- `--changed`;
- path trigger matching;
- lane ordering and deduplication;
- `--plan-only`;
- `--json`;
- fallback to full lane;
- command execution;
- exit-code propagation;
- local override merge;
- invalid generated config;
- invalid local override.

`tools/supermeta-fix/fix_test.py` should cover:

- child output capture to `.codex-bootstrap/fix-loop/last.log`;
- child exit-code preservation;
- formatter or linter classification;
- typecheck classification;
- unit test classification;
- Gradle stale-class classification;
- missing tool classification;
- port-busy classification;
- timeout classification;
- sync conflict classification;
- read-only diagnostic command execution;
- unknown failure fallback;
- proof that no source mutation occurs.

Bootstrap and generated-project tests should cover:

- every template copies the new wrappers and tools;
- every template generates `.codex-bootstrap/checks.json`;
- every template sync contract includes `velocity-tools`;
- generated README, AGENTS, and operations docs include velocity regions;
- Pages metadata exposes the new managed set;
- generated-project smoke runs `agent-smart-check --plan-only --json`.

## Rollout

Implementation should land in this order:

1. Add `tools/supermeta-check` and `agent-smart-check` wrappers.
2. Add `tools/supermeta-fix` and `agent-fix-loop` wrappers.
3. Add generated `.codex-bootstrap/checks.json` rendering.
4. Wire support paths and sync contracts across all templates.
5. Add generated README, AGENTS, and operations regions.
6. Update Pages metadata tests.
7. Run helper tests, bootstrap tests, Pages tests, all-tool discovery tests, and
   the Java template check.

Final verification for the implementation should include:

```bash
python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'
python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
python3 -m unittest discover -s tools/pages -p '*_test.py'
python3 -m unittest discover -s tools -p '*_test.py'
./scripts/agent-gradle templates/java-gradle-cli check
```

## Acceptance Criteria

- A generated project can run `./scripts/agent-smart-check --plan-only --json`
  without executing build tools.
- A generated project can run
  `./scripts/agent-fix-loop -- ./scripts/agent-smart-check --plan-only`.
- Template manifests and sync metadata make velocity tooling resyncable through
  the `velocity-tools` managed set.
- Focused lanes never replace the full check as the handoff gate.
- Fix-loop never mutates source or lockfiles in v1.
- Unknown failures still leave an actionable log path and diagnostic commands.
