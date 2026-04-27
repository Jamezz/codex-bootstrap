import { WebStandardStreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/webStandardStreamableHttp.js";
import type { Logger } from "pino";

import type { ServerConfig } from "./config";
import { createMcpServer } from "./mcp";
import type { StateStore } from "./state";

export interface HttpRuntimeOptions {
  readonly config: ServerConfig;
  readonly stateStore: StateStore;
  readonly logger?: Logger;
}

export type HttpHandler = (request: Request) => Promise<Response>;

export function createHttpHandler(options: HttpRuntimeOptions): HttpHandler {
  return async (request: Request): Promise<Response> => {
    const hostResult = validateHost(request, options.config);
    if (!hostResult.allowed) {
      return jsonResponse(
        { error: "host_not_allowed", host: hostResult.host },
        { status: 403 },
      );
    }

    const url = new URL(request.url);
    if (url.pathname === "/health" && request.method === "GET") {
      return jsonResponse({
        status: "ok",
        transport: "http",
        state: options.config.state,
      });
    }

    if (url.pathname === "/mcp") {
      const transport = new WebStandardStreamableHTTPServerTransport();
      const server = createMcpServer({ stateStore: options.stateStore });
      await server.connect(transport);
      return transport.handleRequest(request);
    }

    return jsonResponse({ error: "not_found" }, { status: 404 });
  };
}

export function startHttpServer(
  options: HttpRuntimeOptions,
): ReturnType<typeof Bun.serve> {
  const server = Bun.serve({
    fetch: createHttpHandler(options),
    hostname: options.config.host,
    port: options.config.port,
  });
  options.logger?.info(
    {
      host: server.hostname,
      port: server.port,
      state: options.config.state,
    },
    "http mcp server listening",
  );
  return server;
}

export function allowedHostHeaders(config: ServerConfig): ReadonlySet<string> {
  const hosts = new Set<string>();
  const normalizedHost = config.host.toLowerCase();
  addHostVariants(hosts, normalizedHost, config.port);
  if (normalizedHost === "127.0.0.1") {
    addHostVariants(hosts, "localhost", config.port);
  }
  if (normalizedHost === "localhost") {
    addHostVariants(hosts, "127.0.0.1", config.port);
  }
  return hosts;
}

function validateHost(
  request: Request,
  config: ServerConfig,
):
  | {
      readonly allowed: true;
      readonly host: string;
    }
  | {
      readonly allowed: false;
      readonly host: string | null;
    } {
  const host = request.headers.get("host");
  if (host === null) {
    return { allowed: false, host };
  }
  const normalizedHost = host.toLowerCase();
  return {
    allowed: allowedHostHeaders(config).has(normalizedHost),
    host,
  };
}

function addHostVariants(hosts: Set<string>, host: string, port: number): void {
  hosts.add(host);
  hosts.add(`${host}:${port}`);
}

function jsonResponse(
  body: Record<string, unknown>,
  init: ResponseInit = {},
): Response {
  return new Response(JSON.stringify(body), {
    ...init,
    headers: {
      "content-type": "application/json",
      ...init.headers,
    },
  });
}
