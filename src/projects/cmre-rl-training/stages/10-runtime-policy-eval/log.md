# Stage 10 Log: Runtime Policy Evaluation

**Date**: 2026-08-05
**Stage**: 10-runtime-policy-eval
**Status**: BLOCKED FOR MISSION TERMINAL EVIDENCE

## G1: Terminal Contract

- **Result**: PASS offline — raw `ResponseObservation.player_result` is normalized
  into `player_result`, `mission.terminated`, `mission.end_reason`, and
  `mission.win_condition=player_result`.
- **Evidence**: `cmre_rl_training/live_sc2_session.py`,
  `tests/test_live_sc2_session.py::LiveActionSpecTests.test_player_result_becomes_terminal_mission_state`。
- **Details**: victory, defeat, tie, and undecided result names are retained;
  `RawSc2Backend` already terminates on the normalized result.

## G2: Held-Out Map Matrix Contract

- **Command**: `python src/projects/cmre-rl-training/tools/evaluate_live_policy.py ... --map dead-of-night|亡者之夜.SC2Map|... --map void-launch|虚空降临.SC2Map|... --dry-run`
- **Result**: PASS static — generated 2 maps x 3 variants = 6 fresh-run commands,
  with independent ports, checkpoint SHA-256, terminal stop, replay save, and
  report paths.
- **Evidence**: `artifacts/stage-10-runtime-policy-eval/dry-run-2/evaluation-report.json`。

## G3: Baseline And Trace Contract

- **Result**: PASS offline — frozen-stochastic, live-update, and deterministic-
  baseline variants are represented; action trace records decision index, action,
  loop-before/after, grounded target, raw results, and errors.
- **Evidence**: `tools/evaluate_live_policy.py`,
  `cmre_rl_training/live_sc2_session.py`,
  `tests/test_live_policy_eval.py`。
- **Replay**: `LiveRawSc2Session.save_replay()` requests native SC2 replay bytes
  before LeaveGame; the runner writes `live-replay.SC2Replay` under the run directory.

## G4: Fresh Runtime Attempt

- **Command**: `python src/projects/cmre-rl-training/tools/evaluate_live_policy.py ... --max-steps 64 --step-mul 8 --port-start 5960 --output-dir src/projects/cmre-rl-training/artifacts/stage-10-runtime-policy-eval/20260805-bounded-64`
- **Result**: BLOCKED — all 6 subprocess reports were rejected by the approved
  launcher because an external runtime owner held PID `20740` on port `5965`.
  A subsequent isolated retry on port `5967` was rejected by the same launcher
  with external PID `16288`, port `5966`, session `zchar01_reborn_port`.
  After that owner released, a fresh retry on ports `5970-5975` was again rejected
  by external PID `48212`, with unknown port and session
  `cmre_alenger-20260805-205220-7132742a`.
  A further retry on the same ports was rejected by external PID `69888`, a
  `-KeepAlive` `launch-cmre-alenger.ps1` process for `zchar01_reborn_port`; its
  SC2 child was PID `52096` listening on port `6119`, session
  `cmre_alenger-20260805-205731-6abdb4cd`.
- **Evidence**:
  `artifacts/stage-10-runtime-policy-eval/20260805-bounded-64/evaluation-report.json`,
  `artifacts/stage-10-runtime-policy-eval/blocked-lease-dead-of-night/live-rl-report.json`,
  `artifacts/stage-10-runtime-policy-eval/blocked-lease-dead-of-night/launcher.err.log`,
  `artifacts/stage-10-runtime-policy-eval/20260805-bounded-64-retry/evaluation-report.json`,
  `artifacts/stage-10-runtime-policy-eval/20260805-bounded-64-retry-2/evaluation-report.json`,
  `artifacts/stage-10-runtime-policy-eval/20260805-bounded-64-retry-2/dead-of-night-frozen-stochastic/launcher.err.log`。
- **Interpretation**: `sample_count=6`, `terminal_count=0`, and
  `runtime_clean=false`; no win rate is computed. This is a runtime lease block,
  not a policy defeat or victory.

## G5: Validation

- **Focused tests**: 24 passed for terminal parsing, evaluator commands,
  blocked summaries, and terminal-stop rollout behavior.
- **Full project tests**: 171 passed.
- **Compilation**: `py_compile` passed for all changed Python modules.
- **Runtime cleanup**: runner-owned SC2 PID snapshots are used for cleanup; the
  external owner PIDs `16288`, `48212`, and `69888` were not touched. The latest
  owner was still alive after the retry and is a separate `-KeepAlive` session.

## G6: Current-Map Victory-First MVP

- **Simulator**: `train_multi_map.py --backend simulator --maps dead-of-night`
  resumed the existing checkpoint for 10 iterations / 640 steps and emitted
  `artifacts/current-map-victory-20260805/map-aware-policy.pt`; the training
  report status is `passed` with `total_mean_reward=151.2`.
- **Runtime**: a current-map run on port `5991` reached API readiness,
  `CreateGame`, `JoinGame`, frame advancement, 581 successful actions, and
  native replay save over 2048 decisions through loop `16384`; same-window
  ScriptError was clean. No `player_result` arrived before the bounded cutoff,
  so this is runtime bridge evidence, not a victory claim.
- **UI diagnosis**: the launcher log records `commander selection code disabled`
  and `headless startup patch`; the visible frontend was the SC2 API bootstrap
  window. `run_live_rl.py` now passes approved-launcher `-DebugMode`, which
  minimizes that frontend while preserving API `CreateGame+JoinGame` map entry.
- **Headless runtime**: a fresh run with the new flag on port `6001` passed the
  full API bridge: `CreateGame`, `JoinGame`, frame advancement, 578 successful
  actions, 2048 decisions through loop `16384`, native replay save, and clean
  same-window ScriptError verdict. The launcher recorded `commander selection
  code disabled`, `headless startup patch`, `SC2 API mode (ApiMinimal)`, and
  `DebugMode: SC2 窗口已最小化`. No `player_result` arrived before the bounded
  cutoff, so the map-entry/UI issue is resolved but mission victory remains
  unverified.

## Outcome

Stage 10 now has a current-map victory-first path and a verified direct map-entry
surface with the bootstrap window minimized. The runtime bridge is proven through
`CreateGame+JoinGame` and bounded action/replay evidence, while a real mission
victory remains unverified because the 2048-decision run had no `player_result`.
The evaluator correctly refuses to turn bounded/no-terminal or launcher-blocked
runs into a win-rate claim. P2 remains native Computer and is outside the
ML-control claim.

## G7: DirectMapApi Attach Retry

