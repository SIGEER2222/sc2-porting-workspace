# Stage 30: Differential Validation Layer

## Objective

Build a `differential-report.v1` layer that compares deterministic simulator observations against native SC2 runtime observations without converting either lane into a native mission-completion claim.

Stage 30 starts from the Stage 29 `normal-start-contract.v1` PASS artifact and defines how equivalent simulator/native observations are collected, normalized, compared, and classified.

## Inputs

- `artifacts/projects/cmre-porting/stage29-normal-start-contract/normal-start-contract-20260817.json`
- `src/projects/cmre-porting/vibe/normal_start_contract.py`
- `src/projects/cmre-porting/vibe/simulator_session.py`
- `reference/sc2-ally-bot/src/sc2_simulator/` as read-only simulator source
- Launcher-owned SC2 runtime evidence rules from `AGENTS.md`
- `C:/Users/Sigeer/Downloads/sc2-simulator-next-stage-plan-stage29-plus.md`

## Differential Scope

The first `differential-report.v1` must define comparable observations for:

- Entity creation.
- Resource changes.
- Unit stats.
- Build time.
- Cost.
- Ability execution.
- Upgrade state.
- Trigger result.

## Guardrails

- Do not claim native mission completion in Stage 30.
- Do not expand CMRE map coverage as a substitute for differential evidence.
- Do not adjust simulator balance values to force parity.
- Keep simulator evidence, native runtime evidence, and inference clearly separated.
- Any native trace must use a compliant launcher-owned SC2 process and same-window ScriptError/runtime-listener evidence.

## Deliverables

- `differential-report.v1` result schema and at least one generated report artifact.
- A reusable comparator that consumes normalized simulator and native observation records.
- A fixture list covering the differential scope above.
- Focused tests for schema validation, comparator classification, and blocked/native-missing evidence handling.
- Updated `log.md`, `result.json`, and `issues.json` with evidence.

## Verification

Initial stage-open validation:

```text
py -3.13 -m json.tool src/projects/cmre-porting/stages/30-differential-validation-layer/result.json
py -3.13 -m json.tool src/projects/cmre-porting/stages/30-differential-validation-layer/issues.json
```

Implementation validation must add focused tests for `differential-report.v1` before the stage can be marked complete.

## Write scope

- `src/projects/cmre-porting/project.json`
- `src/projects/cmre-porting/stages/29-normal-start-contract/**`
- `src/projects/cmre-porting/stages/30-differential-validation-layer/**`
- `src/projects/cmre-porting/vibe/**`
- `artifacts/projects/cmre-porting/stage29-normal-start-contract/**`
- `artifacts/projects/cmre-porting/stage30-differential-validation-layer/**`
