# C# .NET CLI Template

C# .NET CLI Template is a compact C# .NET command-line project with tests, first-class runtime logging, agent notes, and a deterministic verification path.

## Prerequisites

- .NET SDK 10 on PATH;
- network access on first run so NuGet can restore test dependencies.

The project targets `net10.0`.

## Usage

Restore locked dependencies:

```bash
./scripts/agent-dotnet . restore --locked-mode
```

Run the full verification lifecycle:

```bash
./scripts/check
```

Run tests directly:

```bash
./scripts/agent-dotnet . test CsharpDotnetCli.slnx --configuration Release
```

Run the app:

```bash
./scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj --
./scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj -- "Ada Lovelace"
```

## Logging

Runtime logs are quiet by default and become visible when `LOG_LEVEL` enables them:

```bash
LOG_LEVEL=info LOG_FORMAT=text ./scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj --
LOG_LEVEL=info LOG_FORMAT=json ./scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj --
```

`LOG_LEVEL` accepts `trace`, `debug`, `info`, `warn`, `error`, or `off`. `LOG_FORMAT` accepts `text` or `json`. Logs always go to stderr; normal command output stays on stdout unless the CLI is reporting a user-facing error.

## Windows

PowerShell entrypoints mirror the Unix scripts:

```powershell
.\scripts\agent-dotnet.ps1 . restore --locked-mode
.\scripts\check.ps1
.\scripts\agent-dotnet.ps1 . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj --
.\scripts\agent-beans.ps1 prime
.\scripts\agent-task.ps1 ps --match dotnet
```

## Customization

- Product source lives under `src/CsharpDotnetCli`.
- Test source lives under `tests/CsharpDotnetCli.Tests`.
- CLI behavior starts in `src/CsharpDotnetCli/App.cs`.
- Runtime logging lives in `src/CsharpDotnetCli/LoggingConfig.cs`.
- The process entrypoint is `src/CsharpDotnetCli/Program.cs`.
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable project checks in `tools/supermeta-rules/` and wire them through `scripts/check`.
- Keep formatting in `dotnet format`, build checks in `dotnet build`, and behavior checks in xUnit.
- Keep package versions in `Directory.Packages.props` and lock files checked in.

## First Useful Edit

Extend the CLI behavior in `App.cs`, update `AppTests.cs` first or in the same change, then run:

```bash
./scripts/check
./scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj -- example
```

## Project Docs

- `docs/ARCHITECTURE.md`: runtime shape, entrypoints, and code layout.
- `docs/OPERATIONS.md`: verification, run, troubleshooting, and backlog commands.
- `docs/DECISIONS.md`: active decisions only; superseded decision history belongs in completed or archived Beans.

## Backlog

This project starts with a small Beans backlog for replacing the starter behavior, locking architecture decisions, and adding CI or release verification.

If the pinned Beans CLI is installed, inspect project task context with:

```bash
./scripts/agent-beans prime
./scripts/agent-beans list
./scripts/agent-beans check
```

## Agent Workflow

Agents should start by reading `AGENTS.md`, then run:

```bash
./scripts/check
```
