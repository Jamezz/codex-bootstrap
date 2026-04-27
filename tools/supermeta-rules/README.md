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
