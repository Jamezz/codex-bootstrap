import { expect, test } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { InMemoryStateStore, JsonFileStateStore } from "../src/state";

test("memory store supports put, get, list, delete, and clear", async () => {
  const store = new InMemoryStateStore();

  await store.put("beta", "two");
  await store.put("alpha", "one");

  expect(await store.get("alpha")).toMatchObject({
    key: "alpha",
    value: "one",
  });
  expect((await store.list()).map((entry) => entry.key)).toEqual([
    "alpha",
    "beta",
  ]);
  expect((await store.list({ prefix: "a" })).map((entry) => entry.key)).toEqual(
    ["alpha"],
  );
  expect(await store.delete("alpha")).toBe(true);
  expect(await store.delete("alpha")).toBe(false);
  await store.clear();
  expect(await store.list()).toEqual([]);
});

test("json file store persists across instances", async () => {
  const root = await mkdtemp(join(tmpdir(), "bun-mcp-state-"));
  const filePath = join(root, "state", "data.json");
  try {
    const writer = new JsonFileStateStore(filePath);
    await writer.put("alpha", "one");
    await writer.put("beta", "two");

    const reader = new JsonFileStateStore(filePath);
    expect(await reader.get("alpha")).toMatchObject({
      key: "alpha",
      value: "one",
    });
    expect((await reader.list()).map((entry) => entry.key)).toEqual([
      "alpha",
      "beta",
    ]);
  } finally {
    await rm(root, { force: true, recursive: true });
  }
});
