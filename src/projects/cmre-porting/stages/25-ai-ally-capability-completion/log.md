# Stage 25 Log

## Status

In progress. The stage is active because implementation of the requested P1/P2
cooperative AI ally behavior has begun.

## Verification Loop 2026-08-02 Independent Primary/Secondary Retry

- `blocked`: the approved primary launcher attempt used API port `5620` and
  isolated map suffix `stage25-p2-retry-5620`. It exited with
  `SC2_RUNTIME_BUSY` before SC2 launch because the existing protected lease
  owns runtime PID `19648`, port `5600`, owner PID `40128`, and session
  `cmre_alenger-20260802-223507-9f170899` in `keepalive` state.
- `blocked`: because no independent P1 anchor was created, the legal secondary
  P2 join on port `5621` was not attempted. No CreateGame, JoinGame,
  participant/alliance roster, RequestStep, P2-owned action/state delta,
  native replay, or same-window ScriptError result exists for this retry.
- `blocked`: the existing PID/lease was not terminated, replaced, or reused.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-native-retry-20260802/primary-secondary-blocked.json`.

## Native P1/P2 Client Topology Repair 2026-08-02

- `static`: `run_dead_of_night_live.py` now exposes a real `--anchor` mode. It
  creates a two-participant P1/P2 game, joins P1 with explicit server/client
  ports, and sends real P1 `!ally` chat commands while the second client runs
  the P2 strategy.
- `static`: the P2 runner remains fail-closed on `player_id != 2`, joins only
  through `--join-existing --multiplayer-ports`, and now parses P1 commands
  through the project-owned `AllyPolicy`. It emits P2 acknowledgements to the
  team chat and records command, signal, and mode traces. Economy/build/train
  actions remain P2-owned `DefendBasePolicy` actions; tactical overrides are
  filtered to P2 combat units, so SCVs cannot be selected as attack issuers.
- `static`: `launch-cmre-alenger.ps1` now has an explicit
  `-SecondaryClient` mode. It uses a per-port mutex, skips the primary
  runtime/test lock and shared mod/Bank writes, does not replace the primary
  runtime lease, and still starts the second SC2 API client only through the
  approved launcher.
- `static`: the secondary launcher staging smoke passed and produced an
  isolated map copy with no primary lease replacement. Evidence:
  `src/projects/cmre-porting/stages/25-ai-ally-capability-completion/runtime-p2-native-20260802/topology-blocked.json`.
- `blocked`: a fresh primary attempt on port `5203` was rejected before
  CreateGame by the protected PID `23896` / port `5196` lease. A handshake
  against that protected port was disconnected, so it was not reused or
  terminated. The prior single-client attempt on `5201` correctly received
  `player_id=1` and failed closed before actions. Evidence:
  `src/projects/cmre-porting/stages/25-ai-ally-capability-completion/runtime-p2-native-20260802/topology-blocked.json`.
- `blocked`: no fresh P2 action, P1/P2 native roster, or same-window ScriptError
  verdict is claimed from these attempts. The next runtime command must launch
  a primary approved client and a secondary approved client on separate API
  ports, then run the P1 anchor and P2 `--join-existing` runner together.

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
  rejections, zero hidden-state violations, no deadlock, no command storm,
  and the same trace hash.
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

## Verification Loop 2026-08-02 Native P2 Topology and Replay Contract

- `static`: `run_p1_anchor` now polls authoritative `GameInfo` until the
  second participant completes `JoinGame`; a single read before P2 joins is no
  longer treated as a topology failure. The P1 and P2 clients retain distinct
  server/client port tuples and P2 remains fail-closed on `player_id != 2`.
- `static`: `-SecondaryClient` skips shared runtime listener, launch-profile,
  and CampaignXCore Bank writes while staging its isolated map copy. Launcher
  static tests and Python compilation pass.
- `static`: live runtime JSONL now exports current P1/P2/enemy/neutral entity
  coordinates, health, owner, and alive state, plus a map metadata header and
  auditable runtime summary. `--replay-log` exposes the path to the existing
  `vibe.replay_player` HTML renderer. The unit contract proves a P2 entity can
  move in the generated browser timeline; this is not native runtime evidence.
- `static`: Stage 25/19/20 regression passes with `38 passed, 3 subtests`; the
  Stage 22/23, launcher, and kernel suite passes with `82 passed, 3 subtests`;
  `run-all-validation.ps1` passes `52/52`; replay/live runner compilation and
  `git diff --check` pass.
- `blocked`: the attempted real two-client run reused pre-existing ports
  `5196` and `5210`, but both windows exited between the read-only port check
  and websocket handshake. No CreateGame, JoinGame, P2 action, or ScriptError
  claim was made. Other concurrent secondary keepalive windows were left
  untouched. Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-native-pass8-20260802/topology-handshake-blocked.json`.

## Verification Loop 2026-08-02 Failure-First and Port-Owner Repair

- `static`: the requested failure-first cross-stage regression initially
  exposed one determinism failure: `111 passed, 6 subtests passed, 1 failed`;
  seed `42` observed `move=54, attack=1` instead of the expected `attack=2`.
  The isolated test and the full regression rerun both passed, so no assertion
  was weakened and the transient failure is retained as a test-order/flakiness
  signal for follow-up.
- `static`: after the launcher port-owner repair, the Stage 25 focused plus
  Stage 19/20/22/23/kernel/launcher regression passed with `112 passed, 6
  subtests passed`; launcher/kernel subset passed with `58 passed`.
- `static`: PowerShell parser validation passed, `run-all-validation.ps1`
  passed `52/52`, and the Stage 25 runtime/policy modules compiled.
