# Codex Bootstrap

Codex Bootstrap is a GitHub-hosted launchpad for starting software projects with an agent-ready baseline. Clone it into the directory that should become the new project, run `./bootstrap` or `.\bootstrap.ps1`, and the checkout rewrites itself into the selected starter with fresh Git metadata.

The repo currently ships:

- `environments/supermeta/`: the meta environment that explains how this catalog is organized and what new environments must provide.
- `templates/csharp-dotnet-cli/`: a C# .NET command-line starter with xUnit tests, first-class runtime logging, and a deterministic verification path.
- `templates/existing-repo-control/`: a non-destructive control-plane adoption package for bringing existing repositories under Bootstrap-managed scripts, sync metadata, and Supermeta tooling.
- `templates/java-gradle-cli/`: a Java Gradle command-line starter with tests, first-class runtime logging, and a deterministic verification path.
- `templates/python-uv-cli/`: a Python uv command-line starter with pytest, Ruff, mypy, first-class runtime logging, and a deterministic verification path.
- `templates/rust-cargo-cli/`: a Rust Cargo command-line starter with unit tests, Clippy, rustfmt, first-class runtime logging, and a deterministic verification path.
- `templates/typescript-bun-cli/`: a TypeScript Bun command-line starter with Biome, `tsc --noEmit`, Bun tests, first-class runtime logging, and a deterministic verification path.
- `templates/typescript-bun-mcp-server/`: a TypeScript Bun MCP server starter with stdio, Streamable HTTP, typed state stores, Bun tests, and a deterministic verification path.
- `bootstrap` and `bootstrap.ps1`: in-place launchers that materialize a template and remove the catalog from the generated project.
- `site/`: the GitHub Pages installer surface.
- `tools/bootstrap/`: the launcher implementation and smoke tests.
- `tools/pages/`: the GitHub Pages installer-site builder and tests.
- `scripts/agent-bootstrap` and `scripts/agent-bootstrap.ps1`: generated-project sync wrappers for pulling later managed bootstrap updates.
- `scripts/agent-coord` and `scripts/agent-coord.ps1`: advisory local agent coordination with opt-in serialized resource leases.
- `scripts/agent-nag` and `scripts/agent-nag.ps1`: advisory generated-project reminder hooks for bootstrap updates and wrapped-command follow-up.
- `scripts/agent-smart-check` and `scripts/agent-smart-check.ps1`: focused verification lane selection from changed files.
- `scripts/agent-fix-loop` and `scripts/agent-fix-loop.ps1`: failure capture and deterministic next-action diagnostics around any command.
- `scripts/agent-dotnet` and `scripts/agent-dotnet.ps1`: .NET CLI wrappers that keep dotnet home and NuGet package state local to the project during agent runs.
- `tools/supermeta-bootstrap/`: the generated-project managed sync helper.
- `tools/supermeta-agent/`: the local agent coordination helper copied into generated projects.
- `tools/supermeta-nag/`: the generated-project nag helper copied into generated projects.
- `tools/supermeta-check/`: the generated-project smart-check helper copied into generated projects.
- `tools/supermeta-fix/`: the generated-project fix-loop helper copied into generated projects.
- `tools/supermeta-rules/`: a small reusable rule checker that templates can call from their own build systems.
- `tools/supermeta-gradle/`: a Gradle harness that applies agent-safe defaults around wrapper usage.
- `tools/supermeta-beans/`: a pinned Beans wrapper used by generated projects for file-backed backlog context.
- `tools/supermeta-task/`: a language-agnostic stuck-task diagnostic helper copied into generated projects.

## Quick Start

Install directly from GitHub Pages:

```bash
curl -fsSL https://jamezz.github.io/codex-bootstrap/install.sh | bash -s -- my-service --template python-uv-cli
```

On Windows PowerShell:

```powershell
irm https://jamezz.github.io/codex-bootstrap/install.ps1 | iex
Install-CodexBootstrap my-service -Template python-uv-cli
```

List published starters:

```bash
curl -fsSL https://jamezz.github.io/codex-bootstrap/install.sh | bash -s -- --list-templates
```

```powershell
irm https://jamezz.github.io/codex-bootstrap/install.ps1 | iex
Install-CodexBootstrap -ListTemplates
```

Or clone the catalog manually:

```bash
git clone <codex-bootstrap-repo-url> my-service
cd my-service
./bootstrap --template java-gradle-cli --name my-service --package com.example.myservice
./scripts/agent-gradle . check
```

PowerShell equivalents:

