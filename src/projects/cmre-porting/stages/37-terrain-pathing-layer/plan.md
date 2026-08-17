# Stage 37: Terrain Pathing Layer

## Objective

Advance the simulation-first CMRE progression through `terrain-pathing-layer` while keeping
all evidence explicitly scoped to deterministic simulator/control-plane output.

## Inputs

- `src/projects/cmre-porting/vibe/simulation_first_progression.py`
- Prior stage quartet/result files where referenced by generated artifacts
- Read-only simulator APIs exposed through `src/projects/cmre-porting/vibe/`

## Deliverables

- `artifacts/projects/cmre-porting/stage37-terrain-pathing-layer/terrain-pathing-layer-20260817.json`
- Stage-local `result.json`, `log.md`, `issues.json`, and this `plan.md`
- Explicit `BLOCKED`/`PARTIAL` status where simulator evidence cannot prove native behavior

## Verification

```text
PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.simulation_first_progression --stage 37 --out artifacts/projects/cmre-porting/stage37-terrain-pathing-layer/terrain-pathing-layer-20260817.json
py -3.13 -m json.tool artifacts/projects/cmre-porting/stage37-terrain-pathing-layer/terrain-pathing-layer-20260817.json
```

## Write scope

- `src/projects/cmre-porting/stages/37-terrain-pathing-layer/**`
- `artifacts/projects/cmre-porting/stage37-terrain-pathing-layer/**`
- `src/projects/cmre-porting/vibe/simulation_first_progression.py`
