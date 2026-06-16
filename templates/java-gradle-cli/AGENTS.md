# Java Gradle CLI Agent Notes

This is a copyable starter, not a long-lived framework.

## Commands

- Verify from repo root: `./scripts/agent-gradle templates/java-gradle-cli test`
- Full check from repo root: `./scripts/agent-gradle templates/java-gradle-cli check`
- Java lint from repo root: `./scripts/agent-gradle templates/java-gradle-cli checkstyleMain checkstyleTest`
- Run from repo root: `./scripts/agent-gradle templates/java-gradle-cli run`
- Run with app args from repo root: `./scripts/agent-gradle templates/java-gradle-cli run --args="Ada Lovelace"`
- Run with text logs: `cd templates/java-gradle-cli && LOG_LEVEL=info ../../scripts/agent-gradle . run`
- Run with JSON logs: `cd templates/java-gradle-cli && LOG_LEVEL=info LOG_FORMAT=json ../../scripts/agent-gradle . run`
- Beans prime after materialization: `./scripts/agent-beans prime`
- Beans check after materialization: `./scripts/agent-beans check`
- Announce coordination state: `./scripts/agent-coord announce --task "verification" --resource cpu:heavy`
- Inspect peer agents: `./scripts/agent-coord status`
- Serialize perf-sensitive work: `./scripts/agent-coord run --resource perf:exclusive -- ./scripts/agent-gradle templates/java-gradle-cli check`
- Inspect generic task processes: `./scripts/agent-task ps --match gradle`
- List generic task logs: `./scripts/agent-task logs templates/java-gradle-cli/.gradle/agent-capsules --glob '**/*.log'`
- Inspect stuck Gradle processes: `./scripts/agent-gradle templates/java-gradle-cli --ps`
- List harness logs: `./scripts/agent-gradle templates/java-gradle-cli --logs`
- Stop scoped Gradle daemon: `./scripts/agent-gradle templates/java-gradle-cli --stop`
- Inspect build capsule status: `./scripts/agent-gradle templates/java-gradle-cli --status`
- Repair build capsule caches: `./scripts/agent-gradle templates/java-gradle-cli --repair`
- Clean Supermeta rules cache: `./scripts/supermeta-cache clean --project templates/java-gradle-cli`
- If already inside this template: `../../scripts/agent-gradle . test`

## Windows

- Verify from repo root: `.\scripts\agent-gradle.ps1 templates/java-gradle-cli check`
- Run from repo root: `.\scripts\agent-gradle.ps1 templates/java-gradle-cli run`
- Inspect peer agents: `.\scripts\agent-coord.ps1 status`
- Inspect task processes: `.\scripts\agent-task.ps1 ps --match gradle`
- Stop scoped Gradle daemon: `.\scripts\agent-gradle.ps1 templates/java-gradle-cli --stop`
- Clean Supermeta rules cache: `.\scripts\supermeta-cache.ps1 clean --project templates/java-gradle-cli`
- After materialization, verify with `.\scripts\agent-gradle.ps1 . check`

## Rules

- Keep Java version changes in `gradle.properties`.
- Keep Lombok version changes in `gradle.properties`.
- Keep SLF4J, Logback, and logstash-logback-encoder version changes in `gradle.properties`.
- Leave `useExactJavaToolchain=false` for normal agent runs; it avoids slow JDK provisioning while still compiling with `--release`.
- If you rename `App`, update `application.mainClass` in `build.gradle.kts`.
- Keep runtime logging configured through `LoggingConfig`; `LOG_LEVEL` and `LOG_FORMAT` are the public knobs.
- Keep logs on stderr and normal command output on stdout.
- Keep product source files under `src/main` at 1000 lines or less.
- Keep Java package layers to 7 top-level types or fewer before nesting into context-shaped subpackages.
- Supermeta enforces wildcard imports for Java source; use `allow_explicit` only for deliberate exceptions.
- Supermeta rejects handwritten getter, setter, and builder boilerplate; for records, use and instantiate through Lombok `@Builder` patterns for maximum readability, and use Lombok annotations or a configured `ignore_annotations` escape hatch for rare intentional exceptions.
- Supermeta flags repeated Java helper methods; factor repeated helpers into common code instead of copying local utilities.
- Treat unused-import Checkstyle findings as warnings; clean them up, but do not make them a build-breaking gate.
- Preserve Lombok compile-only and annotation-processor wiring.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Keep generated-doc metadata and Beans support paths aligned in `bootstrap-template.json`.
- Keep Java lint in Gradle Checkstyle with config under `config/checkstyle/`.
- Use the Supermeta Gradle harness for agent verification unless debugging raw Gradle behavior.
- Preserve the Gradle wrapper so the template is runnable without a global Gradle install.
- Keep `bootstrap-template.json` aligned with generated-project support paths and verification commands.
- Keep the sample CLI small and test-covered.
- Rename `com.example` before turning this into a real project.
- Prefer breaking the template contract cleanly over keeping weak starter conventions.
