# Stage Plan: CMRE Static Boundaries

## Objective

Produce symbol-level Catalog and Galaxy ownership graphs that are sufficient to approve the first
extractable package boundary without modifying source SC2 content.

## Inputs

- `src/projects/cmre-porting/stages/01-discovery/evidence/static/*.json`
- Registered source `cmre-dev-package`
- Registered Galaxy toolkit and legacy SC2 editor toolkit

## Write scope

- `src/projects/cmre-porting/stages/02-static-boundaries/**`
- `src/projects/cmre-porting/project.json`

## Tasks

1. Resolve `Void.SC2Campaign` against registered official/reference data.
2. Build complete Galaxy include, initializer, trigger registration, objective, reward, and Bank graphs.
3. Build Catalog ID ownership and cross-reference closure for Base, Mengsk, Stetmann, and Tychus.
4. Classify map-owned mission logic separately from reusable runtime behavior.
5. Approve one narrow first extraction candidate and define static/runtime regression scenarios.

## Outputs

- `evidence/static/galaxy-graph.json`
- `evidence/static/catalog-ownership.json`
- `evidence/static/mission-contracts.json`
- `boundary-decision.json`
- Updated result, issues, log, and next stage plan

## Validation

- All evidence JSON parses and matches its declared contract.
- Every approved boundary has dependency closure and no unresolved static ownership edge.
- `node tools/workspace.mjs validate` and `git diff --check` exit 0.

## Stop conditions

- Do not copy or edit CMRE source assets.
- Do not approve a boundary from filename or keyword matching alone.
- If symbol analysis is incomplete, record the missing tool capability and keep the boundary unresolved.
