# Supermeta Beans

`beans.py` is the shared Beans wrapper for generated projects. It keeps task/backlog tooling behind one stable command while Beans is still moving quickly.

From a generated repo:

```bash
./scripts/agent-beans prime
./scripts/agent-beans list --ready
./scripts/agent-beans check
./scripts/agent-beans roadmap
```

Windows PowerShell:

```powershell
.\scripts\agent-beans.ps1 prime
.\scripts\agent-beans.ps1 list --ready
.\scripts\agent-beans.ps1 check
```

The wrapper requires Beans `0.4.2`. If the local CLI is absent or a different version is installed, it exits with install guidance instead of silently using an unknown schema.
