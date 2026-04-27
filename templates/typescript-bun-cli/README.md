# TypeScript Bun CLI Template

This template is a minimal TypeScript command-line application with Bun, Biome, TypeScript type checking, Bun tests, and a Codex-friendly verification path.

It can be materialized from the catalog root with:

```bash
./bootstrap --template typescript-bun-cli --name my-service
```

After materialization, the generated project is standalone and uses:

```bash
./scripts/check
bun run src/main.ts
```

## Prerequisites

- `bun` on PATH;
- network access on first run so Bun can install development dependencies.

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

Run TypeScript lint and type checks directly:

```bash
bun run lint
bun run typecheck
```

Run the app:

```bash
bun run src/main.ts
bun run src/main.ts "Ada Lovelace"
```

Stuck-task diagnostics from the repository root:

```bash
./scripts/agent-task ps --match bun
./scripts/agent-task ps --match tsc
```

Generated projects also include a pinned Beans wrapper and seeded starter backlog:

```bash
./scripts/agent-beans prime
./scripts/agent-beans list --ready
./scripts/agent-beans check
```

## Conventions

- production source files under `src/` are checked for a 1000-line maximum;
- Biome owns formatting and linting;
- `tsc --noEmit` owns static type checking;
- Bun's native test runner owns behavior checks;
- TypeScript and Biome package scripts invoke local tooling through Bun so a separate Node install is not required;
- reusable checks and project callouts live in `supermeta-rules.json` and the shared `tools/supermeta-rules/check.py` helper.

`bootstrap-template.json` declares the generated-project inputs, local support paths, and verification commands used by the root launcher.

The manifest also declares generated-doc metadata used to write `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/DECISIONS.md` after bootstrap.

## Project Shape

```text
src/cli.ts
src/main.ts
tests/cli.test.ts
```

Replace the sample CLI behavior before starting real product work.
