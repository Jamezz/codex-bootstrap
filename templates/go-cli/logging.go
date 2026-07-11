package main

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
)

type logLevel uint8

const (
	logTrace logLevel = iota
	logDebug
	logInfo
	logWarn
	logError
	logOff
)

type logFormat uint8

const (
	logText logFormat = iota
	logJSON
)

type Logger struct {
	level  logLevel
	format logFormat
	writer io.Writer
}

type LoggingConfigError struct {
	variable string
	value    string
	expected string
}

func NewLoggerFromEnv() (Logger, error) {
	levelValue, levelSet := os.LookupEnv("LOG_LEVEL")
	if !levelSet {
		levelValue = "warn"
	}
	level, ok := parseLogLevel(levelValue)
	if !ok {
		return Logger{}, LoggingConfigError{
			variable: "LOG_LEVEL",
			value:    levelValue,
			expected: "trace, debug, info, warn, error, or off",
		}
	}

	formatValue, formatSet := os.LookupEnv("LOG_FORMAT")
	if !formatSet {
		formatValue = "text"
	}
	format, ok := parseLogFormat(formatValue)
	if !ok {
		return Logger{}, LoggingConfigError{
			variable: "LOG_FORMAT",
			value:    formatValue,
			expected: "text or json",
		}
	}

	return Logger{level: level, format: format, writer: os.Stderr}, nil
}

func (errorValue LoggingConfigError) Error() string {
	return fmt.Sprintf("invalid %s %q; expected %s", errorValue.variable, errorValue.value, errorValue.expected)
}

func (logger Logger) Info(message string, fields map[string]any) {
	if !logger.enabled(logInfo) {
		return
	}

	if logger.format == logJSON {
		payload := map[string]any{
			"level":   "info",
			"message": message,
		}
		for key, value := range fields {
			payload[key] = value
		}
		encoded, err := json.Marshal(payload)
		if err != nil {
			fmt.Fprintf(logger.writer, "logging error: %s\n", err)
			return
		}
		fmt.Fprintln(logger.writer, string(encoded))
		return
	}

	fmt.Fprintf(logger.writer, "INFO %s", message)
	for key, value := range fields {
		fmt.Fprintf(logger.writer, " %s=%v", key, value)
	}
	fmt.Fprintln(logger.writer)
}

func (logger Logger) enabled(level logLevel) bool {
	return logger.level != logOff && level >= logger.level
}

func parseLogLevel(value string) (logLevel, bool) {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "trace":
		return logTrace, true
	case "debug":
		return logDebug, true
	case "info":
		return logInfo, true
	case "warn", "warning":
		return logWarn, true
	case "error":
		return logError, true
	case "off":
		return logOff, true
	default:
		return 0, false
	}
}

func parseLogFormat(value string) (logFormat, bool) {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "text":
		return logText, true
	case "json":
		return logJSON, true
	default:
		return 0, false
	}
}
