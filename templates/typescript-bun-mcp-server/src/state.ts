import { randomUUID } from "node:crypto";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname } from "node:path";

import type { ServerConfig } from "./config";

export interface StateEntry {
  readonly key: string;
  readonly value: string;
  readonly updatedAt: string;
}

export interface StateListOptions {
  readonly prefix?: string;
}

export interface StateStore {
  get(key: string): Promise<StateEntry | undefined>;
  put(key: string, value: string): Promise<StateEntry>;
  delete(key: string): Promise<boolean>;
  list(options?: StateListOptions): Promise<readonly StateEntry[]>;
  clear(): Promise<void>;
}

export class StateStoreError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StateStoreError";
  }
}

export class InMemoryStateStore implements StateStore {
  private readonly entries = new Map<string, StateEntry>();

  async get(key: string): Promise<StateEntry | undefined> {
    return this.entries.get(key);
  }

  async put(key: string, value: string): Promise<StateEntry> {
    const entry = {
      key,
      value,
      updatedAt: new Date().toISOString(),
    };
    this.entries.set(key, entry);
    return entry;
  }

  async delete(key: string): Promise<boolean> {
    return this.entries.delete(key);
  }

  async list(options: StateListOptions = {}): Promise<readonly StateEntry[]> {
    const entries = [...this.entries.values()];
    const filtered =
      options.prefix === undefined
        ? entries
        : entries.filter((entry) => entry.key.startsWith(options.prefix ?? ""));
    return filtered.sort((left, right) => left.key.localeCompare(right.key));
  }

  async clear(): Promise<void> {
    this.entries.clear();
  }
}

export class JsonFileStateStore implements StateStore {
  private readonly entries = new Map<string, StateEntry>();
  private loaded = false;

  constructor(private readonly filePath: string) {}

  async get(key: string): Promise<StateEntry | undefined> {
    await this.ensureLoaded();
    return this.entries.get(key);
  }

  async put(key: string, value: string): Promise<StateEntry> {
    await this.ensureLoaded();
    const entry = {
      key,
      value,
      updatedAt: new Date().toISOString(),
    };
    this.entries.set(key, entry);
    await this.persist();
    return entry;
  }

  async delete(key: string): Promise<boolean> {
    await this.ensureLoaded();
    const deleted = this.entries.delete(key);
    if (deleted) {
      await this.persist();
    }
    return deleted;
  }

  async list(options: StateListOptions = {}): Promise<readonly StateEntry[]> {
    await this.ensureLoaded();
    const entries = [...this.entries.values()];
    const filtered =
      options.prefix === undefined
        ? entries
        : entries.filter((entry) => entry.key.startsWith(options.prefix ?? ""));
    return filtered.sort((left, right) => left.key.localeCompare(right.key));
  }

  async clear(): Promise<void> {
    await this.ensureLoaded();
    this.entries.clear();
    await this.persist();
  }

  private async ensureLoaded(): Promise<void> {
    if (this.loaded) {
      return;
    }

    let text: string;
    try {
      text = await readFile(this.filePath, "utf-8");
    } catch (error) {
      if (isNodeError(error) && error.code === "ENOENT") {
        this.loaded = true;
        return;
      }
      throw error;
    }

    const parsed = JSON.parse(text) as unknown;
    this.entries.clear();
    for (const entry of decodeStateFile(parsed)) {
      this.entries.set(entry.key, entry);
    }
    this.loaded = true;
  }

  private async persist(): Promise<void> {
    await mkdir(dirname(this.filePath), { recursive: true });
    const payload = {
      version: 1,
      entries: Object.fromEntries(
        [...this.entries.entries()].sort(([left], [right]) =>
          left.localeCompare(right),
        ),
      ),
    };
    const tempPath = `${this.filePath}.${randomUUID()}.tmp`;
    await writeFile(tempPath, `${JSON.stringify(payload, null, 2)}\n`, "utf-8");
    await rename(tempPath, this.filePath);
  }
}

export function createStateStore(config: ServerConfig): StateStore {
  if (config.state === "file") {
    return new JsonFileStateStore(config.stateFile);
  }
  return new InMemoryStateStore();
}

function decodeStateFile(value: unknown): readonly StateEntry[] {
  if (!isRecord(value) || !isRecord(value.entries)) {
    throw new StateStoreError("state file must contain an entries object");
  }

  const entries: StateEntry[] = [];
  for (const [key, rawEntry] of Object.entries(value.entries)) {
    if (!isRecord(rawEntry)) {
      throw new StateStoreError(
        `state entry ${JSON.stringify(key)} must be an object`,
      );
    }
    if (
      typeof rawEntry.value !== "string" ||
      typeof rawEntry.updatedAt !== "string"
    ) {
      throw new StateStoreError(
        `state entry ${JSON.stringify(key)} must contain string value and updatedAt fields`,
      );
    }
    entries.push({
      key,
      value: rawEntry.value,
      updatedAt: rawEntry.updatedAt,
    });
  }
  return entries;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNodeError(error: unknown): error is NodeJS.ErrnoException {
  return error instanceof Error && "code" in error;
}
