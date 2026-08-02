# Stage 25 Log

## Status

In progress. The stage is active because implementation of the requested P1/P2
cooperative AI ally behavior has begun.

## Native Task Simulator Verification 2026-08-02

- `simulator`: the project-owned native task now controls P2 explicitly and
  starts from a real P2 CommandCenter plus six SCVs, neutral mineral fields,
  and a neutral geyser. It does not call `unit.spawn`,
  `player.set_resource`, or `unit.kill` during the strategy loop.
- `simulator`: seeds `42`, `7`, and `99` all passed the same end-to-end loop.
  Each run built a SupplyDepot and Refinery at loop `0`, built a Barracks at
  loop `30`, trained three Marines, recorded mineral and vespene deposits, and
  issued a successful Marine attack. The final P2 census was one
  CommandCenter, eight SCVs, one SupplyDepot, one Refinery, one Barracks, and
  three Marines.
- `simulator`: every strategy action was issued by owner P2; no SCV attack,
  friendly-fire rejection, command error, or debug injection was recorded.
  All three deterministic action traces have SHA-256
  `52d77af26c2dc89bada4a1c09660084e98a9b257030089df11be7bb7281bf65b`.
- `simulator`: the native task also exercises the corrected simulator
  semantics for neutral-resource filtering, reserved-resource affordability,
  duplicate attack suppression, and point-target `smart` normalization.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/native-task-multiseed-20260802.json`.
- `runtime`: this simulator result is not native SC2 evidence. The corrected
  P2 runtime probe remains blocked by the protected launcher lease and is kept
  separate below; no P2 runtime action is promoted from this run.

## Native Runtime Topology Probe 2026-08-02

- `runtime`: the approved launcher started a fresh isolated map on port `5200`,
  passed its ready gate, and reported no new ScriptError at startup. The P1
  anchor completed `CreateGame` and `JoinGame` as player `1`.
- `blocked`: the anchor's `GameInfo` roster contained only P1. The second
  `run_dead_of_night_live.py --join-existing --multiplayer-ports` runner got
  `Already in a game`; its observation fallback remained player `1`, so the
  fail-closed P2 ownership assertion stopped before any native action was sent.
- `blocked`: this isolates the remaining live gap to participant topology: a
  second websocket into the same single `SC2_x64` client/window does not create
  a second participant. The runtime result is not a strategy failure and is
  not promoted to native P2 evidence. The launcher and SC2 process started by
  this probe were stopped after capture.
- `blocked`: evidence is recorded at
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-native-retry-20260802/runtime-topology-verdict.json`.
- `inference`: the next runtime attempt needs two independent SC2 participant
  client processes/API endpoints, with P1 retaining CreateGame and P2 joining
  as the second participant, before native gather/train/move/attack can be
  evaluated.

## Evidence

- `static`: Stage 25 plan and write scope were reviewed before editing.
- `static`: the simulator already has reciprocal-capable `ScenarioPlayer.allies`
  and `PlayerRegistry.is_ally/is_enemy` primitives; the new contract now keeps
  P1 and P2 ownership separate and exposes P1 to P2 only through visible allies.
- `simulator`: seeds `42`, `7`, and `99` all report reciprocal roster-ready
  P1-human/P2-AI state, P2-only action entity ownership, 62 successful
  dispatches, zero friendly-fire rejections, zero hidden-state violations, and
  no deadlock/oscillation/command storm. The three trace hashes are identical.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/simulator-multiseed.json`.
- `simulator`: seed `42` cooperative replay exported `41` timeline frames,
  `5` P1 command records, `80` P2 action records, `76` successful dispatches,
  owner `2` for every P2 action, and zero friendly-fire rejections. This is a
  browser-viewable simulator artifact, not a native `.SC2Replay`.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/cooperative-ai-ally-replay-20260802/replay.jsonl`.
