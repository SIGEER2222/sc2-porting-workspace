# Stage Plan: CMRE Runtime Baseline

## Objective

Close the real Dead of Night + TerranAlenger3 runtime baseline with dynamic evidence, then hand off
the remaining Gary/Neuro external-driver gap as a separate follow-up issue. This stage no longer
claims Mengsk extraction acceptance; the earlier Mengsk runtime objective is deferred until a
dedicated generated-composition stage is opened.

## Inputs

- `../01-discovery` and `../02-static-boundaries` evidence.
- Alenger3 composition manifests under `evidence/static/`.
- Runtime Bank and ScriptError evidence under `evidence/runtime/`.
- Real runtime observer integration; no mock-only verdict is acceptable.

## Write scope

- `src/projects/cmre-porting/stages/04-runtime-baseline/**`
- `artifacts/runtime/cmre/**`
- `scripts/select-cmre-composition.ps1`
- `scripts/launch-cmre-alenger.ps1`
- `src/config/workspace.json`
- `src/projects/cmre-porting/manifests/source-packages.json`
- `src/projects/cmre-porting/packages/**`
- `config/alenger-mods.json`
- `config/cmre-alenger-dependencies.json`

## Tasks

1. Confirm the single active Gary/Neuro-compatible backend and acquire the SC2 test lock.
2. Launch the 5-dependency Dead of Night + TerranAlenger3 composition with the real observer.
3. Capture commander selection, Alenger3 starting units, command-card dump, train completion,
   mission phase, objective state, ScriptError status, and process status.
4. Patch only map-level CMRE core Galaxy copies for the known LibCOTF/LibCOUI/LibCOMI missing-data
   assumptions; do not modify read-only CMRE source mods.
5. Record the closed Alenger3 runtime baseline in `result.json` and keep raw evidence paths in
   `log.md`.
6. Hand off the remaining Gary/Neuro external-driver problem as `CMRE-RUNTIME-003` instead of
   blocking the Alenger3 runtime baseline.

## Outputs

- `result.json` with `status: PASS` for `亡者之夜.SC2Map` + `TerranAlenger3`.
- `issues.json` with `CMRE-ALENGER3-001` and `CMRE-ALENGER3-RUNTIME-002` resolved.
- `issues.json` retaining `CMRE-RUNTIME-003` as the Gary/Neuro external-driver follow-up.
- Raw Bank and ScriptError evidence under `src/projects/cmre-porting/stages/04-runtime-baseline/evidence/runtime/`.

## Validation

- One test lock at a time.
- Real service/backend connection is visible in the evidence.
- `NeuroIntegration.SC2Bank.20260721-164349` records commander, unit, command-card, train, and
  mission-state probe data.
- `ScriptError.20260721-1624.NONE.txt` and `ScriptError.20260721-164454.txt` show the cleaned
  post-patch runtime state.
- No new ScriptError and SC2 remains alive through the readiness grace period.

## Stop conditions

- Stop and record blocked if the real observer service cannot connect.
- Do not claim runtime success from process startup or mocks.
- Do not start another Gary instance when one active backend exists.
- Do not claim Gary-driven action completion until `CMRE-RUNTIME-003` proves that externally written
  actions can be consumed by running SC2 or a replacement IPC path exists.