- `runtime`: the approved secondary-client launcher probe on port `5220`
  staged the map and started SC2 through the launcher, but the API port did not
  listen within 120 seconds and the launcher exited nonzero. No runtime
  listener, heartbeat, or native P2 action is claimed from this probe.
  Port `5215` was rejected before launch because it was already occupied.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-secondary-port-owner-fix-20260802/launcher-output.txt`.

## Verification Loop 2026-08-02 Follow-up Failure and Formation Boundary Fix

- `static`: the next full regression first failed in
  `test_p2_receives_commands_and_transitions_across_cooperative_modes` with
  `total_dispatched=0`. Isolated reproduction showed that the policy emitted
  formation targets `(-1,-1)` and `(1,-1)` for a leader at `(0,0)`; the typed
  simulator transport correctly rejected those targets as `invalid_target`.
- `static`: the existing `AllyPolicy._formation_destination` boundary repair
  now clamps formation coordinates to the non-negative SC2 playable space.
  The isolated failure test passed after the repair, with no assertion change.
- `static`: the complete Stage 25/19/20/22/23, kernel, launcher, and live
  runner regression passed with `120 passed, 6 subtests passed`; PowerShell
  parser validation passed and `run-all-validation.ps1` passed `52/52` with
  zero warnings. Runtime native P2 validation remains separately blocked by
  the protected lease and is not promoted by this static pass.

## Verification Loop 2026-08-02 Fresh Native P2 Launcher Crash

- `blocked`: a fresh approved launcher attempt used API port `5230` and an
  isolated map copy. Staging completed, but `SC2_x64` crashed before the API
  port listened, so no CreateGame, JoinGame, participant roster, P2 action, or
  replay claim was made.
- `runtime`: the same-window GameLog `NGDP.txt` reported
  `e_fileCorruptRepairable (NGDP:E_REPAIR)` and
  `repair marker detected in SC2Data (EEV_REPAIR_CONTAINER)`. The installation
  contains `SC2Data/CASCRepair.mrk`; this is an installation-level blocker,
  separate from the P2 topology contract.
- `simulator`: the fresh local regression remains green (`37 passed`), with
  Python compilation, `git diff --check`, and Stage 25 JSON parsing passing.
- `blocked`: native P2 acceptance remains open. The launcher/GameLog evidence
  is retained at
  `src/projects/cmre-porting/stages/25-ai-ally-capability-completion/runtime-p2-native-next-20260802/launch-crash-blocked.json`.

## Verification Loop 2026-08-02 High-Tech Simulator Ally Progress

- `static`: the typed `ActionAdapter` now checks the simulator's
  `CommandResult` after attack, move, gather, build, train, and research
  dispatch. A command is not counted as successful merely because
  `unit_order()` returned without raising.
- `static`: the cooperative formation target is clamped to the simulator's
  non-negative playable boundary, and `run_ally_scenario()` clamps its loop
  budget to the scenario's authoritative `max_loops` so an oversized caller
  budget cannot spin after the simulator stops advancing.
- `static`: the Terran build plan now places Factory/EngineeringBay outside
  the Refinery resource reservation area and uses the valid FactoryTechLab
  socket. `build_native_task_scenario()` accepts an explicit loop budget.
- `simulator`: high-resource native P2 runs for seeds `42`, `7`, and `99` all
  passed at loop `500` with `build=8`, `gather=13`, `train=10`, `research=2`,
  and `attack=3`. Each run completed `Factory`, `EngineeringBay`, `Starport`,
  `Armory`, and `FactoryTechLab`, trained `SiegeTank` and `Medivac`, completed
  `TerranInfantryWeaponsLevel1` and `TerranVehicleWeaponsLevel1`, gathered
  both resource types, and reported zero command errors, friendly-fire
  rejections, hidden-state violations, deadlock, or command storm.
  Evidence:
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ally-policy-high-tech-20260802.json`.
- `static`: focused Stage 25 tests pass with `20 passed`; the Stage 25/19/20
  regression passes with `29 passed, 3 subtests passed`; Stage 22/23 passes
  with `16 passed, 3 subtests passed`; launcher/kernel passes with `66 passed`;
  `run-all-validation.ps1` passes `52/52` with zero warnings; changed Python
  modules compile and `git diff --check` passes.
- `blocked`: this is simulator evidence only. Corrected native P2 SC2
  gather/train/move/attack runtime validation remains blocked by the existing
  protected/concurrent launcher and map roster constraints.

## Verification Loop 2026-08-02 Runtime Repair Blocker Recorded

- `blocked`: the approved launcher attempt on API port `5221` completed map
  staging but `SC2_x64` crashed before API listen. The same-window GameLog
  reported `e_fileCorruptRepairable (NGDP:E_REPAIR)` and
  `EEV_REPAIR_CONTAINER` for `SC2Data`, with `SC2Data/CASCRepair.mrk` present.
- `blocked`: because the API never became ready, no CreateGame, JoinGame,
  participant roster, P2 action, native replay, or same-window ScriptError
  verdict is claimed. P2 remains fail-closed and no strategy action was sent.
- `static`: the blocker is recorded separately from the prior topology and
  protected-lease attempts so later recovery can replace only this blocked
  evidence. Evidence:
  `src/projects/cmre-porting/stages/25-ai-ally-capability-completion/runtime-repair-blocked.json`.
- `next`: after the local SC2 installation is repaired outside this repository,
  rerun the approved primary/secondary client flow, verify `player_id=2`, then
  require native SupplyDepot/Refinery/Barracks/Marine transitions, Marine-only
  attack issuers, and a same-window ScriptError verdict before changing stage
  status.

