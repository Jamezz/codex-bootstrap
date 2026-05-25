# Rust Cargo CLI Template

This template is a minimal Rust command-line application with Cargo, unit tests, Clippy, rustfmt, and a Codex-friendly verification path.
It includes first-class runtime logging through a dependency-free starter module with quiet text logs by default and JSON logs available through environment configuration.

It can be materialized from the catalog root with:

```bash
./bootstrap --template rust-cargo-cli --name my-service
```

After materialization, the generated project is standalone and uses:

```bash
./scripts/check
cargo run --quiet
```

## Prerequisites

- Rust toolchain 1.85 or newer on PATH;
- Cargo, rustfmt, and Clippy installed with the toolchain.

The template targets Rust edition 2024 and keeps the starter dependency-free.

## Usage

Run the full check lifecycle:

```bash
./scripts/check
```

Run tests:

```bash
cargo test
```

Run Rust lint and format checks directly:

```bash
cargo fmt --all --check
cargo clippy --all-targets -- -D warnings
```

Run the app:

```bash
cargo run --quiet
cargo run --quiet -- "Ada Lovelace"
```

Enable runtime logs:

```bash
LOG_LEVEL=info cargo run --quiet
LOG_LEVEL=info LOG_FORMAT=json cargo run --quiet
```

`LOG_LEVEL` accepts `trace`, `debug`, `info`, `warn`, `error`, or `off`. `LOG_FORMAT` accepts `text` or `json`. Logs always go to stderr, and normal command output stays on stdout unless the CLI is reporting a user-facing error.

Stuck-task diagnostics from the repository root:

```bash
./scripts/agent-task ps --match cargo
./scripts/agent-task ps --match rustc
```

PowerShell entrypoints are available for Windows agents:

```powershell
cd templates/rust-cargo-cli
.\scripts\check.ps1
cargo run --quiet
.\..\..\scripts\agent-task.ps1 ps --match cargo
```

Generated projects also include a pinned Beans wrapper and seeded starter backlog:

```bash
./scripts/agent-beans prime
./scripts/agent-beans list --ready
./scripts/agent-beans check
```

## Conventions

- production source files under `src/` are checked for a 1000-line maximum;
- Rust source modules are checked for a 7 top-level production item maximum;
- production Rust source rejects `.unwrap()`, `.expect()`, `todo!()`, `unimplemented!()`, and `dbg!()`;
- rustfmt owns formatting;
- Clippy owns linting with warnings denied;
- Cargo owns build and test execution;
- reusable checks and project callouts live in `supermeta-rules.json` and the shared `tools/supermeta-rules/check.py` helper.

`bootstrap-template.json` declares the generated-project inputs, local support paths, and verification commands used by the root launcher.

The manifest also declares generated-doc metadata used to write `docs/ARCHITECTURE.md`, `docs/OPERATIONS.md`, and `docs/DECISIONS.md` after bootstrap.

## Project Shape

```text
src/main.rs
src/cli.rs
src/logging.rs
Cargo.toml
Cargo.lock
```

Replace the sample CLI behavior before starting real product work.
