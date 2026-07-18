# Go CLI Template

Go CLI Template is a compact Go command-line project with unit tests, gofmt, go vet, first-class runtime logging, agent notes, and a deterministic verification path.

It can be materialized from the catalog root with:

~~~bash
./bootstrap --template go-cli --name my-service
~~~

After materialization, the generated project is standalone and uses:

~~~bash
./scripts/check
go run .
~~~

## Prerequisites

- Go 1.26 or newer on PATH, including gofmt;
- network access is not required because the starter has no external dependencies.

## Usage

Run the full verification lifecycle:

~~~bash
./scripts/check
~~~

Run tests:

~~~bash
go test ./...
~~~

Run the app:

~~~bash
go run .
go run . "Ada Lovelace"
~~~

Enable runtime logs:

~~~bash
LOG_LEVEL=info go run .
LOG_LEVEL=info LOG_FORMAT=json go run .
~~~

LOG_LEVEL accepts trace, debug, info, warn, error, or off. LOG_FORMAT accepts text or json. Logs always go to stderr, and normal command output stays on stdout unless the CLI is reporting a user-facing error.

Stuck-task diagnostics from the repository root:

~~~bash
./scripts/agent-task ps --match go
~~~

PowerShell entrypoints are available for Windows agents:

~~~powershell
cd templates/go-cli
.\\scripts\\check.ps1
go run .
..\\..\\scripts\\agent-task.ps1 ps --match go
~~~

Generated projects also include a pinned Beads wrapper and seeded starter backlog:

~~~bash
./scripts/agent-beads prime
./scripts/agent-beads ready --json
./scripts/agent-beads list
~~~

## Conventions

- production Go files are checked for a 1000-line maximum;
- gofmt owns formatting;
- go vet owns static correctness checks;
- go test ./... owns behavior checks;
- reusable checks and project callouts live in supermeta-rules.json and the shared tools/supermeta-rules/check.py helper.

bootstrap-template.json declares the generated-project inputs, local support paths, and verification commands used by the root launcher.

The manifest also declares generated-doc metadata used to write docs/ARCHITECTURE.md, docs/OPERATIONS.md, and docs/DECISIONS.md after bootstrap.

## Project Shape

~~~text
main.go
cli.go
logging.go
*_test.go
tools/check-gofmt/main.go
go.mod
~~~

Replace the sample CLI behavior before starting real product work.

