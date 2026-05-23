# Supermeta Gradle Harness

`gradle.py` runs Gradle in the boring, agent-safe way that has proven less painful across local Codex work:

- use the checked-in `./gradlew` on POSIX and `gradlew.bat` on Windows;
- isolate `GRADLE_USER_HOME` under the project-local `.gradle/supermeta-gradle/gradle-user-home`;
- disable file watching;
- disable resident Gradle daemons by default;
- serialize runs that share that Gradle home;
- tee output to `.gradle/supermeta-gradle/logs/`.

The default mode keeps Gradle distributions, dependencies, and toolchains cached inside the project-local Gradle home, but passes `--no-daemon` so Gradle JVMs do not stay resident after the command exits. This avoids unrelated agents queueing on one shared cache and keeps memory from filling up with idle daemons.

Logs live under `.gradle/` so `clean` tasks cannot delete the active run log. Log names include the process id and a nanosecond suffix so concurrent `--no-lock` runs do not collide.

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
./scripts/agent-task logs .gradle/supermeta-gradle/logs
./scripts/agent-gradle . --ps
./scripts/agent-gradle . --logs
./scripts/agent-gradle . --stop
./scripts/agent-gradle . --kill
```

```powershell
.\scripts\agent-task.ps1 ps --match gradle
.\scripts\agent-gradle.ps1 . --logs
.\scripts\agent-gradle.ps1 . --stop
```

- `--ps` lists likely Gradle/Java build processes.
- `--logs` lists recent harness logs for the project.
- `--stop` asks the scoped Gradle daemon to stop with the project wrapper.
- `--kill` sends `SIGTERM` to likely stuck Gradle processes owned by the current user.

Prefer `--stop` before `--kill` unless a process is clearly wedged.

Set `SUPERMETA_GRADLE_USER_HOME` to opt into an explicit shared cache root or another custom cache location. Set `SUPERMETA_GRADLE_KEEP_DAEMON=1` only when you intentionally want daemon reuse for a short repeated-run session. Pass `--no-default-flags` before `--` when you are intentionally debugging raw Gradle behavior.

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
```

Cold mode adds `--no-parallel` and a conservative worker cap on top of the default no-daemon behavior.

To stop the scoped daemon for a project:

```bash
./scripts/agent-gradle . --stop
```
