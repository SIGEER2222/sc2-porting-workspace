# Stage 35: Golden Scenario Framework

## Objective

Advance the simulation-first CMRE progression through `golden-scenario-framework` while keeping
all evidence explicitly scoped to deterministic simulator/control-plane output.

## Inputs

- `src/projects/cmre-porting/vibe/simulation_first_progression.py`
- Prior stage quartet/result files where referenced by generated artifacts
- Read-only simulator APIs exposed through `src/projects/cmre-porting/vibe/`

## Deliverables

- `artifacts/projects/cmre-porting/stage35-golden-scenario-framework/golden-scenario-framework-20260817.json`
- Stage-local `result.json`, `log.md`, `issues.json`, and this `plan.md`
- Explicit `BLOCKED`/`PARTIAL` status where simulator evidence cannot prove native behavior

## Verification

```text
PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.simulation_first_progression --stage 35 --out artifacts/projects/cmre-porting/stage35-golden-scenario-framework/golden-scenario-framework-20260817.json
py -3.13 -m json.tool artifacts/projects/cmre-porting/stage35-golden-scenario-framework/golden-scenario-framework-20260817.json
```

## Write scope

- `src/projects/cmre-porting/stages/35-golden-scenario-framework/**`
- `artifacts/projects/cmre-porting/stage35-golden-scenario-framework/**`
- `src/projects/cmre-porting/vibe/simulation_first_progression.py`
