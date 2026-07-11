# Go CLI Agent Notes

This is a standalone Go CLI project. Keep it compact, test-covered, and easy for the next agent to verify.

## Commands

- Verify: ./scripts/check
- Format check: go run ./tools/check-gofmt
- Vet: go vet ./...
- Test: go test ./...
- Run: go run .
- Run with app args: go run . "Ada Lovelace"
- Run with text logs: LOG_LEVEL=info go run .
- Run with JSON logs: LOG_LEVEL=info LOG_FORMAT=json go run .
- Beans prime: ./scripts/agent-beans prime
- Beans check: ./scripts/agent-beans check
- Ready backlog: ./scripts/agent-beans list --ready
- Announce coordination state: ./scripts/agent-coord announce --task "verification" --resource cpu:heavy
- Inspect peer agents: ./scripts/agent-coord status
- Serialize perf-sensitive work: ./scripts/agent-coord run --resource perf:exclusive -- ./scripts/check
- Inspect Go processes: ./scripts/agent-task ps --match go

## Windows

- Verify: .\\scripts\\check.ps1
- Run: go run .
- Beans prime: .\\scripts\\agent-beans.ps1 prime
- Inspect peer agents: .\\scripts\\agent-coord.ps1 status
- Inspect Go processes: .\\scripts\\agent-task.ps1 ps --match go

## Rules

- Target Go 1.26 through go.mod unless the project intentionally chooses a different runtime floor.
- Keep CLI behavior in cli.go and process setup in main.go.
- Keep runtime logging in logging.go; LOG_LEVEL and LOG_FORMAT are the public knobs.
- Keep default logging quiet: LOG_LEVEL=warn and LOG_FORMAT=text.
- Keep logs on stderr and normal command output on stdout.
- Fail fast with exit code 2 when logging configuration is invalid.
- Keep product source files under 1000 lines or less.
- Keep reusable checks and project callouts in supermeta-rules.json and the shared Supermeta rule helper.
- Route formatting through gofmt, static checks through go vet, and behavior checks through go test ./...
- Use ./scripts/check for agent verification unless debugging one tool directly.
- Keep the starter dependency-free until product requirements justify a module dependency.
- Extend the sample CLI into real behavior early, and keep tests updated with that change.
- Prefer clean new-project conventions over compatibility with starter mistakes.
