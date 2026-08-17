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

## Remaining work

- `open`: `SIM28-NATIVE-RUNTIME-OUT-OF-SCOPE` remains by design; adapter clearance is simulator-only evidence.
- `open`: `SIM28-P1-CATALOG-FIDELITY-PENDING` tracks the next v2-plan layer: UnitModel/EconomyModel/AbilityModel fidelity checks and broader matrix persistence.