```powershell
git clone <codex-bootstrap-repo-url> my-service
cd my-service
.\bootstrap.ps1 --template java-gradle-cli --name my-service --package com.example.myservice
.\scripts\agent-gradle.ps1 . check
```

Other starter variants:

```bash
./bootstrap --template python-uv-cli --name my-service
./scripts/check

./bootstrap --template rust-cargo-cli --name my-service
./scripts/check

./bootstrap --template typescript-bun-cli --name my-service
./scripts/check

./bootstrap --template typescript-bun-mcp-server --name my-mcp-server
./scripts/check

./bootstrap --template csharp-dotnet-cli --name my-service
./scripts/check
```

The launcher is intentionally destructive. It stages the selected template, rewrites the project identity, removes catalog-only files, deletes the cloned Git metadata, runs `git init`, and leaves the generated project uncommitted with no remote.

Use `--dry-run` to inspect the plan first:

```bash
./bootstrap --template java-gradle-cli --name my-service --package com.example.myservice --dry-run
./bootstrap --template python-uv-cli --name my-service --dry-run
./bootstrap --template rust-cargo-cli --name my-service --dry-run
./bootstrap --template typescript-bun-cli --name my-service --dry-run
./bootstrap --template typescript-bun-mcp-server --name my-mcp-server --dry-run
./bootstrap --template csharp-dotnet-cli --name my-service --dry-run
```

Use `--yes` for non-interactive agent runs.

## Adopt Existing Repositories

Use `agent-bootstrap adopt` from a Codex Bootstrap checkout when the target repository already exists and must not be rewritten by `./bootstrap`.

Preview adoption:

```bash
./scripts/agent-bootstrap adopt --target /path/to/existing-repo --name existing-repo
```

Apply the managed control plane:

```bash
./scripts/agent-bootstrap adopt --target /path/to/existing-repo --name existing-repo --apply
```

For large mixed repos, record the real verification commands during adoption so `agent-smart-check --full` has a useful default:

```bash
./scripts/agent-bootstrap adopt \
  --target /path/to/existing-repo \
  --name existing-repo \
  --verification-command './scripts/ci/all-linux.sh' \
  --apply
```

The adoption path copies only Bootstrap-managed scripts and `tools/supermeta-*`, writes `.codex-bootstrap/sync.json`, `.codex-bootstrap/checks.json`, and nag policy files, and leaves product source and existing docs alone. Put repository-specific lanes in `.codex-bootstrap/checks.local.json`.

## Resync Generated Projects

New generated projects include a bootstrap sync contract under `.codex-bootstrap/sync.json`.

Preview managed updates:

```bash
./scripts/agent-bootstrap sync --dry-run
```

For local beta testing from a checkout or worktree, keep the source ref aligned with the branch being tested:

```bash
./scripts/agent-bootstrap sync --dry-run --source-dir /path/to/codex-bootstrap --source-ref codex/branch-name
```

If an older generated sync runner applied a beta source dir but left
`.codex-bootstrap/sync.json` pointing at `main`, rerun the new helper with the
branch override to repair metadata before trusting plain dry-run or nag output:

```bash
./scripts/agent-bootstrap sync --apply --allow-dirty --source-ref codex/branch-name
./scripts/agent-bootstrap sync --dry-run --allow-dirty --source-ref codex/branch-name
```

Apply when the plan has no conflicts:

```bash
./scripts/agent-bootstrap sync --apply
```

Sync updates only declared managed files and managed regions. It does not merge arbitrary product source under `src/` or `tests/`, and it reports conflicts instead of overwriting local edits.

When the upstream sync contract adds a new managed set, sync enables it unless the set is marked for manual opt-in or the set id is listed in `.codex-bootstrap/sync.json` `optOut`. Missing generated doc regions are appended to existing docs during that migration.

## Agent Nags

Generated projects include advisory reminders for bootstrap updates and wrapped-command follow-up:

```bash
./scripts/agent-nag run-hook session-start
./scripts/agent-nag check-updates --quiet
./scripts/agent-nag snooze post-run-backlog-check --for 7d
```

Wrappers may call nag hooks before and after managed execution. Nags are advisory by default and must not hide the exit code from builds, tests, sync, or coordination runs. Project-specific reminders belong in `.codex-bootstrap/nags.local.json`; runtime state in `.codex-bootstrap/nag-state.json` is generated-project ignored.

## Velocity Tools

Generated projects include focused verification and failure-diagnostic helpers:

```bash
./scripts/agent-smart-check --plan-only
./scripts/agent-smart-check --self-test
./scripts/agent-smart-check --fast-only
./scripts/agent-fix-loop --timeout 600 -- ./scripts/agent-smart-check
```

