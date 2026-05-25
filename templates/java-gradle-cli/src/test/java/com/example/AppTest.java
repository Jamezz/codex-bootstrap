package com.example;

import static org.junit.jupiter.api.Assertions.*;

import java.io.*;
import java.nio.charset.*;

import org.junit.jupiter.api.*;

final class AppTest {
    @Test
    void greetsDefaultProjectName() {
        CliResult result = runApp();

        assertEquals(0, result.exitCode());
        assertEquals("Hello from java-gradle-cli!" + System.lineSeparator(), result.out());
        assertEquals("", result.err());
    }

    @Test
    void greetsProvidedName() {
        CliResult result = runApp("Ada", "Lovelace");

        assertEquals(0, result.exitCode());
        assertEquals("Hello from Ada Lovelace!" + System.lineSeparator(), result.out());
        assertEquals("", result.err());
    }

    @Test
    void rendersHelp() {
        CliResult result = runApp("--help");

        assertEquals(0, result.exitCode());
        assertEquals("Usage: java-gradle-cli [name]" + System.lineSeparator(), result.out());
        assertEquals("", result.err());
    }

    @Test
    void rejectsBlankName() {
        CliResult result = runApp(" ");

        assertEquals(2, result.exitCode());
        assertEquals("", result.out());
        assertEquals("Usage: java-gradle-cli [name]" + System.lineSeparator(), result.err());
    }

    private CliResult runApp(String... args) {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ByteArrayOutputStream err = new ByteArrayOutputStream();
        int exitCode = new App("java-gradle-cli").run(
            args,
            new PrintStream(out, true, StandardCharsets.UTF_8),
            new PrintStream(err, true, StandardCharsets.UTF_8)
        );
        return CliResult.builder()
            .exitCode(exitCode)
            .out(out.toString(StandardCharsets.UTF_8))
            .err(err.toString(StandardCharsets.UTF_8))
            .build();
    }

    @lombok.Builder
    private record CliResult(int exitCode, String out, String err) {
    }
}
