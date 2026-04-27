# Supermeta Gradle Harness

`gradle.py` runs Gradle in the boring, agent-safe way that has proven less painful across local Codex work:

- use the checked-in `./gradlew`;
- isolate `GRADLE_USER_HOME` under `/tmp/supermeta-gradle/gradle-user-home`;
- disable file watching;
- serialize runs that share that Gradle home;
- tee output to `build/supermeta-gradle/`.

The default mode is warm: it keeps Gradle daemon/cache benefits inside the isolated shared Gradle home so repeated agent runs are not painfully slow, and different templates can reuse downloaded Gradle distributions, dependencies, and toolchains.

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

For wedged or diagnostic runs, use cold mode:

```bash
SUPERMETA_GRADLE_COLD=1 ./scripts/agent-gradle templates/java-gradle-cli test
```

Cold mode adds `--no-daemon`, `--no-parallel`, and a conservative worker cap. Warm mode is the normal path.

To stop the scoped daemon for a project:

```bash
./scripts/agent-gradle templates/java-gradle-cli --stop
```