`agent-smart-check` reads `.codex-bootstrap/checks.json` and optional `.codex-bootstrap/checks.local.json` to pick focused lanes from changed files. It runs Finder-copy hygiene first by default: exact duplicate copies are cleaned automatically, divergent or ambiguous copies are quarantined or reported, and verification stops with exit code `3` for review. Lanes can declare `cost`, `tags`, `requires`, and `timeoutSeconds`; use `--fast-only`, `--tag`, `--timeout`, `--hygiene-only`, `--no-hygiene`, and `--self-test` to keep the local loop tight. Focused lanes are for inner-loop work; run the template full check before handoff.

`agent-fix-loop` captures command output to `.codex-bootstrap/fix-loop/last.log`, classifies common failures, records attempt/evidence JSON, and can run read-only diagnostics between retries without mutating source or lockfiles in v1.

## Coordinate Local Agents

Generated projects include advisory coordination for parallel local agents:

```bash
./scripts/agent-coord announce --task "perf pass" --resource cpu:heavy
./scripts/agent-coord status
./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check
```

PowerShell:

```powershell
.\scripts\agent-coord.ps1 status
```

The tool stores per-user state on Linux, macOS, and Windows and only serializes work when `run` or `acquire` is used.

## Suggest Upstream Bootstrap Changes

Generated project `AGENTS.md` and README files include a managed copy/paste workflow for reporting downstream discoveries back to Codex Bootstrap.

Downstream agents should use it when they find a starter bug, stale verification command, agent wrapper issue, Supermeta tool fix, generated docs improvement, template default issue, bootstrap sync problem, or managed-set contract change. Product-only downstream choices should stay downstream.

The report should include metadata from `.codex-bootstrap/sync.json`, relevant `./scripts/agent-bootstrap sync --dry-run` output when sync is involved, reproduction commands, symptoms, local workaround if any, and the upstream verification that should pass after the fix.

```markdown
Upstream bootstrap suggestion

Source downstream project:
- Repository/path:
- Template id:
- Synced upstream commit:
- Sync contract version:
- Downstream project commit/branch:
- Affected managed set or file/region:

Problem or improvement:
- What happened:
- Why this belongs upstream:
- Expected upstream behavior:

Evidence:
- Commands run:
- Failure output or symptoms:
- Relevant downstream files:
- Local workaround, if any:

Requested upstream change:
- Files/contracts likely affected:
- Verification that should pass:
- Compatibility stance:
```

## Environment Contract

Every bootstrap environment should include:

- a README that explains purpose, prerequisites, usage, verification, and customization;
- an `AGENTS.md` with direct instructions for Codex-style agents working inside the environment;
- a generated operational docs pack: `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/DECISIONS.md`;
- a generated Beans workspace with a starter backlog and pinned `scripts/agent-beans` / `scripts/agent-beans.ps1` wrappers;
- a generated sync contract with `.codex-bootstrap/sync.json`, `scripts/agent-bootstrap`, and `tools/supermeta-bootstrap/`;
- a generated nag contract with `.codex-bootstrap/nags.json`, local overrides, `scripts/agent-nag`, and lifecycle hook docs;
- a generated velocity contract with `.codex-bootstrap/checks.json`, `scripts/agent-smart-check`, `scripts/agent-fix-loop`, and lifecycle docs;
- first-class runtime logging with quiet defaults, stderr logs, and documented `LOG_LEVEL`/`LOG_FORMAT` controls;
- a deterministic verification command that can be run before handoff;
- enough project structure to feel like the first commit of a real project, not a toy snippet;
- clear extension points for common next moves.

Runnable templates should also include a `bootstrap-template.json` manifest describing required inputs, support paths that must survive into the generated project, generated verification commands, generated-doc metadata, and the `syncContract` managed sets.

General source rules:

- keep non-generated product source files at 1000 lines or less;
- exception: `tools/bootstrap/bootstrap.py` may exceed 1000 lines because the destructive launcher, template rewrite dispatch, and generated-project docs are intentionally kept in one audited control surface;
- keep Java package layers to 7 top-level types or fewer before nesting into context-shaped subpackages;
- route language-specific lint and reusable heuristic gates through `tools/supermeta-rules/` project callouts;
- enforce wildcard imports for Java source unless a project explicitly allowlists an import;
- report unused Java imports as warnings instead of build-breaking errors;
- enforce Lombok over handwritten getter, setter, and builder boilerplate for Java source unless a project configures an ignore annotation; for records, require Lombok `@Builder` patterns for maximum readability and ensure record creation uses the builder pattern.

