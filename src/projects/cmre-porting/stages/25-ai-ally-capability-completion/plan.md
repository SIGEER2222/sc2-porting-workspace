# Stage 25 Plan: AI Ally Capability Completion

## Objective

Turn the existing Vibe control surface into a truthful native task-strategy
slice. The runtime must support explicit typed function invocation for
diagnosis, while the strategy path must observe a native opening, gather real
resources, train real units, issue real movement/combat commands, and verify
state transitions without injecting units or resources.

The runtime debug path also includes a bounded external Debug VM. Debug
programs are hot-loaded JSON instructions executed through the typed registry;
they may query the complete function catalog but may call only explicit runtime
adapters. A running SC2 session must be reusable across many debug programs.

The cooperative ally model remains in scope: the simulator and runtime must
represent a leader and a distinct AI-controlled ally, expose only visible
allied state, and prevent friendly-fire commands. Stage 24 remains the
historical baseline, but its injected-attacker structure clearance is not
accepted as evidence of native task strategy.

### Runtime topology decision (2026-08-03)

The native runtime acceptance path uses one SC2 client and the map's built-in
Computer player:

- P1 is the only `Participant` and the API client joins as P1.
- P2 is a `Computer` Terran slot with configured difficulty; the map's native
  `AIMeleeStart(2)` path owns P2 economy, production, movement, and combat.
- P1 commands reach P2 through the existing `!ally` chat trigger. The Galaxy
  bridge validates the reciprocal alliance, issues only P2-owned orders, writes
  an acknowledgement to the ally Bank, and emits a player-visible signal.
- The old two-Participant probe remains historical blocked evidence. It is not
  a prerequisite for this topology and must not be retried as the acceptance
  path.

### Priority override

`function.invoke` is a first-class runtime debugging contract. Debug-only
functions remain explicit, typed, and auditable, but `unit.spawn`,
`player.set_resource`, and `unit.kill` are prohibited in the native strategy
acceptance path. A strategy run containing any of those operations is a FAIL,
even if the mission objectives are cleared.

## Current gap and evidence

- `src/projects/cmre-porting/vibe/map_extractor.py` currently emits empty
  `allies` lists and marks the extracted players as AI. The `team` labels in
  `PLAYER_FACTIONS` are metadata, not simulator alliance semantics.
- `src/projects/cmre-porting/vibe/consumers/ally_ai.py` runs one AI-controlled
  player against an enemy. Its scenarios do not contain a reciprocal ally
  roster, and its policy only receives own units plus visible enemies.
- `src/projects/cmre-porting/vibe/contracts.py` exposes no ally-unit view or
  alliance summary. The policy therefore cannot distinguish an allied player
  from an enemy by an explicit contract.
- `reference/sc2-ally-bot/src/sc2_simulator/world/player.py` already provides
  the needed primitive: alliances are explicit player IDs, and the relation
  must be represented in both directions. The reference repository remains
  read-only; reuse the contract, not its files.
- Existing Stage 19/20 clearance proves deterministic P1 control and target
  allocation, but not a distinct AI ally joining a human team. Existing Stage
  23 runtime evidence proves typed combat and native-state preservation, but
  not ally identity or cooperative command behavior. It also explicitly uses
  `vibe.unit.spawn` for the initial attacker set and reinforcements, so it is
  not native-economy evidence.

## Scope and boundaries

### In scope

1. Discover all Galaxy function declarations in the registered CMRE package and
   owned packages into a source-relative catalog. Record signatures, effects,
   trigger/initializer classification, and whether an explicit adapter exists.
2. Define the runtime debug contract for `function.invoke`: explicit function
   IDs, typed arguments, request/response correlation, state versions, and
   structured rejection of unknown functions or invalid arguments. Keep this
   separate from strategy-side action accounting.
3. Implement the bounded Debug VM with `call`, `step`, `assert`, `set`,
   `repeat`, and `catalog.search`. Enforce instruction budgets, typed registry
   checks, and strategy-mode rejection of debug-only functions.
