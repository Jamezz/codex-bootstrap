package com.example;

import java.util.*;

import ch.qos.logback.classic.encoder.*;
import ch.qos.logback.classic.spi.*;
import ch.qos.logback.core.*;
import ch.qos.logback.core.encoder.*;
import net.logstash.logback.encoder.*;
import net.logstash.logback.fieldnames.*;
import org.slf4j.*;

public final class LoggingConfig {
    private static final String DEFAULT_LOG_LEVEL = "warn";
    private static final String DEFAULT_LOG_FORMAT = "text";
    private static final Set<String> LOG_FORMATS = Set.of("text", "json");

    private LoggingConfig() {
    }

    public static Config fromEnvironment() {
        return fromEnvironment(System.getenv());
    }

    static Config fromEnvironment(Map<String, String> env) {
        String levelName = normalizedEnvValue(env, "LOG_LEVEL", DEFAULT_LOG_LEVEL);
        String formatName = normalizedEnvValue(env, "LOG_FORMAT", DEFAULT_LOG_FORMAT);

        ch.qos.logback.classic.Level level = switch (levelName) {
            case "trace" -> ch.qos.logback.classic.Level.TRACE;
            case "debug" -> ch.qos.logback.classic.Level.DEBUG;
            case "info" -> ch.qos.logback.classic.Level.INFO;
            case "warn" -> ch.qos.logback.classic.Level.WARN;
            case "error" -> ch.qos.logback.classic.Level.ERROR;
            case "off" -> ch.qos.logback.classic.Level.OFF;
            default -> throw new IllegalArgumentException(
                "invalid LOG_LEVEL " + quote(env.get("LOG_LEVEL"))
                    + "; expected one of: trace, debug, info, warn, error, off"
            );
        };

        if (!LOG_FORMATS.contains(formatName)) {
            throw new IllegalArgumentException(
                "invalid LOG_FORMAT " + quote(env.get("LOG_FORMAT")) + "; expected one of: json, text"
            );
        }

        return Config.builder()
            .level(level)
            .format(LogFormat.valueOf(formatName.toUpperCase(Locale.ROOT)))
            .build();
    }

    public static void configure(Config config) {
        ch.qos.logback.classic.LoggerContext context =
            (ch.qos.logback.classic.LoggerContext) LoggerFactory.getILoggerFactory();
        context.reset();

        ConsoleAppender<ILoggingEvent> appender = new ConsoleAppender<>();
        appender.setContext(context);
        appender.setName("stderr");
        appender.setTarget("System.err");
        appender.setEncoder(config.format() == LogFormat.JSON
            ? jsonEncoder(context)
            : textEncoder(context));
        appender.start();

        ch.qos.logback.classic.Logger root = context.getLogger(Logger.ROOT_LOGGER_NAME);
        root.detachAndStopAllAppenders();
        root.setLevel(config.level());
        root.addAppender(appender);
    }

    public static void configureFromEnvironment() {
        configure(fromEnvironment());
    }

    private static Encoder<ILoggingEvent> textEncoder(ch.qos.logback.classic.LoggerContext context) {
        PatternLayoutEncoder encoder = new PatternLayoutEncoder();
        encoder.setContext(context);
        encoder.setPattern("%d{yyyy-MM-dd'T'HH:mm:ss.SSSXXX} %-5level %logger{36} - %msg%n");
        encoder.start();
        return encoder;
    }

    private static Encoder<ILoggingEvent> jsonEncoder(ch.qos.logback.classic.LoggerContext context) {
        LogstashFieldNames fieldNames = new LogstashFieldNames();
        fieldNames.setTimestamp("timestamp");
        fieldNames.setLogger("logger");

        LogstashEncoder encoder = new LogstashEncoder();
        encoder.setContext(context);
        encoder.setFieldNames(fieldNames);
        encoder.start();
        return encoder;
    }

    private static String normalizedEnvValue(Map<String, String> env, String name, String defaultValue) {
        String value = env.get(name);
        if (value == null || value.isBlank()) {
            return defaultValue;
        }
        return value.strip().toLowerCase(Locale.ROOT);
    }

    private static String quote(String value) {
        return value == null ? "null" : "'" + value + "'";
    }

    enum LogFormat {
        TEXT,
        JSON
    }

    @lombok.Builder
    record Config(ch.qos.logback.classic.Level level, LogFormat format) {
    }
}