- **Static implementation**: `tools/run_live_rl.py` now launches the approved
  `-DirectMapApi` path and constructs `LiveRawSc2Session(join_existing=True)`,
  so the runner does not issue `CreateGame`. `Sc2ApiClient` reconnects after a
  SC2 WebSocket close, while `JoinGame` retries for the map initialization
  window. Ordinary action/step requests are not replayed automatically.
- **Focused validation**: `test_direct_map_attach_skips_create_game` and the
  transient JoinGame retry test passed; full project suite passed with 173
  tests; changed Python modules compiled.
- **Runtime attempt**: command
  `python src/projects/cmre-rl-training/tools/run_live_rl.py ... --port 6004
  --max-steps 64 --step-mul 8 --stop-on-terminal --save-replay` was rejected
  before API readiness by the approved launcher because external
  `owner_pid=44508` held the SC2 runtime lease for
  `zchar01_reborn_port.SC2Map`. The runner did not terminate that process.
- **Evidence**:
  `artifacts/stage-10-runtime-policy-eval/direct-map-entry-retry-6004/live-rl-report.json`,
  `artifacts/stage-10-runtime-policy-eval/direct-map-entry-retry-6004/launcher.err.log`。
  This is a truthful runtime block (`api_ready=false`), not proof of map entry
  or victory; DirectMapApi still needs a fresh lease-available run.

## Current Outcome

The direct-entry implementation and attach contract are in place, but current
runtime evidence is blocked by an external SC2 process. The previous
ApiMinimal/CreateGame runs remain historical bridge evidence only; they do not
validate the new DirectMapApi path. No mission victory or win rate is claimed.

## G8: PPO Exploration Stabilization

- **Static implementation**: `PPOTrainer` now applies `ent_floor` as a true
  differentiable entropy penalty. The previous form cancelled the entropy
  gradient below the floor, so it recorded an anti-collapse parameter without
  actually pushing low-entropy policies back toward exploration. The GAE docs
  were also corrected to distinguish normalized value targets from advantage
  normalization.
- **Reproducibility**: `train_multi_map.py` reports `ent_coef` and `ent_floor`
  in `training-report.json`, and the checkpoint training metadata records the
  same values. This makes simulator smoke runs reproducible from their report
  and checkpoint alone.
- **Focused validation**: PPO/training/self-training focused tests passed with
  15 tests, including new regression coverage for below-floor entropy gradient,
  above-floor standard entropy bonus behavior, and CLI report propagation of
  the exploration parameters.
- **Simulator evidence**: command
  `python src/projects/cmre-rl-training/tools/train_multi_map.py --backend simulator --maps dead-of-night --iterations 3 --rollout-steps 32 --max-episode-steps 64 --ppo-epochs 2 --batch-size 16 --ent-coef 0.05 --ent-floor 0.5 --step-loops 16 --output-dir src/projects/cmre-rl-training/artifacts/stage-10-runtime-policy-eval/entropy-floor-smoke-20260809`
  completed 96 simulator steps and emitted a passed report plus checkpoint.
  PPO losses were finite and entropy stayed in the 2.37-2.43 range.
- **Full validation**: `PYTHONPATH=src/projects/cmre-rl-training;src/projects/cmre-neuro-adapter;src/projects/cmre-porting python -m unittest discover -s src/projects/cmre-rl-training/tests -v`
  passed 176 tests with 14 expected BC-checkpoint skips.
- **Boundary**: this is offline/simulator training evidence only. No live
  `player_result`, mission victory, or win rate is claimed from this pass.

## G9: API Readiness False-Positive (2026-08-10)

- **Symptom**: live runs aborted at `CreateGame` with
  `sc2_api_connect_timeout:Server disconnected` while the report still recorded
  `api_ready=true`.
- **Root cause**: `wait_for_api` treated a bare TCP connect as readiness. SC2
  opens its listening socket well before the `/sc2api` websocket handler is
  installed, so the runner declared the API ready, then burned its entire 30 s
  `connect` budget on a socket that closed every handshake.
- **Fix**: `probe_sc2_api()` now performs a real `ws_connect` + protobuf `Ping`
  and only returns ready once the protocol answers; `wait_for_api` gates on that
  probe and also aborts when the launcher process exits. `Sc2ApiClient.connect`
  default timeout widened 30 s -> 120 s as defense in depth. The report records
  `api_ready_basis="sc2api_websocket_handshake_and_ping"`.
- **Evidence**: every subsequent run logs
  `[wait_for_api] sc2 api ready on <port>: game_version=5.0.16.97563 status=1`
  and reaches `CreateGame` + `JoinGame`.
- **Boundary lesson**: "the port is open" is not "the service answers". A
  readiness probe that cannot fail is not a readiness probe.

## G10: Blocked Runs Must Name Their Cause

- **Symptom**: a 512-step run reported `status=blocked` with
  `blocked_reason=null` — the same "checker without a checker" smell that hid a
  real defect in CMLib round22.
- **Fix**: `run_live` now builds an explicit `gate_failures` list
  (`api_not_ready`, `create_game_failed`, `join_game_failed`,
  `no_frame_advancement`, `no_action_results`, `zero_action_successes[...]`,
  `step_budget_not_met`), writes it to `runtime_gate_failures`, and sets
  `blocked_reason="runtime_gate_failed:<causes>"`.
- **Evidence**: `artifacts/stage-10-runtime-policy-eval/20260810-ab-newmap/live-rl-report.json`
  now reports `runtime_gate_failed:zero_action_successes:player_faction_uninitialised`
  instead of a blank reason.

## G11: Runtime Census And The Packed-Map Faction Regression

- **Instrument**: `build_runtime_census()` snapshots own units, unit types,
  visible enemies/allies and resources at the first and last observation, so
  "the mission never started" stops masquerading as "the policy chose badly".
- **Single-variable A/B (identical code, parameters and 128 steps; only the
  packed map differs)**:

  | | `亡者之夜_live_packed_GAMEPLAY_OK_20260731.SC2Map` | `亡者之夜_live_packed.SC2Map` |
  | --- | --- | --- |
  | md5 / size | `fa20e497…` / 3 280 916 B | `5f122326…` / 5 756 487 B (20260809-23:33 repack) |
  | status | `passed` | `blocked` |
  | gate failures | `[]` | `zero_action_successes:player_faction_uninitialised` |
  | census verdict | controllable surface present | `player_faction_uninitialised` |
  | own units @ loop 1024 | 2 (`4051` + `Marine`) | 1 (`4051` only) |
  | minerals / visible enemies | 50 / 27 | 0 / 0 |
  | successful actions | 66 / 128 | 0 / 128 |
  | ScriptError | 0 | 0 |

  `api_ready`, `create_game`, `join_game` and `frame_advancement` are **true on
  both arms**, so this is not a transport, launcher or protocol defect.
