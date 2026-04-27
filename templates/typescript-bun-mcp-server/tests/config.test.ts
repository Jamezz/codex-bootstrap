import { expect, test } from "bun:test";

import { DEFAULT_CONFIG, parseConfig, USAGE } from "../src/config";

test("config defaults to stdio and memory state", () => {
  expectConfig(parseConfig([], {})).toEqual(DEFAULT_CONFIG);
});

test("config reads environment defaults", () => {
  expectConfig(
    parseConfig([], {
      MCP_TRANSPORT: "http",
      MCP_STATE: "file",
      MCP_STATE_FILE: "custom/state.json",
      MCP_HOST: "localhost",
      MCP_PORT: "3333",
    }),
  ).toEqual({
    transport: "http",
    state: "file",
    stateFile: "custom/state.json",
    host: "localhost",
    port: 3333,
  });
});

test("cli args override environment defaults", () => {
  expectConfig(
    parseConfig(
      [
        "--transport",
        "stdio",
        "--state",
        "memory",
        "--state-file",
        "cli.json",
        "--host",
        "127.0.0.1",
        "--port",
        "4444",
      ],
      {
        MCP_TRANSPORT: "http",
        MCP_STATE: "file",
        MCP_PORT: "3333",
      },
    ),
  ).toEqual({
    transport: "stdio",
    state: "memory",
    stateFile: "cli.json",
    host: "127.0.0.1",
    port: 4444,
  });
});

test("config renders help", () => {
  const result = parseConfig(["--help"], {});

  expect(result).toEqual({
    ok: false,
    exitCode: 0,
    stdout: USAGE,
    stderr: "",
  });
});

test("config rejects invalid values", () => {
  expect(parseConfig(["--transport", "websocket"], {})).toMatchObject({
    ok: false,
    exitCode: 2,
  });
  expect(parseConfig(["--port", "99999"], {})).toMatchObject({
    ok: false,
    exitCode: 2,
  });
  expect(parseConfig(["--state"], {})).toMatchObject({
    ok: false,
    exitCode: 2,
  });
});

test("main help exits without starting a server", () => {
  const result = Bun.spawnSync({
    cmd: ["bun", "run", "src/main.ts", "--help"],
    env: isolatedEnv(),
    stderr: "pipe",
    stdout: "pipe",
  });

  const decoder = new TextDecoder();
  const stdout = decoder.decode(result.stdout);
  expect(result.exitCode).toBe(0);
  expect(stdout).toContain("Usage: typescript-bun-mcp-server");
  expect(decoder.decode(result.stderr)).toBe("");
});

function expectConfig(result: ReturnType<typeof parseConfig>) {
  if (!result.ok) {
    throw new Error(result.stderr || result.stdout);
  }
  return expect(result.config);
}

function isolatedEnv(): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [key, value] of Object.entries(Bun.env)) {
    if (
      value !== undefined &&
      !key.startsWith("MCP_") &&
      key !== "LOG_LEVEL" &&
      key !== "LOG_FORMAT"
    ) {
      env[key] = value;
    }
  }
  return env;
}
