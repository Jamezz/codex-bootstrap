# Java Gradle CLI Template

This template is a minimal Java command-line application with Gradle, JUnit tests, and a Codex-friendly verification path.

## Prerequisites

- a shell environment that can run the Gradle wrapper;
- network access on first run so Gradle can download dependencies and, if needed, a matching Java toolchain.

The template defaults to Java 21.

## Usage

Run the app:

```bash
./gradlew run
```

Run tests:

```bash
./gradlew test
```

Run the full check lifecycle:

```bash
./gradlew check
```

## Customizing Java

Change the Java baseline in one place:

```properties
javaVersion=21
```

That value lives in `gradle.properties` and feeds the Gradle toolchain configuration in `build.gradle.kts`.

## Conventions

- production source files under `src/main` are checked for a 1000-line maximum;
- wildcard imports are acceptable and preferred when they keep Java files cleaner.

The source limit is configured in `supermeta-rules.json` and executed by Gradle through the shared `tools/supermeta-rules/check.py` helper.

## Project Shape

```text
src/main/java/com/example/App.java
src/test/java/com/example/AppTest.java
```

Replace `com.example` and the greeting before starting real product work.
