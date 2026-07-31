# Stage Plan: Reborn Mods Discovery

## Objective

Create a read-only, evidence-backed inventory of the 5 Reborn mods (crys_the_swarm_reborn + 4 sub-mods) and their declared dependencies, then identify the integration boundary into CMRE runtime.

## Inputs

- Registered source `reborn-hots-071`（`C:/Users/22448/Downloads/重生虫心0.71汉化版（新）/reborn`）
- CMRE runtime at `cmre-runtime/`
- Reference SC2GameData campaign files (swarmstory.sc2campaign, swarmstoryutil.sc2mod)

## Write scope

- `src/projects/reborn-mods-cmre-integration/stages/01-discovery/**`
- `src/projects/reborn-mods-cmre-integration/project.json`

## Tasks

1. Inventory the 5 Reborn mods: file lists, sizes, Catalog XML, Galaxy libraries.
2. Resolve every declared document dependency from each Reborn mod root.
3. Locate the K5Kerrigan spawn/replacement logic in Lib48DF4533.galaxy (commander_start_func at lines 5016-5204, unit_unlocks at 5215-5494).
4. Identify the 15 commander definitions and their replacement units.
5. Identify campaign dependencies (SwarmStory.SC2Campaign, swarmstoryutil.sc2mod).
6. Record unresolved integration questions for the static-analysis stage.

## Outputs

- `evidence/static/reborn-mods-inventory.json`
- `evidence/static/reborn-dependency-graph.json`
- `evidence/static/reborn-commanders.json`（15 指挥官定义）
- `result.json`, `issues.json`, and the next stage plan.

## Validation

- All 5 Reborn mods inventoried with complete file lists.
- 15 commanders identified with replacement units and source lines.
- Campaign dependencies resolved.

## Stop conditions

- Complete when all 5 Reborn mods are inventoried and 15 commanders are cataloged.
- Do not modify or copy files from `reborn-hots-071` source.
- Defer ownership claims that need symbol-level Catalog or Galaxy call evidence to Stage 02.