## Verification Loop 2026-08-02 Post-Reinstall Ability VM Runtime

- `runtime`: the approved `launch-cmre-alenger.ps1` launcher started a fresh
  single-client window on port `5310` with isolated map copy
  `stage25-vm-ability-5310`; the staged map was repacked with StormLib into
  `ability-reinstall.packed.SC2Map`.
- `runtime`: `galaxy_repl.py --map ability-reinstall.packed.SC2Map
  --vm-program debug-vm-runtime-ability.json` completed CreateGame and
  JoinGame as `player_id=1`, then executed 15 VM instructions. Three real
  Marines were created; each received `Stimpack`, and each independent
  `vibe.unit.query_ability` returned `has_ability=true`. Exit code was `0`.
- `runtime`: the same launch window ScriptError scan returned
  `has_new_errors=false`, `count=0`.
- `blocked`: the previous SC2Data repair-marker blocker no longer prevents
  this single-client runtime. Corrected two-client native P2 acceptance remains
  separate and still requires participant-owned `player_id=2` evidence.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-vm-ability-reinstall-20260802/vm-runtime-live.txt`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-vm-ability-reinstall-20260802/script-error-verdict.json`.

- `static`: normalized Ability handler blocks in the kernel, debug-mod, and
  Dead of Night map mirrors are identical (SHA-256
  `F41AAF6EDB82EC507FFDB5FA1B1DEA80A0035E8FD61C1FAF9F70F349F7EC8AF3`), and
  all three headers declare `FunctionUnitAddAbility` and
  `FunctionUnitQueryAbility`.

## Verification Loop 2026-08-02 Tactical Recovery Simulator

- `simulator`: `build_native_recovery_scenario()` was run through the full
  `AllyPolicy` and `ActionAdapter` loop for seeds `42`, `7`, and `99` at loop
  `640`. All three runs passed with the same trace hash
  `39be69a419873b78f7a36d41b187d893f1a6799288c7ceb3f17a6d8b00eb7d5c`.
- `simulator`: the recovery overlay issued only eight attack orders from four
  pre-existing enemy Roaches in two waves. It did not spawn, kill, or mutate
  P2 units/resources (`p2_injection=false`). P2 suffered two Marine losses,
  then completed eight real Barracks train transitions after the first loss.
- `simulator`: P2 issued nine typed `Heal` actions and produced 26 heal events;
  Medivac never attacked, SCV never attacked, friendly-fire rejections and
  hidden-state violations were zero, and no command errors, deadlock, or
  command storm occurred.
- `simulator`: the strategy action stream contains only gather/build/train/
  research/move/attack/heal. No `unit.spawn`, `player.set_resource`, or
  `unit.kill` operation appears in any seed. The complete evidence and replay
  paths are recorded at
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ally-policy-recovery-20260802.json`.
- `static`: Stage 25 focused tests pass with `21 passed`; this recovery result
  remains simulator-only and does not change the open native P2 topology/map
  roster blocker.

## Verification Loop 2026-08-02 Ladder-Style Full-Game Simulator

- `simulator`: `PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.ladder_ai
  --batch --max-loops 5000 --out
  artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ladder-full-game-20260802.json`
  completed the same full-game loop for seeds `42`, `7`, and `99` with overall
  status `PASS`.
- `simulator`: every seed reached loop `3296` with end reason
  `enemy_elimination`, winner P1, and `final_enemy_units_by_type={}`. The
  policy recorded mineral and vespene deposits, expansion to two Command
  Centers, two Barracks, two Factories, FactoryTechLab, Armory, Starport,
  EngineeringBay, both Terran weapon upgrades, and Marine/Hellion/Medivac
  production.
- `simulator`: the same runs recorded scout-route movement, a ladder pressure
  wave, low-health retreat, focus-fire cleanup, `457` attack actions, zero
  dispatch errors, zero hidden-state violations, no deadlock, and no command
  storm. The artifact explicitly declares `evidence_type=simulator` and
  `runtime_claim=none; simulator evidence only`.
- `simulator`: the initial scenario resource budget is intentionally documented
  as `2600 minerals / 800 vespene` so the deterministic simulator's 60-loop
  gather cadence can cover a complete technology tree within the bounded test
  budget. This validates the AI control loop, not ladder balance or native SC2
  economy timing.
- `blocked`: this full-game result does not close the separate native SC2 P2
  participant-topology gate. No simulator result is promoted to runtime
  evidence.

Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ladder-full-game-20260802.json`.

## Verification Loop 2026-08-02 Ladder Replay Tool

- `simulator`: `vibe.ladder_ai` now enables replay output by default. A run
  writes `replay.jsonl` and the self-contained
  `state-driven-player.html` under
  `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ladder-full-game-replay/seed-<seed>/`.
  Batch mode creates one directory per seed; `--no-replay` is an explicit
  opt-out for callers that only need the JSON report.
- `simulator`: the generated replay contains real full-simulation frame state,
  P1/P2/enemy entity ownership, resource snapshots, action dispatch records,
  pressure-wave events, and the `enemy_elimination` terminal frame. The player
  title identifies it as `CMRE 梯队 AI 完整局回放` and remains marked
  `runtime_claim=none; simulator evidence only`.
- `static`: the replay export test passed with a non-empty frame timeline and
  generated HTML containing the simulator-only evidence marker.

