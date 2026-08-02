# Stage 07 Log: Real Transport Adapters

## Progress

The simulator-facing real transport boundaries are implemented within the declared
`cmre-neuro-adapter` write scope. The stage remains blocked at the live probe gate because
the approved launcher found an existing SC2 runtime lease owned by another session.

The foundation-first priority is now explicit: the latest Neuro-WoL remote reference is at
`c723336` (`Fully implemented ability system`). It has broad campaign abilities and reports
movement/combat activity as context, but it does not make every SC2 command a generic Neuro action.
CMRE therefore owns a separate typed basic-command catalog and keeps `ability_*`, `call_merc`,
and mission-specific production policy above it.

An inspectable foundation replay is available under
`artifacts/stage07-basic-command-replay-20260802/`. It records the Neuro action lifecycle,
public context snapshots, state changes, command results, and the canonical simulator event trace.
The same artifact directory now contains `player.html`, a self-contained minimap-style browser
replay with seeking, playback, speed controls, and action/event markers.

## Failure-First Diagnostic

- `simulator`: the initial transport test command failed with
  `ModuleNotFoundError: No module named 'tests.test_transport_adapters'` because the declared
  Stage 07 test module and transport package did not yet exist. This failure drove the bounded
  transport implementation and regression tests.
- `simulator`: after implementation, the focused transport suite passed `6/6` and the project
  suite passed `62/62` tests with `22` subtests under Python 3.13.
- `simulator`: after the foundation slice, the full adapter suite passed `71/71` tests. The new
  command tests drove `SimulatorSession.unit_order` and observed a Marine move, a Barracks build,
  and a Marine production result.
- `simulator`: the adapter-aware replay executed `3/3` actions successfully through
  `NeuroRuntime`; the Marine reached `(5, 3)`, one Barracks completed, and the Marine census became
  `2`. The canonical event trace contains `6` events with SHA-256
  `920767ed775b401632f9ba9004f1ae461d4006589c4e0691a95d46c52269c866`.
- `runtime`: an approved launcher preflight with `-NoLaunch` completed staging successfully,
  but it did not count as live evidence.
- `runtime`: the live launcher attempt was rejected before staging with
  `SC2_RUNTIME_BUSY`, owner PID `36840`, port `5121`, and session
  `cmre_alenger-20260802-124748-6ee40c06`. This is an existing session and was not terminated
  or taken over.

## Evidence

- `simulator`: `python -m pytest tests/test_transport_adapters.py --maxfail=20 -q` -> `6 passed`.
- `simulator`: `python -m pytest -q` -> `62 passed, 22 subtests passed`.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass under Python 3.13.
- `static`: Python 3.11 grammar fallback -> `55` project/test files passed
  `ast.parse(..., feature_version=(3,11))`; no Python 3.11 runtime claim is made.
- `static`: `git diff --check -- src/projects/cmre-neuro-adapter` -> pass before stage metadata
  was added.
- `runtime`: approved preflight command:
  `pwsh -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander TerranRaynor -ListenPort 5091 -ApiMinimal -DebugMode -NoLaunch -MapCopySuffix stage07-preflight`
  -> staging completed and lock released.
- `runtime`: live probe command:
  `pwsh -NoProfile -ExecutionPolicy Bypass -File tools/launchers/launch-cmre-alenger.ps1 -MapName 亡者之夜.SC2Map -Commander TerranRaynor -ListenPort 5091 -DebugMode -KeepAlive -MapCopySuffix stage07-runtime`
  -> blocked by `SC2_RUNTIME_BUSY` before API listening. Captured output:
  `artifacts/projects/cmre-neuro-adapter/artifacts/stage07-real-runtime-20260802-125047/launcher-stdout.txt`
  and `artifacts/projects/cmre-neuro-adapter/artifacts/stage07-real-runtime-20260802-125047/launcher-stderr.txt`.
