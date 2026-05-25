# Rust Cargo CLI Agent Notes

This is a standalone Rust Cargo CLI project. Keep it compact, test-covered, and easy for the next agent to verify.

## Commands

- Verify: `./scripts/check`
- Format check: `cargo fmt --all --check`
- Lint: `cargo clippy --all-targets -- -D warnings`
- Test: `cargo test`
- Run: `cargo run --quiet`
- Run with app args: `cargo run --quiet -- "Ada Lovelace"`
- Run with text logs: `LOG_LEVEL=info cargo run --quiet`
- Run with JSON logs: `LOG_LEVEL=info LOG_FORMAT=json cargo run --quiet`
- Beans prime: `./scripts/agent-beans prime`
- Beans check: `./scripts/agent-beans check`
- Ready backlog: `./scripts/agent-beans list --ready`
- Announce coordination state: `./scripts/agent-coord announce --task "verification" --resource cpu:heavy`
- Inspect peer agents: `./scripts/agent-coord status`
- Serialize perf-sensitive work: `./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check`
- Inspect Cargo or Rust processes: `./scripts/agent-task ps --match cargo` or `./scripts/agent-task ps --match rustc`

## Windows

- Verify: `.\scripts\check.ps1`
- Run: `cargo run --quiet`
- Beans prime: `.\scripts\agent-beans.ps1 prime`
- Inspect peer agents: `.\scripts\agent-coord.ps1 status`
- Inspect Cargo processes: `.\scripts\agent-task.ps1 ps --match cargo`

## Rules

- Keep the starter dependency-free until product requirements justify a crate.
- Keep CLI behavior in `src/cli.rs` and entrypoint glue in `src/main.rs`.
- Keep runtime logging in `src/logging.rs`; `LOG_LEVEL` and `LOG_FORMAT` are the public knobs.
- Keep default logging quiet: `LOG_LEVEL=warn` and `LOG_FORMAT=text`.
- Keep logs on stderr and normal command output on stdout.
- Fail fast with exit code 2 when logging configuration is invalid.
- Keep product source files under `src/` at 1000 lines or less.
- Keep Rust source modules at 7 top-level production items or fewer before splitting around cohesive domain boundaries.
- Do not use `.unwrap()`, `.expect()`, `todo!()`, `unimplemented!()`, or `dbg!()` in production Rust paths; return `Result`, handle `Option`, or keep panic behavior inside tests.
- Keep reusable checks and project callouts in `supermeta-rules.json` and the shared Supermeta rule helper.
- Route formatting through `cargo fmt`, lint through Clippy with warnings denied, and behavior checks through `cargo test`.
- Use `./scripts/check` for agent verification unless debugging one tool directly.
- Keep `Cargo.lock` checked in for CLI applications.
- Extend the sample CLI into real behavior early, and keep tests updated with that change.
- Prefer clean new-project conventions over compatibility with starter mistakes.
