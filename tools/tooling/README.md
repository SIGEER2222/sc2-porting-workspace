# Tooling Boundary

External tools remain independent Git repositories. Register them in `config/workspace.json` and
consume them through commands, files, HTTP, or WebSocket contracts.

Workspace-owned code may:

- resolve registered tool paths;
- normalize tool output into workspace schemas;
- supervise local processes;
- compose bounded commands;
- validate outputs and evidence.

Workspace-owned code may not:

- copy external implementations into this repository;
- patch an external repository as part of an unrelated project stage;
- hide source mutation, live synchronization, or SC2 launch behind an implicit command;
- treat a missing tool as a successful empty result.

Unpack and pack tools will move into their own repository before they become a stable dependency.

## Galaxy analysis wrapper

`tools/analysis/analyze-galaxy.mjs` uses the registered `sc2-galaxy-lang` AST parser. It accepts a logical
source ID and writes normalized include, function, cross-file call, initializer, trigger, Bank,
objective, and reward evidence without embedding machine paths:

```powershell
node tools/analysis/analyze-galaxy.mjs <source-id> <relative-root> <output-path>
```

`tools/analysis/analyze-catalog.mjs` uses the registered `sc2-data` structured XML store to emit an exact
Catalog selector plus reverse references from non-selected entries:

```powershell
node tools/analysis/analyze-catalog.mjs <source-id> <relative-root> <pattern> <output-path>
```

`tools/analysis/extract-catalog-boundary.mjs` executes an approved extraction recipe into ignored
`artifacts/` working content. It copies registered read-only inputs, applies XML AST byte-range
moves to the copies, verifies source hashes, and writes a committed extraction report:

```powershell
node tools/analysis/extract-catalog-boundary.mjs <recipe-path>
```

`tools/analysis/compare-catalog-chains.mjs` loads the source and generated Base-to-commander chains through
the registered structured Catalog store and compares every merged family+ID after removing source
provenance:

```powershell
node tools/analysis/compare-catalog-chains.mjs <recipe-path> <generated-source-id> <output-path>
```
