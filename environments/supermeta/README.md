# Supermeta Environment

Supermeta is the meta bootstrap environment for this repository. It describes what Codex Bootstrap is trying to make repeatable: starting a new project with the pieces an agent needs to move quickly and safely.

## Purpose

Supermeta defines the minimum bar for a bootstrap environment:

- clear project intent;
- repeatable verification;
- agent-facing working instructions;
- obvious customization points;
- enough implementation scaffolding to start real work immediately.

The goal is not to preserve every possible option. The goal is to make the good default path obvious.

`bootstrap` is the in-place launcher. It materializes a template into the current checkout, removes catalog-only files, deletes cloned Git metadata, and initializes a fresh standalone project.

`tools/bootstrap/` owns the launcher implementation and tests. Its smoke test copies the catalog to a temp directory, runs the destructive launcher, verifies the generated project, then develops and verifies a tiny generated CLI example.

`tools/supermeta-rules/check.py` is the shared helper for rules that examples should not reimplement, starting with product source line-count checks.

`tools/supermeta-gradle/gradle.py` is the shared Gradle harness. Gradle templates should document `scripts/agent-gradle` as the agent verification path so local runs consistently avoid global Gradle state, file-watch noise, and parallel output collisions while still keeping warm Gradle performance by default.

## Environment Checklist

When adding a new environment or template, include:

- `README.md` with purpose, prerequisites, usage, verification, and customization;
- `AGENTS.md` with repo-local instructions for agents;
- `bootstrap-template.json` for runnable templates that can be materialized by the root launcher;
- a deterministic validation command;
- a small working example;
- a short explanation of the first likely extension points.

Meta source rules:

- non-generated product source files must stay at 1000 lines or less;
- Java package directories should contain at most 8 source files before nesting into subpackages;
- language-specific lint should be routed through `tools/supermeta-rules/` project callouts;
- wildcard imports are preferred where they are feasible and keep the source cleaner.

## Agent Workflow

1. Read the template README and `AGENTS.md`.
2. Run the verification command before changing behavior.
3. Make the smallest coherent change that improves the starter.
4. Update docs and `bootstrap-template.json` when the template contract changes.
5. Re-run the verification command before handoff.

## Adding Templates

Place copyable project starters under `templates/`. Name them by stack and shape, such as `java-gradle-cli` or `typescript-node-service`.

Favor boring, durable defaults:

- one command to test;
- one command to run;
- explicit tool versions or version knobs;
- no hidden global setup beyond documented prerequisites.

For generated projects, keep support paths local to the project. A materialized starter must not depend on `templates/`, `environments/`, or root bootstrap code after the launcher finishes.
