# Supermeta Beads

`beads.py` is the shared wrapper for generated projects. It requires Beads 1.1.0, initializes a fresh clone from the tracked `.beads/issues.jsonl`, and then forwards native `bd` commands.

```bash
./scripts/agent-beads prime
./scripts/agent-beads ready --json
./scripts/agent-beads list
```

Install Beads with `brew install beads`, `npm install -g @beads/bd@1.1.0`, or the official release installers. Set `SUPERMETA_BEADS_BIN` only for controlled testing or an explicitly managed binary path.
