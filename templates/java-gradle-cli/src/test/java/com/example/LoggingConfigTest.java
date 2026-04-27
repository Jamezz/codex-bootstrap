package com.example;

import static net.logstash.logback.argument.StructuredArguments.*;
import static org.junit.jupiter.api.Assertions.*;

import java.io.*;
import java.nio.charset.*;
import java.util.*;

import ch.qos.logback.classic.*;
import org.junit.jupiter.api.*;
import org.slf4j.*;

final class LoggingConfigTest {
    private PrintStream originalErr;

    @BeforeEach
    void captureOriginalErr() {
        originalErr = System.err;
    }

    @AfterEach
    void restoreErr() {
        System.setErr(originalErr);
        LoggingConfig.configure(new LoggingConfig.Config(Level.OFF, LoggingConfig.LogFormat.TEXT));
    }

    @Test
    void defaultsToQuietTextLogging() {
        LoggingConfig.Config config = LoggingConfig.fromEnvironment(Map.of());

        assertEquals(Level.WARN, config.level());
        assertEquals(LoggingConfig.LogFormat.TEXT, config.format());
    }

    @Test
    void parsesCaseInsensitiveValues() {
        LoggingConfig.Config config = LoggingConfig.fromEnvironment(Map.of(
            "LOG_LEVEL",
            "INFO",
            "LOG_FORMAT",
            "JSON"
        ));

        assertEquals(Level.INFO, config.level());
        assertEquals(LoggingConfig.LogFormat.JSON, config.format());
    }

    @Test
    void rejectsInvalidLevel() {
        IllegalArgumentException error = assertThrows(
            IllegalArgumentException.class,
            () -> LoggingConfig.fromEnvironment(Map.of("LOG_LEVEL", "verbose"))
        );

        assertTrue(error.getMessage().contains("LOG_LEVEL"));
    }

    @Test
    void rejectsInvalidFormat() {
        IllegalArgumentException error = assertThrows(
            IllegalArgumentException.class,
            () -> LoggingConfig.fromEnvironment(Map.of("LOG_FORMAT", "yaml"))
        );

        assertTrue(error.getMessage().contains("LOG_FORMAT"));
    }

    @Test
    void writesTextLogsToStderr() {
        ByteArrayOutputStream err = captureErr();

        LoggingConfig.configure(new LoggingConfig.Config(Level.INFO, LoggingConfig.LogFormat.TEXT));
        LoggerFactory.getLogger("java-gradle-cli")
            .info("command completed {}", keyValue("exitCode", 0));

        String output = err.toString(StandardCharsets.UTF_8);
        assertTrue(output.contains("INFO"));
        assertTrue(output.contains("java-gradle-cli"));
        assertTrue(output.contains("command completed exitCode=0"));
    }

    @Test
    void writesJsonLogsToStderr() {
        ByteArrayOutputStream err = captureErr();

        LoggingConfig.configure(new LoggingConfig.Config(Level.INFO, LoggingConfig.LogFormat.JSON));
        LoggerFactory.getLogger("java-gradle-cli")
            .info("command completed {}", keyValue("exitCode", 0));

        String output = err.toString(StandardCharsets.UTF_8);
        assertTrue(output.startsWith("{"));
        assertTrue(output.contains("\"timestamp\":"));
        assertTrue(output.contains("\"level\":\"INFO\""));
        assertTrue(output.contains("\"logger\":\"java-gradle-cli\""));
        assertTrue(output.contains("\"message\":\"command completed exitCode=0\""));
        assertTrue(output.contains("\"exitCode\":0"));
    }

    private ByteArrayOutputStream captureErr() {
        ByteArrayOutputStream err = new ByteArrayOutputStream();
        System.setErr(new PrintStream(err, true, StandardCharsets.UTF_8));
        return err;
    }
}