Evidence path produced by the default CLI:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ladder-full-game-replay/seed-42/state-driven-player.html`.

## Verification Loop 2026-08-02 Dual-Client P2 Participant Topology

- `runtime`: two fresh SC2 processes launched through the approved launcher
  listened independently on API ports `5450` and `5451`. Both clients passed
  `Ping`; the P1 anchor completed `CreateGame`.
- `runtime`: the P1/P2 clients submitted the same reference-shaped 1v1
  `Portconfig`: server ports `5500/5501` and one guest client pair
  `5502/5503`.
- `blocked`: P1 `JoinGame` did not return during the 180-second handshake
  window, and P2 `JoinGame` likewise did not return a participant response or
  `player_id=2`. `GameInfo` therefore never proved a P1/P2 participant roster;
  no native P2 action was sent and no same-window ScriptError PASS was claimed.
- `blocked`: the preceding minimal topology run proved that P2 without
  `server_ports/client_ports` is rejected by SC2 as `Must first start a game
  with CreateGame or specify ports to join another client's game`. This is
  protocol evidence, not a native strategy result.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-topology-pass12-20260802/topology-handshake-blocked.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-topology-pass12-20260802/p1-anchor-5450-ports.stdout.txt`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-topology-pass12-20260802/p2-runner-5451-ports.stdout.txt`.

## Verification Loop 2026-08-02 Dual-Client Topology Follow-up

- `static`: `run_dead_of_night_live.py` now matches the reference participant
  setup more closely: `CreateGame` uses two unqualified Participant entries,
  both JoinGame requests omit `host_ip`, and the existing shared
  `server=[base,base+1]` / `client=[[base+2,base+3]]` Portconfig is retained.
- `static`: the approved launcher now gives each API client a distinct
  `-tempDir` and explicit `-dataDir`; launcher output and SC2 command lines
  confirm the values for the tested primary/secondary windows.
- `runtime`: four fresh approved-launcher A/B windows reached independent API
  ready and P1 `CreateGame` success. The no-`host_ip`, isolated-temp, and
  isolated-data/temp variants all left both JoinGame requests pending. The
  `realtime=True` variant closed P1's websocket during JoinGame and left P2
  pending.
- `blocked`: no tested window returned `player_id=2`, no P1/P2 participant
  roster appeared in GameInfo, and no P2 native action or native replay was
  produced. Simulator replay artifacts remain simulator-only.
- `static`: focused Stage 25, launcher, and live-runner validation passed with
  `38 passed`; `run-all-validation.ps1` passed `52/52` with zero warnings.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-topology-followup-20260802/topology-handshake-blocked.json`.

## Verification Loop 2026-08-02 Ladder Same-Batch Budget Repair

- `simulator`: the failure-first ladder run reached
  `enemy_elimination`, but one `SupplyDepot` order was rejected with
  `sim_error:insufficient_minerals` because the ladder macro layer did not
  account for a same-batch 100-mineral Hellion order. The rejection was
  observed at loop `2857` for `ladder_SupplyDepot5`; the victory result was
  therefore not accepted as clean.
- `static`: `LadderAI._action_cost()` now uses the existing
  `DefendBasePolicy` cost tables to subtract same-batch train/build/research
  commitments before adding expansion, production, or supply orders. This
  keeps the real simulator budget check authoritative and avoids suppressing
  dispatch errors.
- `simulator`: the focused ladder suite passed with `4 passed`; complete
  victory and deterministic seed checks now report an empty error breakdown.
- `static`: the combined Stage 25 AI ally, ladder, and Debug VM suites passed
  with `38 passed`.
- `static`: the cross-stage regression collection passed with `130 passed` and
  `6 subtests passed`, covering Stage 19/20/22/23, Stage 25, Debug VM, Galaxy
  kernel, launcher, and live-runner adapter tests.
- `static`: `run-all-validation.ps1` passed `52/52` checks with zero warnings
  after the ladder budget fix.
- `simulator`: the post-fix CMRE matrix passed `15/15` maps at seed `42` and
  `max_loops=320`. Every map reached `TACTICAL_PASS`; each run reported zero
  dispatch errors, deadlock, command storm, friendly-fire, and hidden-state
  violations. The matrix is simulator-only and does not claim native mission
  completion.
- `simulator`: the final direct ladder batch report passed for seeds `42`, `7`,
  and `99`. Every run reached `enemy_elimination` with `victory=true`, empty
  `final_enemy_units_by_type`, empty `error_breakdown`, and all macro/tactical
  safety checks true. This report supersedes the retained failure-first debug
  artifact; both remain clearly labeled by purpose.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/cmre-map-matrix-20260802-rerun/matrix-summary.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ladder-budget-fixed-20260802.json`,
`src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ladder_ai.py`,
`src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py`.

- `blocked`: corrected native P2 gather/train/move/attack validation remains
  open because the approved dual-client SC2 JoinGame path still does not
  expose a participant-owned `player_id=2`; simulator passes do not close
  this runtime gate.

## Verification Loop 2026-08-02 Debug VM Capability Pass

- `runtime` `WARN`: an initial fresh launcher window on API port `5630` was
  reachable, but the VM was started with `--join-wait 0` and no `--map`. The
  first `vibe.catalog.set` call timed out before map initialization; this is
  retained as a startup-order diagnostic, not as a capability result.
- `runtime`: the approved launcher was restarted on port `5640`, the staged map
  was packed with the existing `pack_stormlib.py`, and `galaxy_repl.py` ran
  `CreateGame/JoinGame player_id=1` with `--map` and `--join-wait 15` in the
  same process. The hot-loaded `debug-vm-runtime-capability.json` completed
  `47/47` instructions with `status=passed`, without a second game restart.
