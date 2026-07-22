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
