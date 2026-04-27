# Codex Bootstrap

Codex Bootstrap is a GitHub-hosted launchpad for starting software projects with an agent-ready baseline. Clone it into the directory that should become the new project, run `./bootstrap`, and the checkout rewrites itself into the selected starter with fresh Git metadata.

The repo currently ships:

- `environments/supermeta/`: the meta environment that explains how this catalog is organized and what new environments must provide.
- `templates/java-gradle-cli/`: a Java Gradle command-line starter with tests and a deterministic verification path.
- `bootstrap`: the in-place launcher that materializes a template and removes the catalog from the generated project.
- `tools/bootstrap/`: the launcher implementation and smoke tests.
- `tools/supermeta-rules/`: a small reusable rule checker that templates can call from their own build systems.
- `tools/supermeta-gradle/`: a Gradle harness that applies agent-safe defaults around wrapper usage.

## Quick Start

```bash
git clone <codex-bootstrap-repo-url> my-service
cd my-service
./bootstrap --template java-gradle-cli --name my-service --package com.example.myservice
./scripts/agent-gradle . check
```

The launcher is intentionally destructive. It stages the selected template, rewrites the project identity, removes catalog-only files, deletes the cloned Git metadata, runs `git init`, and leaves the generated project uncommitted with no remote.

Use `--dry-run` to inspect the plan first:

```bash
./bootstrap --template java-gradle-cli --name my-service --package com.example.myservice --dry-run
```

Use `--yes` for non-interactive agent runs.

## Environment Contract

Every bootstrap environment should include:

- a README that explains purpose, prerequisites, usage, verification, and customization;
- an `AGENTS.md` with direct instructions for Codex-style agents working inside the environment;
- a deterministic verification command that can be run before handoff;
- enough project structure to feel like the first commit of a real project, not a toy snippet;
- clear extension points for common next moves.

Runnable templates should also include a `bootstrap-template.json` manifest describing required inputs, support paths that must survive into the generated project, and generated verification commands.

General source rules:

- keep non-generated product source files at 1000 lines or less;
- keep Java package directories to 8 source files or fewer before nesting into subpackages;
- route language-specific lint through `tools/supermeta-rules/` project callouts;
- use wildcard imports where feasible, especially when they reduce import churn without hiding meaning.

Prefer compatibility-breaking cleanup over preserving early template mistakes. These templates exist to start new projects cleanly, so change the contract when the new contract is better.

## Layout

```text
bootstrap
environments/
  supermeta/
scripts/
  agent-gradle
templates/
  java-gradle-cli/
tools/
  bootstrap/
  supermeta-gradle/
  supermeta-rules/
```

Use `environments/` for meta or workflow environments. Use `templates/` for copyable project starters.

## Verification

Verify the bootstrap launcher, generated-project smoke path, and post-bootstrap example development loop with:

```bash
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
```

Verify the first runnable template in catalog form with:

```bash
./scripts/agent-gradle templates/java-gradle-cli test
./scripts/agent-gradle templates/java-gradle-cli run
```

The harness uses the template wrapper with an isolated shared Gradle home, file watching disabled, serialized runs, and a per-run log under `.gradle/supermeta-gradle/logs/`. It keeps Gradle warm by default for faster repeated agent runs; set `SUPERMETA_GRADLE_COLD=1` for conservative no-daemon diagnostics.

For parallel Gradle execution inside one build, pass `--parallel --max-workers=<n>` to the Gradle args or set `SUPERMETA_GRADLE_PARALLEL=1` with `SUPERMETA_GRADLE_MAX_WORKERS=<n>`.