- **Evidence**:
  `artifacts/stage-10-runtime-policy-eval/20260810-ab-oldmap/live-rl-report.json`,
  `artifacts/stage-10-runtime-policy-eval/20260810-ab-newmap/live-rl-report.json`,
  `artifacts/stage-10-runtime-policy-eval/20260810-raynor-512b/live-rl-report.json`
  (0/512 on the repack, single tag `4326424577`).
- **Corrected attribution**: the prior root-cause note claimed the packed map
  inherently never enters gameplay because it retains the CMRE launcher and
  campaign trigger stack. That is falsified here — the Jul-31 artifact carries
  the *same* launcher and campaign stack and does hand the player a controllable
  unit. The regression was introduced by the 2026-08-09 rebuild (base switched
  to the Aug-8 `_live_vibe` map plus a 140 047 B kernel injection), not by the
  campaign stack as such.
- **Containment**: `run_live_rl.py` now defaults `--map-path` to the known-good
  artifact, with the A/B justification inline, and `tests/test_live_map_pin.py`
  fails if the default, the file, or its md5 ever drifts. The guard was verified
  with a negative control: reverting the default to the broken repack makes the
  test suite fail (rc=1, 2 failures), and the source was restored byte-identical.

## G12: Stage 5 Live Ladder (2026-08-10)

All runs use the approved launcher, the known-good packed map, Raynor at the
declared max level with full mastery, `--stop-on-terminal` and `--save-replay`.

| rung | steps | loops | successful actions | distinct actions | entropy (nats) | illegal rate | ScriptError | replay | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 512 | 0 → 4 096 | 213 | 8 | 1.860 | 0.0 | 0 | 56 959 B | `passed` |
| 2 | 2 048 | 0 → 16 384 | 874 | 8 | 1.868 | 0.0 | 0 | 57 376 B | `passed` |
| 3 | 8 192 | 0 → 65 536 | 3 298 | 8 | 1.873 | 0.0 | 0 | 68 427 B | `passed` |

- **Gates**: no ScriptError, no API/launcher mismatch, commander max-level gate
  passed, and the action distribution is not collapsed (8 distinct actions,
  entropy ≈ 1.86–1.87 of a 19-way space).
- **Ladder is monotone and stable**: the success rate holds at 41.6 % / 42.7 % /
  40.3 % and `reward_mean` is −1.1494 (2 048) versus −1.1499 (8 192) — a 16×
  longer horizon does not degrade the runner, so the bridge is not a
  short-rollout artefact.
- **Evidence**:
  `artifacts/stage-10-runtime-policy-eval/20260810-raynor-512-accept/`,
  `artifacts/stage-10-runtime-policy-eval/20260810-raynor-2048-accept/`,
  `artifacts/stage-10-runtime-policy-eval/20260810-raynor-8192-accept/`
  (each holds `live-rl-report.json`, `live-replay.SC2Replay`, `launcher.log`).
- **Honest boundary — no terminal result is reachable on this artifact**: the
  census is *flat* from loop 1 024 all the way to loop 65 536 —
  `own_unit_count=2`,
  `minerals=50`, `supply_cap=0`, `visible_enemy_count=27` throughout. The policy
  controls exactly one real unit (tag `4418437121`); `build_structure`,
  `produce_unit` and `gather_resources` are chosen 0 times because there is no
  base to use them on. The known-good artifact therefore grants a *controllable
  unit*, not a *commander economy*.
- **Consequence**: `build_runtime_census` now reports three states and a
  `terminal_evidence_reachable` flag. This artifact classifies as
  `partial_faction:units_without_commander_economy`, which is valid Stage-5
  action evidence and structurally cannot produce a mission `player_result`.
  Stage 6 stays blocked until an artifact reports
  `terminal_evidence_reachable=true`; chasing a victory run on this map would
  only manufacture timeouts.

## G13: Two Diagnostic Traps Hit While Closing the 8 192 Rung (2026-08-10)

The third rung took three attempts. Neither of the first two failures was what
it looked like, and both are the kind of mistake that gets recorded as a fake
defect if it is not chased to the bottom.

### Trap 1 — `EXIT=127` came from the harness, not from the program

The first 8 192 attempt (port 5970) reported `EXIT=127` with a stdout that
contained only `[wait_for_api] sc2 api ready on 5970: ...`. Exit 127 reads as
"the program died", and 127 in a shell means *command not found* — so the
obvious reading was "the Python entry point was not found". Both readings are
wrong: the launcher log for that attempt is complete and healthy, and the real
cause is that **the agent shell on this host has no `sleep` binary**
(`/usr/bin/bash: line 1: sleep: command not found`). A `sleep` in the command
chain returned 127 and that code was attributed to the run.

- **Rule**: on this host never put `sleep` in a bash command chain — use the
  shell-tool equivalent (`Start-Sleep`) instead. And never read `$?` of a
  *chain* as the exit status of the *program*; capture the program's own status
  explicitly and give it its own stderr file.
- **Tell**: the exit code and the artifacts disagree (127 but the launcher log
  is complete; or 0 but no report on disk). Trust the artifacts.

### Trap 2 — a real but transient SC2 disconnect

The second attempt (port 5972) produced a genuine failure report:
`error="LiveSc2Error: sc2_api_websocket_closed:257:None"` (257 is
`aiohttp.WSMsgType.CLOSED`), 19 observations, 18 steps, loop 144,
`runtime_gate_failures=["step_budget_not_met"]`, `replay_saved=false`,
`leave_error="sc2_api_not_connected"`. SC2 dropped the socket about 6 s of game
time in.

- **Ruled out — the launcher**: a `diff` of the failing and the passing
  (2 048-step) `launcher.log` with all digits normalised differs on exactly one
  line, the lock session id. Identical behaviour, so the launcher is not a
  variable here.
- **Ruled out — a systematic 8 192 ceiling**: the retry with the identical
  parameter set on a fresh port reached all 8 192 steps.
- **Classification**: transient runtime disconnect, logged as EVAL-011. The
  failure is *fail-closed and self-labelling* — `status=failed`,
  `runtime_gate=false`, `step_budget_not_met`, no replay — so it can never be
  mistaken for evidence. That is the gate working, not the gate breaking.
- **Rule**: a mid-rollout `sc2_api_websocket_closed` is retried exactly once on
  a fresh port after a clean SC2 kill. If it reproduces at a similar step count
  it is a defect; if it does not it is logged as transient. Never retry
  silently.

### Trap 3 (self-inflicted) — the retry destroyed its own evidence

The retry reused the *same* output directory and deleted
`live-rl-report.json` before relaunching, so the failing report from attempt 2
no longer exists on disk. What survives is
`20260810-raynor-8192-accept/failed-attempt-5972.transcript.json`, explicitly
marked `_kind: transcript-excerpt` and `_warning: NOT a runner-produced
artifact` — it is a console transcription, and it is recorded as a log entry,
not as evidence. This is written down rather than quietly patched because a
reconstructed file that looks like a runner artifact is worse than a missing
one.