- `runtime`: the VM created a real Marine and Medivac, added the non-native
  `MedivacHeal` ability to the Marine and read back `has_ability=true`, wrote
  and read Medivac energy, lowered and read Marine life, and changed Marine
  `LifeMax` to `60.5` and `Speed` to `4.5` through Catalog writes.
- `runtime`: the VM changed Marine mineral/gas cost fields to `25/10` and
  changed the loaded `BarracksTrainNova.InfoArray[0].Unit` reference from
  `Marine_BlackOpsSpawnerUnit` to `Marauder`; both values were read back from
  the live Catalog. The tested visual handlers returned `applied=true` for
  model variation, scale `1.5`, tint, and opacity `0.5`, but no screenshot or
  pixel-level visual assertion was made.
- `runtime`: the same 5640 launcher epoch ScriptError scan returned
  `has_new_errors=false`, `count=0`, and no files.
- `static`: `test_debug_vm.py` passed `12` tests, `test_kernel.py` passed `49`
  tests, and `run-all-validation.ps1` passed `52/52` checks with zero warnings.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-vm-capability-5640-20260802/vm-runtime-live.txt`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-vm-capability-5640-20260802/script-error-verdict.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-vm-capability-5640-20260802/vm-capability-5640.packed.SC2Map`,
`src/projects/cmre-porting/stages/25-ai-ally-capability-completion/debug-vm-runtime-capability.json`.

- `blocked`: this Debug VM pass is debug-mode injection evidence and does not
  close the separate native P2 participant/topology gate. Visual presentation
  remains open until a runtime screenshot or equivalent pixel assertion is
  captured.
- `runtime` `BLOCKED`: `VisualCapture` captured the 5640 SC2 window at
  `2560x1440`, but the image had `0` non-black and `0` non-transparent pixels;
  `ApiMinimal` therefore provided no usable visual frame. This confirms the
  screenshot path and preserves the artifact, but does not validate the visual
  mutation on screen.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-vm-capability-5640-20260802/screenshots/visual-capability-final-20260802-230749-5640.png`.

## Verification Loop 2026-08-03 CMRE Full-Game Simulator Matrix

- `simulator`: the final command
  `PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.run_cmre_map_matrix
  --seed 42 --max-loops 2000 --max-enemy-per-player 1
  --output-dir artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/cmre-map-matrix-20260803-final`
  returned `status=PASS` with `map_count=15` and `inventory_map_count=15`.
- `simulator`: all 15 maps reached `enemy_elimination` with `victory=true` and
  empty `enemy_units_remaining`. Every run reported zero dispatch errors,
  deadlock, command storm, friendly-fire rejection, and hidden-state violation.
- `simulator`: every map directory contains `replay.jsonl`,
  `state-driven-player.html`, and `run-summary.json`; the final artifact census
  found `15` directories and `0` invalid runs.
- `static`: the final targeted suites passed with `22` AI ally tests and `4`
  ladder tests. The bounded tactical matrix test now explicitly passes
  `full_game=false`; the CLI default remains full-game mode.
- `static`: `往日神庙` no longer reports stale focus-target errors after the
  single-focus attack change. `黑暗杀星` no longer stages sampled enemies
  outside map bounds; delayed focus commands that target an already-cleared
  observed enemy are recorded as `superseded`, not as simulator errors.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/cmre-map-matrix-20260803-final/matrix-summary.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/cmre-map-matrix-20260803-final/黑暗杀星/run-summary.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/cmre-map-matrix-20260803-final/往日神庙/run-summary.json`,
`src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py`,
`src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ladder_ai.py`.

The matrix is explicitly `simulator` evidence. Native SC2 P2 participant
topology and native mission completion remain separate blocked runtime issues.

## Verification Loop 2026-08-03 Native P2 Computer Glue Follow-up

- `static`: `tools/launchers/lib/cmre-on-demand-overlay.ps1` now selects the
  Dead of Night fragment from the ASCII `gv_day_Duration_First` MapScript
  signature instead of comparing the Chinese filename after PowerShell code
  page conversion. The launcher regression test asserts this selector and the
  native P2 glue contract.
- `static`: focused Stage 25, ladder, launcher, and live-runner tests passed:
  `46 passed`. `run-all-validation.ps1` passed `52/52` with zero warnings.
- `simulator`: the follow-up ladder batch for seeds `42`, `7`, and `99`
  reached `enemy_elimination` with victory, full economy/tech/tactical checks,
  zero dispatch errors, and simulator-only replay output.
- `static`: approved secondary staging generated
  `stage25-p2-computer-v8`; its `MapScript.galaxy` contains
  `gt_CmreOnDemandComputerAllyReady`, `MeleeInitUnitsForPlayer(2, ...)`,
  `MeleeInitResourcesForPlayer(2, ...)`, and `AIMeleeStart(2)`. StormLib
  packed the 79-file map into the v8 stage artifact.
- `runtime`: an approved direct-map launcher loaded the current map and
  reported `runtime_listener_ready`; the same launcher epoch reported no new
  non-empty `*ScriptError*.txt` files. This window had no API and produced no
  P2 Bank/replay evidence, so it is not native strategy acceptance.
