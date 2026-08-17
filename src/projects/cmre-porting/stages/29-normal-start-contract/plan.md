# Stage 29: Normal Start Contract

## Objective

Establish a normal RTS macro-bootstrap scenario without adapter-injected advantages. Stage 29 must prove the deterministic simulator can start from a fair, ordinary Terran-vs-Terran opening state before any additional CMRE map coverage, commander simulation, or native mission-completion claim.

The target output is `normal-start-contract.v1` with `result_category=macro_bootstrap` and `native_claim=false`.

## Inputs

- `C:/Users/Sigeer/Downloads/sc2-simulator-next-stage-plan-stage29-plus.md`
- `src/projects/cmre-porting/stages/28-simulator-baseline-hardening/result.json`
- `src/projects/cmre-porting/vibe/catalog_fidelity.py`
- `src/projects/cmre-porting/vibe/run_cmre_map_matrix.py`
- `reference/sc2-ally-bot/src/sc2_simulator/` as read-only simulator source

## Normal-start contract

The Stage 29 scenario starts both sides from the same normal macro state:

```yaml
players:
  P1:
    race: Terran
    minerals: 50
    gas: 0
    workers: 12
  P2:
    race: Terran
    minerals: 50
    gas: 0
    workers: 12
enemy:
  none
```

## Prohibited adapter advantages

Stage 29 must not use any of the following to make the scenario pass:

- Initial combat-unit injection.
- Extra building injection.
- Resource multipliers or boosted starting resources.
- Enemy replacement.
- Enemy relocation or staging for clearance.
- Map-count expansion as a substitute for macro-bootstrap evidence.

## Required checks

The contract must independently validate:

- Worker mining.
- Resource income.
- Resource deposit.
- Supply handling.
- Worker survival.
- Building construction.
- Production completion.
- Combat-unit creation.
- No dispatch error.
- No deadlock.

## Deliverables

- `normal-start-contract.v1` report schema and generated artifact.
- A deterministic normal-start scenario builder or fixture that does not depend on CMRE adapter transforms.
- A focused simulator test proving the required checks pass from the normal-start state.
- Result-model fields that classify the outcome as `macro_bootstrap` and keep `native_claim=false`.
- Stage evidence in `log.md`, `result.json`, and `issues.json`.

## Non-goals

- No native SC2 mission-completion claim.
- No native runtime evidence lane; that belongs to Stage 31.
- No broader CMRE map-matrix expansion.
- No commander balance, commander-specific simulation, or ML policy training.
- No simulator value changes to chase balance parity.

## Verification

Initial validation for the stage-management transition:

```text
py -3.13 -m json.tool src/projects/cmre-porting/project.json
py -3.13 -m json.tool src/projects/cmre-porting/stages/28-simulator-baseline-hardening/result.json
py -3.13 -m json.tool src/projects/cmre-porting/stages/29-normal-start-contract/result.json
py -3.13 -m json.tool src/projects/cmre-porting/stages/29-normal-start-contract/issues.json
```

Implementation validation must add focused tests for `normal-start-contract.v1` before the stage can be marked complete.

## Write scope

- `src/projects/cmre-porting/project.json`
- `src/projects/cmre-porting/stages/28-simulator-baseline-hardening/**`
- `src/projects/cmre-porting/stages/29-normal-start-contract/**`
- `src/projects/cmre-porting/vibe/**`
- `artifacts/projects/cmre-porting/stage29-normal-start-contract/**`
