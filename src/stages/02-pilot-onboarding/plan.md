# Reborn MVP Onboarding Plan

## Objective

Create an auditable project record for `reborn.zexpedition03.raynor-mvp`, capture its effective
dependency graph and adapter boundary, and prepare a runtime smoke scenario without modifying the
downloaded Reborn source.

## Inputs

- `stages/01-manifest-design/result.json`
- `stages/01-manifest-design/evidence/pilot/` manifests
- `reborn-hots-071` local source binding
- `legacy-project` Reborn adapter and launcher packages

## Write scope

- `src/projects/reborn-zexpedition03-raynor-mvp/`
- `stages/02-pilot-onboarding/`
- `artifacts/` for generated analyzer reports only
- `legacy-project:out/compositions/reborn.zexpedition03_reborn_port__p1-TerranRaynor.launcher-plan.json`
- `legacy-project:out/verification/reborn.zexpedition03_reborn_port__p1-TerranRaynor/`

## Tasks

1. Create the project manifest with registered source IDs and explicit acceptance criteria.
2. Run legacy dependency inspection for the source map, Reborn core mod, and effective Raynor composition.
3. Write the dependency graph, analyzer command record, and unresolved dependency list under project evidence.
4. Compare the source map with the existing port target and document the adapter ownership boundary.
5. Run the launcher `-CheckOnly` and composer verification without starting SC2.
6. Decide whether the runtime stage is eligible; preserve known build-panel and unresolved-dependency gaps.

## Outputs

- Project manifest and discovery-stage records.
- Static dependency graph and unresolved issue list.
- Adapter proposal and runtime scenario.
- Next-stage runtime validation plan or a narrow retry plan if static checks fail.

## Validation

- `node tools/workspace.mjs validate`
- Legacy toolkit `inspect` in declared and effective modes.
- Reborn launcher `-CheckOnly`.
- Composer `verify` for the selected composition.
- JSON Schema validation of project and stage outputs.

## Stop conditions

- Stop before runtime if the effective dependency boundary remains incomplete.
- Do not edit or copy the downloaded Reborn source.
- Do not claim commander behavior from static evidence or heartbeat-only probe reports.