- `static`: the self-contained replay player was generated from those records;
  its embedded JavaScript parsed successfully. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/cooperative-ai-ally-replay-20260802/full-map-player.html`.
- `runtime`: a pre-existing protected window was observed read-only at
  `127.0.0.1:5151`: GameInfo reported P1 participant/P2 computer and raw
  observation showed four owner=2 units with alliance=2. This is context only,
  not Stage 25 acceptance evidence because no command was sent to that window.
- `blocked`: the fresh approved launcher command on port `5142` was rejected
  with `SC2_RUNTIME_BUSY` for the protected PID `37884`/port `5151`; no fresh
  ScriptError verdict was claimed. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-20260802/runtime-verdict.json`.
- `blocked`: after the first protected process exited, a second fresh launcher
  attempt was rejected by a new protected lease, PID `40408`/port `5152`.
  Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-20260802-pass1/runtime-verdict.json`.
- `historical-invalid`: the earlier approved launcher epoch on port `5152`
  reached loop `5504`, but its report joined as `observed_player_id=1` with P2
  configured as a computer. Its trace contains `attack=35` from SCVs and no
  P2-owned Barracks/Refinery/Marine proof, so it is explicitly excluded from
  Stage 25 native-strategy acceptance. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-native-task-pass6/runtime-native-strategy-pass7.json`.
- `runtime`: the current staged map was repacked with the existing StormLib
  tool and passed a fresh `CreateGame + JoinGame`; same-websocket
  `function.invoke` returned `vibe.test.ping -> pong` and
  `vibe.query.units(SCV) -> count=12`. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-native-task-pass6/debug-function-probe-pass7.txt`.
- `static`: the same probe's typed client rejected the unknown function before
  transport as `FUNCTION_NOT_FOUND`; this is registry validation evidence, not
  Galaxy-side rejection evidence.
- `runtime`: the same launcher epoch has no new non-empty ScriptError files.
  Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-native-task-pass6/script-error-verdict.json`.
- `blocked`: P1 `ActionChat(!ally ...)` messages are visible in SC2
  observations, but the fresh runtime report still has empty `bank_after` and
  `p2_command_ack_observed=false`; P2 alliance/owner observation is valid, but
  Galaxy command acknowledgement and resulting order cannot be claimed.
- `static`: the AST catalog was regenerated from the registered CMRE development
  package and owned project packages. It contains 35,404 function declarations,
  0 parser errors, 35,390 inventory-only entries, and 14 source declarations
  matched to 7 explicit callable registry IDs. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/discovery/function-catalog.json`.
- `simulator`: the Debug VM executed a hot-loaded program through the real
  `SimulatorTransport`: ping returned `pong`, the typed unit query returned one
  Marine, one scenario step reached loop 1, and catalog search returned 4
  matches. The program passed 8 instructions with 5 transport requests and did
  not restart the session. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/discovery/debug-vm-simulator-smoke.json`.
- `static`: VM malformed wire arguments are rejected before bridge dispatch;
  the REPL returns exit code 1 for a failed VM program and confines catalog
  loading to repository paths. Focused Debug VM tests report 8 passed.
- `runtime`: the first fresh KeepAlive window on port 5153 passed CreateGame,
  JoinGame, `vibe.test.ping`, and catalog search through `galaxy_repl.py` with
  VM exit code 0. Same-window ScriptError scan from launcher epoch
  `2026-08-02T15:28:11+08:00` found zero new errors. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-debug-vm-20260802/script-error-verdict.json`.
- `runtime`: a negative contract probe confirmed that a second independent REPL
  process with a random session is rejected by the Galaxy Kernel session lock;
  no game restart or process injection was attempted. The REPL now supports
  `--rpc-session-id` to resume the existing session across processes. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-debug-vm-20260802/session-isolation-rejection.json`.
