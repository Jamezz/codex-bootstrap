# Agent Coordination Design

Date: 2026-05-23
Status: Approved design

## Purpose

Codex Bootstrap projects should give parallel agents a lightweight way to advertise what they are doing and avoid trampling shared machine resources when they choose to coordinate.

The common failure mode is not one project needing a heavyweight scheduler. It is several local agents running across different checkouts, with some doing CPU-heavy builds, Docker work, or perf tests where concurrent runs spoil measurements or waste time. The right V1 is a per-user coordination surface that works from every generated project, requires no daemon, and stays advisory unless an agent explicitly asks to serialize work.

## Scope

V1 adds a cross-template agent coordination tool:

- Unix entrypoint: `scripts/agent-coord`.
- Windows PowerShell entrypoint: `scripts/agent-coord.ps1`.
- Shared Python implementation: `tools/supermeta-agent/agent.py`.
- Shared tests and docs under `tools/supermeta-agent/`.
- Generated README, `AGENTS.md`, and operations snippets.
- Template manifest support paths and sync-contract entries for every starter.
- A per-user registry of live agents and resource leases.
- Advisory status commands by default.
- Opt-in serialized execution through explicit lease or `run` commands.
- Linux, macOS, and Windows support from day one.

## Non-Goals

- Do not start or require a background daemon.
- Do not coordinate across machines unless the user intentionally points multiple agents at a shared coordination directory.
- Do not make ordinary `scripts/check` commands block by default.
- Do not infer all resource needs from process names.
- Do not kill or pause other agents.
- Do not replace language-specific wrappers such as `agent-gradle` or `agent-dotnet`.
- Do not build a distributed lock service, queue broker, or MCP server in V1.

## Architecture

The coordination model is file-backed and stdlib-only.

Each generated project receives `scripts/agent-coord`, `scripts/agent-coord.ps1`, and `tools/supermeta-agent/`. The wrappers locate Python the same way existing support wrappers do, then invoke the shared implementation.

The implementation writes state to a per-user coordination home:

- Linux: `$XDG_STATE_HOME/codex-bootstrap/agents`, falling back to `~/.local/state/codex-bootstrap/agents`.
- macOS: `~/Library/Application Support/codex-bootstrap/agents`.
- Windows: `%LOCALAPPDATA%\CodexBootstrap\agents`.
- Override: `CODEX_AGENT_COORD_HOME`.

The coordination home contains:

```text
registry/
  <agent-id>.json
leases/
  <resource-key>.json
locks/
  registry.lock
  leases.lock
corrupt/
```

All state writes are atomic: write a temporary file in the same directory, flush it, then replace the target. Registry and lease updates are protected by an exclusive file lock. Locking uses `fcntl` on Linux/macOS and `msvcrt` on Windows, matching the existing cross-platform pattern in the Gradle harness.

## Agent Identity

Every command resolves an agent identity. Resolution order:

1. `--agent-id`
2. `CODEX_AGENT_ID`
3. `CODEX_SESSION_ID`
4. stable fallback from host, user, and cwd hash

The fallback identity should be stable across separate CLI invocations in the same checkout:

```text
<hostname>-<user>-<repo-slug>-<cwd-hash>
```

Agents running multiple independent sessions in the same checkout should set `CODEX_AGENT_ID` or pass `--agent-id` so their registry records do not overwrite each other.

Registry records are JSON:

```json
{
  "schemaVersion": 1,
  "agentId": "host-12345-hazeldisk-a1b2c3",
  "pid": 12345,
  "host": "host",
  "platform": "darwin",
  "cwd": "/Users/example/src/hazeldisk",
  "repoName": "hazeldisk",
  "templateId": "java-gradle-cli",
  "task": "perf pass",
  "tags": ["hazeldisk"],
  "resources": ["cpu:heavy", "perf"],
  "startedAt": "2026-05-23T19:00:00Z",
  "updatedAt": "2026-05-23T19:05:00Z",
  "ttlSeconds": 900
}
```

`templateId` is read from `.codex-bootstrap/sync.json` when present. Missing metadata is not an error because the tool also needs to work in catalog and legacy checkouts.

Expired registry records are ignored by status output and removed opportunistically during any mutating command.

## Command Contract

Primary commands:

```bash
./scripts/agent-coord announce --task "perf pass" --resource cpu:heavy --resource perf --tag hazeldisk
./scripts/agent-coord status
./scripts/agent-coord leave
./scripts/agent-coord acquire --resource perf:exclusive --timeout 20m
./scripts/agent-coord release --resource perf:exclusive
./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check
```

PowerShell equivalents:

```powershell
.\scripts\agent-coord.ps1 announce --task "perf pass" --resource cpu:heavy
.\scripts\agent-coord.ps1 status
.\scripts\agent-coord.ps1 run --resource perf:exclusive -- .\scripts\check.ps1
```

Command behavior:

- `announce` writes or refreshes the caller's registry record and exits.
- `status` prints live agents, live leases, stale-record cleanup notes, and resource conflicts in a human-readable table by default.
- `leave` removes the caller's registry record and releases leases held by that agent.
- `acquire` blocks until the requested resources are available or the timeout expires.
- `release` releases resources held by the caller.
- `run` announces the caller, acquires requested resources, runs the child command, refreshes heartbeats while the child is alive, releases resources on exit, and returns the child exit code.