- **Rule**: a retry never reuses the output directory of the attempt it is
  retrying. Suffix it (`-attempt2`, `-attempt3`) so every attempt keeps its own
  `live-rl-report.json`, `launcher.log` and stdout/stderr.

## G14: Root Cause of the Missing Commander Economy (2026-08-10)

EVAL-009 said "no artifact grants a commander economy" but treated it as a
property of the packed map. A second, independent evidence channel — one that
does not go through the SC2 API at all — now says *why*.

The launcher performs a `CMRE runtime listener bank reset` at every launch, so
`Documents/StarCraft II/Banks/<n>/CMRERebornDebug.SC2Bank` starts each run
zeroed. After the passing 8 192-step run (launcher reset at 01:08:42, run ended
01:11:45, 65 536 game loops in between) the bank is **still entirely zero** —
159 keys, `nonzero_ints=0`, in all three account folders that hold it (1, 2, 14).
The decisive keys:

| key | value after 65 536 loops |
| --- | --- |
| `initialization_gate_started` | 0 |
| `initialization_complete` | 0 |
| `initialization_units_ready_p1` | 0 |
| `initialization_building_ready_p1` | 0 |
| `bridge_heartbeat_started` | 0 |
| `bridge_starting_units_created_p1` | 0 |
| `hatchery_p1_count` / `drone_p1_count` | 0 / 0 |
| `startup_custom_launch` | 0 |

- **Root cause**: the CMRE Reborn initialization / bridge trigger chain never
  executes in this run. It is not that the chain runs and fails a condition —
  `initialization_gate_started=0` means it never even entered the gate.
- **Why the Marine still exists**: the map's own start-up gives P1 one unit and
  50 minerals, which is what the API census sees. The *co-op commander*
  initialization — the part that would place a Command Center and SCVs and
  therefore raise `supply_cap` above 0 — is a CMRE Reborn trigger, and that is
  the part that never fires. "One controllable unit" and "a commander economy"
  come from two different code paths, and only the first one is alive.
- **Cross-module consistency**: this is the same signature already recorded for
  the N5b port line — markers written before the first `Wait` exist, everything
  that needs a post-`Wait` execution slice is dead. Two independent projects,
  same failure shape.
- **Consequence for the plan**: Stage 6 is not blocked by "we need a better
  packed map" in the abstract; it is blocked by one concrete, checkable
  condition — get `initialization_gate_started` to become non-zero. That is now
  the acceptance signal for any future artifact, and it can be checked from the
  bank without burning a live API run.
- **Evidence**:
  `artifacts/stage-10-runtime-policy-eval/20260810-raynor-8192-accept/CMRERebornDebug.postrun.SC2Bank`
  (snapshot taken straight after the passing run).

## G15: The Overlay Was Never Packed (2026-08-10)

G14 named the acceptance signal — get `initialization_gate_started` to become
non-zero — but still assumed the fix lived inside the packed map's contents.
It did not. It lived in *which tree got packed*.

The approved launcher does not hand SC2 the artifact from `artifacts/live-maps/`.
It stages a map into `E:\SC2\SC2new\StarCraft II\Maps\亡者之夜.SC2Map` and
then injects an overlay set into that staging directory at launch time — its own
log says so, line by line:

```
CMRE Galaxy host overlay: 12 CMRE files (official commander, no adapter)
CMRE preselected commander startup overlay applied ...: TerranRaynor
CMRE trigger custom-script overlay applied: ...\Maps\亡者之夜.SC2Map\Triggers
CMRE startup debug markers applied
CMRE observer/runtime overlay applied on demand
CMRE core runtime error patches applied: 19 locations
```

Every packed artifact in `artifacts/live-maps/` predates that injection, because
they were packed from *source* trees. `run_live_rl.py` then deliberately loads
the packed artifact through `CreateGame(local_map=map_data)` (the N5b map-path
mismatch fix), which means the staged, fully-overlayed map is built at every
launch and then never used. The initialization gate could not fire because the
trigger that opens it was not in the bytes SC2 was given.

- **Fix**: pack the launcher's staging directory itself.
  `tools/mpq/scripts/pack_stormlib.py` over
  `E:\SC2\SC2new\StarCraft II\Maps\亡者之夜.SC2Map` produces
  `artifacts/live-maps/亡者之夜_live_packed_OVERLAY_20260810.SC2Map`
  (md5 `ccc74e2c6fff5b1914d196b5867705c5`, 3 328 542 B). Re-extracting it
  confirms the markers the previous artifacts lacked:
  `gt_CmreOnDemandInitializationGate_Init` x3, `initialization_gate_started` x1,
  `gt_CmreOnDemandCommanderStartingUnits_Init` x3, `LibMapModBridge`,
  `LibPortingObserver`, and `TerranRaynor` x10 in `LibCOOC.galaxy`.

### Single-variable A/B, 256 steps

| | GAMEPLAY_OK_20260731 | OVERLAY_20260810 |
| --- | --- | --- |
| census verdict | `faction_initialised` | `faction_initialised` |
| `commander_economy_online` | **false** | **true** |
| supply | 0 / 0 | **15 / 15** |
| own units | Marine + placeholder 4051 | **15 SCV + CommandCenter** + 4051 + 4028 |
| minerals | 50 | **535** |
| visible enemy / ally | 27 / - | 9 / 29 |
| `terminal_evidence_reachable` | false | **true** |
| reward_sum | -587.65 | **+2577.95** |
| illegal action rate | - | 0.0 |

- **`faction_initialised` was not a sufficient pin.** The 20260731 artifact
  satisfies it while leaving `supply_cap=0` forever, so it can hand out a unit
  and still never reach a mission terminal. The pin test now keys on the overlay
  artifact by md5 and requires the source comment to document
  `commander_economy_online`, not just the faction verdict.

### Evidence durability — an honest gap, and the fix for it

The matching bank read did land: at 04:40 the **root** bank
`Documents/StarCraft II/Banks/CMRERebornDebug.SC2Bank` showed
`initialization_gate_started=1`, `initialization_complete=1`,
`map_init_entered=1`, `preselected_commander_startup=1`,
`initialization_building_ready_p1/p2=1`, `initialization_units_ready_p1/p2=1`.
Two things about that reading are worth recording:

1. The real writes go to the **root** bank file, not the account-scoped
   `Banks/1|2|14/` copies that G14 sampled — those stay zeroed. Sampling only
   the account folders would have kept reporting a false negative.
2. It is **transient**. The launcher resets that bank at every launch, and the
   04:42 relaunch overwrote it. The file cited above no longer exists.

