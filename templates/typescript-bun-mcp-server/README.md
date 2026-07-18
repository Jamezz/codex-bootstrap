# TypeScript Bun MCP Server Template

This template is a compact MCP server with Bun, TypeScript, stdio, Bun-native Streamable HTTP, typed state stores, Biome, Bun tests, and a Codex-friendly verification path.
It includes first-class runtime logging through Pino with quiet text logs by default and JSON logs available through environment configuration.

It can be materialized from the catalog root with:

```bash
./bootstrap --template typescript-bun-mcp-server --name my-service
```

After materialization, the generated project is standalone and uses:

```bash
./scripts/check
bun run src/main.ts --help
```

## Prerequisites

- `bun` on PATH;
- network access on first run so Bun can install dependencies.

Bun is the package manager, runtime, and test runner for this template. Do not add npm, pnpm, or Yarn fallback paths unless the project intentionally changes package-manager strategy.

## Usage

Install locked dependencies:

```bash
bun install --frozen-lockfile
```

Run the full check lifecycle:

```bash
./scripts/check
```

Run tests:

```bash
bun test
```

Run the local stdio MCP server:

```bash
bun run src/main.ts
```

Run the HTTP MCP server:

```bash
bun run src/main.ts --transport http
```

Use the JSON file state store:

```bash
bun run src/main.ts --state file --state-file .mcp/state.json
```

Enable runtime logs:

```bash
LOG_LEVEL=info bun run src/main.ts --transport http
LOG_LEVEL=info LOG_FORMAT=json bun run src/main.ts --transport http
```

`LOG_LEVEL` accepts `trace`, `debug`, `info`, `warn`, `error`, or `off`. `LOG_FORMAT` accepts `text` or `json`. Logs always go to stderr; stdout is reserved for the stdio MCP transport.

Stuck-task diagnostics from the repository root:

```bash
./scripts/agent-task ps --match bun
./scripts/agent-task ps --match tsc
```

PowerShell entrypoints are available for Windows agents:

```powershell
cd templates/typescript-bun-mcp-server
.\scripts\check.ps1
bun run src/main.ts --help
.\..\..\scripts\agent-task.ps1 ps --match bun
```

Generated projects also include a pinned Beads wrapper and seeded starter backlog:

```bash
./scripts/agent-beads prime
./scripts/agent-beads ready --json
./scripts/agent-beads list
```

## Conventions

- production source files under `src/` are checked for a 1000-line maximum;
- MCP server registration lives in `src/mcp.ts`;
- transport startup lives in `src/stdio.ts`, `src/http.ts`, and `src/main.ts`;
- state behavior lives behind the `StateStore` interface in `src/state.ts`;
- Biome owns formatting and linting;
- `tsc --noEmit` owns static type checking;
- Bun's native test runner owns behavior checks;
- TypeScript and Biome package scripts invoke local tooling through Bun so a separate Node install is not required;
- reusable checks and project callouts live in `supermeta-rules.json` and the shared `tools/supermeta-rules/check.py` helper.

`bootstrap-template.json` declares the generated-project inputs, local support paths, and verification commands used by the root launcher.

The manifest also declares generated-doc metadata used to write `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/DECISIONS.md` after bootstrap.

## Project Shape

```text
src/config.ts
src/http.ts
src/logging.ts
src/main.ts
src/mcp.ts
src/state.ts
src/stdio.ts
tests/config.test.ts
tests/http.test.ts
tests/mcp.test.ts
tests/state.test.ts
```

Replace the stub tools before starting real product work.
