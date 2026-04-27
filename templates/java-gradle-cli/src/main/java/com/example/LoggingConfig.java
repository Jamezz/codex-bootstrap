package com.example;

import java.util.*;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.LoggerContext;
import ch.qos.logback.classic.encoder.PatternLayoutEncoder;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.ConsoleAppender;
import ch.qos.logback.core.encoder.Encoder;
import net.logstash.logback.encoder.LogstashEncoder;
import net.logstash.logback.fieldnames.LogstashFieldNames;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

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

        Level level = switch (levelName) {
            case "trace" -> Level.TRACE;
            case "debug" -> Level.DEBUG;
            case "info" -> Level.INFO;
            case "warn" -> Level.WARN;
            case "error" -> Level.ERROR;
            case "off" -> Level.OFF;
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

        return new Config(level, LogFormat.valueOf(formatName.toUpperCase(Locale.ROOT)));
    }

    public static void configure(Config config) {
        LoggerContext context = (LoggerContext) LoggerFactory.getILoggerFactory();
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

    private static Encoder<ILoggingEvent> textEncoder(LoggerContext context) {
        PatternLayoutEncoder encoder = new PatternLayoutEncoder();
        encoder.setContext(context);
        encoder.setPattern("%d{yyyy-MM-dd'T'HH:mm:ss.SSSXXX} %-5level %logger{36} - %msg%n");
        encoder.start();
        return encoder;
    }

    private static Encoder<ILoggingEvent> jsonEncoder(LoggerContext context) {
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

    record Config(Level level, LogFormat format) {
    }
}
