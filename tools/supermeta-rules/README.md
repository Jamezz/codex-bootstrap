# Supermeta Rules

`check.py` is a small, dependency-free rule checker for bootstrap templates. Templates can use it from their own build systems instead of reimplementing catalog rules.

Run it from the repo root:

```bash
python3 tools/supermeta-rules/check.py --config templates/java-gradle-cli/supermeta-rules.json --root templates/java-gradle-cli
```

## Supported Rules

### `line_count`

Checks that matching files stay under a configured maximum line count.

```json
{
  "line_count": [
    {
      "name": "product-source",
      "max_lines": 1000,
      "paths": ["src/main"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"]
    }
  ]
}
```

### `java_package_file_count`

Checks that each Java package directory contains no more than a configured number of directly contained Java source files. Subpackages are counted independently.

```json
{
  "java_package_file_count": [
    {
      "name": "java-package-size",
      "max_files": 8,
      "paths": ["src/main/java", "src/test/java"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"]
    }
  ]
}
```

### `project_callouts`

Runs project-specific language tooling when matching files exist. Commands run from the configured project root and report a Supermeta finding when they exit non-zero.

```json
{
  "project_callouts": [
    {
      "name": "java-checkstyle",
      "language": "java",
      "paths": ["src/main/java", "src/test/java"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"],
      "command": ["../../scripts/agent-gradle", ".", "checkstyleMain", "checkstyleTest"]
    }
  ]
}
```

Use `--skip-callouts` or `SUPERMETA_SKIP_PROJECT_CALLOUTS=1` when the rule engine is already running from the tool it would call back into. Gradle templates use this to avoid nested Gradle execution.
