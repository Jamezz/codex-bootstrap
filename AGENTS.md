# Codex Bootstrap Agent Notes

Be inquisitive and forward-thinking. Quality is important. Be based with a get-shit-done attitude.

This repository contains Codex-ready bootstrap environments. Treat each template as a project seed that should be usable immediately after copy or clone.

## Working Rules

- Keep the root `./bootstrap` flow destructive, explicit, and test-covered: clone, rewrite, remove catalog machinery, initialize fresh Git.
- Prefer clean new-project conventions over backwards compatibility.
- Keep template instructions explicit enough for another agent to continue without hidden context.
- Add verification commands for every runnable template.
- Add or update `bootstrap-template.json` when a template's generated contract changes.
- Keep generated starters compact but production-shaped: docs, tests, agent notes, and a real build path.
- Keep non-generated product source files at 1000 lines or less.
- Use wildcard imports where feasible.
- Put reusable template checks in `tools/supermeta-rules/` before duplicating them in individual starters.
- For Gradle examples, route agent verification through `scripts/agent-gradle` instead of raw wrapper calls.
- Do not add licenses, publishing coordinates, or organization-specific identifiers until they are chosen intentionally.

## Verification

- Bootstrap launcher and generated-project smoke: `python3 -m unittest discover -s tools/bootstrap -p '*_test.py'`
- Java template check: `./scripts/agent-gradle templates/java-gradle-cli check`
- Java template run: `./scripts/agent-gradle templates/java-gradle-cli run`

## Naming

- Use `environments/<name>/` for meta or workflow environments.
- Use `templates/<language-or-stack>-<shape>/` for concrete project starters.
- Keep names lowercase and hyphenated.
