# Stage Plan: Reborn Static Boundaries

## Objective

Produce symbol-level Catalog and Galaxy ownership analysis for the Reborn mods, sufficient to approve the integration boundary into CMRE runtime without modifying Reborn source content.

## Inputs

- `src/projects/reborn-mods-cmre-integration/stages/01-discovery/**`
- Registered source `reborn-hots-071`
- CMRE runtime at `cmre-runtime/`
- `src/config/cmre-alenger-dependencies.json`

## Write scope

- `src/projects/reborn-mods-cmre-integration/stages/02-static-boundaries/**`
- `src/projects/reborn-mods-cmre-integration/project.json`

## Tasks

1. Resolve each Reborn mod's document dependencies against CMRE runtime.
2. Build Galaxy ownership graph: K5Kerrigan spawn → commander replacement → unit unlocks.
3. Build Catalog ownership: WarPig, HunterKiller, and 13 other replacement units' definitions.
4. Identify the integration point: CMRE launcher `-EnableReborn` switch.
5. Define the mod deployment layout: `cmre-runtime/Mods/reborn/`.
6. Approve the integration boundary and define runtime regression scenarios.

## Outputs

- `evidence/static/reborn-galaxy-graph.json`
- `evidence/static/reborn-catalog-ownership.json`
- `boundary-decision.json`
- `result.json`, `issues.json`, and the next stage plan.

## Validation

- All 5 Reborn mods have dependency closure with CMRE runtime.
- 15 replacement units have Catalog definitions in Reborn mod XML.
- `-EnableReborn` switch design approved.

## Stop conditions

- Do not copy or edit Reborn source assets.
- Do not approve integration from filename matching alone; require symbol-level evidence.
- If symbol analysis is incomplete, record the missing capability and keep boundary unresolved.
