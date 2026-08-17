# Stage 28: Simulator Baseline Hardening

## Objective

Prioritize the deterministic CMRE simulator before additional Galaxy VM/runtime work. Tighten Stage 25 full-game simulator results so they are explicitly classified as simulator adapter clearance, not native mission completion, and add auditable provenance for map-to-simulator transformations and action issuers.

## Inputs

- `C:/Users/Sigeer/Downloads/sc2-simulator-improvement-plan-v2-simulation-first-20260817.md`
- `src/projects/cmre-porting/stages/25-ai-ally-capability-completion/result.json`
- `src/projects/cmre-porting/vibe/run_cmre_map_matrix.py`
- `src/projects/cmre-porting/vibe/cmre_map_catalog.py`
- `src/projects/cmre-porting/vibe/consumers/ally_ai.py`

## Deliverables

- Map-matrix summaries use `adapter_clearance` result semantics and preserve `runtime_claim: none`.
- Scenario metadata exposes a `simulator_transformation_audit` for source/static data, adapter-injected data, and simulator-only approximations.
- Ally replay/action outputs expose issuer unit types and aggregate action actor counts, including worker attack counts.
- Focused regression tests prove the new semantics and audit fields.

## Non-goals

- No native SC2 mission-completion claim.
- No expansion of map-adapter coverage solely to increase pass counts.
- No ML policy training or new Galaxy VM hook promotion in this stage.

## Verification

```text
PYTHONPATH=src/projects/cmre-porting py -3.13 -m unittest -q stages/28-simulator-baseline-hardening/test_simulator_baseline_hardening.py
PYTHONPATH=src/projects/cmre-porting py -3.13 -m unittest -q stages/25-ai-ally-capability-completion/test_ladder_ai.py
```

## Write scope

- `src/projects/cmre-porting/project.json`
- `src/projects/cmre-porting/stages/28-simulator-baseline-hardening/**`
- `src/projects/cmre-porting/vibe/**`
- `artifacts/projects/cmre-porting/stage28-simulator-baseline-hardening/**`
