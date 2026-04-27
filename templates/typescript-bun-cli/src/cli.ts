export interface CliResult {
  readonly exitCode: number;
  readonly stdout: string;
  readonly stderr: string;
}

export const DEFAULT_NAME = "typescript-bun-cli";
export const USAGE = "Usage: typescript-bun-cli [name]";

export function render(
  args: readonly string[],
  defaultName = DEFAULT_NAME,
): CliResult {
  const [firstArg] = args;
  if (firstArg === "--help") {
    return {
      exitCode: 0,
      stdout: USAGE,
      stderr: "",
    };
  }

  const name = args.length === 0 ? defaultName : args.join(" ").trim();
  if (name.length === 0) {
    return {
      exitCode: 2,
      stdout: "",
      stderr: USAGE,
    };
  }

  return {
    exitCode: 0,
    stdout: `Hello from ${name}!`,
    stderr: "",
  };
}
