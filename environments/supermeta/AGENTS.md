# Supermeta Agent Notes

Supermeta owns the standards for the bootstrap catalog.

When editing this environment:

- keep the contract short, direct, and implementable;
- preserve the root launcher contract: generated projects keep only local support tooling and fresh Git metadata;
- update the root README if the catalog layout changes;
- require every runnable template to document verification;
- require runnable templates to declare generated-project behavior in `bootstrap-template.json`;
- carry the 1000-line product source limit into new starters;
- carry the Java 7-top-level-types-per-package-layer limit into Java starters;
- enforce Java wildcard imports and Lombok-backed getter, setter, and builder boilerplate through `tools/supermeta-rules/`;
- route reusable checks through `tools/supermeta-rules/`;
- route language-specific lint through `project_callouts`;
- route Gradle agent commands through `scripts/agent-gradle`;
- prefer better new-project defaults over compatibility with older template shapes.
