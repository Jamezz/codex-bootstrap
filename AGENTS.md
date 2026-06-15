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
- Keep generated docs and Beans support first-class for every starter: architecture, operations, active decisions, `.beans.yml`, seeded starter backlog, and `scripts/agent-beans`.
- Keep velocity tooling practical and conservative: `agent-smart-check` accelerates inner loops with lane `cost`, `tags`, `requires`, and timeouts; `agent-fix-loop` captures classified attempt evidence; full template checks remain the handoff gate.
- Keep non-generated product source files at 1000 lines or less.
- Exception: `tools/bootstrap/bootstrap.py` may exceed 1000 lines because it owns the destructive launcher, template rewrite dispatch, and generated-project docs in one tested control surface. Split it only when the boundary is obvious and keeps the bootstrap flow easier to audit.
- Keep Java package layers at 7 top-level types or fewer before splitting into context-shaped subpackages.
- Keep JavaScript and TypeScript package layers at 7 directly contained source files or fewer before splitting into context-shaped subdirectories.
- Route language-specific lint through `tools/supermeta-rules/` project callouts before duplicating checks in templates.
- Use wildcard imports where feasible.
- Put reusable template checks in `tools/supermeta-rules/` before duplicating them in individual starters.
- For Gradle examples, route agent verification through `scripts/agent-gradle` instead of raw wrapper calls.
- Do not add licenses, publishing coordinates, or organization-specific identifiers until they are chosen intentionally.

## Verification

- Bootstrap launcher, generated-project smoke, and post-bootstrap example loop: `python3 -m unittest discover -s tools/bootstrap -p '*_test.py'`
- Velocity helper tests: `python3 -m unittest discover -s tools/supermeta-check -p '*_test.py'` and `python3 -m unittest discover -s tools/supermeta-fix -p '*_test.py'`
- Java template check: `./scripts/agent-gradle templates/java-gradle-cli check`
- Java template run: `./scripts/agent-gradle templates/java-gradle-cli run`
- Rust template check: `cd templates/rust-cargo-cli && ./scripts/check`
- Rust template run: `cd templates/rust-cargo-cli && cargo run --quiet`

## Naming

- Use `environments/<name>/` for meta or workflow environments.
- Use `templates/<language-or-stack>-<shape>/` for concrete project starters.
- Keep names lowercase and hyphenated.