So the durable citation for this entry is the API-side census in
`20260810-overlay-ab-256/live-rl-report.json`, not a bank file, and the bank
reading is logged as a transient observation. `snapshot_initialization_banks()`
was added to `run_live_rl.py` (with
`tests/test_initialization_bank_snapshot.py`, 4 cases including a zeroed-bank
negative control and an "account copies must not mask a root write" case) so
that from the next run onwards the bank is copied into the run's own output
directory before the launcher dies.

- **Rule**: evidence that a launch resets is not evidence until a run captures
  it. If a signal only exists between two launches, the capture has to live
  inside the runner, not inside the operator's session.

## G16: A Scheduling Collision Wearing a JoinGame Costume (2026-08-10)

The first Stage 6 long-horizon attempt failed with `api_ready=true`,
`create_game=true`, `join_game=false`, and
`JoinGame_timeout:sc2_api_connect_timeout ... 远程计算机拒绝网络连接`. Read
naively that is "the map fails to load on JoinGame" — and the map would have
been the prime suspect, since it had just been rebuilt.

The launcher log says otherwise:

```
SC2 API mode: API listening on 127.0.0.1:5972 (SC2_x64 PID=29720)
...
SC2 runtime lease: PID=29720 exited; releasing the global lease
```

The game SC2 had already brought up **exited on its own** between CreateGame and
JoinGame. The same log also shows this session preempting a previous lock holder
and terminating an SC2 process it judged orphaned:

```
[TestLock] 旧锁持有者进程已退出，自动抢占
[cleanup]   终止 PID=6508 Name=SC2_x64 ParentPID=41024
```

A concurrent galaxy-vibe transport probe
(`tools/galaxy-vibe/transport/bank_probe.py --port 5000 --ping-count 100`) was
cycling SC2 in the same window. The real-machine slot is a single global
resource — one ws port slot, one `artifacts/runtime/sc2-runtime-lease.json`, and
an orphan-cleanup path that kills SC2 processes — so two lines running at once
preempt and kill each other.

- **Diagnosis rule**: when a runtime gate fails at a *later* stage than the one
  it previously reached, check whether the process that was serving it is still
  alive before blaming the artifact. `join_game=false` with `create_game=true`
  and a dead server PID is a liveness failure, not a map failure.
- **Discipline**: real-machine runs yield, they do not preempt.
  `out/stage6_guarded.py` polls until no foreign `SC2_x64.exe` and no
  `bank_probe`/matrix python process is in flight, waits, and then launches. If
  the slot never frees inside the window it writes `status: "yielded"` — a
  refusal to run, deliberately distinct from a failure, so a scheduling
  collision can never be laundered into evidence about the policy or the map.

## G17 — Yielding At The Door Does Not Keep The Room

`out/stage6_guarded.py` v1 waited for an empty slot and then launched. It worked
exactly as designed, and the run still died.

The 04:55 attempt was **healthy**: `join_game=true`, `frame_advancement=true`,
3014 policy steps, game loop **24112** (~18 minutes of mission time), 188
successful actions, `script_error_verdict.count=0`. Then:

```
error: LiveSc2Error: sc2_api_websocket_closed:257:None
runtime_gate_failures: ["step_budget_not_met"]
```

Forensics, to the second:

| time | event |
| --- | --- |
| 05:02:15 | our `sc2-runtime-lease.json` writes its last heartbeat (`runtimePid=31200`, port 5974) |
| 05:02:18 | `SC2Switcher_x64.exe -listen 127.0.0.1 -port 5000 -debug` starts (parent PID 36392, already dead) |

Three seconds. The competing galaxy-vibe line took the slot out from under a
running game.

**A launch-time check protects the launch, not the run.** That is not a bug in
v1, it is the limit of what v1 could ever do. The exposure is the whole run
duration, so the fix has to attack duration, garbage, and misattribution
together:

1. **Shrink the exposure.** Measured throughput was ~8.4 policy steps/s and
   ~67 game loops/s at `step_mul=8`. The per-step cost is observation build +
   inference, *not* SC2 simulating loops — so raising `step_mul` to 32 buys
   roughly 4x game time per wall second. `6000 x 32 = 192000` loops covers
   ~143 minutes of mission time in ~12 minutes of wall clock. A 32-minute
   exposure against an hourly competitor is a coin flip; 12 minutes is not.
2. **Reclaim corpses, never evict live work.** After the collision the box was
   left with `SC2_x64` PID 38208 listening on 5000 with its parent dead, zero
   ESTABLISHED sockets and no driver process — the competing line had finished
   at 05:06:51. v2 reclaims a foreign runtime only when *no* foreign python
   driver exists **and** its port shows zero ESTABLISHED connections in two
   samples 20s apart. Two samples, because one cannot tell an abandoned runtime
   from one that is a heartbeat away from reconnecting. It reclaimed 38208 and
   the slot freed 15s later.
3. **Never file a stolen run as a result.** v2 diffs the SC2 process set across
   the run; a closed socket plus a process we did not own appearing mid-run is
   labelled `preempted` and retried in a fresh directory. `step_budget_not_met`
   caused by a competitor is a scheduling fault. Letting it reach the ledger as
   a Stage 6 outcome would be a measurement reporting the state of the
   scheduler while claiming to describe the policy.

### The snapshot that could be destroyed by an unrelated directory

The same report carried:

```
initialization_bank: {"error": "FileNotFoundError: [WinError 3] ...
  .runtime-lab-backup-1786206967\.runtime-lab-backup-1786206967\ (x7)"}
```

`snapshot_initialization_banks()` scanned with
`Path.glob("**/CMRERebornDebug.SC2Bank")`, which walks into the pathologically
self-nested backup chain in `Documents/StarCraft II/Banks` until the path
overruns MAX_PATH. The snapshot exists precisely because the init-chain evidence
is transient — and it lost that evidence to a directory that has nothing to do
with the run.

Replaced with `iter_debug_banks()`: a depth-bounded `os.walk` that prunes
`.runtime-lab-backup*`. Verified against the real Banks root — 4 banks, no
exception. The regression test rebuilds the cursed chain (4 levels; 6 already
overruns MAX_PATH while *creating the fixture*, which is the same wall the
production glob hit), and a second test asserts an ordinary nested bank
(`Banks/14/`) is still collected — without that negative control, "prune the
cursed directory" could quietly degenerate into "only ever read the root" and
drop the account-scoped copies the merge depends on.

- **Rule**: a measurement that its own environment can destroy is not a
  measurement. Harden the collector, not the conclusion.
- **Rule**: when a guard fails, ask what it was *structurally capable* of
  guarding before adding more of the same. v1 was not a weak door check; it was
  a door check applied to a duration problem.

