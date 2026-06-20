# Supermeta Rules

`check.py` is a small rule checker for generated projects. Core rules that do not need parsers stay standard-library-only; parser-backed rules such as `repeated_helper_methods` use the optional pinned dependencies in `tools/supermeta-rules/requirements.txt`. Templates can call the checker from their own build systems instead of reimplementing shared rules.

Run it from a generated project root:

```bash
python3 tools/supermeta-rules/check.py --config supermeta-rules.json --root .
```

When working inside the Codex Bootstrap catalog itself, pass a template config and template root:

```bash
python3 tools/supermeta-rules/check.py --config templates/java-gradle-cli/supermeta-rules.json --root templates/java-gradle-cli
```

Rule `paths` may point at a broad repo area, but keep `include` patterns rooted at the real source or test trees. The matcher streams those include globs first and then applies final include/exclude filtering, so broad adoption configs do not have to scan build outputs, vendored trees, or generated artifacts before finding source files.

By default, the checker detects the Git working set for the configured root. When staged, unstaged, untracked, or branch-local files are found, file-local rules scan only those matching files. Cross-file aggregate rules, such as Java package sizing, JavaScript package sizing, and Lombok record-constructor enforcement, still scan the full configured tree to avoid false negatives. If Git cannot provide a reliable non-empty working set, the checker falls back to a full scan.

The checker keeps a Git-metadata counter and promotes the next automatic working-set run to a full scan after 10 fast scans for the same root. Set `SUPERMETA_RULES_FAST_SCAN_INTERVAL=<positive integer>` to tune that cadence for local diagnostics.

Use `--full` or `SUPERMETA_RULES_FULL=1` when a run must scan every matching file regardless of Git state.

## Persistent Analysis Cache

Expensive per-file analysis is cached by default under `.gradle/supermeta-rules/cache-v1.json`, or under the path named
by `SUPERMETA_RULES_CACHE_FILE`. Gradle-backed projects should pass the cache file explicitly and declare it as a task
output so unchanged rule inputs can be skipped by Gradle and unchanged source files can be reused by the checker.

```bash
python3 tools/supermeta-rules/check.py \
  --config supermeta-rules.json \
  --root . \
  --cache-file .gradle/supermeta-rules/cache-v1.json
```

Use `--cache-report` to print hit, miss, stale, write, and eviction counts. Use `--no-cache` only when validating cache
behavior or bisecting a scanner bug.

Gradle-backed projects expose a targeted cache clean task:

```bash
./scripts/supermeta-cache clean
./scripts/agent-gradle . cleanSupermetaRulesCache
./scripts/agent-gradle . verifySupermetaRulesClean
./scripts/agent-gradle . --clean-supermeta-cache verifySupermetaRules
```

Cache keys include the relative file path, file digest, rule id, rule options, and tool fingerprint. Changing
`supermeta-rules.json`, the scanner implementation, or optional parser dependencies invalidates affected entries instead
of reusing stale analysis.

The CLI streams rule progress and discovered findings to stderr while keeping the final pass/fail summary on stdout. Set `SUPERMETA_RULES_QUIET=1` to suppress progress output in contexts that need a quiet checker.

## Supported Rules