4. Add the smallest typed native action/query surface needed by the MVP:
   resource/unit observation, gather, train, move, attack, and mission state.
   The simulator, Host, registry, and Galaxy mirror must agree on names and
   argument types. Do not add arbitrary Galaxy reflection.
5. Define a strategy audit that records every operation family and rejects
   debug injection (`spawn`, resource mutation, forced kill, or equivalent)
   during native strategy runs.
6. Define a project-owned cooperative roster contract for leader P1, AI ally
   P2, and enemy players. The simulator roster must validate reciprocal
   alliances, reject asymmetric or unknown ally IDs, and record an explicit
   `ally_joined`/roster-ready transition in the report.
7. Extend the observation contract with `visible_allies` and an alliance
   summary containing player ID, unit counts, base/leader position, and alive
   state. Keep hidden entities inaccessible to policy code.
8. Upgrade `AllyPolicy` into a bounded state machine with explicit modes:
   `follow`, `regroup`, `defend_base`, `assist_attack`, and `retreat`.
   Priority must be deterministic: self-preservation and base defense first,
   explicit leader/objective assistance second, regroup/follow third, hold
   last.
9. Extend the action adapter only through existing typed simulator/runtime
   boundaries. Commands must be attributed to P2, obey per-unit rate limits,
   tolerate stale targets, and never issue attacks against P1 or other allies.
10. Add a Dead of Night native-task scenario that keeps mission-owned P1
   initialization intact, starts from the observed native economy, and records
   gather/train/move/attack deltas. Add the cooperative roster to the same
   scenario only where the live map exposes the required team identity.
11. Add a Dead of Night cooperative scenario that keeps mission-owned P1
   initialization intact, gives P2 an AI ally roster entry and controlled
   starting force, and retains P3/P4/P5 as enemies. Do not modify the source
   map or canonical commander behavior.
12. Add simulator evidence for native task transitions, debug-operation
   rejection, ally visibility, same-team targeting rejection,
   assist/follow/defend transitions, reinforcement and ally-loss recovery,
   deterministic multi-seed behavior, and command/error accounting.
13. Add one bounded runtime probe through `tools/launchers/` that first calls
   a safe registered debug/query function, then observes raw
   alliance values and owner IDs, confirms P2 is allied to P1 and hostile to
   the declared enemy set, runs native gather/train/move/attack actions without
   injection, observes resulting state changes, and checks the same-window
   ScriptError verdict.

### Out of scope

- Editing registered source maps, canonical commander mods, or external
  repositories.
- Dynamic diplomacy or arbitrary in-game alliance mutation. Team membership is
  established by the scenario/map roster and verified at runtime.
- Full economy optimization, commander-specific ability coverage, and
  multi-map strategy generalization. This stage proves only the bounded native
  task loop and its debug boundary.
- Reusing simulator victory as runtime evidence.

## Implementation steps

1. Run the AST catalog discovery and review the inventory-only versus
   callable-adapter split.
2. Add the explicit function metadata and strategy/debug capability labels;
   keep the implementation map explicit in Python and Galaxy.
3. Implement and unit-test the Debug VM against a fake bridge, then expose it
   through the existing REPL without adding a second transport.
4. Add the typed native action/query path in the simulator and Host. For the
   live map, reuse the existing raw SC2 action adapter where it is the native
   transport, but record equivalent typed action names and pre/post state.
5. Add the strategy audit and no-injection assertions before changing policy
   behavior.
6. Add the cooperative roster and alliance invariants in the project-owned
   simulator path. Prefer the existing `ScenarioPlayer.allies` and
   `PlayerRegistry` primitives; add only the smallest validator/report fields
   required by two consumers (simulator policy and runtime probe).
7. Extend `Observation` and its tests with ally views while preserving all
   existing consumers and the hidden-state guard. Add a stable `team_id` or
   equivalent derived roster identity only if the current owner/allies fields
   cannot express the contract without duplication.
8. Refactor `AllyPolicy`/`ActionAdapter` around the explicit mode state machine,
   P2 issuer ownership, ally-safe target filtering, bounded retries, and
   decision traces that record mode transitions and reasons.
