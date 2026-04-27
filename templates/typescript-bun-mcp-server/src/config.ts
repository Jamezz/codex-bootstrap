export type TransportMode = "stdio" | "http";
export type StateMode = "memory" | "file";

export interface ServerConfig {
  readonly transport: TransportMode;
  readonly state: StateMode;
  readonly stateFile: string;
  readonly host: string;
  readonly port: number;
}

export type ConfigParseResult =
  | {
      readonly ok: true;
      readonly config: ServerConfig;
    }
  | {
      readonly ok: false;
      readonly exitCode: number;
      readonly stdout: string;
      readonly stderr: string;
    };

type ConfigErrorResult = Extract<ConfigParseResult, { readonly ok: false }>;

export const DEFAULT_CONFIG: ServerConfig = {
  transport: "stdio",
  state: "memory",
  stateFile: ".mcp/state.json",
  host: "127.0.0.1",
  port: 3000,
};

export const USAGE = `Usage: typescript-bun-mcp-server [options]

Options:
  --transport <stdio|http>  MCP transport. Defaults to stdio or MCP_TRANSPORT.
  --state <memory|file>     State store. Defaults to memory or MCP_STATE.
  --state-file <path>       JSON state file for --state file. Defaults to .mcp/state.json or MCP_STATE_FILE.
  --host <host>             HTTP bind host. Defaults to 127.0.0.1 or MCP_HOST.
  --port <port>             HTTP port. Defaults to 3000 or MCP_PORT.
  --help                    Show this help.
`;

type MutableConfig = {
  transport: TransportMode;
  state: StateMode;
  stateFile: string;
  host: string;
  port: number;
};

const TRANSPORT_MODES = ["stdio", "http"] as const;
const STATE_MODES = ["memory", "file"] as const;

export function parseConfig(
  args: readonly string[],
  env: Record<string, string | undefined> = Bun.env,
): ConfigParseResult {
  const envConfig = parseEnvConfig(env);
  if (!envConfig.ok) {
    return envConfig;
  }

  const config: MutableConfig = { ...envConfig.config };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--help" || arg === "-h") {
      return { ok: false, exitCode: 0, stdout: USAGE, stderr: "" };
    }
    if (arg === "--transport") {
      const value = requireValue(args, index, arg);
      if (!value.ok) {
        return value;
      }
      const transport = parseTransportMode(value.value);
      if (transport === undefined) {
        return usageError(`invalid --transport ${JSON.stringify(value.value)}`);
      }
      config.transport = transport;
      index += 1;
      continue;
    }
    if (arg === "--state") {
      const value = requireValue(args, index, arg);
      if (!value.ok) {
        return value;
      }
      const state = parseStateMode(value.value);
      if (state === undefined) {
        return usageError(`invalid --state ${JSON.stringify(value.value)}`);
      }
      config.state = state;
      index += 1;
      continue;
    }
    if (arg === "--state-file") {
      const value = requireValue(args, index, arg);
      if (!value.ok) {
        return value;
      }
      if (value.value.trim().length === 0) {
        return usageError("--state-file cannot be blank");
      }
      config.stateFile = value.value;
      index += 1;
      continue;
    }
    if (arg === "--host") {
      const value = requireValue(args, index, arg);
      if (!value.ok) {
        return value;
      }
      if (value.value.trim().length === 0) {
        return usageError("--host cannot be blank");
      }
      config.host = value.value;
      index += 1;
      continue;
    }
    if (arg === "--port") {
      const value = requireValue(args, index, arg);
      if (!value.ok) {
        return value;
      }
      const port = parsePort(value.value);
      if (port === undefined) {
        return usageError(`invalid --port ${JSON.stringify(value.value)}`);
      }
      config.port = port;
      index += 1;
      continue;
    }
    return usageError(`unknown option ${JSON.stringify(arg)}`);
  }

  return { ok: true, config };
}

function parseEnvConfig(
  env: Record<string, string | undefined>,
): ConfigParseResult {
  const transport = parseTransportMode(
    normalizedEnvValue(env.MCP_TRANSPORT, DEFAULT_CONFIG.transport),
  );
  if (transport === undefined) {
    return usageError(
      `invalid MCP_TRANSPORT ${JSON.stringify(env.MCP_TRANSPORT)}`,
    );
  }

  const state = parseStateMode(
    normalizedEnvValue(env.MCP_STATE, DEFAULT_CONFIG.state),
  );
  if (state === undefined) {
    return usageError(`invalid MCP_STATE ${JSON.stringify(env.MCP_STATE)}`);
  }

  const port = parsePort(
    normalizedEnvValue(env.MCP_PORT, String(DEFAULT_CONFIG.port)),
  );
  if (port === undefined) {
    return usageError(`invalid MCP_PORT ${JSON.stringify(env.MCP_PORT)}`);
  }

  return {
    ok: true,
    config: {
      transport,
      state,
      stateFile: env.MCP_STATE_FILE?.trim() || DEFAULT_CONFIG.stateFile,
      host: env.MCP_HOST?.trim() || DEFAULT_CONFIG.host,
      port,
    },
  };
}

function requireValue(
  args: readonly string[],
  index: number,
  option: string,
):
  | {
      readonly ok: true;
      readonly value: string;
    }
  | ConfigErrorResult {
  const value = args[index + 1];
  if (value === undefined || value.startsWith("--")) {
    return usageError(`${option} requires a value`);
  }
  return { ok: true, value };
}

function normalizedEnvValue(
  value: string | undefined,
  defaultValue: string,
): string {
  if (value === undefined || value.trim().length === 0) {
    return defaultValue;
  }
  return value.trim().toLowerCase();
}

function parseTransportMode(value: string): TransportMode | undefined {
  return TRANSPORT_MODES.includes(value as TransportMode)
    ? (value as TransportMode)
    : undefined;
}

function parseStateMode(value: string): StateMode | undefined {
  return STATE_MODES.includes(value as StateMode)
    ? (value as StateMode)
    : undefined;
}

function parsePort(value: string): number | undefined {
  if (!/^[0-9]+$/.test(value)) {
    return undefined;
  }
  const port = Number(value);
  if (!Number.isInteger(port) || port < 0 || port > 65535) {
    return undefined;
  }
  return port;
}

function usageError(message: string): ConfigErrorResult {
  return {
    ok: false,
    exitCode: 2,
    stdout: "",
    stderr: `${message}\n\n${USAGE}`,
  };
}
