# Supermeta Gradle Harness

`gradle.py` runs Gradle inside a project-local build capsule so multiple agents can compile without sharing mutable
Gradle state:

- use the checked-in `./gradlew` on POSIX and `gradlew.bat` on Windows;
- isolate `GRADLE_USER_HOME`, local build cache, logs, locks, generated-output hygiene, and included-build metadata under
  `.gradle/agent-capsules/<capsule-id>/`;
- disable file watching;
- keep warm Gradle daemons scoped to that capsule by default;
- serialize runs that share a capsule;
- tee output to the capsule `logs/` directory.

The default capsule id comes from `SUPERMETA_BUILD_CAPSULE_ID`, `CODEX_BUILD_CAPSULE_ID`, `FORGE_SESSION_ID`,
`APERTURE_SESSION_ID`, or `CODEX_SESSION_ID`. If none are set, the wrapper derives a stable id from the checkout path.
Pass `--capsule-id <id>` when two concurrent agents in the same checkout need separate caches.

Logs live under `.gradle/` so `clean` tasks cannot delete the active run log. Log names include the process id and a
nanosecond suffix so intentional `--no-lock` runs do not collide.

The summary reports both `run_elapsed` and `total_elapsed`. When another agent run is holding the same project's Gradle-home lock, `lock_wait` makes that queue time explicit.

From a generated project root:

```bash
./scripts/agent-gradle . test
./scripts/agent-gradle . check
./scripts/agent-gradle . run
```

Windows PowerShell:

```powershell
.\scripts\agent-gradle.ps1 . test
.\scripts\agent-gradle.ps1 . check
.\scripts\agent-gradle.ps1 . run
```

Direct invocation:

```bash
python3 tools/supermeta-gradle/gradle.py --project . -- test
```

When working inside the Codex Bootstrap catalog itself, pass the template directory instead:

```bash
./scripts/agent-gradle templates/java-gradle-cli check
```

## Stuck Build Diagnostics

These helpers wrap the shared `agent-task` process/log diagnostics with Gradle defaults:

```bash
./scripts/agent-task ps --match gradle
./scripts/agent-task logs .gradle/agent-capsules --glob '**/*.log'
./scripts/agent-gradle . --ps
./scripts/agent-gradle . --logs
./scripts/agent-gradle . --stop
./scripts/agent-gradle . --kill
./scripts/agent-gradle . --status
./scripts/agent-gradle . --repair
./scripts/supermeta-cache clean
./scripts/agent-gradle . --clean-supermeta-cache
./scripts/agent-gradle . --clean-supermeta-cache check
```

```powershell
.\scripts\agent-task.ps1 ps --match gradle
.\scripts\agent-gradle.ps1 . --logs
.\scripts\agent-gradle.ps1 . --stop
```

- `--ps` lists likely Gradle/Java build processes.
- `--logs` lists recent harness logs for the project.
- `--status` prints the capsule paths and scoped process diagnostics.
- `--stop` asks the scoped Gradle daemon to stop with the project wrapper.
- `--repair` stops the scoped daemon and removes the capsule Gradle caches and local build cache.
- `scripts/supermeta-cache clean` is the direct cache-only command. `--clean-supermeta-cache` is the equivalent harness
  option and can be combined with a Gradle task to force a fresh rule scan before that task runs.
- `--kill` sends `SIGTERM` to likely stuck Gradle processes owned by the current user.

Prefer `--stop` before `--kill` unless a process is clearly wedged.

Set `SUPERMETA_GRADLE_USER_HOME` to opt into an explicit shared cache root or another custom cache location. Pass
`--no-default-flags` before `--` when you are intentionally debugging raw Gradle behavior.

## Generated-Output Hygiene

Before Gradle starts, the wrapper proactively scans generated output directories (`build`, `out`, `target`) for
classpath-relevant duplicate files such as `Worker 2.class` or `defaults copy.properties`.

- exact duplicates are removed before Gradle sees them;
- divergent or ambiguous duplicates are quarantined under the capsule `hygiene/` directory and the run exits for review;
- generated reports are ignored, because report copies are not classpath hazards.

Run hygiene without Gradle:

```bash
./scripts/agent-gradle . --hygiene-only
```

Use `--no-hygiene` only when debugging the hygiene tool itself.

## Included Builds

Composite builds can collide when multiple agents build through the same sibling checkouts. Use strict included-build
mode with explicit repo ids when agent concurrency matters:

```bash
./scripts/agent-gradle . --strict-included-builds --included-build-repo shared-lib -- :app:compileJava
```

The wrapper resolves the project-directory source in this order:

1. `--project-directory-file <file>`
2. `SUPERMETA_PROJECT_DIRECTORY_FILE`
3. local `project-directory.properties`
4. local `project-directory.properties.example`

It then creates detached worktrees for the required included builds under the capsule `included-builds/` directory and
exports a generated `SUPERMETA_PROJECT_DIRECTORY_FILE` that points Gradle at those capsule-local worktrees.

For parallel Gradle execution inside one build, either pass Gradle flags directly:

```bash
./scripts/agent-gradle . check --parallel --max-workers=4
```

or opt into parallel defaults for repeated agent commands:

```bash
SUPERMETA_GRADLE_PARALLEL=1 SUPERMETA_GRADLE_MAX_WORKERS=4 ./scripts/agent-gradle . check
```

The project Gradle-home lock still serializes separate harness processes for the same checkout by default. Use `--no-lock` only for intentional concurrent experiments where the projects or tasks will not delete each other's outputs.

For wedged or diagnostic runs, use cold mode:

```bash
SUPERMETA_GRADLE_COLD=1 ./scripts/agent-gradle . test
# or
./scripts/agent-gradle . --cold -- test
```

Cold mode adds `--no-daemon`, `--no-parallel`, and a conservative worker cap for wedged or diagnostic runs.

To stop the scoped daemon for a project:

```bash
./scripts/agent-gradle . --stop
```