Incidental evidence of the collision, found while fixing the scan: the root
`CMRERebornDebug.SC2Bank` now reads `stage16_before_vibe=1 / stage16_after_vibe=1`
— the galaxy-vibe line's markers. Our init markers are gone. One bank, two
writers, last writer wins.

## G18 — Three Green Lights On A Run That Never Finished A Game

The run everyone was waiting for finally happened, uninterrupted: 6000 steps at
`step_mul 32`, **192,000 game loops — about 143 minutes of mission time**,
`join_game=true`, `frame_advancement=true`, 0 ScriptErrors, a 1.41 MB replay on
disk, bank snapshots captured. Nothing preempted it. The yield discipline from
G17 worked.

`terminal_observed=false`. `terminal_results=[]`.

That kills the horizon hypothesis outright. Four full matches' worth of time
elapsed and the mission never handed this player a `player_result`. Stage 6 was
never blocked by "not long enough".

What the run did produce was three checkers reporting success on the one
question Stage 6 exists to answer.

**Green light 1 — the report.** `status="passed"`, `runtime_gate=true`,
`runtime_gate_failures=[]`. The gate read:

```python
int(report.get("steps_collected", 0)) == int(args.max_steps)
or (args.stop_on_terminal and report.get("terminal_observed"))
```

An `or`. Exhausting the budget and observing a terminal were interchangeable.
`--stop-on-terminal` *permits* an early exit; it never *demanded* one. So the
plan's hard rule — "do not convert timeout/cutoff into victory" — was violated
by the code that was supposed to enforce it, and it looked like a pass.

**Green light 2 — the guard.** `stage6_guarded.py` was written last round
specifically to stop a bad run from being filed as a result. Its `classify()`
began `if status == "passed" or report.get("terminal_observed")`. It trusted the
checker it was guarding. `attempts.json` records `final_outcome: "terminal"`
directly above `"terminal_observed": false`.

**Green light 3 — the action metric.** `illegal_action_rate = 0.0`,
`illegal_action_count = 0`. Meanwhile the engine's own verdict on the same 6000
orders:

| ActionResult | count | share |
| --- | --- | --- |
| NotSupported (2) | 3485 | 58.1% |
| Error (3) | 2450 | 40.8% |
| **Success (1)** | **50** | **0.83%** |
| Cant* (100/89/28) | 15 | 0.3% |

`illegal_action_rate` measures whether the policy picked an action the *mask*
allowed. It is structurally incapable of noticing that the game threw away
99.2% of the resulting orders. The gate's only related check,
`action_successes > 0`, is the degenerate threshold in its purest form: 50
passes it exactly as well as 6000 would.

The action distribution says the same thing without any metric at all —
`build_structure 0`, `research_upgrade 0`, `produce_unit 2`,
`gather_resources 21`, against 5865 move/stop/hold/patrol/attack-move orders
aimed at a handful of repeated unit tags.

### What the census got wrong, and why it matters more than it looks

`runtime_census.final`: `supply_cap=0`, `own_unit_count=2`, `minerals=2472`.
Verdict: `partial_faction:units_without_commander_economy` — the
*broken artifact* label. But this repo already records this same overlay
artifact reporting `faction_initialised` (see the comment at the head of
`run_live_rl.py`). Both cannot be true of a healthy measurement.

They can both be *reported* by a measurement that samples exactly two points.
"Never received an economy" and "had a base and lost it" both end at
`supply_cap=0` with a couple of stragglers. The census could not tell them
apart — and the two have opposite consequences: one says stop and fix the map,
the other says the policy lost a real match. Choosing the wrong branch here
costs a whole round.

Fix: `CensusPeakTracker`, sampled from inside the action-grounding hook (the
only place that already receives the raw observation every step, so
`collect_rollout` and `ActionGrounder` stay untouched). The census now carries
`commander_economy_ever_online`, `economy_collapsed`, a `peak` block with
`max_supply_cap` and the loop it happened at, and a new verdict
`economy_lost:commander_economy_came_online_then_collapsed`.

### The thing sitting in the bank

`bridge_prevent_defeat_p1 = 1`.

If the mod suppresses defeat for the API player, then a player with no
production can neither win nor lose. That is precisely the frozen state
observed for two hours of mission time. If that reading holds, no horizon will
ever satisfy Stage 6 by waiting — filed as EVAL-019, and it is a *static source*
question, answerable with no real-machine slot at all.

### Rules

- **`--stop-on-terminal` permits; it does not demand.** A flag that allows an
  early exit is not an assertion that one occurred. Intent must be declared
  separately (`--require-terminal`) or the permissive reading wins silently.
- **A guard that trusts the checker it guards is decoration.** `classify()` now
  keys only on `terminal_observed`, and a healthy-but-terminal-less run gets its
  own outcome (`no_terminal`) instead of being laundered into `terminal` or
  retried pointlessly.
- **Name what a metric measures, then ask what it therefore cannot see.**
  `illegal_action_rate` was honest about mask compliance and silent about engine
  acceptance. Nobody lied; the name just invited the wrong inference.
- **Two-point sampling cannot observe a trajectory.** If start and end look
  identical for two opposite causes, the measurement has no opinion — and will
  state one anyway.
- **A negative control must fail on the criterion under test.** Replaying the
  real 20260810-stage6-terminal-3 report through the new helper yields
  `terminal_not_observed:evidence_unreachable:partial_faction:...`, exactly the
  criterion; with `require_terminal=False` it stays clean, proving Stage 5 and
  `train_eval_loop` (which sets `--stop-on-terminal` by default) do not go red.

Tests: 279 passed, 14 skipped, 23 subtests (up from 266). Stage 10 stays
`blocked`. The blocker changed class from `scheduling` to
`mission-terminal-unreachable`, and for the first time it is checkable without
a live API.

## G19 — The Player Who Owned Nothing

The round-5 verdict said the terminal was unreachable and blamed the census
verdict `partial_faction`. That was the right conclusion for the wrong reason.
This round found the reason, and it needed no live slot at all.

**The falsified hypothesis first.** EVAL-019 supposed that
`bridge_prevent_defeat_p1=1` suppressed the mission's defeat trigger. It does
not. The key is written at `LibMapModBridge.galaxy:109` and `:123` as a pure
debug-bank readout meaning "P1 already owns a PreventDefeat-tagged unit, or its
starting structure, so do not create a second one". The map never reads it. Its
only reader is our own launcher overlay, `initialization-gate.galaxy:74`, which
treats it as *evidence that P1 has a base*. A diagnostic was mistaken for a
control because its name reads like one.

**What the read actually turned up.** Chasing that key led into the overlay's
initialization gate, where lines 111-115 do this:

