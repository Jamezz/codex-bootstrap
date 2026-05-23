# Java Heuristic Scans Design

Date: 2026-05-23
Status: Approved design

## Purpose

The Java Gradle starter already documents two preferences: wildcard imports and Lombok-backed compact source. Those preferences should become hard template gates so generated Java projects reject import churn and handwritten getter, setter, or builder boilerplate by default.

The enhancement belongs in `tools/supermeta-rules/` because these are reusable heuristic scans, not one-off Gradle or Checkstyle policy. The Java starter should opt into the rules through `supermeta-rules.json`, and generated projects should receive the same enforcement through the existing bootstrap support-path copy.

## Scope

V1 adds two Java-specific Supermeta rules:

- `java_import_style`: rejects non-wildcard Java imports unless explicitly allowlisted.
- `java_lombok_boilerplate`: rejects source patterns that are better expressed with Lombok, with an optional ignore annotation escape hatch for intentional handwritten code.

The rules apply to configured Java source paths, including tests when the project config includes them. Generated code remains excluded through the same include and exclude model used by current Supermeta rules.

## Non-Goals

- Do not build or vendor a Java parser in V1.
- Do not require Java compilation or symbol resolution.
- Do not replace Checkstyle; keep Checkstyle for structural Java lint and keep Supermeta rules for template heuristics.
- Do not detect every possible constructor or domain factory pattern as Lombok boilerplate in V1.

## Architecture

`tools/supermeta-rules/check.py` remains the single scanner entrypoint. `run_rules()` should dispatch the existing rules plus the new Java rule families, and the unknown-rule validation should include the new keys.

Both Java rules should use the existing `paths`, `include`, and `exclude` contract. Findings should use the existing `Finding` shape, with paths relative to the configured root and messages that name the offending method or import.

The Java Gradle starter enables both rules in `templates/java-gradle-cli/supermeta-rules.json`. The starter source and generated documentation should be updated so the rule is described as enforced policy, not a soft convention.

## Rule: `java_import_style`

Config fields:

- `name`: rule name used in findings.
- `paths`: source roots or files to scan.
- `include`: defaults to `["**/*.java"]`.
- `exclude`: defaults to `[]`.
- `allow_explicit`: optional list of explicit import strings that remain allowed.

Behavior:

- Reject `import com.example.Type;`.
- Reject `import static com.example.Type.member;`.
- Allow `import com.example.*;`.
- Allow `import static com.example.Type.*;`.
- Ignore package declarations, comments, and non-import code.
- Compare allowlisted imports after trimming the leading `import`, optional `static`, trailing semicolon, and surrounding whitespace.

Example finding:

```text
[java-wildcard-imports] src/main/java/com/example/Foo.java: explicit import java.util.List; use java.util.* unless allowlisted
```

## Rule: `java_lombok_boilerplate`

Config fields:

- `name`: rule name used in findings.
- `paths`: source roots or files to scan.
- `include`: defaults to `["**/*.java"]`.
- `exclude`: defaults to `[]`.
- `allow_methods`: optional method-name allowlist for exceptional handwritten methods.
- `ignore_annotations`: optional annotation-name list for class-level or method-level exceptions.

Behavior:

- Reject simple getters: `getX()` or `isX()` methods that only return a field.
- Reject simple setters: `setX(value)` methods that only assign a field.
- Reject fluent setters that assign a field and return `this`.
- Reject nested builder classes or `builder()` factories when they follow repetitive field-setter plus `build()` patterns.
- Allow non-boilerplate methods with validation, normalization, logging, branching, external calls, or meaningful domain logic.
- Respect `allow_methods` for named methods that must remain handwritten.
- Respect `ignore_annotations` when the configured annotation appears on the method or enclosing class.

Annotation matching is source-level and should accept both simple and fully qualified forms. For example, a config value of `ManualBoilerplate` should match `@ManualBoilerplate`, and `com.acme.ManualBoilerplate` should match `@com.acme.ManualBoilerplate`. The default list is empty so new starters stay strict until a project intentionally creates an escape hatch.

Example config:

```json
{
  "java_lombok_boilerplate": [
    {
      "name": "java-lombok-boilerplate",
      "paths": ["src/main/java", "src/test/java"],
      "include": ["**/*.java"],
      "exclude": ["**/generated/**"],
      "ignore_annotations": ["ManualBoilerplate"],
      "allow_methods": []
    }
  ]
}
```

Example finding:

```text
[java-lombok-boilerplate] src/main/java/com/example/Foo.java: getName() is Lombok boilerplate; use Lombok or annotate the method/class with ManualBoilerplate if this is intentionally handwritten
```

## Heuristic Boundaries

The scanner should be deliberately conservative about what it flags as Lombok boilerplate. False negatives are acceptable in V1 when code shape is complex. False positives should be avoided because this rule is a hard gate.

Line comments and block comments should not trigger findings. String contents should not trigger findings. The implementation can use lightweight source stripping plus brace-aware method and class scanning instead of a full parser.

## Template Contract

The Java Gradle starter should enable:

```json
"java_import_style": [
  {
    "name": "java-wildcard-imports",
    "paths": ["src/main/java", "src/test/java"],
    "include": ["**/*.java"],
    "exclude": ["**/generated/**"],
    "allow_explicit": []
  }
],
"java_lombok_boilerplate": [
  {
    "name": "java-lombok-boilerplate",
    "paths": ["src/main/java", "src/test/java"],
    "include": ["**/*.java"],
    "exclude": ["**/generated/**"],
    "ignore_annotations": [],
    "allow_methods": []
  }
]
```

`templates/java-gradle-cli/src/main/java/com/example/LoggingConfig.java` currently uses several explicit imports and should be converted to wildcard imports as part of implementation. The existing Lombok wiring in `build.gradle.kts` and `gradle.properties` remains the starter baseline.

## Error Handling

Invalid config should raise `ValueError` with the same style as existing Supermeta rules:

- non-array rule groups fail with `<rule_key> must be an array`;
- `allow_explicit`, `allow_methods`, and `ignore_annotations` must be arrays of non-empty strings;
- unknown top-level keys still fail fast;
- unreadable files should surface through the normal file read error path.

When a project config sets an ignore annotation, findings should mention that annotation in the suggestion. When no ignore annotation is configured, findings should only recommend Lombok.

## Testing

Add focused tests in `tools/supermeta-rules/check_test.py`:

- wildcard imports pass;
- explicit normal imports fail;
- explicit static imports fail;
- allowlisted explicit imports pass;
- generated-source exclusions are honored;
- simple getters fail;
- boolean `isX()` getters fail;
- void setters fail;
- fluent setters fail;
- non-trivial methods pass;
- nested builder patterns fail;
- method-level ignore annotations suppress findings;
- class-level ignore annotations suppress findings;
- fully qualified ignore annotations match;
- invalid rule config fails clearly.

Run these verification commands after implementation:

```sh
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
./scripts/agent-gradle templates/java-gradle-cli check
```
