import { expect, test } from "bun:test";

import { DEFAULT_CONFIG } from "../src/config";
import { allowedHostHeaders, createHttpHandler } from "../src/http";
import { InMemoryStateStore } from "../src/state";

test("http handler serves health response", async () => {
  const config = {
    ...DEFAULT_CONFIG,
    transport: "http" as const,
  };
  const handler = createHttpHandler({
    config,
    stateStore: new InMemoryStateStore(),
  });

  const response = await handler(
    new Request("http://127.0.0.1:3000/health", {
      headers: { host: "127.0.0.1:3000" },
    }),
  );

  expect(response.status).toBe(200);
  await expect(response.json()).resolves.toEqual({
    status: "ok",
    transport: "http",
    state: "memory",
  });
});

test("http handler rejects unexpected host header", async () => {
  const config = {
    ...DEFAULT_CONFIG,
    transport: "http" as const,
  };
  const handler = createHttpHandler({
    config,
    stateStore: new InMemoryStateStore(),
  });

  const response = await handler(
    new Request("http://127.0.0.1:3000/health", {
      headers: { host: "evil.example:3000" },
    }),
  );

  expect(response.status).toBe(403);
  await expect(response.json()).resolves.toMatchObject({
    error: "host_not_allowed",
  });
});

test("allowed host headers include localhost aliases for the default bind", () => {
  expect([...allowedHostHeaders(DEFAULT_CONFIG)].sort()).toEqual([
    "127.0.0.1",
    "127.0.0.1:3000",
    "localhost",
    "localhost:3000",
  ]);
});
