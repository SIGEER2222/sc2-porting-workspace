# Stage 43: Mission Adapter Contract

## Objective

Advance the simulation-first CMRE progression through `mission-adapter-contract` while keeping
all evidence explicitly scoped to deterministic simulator/control-plane output.

## Inputs

- `src/projects/cmre-porting/vibe/simulation_first_progression.py`
- Prior stage quartet/result files where referenced by generated artifacts
- Read-only simulator APIs exposed through `src/projects/cmre-porting/vibe/`

## Deliverables

- `artifacts/projects/cmre-porting/stage43-mission-adapter-contract/mission-adapter-contract-20260817.json`
- Stage-local `result.json`, `log.md`, `issues.json`, and this `plan.md`
- Explicit `BLOCKED`/`PARTIAL` status where simulator evidence cannot prove native behavior

## Verification

```text
PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.simulation_first_progression --stage 43 --out artifacts/projects/cmre-porting/stage43-mission-adapter-contract/mission-adapter-contract-20260817.json
py -3.13 -m json.tool artifacts/projects/cmre-porting/stage43-mission-adapter-contract/mission-adapter-contract-20260817.json
```

## Write scope

- `src/projects/cmre-porting/stages/43-mission-adapter-contract/**`
- `artifacts/projects/cmre-porting/stage43-mission-adapter-contract/**`
- `src/projects/cmre-porting/vibe/simulation_first_progression.py`