- `runtime`: `python tools/galaxy-vibe/script_error_check.py --since 1785646068 --out src/projects/cmre-neuro-adapter/artifacts/stage07-real-runtime-current-check-script-error-verdict.json` -> no new errors, but this scan is not a same-window successful Stage 07 runtime and is non-qualifying for G4.

## Foundation Evidence

- `static`: `cmre_neuro_adapter/neuro/basic_actions.py` defines 19 explicit command routes; each
  route fixes one simulator/SC2 command kind and has a closed argument schema.
- `simulator`: `tests/test_basic_actions.py` covers route completeness, research argument
  normalization, array validation, movement state change, construction completion, and unit
  production.
- `static`: `neuro/schemas.py` now supports typed arrays only when an `items` schema is present;
  the existing invalid-schema regression remains passing.

## Gate Results

| Gate | Result | Evidence |
|---|---|---|
| G1-contract | PASS | Typed transport boundaries and focused simulator tests |
| G2-reconnect | PASS | Reconnect and idempotency tests with injected fakes |
| G3-failure | PASS | Timeout, stale-state, duplicate, unsupported, and backend-error tests |
| G4-live-probe | BLOCKED | Approved launcher blocked by an unrelated existing SC2 runtime lease |
| G5-packaging | PASS | Python tests, compileall, Python 3.11 grammar fallback, and diff check |

## Changes

- `cmre_neuro_adapter/transports/common.py`: shared typed transport status, execution result,
  error, correlation, state-version, and canonical payload helpers.
- `cmre_neuro_adapter/transports/sc2api_neuro.py`: injected async SC2 API boundary with
  timeout, reconnect, public context projection, stale-state checks, and duplicate results.
- `cmre_neuro_adapter/transports/bank_neuro.py`: injected Bank store boundary with XML Bank
  read/write support, atomic replacement, context publication, action staging, and result polling.
- `cmre_neuro_adapter/transports/input_neuro.py`: explicit input binding fallback with typed
  action results and explicit unsupported observation/context operations.
- `tests/test_transport_adapters.py`: offline transport contract, failure, reconnect,
  idempotency, XML round-trip, and input fallback coverage.
- `cmre_neuro_adapter/neuro/basic_actions.py`: explicit basic command catalog and fixed route
  conversion for movement, combat, economy, production, upgrades, abilities, and utility orders.
- `cmre_neuro_adapter/neuro/schemas.py`: typed array argument validation for grouped unit IDs.
- `cmre_neuro_adapter/neuro/simulator_transport.py`: optional basic-action routing through the
  canonical `unit.order` operation.
- `tests/test_basic_actions.py`: simulator-backed foundation regression suite.

## Replay Artifacts

- `artifacts/stage07-basic-command-replay-20260802/replay.jsonl`: adapter-aware JSONL replay with
  action IDs, acceptance/dispatch results, public contexts, state checks, and key events.
- `artifacts/stage07-basic-command-replay-20260802/simulator-events.jsonl`: canonical simulator
  event and command-result trace.
- `artifacts/stage07-basic-command-replay-20260802/summary.json`: replay summary and trace hash.
- `artifacts/stage07-basic-command-replay-20260802/player.html`: self-contained visual replay
  player with a Canvas minimap, draggable timeline, playback controls, and `0.5x` through `16x`
  speed buttons.
- `artifacts/stage07-basic-command-replay-20260802/player-smoke.png`: Chrome headless screenshot
  proving the rendered player is non-empty.

## Economy Progression Replay

The previous full-map artifact used `dead_of_night_replay_20260802_124446.jsonl`, whose loop-0
observation already contained `159` P1 entities including `128` Battlecruisers and a constant
`50` mineral bank. That is a terminal-style test snapshot, not a credible opening, so it was
retired from the player.

The corrected player uses the older complete map observation as its baseline and adds a bounded,
deterministic economy layer without editing the read-only `cmre-porting` project:

