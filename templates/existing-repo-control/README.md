# Existing Repo Control Plane Template

This template is not a product starter. It is a Bootstrap-managed control-plane package for adopting an existing repository without rewriting its source tree.

Use it through the catalog-side adoption command:

```bash
./scripts/agent-bootstrap adopt --target /path/to/existing-repo --name existing-repo --apply
```

The adoption flow copies Bootstrap-managed agent scripts and Supermeta tools, writes `.codex-bootstrap/sync.json`, and leaves product source files alone.
