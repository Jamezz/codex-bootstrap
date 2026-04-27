# Codex Bootstrap

Codex Bootstrap is a catalog of small, production-shaped starter environments for new software projects. Each environment is meant to be easy for a Codex agent to copy, inspect, verify, and extend without guessing the project conventions from scratch.

The repo starts with two pieces:

- `environments/supermeta/`: the meta environment that explains how this catalog is organized and what new environments must provide.
- `templates/java-gradle-cli/`: a Java Gradle command-line starter with tests and a deterministic verification path.
- `tools/supermeta-rules/`: a small reusable rule checker that templates can call from their own build systems.

## Environment Contract

Every bootstrap environment should include:

- a README that explains purpose, prerequisites, usage, verification, and customization;
- an `AGENTS.md` with direct instructions for Codex-style agents working inside the environment;
- a deterministic verification command that can be run before handoff;
- enough project structure to feel like the first commit of a real project, not a toy snippet;
- clear extension points for common next moves.

General source rules:

- keep non-generated product source files at 1000 lines or less;
- use wildcard imports where feasible, especially when they reduce import churn without hiding meaning.

Prefer compatibility-breaking cleanup over preserving early template mistakes. These templates exist to start new projects cleanly, so change the contract when the new contract is better.

## Layout

```text
environments/
  supermeta/
templates/
  java-gradle-cli/
tools/
  supermeta-rules/
```

Use `environments/` for meta or workflow environments. Use `templates/` for copyable project starters.

## Verification

The catalog itself is mostly documentation today. Verify the first runnable template with:

```bash
cd templates/java-gradle-cli
./gradlew test
./gradlew run
```

`./gradlew test` is the minimum acceptance gate for the Java template.
