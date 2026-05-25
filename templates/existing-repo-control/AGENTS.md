# Existing Repo Control Plane Agent Notes

This package exists to seed Bootstrap control-plane tooling into an already-existing repository.

## Rules

- Do not treat this as a product starter.
- Keep adoption non-destructive.
- Keep project-specific verification in `.codex-bootstrap/checks.local.json` or in the downstream repository's own scripts.
- Managed Bootstrap tools should stay under `scripts/`, `tools/supermeta-*`, and `.codex-bootstrap/`.