- `runtime`: after resuming the original session with `--rpc-session-id`, a
  second REPL process executed the same VM on port 5153 without CreateGame or
  JoinGame. It returned `pong`, found 4 catalog entries, and exited 0. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-debug-vm-20260802/vm-resume.json`.
- `blocked`: a fresh approved launcher request on port `5161` was rejected
  before `CreateGame` by the protected global lease for PID `39308`/port
  `5153`; no P2 action was sent and no ScriptError verdict was claimed.
  Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-validation-blocked.json`.

## Verification Loop 2026-08-02 16:15

- `static`: the corrected P2 policy now pauses economy under base threat, keeps
  SCVs out of combat, assigns up to three SCVs to each completed Refinery, and
  does not reserve resources for absent Factory/Starport producers. Focused
  Stage 25 assertions pass.
- `static`: live observation preserves `build_progress`, order target tags,
  neutral geyser positions, and native Refinery target tags. Focused Stage 25
  plus live adapter tests pass with `20 passed`.
- `static`: Stage 19/20/22/23 regression passes with `25 passed, 6 subtests
  passed`; `py_compile` and `git diff --check` pass.
- `static`: `run-all-validation.ps1` passes `52/52` checks with zero warnings.
- `blocked`: an approved launcher request on port `5162` was rejected before
  `CreateGame` by the live protected KeepAlive lease on PID `34556`/port
  `5154`; no actions were sent and no ScriptError verdict was claimed.
  Evidence:
  `src/projects/cmre-porting/stages/25-ai-ally-capability-completion/runtime-p2-validation-blocked-pass2.json`.

## Verification Loop 2026-08-02 16:23

- `runtime`: the approved launcher window on port `5154` completed
  `CreateGame + JoinGame` for the packed Dead of Night map. The hot-loaded VM
  program called `vibe.unit.spawn_group` and created three real Marine units,
  then used `foreach` over the returned `unit_tags` array to call
  `vibe.unit.add_behavior` for each tag. All three calls returned
  `count=1`; the final `vibe.unit.query_behavior` returned
  `has_behavior=true` for `Conjoined`. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-debug-vm-group-20260802/vm-runtime-live.txt`.
- `runtime`: the same VM session completed 11 instructions with status
  `passed`, and the final trace contains the three real runtime tags
  `146538497`, `146800641`, and `147062785`. No game restart occurred between
  session creation and the function calls. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-debug-vm-group-20260802/vm-runtime-live.txt`.
- `runtime`: the same launcher epoch ScriptError scan found zero new errors.
  Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-debug-vm-group-20260802/script-error-verdict.json`.
- `runtime`: an initial probe using `StimpackBehavior` was rejected with
  `INVALID_ARGS` because that behavior is absent from this map's Catalog. The
  follow-up program used the map-present `Conjoined` behavior and passed; this
  confirms the runtime Catalog validation is active rather than silently
  accepting arbitrary behavior IDs. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-debug-vm-group-20260802/vm-runtime.txt`.

## Changes

- `Observation` now exposes `visible_allies` and an alliance summary filtered by
  vision and reciprocal alliance.
- `AllyPolicy` is a P2-owned state machine with P1 command authorization,
  deduplication, text notices, safety priority, and ally-safe targeting.
- `ActionAdapter` attributes every dispatch to P2 and blocks P1/ally targets.
- The live runner now sends P1 `ActionChat(!ally ...)` commands and records P2
  raw alliance, owner, position deltas, Bank acknowledgements, and chat events;
  it no longer sends P1-owned raw actions as the AI ally.
- The live runner now rejects any `GameInfo` roster where P1 or P2 is not a
  participant, before native decisions or action dispatch.
- The Galaxy kernel and its debug/map mirrors register the P1-only `!ally`
  trigger. It issues orders only to P2 units and writes status/result signals.
- Removed the stray `+` before the cooperative ally section in the project map
  Galaxy mirror before repacking the current runtime map.

## Validation