- `blocked`: the direct-map launcher remains `-KeepAlive` with runtime PID
  `16276`, launcher PID `32640`, and the protected main lease. A new single
  client API runner cannot start until that owner releases the lease. No
  process was terminated and no existing runtime was overwritten.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-20260803-v8/stage25-p2-computer-v8.packed.SC2Map`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-direct-map-input-20260803/launcher.stdout.txt`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ladder-full-game-20260803-followup.json`,
`artifacts/galaxy-vibe/static-validation-report.json`.

## Verification Loop 2026-08-03 Native Ally Command Recovery

- `static`: the Dead of Night map-owned adapter now contains an explicit
  `!ally` fallback. It accepts only P1 chat, reads only P2-owned units and
  enemy-alliance targets, and records command/result/order evidence under
  `CMRERebornDebug.debug` with `ally_` keys. The typed `GalaxyVibe` kernel
  path remains unchanged.
- `static`: PowerShell parser validation passed; launcher static tests passed
  with `11 passed`; kernel regression passed with `49 passed`.
- `runtime` `BLOCKED`: approved DirectMap+API r6 reproduced the SC2Switcher
  bootstrap crash with `ACCESS_VIOLATION (0xC0000005)` before API listen.
  No CreateGame, JoinGame, P2 roster, replay, or strategy claim is made.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-direct-map-input-20260803-r6/runtime-verdict.json`.
- `runtime` `BLOCKED`: approved DirectMap r9 reached runtime listener,
  initialization complete, P1/P2 readiness markers, and same-window zero new
  ScriptErrors. The map reported `ally_p2_player_type=0` and
  `ally_not_ready_reason=p2_not_computer`; the non-API map had no lobby P2
  Computer roster. An ASCII clipboard `!ally status` input produced no Chat
  event or fallback command key. This is runtime blocked evidence, not native
  P2 acceptance.
  Evidence: `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-direct-map-input-20260803-r9/runtime-verdict.json`.
- `blocked`: the required native topology still needs a working approved API
  launch that supplies P1 Participant plus P2 Computer. DirectMap API is
  blocked by the SC2 crash; DirectMap without API exposes P2 as type `0` and
  does not deliver ChatMessage events.

## Verification Loop 2026-08-03 Native P2 Computer Runtime PASS

- `static`: the approved launcher completed `stage25-p2-computer-v11` staging,
  and StormLib packed the staged map into a 79-file
  `stage25-p2-computer-v11.packed.SC2Map`.
- `runtime`: one approved ApiMinimal launcher on port `5730` completed
  `CreateGame` and `JoinGame` with observed player `1`. `GameInfo` proved P1
  `Participant` and P2 `Computer`, Terran, difficulty `2`; the old two-client
  Participant topology was not used.
- `runtime`: after RequestStep-driven initialization, the native markers
  reached `initialization_complete=1`,
  `initialization_units_ready_p1=1`, `initialization_units_ready_p2=1`,
  `ally_not_ready_reason=none`, `ally_p2_native_ai_path=1`,
  `ally_computer_ally_ready=1`, and `ally_p2_unit_count=14`. P2 was observed
  through owner `2` units with alliance value `2`.
- `runtime`: P1 sent `!ally status`, `!ally defend`, and `!ally attack`.
  All three chat actions were accepted; P2 Bank acknowledgements completed
  with final `last_result=attack_issued`; P2-owned state changed across the
  command trace; and the native Computer-ally strategy audit passed with no
  debug injection or raw P2 API action.
- `static`: the map-owned fallback contains the P2 response path using
  `UIDisplayMessage` plus Bank debug acknowledgement. SC2 Observation does
  not echo `UIDisplayMessage` as a ChatMessage, so `p2_signal_trace` is empty
  in this API report; the player-visible signal is retained as a Galaxy/static
  contract and the Bank acknowledgement is the runtime-observed response.
- `runtime`: the runner emitted a real native `native-live-replay.SC2Replay`,
  a 1200-loop `native-live-replay.jsonl`, and a self-contained dynamic
  `full-map-player.html` with timeline and Canvas playback code.
- `runtime`: `script_error_check.py --since 1785726362` returned
  `has_new_errors=false`, `count=0`, and no new non-empty ScriptError files in
  the same launcher epoch.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-20260803-v11/runtime-report.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-20260803-v11/native-live-replay.SC2Replay`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-20260803-v11/full-map-player.html`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-20260803-v11/script-error-verdict.json`.

## Verification Loop 2026-08-03 Native Ally Signal Runtime Recheck

- `runtime` `WARN` (not promoted): v12 passed the native Computer-ally core
  path, but `p2_signal_observed=false` because the runner's Bank bridge invokes
  `LibVibeKernel.galaxy`, while the first signal marker was added only to the
  map chat fallback. No core behavior claim was changed by this intermediate
  result.
- `static`: `libVibeKernel_gf_EchoAlly` was added to both the registered kernel
  and the active Dead of Night map mirror. It preserves the existing
  `UIDisplayMessage` output and records `ally.last_signal` plus an incrementing
  `ally.signal_count`; the runner accepts only a per-run count increase.
  Targeted runner/launcher regression passed `20` tests.
- `runtime`: v13 on approved API port `5750` completed the single-client
  Computer-ally path. Roster values were P1 `type=1`, P2 `type=2`, Terran,
  difficulty `2`; initialization reached `initialization_complete=1`,
  `initialization_units_ready_p1/p2=1`, `ally_not_ready_reason=none`, and
  `ally_p2_unit_count=14`.
- `runtime`: P1 issued `!ally status`, `!ally defend`, and `!ally attack`.
  All three were accepted; the final Bank contained
  `command_count=3`, `signal_count=3`, `last_result=attack_issued`, and
  `last_signal="[Ally P2] Acknowledged: attack. P2 units engaging hostile target."`.
  The report set `p2_signal_observed=true`, `p2_command_ack_observed=true`,
  `p2_visible_as_p1_ally=true`, and native strategy audit `PASS` with no debug
  injection.
- `runtime`: v13 emitted a non-empty native `.SC2Replay`, a 1200-loop JSONL
  replay, and a dynamic `full-map-player.html` containing timeline,
  requestAnimationFrame, Canvas, and playback controls.
- `runtime`: `script_error_check.py --since 1785727614` returned
  `has_new_errors=false`, `count=0`, and no new non-empty ScriptError files in
  the same launcher epoch.
- `static`: the final focused regression collection passed `107` tests;
  `run-all-validation.ps1` passed `52/52` checks with zero warnings; and
  `py_compile` plus `git diff --check` passed after the signal change.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-20260803-v13/runtime-report.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-20260803-v13/native-live-replay.SC2Replay`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-20260803-v13/full-map-player.html`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-20260803-v13/script-error-verdict.json`.