9. Build the project-owned native-task and cooperative Dead of Night simulator
   scenarios and Stage 25 focused tests. Keep debug injection tests in a
   separate test class and never mix their evidence into native strategy.
   Keep Stage 19/20 clearance tests and Stage 23 typed combat tests in the
   regression set.
10. Run simulator-first validation across at least seeds 42, 7, and 99. Require
   native task transitions, zero debug injections, and truthful rejection
   evidence before ally-specific checks.
11. Run the complete function catalog and Debug VM smoke validation. Require
   zero parser errors, registry/catalog alignment, typed argument rejection
   before transport, and a truthful nonzero VM exit on failure.
12. Run simulator-first validation across at least seeds 42, 7, and 99. Require
   roster-ready evidence, no friendly-fire commands, nonzero ally assist/follow
   transitions, truthful error accounting, and deterministic report hashes or
   an explicitly documented allowed variance.
13. Run the bounded single-client Computer-ally runtime probe through the
   approved launcher after the simulator contract passes. Capture
   CreateGame/JoinGame, a P1 Participant plus P2 Computer roster, raw alliance
   observations, P2 owner counts, P1 chat commands, Galaxy acknowledgements,
   frame advance, an observable P2 state delta, a native `.SC2Replay`, a
   browser `full-map-player.html`, and same-window ScriptError evidence.
14. Record `result.json`, `log.md`, and `issues.json`; promote `currentStage`
   from Stage 24 only when implementation begins and keep simulator, static,
   runtime, blocked, and inference evidence separate.

## Proposed write scope

- `src/projects/cmre-porting/project.json`
- `src/projects/cmre-porting/stages/25-ai-ally-capability-completion/**`
- `src/projects/cmre-porting/vibe/contracts.py`
- `src/projects/cmre-porting/vibe/consumers/ally_ai.py`
- `src/projects/cmre-porting/vibe/run_dead_of_night.py`
- `src/projects/cmre-porting/vibe/run_dead_of_night_live.py`
- `tools/galaxy-vibe/host/vibe_host.py` only if an existing typed query needs a
  narrow ally-safe adapter adjustment
- `tools/launchers/launch-cmre-alenger.ps1` and its existing overlay/test files
  only if the runtime probe requires a launcher staging fix
- `artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/**`
- `tools/cmre-webui/**` and repository-root `DESIGN.md` for the browser runtime
  debug console, reusing the existing launcher WebUI and Vibe RPC session.

No file in `reference/`, registered source maps, canonical commander packages,
or external repositories may be modified.

## User-requested simulator completion extension

The simulator scope is extended to cover one complete ladder-style Terran game,
not only an opening or isolated tactical slice. The project-owned `LadderAI`
must use observed economy state to gather minerals/vespene, reserve resources,
maintain supply, expand, add production and tech structures, research upgrades,
train a mixed army, scout, respond to pressure waves, retreat damaged units,
focus-fire visible enemies, and terminate only after enemy elimination. This is
simulator evidence and must remain separate from native SC2 runtime evidence.

## Acceptance criteria

1. The catalog contains every discovered function with zero parser errors, and
   inventory-only entries cannot be invoked by the Debug VM.
2. The Debug VM executes a hot-loaded program containing call, state assertion,
   repeat, step, and catalog search without restarting the game session.
3. The debug runtime contract passes with a successful safe `function.invoke`,
   request/response correlation, typed validation, and rejection of unknown or
   malformed calls. The same contract reports zero ScriptErrors in fresh SC2.
4. A simulator native-task scenario starts without debug injection and proves
   at least one real gather transition, one real train transition, and one
   real move or attack transition through pre/post observations.
5. Native strategy evidence contains zero `unit.spawn`,
   `player.set_resource`, `unit.kill`, or equivalent forced-state operations;
   the negative gate fails closed if any appears.
6. A simulator scenario contains P1 and P2 with reciprocal alliance entries;
   P2 is `is_ai=true`, P1/P2 are not enemies in either direction, and P3/P4/P5
   remain hostile. An asymmetric/unknown roster fails before simulation.
