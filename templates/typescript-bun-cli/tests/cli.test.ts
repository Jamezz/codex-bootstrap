import { expect, test } from "bun:test";

import { render } from "../src/cli";

test("greets default project name", () => {
  expect(render([])).toEqual({
    exitCode: 0,
    stdout: "Hello from typescript-bun-cli!",
    stderr: "",
  });
});

test("greets provided name", () => {
  expect(render(["Ada", "Lovelace"])).toEqual({
    exitCode: 0,
    stdout: "Hello from Ada Lovelace!",
    stderr: "",
  });
});

test("renders help", () => {
  expect(render(["--help"])).toEqual({
    exitCode: 0,
    stdout: "Usage: typescript-bun-cli [name]",
    stderr: "",
  });
});

test("rejects blank name", () => {
  expect(render([" "])).toEqual({
    exitCode: 2,
    stdout: "",
    stderr: "Usage: typescript-bun-cli [name]",
  });
});
