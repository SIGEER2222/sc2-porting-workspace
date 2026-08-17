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

## Implementation validation

- `simulator`: Added `src/projects/cmre-porting/vibe/normal_start_contract.py` with a fair P1/P2 Terran normal-start fixture and a macro-only P2 policy. The fixture starts both players at 50 minerals, 0 gas, 12 SCVs, one Command Center, no enemy, no initial combat units, and mirrored neutral resource clusters.
- `simulator`: Generated `artifacts/projects/cmre-porting/stage29-normal-start-contract/normal-start-contract-20260817.json` with `status=PASS`, `contract_schema_version=normal-start-contract.v1`, `result_category=macro_bootstrap`, and `native_claim=false`.
- `simulator`: Required checks all passed: worker mining, resource income, resource deposit, supply handling, worker survival, building construction, production completion, combat-unit creation, no dispatch error, and no deadlock. Final P2 state after 900 loops was 12 SCVs, 1 SupplyDepot, 1 Barracks, 2 Marines, 0 dispatch errors, trace `8ad3063ba6a3c055811d9c5eadd1bff9e1f561f7ea68bf385f17faebfa07b4f9`.
- `static`: Added `src/projects/cmre-porting/stages/29-normal-start-contract/test_normal_start_contract.py` to assert fixture fairness, required contract checks, and report artifact writing.
- `validation`: `py -3.13 -m unittest src.projects.cmre-porting.stages.29-normal-start-contract.test_normal_start_contract` passed: 3 tests in 2.588s.
- `validation`: `py -3.13 -m json.tool artifacts/projects/cmre-porting/stage29-normal-start-contract/normal-start-contract-20260817.json` passed, followed by explicit artifact assertions for schema, category, native claim, and all required checks.
- `scope`: Stage 29 remains simulator-only macro-bootstrap evidence; native mission-completion proof stays deferred to Stage 31.