7. The policy receives allied units through `Observation.visible_allies`,
   never accesses `world.entities`, and emits a trace showing at least three
   distinct valid modes across the scenario: follow/regroup, defend/assist,
   and retreat or hold.
8. No issued or dispatched action targets an allied unit; all P2 commands are
   owner-valid, per-unit rate-limited, correlated, and accounted for when a
   unit or target becomes stale.
9. Seeds 42, 7, and 99 pass the focused simulator scenario with roster-ready
   evidence, no friendly-fire result, nonzero cooperative action evidence, and
   no deadlock, oscillation, or command-storm safety failure.
10. Existing Stage 19/20 simulator tests, Stage 22/23 typed combat tests, and
   launcher/kernel static validation remain green.
11. A fresh approved-launcher runtime window observes P1 as a Participant and
   P2 as a Computer, confirms their native team relationship, advances frames,
   receives at least one P1 command, observes a P2-owned state delta or native
   AI transition, records a P2 acknowledgement, and reports zero new
   ScriptErrors in that same window. No raw P2 Participant client is required.
   A blocked runtime remains BLOCKED, never PASS.
12. Stage artifacts contain repo-relative evidence paths, valid JSON schemas,
   explicit evidence classifications, and no claim that simulator success is
   runtime success.
13. The ladder-style simulator completes a full game for seeds 42, 7, and 99,
   reaches `enemy_elimination`, leaves no enemy units alive, and proves mineral
   and gas economy, expansion, scaled production, high-tech structures,
   upgrades, mixed army production, scouting, pressure response, tactical
   attacks, and zero safety/dispatch errors.
14. The ladder simulator CLI produces a replay JSONL and a single-file
   `state-driven-player.html` by default; the HTML contains real timeline
   frames and can be opened directly with a `file:///` URL. `--no-replay` is
   available only as an explicit opt-out.

## Verification commands

### Static and simulator

```text
python -m pytest -q src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py
python -m pytest -q src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py src/projects/cmre-porting/stages/20-simulator-ai-ally-adversarial-hardening/test_adversarial_hardening.py src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/test_simulator_ai_ally_clearance.py
python -m py_compile src/projects/cmre-porting/vibe/contracts.py src/projects/cmre-porting/vibe/consumers/ally_ai.py src/projects/cmre-porting/vibe/run_dead_of_night.py src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py
powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1
PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.ladder_ai --batch --max-loops 5000 --out artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/ladder-full-game-20260802.json
PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.ladder_ai --seed 42 --max-loops 5000
```

### Runtime

Use the approved `tools/launchers/launch-cmre-alenger.ps1` launcher with a
fresh packed map and a new port. The stage runner must use `RequestStep`, not
wall-clock sleep, and must execute a same-window ScriptError check using the
actual launch epoch. The exact command and artifact paths are recorded only
after the runtime recipe exists and the simulator gate passes.

## Risks and mitigations

- Alliance fields can be asymmetric: validate both directions at scenario
  load and test friendly-fire rejection from both P1 and P2.
- Adding ally visibility can accidentally expose omniscient state: construct
  views through the existing vision layer and retain the hidden-state guard.
- A P2 action path can bypass the current P1 assumptions: make issuer/player
  ownership explicit in every action and add cross-player command tests.
- The live map may not expose a usable AI P2 slot: treat missing native
  alliance evidence as a runtime blocker and use a map adapter/staged overlay
  only if the current project scope permits it.
- State-machine additions can destabilize proven clearance behavior: keep the
  new cooperative consumer separate from the Stage 19/20 controller until the
  new tests pass, then integrate only through existing task boundaries.

## Deliverables

- Stage 25 plan, log, result, and issues records.
- AST-derived complete function catalog and repeatable discovery command.
- Bounded Debug VM implementation, smoke program, and focused tests.
- Project-owned cooperative simulator scenario and focused regression tests.
- Ladder-style full-game simulator AI and multi-seed victory evidence.
- Default simulator replay JSONL and single-file HTML player.
- Runtime recipe and evidence bundle proving native P1/P2 team identity and a
  typed cooperative action, or a truthful blocked record with next action.
- Updated project handoff only after all evidence and validation gates agree.
