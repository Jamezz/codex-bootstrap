# Repeated Helper Methods Design

Date: 2026-06-03
Status: Draft for written spec review

## Purpose

Agents often solve local implementation pressure by copying small helper
methods into nearby classes or tests. That works briefly, but it leaves repeated
logic spread across a project and makes later behavior changes harder to apply
correctly.

Codex Bootstrap should add a Supermeta rule that detects repeated helper
methods and guides agents toward common code. Java is the V1 target because the
Java starter already has shared Supermeta Java policy, Gradle verification, and
enough helper-like code patterns to make the rule useful. The design should
still leave a clear path for Python, TypeScript, Rust, and C# adapters.

## Scope

V1 adds a parser-backed `repeated_helper_methods` Supermeta rule family.

In scope:

- Java helper extraction through Tree-sitter.
- Source-set-aware grouping so production helpers compare only with production
  helpers and test helpers compare only with test helpers.
- Exact normalized helper duplicates as hard findings.
- Conservative near-duplicate helper matches as advisory findings.
- Configurable minimum method size, near-match threshold, ignore annotations,
  and method allowlists.
- Java starter opt-in through `templates/java-gradle-cli/supermeta-rules.json`.
- Documentation for the cross-language adapter path.

Out of scope:

- Cross-language duplicate detection.
- Public API similarity enforcement.
- Automatic refactoring or code movement.
- Parser-backed adapters for Python, TypeScript, Rust, or C# in V1.
- A regex fallback when the parser dependency is unavailable.

## Architecture

`tools/supermeta-rules/check.py` remains the CLI entrypoint. It should only add
thin dispatch for `repeated_helper_methods`, top-level unknown-rule validation,
and conversion from helper findings into the existing `Finding` shape.

The rule logic belongs in a focused helper module, such as
`tools/supermeta-rules/repeated_helpers.py`, so `check.py` does not keep growing
as the parser and fuzzy comparison code matures.

The shared pipeline is:

1. Load each enabled rule object.
2. Validate and expand configured source groups.
3. Ask the configured language adapter to extract helper candidates.
4. Normalize each helper into a language-neutral comparison record.
5. Cluster exact normalized duplicates inside the same group.
6. Score near-duplicate candidates inside the same group.
7. Return hard findings for exact duplicates and advisory findings for near
   matches.

Language adapters should emit a common record shape:

- relative file path;
- source group name;
- method or function name;
- line number;
- language;
- visibility and static/helper metadata;
- normalized token stream;
- rough structural fingerprint;
- display summary for findings.

Java is the only implemented adapter in V1. Later adapters reuse the same
record, clustering, scoring, and reporting path.

## Rule Behavior

The rule compares helpers only within configured source groups. The Java starter
should define a `main` group for `src/main/java` and a `test` group for
`src/test/java`. A helper repeated once in production and once in tests should
not fail V1, because the right extraction target is often different.

Java V1 helper eligibility is intentionally conservative.

Production source includes:

- `private` methods;
- package-private `static` utility-shaped methods that are not public API.

Test source additionally includes package-private helper methods, because test
fixtures commonly use package-private helpers instead of private static
utilities.

The rule excludes:

- constructors;
- abstract methods;
- interface method declarations;
- `public` or `protected` production methods;
- non-static package-private production methods;
- methods annotated with `@Override`;
- methods or enclosing types carrying configured ignore annotations;
- generated paths filtered by `exclude`;
- methods below the configured size threshold.

Exact normalized duplicates are hard findings. The message should name the
matching methods, show their locations, and tell the agent to factor the helper
into common code in the nearest appropriate scope: an existing support class, a
small package utility, a test fixture helper, or another project-local shared
module.

Near-duplicates are advisory by default. They should be visible in output but
should not fail the run unless a future config explicitly promotes them. The
message should say to review the helpers for shared extraction, not claim that a
refactor is mandatory.

