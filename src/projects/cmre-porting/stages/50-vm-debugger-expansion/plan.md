# Stage 50: Ares-Inspired Tactical Validation Layer

## Objective

Pivot Stage 50 from VM-debugger work to the simulator's macro tactical validation
lane. The simulator should act as a PvE AI tactical evaluation sandbox and CI
regression gate: it should answer whether one AI strategy completes a tactical
objective faster, more reliably, or with better tradeoffs than another.

## Inputs

- `src/projects/cmre-porting/stages/49-commander-balance-report/result.json`
- `artifacts/projects/cmre-porting/stage49-commander-balance-report/commander-balance-report-20260817.json`
- `src/projects/cmre-porting/stages/50-vm-debugger-expansion/sc2-simulator-macro-tactics-questionnaire-20260818.md`
- `src/projects/cmre-porting/stages/50-vm-debugger-expansion/sc2-simulator-macro-tactics-roadmap-20260818.md`
- `src/projects/cmre-porting/stages/50-vm-debugger-expansion/ares-sc2-tactical-layer-integration-20260818.md`
- Local reference: `E:/Code/sc2-rts-reference/ares-sc2`

## Deliverables

- A Stage50 macro tactical validation roadmap derived from the user's answers.
- An Ares-SC2 tactical-layer integration note covering mediator, behavior, role,
  squad, build-runner, and engagement-result abstractions.
- A next implementation sequence for `tactical_report.v1`, Ares-inspired
  Observation/Action/Mediator interfaces, experiment runner, timing-push golden
  scenario, and CI regression gate.

## Verification

```text
py -3.13 -m json.tool src/projects/cmre-porting/stages/49-commander-balance-report/result.json
```

## Boundaries

- Do not make SC2 native/runtime parity a prerequisite for simulator tactical work.
- Do not let micro-rule fidelity gaps block macro tactical validation; use M7
  capability coverage to mark confidence/reliability instead.
- Use Ares-SC2 as a tactical decision vocabulary/reference, not as a bottom-up
  simulator implementation source.
- Keep VM debugger / hook work out of this stage unless a later stage explicitly
  reopens that lane.