- source: `../cmre-porting/artifacts/dead_of_night_replay_20260730_224154.jsonl`
- derived replay: `artifacts/stage07-basic-command-replay-20260802/progression-replay.jsonl`
- player: `artifacts/stage07-basic-command-replay-20260802/full-map-player.html`
- screenshot: `artifacts/stage07-basic-command-replay-20260802/full-map-smoke.png`
- interaction screenshot: `artifacts/stage07-basic-command-replay-20260802/full-map-interaction.png`

`simulator`: the derived replay has `36` frames over loop `0..3500`. It starts with `27` P1
entities, `1` enemy sensor tower, and `26` neutral resource entities. The source neutral and
enemy entity lists, plus baseline P1 entities, are preserved frame-by-frame. The progression
layer starts at `250` minerals and `0` vespene, charges explicit costs, and records `16`
successful actions plus `256` displayed frame events, including SCV/Marine/Marauder training,
Supply Depot/Barracks/Refinery/Turret construction, Combat Shield research scheduling, enemy
waves, and deaths. The final displayed bank is `5` minerals, `74` vespene, and `16/31` supply
after combat losses.

`runtime`: Playwright Chromium opened the actual self-contained HTML. The initial frame rendered
`900000` non-empty canvas pixels, `54` visible entity rows, `250` minerals, `0` vespene, `28/31`
supply, and `16` action cards. 16x speed, seeking to loop `1000`, playback toggling, Marine
filtering, and entity selection all passed. This is local browser replay evidence, not a live SC2
runtime claim.

## Visual Replay Verification

- `static`: `python -m cmre_neuro_adapter.replay_player artifacts/stage07-basic-command-replay-20260802/replay.jsonl --output artifacts/stage07-basic-command-replay-20260802/player.html` -> generated a 45 KB self-contained HTML file from the 26-record JSONL replay.
- `runtime`: Chrome headless DOM check -> title, `SIMULATOR PASS`, Canvas, seek range `0..20`, and `16x` control rendered.
- `runtime`: Chrome CDP interaction check -> Canvas had `900000` non-empty pixels; `16x` activated; seek selected loop `100`; play/pause changed button state; end selected loop `195`.
- `runtime`: the browser screenshot is local replay-player evidence only; it is not a live SC2 runtime or G4 pass.

## Verification Refresh

- `simulator`: `python -m pytest tests/test_transport_adapters.py --maxfail=20 -q` -> `6 passed`.
- `simulator`: `python -m unittest tests.test_basic_actions -v` -> `6/6` tests passed.
- `simulator`: `python -m unittest discover -s tests -q` -> `71/71` tests passed.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass.
- `static`: Python 3.11 grammar fallback -> `55` files passed with `ast.parse(..., feature_version=(3,11))`.
- `static`: Stage 07 JSON parse and `git diff --check -- src/projects/cmre-neuro-adapter` -> pass.
- `simulator`: replay artifact assertions -> `PASS`; `replay.jsonl` contains `26` records and
  `summary.json` reports `3/3` actions and the expected move/build/produce effects.

## Problems and Limitations

- Python 3.11 is not installed. Compatibility is limited to grammar parsing plus Python 3.13
  execution; no 3.11 runtime claim is made.
- No live Neuro WebSocket, Bank-in-game, SC2 API action, or Stage 07 runtime heartbeat claim
  is made. The live launcher could not acquire the global runtime lease.
- The basic command catalog is simulator-verified but not yet proven against the live SC2 API,
  Bank execution loop, or input injection. Those remain the G4 follow-up.
- The current owner session at port `5121` must finish or release its lease before a new live
  probe can be run. It is not safe for this stage to terminate it because it was not created by
  this run.

## Handoff

Stage 07 remains the active stage. Re-run the live probe through the approved launcher after
the existing runtime lease is released, then perform `CreateGame + JoinGame`, collect runtime
listener/heartbeat evidence, and run a same-window `ScriptError` check. Do not mark G4 PASS or
write a next-stage plan from the current evidence.
