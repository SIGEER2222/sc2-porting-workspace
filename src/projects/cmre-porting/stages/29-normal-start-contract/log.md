# Stage 29 Log: Normal Start Contract

## 2026-08-17

- `static`: Created Stage 29 from `C:/Users/Sigeer/Downloads/sc2-simulator-next-stage-plan-stage29-plus.md` after Stage 28 completed simulator result semantics and catalog-fidelity baseline hardening.
- `static`: Stage 29 intentionally shifts from map adapter clearance to a normal RTS macro-bootstrap contract. The goal is a fair Terran-vs-Terran opening with 50 minerals, 0 gas, 12 workers each, and no staged enemy or adapter-injected advantage.
- `scope`: Stage 29 remains deterministic simulator work. It must output `normal-start-contract.v1`, classify success as `result_category=macro_bootstrap`, and keep `native_claim=false`.
- `scope`: Native SC2 differential/runtime proof is deferred to Stage 30/31; Stage 29 must not claim native mission completion.

## Required evidence

- `simulator`: Worker mining, resource income, resource deposit, supply handling, worker survival, building construction, production completion, combat-unit creation, no dispatch error, and no deadlock must each be independently asserted.
- `static`: The scenario or fixture must document that no initial combat units, extra buildings, resource multipliers, enemy replacement, or enemy relocation are injected.
- `static`: Result model must not use `victory=true` as the sole success marker; it must expose `result_category=macro_bootstrap` and `native_claim=false`.

## Evidence paths

- `src/projects/cmre-porting/stages/29-normal-start-contract/plan.md`
- `src/projects/cmre-porting/stages/29-normal-start-contract/result.json`
- `src/projects/cmre-porting/stages/29-normal-start-contract/issues.json`

## Transition validation

- `static`: `py -3.13 -m json.tool src/projects/cmre-porting/project.json && py -3.13 -m json.tool src/projects/cmre-porting/stages/28-simulator-baseline-hardening/result.json && py -3.13 -m json.tool src/projects/cmre-porting/stages/29-normal-start-contract/result.json && py -3.13 -m json.tool src/projects/cmre-porting/stages/29-normal-start-contract/issues.json` passed; project `currentStage` now points to `29-normal-start-contract`.

## Next implementation step

- Build the deterministic normal-start fixture and focused `normal-start-contract.v1` test before running any broader CMRE map-matrix sweep.