Prefer compatibility-breaking cleanup over preserving early template mistakes. These templates exist to start new projects cleanly, so change the contract when the new contract is better.

## Layout

```text
bootstrap
bootstrap.ps1
environments/
  supermeta/
scripts/
  agent-beans
  agent-beans.ps1
  agent-coord
  agent-coord.ps1
  agent-nag
  agent-nag.ps1
  agent-dotnet
  agent-dotnet.ps1
  agent-gradle
  agent-gradle.ps1
  agent-task
  agent-task.ps1
site/
  install.sh
  install.ps1
  index.html
templates/
  csharp-dotnet-cli/
  existing-repo-control/
  java-gradle-cli/
  python-uv-cli/
  rust-cargo-cli/
  typescript-bun-cli/
  typescript-bun-mcp-server/
tools/
  bootstrap/
  pages/
  supermeta-agent/
  supermeta-nag/
  supermeta-gradle/
  supermeta-beans/
  supermeta-rules/
  supermeta-task/
```

Use `environments/` for meta or workflow environments. Use `templates/` for copyable project starters.

## Verification

Verify the bootstrap launcher, generated-project smoke path, and post-bootstrap example development loop with:

```bash
python3 -m unittest discover -s tools -p '*_test.py'
```

Build the GitHub Pages installer artifact locally with:

```bash
python3 tools/pages/build_pages.py --output build/pages
bash -n build/pages/install.sh
```

`build/pages/install.ps1` is the Windows installer. If PowerShell is available locally, run it with `-Help` after the Pages build:

```powershell
.\build\pages\install.ps1 -Help
```

Verify the first runnable template in catalog form with:

```bash
./scripts/agent-gradle templates/java-gradle-cli test
./scripts/agent-gradle templates/java-gradle-cli run
```

Verify the Python starter in catalog form with:

```bash
cd templates/python-uv-cli
UV_CACHE_DIR=/tmp/codex-bootstrap-uv-cache ./scripts/check
UV_CACHE_DIR=/tmp/codex-bootstrap-uv-cache uv run --no-editable python-uv-cli
```

Verify the Rust starter in catalog form with:

```bash
cd templates/rust-cargo-cli
./scripts/check
cargo run --quiet
```

Verify the TypeScript starter in catalog form with:

```bash
cd templates/typescript-bun-cli
./scripts/check
bun run src/main.ts
```

Verify the TypeScript Bun MCP server starter in catalog form with:

```bash
cd templates/typescript-bun-mcp-server
./scripts/check
bun run src/main.ts --help
```

Verify the C# .NET starter in catalog form with:

```bash
cd templates/csharp-dotnet-cli
./scripts/check
../../scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj --
```

The TypeScript starters require `bun` on PATH. The Python commands above use `UV_CACHE_DIR` only to keep local agent runs out of the user home directory; generated projects can use uv's normal cache location when permitted.
The Rust starter requires Rust 1.85 or newer with rustfmt and Clippy installed.
The C# starter requires .NET SDK 10 on PATH. `scripts/agent-dotnet` keeps `DOTNET_CLI_HOME` and `NUGET_PACKAGES` under the project by default so sandboxed agent runs do not write to the user home directory.

The harness uses the template wrapper with a project-local Gradle home, file watching disabled, no resident daemon by default, same-checkout serialized runs, and a per-run log under `.gradle/supermeta-gradle/logs/`. It keeps downloaded Gradle assets warm inside each checkout without leaving idle Gradle JVMs around; set `SUPERMETA_GRADLE_COLD=1` for conservative low-worker diagnostics.

For parallel Gradle execution inside one build, pass `--parallel --max-workers=<n>` to the Gradle args or set `SUPERMETA_GRADLE_PARALLEL=1` with `SUPERMETA_GRADLE_MAX_WORKERS=<n>`.

Set `SUPERMETA_GRADLE_KEEP_DAEMON=1` only for a short repeated-run session where daemon reuse is worth the memory.

Generated projects can also carry a general stuck-task helper for process and log inspection:

```bash
./scripts/agent-task ps --match gradle
./scripts/agent-task logs .gradle/supermeta-gradle/logs
```

On Windows PowerShell, use the `.ps1` entrypoints:

```powershell
.\scripts\agent-task.ps1 ps --match gradle
.\scripts\agent-gradle.ps1 . check
```

The Gradle harness exposes shorter Gradle-specific recovery commands on top of that helper:

```bash
./scripts/agent-gradle templates/java-gradle-cli --ps
./scripts/agent-gradle templates/java-gradle-cli --logs
./scripts/agent-gradle templates/java-gradle-cli --stop
```
