# Stage 32: Simulator Fidelity Matrix

## Objective

Build a reproducible, simulator-only feature matrix that makes support and
fidelity boundaries explicit. This stage continues the Simulation-First
workstream; it does not modify the reference simulator, collect native SC2
observations, or claim mission completion.

## Inputs

- `src/projects/cmre-porting/vibe/catalog_fidelity.py`
- `src/projects/cmre-porting/vibe/normal_start_contract.py`
- `src/projects/cmre-porting/vibe/differential_validation.py`
- `artifacts/projects/cmre-porting/stage30-differential-validation-layer/differential-report-20260817.json`
- operator-supplied `sc2-simulator-improvement-plan-v2-simulation-first-20260817.md`
- read-only simulator catalog and systems under `reference/sc2-ally-bot/`

## Deliverables

- `vibe/simulator_fidelity_matrix.py`: a project-local report builder and CLI.
- `test_simulator_fidelity_matrix.py`: focused contract tests for all 27
  roadmap rows, truthful status labels, provenance, and artifact writing.
- `artifacts/projects/cmre-porting/stage32-simulator-fidelity-matrix/fidelity-matrix-20260817.json`.
- A stage result, issue register, and log with evidence paths.

## Matrix contract

Each row contains `domain`, `feature`, `supported`, `fidelity`, `tested`,
`test_id`, `native_differential`, `native_differential_reason`, and `source`.
The matrix includes every requested row from the roadmap:

- Unit: HP/Shield, Armor
- Weapon: Damage, Period, Range, Target Filter
- Movement: Speed, Acceleration, Collision
- Combat: Damage, Splash, Search
- Economy: Gather, Deposit
- Production: Train
- Upgrade: Modifier
- Ability: Cost, Cooldown, Effect
- Vision: Sight
- Terrain: Walkable, Height
- Pathing: Path
- Trigger: Event, Condition, Action
- Mission: Objective

`fidelity` describes the current deterministic simulator boundary, not native
SC2 parity. `native_differential` is `BLOCKED` for every row until an explicit
runtime-labelled observation exists. Unsupported features remain visible as
`UNSUPPORTED`; they must not disappear from the denominator.

`tested=true` means the generator's static capability probe completed for that
row; it does not assert a native or full behavioral equivalence test.

## Verification

```text
PYTHONPATH=src/projects/cmre-porting py -3.13 -m unittest discover -s src/projects/cmre-porting/stages/32-simulator-fidelity-matrix -p test_simulator_fidelity_matrix.py -v
PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.simulator_fidelity_matrix --out artifacts/projects/cmre-porting/stage32-simulator-fidelity-matrix/fidelity-matrix-20260817.json
py -3.13 -m json.tool artifacts/projects/cmre-porting/stage32-simulator-fidelity-matrix/fidelity-matrix-20260817.json
```

The CLI exits successfully for a valid simulator report even when native
comparison is `BLOCKED`. Native completion remains outside this stage.

## Write scope

- `src/projects/cmre-porting/stages/32-simulator-fidelity-matrix/**`
- `src/projects/cmre-porting/vibe/simulator_fidelity_matrix.py`
- `artifacts/projects/cmre-porting/stage32-simulator-fidelity-matrix/**`
