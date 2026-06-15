# TypeScript Bun CLI Agent Notes

This is a copyable starter, not a long-lived framework.

## Commands

- Install locked dependencies from repo root: `cd templates/typescript-bun-cli && bun install --frozen-lockfile`
- Verify from repo root: `cd templates/typescript-bun-cli && ./scripts/check`
- Type check from repo root: `cd templates/typescript-bun-cli && bun run typecheck`
- Lint and format check from repo root: `cd templates/typescript-bun-cli && bun run lint`
- Test from repo root: `cd templates/typescript-bun-cli && bun test`
- Run from repo root: `cd templates/typescript-bun-cli && bun run src/main.ts`
- Run with app args from repo root: `cd templates/typescript-bun-cli && bun run src/main.ts "Ada Lovelace"`
- Run with text logs: `cd templates/typescript-bun-cli && LOG_LEVEL=info bun run src/main.ts`
- Run with JSON logs: `cd templates/typescript-bun-cli && LOG_LEVEL=info LOG_FORMAT=json bun run src/main.ts`
- Beans prime after materialization: `./scripts/agent-beans prime`
- Beans check after materialization: `./scripts/agent-beans check`
- Announce coordination state: `./scripts/agent-coord announce --task "verification" --resource cpu:heavy`
- Inspect peer agents: `./scripts/agent-coord status`
- Serialize perf-sensitive work: `./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check`
- Inspect Bun processes: `./scripts/agent-task ps --match bun`
- Inspect TypeScript processes: `./scripts/agent-task ps --match tsc`

## Windows

- Verify from template root: `.\scripts\check.ps1`
- Run from template root: `bun run src/main.ts`
- Beans prime after materialization: `.\scripts\agent-beans.ps1 prime`
- Inspect peer agents: `.\scripts\agent-coord.ps1 status`
- Inspect Bun processes after materialization: `.\scripts\agent-task.ps1 ps --match bun`

## Rules

- Bun is the only package-manager/runtime contract for this project; do not add npm, pnpm, or Yarn fallback paths.
- Keep runtime and dev dependencies in `package.json`, with the resolved lock in `bun.lock`.
- Keep CLI behavior in `src/cli.ts` and entrypoint glue in `src/main.ts`.
- Keep runtime logging in `src/logging.ts`; `LOG_LEVEL` and `LOG_FORMAT` are the public knobs.
- Keep logs on stderr and normal command output on stdout.
- Keep product source files under `src/` at 1000 lines or less.
- Keep JavaScript and TypeScript package layers at 7 directly contained source files or fewer before splitting into context-shaped subdirectories.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Keep generated-doc metadata and Beans support paths aligned in `bootstrap-template.json`.
- Route formatting and linting through Biome, type checking through `tsc --noEmit`, and behavior checks through `bun test`.
- Keep the `typecheck`, `lint`, and `format` package scripts Bun-invoked so a stale global Node install cannot break verification.
- Use `./scripts/check` for agent verification unless debugging one tool directly.
- Keep `bootstrap-template.json` aligned with generated-project support paths and verification commands.
- Keep the sample CLI small and test-covered.
- Prefer breaking the template contract cleanly over keeping weak starter conventions.
