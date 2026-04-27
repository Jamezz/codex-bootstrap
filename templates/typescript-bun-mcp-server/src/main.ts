#!/usr/bin/env bun

import { parseConfig } from "./config";
import { startHttpServer } from "./http";
import { createLogger, LoggingConfigurationError } from "./logging";
import { createStateStore } from "./state";
import { runStdioServer } from "./stdio";

const parsed = parseConfig(Bun.argv.slice(2));
if (!parsed.ok) {
  if (parsed.stdout.length > 0) {
    console.log(parsed.stdout.trimEnd());
  }
  if (parsed.stderr.length > 0) {
    console.error(parsed.stderr.trimEnd());
  }
  process.exitCode = parsed.exitCode;
} else {
  try {
    const logger = createLogger();
    const stateStore = createStateStore(parsed.config);
    if (parsed.config.transport === "http") {
      startHttpServer({ config: parsed.config, stateStore, logger });
    } else {
      await runStdioServer({ stateStore, logger });
    }
  } catch (error) {
    if (error instanceof LoggingConfigurationError) {
      console.error(`Logging configuration error: ${error.message}`);
      process.exitCode = 2;
    } else {
      throw error;
    }
  }
}
