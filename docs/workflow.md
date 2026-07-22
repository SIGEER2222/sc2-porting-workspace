# AI Development Workflow

Every project advances through explicit stages:

1. `discovery`: inventory source assets and declared dependencies.
2. `static-analysis`: build dependency, initialization, trigger, objective, and reward graphs.
3. `gap-analysis`: compare the source environment with the target composition.
4. `adapter-design`: choose the smallest ownership layer and define the write scope.
5. `implementation`: make bounded map, mod, or adapter changes.
6. `static-validation`: validate Galaxy, Catalog, dependencies, and packaging.
7. `runtime-validation`: launch SC2 and collect dynamic evidence.
8. `acceptance`: compare observed behavior with project acceptance criteria.

Each stage owns:

```text
stages/<number>-<name>/
  plan.md
  log.md
  result.json
  issues.json
  evidence/
```

The loop advances only when the current stage's outputs and validation commands pass. A failed stage
updates its log and issues, then creates a narrower retry plan instead of silently expanding scope.

## Local source binding

Committed manifests refer to external inputs by source ID. Machine-specific absolute paths stay in
the ignored `src/config/local.sources.json` file and are created through the workspace command:

```powershell
node tools/workspace.mjs bind-source <source-id> <local-path>
node tools/workspace.mjs resolve <source-id>
```
