# Stage 07 Plan: Real Transport Adapters

> Start condition: Stage 06 ability slice PASS, with simulator effect requests and persistence
> limitations recorded explicitly.

## Objective

Map the verified Neuro/session, mission context, simulator action, and ability contracts onto
the supported real transports without moving mission authority into the adapter. The stage must
separate SC2 API observation/action, Bank-mediated action/context, and input fallback behavior.

## Contract

- Each transport consumes and produces the existing typed contracts; it must not expose hidden
  simulator or SC2 state to Neuro.
- Ability effect requests remain mission-owned. A transport reports accepted, rejected, or
  failed execution with stable action correlation.
- Reconnect and registration behavior reuse `NeuroRuntime`; transports must not duplicate its
  queue or lifecycle state machine.
- Real-SC2 claims require an approved launcher invocation, fresh GameLogs error review, and
  runtime listener/heartbeat evidence. Startup alone is insufficient.

## Planned Outputs

```text
cmre_neuro_adapter/transports/sc2api_neuro.py
cmre_neuro_adapter/transports/bank_neuro.py
cmre_neuro_adapter/transports/input_neuro.py
tests/test_transport_adapters.py
stages/07-real-adapters/result.json
stages/07-real-adapters/issues.json
```

## Work Plan

1. Run static discovery against the registered Neuro API and WoL repositories; document exact
   reference message, Bank, and input boundaries before writing adapters.
2. Implement a transport protocol and offline fakes that preserve `PublicMissionContext`,
   `ActionCommand`, `ExecutionResult`, and `AbilityEffectRequest` shapes.
3. Add reconnect, timeout, stale-state, duplicate, and transport-error tests without requiring
   an SC2 executable.
4. Wire the approved launcher path for the first real runtime probe. Do not launch
   `SC2_x64.exe` directly.
5. Review fresh `GameLogs/*ScriptError*.txt`, capture runtime listener/heartbeat evidence, and
   record any unavailable transport as an explicit issue.

## Gates

| Gate | Verification | Evidence |
|---|---|---|
| G1-contract | Typed transport boundaries preserve current message shapes | static + simulator |
| G2-reconnect | Reconnect restores identity, actions, and context without duplicate queue state | simulator |
| G3-failure | Timeout, stale version, duplicate, and backend errors become typed results | simulator |
| G4-live-probe | Approved launcher reaches runtime listener/heartbeat with fresh log review | runtime |
| G5-packaging | Adapter package validates without editing registered read-only sources | static |

## Non-goals

- Do not change canonical commander mods or mission-owned Galaxy scripts for adapter convenience.
- Do not claim live effects from static files, launcher exit code, or process startup alone.
- Do not introduce a new dependency until static discovery shows the existing registered tools
  cannot provide the required boundary.
