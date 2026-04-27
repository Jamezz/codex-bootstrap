#!/usr/bin/env bun

import { render } from "./cli";

const result = render(Bun.argv.slice(2));

if (result.stdout.length > 0) {
  console.log(result.stdout);
}

if (result.stderr.length > 0) {
  console.error(result.stderr);
}

process.exit(result.exitCode);
