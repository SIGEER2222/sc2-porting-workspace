# Stage 07 Plan: Real Transport Adapters

> Start condition: Stage 06 ability slice PASS, with simulator effect requests and persistence
> limitations recorded explicitly.

## Objective

Map the verified Neuro/session, mission context, simulator action, and ability contracts onto
the supported real transports without moving mission authority into the adapter. The stage must
separate SC2 API observation/action, Bank-mediated action/context, and input fallback behavior.

## Foundation Priority

Before advancing the CMRE porting stages, complete the transport-neutral basic command surface
that the latest Neuro-WoL reference relies on around its campaign-specific abilities. The
reference emits movement, hold, patrol, stop, and attack as game activity context; CMRE therefore
needs explicit typed command routes for those operations instead of treating them as hidden
context-only behavior.

The first command slice is:

`move_units`, `stop_units`, `hold_units`, `patrol_units`, `attack_move_units`, `attack_units`,
`gather_resources`, `build_structure`, `produce_unit`, `research_upgrade`, the three cast forms,
`repair_units`, `morph_unit`, `cancel_order`, `load_units`, `unload_units`, and `rally_producer`.
Each route maps to one fixed SC2 command kind and is reusable by the simulator, SC2 API, Bank,
and input transports. Neuro-specific `call_merc` and `ability_*` actions remain an upper-layer
ability registry, not part of this generic command catalog.

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
2. Implement the typed basic command catalog and offline simulator proof before real transport
   probing. Array arguments must declare item schemas and all command routes must be explicit.
3. Implement a transport protocol and offline fakes that preserve `PublicMissionContext`,
   `ActionCommand`, `ExecutionResult`, and `AbilityEffectRequest` shapes.
4. Add reconnect, timeout, stale-state, duplicate, command-routing, and transport-error tests without requiring
   an SC2 executable.
5. Wire the approved launcher path for the first real runtime probe. Do not launch
   `SC2_x64.exe` directly.
6. Review fresh `GameLogs/*ScriptError*.txt`, capture runtime listener/heartbeat evidence, and
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
