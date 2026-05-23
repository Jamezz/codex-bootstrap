# Java Gradle CLI Template

This template is a minimal Java command-line application with Gradle, JUnit tests, and a Codex-friendly verification path.
It includes first-class runtime logging through SLF4J and Logback with quiet text logs by default and JSON logs available through environment configuration.

It can be materialized from the catalog root with:

```bash
./bootstrap --template java-gradle-cli --name my-service --package com.example.myservice
```

After materialization, the generated project is standalone and uses:

```bash
./scripts/agent-gradle . check
./scripts/agent-gradle . run
```

## Prerequisites

- a shell environment that can run the Gradle wrapper;
- network access on first run so Gradle can download its distribution and dependencies.

The template defaults to Java 21 source/API compatibility and uses the installed JDK by default to avoid slow toolchain provisioning during agent runs.

## Usage

Run the app:

```bash
./gradlew run
```

Pass application arguments through Gradle:

```bash
./gradlew run --args="Ada Lovelace"
```

Run tests:

```bash
./gradlew test
```

Run the full check lifecycle:

```bash
./gradlew check
```

Run Java lint directly:

```bash
./gradlew checkstyleMain checkstyleTest
```

Enable runtime logs:

```bash
LOG_LEVEL=info ./gradlew run
LOG_LEVEL=info LOG_FORMAT=json ./gradlew run
```

`LOG_LEVEL` accepts `trace`, `debug`, `info`, `warn`, `error`, or `off`. `LOG_FORMAT` accepts `text` or `json`. Logs always go to stderr, and normal command output stays on stdout unless the CLI is reporting a user-facing error.

Agent-safe runs from the repository root:

```bash
./scripts/agent-gradle templates/java-gradle-cli test
./scripts/agent-gradle templates/java-gradle-cli check
./scripts/agent-gradle templates/java-gradle-cli checkstyleMain checkstyleTest
./scripts/agent-gradle templates/java-gradle-cli run
./scripts/agent-gradle templates/java-gradle-cli run --args="Ada Lovelace"
```

Stuck-build diagnostics from the repository root:

```bash
./scripts/agent-task ps --match gradle
./scripts/agent-task logs templates/java-gradle-cli/.gradle/supermeta-gradle/logs
./scripts/agent-gradle templates/java-gradle-cli --ps
./scripts/agent-gradle templates/java-gradle-cli --logs
./scripts/agent-gradle templates/java-gradle-cli --stop
```

PowerShell entrypoints are available for Windows agents:

```powershell
.\scripts\agent-gradle.ps1 templates/java-gradle-cli check
.\scripts\agent-gradle.ps1 templates/java-gradle-cli run
.\scripts\agent-task.ps1 ps --match gradle
.\scripts\agent-gradle.ps1 templates/java-gradle-cli --stop
```

Generated projects also include a pinned Beans wrapper and seeded starter backlog:

```bash
./scripts/agent-beans prime
./scripts/agent-beans list --ready
./scripts/agent-beans check
```

Agents should prefer the harness because it uses the checked-in wrapper with isolated shared Gradle state, no file watching, serialized runs, captured logs under `.gradle/supermeta-gradle/logs/`, and warm Gradle performance by default.

For parallel Gradle execution inside one build:

```bash
./scripts/agent-gradle templates/java-gradle-cli check --parallel --max-workers=4
```

## Customizing Java

Change the Java baseline in one place:

```properties
javaVersion=21
```

That value lives in `gradle.properties` and feeds `javac --release` in `build.gradle.kts`.

Change the Lombok baseline in the same file:

```properties
lombokVersion=1.18.44
```

Lombok is wired as a compile-only dependency and annotation processor for main and test source sets.

Change the logging dependency baselines in the same file:

```properties
slf4jVersion=2.0.17
logbackVersion=1.5.32
logstashLogbackEncoderVersion=9.0
```

When you need tests to run on an exact matching JDK, opt into Gradle toolchains:

```properties
useExactJavaToolchain=true
```

Leave exact toolchains off for normal agent verification unless the runtime JDK version itself is under test.

## Conventions

- production source files under `src/main` are checked for a 1000-line maximum;
- Java package directories are checked for an 8-source-file maximum before they should be split into subpackages;
- wildcard imports are enforced for Java source by Supermeta; use explicit imports only through `allow_explicit` in `supermeta-rules.json`;
- Lombok boilerplate checks reject handwritten getters, setters, and builder patterns; use Lombok annotations or a configured `ignore_annotations` escape hatch for rare intentional exceptions;
- if you rename `App`, update `application.mainClass` in `build.gradle.kts`.

The source limits and project callouts are configured in `supermeta-rules.json` and executed through the shared `tools/supermeta-rules/check.py` helper. Java lint uses Gradle Checkstyle with config in `config/checkstyle/checkstyle.xml`.

`bootstrap-template.json` declares the generated-project inputs, local support paths, and verification commands used by the root launcher.

The manifest also declares generated-doc metadata used to write `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/DECISIONS.md` after bootstrap.

## Project Shape

```text
src/main/java/com/example/App.java
src/main/java/com/example/LoggingConfig.java
src/test/java/com/example/AppTest.java
src/test/java/com/example/LoggingConfigTest.java
```

Replace `com.example` and extend the CLI behavior before starting real product work.
