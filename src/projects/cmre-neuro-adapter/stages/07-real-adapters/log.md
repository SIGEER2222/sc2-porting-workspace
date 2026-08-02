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
- `simulator`: after the foundation slice, the full adapter suite passed `72/72` tests. The new
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

That former derived player is retained only as a retired historical artifact. It used a legacy
map baseline and is not the current economy proof. The current proof is the clean fixture below;
it does not copy source entities or resources into the opening:

- source: `../cmre-porting/artifacts/dead_of_night_replay_20260730_224154.jsonl`
- derived replay: `artifacts/stage07-basic-command-replay-20260802/progression-replay.jsonl`
- player: `artifacts/stage07-basic-command-replay-20260802/full-map-player.html`
- screenshot: `artifacts/stage07-basic-command-replay-20260802/full-map-smoke.png`
- interaction screenshot: `artifacts/stage07-basic-command-replay-20260802/full-map-interaction.png`

The retired artifact's old claims are superseded by `MACRO-001` below.

`runtime`: Playwright Chromium opened the actual self-contained HTML. The initial frame rendered
`900000` non-empty canvas pixels, `54` visible entity rows, `250` minerals, `0` vespene, `28/31`
supply, and `16` action cards. 16x speed, seeking to loop `1000`, playback toggling, Marine
filtering, and entity selection all passed. This is local browser replay evidence, not a live SC2
runtime claim.

## State-driven Macro Closure

The implementation plan is recorded at `stages/07-real-adapters/macro-economy-implementation-plan.md`.
`cmre_neuro_adapter/macro_replay.py` now runs `MacroFixture.standard_opening()` through
`SimulatorSessionBackend` and `SimulatorTransport`. The planner consumes public observations and
M7 Catalog rules; it has no fixed action times and never calls `unit.spawn` or
`player.set_resource` after reset.

`simulator`: the fresh replay
`artifacts/stage07-basic-command-replay-20260802/state-driven-progression-replay.jsonl` starts
with `1 CommandCenter`, `8 SCV`, `6 MineralField`, and `2 VespeneGeyser`. It records `18/18`
completed actions: three additional SCVs, one SupplyDepot, one Barracks, one Refinery, two
Marines, opening mineral assignments, new-worker reassignment, and three gas-worker assignments.
The final census is `11 SCV`, `1 SupplyDepot`, `1 Barracks`, `1 Refinery`, `2 Marine`; the final
bank is `10` minerals and `24` vespene. The summary explicitly reports
`no_synthetic_entities=true` and the accepted/started/completed/failed lifecycle.

`runtime`: Playwright Chromium opened
`artifacts/stage07-basic-command-replay-20260802/state-driven-player.html`. Canvas pixel check
reported `900000` non-empty pixels at `1200x750`; seek moved to loop `520`, `16x` activated,
playback entered the active state, lifecycle event text was present, and the screenshot is
`artifacts/stage07-basic-command-replay-20260802/state-driven-player-smoke.png`. This is browser
replay evidence, not live SC2 runtime evidence.

The local simulator's placement validator reserves neutral resource footprints for all structure
builds, so the fixture places the Refinery in a free slot and keeps the declared geyser as the
public gas source. This is recorded as a simulator limitation rather than hidden by synthetic
entities.

## Visual Replay Verification

- `static`: `python -m cmre_neuro_adapter.replay_player artifacts/stage07-basic-command-replay-20260802/replay.jsonl --output artifacts/stage07-basic-command-replay-20260802/player.html` -> generated a 45 KB self-contained HTML file from the 26-record JSONL replay.
- `runtime`: Chrome headless DOM check -> title, `SIMULATOR PASS`, Canvas, seek range `0..20`, and `16x` control rendered.
- `runtime`: Chrome CDP interaction check -> Canvas had `900000` non-empty pixels; `16x` activated; seek selected loop `100`; play/pause changed button state; end selected loop `195`.
- `runtime`: the browser screenshot is local replay-player evidence only; it is not a live SC2 runtime or G4 pass.

## Verification Refresh