Machine-readable output should be available through `--json` for `status`, `announce`, `acquire`, `release`, and `leave`.

## Advisory By Default

Announcing a resource does not block another agent. It only makes the agent visible in `status` output.

This is intentional. Coordination should not surprise generated-project users or make normal checks hang because another checkout is busy. Agents choose serialization only when they use `acquire` or `run`.

When `status` sees multiple live agents advertising the same resource, it should call that out as advisory contention:

```text
resource        mode       holders
cpu:heavy       advisory   3 agents advertising
perf            advisory   2 agents advertising
perf:exclusive  leased     host-12345-hazeldisk-a1b2c3
```

## Lease Semantics

A lease is a JSON file keyed by a normalized resource name:

```json
{
  "schemaVersion": 1,
  "resource": "perf:exclusive",
  "agentId": "host-12345-hazeldisk-a1b2c3",
  "pid": 12345,
  "host": "host",
  "cwd": "/Users/example/src/hazeldisk",
  "task": "perf pass",
  "acquiredAt": "2026-05-23T19:00:00Z",
  "updatedAt": "2026-05-23T19:05:00Z",
  "ttlSeconds": 900
}
```

V1 supports exclusive leases only. That keeps the implementation honest and avoids inventing partial scheduler semantics too early. Concurrency limits such as `maxConcurrent: 2` can be added later if real usage shows they are worth the extra state.

Lease rules:

- A live lease blocks another agent from acquiring the same resource.
- The owning agent can reacquire the same resource idempotently.
- Expired leases are removed before acquisition.
- `run` refreshes leases while the child process is alive.
- `release --all` releases all leases owned by the caller.
- If the child process exits because of a signal or exception, `run` still attempts release before returning.

Default lease TTL is 15 minutes. Users can override it with `--ttl 30m` or `CODEX_AGENT_COORD_TTL_SECONDS`.

## Resource Names

Resource names are slash-free, case-sensitive strings made from letters, digits, `.`, `_`, `-`, and `:`. Invalid names fail fast.

Recommended starter names:

- `perf`
- `perf:exclusive`
- `cpu:heavy`
- `memory:heavy`
- `disk:heavy`
- `network:external`
- `docker`
- `gradle-home`

The docs should recommend project-specific names for scarce local fixtures, such as `hazeldisk:perf-cluster` or `omega:local-lab`.

## Error Handling

The tool should fail clearly and conservatively:

- Missing Python exits with status 2 from the wrapper.
- Invalid command usage exits with status 2.
- Invalid resource names exit with status 2.
- Locking failures exit with status 1.
- `acquire` timeout exits with status 75 so agents can distinguish contention from test failure.
- `run` returns the child command's exit code after successful acquisition.
- Corrupt JSON records are reported, ignored for scheduling, and moved to a `corrupt/` directory when possible.
- Unavailable process inspection is not fatal because coordination is based on TTL heartbeats, not platform-specific process APIs.

Status output should name the blocking lease owner, cwd, task, age, and last heartbeat so another agent can make an informed decision.

## Generated Contract

Every runnable template should copy:

- `scripts/agent-coord`
- `scripts/agent-coord.ps1`
- `tools/supermeta-agent/agent.py`
- `tools/supermeta-agent/agent_test.py`
- `tools/supermeta-agent/README.md`

Every template `bootstrap-template.json` should include those support paths and sync-contract entries:

- Add `scripts/agent-coord` and `scripts/agent-coord.ps1` to `agent-scripts`.
- Add `tools/supermeta-agent/*` to `supermeta-tools`.
- Update generated docs sections through `tools/bootstrap/bootstrap.py`.

Generated `README.md`, `AGENTS.md`, and `docs/OPERATIONS.md` should document:

- how to announce work;
- how to inspect live agents;
- how to serialize a sensitive command with `run`;
- where state is stored on Linux, macOS, and Windows;
- how to override state location for shared coordination;
- how to recover with `leave` or TTL expiry.

## Bootstrap Repository Contract

The catalog itself should also support the tool from repo root:

```bash
./scripts/agent-coord status
./scripts/agent-coord run --resource perf:exclusive -- python3 -m unittest discover -s tools -p '*_test.py'
```

This makes the Bootstrap repo a first-class user of its own generated coordination surface.

## Testing

Add focused tests in `tools/supermeta-agent/agent_test.py`:

- platform-specific state-home resolution for Linux, macOS, Windows, and override env;
- atomic registry write and read;
- stale registry cleanup;
- `announce` updates an existing agent record;
- `leave` removes the record and owned leases;
- resource-name validation rejects unsafe names;
- exclusive lease acquisition succeeds when free;
- acquisition times out when another live agent owns the lease;
- expired leases are reclaimed;
- reentrant acquisition by the same agent succeeds;
- `run` returns the child exit code;
- `run` releases leases after success and failure;
- corrupt JSON records are ignored and reported;
- `--json` status emits stable machine-readable output.

Update existing bootstrap tests so generated projects include the new support paths, docs, wrappers, and sync-contract entries.

Run these verification commands after implementation:

```sh
python3 -m unittest discover -s tools/supermeta-agent -p '*_test.py'
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
python3 -m unittest discover -s tools -p '*_test.py'
```
