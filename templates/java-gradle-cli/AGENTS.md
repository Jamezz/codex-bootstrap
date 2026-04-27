# Java Gradle CLI Agent Notes

This is a copyable starter, not a long-lived framework.

## Commands

- Verify from repo root: `./scripts/agent-gradle templates/java-gradle-cli test`
- Full check from repo root: `./scripts/agent-gradle templates/java-gradle-cli check`
- Java lint from repo root: `./scripts/agent-gradle templates/java-gradle-cli checkstyleMain checkstyleTest`
- Run from repo root: `./scripts/agent-gradle templates/java-gradle-cli run`
- Run with app args from repo root: `./scripts/agent-gradle templates/java-gradle-cli run --args="Ada Lovelace"`
- Inspect generic task processes: `./scripts/agent-task ps --match gradle`
- List generic task logs: `./scripts/agent-task logs templates/java-gradle-cli/.gradle/supermeta-gradle/logs`
- Inspect stuck Gradle processes: `./scripts/agent-gradle templates/java-gradle-cli --ps`
- List harness logs: `./scripts/agent-gradle templates/java-gradle-cli --logs`
- Stop scoped Gradle daemon: `./scripts/agent-gradle templates/java-gradle-cli --stop`
- If already inside this template: `../../scripts/agent-gradle . test`

## Rules

- Keep Java version changes in `gradle.properties`.
- Keep Lombok version changes in `gradle.properties`.
- Leave `useExactJavaToolchain=false` for normal agent runs; it avoids slow JDK provisioning while still compiling with `--release`.
- If you rename `App`, update `application.mainClass` in `build.gradle.kts`.
- Keep product source files under `src/main` at 1000 lines or less.
- Keep Java package directories to 8 source files or fewer before nesting into subpackages.
- Use wildcard imports where feasible.
- Use Lombok where it keeps Java source compact; preserve compile-only and annotation-processor wiring.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Keep Java lint in Gradle Checkstyle with config under `config/checkstyle/`.
- Use the Supermeta Gradle harness for agent verification unless debugging raw Gradle behavior.
- Preserve the Gradle wrapper so the template is runnable without a global Gradle install.
- Keep `bootstrap-template.json` aligned with generated-project support paths and verification commands.
- Keep the sample CLI small and test-covered.
- Rename `com.example` before turning this into a real project.
- Prefer breaking the template contract cleanly over keeping weak starter conventions.
