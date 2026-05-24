"""Generated velocity-tool docs and smart-check policies."""

from __future__ import annotations

import json
from pathlib import Path


def generated_velocity_readme_region(check_command_text: str) -> str:
    return f"""<!-- codex-bootstrap:begin generated-docs/velocity-tools -->
## Velocity Tools

Use the fast inner-loop verifier during development:

```bash
./scripts/agent-smart-check --plan-only
./scripts/agent-smart-check --fast-only
./scripts/agent-fix-loop --timeout 600 -- ./scripts/agent-smart-check
```

Run the full gate before handoff:

```bash
{check_command_text}
```

Generated lanes live in `.codex-bootstrap/checks.json`. Downstream-only lanes belong in `.codex-bootstrap/checks.local.json`.
<!-- codex-bootstrap:end generated-docs/velocity-tools -->
"""


def generated_velocity_agent_region(check_command_text: str) -> str:
    return f"""<!-- codex-bootstrap:begin generated-docs/velocity-tools -->
## Velocity Tools

- Use `./scripts/agent-smart-check --self-test` after changing `.codex-bootstrap/checks*.json`.
- Use `./scripts/agent-fix-loop --timeout 600 -- ./scripts/agent-smart-check` for fast inner-loop verification.
- Use `{check_command_text}` before handoff; focused lanes are not a release gate.
- Put downstream-only smart-check lanes in `.codex-bootstrap/checks.local.json`.
- Keep lane metadata current: `cost`, `tags`, `requires`, and `timeoutSeconds`.
- Do not let `agent-fix-loop` mutate source or lockfiles in v1.
<!-- codex-bootstrap:end generated-docs/velocity-tools -->
"""


def generated_velocity_operations_region(check_command_text: str) -> str:
    return f"""<!-- codex-bootstrap:begin generated-docs/velocity-tools -->
## Velocity Tools

Plan focused lanes:

```bash
./scripts/agent-smart-check --plan-only
```

Validate the lane contract:

```bash
./scripts/agent-smart-check --self-test
```

Capture and classify a failing inner loop:

```bash
./scripts/agent-fix-loop --timeout 600 -- ./scripts/agent-smart-check
```

Run the full handoff gate:

```bash
{check_command_text}
```

Generated lanes live in `.codex-bootstrap/checks.json`. Put project-only lane overrides in `.codex-bootstrap/checks.local.json`.
<!-- codex-bootstrap:end generated-docs/velocity-tools -->
"""


def write_checks_policy_file(template_id: str, template_type: str, staged_root: Path) -> None:
    codex_dir = staged_root / ".codex-bootstrap"
    codex_dir.mkdir(parents=True, exist_ok=True)
    (codex_dir / "checks.json").write_text(
        format_checks_policy(default_checks_policy(template_id, template_type)) + "\n",
        encoding="utf-8",
    )


def format_checks_policy(policy: dict[str, object]) -> str:
    return format_json_value(policy, 0)


def format_json_value(value: object, indent: int) -> str:
    inline = inline_json_value(value)
    if inline is not None and len(inline) + indent <= 80:
        return inline
    prefix = " " * indent
    child_prefix = " " * (indent + 2)
    if isinstance(value, dict):
        lines = ["{"]
        items = sorted(value.items())
        for index, (key, child) in enumerate(items):
            comma = "," if index < len(items) - 1 else ""
            lines.append(f"{child_prefix}{json.dumps(key)}: {format_json_value(child, indent + 2)}{comma}")
        lines.append(f"{prefix}}}")
        return "\n".join(lines)
    if isinstance(value, list):
        lines = ["["]
        for index, child in enumerate(value):
            comma = "," if index < len(value) - 1 else ""
            lines.append(f"{child_prefix}{format_json_value(child, indent + 2)}{comma}")
        lines.append(f"{prefix}]")
        return "\n".join(lines)
    return json.dumps(value)


def inline_json_value(value: object) -> str | None:
    if isinstance(value, list) and all(is_json_scalar(item) for item in value):
        return json.dumps(value, separators=(", ", ": "))
    if isinstance(value, list) and all(
        isinstance(item, list) and all(is_json_scalar(child) for child in item)
        for item in value
    ):
        return json.dumps(value, separators=(", ", ": "))
    return None


def is_json_scalar(value: object) -> bool:
    return value is None or isinstance(value, str | int | float | bool)


def default_checks_policy(template_id: str, template_type: str) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "templateId": template_id,
        "lanes": default_check_lanes(template_type),
    }


