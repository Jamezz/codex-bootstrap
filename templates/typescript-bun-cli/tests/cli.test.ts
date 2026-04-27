import { expect, test } from "bun:test";

import { render } from "../src/cli";
import { LoggingConfigurationError, parseLoggingConfig } from "../src/logging";

test("greets default project name", () => {
  expect(render([])).toEqual({
    exitCode: 0,
    stdout: "Hello from typescript-bun-cli!",
    stderr: "",
  });
});

test("greets provided name", () => {
  expect(render(["Ada", "Lovelace"])).toEqual({
    exitCode: 0,
    stdout: "Hello from Ada Lovelace!",
    stderr: "",
  });
});

test("renders help", () => {
  expect(render(["--help"])).toEqual({
    exitCode: 0,
    stdout: "Usage: typescript-bun-cli [name]",
    stderr: "",
  });
});

test("rejects blank name", () => {
  expect(render([" "])).toEqual({
    exitCode: 2,
    stdout: "",
    stderr: "Usage: typescript-bun-cli [name]",
  });
});

test("logging config defaults to quiet text", () => {
  expect(parseLoggingConfig({})).toEqual({
    level: "warn",
    format: "text",
  });
});

test("logging config parses case-insensitive values", () => {
  expect(parseLoggingConfig({ LOG_LEVEL: "OFF", LOG_FORMAT: "JSON" })).toEqual({
    level: "off",
    format: "json",
  });
});

test("logging config rejects invalid level", () => {
  expect(() => parseLoggingConfig({ LOG_LEVEL: "verbose" })).toThrow(
    LoggingConfigurationError,
  );
});

test("logging config rejects invalid format", () => {
  expect(() => parseLoggingConfig({ LOG_FORMAT: "yaml" })).toThrow(
    LoggingConfigurationError,
  );
});

test("main keeps default run output quiet", () => {
  const result = runMain();

  expect(result.exitCode).toBe(0);
  expect(result.stdout).toBe("Hello from typescript-bun-cli!\n");
  expect(result.stderr).toBe("");
});

test("main writes text log when info is enabled", () => {
  const result = runMain({ LOG_LEVEL: "info", LOG_FORMAT: "text" });

  expect(result.exitCode).toBe(0);
  expect(result.stdout).toBe("Hello from typescript-bun-cli!\n");
  expect(result.stderr).toContain("INFO");
  expect(result.stderr).toContain("typescript-bun-cli - command completed");
  expect(result.stderr).toContain("exitCode: 0");
});

test("main writes json log when json is enabled", () => {
  const result = runMain({ LOG_LEVEL: "info", LOG_FORMAT: "json" });

  expect(result.exitCode).toBe(0);
  const event = JSON.parse(result.stderr.trim()) as Record<string, unknown>;
  expect(event.level).toBe("info");
  expect(event.app).toBe("typescript-bun-cli");
  expect(event.message).toBe("command completed");
  expect(event.exitCode).toBe(0);
});

test("main fails fast on invalid logging config", () => {
  const result = runMain({ LOG_LEVEL: "verbose" });

  expect(result.exitCode).toBe(2);
  expect(result.stdout).toBe("");
  expect(result.stderr).toContain(
    "Logging configuration error: invalid LOG_LEVEL",
  );
});

function runMain(env: Record<string, string | undefined> = {}) {
  const runEnv: Record<string, string> = {};
  for (const [key, value] of Object.entries(Bun.env)) {
    if (value !== undefined && key !== "LOG_LEVEL" && key !== "LOG_FORMAT") {
      runEnv[key] = value;
    }
  }
  for (const [key, value] of Object.entries(env)) {
    if (value !== undefined) {
      runEnv[key] = value;
    }
  }

  const result = Bun.spawnSync({
    cmd: ["bun", "run", "src/main.ts"],
    env: runEnv,
    stderr: "pipe",
    stdout: "pipe",
  });
  const decoder = new TextDecoder();
  return {
    exitCode: result.exitCode,
    stdout: decoder.decode(result.stdout),
    stderr: decoder.decode(result.stderr),
  };
}
