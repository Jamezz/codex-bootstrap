package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestParseLogLevelAcceptsSupportedValues(t *testing.T) {
	for _, testCase := range []struct {
		value string
		want  logLevel
	}{
		{value: "trace", want: logTrace},
		{value: "warning", want: logWarn},
		{value: "off", want: logOff},
	} {
		got, ok := parseLogLevel(testCase.value)
		if !ok || got != testCase.want {
			t.Fatalf("parseLogLevel(%q) = (%v, %v), want (%v, true)", testCase.value, got, ok, testCase.want)
		}
	}
}

func TestParseLogLevelRejectsUnknownValues(t *testing.T) {
	if _, ok := parseLogLevel("verbose"); ok {
		t.Fatal("parseLogLevel(verbose) accepted an unsupported value")
	}
}

func TestLoggerWritesInfoAsJSON(t *testing.T) {
	var output bytes.Buffer
	logger := Logger{level: logInfo, format: logJSON, writer: &output}

	logger.Info("command completed", map[string]any{"exitCode": 0})

	text := output.String()
	if !strings.Contains(text, "\"level\":\"info\"") ||
		!strings.Contains(text, "\"message\":\"command completed\"") ||
		!strings.Contains(text, "\"exitCode\":0") {
		t.Fatalf("JSON log = %q, missing expected fields", text)
	}
}

func TestDefaultWarningLevelSuppressesInfo(t *testing.T) {
	var output bytes.Buffer
	logger := Logger{level: logWarn, format: logText, writer: &output}

	logger.Info("hidden", nil)

	if output.Len() != 0 {
		t.Fatalf("default warning logger wrote %q, want no output", output.String())
	}
}
