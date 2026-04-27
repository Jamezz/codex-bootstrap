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
- Beans prime after materialization: `./scripts/agent-beans prime`
- Beans check after materialization: `./scripts/agent-beans check`
- Inspect Bun processes: `./scripts/agent-task ps --match bun`
- Inspect TypeScript processes: `./scripts/agent-task ps --match tsc`

## Rules

- Bun is the only package-manager/runtime contract for this project; do not add npm, pnpm, or Yarn fallback paths.
- Keep runtime and dev dependencies in `package.json`, with the resolved lock in `bun.lock`.
- Keep CLI behavior in `src/cli.ts` and entrypoint glue in `src/main.ts`.
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Keep generated-doc metadata and Beans support paths aligned in `bootstrap-template.json`.
- Route formatting and linting through Biome, type checking through `tsc --noEmit`, and behavior checks through `bun test`.
- Keep the `typecheck`, `lint`, and `format` package scripts Bun-invoked so a stale global Node install cannot break verification.
- Use `./scripts/check` for agent verification unless debugging one tool directly.
- Keep `bootstrap-template.json` aligned with generated-project support paths and verification commands.
- Keep the sample CLI small and test-covered.
- Prefer breaking the template contract cleanly over keeping weak starter conventions.
