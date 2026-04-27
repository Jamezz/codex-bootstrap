#!/usr/bin/env bun

import type { Logger } from "pino";

import { render } from "./cli";
import { createLogger, LoggingConfigurationError } from "./logging";

let logger: Logger | undefined;
try {
  logger = createLogger();
} catch (error) {
  if (error instanceof LoggingConfigurationError) {
    console.error(`Logging configuration error: ${error.message}`);
    process.exitCode = 2;
  } else {
    throw error;
  }
}

if (logger !== undefined) {
  const result = render(Bun.argv.slice(2));

  if (result.stdout.length > 0) {
    console.log(result.stdout);
  }

  if (result.stderr.length > 0) {
    console.error(result.stderr);
  }

  logger.info({ exitCode: result.exitCode }, "command completed");
  process.exitCode = result.exitCode;
}