## Configuration

The config should be language-neutral even though V1 implements only Java.

Example Java starter config:

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

Fields:

- `name`: finding rule name.
- `language`: V1 accepts `java`.
- `groups`: source sets that should be scanned and compared independently.
- `min_statements`: minimum parsed method-body statement count for eligibility.
- `near_match_threshold`: minimum fuzzy similarity for advisory near matches.
- `advisory_near_matches`: when true, near matches are reported without failing.
- `ignore_annotations`: simple or fully qualified annotations that suppress a
  method or enclosing type.
- `allow_methods`: method-name allowlist for intentional repeated helpers.

Every rule object still supports the existing optional `enabled` boolean.
Disabled rules must be skipped before rule-specific required fields or parser
dependencies are validated.

## Java Adapter

The Java adapter should use Tree-sitter to parse source into syntax trees and
extract method declarations. It should not extend the current Java regex and
brace heuristics, because fuzzy comparison depends on stable syntax boundaries.

The adapter should classify methods from syntax and nearby modifiers:

- method name;
- declaration line;
- modifiers such as `private`, `protected`, `public`, `static`, and `abstract`;
- method annotations;
- enclosing type annotations;
- body statement count;
- syntax nodes for the method body.

The adapter should fail clearly when Java parsing cannot run for an enabled rule.
It should not silently fall back to text scanning, because weak parsing would
make fuzzy output harder for agents to trust.

## Normalization

Normalization should keep behaviorally useful structure and remove incidental
naming noise.

The Java adapter should:

- replace parameter and local variable identifiers with stable placeholders;
- replace literals with typed placeholders such as `<string>`, `<number>`, and
  `<boolean>`;
- preserve control-flow tokens, method calls, field accesses, operators, return
  shape, and exception handling;
- preserve enough external type and method names to avoid merging unrelated
  helpers that only share a skeleton;
- ignore comments, formatting, annotations, and harmless modifier ordering.

Exact duplicates are methods with identical normalized token streams inside the
same group.

## Fuzzy Matching

Near-match scoring should be conservative. V1 should use normalized token
sequence similarity plus a rough structural fingerprint so similar-looking but
structurally different helpers do not trigger.

A near match should be reported only when:

- both methods are eligible helpers;
- both methods clear `min_statements`;
- both methods are in the same source group;
- both methods share the same rough control-flow fingerprint;
- token similarity is at or above `near_match_threshold`.

The default behavior is advisory. Near matches should guide agents toward
possible consolidation without creating a hard gate from fuzzy evidence.

## Dependency Contract

This feature intentionally breaks the earlier dependency-free posture of
`tools/supermeta-rules/check.py`. Parser-backed helper comparison is the right
tradeoff for this rule because the fuzzy component needs reliable syntax.

The implementation should add the smallest explicit Python dependency story for
the shared Supermeta rule engine, expected to include Tree-sitter and the Java
grammar package. The rule should import parser dependencies only when an enabled
`repeated_helper_methods` rule needs them, so existing projects without the rule
do not pay the cost or fail at import time.

When the parser package is unavailable and the rule is enabled, the checker
should return a clear tool/config error that tells the agent which dependency is
missing and how to install the shared tool requirements.

## Template Contract

The Java Gradle starter should enable `repeated_helper_methods` by default in
`templates/java-gradle-cli/supermeta-rules.json`.

Generated Java projects should receive:

- the new Supermeta helper module;
- the dependency manifest or documented install path for parser dependencies;
- README and agent-note guidance explaining the repeated-helper rule;
- verification commands that still route through `scripts/agent-gradle` and the
  shared Supermeta checker.

Other templates should not enable the rule in V1. Their docs may mention the
planned adapter path, but generated Python, TypeScript, Rust, and C# starters
should not claim repeated-helper enforcement until their adapters exist.

Any new support files must be listed in the relevant template manifests so
bootstrap smoke and generated-project sync keep working.

