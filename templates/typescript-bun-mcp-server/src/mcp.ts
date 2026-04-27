import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import * as z from "zod/v4";

import type { StateStore } from "./state";

export const DEFAULT_SERVER_NAME = "typescript-bun-mcp-server";
export const DEFAULT_SERVER_VERSION = "0.1.0";

export interface McpServerOptions {
  readonly stateStore: StateStore;
  readonly name?: string;
  readonly version?: string;
}

export function createMcpServer(options: McpServerOptions): McpServer {
  const server = new McpServer({
    name: options.name ?? DEFAULT_SERVER_NAME,
    version: options.version ?? DEFAULT_SERVER_VERSION,
  });
  const stateStore = options.stateStore;

  server.registerTool(
    "echo",
    {
      title: "Echo",
      description: "Return the provided message, optionally uppercased.",
      inputSchema: {
        message: z.string().min(1),
        uppercase: z.boolean().optional(),
      },
    },
    async ({ message, uppercase }) => {
      const text = uppercase === true ? message.toUpperCase() : message;
      return {
        content: [{ type: "text", text }],
        structuredContent: { message: text },
      };
    },
  );

  server.registerTool(
    "state_put",
    {
      title: "Put State",
      description: "Store a string value by key.",
      inputSchema: {
        key: z.string().min(1),
        value: z.string(),
      },
    },
    async ({ key, value }) => {
      const entry = await stateStore.put(key, value);
      return {
        content: [{ type: "text", text: `stored ${key}` }],
        structuredContent: stateEntryContent(entry),
      };
    },
  );

  server.registerTool(
    "state_get",
    {
      title: "Get State",
      description: "Read a stored value by key.",
      inputSchema: {
        key: z.string().min(1),
      },
    },
    async ({ key }) => {
      const entry = await stateStore.get(key);
      if (entry === undefined) {
        return {
          content: [{ type: "text", text: `${key} was not found` }],
          structuredContent: { key, found: false },
        };
      }
      return {
        content: [{ type: "text", text: entry.value }],
        structuredContent: { key, found: true, value: entry.value },
      };
    },
  );

  server.registerTool(
    "state_list",
    {
      title: "List State",
      description: "List stored entries, optionally filtered by key prefix.",
      inputSchema: {
        prefix: z.string().optional(),
      },
    },
    async ({ prefix }) => {
      const entries = await stateStore.list(
        prefix === undefined ? {} : { prefix },
      );
      return {
        content: [
          {
            type: "text",
            text: JSON.stringify({ entries }, null, 2),
          },
        ],
        structuredContent: { entries },
      };
    },
  );

  server.registerTool(
    "state_delete",
    {
      title: "Delete State",
      description: "Delete a stored value by key.",
      inputSchema: {
        key: z.string().min(1),
      },
    },
    async ({ key }) => {
      const deleted = await stateStore.delete(key);
      return {
        content: [
          {
            type: "text",
            text: deleted ? `deleted ${key}` : `${key} was not found`,
          },
        ],
        structuredContent: { key, deleted },
      };
    },
  );

  server.registerResource(
    "state_snapshot",
    "state://snapshot",
    {
      title: "State Snapshot",
      description: "Current state store contents as JSON.",
      mimeType: "application/json",
    },
    async (uri) => {
      const entries = await stateStore.list();
      return {
        contents: [
          {
            uri: uri.href,
            mimeType: "application/json",
            text: JSON.stringify({ entries }, null, 2),
          },
        ],
      };
    },
  );

  server.registerPrompt(
    "summarize_state",
    {
      title: "Summarize State",
      description: "Ask a client model to summarize the current state keys.",
    },
    async () => {
      const entries = await stateStore.list();
      const keys = entries.map((entry) => entry.key);
      return {
        description: "Summarize the current MCP state store.",
        messages: [
          {
            role: "user",
            content: {
              type: "text",
              text: `Summarize these state keys and note any obvious grouping: ${JSON.stringify(keys)}.`,
            },
          },
        ],
      };
    },
  );

  return server;
}

function stateEntryContent(entry: {
  readonly key: string;
  readonly value: string;
  readonly updatedAt: string;
}): Record<string, unknown> {
  return {
    key: entry.key,
    value: entry.value,
    updatedAt: entry.updatedAt,
  };
}
