# Stage 33: World-State Observability Contract

## Objective

Make simulator behavior auditable through explicit world-state snapshots and
trace sections before adding more feature breadth. This is the next
Simulation-First P0 step after the fidelity matrix; it does not claim native
SC2 parity and does not modify the read-only simulator package.

## Inputs

- `src/projects/cmre-porting/vibe/simulator_fidelity_matrix.py`
- `src/projects/cmre-porting/vibe/differential_validation.py`
- existing read-only simulator `WorldState`, snapshot, trace, and event models
- Stage 32 matrix artifact and the existing Stage 29 trace hash

## Deliverables

- A project-local observability contract covering the relevant state domains:
  `MapState`, `PlayerState`, `EntityState`, `ResourceState`,
  `TechnologyState`, `UpgradeState`, `VisionState`, `SpatialState`,
  `AbilityState`, `ProjectileState`, `MissionState`, `TriggerState`, and
  `RNGState`.
- Focused tests proving deterministic serialization, stable hashes, explicit
  domain presence, and no hidden-state omission in the contract report.
- A simulator-only JSON artifact with source paths, trace identity, and
  unresolved native-differential status.

## Boundaries

- Do not expand combat, economy, AI, or map behavior in this stage.
- Do not treat a simulator snapshot as a native runtime observation.
- Any domain not currently observable must be reported as `BLOCKED` or
  `UNSUPPORTED`, never silently omitted.

## Verification

```text
PYTHONPATH=src/projects/cmre-porting py -3.13 -m unittest discover -s src/projects/cmre-porting/stages/33-world-state-observability-contract -p test_world_state_observability_contract.py -v
PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.world_state_observability --out artifacts/projects/cmre-porting/stage33-world-state-observability-contract/world-state-observability-20260817.json
py -3.13 -m json.tool artifacts/projects/cmre-porting/stage33-world-state-observability-contract/world-state-observability-20260817.json
```

## Write scope

- `src/projects/cmre-porting/stages/33-world-state-observability-contract/**`
- `src/projects/cmre-porting/vibe/world_state_observability.py`
- `artifacts/projects/cmre-porting/stage33-world-state-observability-contract/**`
