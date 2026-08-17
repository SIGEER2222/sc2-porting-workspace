# Stage 50: VM Debugger Expansion

## Objective

Return from simulator-first control-plane reports to the generic-runtime-lab VM
debugger lane.  Use the Stage 03 current VM signature trace and the Stage 49
commander-balance report as inputs, but do not enable executable hooks until a
current-version signature is independently validated in a launcher-owned debug
process.

## Inputs

- `src/projects/generic-runtime-lab/stages/03-current-vm-signature-trace/result.json`
- `src/projects/cmre-porting/stages/49-commander-balance-report/result.json`
- `artifacts/projects/cmre-porting/stage49-commander-balance-report/commander-balance-report-20260817.json`

## Deliverables

- A debugger expansion plan that separates static signature candidates, debug-window observations, and any future hook promotion.
- Explicit carry-forward blockers for native SC2 runtime evidence and native differential comparison.

## Verification

```text
py -3.13 -m json.tool src/projects/cmre-porting/stages/49-commander-balance-report/result.json
```

## Boundaries

- Do not treat Stage 49 simulator balance rows as native balance evidence.
- Do not patch or hook SC2 without a fresh launcher-owned debug process and same-window ScriptError evidence.
