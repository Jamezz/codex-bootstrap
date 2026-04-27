import pino, { type Logger } from "pino";
import pretty from "pino-pretty";

export type LogLevel = "trace" | "debug" | "info" | "warn" | "error" | "off";
export type LogFormat = "text" | "json";

export interface LoggingConfig {
  readonly level: LogLevel;
  readonly format: LogFormat;
}

export interface LoggerOptions {
  readonly appName?: string;
  readonly env?: Record<string, string | undefined>;
}

export class LoggingConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "LoggingConfigurationError";
  }
}

const DEFAULT_LOG_LEVEL = "warn";
const DEFAULT_LOG_FORMAT = "text";
const LOG_LEVELS = ["trace", "debug", "info", "warn", "error", "off"] as const;
const LOG_FORMATS = ["text", "json"] as const;

export function parseLoggingConfig(
  env: Record<string, string | undefined> = Bun.env,
): LoggingConfig {
  const level = normalizedEnvValue(env.LOG_LEVEL, DEFAULT_LOG_LEVEL);
  const format = normalizedEnvValue(env.LOG_FORMAT, DEFAULT_LOG_FORMAT);

  if (!isLogLevel(level)) {
    throw new LoggingConfigurationError(
      `invalid LOG_LEVEL ${JSON.stringify(env.LOG_LEVEL)}; expected one of: ${LOG_LEVELS.join(", ")}`,
    );
  }
  if (!isLogFormat(format)) {
    throw new LoggingConfigurationError(
      `invalid LOG_FORMAT ${JSON.stringify(env.LOG_FORMAT)}; expected one of: ${LOG_FORMATS.join(", ")}`,
    );
  }

  return { level, format };
}

export function createLogger(options: LoggerOptions = {}): Logger {
  const appName = options.appName ?? "typescript-bun-mcp-server";
  const config = parseLoggingConfig(options.env ?? Bun.env);
  const loggerOptions = {
    base: { app: appName },
    formatters: {
      level: (label: string) => ({ level: label }),
    },
    level: pinoLogLevel(config.level),
    messageKey: "message",
    timestamp: () => `,"timestamp":"${new Date().toISOString()}"`,
  };

  if (config.format === "json") {
    return pino(loggerOptions, pino.destination({ dest: 2, sync: true }));
  }

  return pino(
    loggerOptions,
    pretty({
      colorize: false,
      destination: 2,
      ignore: "pid,hostname",
      messageKey: "message",
      messageFormat: "{app} - {message}",
      sync: true,
      timestampKey: "timestamp",
      translateTime: "yyyy-mm-dd'T'HH:MM:ss.l'Z'",
    }),
  );
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

function isLogLevel(value: string): value is LogLevel {
  return LOG_LEVELS.includes(value as LogLevel);
}

function isLogFormat(value: string): value is LogFormat {
  return LOG_FORMATS.includes(value as LogFormat);
}

function pinoLogLevel(level: LogLevel): string {
  if (level === "off") {
    return "silent";
  }
  return level;
}