## Output

Exact duplicate example:

```text
[repeated-helper-methods] src/main/java/com/example/Foo.java:42 duplicates helper body also found at src/main/java/com/example/Bar.java:31; factor this helper into common code in the nearest appropriate package or support class
```

Near-match example:

```text
[repeated-helper-methods] src/test/java/com/example/FooTest.java:77 is similar to src/test/java/com/example/BarTest.java:64; review these helpers for shared test fixture extraction
```

If the existing `Finding` type cannot represent advisory findings distinctly,
the implementation plan should either extend the finding model with severity or
route advisory findings through a non-failing warning list. The hard requirement
is that exact duplicates fail and advisory near matches do not fail by default.

## Error Handling

Invalid config should follow existing Supermeta error style:

- `repeated_helper_methods` must be an array;
- each rule must be an object;
- `language` must be a supported non-empty string;
- `groups` must be a non-empty array;
- group `name`, `paths`, `include`, and `exclude` must validate like existing
  path-based rule fields;
- `min_statements` must be a positive integer;
- `near_match_threshold` must be a number greater than 0 and at most 1;
- `ignore_annotations` and `allow_methods` must be arrays of non-empty strings.

Disabled rules should skip all of the above validation except the existing
`enabled` boolean validation.

Unreadable source files, parser initialization failures, and unsupported
languages should fail clearly. Parser syntax errors in an individual Java source
file should produce a rule finding or tool error that names the file rather than
causing an unhandled traceback.

## Cross-Language Plan

The cross-language path is adapter-driven:

- Python adapter: function and private helper extraction from `ast`, because the
  standard library already provides stable parsing.
- TypeScript adapter: Tree-sitter or TypeScript compiler API extraction for
  functions, private methods, and local helpers.
- Rust adapter: Tree-sitter Rust extraction for private functions and test
  helpers, with module-aware grouping.
- C# adapter: Tree-sitter C# or Roslyn-backed extraction, depending on what
  keeps generated projects simplest.

The shared clustering and fuzzy logic should remain language-neutral. Each
adapter is responsible only for syntax extraction, helper eligibility, and
normalization into the common record shape.

## Testing

Focused behavior tests belong under `tools/supermeta-rules`. If parser-specific
coverage becomes substantial, add a new test module next to `check_test.py`
instead of making the existing file harder to navigate.

V1 tests should cover:

- exact duplicate private Java helpers fail;
- renamed locals and parameters still normalize to a duplicate;
- production and test groups do not compare with each other;
- public and protected production methods are ignored;
- tiny helpers are ignored;
- `@Override` methods are ignored;
- configured ignore annotations suppress methods and enclosing types;
- generated excludes are honored;
- near-duplicates produce advisory output only;
- disabled rule placeholders skip validation and parser dependency loading;
- missing parser dependency reports a clear error when the rule is enabled;
- invalid config fails with direct `ValueError` messages.

Template and bootstrap tests should prove generated Java projects receive the
new support files and config.

## Verification

After implementation, run:

```sh
python3 -m unittest discover -s tools/supermeta-rules -p '*_test.py'
python3 -m unittest discover -s tools/bootstrap -p '*_test.py'
./scripts/agent-gradle templates/java-gradle-cli check
./scripts/agent-gradle templates/java-gradle-cli run
```

If a dependency manifest is added for shared tools, include its install or lock
verification in the final implementation plan.

## Risks

The main risk is false positives that push agents into bad refactors. V1 reduces
that risk by making only exact normalized duplicates fail and keeping fuzzy
matches advisory.

The second risk is dependency friction for generated projects. V1 should make
the parser dependency explicit, lazy-load it only when the rule is enabled, and
fail with installation guidance instead of surprising tracebacks.

The third risk is config drift across templates. V1 should update Java starter
config, generated docs, support-file manifests, and bootstrap smoke coverage in
one change.
