# Stage 49: Commander Balance Report

## Objective

Advance the simulation-first CMRE progression through `commander-balance-report` while keeping
all evidence explicitly scoped to deterministic simulator/control-plane output.

## Inputs

- `src/projects/cmre-porting/vibe/simulation_first_progression.py`
- Prior stage quartet/result files where referenced by generated artifacts
- Read-only simulator APIs exposed through `src/projects/cmre-porting/vibe/`

## Deliverables

- `artifacts/projects/cmre-porting/stage49-commander-balance-report/commander-balance-report-20260817.json`
- Stage-local `result.json`, `log.md`, `issues.json`, and this `plan.md`
- Explicit `BLOCKED`/`PARTIAL` status where simulator evidence cannot prove native behavior

## Verification

```text
PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.simulation_first_progression --stage 49 --out artifacts/projects/cmre-porting/stage49-commander-balance-report/commander-balance-report-20260817.json
py -3.13 -m json.tool artifacts/projects/cmre-porting/stage49-commander-balance-report/commander-balance-report-20260817.json
py -3.13 -m unittest discover -s src/projects/cmre-porting/stages/49-commander-balance-report -p test_commander_balance_report.py -v
```

## Write scope

- `src/projects/cmre-porting/stages/49-commander-balance-report/**`
- `artifacts/projects/cmre-porting/stage49-commander-balance-report/**`
- `src/projects/cmre-porting/vibe/simulation_first_progression.py`
