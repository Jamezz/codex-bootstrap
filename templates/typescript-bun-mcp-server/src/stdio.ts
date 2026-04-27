import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import type { Logger } from "pino";

import { createMcpServer } from "./mcp";
import type { StateStore } from "./state";

export interface StdioRuntimeOptions {
  readonly stateStore: StateStore;
  readonly logger?: Logger;
}

export async function runStdioServer(
  options: StdioRuntimeOptions,
): Promise<void> {
  const server = createMcpServer({ stateStore: options.stateStore });
  const transport = new StdioServerTransport();
  options.logger?.info("stdio mcp server starting");
  await server.connect(transport);
}
