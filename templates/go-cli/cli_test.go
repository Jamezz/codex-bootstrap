package main

import "testing"

func TestRenderGreetingUsesWorldByDefault(t *testing.T) {
	if got := RenderGreeting(nil); got != "Hello, world!" {
		t.Fatalf("RenderGreeting(nil) = %q, want %q", got, "Hello, world!")
	}
}

func TestRenderGreetingJoinsAndTrimsArguments(t *testing.T) {
	if got := RenderGreeting([]string{" Ada ", "Lovelace "}); got != "Hello, Ada Lovelace!" {
		t.Fatalf("RenderGreeting(args) = %q, want %q", got, "Hello, Ada Lovelace!")
	}
}

func TestRenderGreetingTreatsBlankArgumentsAsWorld(t *testing.T) {
	if got := RenderGreeting([]string{"  "}); got != "Hello, world!" {
		t.Fatalf("RenderGreeting(blank) = %q, want %q", got, "Hello, world!")
	}
}