- `python -m pytest -q src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py tools/launchers/tests/test_live_runner_unit_adapter.py` -> `13 passed`.
- Stage 25 + Stage 19 + Stage 20 regression -> `15 passed, 3 subtests passed`.
- Stage 22 + Stage 23 typed combat regression -> `16 passed, 3 subtests passed`.
- `python -m pytest -q tools/launchers/tests/test_live_runner_unit_adapter.py tools/galaxy-vibe/tests/test_kernel.py tools/launchers/tests/test_launch_cmre_alenger_static.py` -> `58 passed`.
- `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> `52/52 passed, 0 warnings`.
- `python -m py_compile` over Stage 25 runtime/policy modules and focused tests -> pass.
- `git diff --check` -> pass.
- `python -m vibe.replay_player artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/cooperative-ai-ally-replay-20260802/replay.jsonl --output artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/cooperative-ai-ally-replay-20260802/full-map-player.html` -> `41` frames, loop `0 -> 40`.
- `node` embedded-script parse check over `full-map-player.html` -> pass.
- `node src/projects/cmre-porting/stages/25-ai-ally-capability-completion/discover_function_catalog.mjs ...` -> 35,404 declarations, 0 parser errors, 14 callable-adapter source declarations.
- `py -3.13 -m pytest -q src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_debug_vm.py` -> `7 passed`.
- `inline Python DebugVm bridge over SimulatorTransport` -> VM smoke PASS; 8 instructions, 5 transport requests, no session restart.
- `approved launch-cmre-alenger.ps1 -ListenPort 5153 -DebugMode -KeepAlive` + `galaxy_repl.py --map ... --vm-program ...` -> runtime VM PASS; `vibe.test.ping=pong`, catalog search count=4, exit code 0.
- `script_error_check.py --since 2026-08-02T15:28:11+08:00` -> zero new ScriptError files, exit code 0.
- `galaxy_repl.py --port 5153 --join-wait 0 --vm-program ...` with a new random session -> expected session-lock timeout; follow-up recovery uses `--rpc-session-id`.
- `galaxy_repl.py --port 5153 --join-wait 0 --rpc-session-id <existing-session> --vm-program ...` -> runtime VM PASS without CreateGame/JoinGame or game restart.
- `python tools/mpq/scripts/pack_stormlib.py ...` -> packed 76 files; the
  existing `verify_mpq.py` cannot inspect this StormLib archive because its
  reader does not support encryption, so SC2 `CreateGame + JoinGame` is the
  runtime packaging evidence.
- `approved launch-cmre-alenger.ps1 -ListenPort 5161 -DebugMode` -> blocked
  with `SC2_RUNTIME_BUSY` by the protected PID `39308`/port `5153`; exit code
  `1`, no game created.
- `approved launch-cmre-alenger.ps1 -ListenPort 5154 -DebugMode -KeepAlive` +
  `galaxy_repl.py --vm-program debug-vm-runtime-group.json` -> runtime VM
  PASS; three Marines spawned, all three received `Conjoined`, final query
  returned `has_behavior=true`, VM exit code `0`.
- `py -3.13 tools/galaxy-vibe/script_error_check.py --since
  2026-08-02T16:07:30.886+08:00 --out
  artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-debug-vm-group-20260802/script-error-verdict.json`
  -> zero new ScriptError files, exit code `0`.

## Stop Condition

Simulator, static, native-task, and typed debug-function gates are complete.
Stage 25 remains `IN_PROGRESS` with issue `RUNTIME-P2-NATIVE-VALIDATION-BLOCKED`
until a fresh approved-launcher window proves P1/P2 participant roster, P2-owned
native build/train/combat actions, no SCV attack, resulting state deltas, and a
same-window ScriptError check. The historical P1 runtime report and the
protected 5153 Debug VM window cannot satisfy this gate.

## Verification Loop 2026-08-02 Map-Derived Replay Correction

- `static`: the registered map source was inspected at
  `src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map`. `Objects` contains
  1319 ObjectUnit objects; the extractor produces 1308 supported simulator
  entities. The only P1/P2 objects are `ACHeroSpawnPlacement` markers at
  `(85,94)` and `(76,103)`. The map script defines P1/P2 as the human-side
  alliance and P3/P4/P5/P7 as hostile.
- `simulator`: the strict map-derived scenario uses `MapExtractor` output and
  adds only the P1/P2 roster/control overlay. It injects zero starting units.
  The map hash is
  `3b46e6afdfe4664e1ccc2f49c973331f66746425fa36832a00f5680c056ed322`.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-replay-20260802/map-scenario-source.json`.