Every rule object supports an optional `enabled` boolean. Omitted means enabled. Set `"enabled": false` to leave a disabled rule in config as a visible placeholder; disabled rules are skipped before rule-specific required fields are validated.

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
      "exclude": ["**/generated/**"],
      "narrow_to_working_set": true
    }
  ]
}
```

Set `narrow_to_working_set` to `false` for small, high-signal layout surfaces that should be scanned every run even
when only one file changed.

### `java_package_class_count`

Checks that each Java package layer contains no more than a configured number of directly contained top-level Java types. Subpackages are counted independently, and nested classes inside a top-level type do not count against the package layer.

```json
{
  "java_package_class_count": [
    {
      "name": "java-package-size",
      "max_classes": 7,
      "paths": ["src/main/java", "src/test/java"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"]
    }
  ]
}
```

### `javascript_package_file_count`

Checks that each JavaScript or TypeScript package layer contains no more than a configured number of directly contained source files. Subdirectories are counted independently, matching the Java package-size rule so frontend and TUI code is forced into cohesive directories instead of broad catch-all folders.

Set `min_package_depth` when source roots should behave like Java source roots: files must live under at least that many package directories beneath each configured `path`. For example, `"paths": ["src"]` with `"min_package_depth": 1` allows `src/tui/app.tsx` but rejects `src/app.tsx`.

```json
{
  "javascript_package_file_count": [
    {
      "name": "javascript-package-size",
      "max_files": 7,
      "min_package_depth": 1,
      "paths": ["src", "test"],
      "include": ["**/*.ts", "**/*.tsx", "**/*.js", "**/*.jsx"],
      "exclude": ["**/generated/**", "**/node_modules/**"]
    }
  ]
}
```

### `repeated_helper_methods`

Checks for helper methods that have been copied instead of factored into common code. Java is the first supported language. The rule uses Tree-sitter, so enabled Java projects must install `tools/supermeta-rules/requirements.txt`.

Exact normalized duplicates are blocking findings. Near matches are advisory by default and do not fail the run.

```json
{
  "repeated_helper_methods": [
    {
      "name": "repeated-helper-methods",
      "language": "java",
      "groups": [
        {
          "name": "main",
          "paths": ["src/main/java"],
          "include": ["**/*.java"],
          "exclude": ["**/generated/**"]
        },
        {
          "name": "test",
          "paths": ["src/test/java"],
          "include": ["**/*.java"],
          "exclude": ["**/generated/**"]
        }
      ],
      "min_statements": 3,
      "near_match_threshold": 0.86,
      "advisory_near_matches": true,
      "ignore_annotations": ["Generated", "ManualDuplication"],
      "allow_methods": []
    }
  ]
}
```

Groups compare independently, so production helpers do not compare with test helpers. Future Python, TypeScript, Rust, and C# adapters should reuse the same config shape and shared fuzzy-comparison pipeline.

### `rust_module_item_count`

Checks that each Rust source module stays below a configured number of top-level items before it should be split around a clearer domain boundary. Test modules named `tests` are ignored.

```json
{
  "rust_module_item_count": [
    {
      "name": "rust-module-size",
      "max_items": 7,
      "paths": ["src"],
      "include": ["**/*.rs"],
      "exclude": ["**/generated/**"]
    }
  ]
}
```

### `rust_panic_boundary`

Rejects panic-prone constructs in production Rust source: `.unwrap(`, `.expect(`, `todo!`, `unimplemented!`, and `dbg!`. By default, `#[cfg(test)] mod tests` blocks are ignored so tests can stay direct.

```json
{
  "rust_panic_boundary": [
    {
      "name": "rust-panic-boundary",
      "paths": ["src"],
      "include": ["**/*.rs"],
      "exclude": ["**/generated/**"],
      "allow_tests": true
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

Python and TypeScript templates use the same rule shape for language-specific checks:

```json
{
  "project_callouts": [
    {
      "name": "python-typecheck",
      "language": "python",
      "paths": ["src", "tests"],
      "include": ["**/*.py"],
      "exclude": ["**/generated/**"],
      "command": ["uv", "run", "mypy", "src", "tests"]
    },
    {
      "name": "typescript-typecheck",
      "language": "typescript",
      "paths": ["src", "tests"],
      "include": ["**/*.ts"],
      "exclude": ["**/generated/**"],
      "command": ["bun", "run", "typecheck"]
    }
  ]
}
```

Use `--skip-callouts` or `SUPERMETA_SKIP_PROJECT_CALLOUTS=1` when the rule engine is already running from the tool it would call back into. Gradle templates use this to avoid nested Gradle execution.
