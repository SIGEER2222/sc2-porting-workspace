# Stage Plan: CMRE Runtime Baseline

## Objective

Run the real Dead of Night + Mengsk source composition and capture dynamic evidence before accepting
the generated extraction.

## Inputs

- `../01-discovery` and `../02-static-boundaries` evidence.
- `../03-mengsk-extraction-recipe` generated artifacts.
- `manifests/runtime-scenarios/dead-of-night-mengsk-baseline.json`.
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
2. Launch the source composition with the real observer.
3. Capture ready, selection, resource target, issued worker order, production, objective, and night-cycle events.
4. Run the same scenario on the generated composition after launcher wiring exists.
5. Write a runtime verdict with raw evidence paths and ScriptError/process status.
6. Provide a guarded launcher entry point for selecting a registered CMRE map and configured commander.

## Outputs

- `source-runtime-verdict.json`
- `generated-runtime-verdict.json` or an explicit blocked issue
- Raw observer/log evidence under `artifacts/runtime/cmre/dead-of-night/mengsk-baseline/`

## Validation

- One test lock at a time.
- Real service/backend connection is visible in the evidence.
- No new ScriptError and SC2 remains alive through the readiness grace period.

## Stop conditions

- Stop and record blocked if the real observer service cannot connect.
- Do not claim runtime success from process startup or mocks.
- Do not start another Gary instance when one active backend exists.
