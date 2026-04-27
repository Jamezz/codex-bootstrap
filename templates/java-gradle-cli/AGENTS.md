# Java Gradle CLI Agent Notes

This is a copyable starter, not a long-lived framework.

## Commands

- Verify: `./gradlew test`
- Run: `./gradlew run`

## Rules

- Keep Java version changes in `gradle.properties`.
- Keep product source files under `src/main` at 1000 lines or less.
- Use wildcard imports where feasible.
- Keep reusable checks in `supermeta-rules.json` and the shared Supermeta rule helper.
- Preserve the Gradle wrapper so the template is runnable without a global Gradle install.
- Keep the sample app small and test-covered.
- Rename `com.example` before turning this into a real project.
- Prefer breaking the template contract cleanly over keeping weak starter conventions.
