package main

import (
	"fmt"
	"os"
)

func main() {
	logger, err := NewLoggerFromEnv()
	if err != nil {
		fmt.Fprintf(os.Stderr, "Logging configuration error: %s\n", err)
		os.Exit(2)
	}

	fmt.Fprintln(os.Stdout, RenderGreeting(os.Args[1:]))
	logger.Info("command completed", map[string]any{"exitCode": 0})
}
