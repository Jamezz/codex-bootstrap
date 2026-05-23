# Supermeta Agent Coordination

Shared local coordination for generated projects. The tool is advisory by default: agents can announce their work and inspect other live agents without blocking ordinary checks.

```bash
./scripts/agent-coord announce --task "perf pass" --resource cpu:heavy --resource perf
./scripts/agent-coord status
./scripts/agent-coord leave
```

Use `run` when a command should serialize on an exclusive local resource:

```bash
./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check
```

Windows PowerShell:

```powershell
.\scripts\agent-coord.ps1 status
.\scripts\agent-coord.ps1 run --resource perf:exclusive -- .\scripts\check.ps1
```

State is per-user:

- Linux: `$XDG_STATE_HOME/codex-bootstrap/agents`, or `~/.local/state/codex-bootstrap/agents`.
- macOS: `~/Library/Application Support/codex-bootstrap/agents`.
- Windows: `%LOCALAPPDATA%\CodexBootstrap\agents`.

Set `CODEX_AGENT_COORD_HOME` when several agents should coordinate through a shared directory. Set `CODEX_AGENT_ID` when multiple sessions in the same checkout should keep separate registry records.
