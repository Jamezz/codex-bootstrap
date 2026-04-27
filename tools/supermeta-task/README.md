# Supermeta Task Diagnostics

Shared stuck-task helpers for generated projects. This tool is intentionally language-agnostic so templates can reuse it for Gradle, Node, Maven, test runners, or custom long-running commands.

From a generated repo:

```bash
./scripts/agent-task ps --match gradle
./scripts/agent-task ps --match uv
./scripts/agent-task ps --match bun
./scripts/agent-task logs .gradle/supermeta-gradle/logs
./scripts/agent-task kill --match gradle
```

- `ps` lists matching process commands. Without `--match`, it uses broad build/test defaults.
- `logs` lists recent files from a log directory.
- `kill` sends `SIGTERM` and requires at least one explicit `--match` pattern.

Prefer build-specific stop commands, such as `./scripts/agent-gradle . --stop`, before `kill`.
