# Java Gradle CLI Agent Notes

This is a copyable starter, not a long-lived framework.

## Commands

- Verify from repo root: `./scripts/agent-gradle templates/java-gradle-cli test`
- Full check from repo root: `./scripts/agent-gradle templates/java-gradle-cli check`
- Run from repo root: `./scripts/agent-gradle templates/java-gradle-cli run`
- If already inside this template: `../../scripts/agent-gradle . test`

## Rules

- Keep Java version changes in `gradle.properties`.
- Leave `useExactJavaToolchain=false` for normal agent runs; it avoids slow JDK provisioning while still compiling with `--release`.
- Keep product source files under `src/main` at 1000 lines or less.
- Use wildcard imports where feasible.
- Keep reusable checks in `supermeta-rules.json` and the shared Supermeta rule helper.
- Use the Supermeta Gradle harness for agent verification unless debugging raw Gradle behavior.
- Preserve the Gradle wrapper so the template is runnable without a global Gradle install.
- Keep `bootstrap-template.json` aligned with generated-project support paths and verification commands.
- Keep the sample app small and test-covered.
- Rename `com.example` before turning this into a real project.
- Prefer breaking the template contract cleanly over keeping weak starter conventions.
