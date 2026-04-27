# TypeScript Bun MCP Server Agent Notes

This is a copyable MCP server starter, not a long-lived framework.

## Commands

- Install locked dependencies from repo root: `cd templates/typescript-bun-mcp-server && bun install --frozen-lockfile`
- Verify from repo root: `cd templates/typescript-bun-mcp-server && ./scripts/check`
- Type check from repo root: `cd templates/typescript-bun-mcp-server && bun run typecheck`
- Lint and format check from repo root: `cd templates/typescript-bun-mcp-server && bun run lint`
- Test from repo root: `cd templates/typescript-bun-mcp-server && bun test`
- Show server help from repo root: `cd templates/typescript-bun-mcp-server && bun run src/main.ts --help`
- Run stdio server from repo root: `cd templates/typescript-bun-mcp-server && bun run src/main.ts`
- Run HTTP server from repo root: `cd templates/typescript-bun-mcp-server && bun run src/main.ts --transport http`
- Run with file state from repo root: `cd templates/typescript-bun-mcp-server && bun run src/main.ts --state file --state-file .mcp/state.json`
- Run with text logs: `cd templates/typescript-bun-mcp-server && LOG_LEVEL=info bun run src/main.ts --transport http`
- Run with JSON logs: `cd templates/typescript-bun-mcp-server && LOG_LEVEL=info LOG_FORMAT=json bun run src/main.ts --transport http`
- Beans prime after materialization: `./scripts/agent-beans prime`
- Beans check after materialization: `./scripts/agent-beans check`
- Inspect Bun processes: `./scripts/agent-task ps --match bun`
- Inspect TypeScript processes: `./scripts/agent-task ps --match tsc`

## Rules

- Bun is the only package-manager/runtime contract for this project; do not add npm, pnpm, or Yarn fallback paths.
- Keep runtime and dev dependencies in `package.json`, with the resolved lock in `bun.lock`.
- Keep MCP tool, prompt, and resource registration in `src/mcp.ts`.
- Keep transport startup out of `src/mcp.ts` so protocol tests can exercise the server without stdio or HTTP.
- Keep state behind `StateStore`; do not bind tool handlers directly to a persistence implementation.
- Keep stdio output clean: logs and diagnostics go to stderr, never stdout.
- Keep runtime logging in `src/logging.ts`; `LOG_LEVEL` and `LOG_FORMAT` are the public knobs.
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Keep generated-doc metadata and Beans support paths aligned in `bootstrap-template.json`.
- Route formatting and linting through Biome, type checking through `tsc --noEmit`, and behavior checks through `bun test`.
- Keep the `typecheck`, `lint`, and `format` package scripts Bun-invoked so a stale global Node install cannot break verification.
- Use `./scripts/check` for agent verification unless debugging one tool directly.
- Keep `bootstrap-template.json` aligned with generated-project support paths and verification commands.
- Keep the stub MCP capabilities small and test-covered.
- Prefer breaking the template contract cleanly over keeping weak starter conventions.