- `simulator`: the generated replay contains 41 frames from loop 0 to 40,
  1308 entities in the first frame, 5 accepted P1 commands, and 0 P2 native
  actions because the source map has zero P2 units. A source-consistency check
  matched every first-frame entity by unit type, owner, source Object ID,
  source coordinate, and resource amount.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-replay-20260802/replay.jsonl`.
- `static`: the self-contained browser player includes the map source path,
  source hash, 1319/1308 native counts, exact map bounds, and P2 native spawn
  count 0. The embedded JavaScript parsed with Node `vm.Script`. Chrome
  headless loaded the file and produced a non-empty 367352-byte screenshot;
  Playwright and Puppeteer are not installed in this environment.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-replay-20260802/full-map-player.html`.
- `historical-invalid`: the previous
  `cooperative-ai-ally-replay-20260802` remains a six-unit fixture replay. It
  is not used as map evidence and is explicitly marked historical-invalid in
  `result.json`.
- `static`: Stage 25/19/20 regression passes with `22 passed, 3 subtests
  passed`; Stage 22/23 passes with `16 passed, 3 subtests passed`; launcher and
  kernel tests pass with `63 passed`; `run-all-validation.ps1` passes `52/52`
  with zero warnings; focused map replay test passes as part of Stage 25's
  `13 passed` result.
- `blocked`: strict map fidelity does not by itself create P1/P2 commander
  forces, and the fresh native P2 runtime remains blocked by the protected
  KeepAlive lease. Neither the map-derived replay nor the earlier fixture may
  be promoted to native P2 movement/combat runtime evidence.

## Verification Loop 2026-08-02 Runtime WebUI Console

- `static`: the browser runtime console is implemented in the existing CMRE
  WebUI. It exposes the explicit function catalog, typed JSON arguments,
  session connect/resume/disconnect, bounded Debug VM execution, step control,
  call trace, response payload, and error-code inspection. Changed paths:
  `tools/cmre-webui/server.py`, `tools/cmre-webui/webui/index.html`,
  `tools/cmre-webui/webui/app.js`, `tools/cmre-webui/webui/styles.css`, and
  `DESIGN.md`.
- `static`: `py -3.13 -m pytest -q
  tools/cmre-webui/test_runtime_contract.py` passes with `1 passed`. The test
  starts the real server process and verifies catalog/session/page handlers,
  plus truthful `502` responses for disconnected function and VM requests.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/webui-runtime-contract-20260802.json`.
- `static`: `py -3.13 -m py_compile tools/cmre-webui/server.py
  tools/cmre-webui/test_runtime_contract.py`, `node --check
  tools/cmre-webui/webui/app.js`, and `git diff --check` pass. Kernel/launcher
  regression passes with `63 passed`; Debug VM focused tests pass with
  `9 passed`.
- `blocked`: browser-originated live invoke was not promoted to runtime
  evidence. Port `5163` refused the connection and port `5164` disconnected
  after the SC2 API handshake, so no UI request reached `function.invoke`.
  The approved launcher Debug VM group probe remains a separate runtime PASS.

## Verification Loop 2026-08-02 Runtime WebUI VM Revalidation

- `runtime`: after explicitly releasing the stale PID 16080 window, the
  approved launcher started a fresh SC2 API window on port `5192` with PID
  `38420`. The launcher staged the current map overlay and passed its API
  ready/ScriptError gate.
- `blocked`: the first CLI attempt passed the launcher staging directory to
  `CreateGame`; SC2 truthfully rejected it because `CreateGame` requires a
  packed `.SC2Map` file. No VM instruction was sent in that attempt.
- `runtime`: the staged map was packed with the existing StormLib tool, then
  `galaxy_repl.py` completed `CreateGame + JoinGame` and ran the 11-instruction
  VM. It created three real Marines, applied `Conjoined` to each, and the
  final query returned `has_behavior=true`. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-webui-vm-20260802/runtime-vm-cli.json`.
