# Stage 28 Log: Simulator Baseline Hardening

## 2026-08-17

- `static`: Activated `cmre-porting` as the workspace project and opened Stage 28 for simulator-first baseline hardening.
- `static`: Stage 28 intentionally scopes P0 work to result semantics, transformation provenance, action issuer audit, and focused simulator regressions.
- `inference`: Stage 25 simulator passes remain valuable deterministic adapter-clearance evidence, but must not be labelled as full native SC2 mission completion.

## P0 implementation

- `static`: Updated `run_cmre_map_matrix.py` so full-game simulator passes are classified as `result_category=adapter_clearance` and `probe_status=ADAPTER_CLEARANCE_PASS`; the old active-code label `FULL_GAME_PASS` is no longer emitted.
- `static`: Added `claim_status=simulator_adapter_clearance_not_native_runtime` and preserved `runtime_claim=none; native SC2 mission completion not exercised` in map probe summaries.
- `static`: Added `simulator_transformation_audit` to map-derived scenario metadata, split into `source_static`, `map_derived`, `adapter_transforms`, `simulator_only`, and `claim` sections.
- `static`: Added action issuer provenance to ally replay/action output: `issuer_unit_type`, `action_actor_type_counts`, `attack_actor_type_counts`, and `worker_attack_action_count`.
- `scope`: Stage 28 does not claim native SC2 mission completion and does not promote any Galaxy VM/runtime hook.

## Validation

- `static`: `py -3.13 -m py_compile src/projects/cmre-porting/vibe/consumers/ally_ai.py src/projects/cmre-porting/vibe/run_cmre_map_matrix.py src/projects/cmre-porting/vibe/cmre_map_catalog.py` passed with exit code 0.
- `simulator`: `PYTHONPATH=src/projects/cmre-porting py -3.13 -m unittest -q stages/28-simulator-baseline-hardening/test_simulator_baseline_hardening.py` passed: 3 tests in 0.114s.
- `simulator`: `PYTHONPATH=src/projects/cmre-porting py -3.13 -m unittest -q stages/25-ai-ally-capability-completion/test_ladder_ai.py` passed: 4 tests in 117.386s.
- `static`: Search for `FULL_GAME_PASS` in active `vibe` code returned no emitter; the only remaining reference is the Stage 28 negative assertion.

## Evidence paths

- `src/projects/cmre-porting/stages/28-simulator-baseline-hardening/test_simulator_baseline_hardening.py`
- `src/projects/cmre-porting/stages/28-simulator-baseline-hardening/result.json`
- `artifacts/projects/cmre-porting/stage28-simulator-baseline-hardening/validation-20260817.json`

## P1 catalog fidelity baseline

- `static`: Added `src/projects/cmre-porting/vibe/catalog_fidelity.py` to build a project-local `cmre-catalog-fidelity-baseline.v1` report from the simulator `sc2_simulator.m7` CatalogSnapshot without modifying the read-only simulator package.
- `static`: The baseline records `runtime_claim=none; simulator catalog fidelity only`, catalog source/hash/counts, scenario unit reference closure, unsupported-unit rejection, UnitModel, EconomyModel, ProductionModel, AbilityModel, and catalog-reference-closure checks.
- `static`: `run_cmre_map_matrix.py` now computes `catalog_fidelity_baseline` for each map probe, includes it in the summary, and adds `checks.catalog_fidelity_baseline` so adapter-clearance summaries fail if the minimum static catalog gate fails.
- `static`: Generated `artifacts/projects/cmre-porting/stage28-simulator-baseline-hardening/catalog-fidelity-baseline-20260817.json` from `亡者之夜.SC2Map`; observed status `PASS`, unit count `117`, and catalog content hash `cafab5205fba13a7`.

## P1 validation

- `static`: `py -3.13 -m py_compile src/projects/cmre-porting/vibe/catalog_fidelity.py src/projects/cmre-porting/vibe/run_cmre_map_matrix.py src/projects/cmre-porting/stages/28-simulator-baseline-hardening/test_simulator_baseline_hardening.py` passed with exit code 0.
- `simulator`: `PYTHONPATH=src/projects/cmre-porting py -3.13 -m unittest -q stages/28-simulator-baseline-hardening/test_simulator_baseline_hardening.py` passed: 5 tests in 0.138s.
- `simulator`: `PYTHONPATH=src/projects/cmre-porting py -3.13 -m unittest -q stages/25-ai-ally-capability-completion/test_ladder_ai.py` passed: 4 tests in 98.611s.

## Evidence paths

- `src/projects/cmre-porting/vibe/catalog_fidelity.py`
- `src/projects/cmre-porting/vibe/run_cmre_map_matrix.py`
- `src/projects/cmre-porting/stages/28-simulator-baseline-hardening/test_simulator_baseline_hardening.py`
- `src/projects/cmre-porting/stages/28-simulator-baseline-hardening/result.json`
- `src/projects/cmre-porting/stages/28-simulator-baseline-hardening/issues.json`
- `artifacts/projects/cmre-porting/stage28-simulator-baseline-hardening/catalog-fidelity-baseline-20260817.json`
- `artifacts/projects/cmre-porting/stage28-simulator-baseline-hardening/validation-20260817.json`

## Handoff

- `static`: Stage 28 is marked complete after P0 simulator result semantics and P1 catalog-fidelity baseline passed focused regression validation.
- `scope`: Native SC2 mission completion remains explicitly out of scope for Stage 28 and is carried as a recorded boundary, not a Stage 28 implementation blocker.
- `static`: Opened Stage 29 `normal-start-contract` from the Stage29+ roadmap. Stage 29 must prioritize fair normal RTS macro-bootstrap evidence before broader map-matrix sweeps or native runtime claims.