## Verification Loop 2026-08-03 Generic Map Computer-Ally Reuse

- `simulator`: `vibe.run_cmre_map_matrix --map 克哈裂痕 --seed 42 --max-loops 6000 --max-enemy-per-player 1` passed. The map-derived scenario resolved source hash `9b0e34294ed501820901b17cee8018b9118f60770fd841406233e1077a4a38de`, map-derived leader/base/expansion/objective geometry, and reached `enemy_elimination` with zero simulator errors.
- `static`: generic map glue now contains the same P1/P2 Computer contract as the Dead of Night fragment: P2 start-point lookup, `MeleeInitUnitsForPlayer(2, ...)`, `MeleeInitResourcesForPlayer(2, ...)`, `AIMeleeStart(2)`, reciprocal alliance setup, and P1-only `!ally` status/follow/defend/attack/regroup/retreat handling. Maps without a local kernel mirror fall back to the registered `tools/galaxy-vibe/kernel` files.
- `static`: candidate staging through `tools/launchers/launch-cmre-alenger.ps1 -MapName 克哈裂痕.SC2Map -Commander Empire -ApiMinimal -DebugMode -NoLaunch` passed; StormLib packed the staged 86-file map into the candidate artifact.
- `runtime`: the approved ApiMinimal single-client window on port `5760` completed CreateGame/JoinGame with P1 `Participant` and P2 `Computer` on `[CM] 克哈裂痕`. Native P2 initialization exposed 14 owned units, P2 was visible to P1 with alliance value `2`, and P1 `!ally status`, `!ally defend`, and `!ally attack` all completed with P2 Bank acknowledgements, P2 position deltas, and the P2-to-P1 signal marker.
- `runtime`: the corrected candidate replay header resolves `克哈裂痕` through `cmre_map_catalog`, records native object count `1621`, native spawn count `1461`, source-map resolution `true`, and topology `single_client_p1_participant_p2_computer`; it no longer reuses Dead of Night metadata. The run emitted a non-empty native `.SC2Replay`, a 1200-loop JSONL timeline, and a dynamic Canvas `full-map-player.html` titled `克哈裂痕`.
- `runtime`: `script_error_check.py --since 1785729563` returned `has_new_errors=false`, `count=0`, and no new non-empty ScriptError files in the same launcher window. The runtime report recorded `p1_p2_computer_roster`, `p2_visible_as_p1_ally`, `p2_signal_observed`, `native_strategy_state_delta`, and `native_strategy_no_debug_injection` as true, with zero command failures.
- `static`: focused launcher/live-runner regression passed `21` tests; runner `py_compile` and `git diff --check` passed. The existing `run-all-validation.ps1` result remains `52/52` with zero warnings.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-kh-rift-20260803/matrix-summary.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-keha-20260803-v1/stage25-p2-computer-keha-v1.packed.SC2Map`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-keha-20260803-v1/runtime-report-map-catalog.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-keha-20260803-v1/native-live-replay-map-catalog.SC2Replay`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-keha-20260803-v1/native-live-replay-map-catalog.jsonl`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-keha-20260803-v1/full-map-player.html`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-keha-20260803-v1/script-error-verdict-map-catalog.json`.

- `static` final post-change regression: Stage 19/20/22/23/25 plus kernel and launcher/live-runner suites passed `133` tests with `6` subtests; `run-all-validation.ps1` passed `52/52` with zero warnings. The candidate SC2 process and port `5760` were then closed and no runtime lease remained.

## Verification Loop 2026-08-03 Source Minimap Projection Follow-up

- `static`: `replay_player.py` now emits a projection report for every map-backed
  HTML replay. It records the source map, Minimap dimensions, non-black content
  rectangle, world bounds, projected ObjectUnit count, out-of-rectangle count,
  and representative resource/structure/start samples. The report is embedded
  in `PROJECTION_REPORT` and shown as a PASS/WARN status in the player.
- `static`: the static source layer now renders resources as marked squares and
  structure-like ObjectUnits as footprint anchor boxes, while mobile/static
  units remain owner-colored points. Existing dynamic entities still use their
  current `x/y`; `source_x/source_y` are not used for playback positions.
- `simulator`: a fresh map-derived 亡者之夜 run reached `enemy_elimination`
  with zero simulator errors and emitted a JSONL timeline plus a self-contained
  `state-driven-player.html`. Its source projection covers `1319/1319`
  ObjectUnits, uses a `256x256` Minimap with content rectangle `[48,48,160,160]`,
  and resolves the map hash from the source package.
- `simulator`: the existing strict 克哈裂痕 native replay HTML was regenerated
  with the new renderer. It keeps the native runtime JSONL and `.SC2Replay`
  unchanged while adding projection calibration and static anchor rendering.
- `runtime`/`browser`: Chrome headless loaded both map HTML files with the
  embedded minimaps ready, Canvas non-empty, zero page errors, and playback
  advancement. 克哈裂痕 advanced loop `105 -> 157`; 亡者之夜 advanced
  loop `0 -> 1`. These are browser/static replay checks, not native SC2 render
  equivalence.
- `static`: focused map projection tests passed `2`; the complete Stage
  19/20/22/23/25 + Debug VM + Ladder + kernel + launcher/live-runner suite
  passed `135` tests with `6` subtests; `run-all-validation.ps1` passed
  `52/52` with zero warnings.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-20260803-v2/亡者之夜/replay.jsonl`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-20260803-v2/亡者之夜/state-driven-player.html`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-20260803-v2/亡者之夜/browser-projection-smoke.png`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-keha-20260803-v1/full-map-player.html`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/runtime-p2-computer-keha-20260803-v1/browser-projection-smoke.png`,