```galaxy
if (gf_CmreOnDemandInitializationReady()) {
    libMapModBridge_gf_WriteDebugBank("initialization_building_ready_p1", 1);
    libMapModBridge_gf_WriteDebugBank("initialization_building_ready_p2", 1);
    libMapModBridge_gf_WriteDebugBank("initialization_units_ready_p1", 1);
    libMapModBridge_gf_WriteDebugBank("initialization_units_ready_p2", 1);
    libMapModBridge_gf_WriteDebugBank("initialization_complete", 1);
```

Five markers, one boolean. They are not five observations; they are five
restatements. And the boolean they restate skips the checks they claim to
report (gate lines 63-92):

```galaxy
lv_createP1 = gf_CmreOnDemandProfileInt("CreateStartingUnitsP1");  // 0 if absent
lv_ensureP1 = gf_CmreOnDemandProfileInt("EnsurePreventDefeatP1");  // 0 if absent
if ((lv_ensureP1 != 0) && (!lv_buildingP1)) { return false; }      // skipped
lv_unitsP1 = true;
if (lv_createP1 != 0) { lv_unitsP1 = (...); }                      // skipped
```

`grep -r "CreateStartingUnitsP1\|EnsurePreventDefeatP1" src/projects/cmre-rl-training`
returns nothing. The RL harness has never set either key, so both branches have
always been dead, so the gate has always returned ready without looking at P1.

**The two witnesses disagree, and one of them is ours.** Attempt 3's own report
carries both statements:

| source | claim about player 1 |
| --- | --- |
| Galaxy `initialization_bank.keys` | `building_ready_p1=1`, `units_ready_p1=1`, `initialization_complete=1` |
| SC2 API `runtime_census.initial` | `own_unit_count=0`, `minerals=0`, `supply_cap=0` |

`player_id` is 1 in that report, so this is not a slot mismatch. The 512-step
run that Stage 5 accepted starts exactly as empty. Every downstream symptom
falls out of this one fact: 3485 `NotSupported` + 2450 `Error` against 50
successes (EVAL-018) is what commanding a nonexistent faction looks like; no
production means no objective progress, so no victory; no owned PreventDefeat
unit means nothing for `MapScript.galaxy:7149` to find dead, so no defeat. The
run could not have terminated. It was never playing.

**The fix uses the witness that is not ours.** Galaxy markers cannot police
Galaxy initialisation. `run_live_rl.faction_precondition_failures` reads the
API's first observation instead and refuses the rollout when P1 has no units or
no supply, gated behind `--require-faction` (implied by `--require-terminal`, so
Stage 5 and `train_eval_loop` are untouched). It aborts *before* `collect_rollout`,
which matters in wall-clock: attempts 1-3 each burned ~20 minutes of an
exclusive real-machine slot to learn something observable at step 0.
`stage6_guarded.classify()` now returns `no_faction` and stops retrying, because
relaunching does not add a base to a launch profile.

Rules this round earned:

- **A diagnostic named like a control will be read as a control.** `prevent_defeat`
  described the condition being recorded, not an action being taken.
- **Count the booleans, not the markers.** Five green keys written in one
  unconditional block are one green key. If two markers can never disagree,
  there is one fact.
- **A check guarded by config that nobody sets is dead code that reports
  success.** The dangerous form of fail-open is not a wrong comparison, it is a
  branch that never runs while its marker still fires.
- **When two subsystems both report on the same fact, prefer the one that is not
  the subsystem under test.** The SC2 API had the answer in `runtime_census`
  from the first attempt; we kept asking the map whether the map was ready.
- **Fail closed early, not just correctly.** A gate that only fires after the
  rollout is a verdict; a gate that fires at step 0 is a refund.

Tests: 284 passed, 14 skipped, 25 subtests (up from 279). Ledger: issues 20
(EVAL-019 resolved/falsified, EVAL-020 opened critical), result 43/29/36. Stage
10 stays `blocked`; blocker class moves from `mission-terminal-unreachable` to
`empty-faction-at-rollout-start`. It remains checkable without a live API, and
it is now actionable: give the launch profile a commander base.

## G20 — Declared Max Level Was Not The Launched Level

The commander requirement was still only declared in the launcher profile.
That is why the user could see Raynor treated as level 7 even after the runner
said commander_level=15: the approved launcher was not writing
Player|N|CommanderLevel unconditionally, so the runtime customization path
could fall back to the saved profile value. CMUIX_LaunchProfileApplyCommanderCustomization
reads Player|N|CommanderLevel from the launch-profile bank, and the new launcher
default now writes it explicitly for both players together with the full six-slot
mastery defaults.

What changed: tools/launchers/launch-cmre-alenger.ps1 now writes
ProfileConfigLocked=1, CustomizationSaved=1, CommanderLevel=15, and the six-slot
mastery profile before the optional buff patch branch. The ML runner also
fail-closes declared-full runs whose mastery layout is not actually full, so the
config can no longer drift from the launch profile without being named.

Evidence: static launcher test coverage now pins the bank writes, the runtime
gate blocks partial layouts before SC2 starts, the dry-run plan shows
--commander-level 15 plus full mastery defaults, and the preflight report records
the fail-closed layout rejection. No fresh live SC2 run was launched in this turn
because an existing SC2_x64 session was still active on the machine, so runtime
readback of the in-game commander UI remains open in EVAL-010.

## G21 — Launch-Profile Evidence Must Be Fresh, And The Runner Must Use pwsh

The new commander bank reader found a second failure mode before it could
promote runtime proof. The first live smoke at port 6012 started the approved
launcher but failed before API readiness with approved_launcher_exited:4294967295.
Its report captured the only available CMCoopLaunchProfile bank as an old
TerranAlenger3 profile. The bank was older than the run start, was marked
fresh=false, and was deliberately not selected; commander_runtime_proven stayed
false. A stale bank is now evidence of a missing write, never evidence that the
current launch used a max-level Raynor.

The direct preflight showed the launcher itself can stage the map and write a
level-15 / six-times-30 Raynor profile. The difference was its host: the runner
hard-coded Windows PowerShell 5.1 while the working launcher surface on this
machine is pwsh 7. run_live_rl now prefers pwsh when present, falls back to
powershell only when pwsh is unavailable, and snapshots fresh
CMCoopLaunchProfile.SC2Bank copies into the run artifact. The SC2Bank parser
turns a fresh player-1 CommanderLevel plus MasteryLevel=180 and six 30-point
slots into bank evidence; a lower level or partial layout overrides the CLI
declaration and blocks the commander gate.

Validation: PowerShell parser passed, commander profile tests passed 15/15,
commander gate tests passed 12/12, and the full cmre-rl-training suite passed
297 with 14 skipped and 28 subtests. A post-fix live retry was not started:
the real-machine owner was an external pwsh TerranAlenger3 launcher (PID 47212)
with SC2_x64 PID 35652. It was not terminated or modified. Consequently,
EVAL-010 remains open until a fresh live bank is captured, and EVAL-022 records
the shell fix as contained rather than runtime-verified.

