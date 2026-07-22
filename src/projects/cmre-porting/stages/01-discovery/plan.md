# Stage Plan: CMRE Source Discovery

## Objective

Create a read-only, evidence-backed inventory and declared dependency graph for the complete CMRE
development package, then identify the next static-analysis boundary without copying SC2 content.

## Inputs

- Registered source `cmre-dev-package`.
- Legacy SC2 editor toolkit `inspect` command.
- Galaxy source files and Catalog XML under the registered source.

## Write scope

- `src/projects/cmre-porting/**`

## Tasks

1. Inventory maps, mods, file types, and package sizes.
2. Resolve every declared document dependency from the CMRE package root.
3. Locate Galaxy libraries, initializers, trigger registration, objectives, rewards, and Banks.
4. Locate commander-specific Catalog clusters and existing commander package boundaries.
5. Record unresolved ownership and runtime questions for the static-analysis stage.

## Outputs

- `evidence/static/package-inventory.json`
- `evidence/static/dependency-graph.json`
- `evidence/static/split-candidates.json`
- `result.json`, `issues.json`, and the next stage plan.

## Validation

- `node tools/workspace.mjs validate` exits 0.
- JSON and project schemas validate.
- `git diff --check` exits 0.

## Stop conditions

- Complete when all 15 mission maps, the launcher, and five Mod packages are inventoried and linked.
- Do not modify or copy files from `cmre-dev-package`.
- Defer ownership claims that need symbol-level Catalog or Galaxy call evidence.
