# Supermeta Gradle Harness

`gradle.py` runs Gradle in the boring, agent-safe way that has proven less painful across local Codex work:

- use the checked-in `./gradlew`;
- isolate `GRADLE_USER_HOME` under `/tmp/supermeta-gradle/gradle-user-home`;
- disable file watching;
- serialize runs that share that Gradle home;
- tee output to `.gradle/supermeta-gradle/logs/`.

The default mode is warm: it keeps Gradle daemon/cache benefits inside the isolated shared Gradle home so repeated agent runs are not painfully slow, and different templates can reuse downloaded Gradle distributions, dependencies, and toolchains.

Logs live under `.gradle/` so `clean` tasks cannot delete the active run log. Log names include the process id and a nanosecond suffix so concurrent `--no-lock` runs do not collide.

The summary reports both `run_elapsed` and `total_elapsed`. When another agent run is holding the shared Gradle-home lock, `lock_wait` makes that queue time explicit.

From the repository root:

```bash
./scripts/agent-gradle templates/java-gradle-cli test
./scripts/agent-gradle templates/java-gradle-cli check
./scripts/agent-gradle templates/java-gradle-cli run
```

Direct invocation:

```bash
python3 tools/supermeta-gradle/gradle.py --project templates/java-gradle-cli -- test
```

Set `SUPERMETA_GRADLE_USER_HOME` to override the cache root. Pass `--no-default-flags` before `--` when you are intentionally debugging raw Gradle behavior.

For parallel Gradle execution inside one build, either pass Gradle flags directly:

```bash
./scripts/agent-gradle templates/java-gradle-cli check --parallel --max-workers=4
```

or opt into parallel defaults for repeated agent commands:

```bash
SUPERMETA_GRADLE_PARALLEL=1 SUPERMETA_GRADLE_MAX_WORKERS=4 ./scripts/agent-gradle templates/java-gradle-cli check
```

The shared Gradle-home lock still serializes separate harness processes by default. Use `--no-lock` only for intentional concurrent experiments where the projects or tasks will not delete each other's outputs.

For wedged or diagnostic runs, use cold mode:

```bash
SUPERMETA_GRADLE_COLD=1 ./scripts/agent-gradle templates/java-gradle-cli test
```

Cold mode adds `--no-daemon`, `--no-parallel`, and a conservative worker cap. Warm mode is the normal path.

To stop the scoped daemon for a project:

```bash
./scripts/agent-gradle templates/java-gradle-cli --stop
```