`src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py`.

## Verification Loop 2026-08-03 Catalog Visuals and Fresh Browser Replay Checks

- `simulator`: fresh strict map-derived 克哈裂痕 output is PASS with source map
  hash/geometry resolved from `src/projects/cmre-porting/packages/Maps/克哈裂痕.SC2Map`;
  the replay contains 1621 map ObjectUnits and its HTML is
  `map-derived-keha-20260803-v2/克哈裂痕/state-driven-player.html`.
- `simulator`: fresh strict map-derived 亡者之夜 output is PASS with
  `enemy_elimination`, zero simulator errors, and 1319 source ObjectUnits;
  the HTML is `map-derived-dead-of-night-20260803-v3/full-map-player.html`.
- `browser`: Chrome headless loaded both fresh HTML files from `file:///` with
  `mapImageReady=true`, non-empty Canvas pixels, zero page/console/request
  errors, and automatic `togglePlay()` advanced both timelines `0 -> 6`;
  `stepFrame(1)` then advanced them `6 -> 7`. The projection report is PASS
  for 1621/1621 克哈裂痕 objects and 1319/1319 亡者之夜 objects. The
  embedded Catalog report is PASS with exact source footprints and truthful
  unavailable-icon fallbacks.
- `static`: Stage 25 focused tests passed `26`; the Stage 19/20/25 combined
  regression passed `35` tests with `3` subtests; the changed modules compile,
  `git diff --check` is clean, and `run-all-validation.ps1` passed `52/52`
  with zero warnings.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-keha-20260803-v2/克哈裂痕/replay.jsonl`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-keha-20260803-v2/克哈裂痕/state-driven-player.html`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-20260803-v3/replay.jsonl`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-20260803-v3/full-map-player.html`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/browser-projection-smoke-20260803-v2.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/browser-projection-keha-20260803-v2.png`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/browser-projection-dead-of-night-20260803-v3.png`,
`artifacts/galaxy-vibe/static-validation-report.json`.

## Verification Loop 2026-08-03 Playback Accumulation Fix

- `static`: fixed the HTML player's animation clock so sub-33ms
  `requestAnimationFrame` callbacks accumulate elapsed time instead of
  resetting `lastTs` on every callback. This was the cause of the previously
  non-moving automatic playback; manual `stepFrame` was unaffected.
- `browser`: regenerated both map HTML files and verified the real browser
  path: 克哈裂痕 `togglePlay()` moved frame `0 -> 6`, then `stepFrame(1)` moved
  `6 -> 7`; 亡者之夜 produced the same transitions. No page, console, or
  request errors occurred.
- `static`: the new playback regression assertion and the full Stage 25 plus
  Stage 19/20 regression passed; `py_compile`, `git diff --check`, and the
  `52/52` static validation gate also passed.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/browser-projection-smoke-20260803-v2.json`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-keha-20260803-v2/克哈裂痕/state-driven-player.html`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/map-derived-dead-of-night-20260803-v3/full-map-player.html`.

## Verification Loop 2026-08-03 Imported Map Debug Tool Documentation

- `static`: copied the user-provided `地图调试和斗蛐蛐工具（完整功能版).SC2Map` and legacy `.doc` into the stage artifact import directory; the copied map SHA-256 matches the download source.
- `static`: opened the legacy `.doc` read-only through Word COM, extracted 294 paragraphs, and exported 41 embedded screenshots. The AI-readable Markdown keeps the extracted text in document order and links all 41 valid JPG/PNG files.
- `static`: strict Markdown checks found 41/41 image links present, zero control characters, and all 41 exported images decodable. A representative exported screenshot was visually inspected.
- `static`: the imported map remains an artifact/read-only input and was not promoted into the canonical `packages` tree; no runtime behavior claim is made for this import.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/imports/地图调试和斗蛐蛐工具（完整功能版）/地图调试和斗蛐蛐工具（完整功能版).SC2Map`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/imports/地图调试和斗蛐蛐工具（完整功能版）/地图调试和斗蛐蛐工具（完整功能版)说明文档.md`,
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/imports/地图调试和斗蛐蛐工具（完整功能版）/images/`.

## Verification Loop 2026-08-03 Tool README Summary

- `static`: added `README.md` beside the imported map and converted manual. It summarizes the tool as an SC2 in-map debugging panel and unit-versus-unit experiment sandbox.
- `static`: the summary covers unit creation, skills/behaviors/items/weapons, tech/resources/player control, statistics/effect lookup, model attachment and animation tuning, and formation-based battles.
- `static`: README links resolve to the local map, original `.doc`, converted Markdown, and screenshot directory. It explicitly preserves the read-only import boundary and makes no new runtime compatibility claim.

Evidence:
`artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/imports/地图调试和斗蛐蛐工具（完整功能版）/README.md`.
