# C# .NET CLI Template Agent Notes

This is a standalone C# .NET CLI project. Keep it compact, test-covered, and easy for the next agent to verify.

## Commands

- Restore locked dependencies: `./scripts/agent-dotnet . restore --locked-mode`
- Verify: `./scripts/check`
- Format check: `./scripts/agent-dotnet . format CsharpDotnetCli.slnx --verify-no-changes --no-restore`
- Build: `./scripts/agent-dotnet . build CsharpDotnetCli.slnx --configuration Release --no-restore`
- Test: `./scripts/agent-dotnet . test CsharpDotnetCli.slnx --configuration Release --no-build`
- Run: `./scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj --`
- Run with app args: `./scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj -- "example"`
- Run with text logs: `LOG_LEVEL=info ./scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj --`
- Run with JSON logs: `LOG_LEVEL=info LOG_FORMAT=json ./scripts/agent-dotnet . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj --`
- Beans prime: `./scripts/agent-beans prime`
- Beans check: `./scripts/agent-beans check`
- Ready backlog: `./scripts/agent-beans list --ready`
- Announce coordination state: `./scripts/agent-coord announce --task "verification" --resource cpu:heavy`
- Inspect peer agents: `./scripts/agent-coord status`
- Serialize perf-sensitive work: `./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check`
- Inspect dotnet processes: `./scripts/agent-task ps --match dotnet`

## Windows

- Restore locked dependencies: `.\scripts\agent-dotnet.ps1 . restore --locked-mode`
- Verify: `.\scripts\check.ps1`
- Run: `.\scripts\agent-dotnet.ps1 . run --project src/CsharpDotnetCli/CsharpDotnetCli.csproj --`
- Beans prime: `.\scripts\agent-beans.ps1 prime`
- Inspect peer agents: `.\scripts\agent-coord.ps1 status`
- Inspect dotnet processes: `.\scripts\agent-task.ps1 ps --match dotnet`

## Beans

- Before substantial work, run `./scripts/agent-beans prime` and follow its project-task context.
- Use `./scripts/agent-beans list --ready` to inspect ready work.
- Keep the seeded Beans current as starter behavior is replaced.
- If `./scripts/agent-beans` reports a missing or wrong Beans CLI version, tell the user instead of bypassing the wrapper.

## Rules

- Target .NET 10 through `net10.0` unless the project intentionally chooses a different runtime floor.
- Keep runtime and test dependency versions centralized in `Directory.Packages.props`.
- Keep package lock files checked in and use locked restore for verification.
- Keep CLI behavior in `App.cs` and entrypoint glue in `Program.cs`.
- Keep runtime logging in `LoggingConfig.cs`.
- Keep runtime logging behind `LOG_LEVEL` and `LOG_FORMAT`.
- Keep default logging quiet: `LOG_LEVEL=warn` and `LOG_FORMAT=text`.
- Keep logs on stderr and normal command output on stdout.
- Fail fast with exit code 2 when logging configuration is invalid.
- Keep product source files under `src/` at 1000 lines or less.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Route formatting through `dotnet format`, build through `dotnet build`, and behavior checks through xUnit.
- Use `scripts/agent-dotnet` for agent verification unless debugging raw dotnet behavior.
- Extend the sample CLI into real behavior early, and keep tests updated with that change.
- Prefer clean new-project conventions over compatibility with starter mistakes.