- `runtime`: the WebUI at `http://127.0.0.1:8768` resumed session
  `repl_32f2ed98ec89` on port `5192`. Its real HTTP `function.invoke` returned
  `vibe.test.ping` with `error_code=OK` and `pong`; its real `run-vm` returned
  `status=passed`, 11 instructions, three unit tags, and final
  `has_behavior=true`. The backend trace contained 11 records. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-webui-vm-20260802/webui-api-runtime.json`.
- `runtime`: same-window ScriptError check using launcher epoch
  `1785662534` returned zero new errors. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-webui-vm-20260802/script-error-verdict.json`.

## Verification Loop 2026-08-02 Dynamic Map Replay

- `simulator`: the strict replay now carries an explicit
  `map_script_simulator_overlay`. It preserves the 1308 ObjectUnit-derived
  entities in the first frame and transcribes the registered map script's
  first-night `gf_AINormalInfestedAttacksNight1InfestedCivilians` branch,
  `Special Infested Spawn - SW` region, P5 owner, and 140-loop attack-wave
  delay. The overlay mutates no native ObjectUnit entity. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-replay-20260802/map-scenario-source.json`.
- `simulator`: the regenerated browser replay contains 65 sampled frames,
  loop `0 -> 6384`, enters Night 1, records map-script wave events at loops
  `4845` and `5741`, and adds 8 dynamic P5 entities. The first wave has zero
  units on the selected normal difficulty because that is the source script's
  normal branch; the second wave creates 8 `InfestedCivilian` source units,
  represented by the simulator's `Marine` catalog mapping. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-replay-20260802/run-summary.json`.
- `simulator`: first-frame source consistency still passes for all 1308
  entities. A cross-frame census found coordinate changes for all 8 dynamic
  entities; no P1/P2 entity appeared in the first frame, and all 5 P1 command
  records remain present. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-replay-20260802/replay.jsonl`.
- `simulator`: `scenario_step_movement_only` keeps this map-only path within
  the real simulator movement system while avoiding a full combat/economy/
  vision scan over 1308 idle native entities. Generic P1/P2 scenarios still
  use the full `scenario_step` path. The 100-loop overlay probe completed in
  1.7 seconds; the full 6400-loop replay completed in 100 seconds.
- `static`: Stage 25 focused tests pass (`13 passed`), all changed Python
  modules compile, and Chrome headless loaded the generated HTML and produced
  a non-empty `448207`-byte screenshot at
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-replay-20260802/playback-smoke.png`.
- `blocked`: an automated Chrome DevTools click probe was not promoted to
  evidence because the local command policy blocked the CDP shell command.
  Browser playback behavior is therefore supported by the replay state
  census and the existing player loop implementation, not by a claimed CDP
  click result.

## Verification Loop 2026-08-02 Playback Position Fix

- `static`: the generated player was drawing `source_x/source_y`, which are
  immutable map-source coordinates, instead of the current replay `x/y`; this
  made moving simulator entities appear static while the timeline advanced.
- `static`: `src/projects/cmre-porting/vibe/replay_player.py` now draws
  `worldToCanvas(e.x, e.y)` and keeps source coordinates only as audit data.
  The focused replay test asserts that the generated HTML contains the current
  coordinate expression and no longer contains the source-coordinate fallback.
