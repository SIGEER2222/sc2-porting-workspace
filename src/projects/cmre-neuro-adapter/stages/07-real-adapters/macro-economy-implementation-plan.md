# Macro Economy and Production Closure Plan

## Target result

Replace the previous fixed-time progression replay with a state-driven Terran macro
fixture that can be executed through the existing simulator transport and replayed
in the minimap player. The opening must contain only declared starting assets. New
SCVs, buildings, and combat units may appear only after an accepted command has
started and the simulator has observed its completion.

## Architecture

1. `macro_replay.py` owns the fixture, planner, runner, lifecycle ledger, and JSONL
   replay serialization. It uses the public `SimulatorSessionBackend` and
   `SimulatorTransport` boundary; the planner does not receive the simulator world.
2. `MacroCatalog` reads unit costs, supply, build time, producer/builder, and
   requirements from the loaded M7 Catalog. No production cost or duration is copied
   into the policy.
3. `StateDrivenMacroPlanner` makes decisions from each public observation:
   - assign all declared opening SCVs to declared mineral nodes;
   - continuously train SCVs when the Command Center is idle and resources/supply
     permit;
   - build a Supply Depot before the next supply block;
   - build Barracks after the depot completes;
   - train Marines only from a completed Barracks;
   - add a Refinery after Barracks and gas demand are available;
   - keep every producer and builder single-booked until observation confirms the
     order completed.
4. `MacroReplayRunner` advances the simulator in bounded steps, snapshots public
   observations, correlates entity tags, and records
   `accepted -> started -> completed` or `failed`. A successful dispatch is not a
   completion claim.
5. `progression_replay.py` becomes a compatibility CLI that generates the new clean
   macro replay. It will reject legacy source frames as an execution source instead
   of adding synthetic entities to them.

## Evidence sources

- `src/projects/cmre-neuro-adapter/cmre_neuro_adapter/neuro/simulator_transport.py`:
  typed public observation/action boundary and simulator dispatch behavior
  (`simulator` evidence after execution).
- `src/projects/cmre-porting/vibe/contracts.py` and
  `src/projects/cmre-porting/vibe/simulator_session.py`: existing observation,
  scenario, step, and Catalog-backed simulation contracts (`static` source; the
  adapter will not modify these files).
- `reference/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py` and
  `reference/sc2-ally-bot/src/sc2_simulator/systems/{economy,construction,production}.py`:
  authoritative local simulator costs, prerequisites, queues, and completion rules
  (`static` source).
- `reference/python-sc2/examples/terran/mass_reaper.py` and
  `reference/python-sc2/sc2/bot_ai.py`: mature worker distribution, pending-build,
  affordability, supply, and producer-idle patterns (`static` source).
- `reference/SC2-Neuro-WoL-Integration`: resource/production context and completion
  event separation (`static` source; no source edits).

## Acceptance

- The generated replay starts with exactly the declared fixture assets and no Marine,
  Marauder, Supply Depot, Barracks, or Refinery.
- Mineral income is zero before gather orders and positive only after SCVs are assigned
  to mineral nodes; resource balances show income before each spend.
- At least two SCVs and two Marines complete through the simulator; no unit is inserted
  by the replay builder.
- At least one Supply Depot, Barracks, and Refinery each has a real entity tag and a
  completion observation; Marines are never queued before Barracks completion.
- Every produced entity has a correlated action id, accepted/started/completed records,
  and a simulator-observed entity tag. Failed/rejected attempts carry a reason.
- No `unit.spawn`, `player.set_resource`, or fixed `ScheduledAction` is used by the
  macro run after fixture initialization.
- Existing replay-player controls continue to render the generated JSONL; a browser
  smoke check verifies canvas, seeking, playback, speed, and lifecycle events.

## Validation and stop condition

Run the focused macro tests, the full adapter test suite, compile/static checks, then
generate a fresh replay and player under `artifacts/`. Inspect the JSONL assertions and
run the browser smoke check. The implementation is complete when these simulator and
browser gates pass. Live SC2 remains a separate runtime gate and is not claimed unless
the approved launcher, listener/heartbeat, advancing frames, and same-window
`ScriptError` verdict are available.
