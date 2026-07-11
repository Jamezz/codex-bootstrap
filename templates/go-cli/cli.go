package main

import "strings"

func RenderGreeting(args []string) string {
	parts := make([]string, 0, len(args))
	for _, arg := range args {
		if trimmed := strings.TrimSpace(arg); trimmed != "" {
			parts = append(parts, trimmed)
		}
	}

	name := strings.Join(parts, " ")
	if name == "" {
		name = "world"
	}

	return "Hello, " + name + "!"
}
