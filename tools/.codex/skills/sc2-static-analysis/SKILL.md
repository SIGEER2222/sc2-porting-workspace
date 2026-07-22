---
name: sc2-static-analysis
description: Analyze SC2 maps, mods, campaigns, Galaxy libraries, Catalog data, initializers, triggers, objectives, rewards, and Banks to build an evidence-backed dependency graph. Use before changing or adapting an SC2 map/mod, when dependencies are unclear, when source and target environments differ, or when runtime behavior needs a static explanation.
---

# SC2 Static Analysis

Build the dependency model before proposing edits.

## Workflow

1. Read `src/config/workspace.json`, the active `project.json`, and the current stage plan.
2. Resolve source paths by registered ID. Treat read-only sources as immutable.
3. Classify each input as unpacked map, MPQ map, mod, campaign, data mirror, or generated artifact.
4. Use the registered Galaxy toolkit first for document dependencies, Catalog ownership, includes,
   calls, initializers, trigger registration, Bank access, objectives, and rewards.
5. Record every graph edge with a file, line, command output, or analyzer artifact.
6. Mark dynamic IDs, indirect calls, generated strings, and unresolved dependencies explicitly.
7. Write a dependency graph matching `docs/schemas/dependency-graph.schema.json`.
8. Update the stage log and result. Do not modify SC2 content in a static-analysis stage.

## Required graph coverage

- DocumentHeader and DocumentInfo dependencies.
- Galaxy include and initialization order.
- Function declarations, implementations, and cross-library calls.
- Catalog definition, inheritance, merge, and override ownership.
- Trigger events, registrations, and initializer entry points.
- Mission objectives, rewards, progression gates, and Bank reads/writes.
- External assets or native packages required by the composition.

## Evidence discipline

- Label analyzer-confirmed relationships as `static`.
- Label plausible but unresolved relationships as `inference`.
- Never treat an empty analyzer result as proof of absence.
- Never claim runtime execution from source analysis.

Read [output-contract.md](references/output-contract.md) before writing the graph.

## Syntax and type diagnostics

In addition to the dependency graph, run syntax/type diagnostics to catch
Galaxy script errors before runtime:

```powershell
# 诊断整个目录
node tools/utils/workspace.mjs lint src/projects/<project-id>

# 诊断单个文件，输出到 artifacts
node tools/utils/workspace.mjs lint path/to/file.galaxy --out evidence/static/diagnostics.json

# 仅语法诊断（不做 type checking，更快）
node tools/utils/workspace.mjs lint <path> --no-type-check --format text
```

输出格式见 `docs/schemas/static-diagnostics.schema.json`。底层调用
`reference/sc2-galaxy-toolkit/packages/sc2-galaxy-lang` 的 parser + binder +
checker。首次使用前需在 submodule 内 `pnpm install && pnpm -r run build`。

与 `analyze-galaxy.mjs`（dependency graph）互补：lint 专注诊断"写错什么"，
analyze 专注"调用了什么"。两者可同时运行。