- `simulator`: `python -m pytest tests/test_transport_adapters.py --maxfail=20 -q` -> `6 passed`.
- `simulator`: `python -m unittest tests.test_basic_actions -v` -> `6/6` tests passed.
- `simulator`: `python -m unittest discover -s tests -q` -> `72/72` tests passed.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass.
- `static`: Python 3.11 grammar fallback -> `55` files passed with `ast.parse(..., feature_version=(3,11))`.
- `static`: Stage 07 JSON parse and `git diff --check -- src/projects/cmre-neuro-adapter` -> pass.
- `simulator`: macro replay assertions -> `PASS`; the state-driven JSONL summary reports
  `18/18` completed actions, all required entity completions, positive mineral/gas collection,
  and no synthetic entities.

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

## Real Map Replay Attempt 2026-08-02

The requested replay target was confirmed as the real `亡者之夜.SC2Map` map. The encrypted live
map was unpacked with `tools/mpq/MPQEditor.exe` into
`artifacts/real-map-source-20260802/`; the source contains `Minimap.tga`, `Objects`, terrain,
regions, and the complete map data. `Objects` contains 1319 original `ObjectUnit` records and
the terrain height map is 193x193. `Minimap.tga` was converted to `minimap.png` and its map
content rectangle is recorded as pixels 48..208 over world bounds 16..176.

`static`: `python -m cmre_neuro_adapter.real_map_replay` metadata construction and the focused
replay tests pass. The player now embeds the real minimap, world-coordinate transform, all
original `Objects`, P1/P2 friendly ownership, and a toggleable static layer; playback still
supports seeking, pause/play, and 0.5x..16x speed.

`runtime`: the approved launcher successfully staged isolated CMRE overlays for
`real-map-replay-live1`, `live2`, `live4`, and `live6`; each staged directory packed successfully
with `tools/mpq/scripts/pack-sc2map.ps1` (76 files, 3,285,137 bytes). These are staging/packaging
claims only. Attempts to hold a dedicated 5191 runtime were repeatedly blocked or lost because
other valid KeepAlive sessions occupied the global lease; the latest external owner was
`owner_pid=27016`, `runtime_pid=38420`, `port=5192`, session
`cmre_alenger-20260802-172211-66826c28`. The owner heartbeat remained valid throughout the final
polling window. A connection-refused capture and a shell-lifecycle timeout produced no replay
JSONL and are not promoted to runtime evidence.

`blocked`: no `CreateGame + JoinGame + RequestStep` evidence, runtime entity/resource/action
trace, or same-window ScriptError verdict was obtained for this run. Do not use the static preview
or simulator macro replay as a real runtime substitute. Re-run the approved launcher after the
external 5192 lease is released; keep the real-map source and player implementation unchanged.

The extracted map source and packed staging copies remain local under `artifacts/` and are
intentionally not included in the code commit because they are generated 60+ MB map copies.
Their paths and hashes are recorded by the stage artifacts and this log; the committed change
contains the replay implementation, player, tests, and stage evidence updates.

Follow-up retry at `2026-08-02T17:50:11+08:00` also lost the free window to a valid external
KeepAlive session `owner_pid=38060`, `runtime_pid=5000`, `port=5201`, session
`cmre_alenger-20260802-175011-03672d29`. The retry was stopped before any connection to that
session; G4 remains blocked.

## Playback Guard Refresh 2026-08-02 18:03 +08:00

The opened `real-map-static-preview.html` is intentionally a static real-map inspection, not a
runtime replay. Its JSONL contains one `frame` at loop 0 plus `header`, `map`, and `summary`
records, so playback has no second state to advance to. The player previously exposed normal
playback controls for that single-frame input, which made the control appear broken.

The player now detects `STATIC_PREVIEW` or a static single-frame payload, shows
`静态地图预览 · 无动态回放帧`, and disables play, frame stepping, speed, and seeking. The
existing state-driven simulator replay remains a separate playable artifact with 147 frames.

Evidence:

- `simulator`: `python -m unittest tests.test_replay_player -v` -> `7` tests passed.
- `static`: `python -m compileall -q cmre_neuro_adapter tests` -> pass.
- `static`: `git diff --check -- src/projects/cmre-neuro-adapter/...` -> pass.
- `runtime`: Chrome headless DOM load of `real-map-static-preview.html` -> status text rendered,
  play/step/seek controls rendered with `disabled`.
- `runtime`: Chrome headless DOM load of `state-driven-player.html` -> play button remained
  enabled and the timeline range was `0..146`.

This does not change the live runtime blocker. A genuine real-map dynamic replay still requires
an independent approved SC2 runtime lease and `CreateGame + JoinGame + RequestStep` evidence.