def default_check_lanes(template_type: str) -> list[dict[str, object]]:
    if template_type == "java-gradle-cli":
        return [
            lane(
                "java-test",
                "Java source or tests changed.",
                ["src/main/java/**/*.java", "src/test/java/**/*.java"],
                [["./scripts/agent-gradle", ".", "test"]],
                cost="fast",
                tags=["java", "test"],
                requires=["java"],
                timeout_seconds=180,
            ),
            lane(
                "java-style",
                "Java style or Checkstyle config changed.",
                ["src/main/java/**/*.java", "src/test/java/**/*.java", "config/checkstyle/**/*.xml"],
                [["./scripts/agent-gradle", ".", "checkstyleMain", "checkstyleTest"]],
                cost="standard",
                tags=["java", "style", "quality"],
                requires=["java"],
                timeout_seconds=180,
            ),
            full_lane("Complete Java verification.", [["./scripts/agent-gradle", ".", "check"]], ["java"], 600),
        ]
    if template_type == "python-uv-cli":
        return [
            lane(
                "python-test",
                "Python source or tests changed.",
                ["src/**/*.py", "tests/**/*.py"],
                [["uv", "run", "--no-editable", "pytest"]],
                cost="fast",
                tags=["python", "test"],
                requires=["uv"],
                timeout_seconds=120,
            ),
            lane(
                "python-quality",
                "Python quality config or typed source changed.",
                ["src/**/*.py", "tests/**/*.py", "pyproject.toml", "supermeta-rules.json"],
                [
                    command(["uv", "run", "ruff", "check", "src", "tests"], timeout_seconds=60),
                    command(["uv", "run", "mypy", "src", "tests"], timeout_seconds=180),
                ],
                cost="standard",
                tags=["python", "quality", "typecheck"],
                requires=["uv"],
                timeout_seconds=240,
            ),
            full_lane("Complete Python verification.", [["./scripts/check"]], ["uv"], 600),
        ]
    if template_type == "csharp-dotnet-cli":
        return [
            lane(
                "dotnet-test",
                "C# source or tests changed.",
                ["src/**/*.cs", "tests/**/*.cs"],
                [["./scripts/agent-dotnet", ".", "test"]],
                cost="fast",
                tags=["dotnet", "test"],
                requires=["dotnet"],
                timeout_seconds=180,
            ),
            lane(
                "dotnet-quality",
                "C# project or package configuration changed.",
                ["*.slnx", "Directory.*.props", "src/**/*.csproj", "tests/**/*.csproj"],
                [["./scripts/check"]],
                cost="standard",
                tags=["dotnet", "quality"],
                requires=["dotnet"],
                timeout_seconds=300,
            ),
            full_lane("Complete C# verification.", [["./scripts/check"]], ["dotnet"], 600),
        ]
    if template_type == "typescript-bun-mcp-server":
        source_paths = [
            "src/mcp.ts",
            "src/http.ts",
            "src/stdio.ts",
            "src/state.ts",
            "src/config.ts",
            "src/**/*.ts",
            "tests/**/*.ts",
        ]
    else:
        source_paths = ["src/**/*.ts", "tests/**/*.ts"]
    return [
        lane(
            "typescript-test",
            "TypeScript source or tests changed.",
            source_paths,
            [["bun", "test"]],
            cost="fast",
            tags=["typescript", "test"],
            requires=["bun"],
            timeout_seconds=120,
        ),
        lane(
            "typescript-quality",
            "TypeScript quality config or typed source changed.",
            source_paths + ["package.json", "tsconfig.json", "biome.json"],
            [["bun", "run", "typecheck"], ["bun", "run", "lint"]],
            cost="standard",
            tags=["typescript", "quality", "typecheck"],
            requires=["bun"],
            timeout_seconds=240,
        ),
        full_lane("Complete TypeScript verification.", [["./scripts/check"]], ["bun"], 600),
    ]


def lane(
    lane_id: str,
    description: str,
    paths: list[str],
    commands: list[object],
    cost: str,
    tags: list[str],
    requires: list[str],
    timeout_seconds: int,
) -> dict[str, object]:
    return {
        "id": lane_id,
        "description": description,
        "cost": cost,
        "tags": tags,
        "requires": requires,
        "timeoutSeconds": timeout_seconds,
        "triggers": {"paths": paths},
        "commands": commands,
        "escalatesTo": "full",
    }


def full_lane(description: str, commands: list[object], requires: list[str], timeout_seconds: int) -> dict[str, object]:
    return {
        "id": "full",
        "description": description,
        "cost": "full",
        "tags": ["full"],
        "requires": requires,
        "timeoutSeconds": timeout_seconds,
        "commands": commands,
    }


def command(argv: list[str], timeout_seconds: int) -> dict[str, object]:
    return {"argv": argv, "timeoutSeconds": timeout_seconds}