- `simulator`: the strict map replay was regenerated after the fix with 65
  frames and loop `0 -> 6384`; its source fidelity and 8/8 dynamic position
  changes remain intact. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-replay-20260802/full-map-player.html`.
- `static`: an inline Node `vm` probe executed the generated HTML's real
  `togglePlay()`/`tick()` path, advanced the timeline `0 -> 30 -> 60`, and
  confirmed a dynamic P5 entity was drawn at current coordinates different
  from its source coordinates. This is HTML-script evidence, not native SC2
  runtime evidence. Evidence: the same `full-map-player.html`.
- `static`: Chrome headless loaded the regenerated HTML after the fix and
  produced a non-empty `362714`-byte screenshot. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-replay-20260802/playback-smoke-after-fix.png`.
- `static`: focused replay tests passed (`2 passed`), and
  `py_compile` passed for the player and Stage 25 test module.

## Verification Loop 2026-08-02 Fresh Runtime VM Rerun

- `runtime`: the previous `5201` lease was explicitly released after the
  requested restart. The approved launcher then acquired a fresh lease on
  port `5194`, started SC2 PID `35904`, reached API ready, and passed its
  launcher ScriptError gate.
- `runtime`: the current staged map overlay was packed with StormLib into
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-vm-rerun-20260802/vm-rerun.packed.SC2Map`.
  `galaxy_repl.py` completed `CreateGame + JoinGame` with `player_id=1` and
  advanced 10 seconds before dispatching VM instructions.
- `runtime`: the 11-instruction Debug VM passed in the real SC2 window. It
  created three real Marines, added `Conjoined` count `1` to all three
  runtime unit tags, and the final query returned `has_behavior=true`.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-vm-rerun-20260802/vm-runtime-live.txt`.
- `runtime`: the same launcher epoch `1785664955` ScriptError scan returned
  `has_new_errors=false`, `count=0`. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-vm-rerun-20260802/script-error-verdict.json`.
- `blocked`: this rerun validates the typed Debug VM path only. It does not
  satisfy the separate native P2 gather/train/move/attack acceptance, which
  remains blocked by the map roster and native strategy lane.

## Verification Loop 2026-08-02 Simulator Ally Economy Integration

- `static`: `AllyPolicy` now composes the project-owned `DefendBasePolicy`
  economy planner. P2 receives only `gather`, `build`, and `train` actions from
  that planner; worker/building entities are excluded from combat formation
  control, so SCVs are not sent into attacks.
- `static`: `ActionAdapter` now dispatches P2-owned `gather`, `build`, and
  `train` orders through the existing typed `SimulatorSession.unit_order`
  boundary. Replay/result records include action kind counts, event kinds,
  final P2 unit composition, and final resources.
- `simulator`: the integrated `AllyPolicy` native opening passed for seeds
  `42`, `7`, and `99`. Each run dispatched `build=3`, `gather=8`, `train=5`,
  and `attack=2`; final P2 composition was
  `CommandCenter=1, SupplyDepot=1, Barracks=1, Refinery=1, SCV=8,
  Marine=3`. All runs had zero dispatch errors, zero friendly-fire
  rejections, no deadlock, no command storm, and the same trace hash.
  Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ally-policy-native-opening-20260802.json`.
- `simulator`: visible enemy contact transitions the policy into
  `assist_attack`; combat units share a deterministic focus target and use
  formation offsets for follow/regroup movement. Stale repeated attack orders
  are suppressed before dispatch.
- `static`: focused Stage 25 tests pass with `19 passed`; Stage 19/20 pass with
  `9 passed, 3 subtests passed`; Stage 22/23 pass with `16 passed, 3 subtests
  passed`; launcher/kernel tests pass with `63 passed`; `run-all-validation.ps1`
  passes `52/52` with zero warnings; changed modules compile and `git diff
  --check` passes.
