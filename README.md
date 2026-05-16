# Codex Bootstrap

Codex Bootstrap is a GitHub-hosted launchpad for starting software projects with an agent-ready baseline. Clone it into the directory that should become the new project, run `./bootstrap` or `.\bootstrap.ps1`, and the checkout rewrites itself into the selected starter with fresh Git metadata.

The repo currently ships:

- `environments/supermeta/`: the meta environment that explains how this catalog is organized and what new environments must provide.
- `templates/csharp-dotnet-cli/`: a C# .NET command-line starter with xUnit tests, first-class runtime logging, and a deterministic verification path.
- `templates/java-gradle-cli/`: a Java Gradle command-line starter with tests, first-class runtime logging, and a deterministic verification path.
- `templates/python-uv-cli/`: a Python uv command-line starter with pytest, Ruff, mypy, first-class runtime logging, and a deterministic verification path.
- `templates/typescript-bun-cli/`: a TypeScript Bun command-line starter with Biome, `tsc --noEmit`, Bun tests, first-class runtime logging, and a deterministic verification path.
- `templates/typescript-bun-mcp-server/`: a TypeScript Bun MCP server starter with stdio, Streamable HTTP, typed state stores, Bun tests, and a deterministic verification path.
- `bootstrap` and `bootstrap.ps1`: in-place launchers that materialize a template and remove the catalog from the generated project.
- `site/`: the GitHub Pages installer surface.
- `tools/bootstrap/`: the launcher implementation and smoke tests.
- `tools/pages/`: the GitHub Pages installer-site builder and tests.
- `scripts/agent-dotnet` and `scripts/agent-dotnet.ps1`: .NET CLI wrappers that keep dotnet home and NuGet package state local to the project during agent runs.
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
./bootstrap --template typescript-bun-cli --name my-service --dry-run
./bootstrap --template typescript-bun-mcp-server --name my-mcp-server --dry-run
./bootstrap --template csharp-dotnet-cli --name my-service --dry-run
```

Use `--yes` for non-interactive agent runs.

## Environment Contract

Every bootstrap environment should include:

- a README that explains purpose, prerequisites, usage, verification, and customization;
- an `AGENTS.md` with direct instructions for Codex-style agents working inside the environment;
- a generated operational docs pack: `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/DECISIONS.md`;
- a generated Beans workspace with a starter backlog and pinned `scripts/agent-beans` / `scripts/agent-beans.ps1` wrappers;
- first-class runtime logging with quiet defaults, stderr logs, and documented `LOG_LEVEL`/`LOG_FORMAT` controls;
- a deterministic verification command that can be run before handoff;
- enough project structure to feel like the first commit of a real project, not a toy snippet;
- clear extension points for common next moves.

Runnable templates should also include a `bootstrap-template.json` manifest describing required inputs, support paths that must survive into the generated project, generated verification commands, and generated-doc metadata.

General source rules:

- keep non-generated product source files at 1000 lines or less;
- exception: `tools/bootstrap/bootstrap.py` may exceed 1000 lines because the destructive launcher, template rewrite dispatch, and generated-project docs are intentionally kept in one audited control surface;
- keep Java package directories to 8 source files or fewer before nesting into subpackages;
- route language-specific lint through `tools/supermeta-rules/` project callouts;
- use wildcard imports where feasible, especially when they reduce import churn without hiding meaning.

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
  java-gradle-cli/
  python-uv-cli/
  typescript-bun-cli/
  typescript-bun-mcp-server/
tools/
  bootstrap/
  pages/
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
The C# starter requires .NET SDK 10 on PATH. `scripts/agent-dotnet` keeps `DOTNET_CLI_HOME` and `NUGET_PACKAGES` under the project by default so sandboxed agent runs do not write to the user home directory.

The harness uses the template wrapper with an isolated shared Gradle home, file watching disabled, serialized runs, and a per-run log under `.gradle/supermeta-gradle/logs/`. It keeps Gradle warm by default for faster repeated agent runs; set `SUPERMETA_GRADLE_COLD=1` for conservative no-daemon diagnostics.

For parallel Gradle execution inside one build, pass `--parallel --max-workers=<n>` to the Gradle args or set `SUPERMETA_GRADLE_PARALLEL=1` with `SUPERMETA_GRADLE_MAX_WORKERS=<n>`.

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
