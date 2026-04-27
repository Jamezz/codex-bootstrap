import { expect, test } from "bun:test";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { InMemoryTransport } from "@modelcontextprotocol/sdk/inMemory.js";

import { createMcpServer } from "../src/mcp";
import { InMemoryStateStore } from "../src/state";

test("mcp server exposes tools, state resource, and prompt", async () => {
  const stateStore = new InMemoryStateStore();
  const server = createMcpServer({
    stateStore,
    name: "test-server",
    version: "0.1.0",
  });
  const client = new Client({
    name: "test-client",
    version: "0.1.0",
  });
  const [clientTransport, serverTransport] =
    InMemoryTransport.createLinkedPair();

  await server.connect(serverTransport);
  await client.connect(clientTransport);
  try {
    const tools = await client.listTools();
    expect(tools.tools.map((tool) => tool.name).sort()).toEqual([
      "echo",
      "state_delete",
      "state_get",
      "state_list",
      "state_put",
    ]);

    const echo = await client.callTool({
      name: "echo",
      arguments: { message: "hello", uppercase: true },
    });
    expect(echo.structuredContent).toEqual({ message: "HELLO" });

    const put = await client.callTool({
      name: "state_put",
      arguments: { key: "alpha", value: "one" },
    });
    expect(put.structuredContent).toMatchObject({
      key: "alpha",
      value: "one",
    });

    const get = await client.callTool({
      name: "state_get",
      arguments: { key: "alpha" },
    });
    expect(get.structuredContent).toEqual({
      key: "alpha",
      found: true,
      value: "one",
    });

    const snapshot = await client.readResource({ uri: "state://snapshot" });
    const firstContent = snapshot.contents[0];
    expect(firstContent).toMatchObject({
      uri: "state://snapshot",
      mimeType: "application/json",
    });
    if (firstContent === undefined || !("text" in firstContent)) {
      throw new Error("expected text resource content");
    }
    expect(firstContent.text).toContain('"alpha"');

    const prompt = await client.getPrompt({ name: "summarize_state" });
    expect(prompt.messages[0]?.content).toMatchObject({
      type: "text",
    });
    const promptText = prompt.messages[0]?.content;
    if (promptText === undefined || !("text" in promptText)) {
      throw new Error("expected text prompt content");
    }
    expect(promptText.text).toContain("alpha");
  } finally {
    await client.close();
    await server.close();
  }
});
