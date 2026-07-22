# AI Development Workflow

AI-assisted SC2Map/SC2Mod changes must run through three evidence gates before a stage can close:

1. `knowledge-retrieval`: query the local SC2 editor knowledge base and Blizzard tutorial index
   before designing Galaxy, Catalog, Bank, Trigger, actor, data editor, or document-file changes.
2. `static-validation`: run `sc2-galaxy-toolkit` backed checks before launch so syntax, include,
   unresolved-call, dependency, and Catalog mistakes are caught outside the game.
3. `runtime-validation`: launch SC2 with an observer/API bridge and collect runtime evidence for the
   feature claim. Process startup alone is not evidence.

The standard entry points are:

```powershell
node tools/utils/workspace.mjs search "<SC2 editor or Galaxy question>" --top-k 5
node tools/utils/workspace.mjs lint <path-to-galaxy-or-package> --format json --out <stage>/evidence/static/galaxy-lint.json
node tools/analysis/analyze-galaxy.mjs --composition <stage>/evidence/static/composition.json <stage>/evidence/static/galaxy-graph.json
node tools/utils/workspace.mjs observe --port <sc2-api-port> --duration 120 --scenario <scenario.json> --out-dir <stage>/evidence/runtime
```

Every changed behavior claim must cite at least one `static` or `runtime` evidence path in the stage
log. `inference` is allowed only as a hypothesis or next-step note.

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
node tools/utils/workspace.mjs bind-source <source-id> <local-path>
node tools/utils/workspace.mjs resolve <source-id>
```