## G22 — Fresh Raynor Commander Bank Evidence (Runtime)

Once the external owner released the real-machine slot, the post-fix smoke ran
through the approved launcher on port 6015. It passed API readiness,
CreateGame, JoinGame, frame advancement and action-result gates, with no
same-window ScriptError. The run is intentionally only eight steps and claims
no mission terminal or victory.

The relevant proof is in the captured fresh CMCoopLaunchProfile bank, not the
CLI arguments: player 1 is TerranRaynor, CommanderLevel=15, MasteryLevel=180,
MasteryCount=6, and all six Mastery|slot|Value entries are 30. The runner
records commander_runtime_proven=true and commander_evidence_source=bank only
after the bank modification timestamp is inside the run window. The copied bank
is retained under the run artifact, so a later launch cannot overwrite this
evidence.

Evidence:

- artifacts/stage-10-runtime-policy-eval/20260810-commander-bank-runtime-pwsh/live-rl-report.json
- artifacts/stage-10-runtime-policy-eval/20260810-commander-bank-runtime-pwsh/launcher.log
- artifacts/stage-10-runtime-policy-eval/20260810-commander-bank-runtime-pwsh/banks/CMCoopLaunchProfile.SC2Bank

This resolves EVAL-010 and EVAL-022. Stage 10 itself remains blocked by
EVAL-002: no player_result has been observed, and an eight-step bridge smoke is
not a mission-completion result.

## G23 - Terminal Intent Was Blocked By The Existing Runtime Owner

The first terminal-intent run using the approved launcher after the commander
bank fix was attempted with `--stop-on-terminal --require-terminal`
(`2048` decisions, `step_mul=32`, replay capture enabled). It did not reach
SC2 API readiness: the launcher exited with `SC2_RUNTIME_BUSY` because the
existing external owner still held the real-machine slot (`SC2_x64` PID
`13672`, lease session `cmre_alenger-20260810-194501-f752e341`, state
`detached`). The run is therefore a truthful blocked runtime result, not a
policy failure and not a terminal result.

Evidence:

- `artifacts/stage-10-runtime-policy-eval/20260810-terminal-bankproof-2048x32/live-rl-report.json`
- `artifacts/stage-10-runtime-policy-eval/20260810-terminal-bankproof-2048x32/launcher.log`
- `artifacts/stage-10-runtime-policy-eval/20260810-terminal-bankproof-2048x32/launcher.err.log`

The report confirms `launcher_started=true` but `api_ready=false`,
`create_game=false`, `join_game=false`, `frame_advancement=false`, and no
actions. The only launch-profile bank was stale TerranAlenger3 evidence and
was correctly excluded from `commander_runtime_proven`.

## G24 - Economy-Capable Offline Training And Hash-Complete Plans

The train/eval loop now exposes `--train-step-loops` and starting resources,
records them in `training-report.json`, and rewrites the eval plan after the
checkpoint exists so `checkpoint_sha256` is final rather than `pending`.
It also persists the complete cycle as `train-eval-report.json`, including
truthful `trained_only` or blocked states. Targeted regression coverage is
`14 passed`.

Two simulator-only runs were completed from the previous checkpoint:

- `20260810-step8-curriculum`: `24 x 128 = 3072` steps,
  `step_loops=8`, reward `0.1008463542`, entropy `2.3538448`,
  `distinct_actions_used=12`, illegal rate `0.0`, checkpoint SHA-256
  `75765e240bdc2c444812b35e83f3927fcd652b3208e0341ff29b069de0c90bb4`.
- `20260810-economy-curriculum`: `8 x 64 = 512` steps,
  `step_loops=64`, `start_minerals=200`, reward `0.109375`,
  entropy `2.4366235`, `distinct_actions_used=12`, illegal rate `0.0`,
  checkpoint SHA-256
  `45f8f1071548b1226e022f7e37420e9ee1f1027c29f0ed7ce57cd65eded8abeb`.

The persistence path was exercised end-to-end by
`20260810-cycle-report-smoke`: `64` simulator steps at `step_loops=64` and
`start_minerals=200` produced a `trained_only` cycle report whose recorded
checkpoint hash matches the final plan hash
(`1d8923319943e20249692fbae33a168abde9c798fdf5ca5d412d335a207eb0ab`).
Evidence: `artifacts/stage-10-runtime-policy-eval/20260810-cycle-report-smoke/train-eval/train-eval-report.json`.

These are simulator evidence only. The small reward delta does not establish
live tactical improvement or a mission win; EVAL-002 remains blocked until a
fresh long-horizon live run records an actual `player_result`.

## G25 - Commander Identity Is A Separate Runtime Gate

The next terminal-intent launch acquired the approved launcher lease on port
6018 and passed the real WebSocket Ping. Its controller did not produce a
`live-rl-report.json` before the API listener disappeared, so it has no
CreateGame, JoinGame, faction, action, replay, or terminal evidence. A later
`--skip-launch` diagnostic on that port correctly timed out rather than treating
the prior TCP listener as a live API.

That diagnostic exposed a separate fail-open condition in the commander gate:
a fresh `CMCoopLaunchProfile.SC2Bank` can report a different commander with
level 15 and six full mastery slots. The former parser replaced the requested
identity with the observed one before validation, so `TerranRaynor` requested
with observed `TerranAlenger3` could pass. The runner now keeps the requested
identity immutable and reports the bank identity separately; any mismatch is a
gate failure. The post-interruption bank is diagnostic only: another session
may have written it, so it proves neither commander's state for the interrupted
run.

Validation:

- `python -m pytest src/projects/cmre-rl-training/tests/test_commander_profile.py src/projects/cmre-rl-training/tests/test_commander_gate_fail_closed.py -q` -> `28 passed, 7 subtests passed`.
- `python -m pytest src/projects/cmre-rl-training/tests -q` -> `302 passed, 14 skipped, 28 subtests passed`.
- The captured bank was passed through the actual validation function after the
  fix: requested `TerranRaynor`, observed `TerranAlenger3`,
  `identity_ok=false`, `passed=false`.

Evidence:

- `artifacts/stage-10-runtime-policy-eval/20260810-terminal-economy-curriculum-after-init-fix-2048x32/launcher.log`
- `artifacts/stage-10-runtime-policy-eval/20260810-init-after-join-smoke/live-rl-report.json`

Stage 10 remains blocked. At the next free runtime slot, start a new approved
launcher session rather than attaching to a prior one, require a fresh bank
that names `TerranRaynor`, then require the initialized-faction, action,
ScriptError, replay, and `player_result` gates.
