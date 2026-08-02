# Stage 25 Plan: AI Ally Capability Completion

## Objective

Turn the current single-controller "AI ally" slice into a real cooperative
ally model. The simulator must represent a human/leader player and a distinct
AI-controlled ally on the same team; the policy must observe and coordinate
with allied units without seeing hidden world state; the approved SC2 runtime
must prove the same team identity and at least one resulting cooperative
state transition.

Stage 24 is the verified baseline. This stage is a follow-up capability stage,
not a correction to the completed structure-clearance acceptance.

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
  not ally identity or cooperative command behavior.

## Scope and boundaries

### In scope

1. Define a project-owned cooperative roster contract for leader P1, AI ally
   P2, and enemy players. The simulator roster must validate reciprocal
   alliances, reject asymmetric or unknown ally IDs, and record an explicit
   `ally_joined`/roster-ready transition in the report.
2. Extend the observation contract with `visible_allies` and an alliance
   summary containing player ID, unit counts, base/leader position, and alive
   state. Keep hidden entities inaccessible to policy code.
3. Upgrade `AllyPolicy` into a bounded state machine with explicit modes:
   `follow`, `regroup`, `defend_base`, `assist_attack`, and `retreat`.
   Priority must be deterministic: self-preservation and base defense first,
   explicit leader/objective assistance second, regroup/follow third, hold
   last.
4. Extend the action adapter only through existing typed simulator/runtime
   boundaries. Commands must be attributed to P2, obey per-unit rate limits,
   tolerate stale targets, and never issue attacks against P1 or other allies.
5. Add a Dead of Night cooperative scenario that keeps mission-owned P1
   initialization intact, gives P2 an AI ally roster entry and controlled
   starting force, and retains P3/P4/P5 as enemies. Do not modify the source
   map or canonical commander behavior.
6. Add simulator evidence for ally visibility, same-team targeting rejection,
   assist/follow/defend transitions, reinforcement and ally-loss recovery,
   deterministic multi-seed behavior, and command/error accounting.
7. Add one bounded runtime probe through `tools/launchers/` that observes raw
   alliance values and owner IDs, confirms P2 is allied to P1 and hostile to
   the declared enemy set, issues a typed cooperative action, observes a
   resulting state change, and checks the same-window ScriptError verdict.

### Out of scope

- Editing registered source maps, canonical commander mods, or external
  repositories.
- Dynamic diplomacy or arbitrary in-game alliance mutation. Team membership is
  established by the scenario/map roster and verified at runtime.
- Full autonomous economy, production optimization, or all commander-specific
  abilities. Add those only as separate capability stages after this contract
  is stable.
- Reusing simulator victory as runtime evidence.

## Implementation steps

1. Add the cooperative roster and alliance invariants in the project-owned
   simulator path. Prefer the existing `ScenarioPlayer.allies` and
   `PlayerRegistry` primitives; add only the smallest validator/report fields
   required by two consumers (simulator policy and runtime probe).
2. Extend `Observation` and its tests with ally views while preserving all
   existing consumers and the hidden-state guard. Add a stable `team_id` or
   equivalent derived roster identity only if the current owner/allies fields
   cannot express the contract without duplication.
3. Refactor `AllyPolicy`/`ActionAdapter` around the explicit mode state machine,
   P2 issuer ownership, ally-safe target filtering, bounded retries, and
   decision traces that record mode transitions and reasons.
4. Build the project-owned cooperative Dead of Night simulator scenario and
   stage25 focused tests. Keep Stage 19/20 clearance tests and Stage 23 typed
   combat tests in the regression set.
5. Run simulator-first validation across at least seeds 42, 7, and 99. Require
   roster-ready evidence, no friendly-fire commands, nonzero ally assist/follow
   transitions, truthful error accounting, and deterministic report hashes or
   an explicitly documented allowed variance.
6. Run the bounded runtime probe through the approved launcher after the
   simulator contract passes. Capture CreateGame/JoinGame, raw alliance
   observations, P1/P2 owner counts, typed action correlation, frame advance,
   resulting state delta, and same-window ScriptError evidence.
7. Record `result.json`, `log.md`, and `issues.json`; promote `currentStage`
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

No file in `reference/`, registered source maps, canonical commander packages,
or external repositories may be modified.

## Acceptance criteria

1. A simulator scenario contains P1 and P2 with reciprocal alliance entries;
   P2 is `is_ai=true`, P1/P2 are not enemies in either direction, and P3/P4/P5
   remain hostile. An asymmetric/unknown roster fails before simulation.
2. The policy receives allied units through `Observation.visible_allies`,
   never accesses `world.entities`, and emits a trace showing at least three
   distinct valid modes across the scenario: follow/regroup, defend/assist,
   and retreat or hold.
3. No issued or dispatched action targets an allied unit; all P2 commands are
   owner-valid, per-unit rate-limited, correlated, and accounted for when a
   unit or target becomes stale.
4. Seeds 42, 7, and 99 pass the focused simulator scenario with roster-ready
   evidence, no friendly-fire result, nonzero cooperative action evidence, and
   no deadlock, oscillation, or command-storm safety failure.
5. Existing Stage 19/20 simulator tests, Stage 22/23 typed combat tests, and
   launcher/kernel static validation remain green.
6. A fresh approved-launcher runtime window observes the native P1/P2 team
   relationship, advances frames, receives at least one successful typed P2
   action result, records a resulting observable state delta, and reports zero
   new ScriptErrors in that same window. A blocked runtime remains BLOCKED,
   never PASS.
7. Stage artifacts contain repo-relative evidence paths, valid JSON schemas,
   explicit evidence classifications, and no claim that simulator success is
   runtime success.

## Verification commands

### Static and simulator

```text
python -m pytest -q src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py
python -m pytest -q src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py src/projects/cmre-porting/stages/20-simulator-ai-ally-adversarial-hardening/test_adversarial_hardening.py src/projects/cmre-porting/stages/19-simulator-ai-ally-clearance/test_simulator_ai_ally_clearance.py
python -m py_compile src/projects/cmre-porting/vibe/contracts.py src/projects/cmre-porting/vibe/consumers/ally_ai.py src/projects/cmre-porting/vibe/run_dead_of_night.py src/projects/cmre-porting/stages/25-ai-ally-capability-completion/test_ai_ally_capability.py
powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1
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
- Project-owned cooperative simulator scenario and focused regression tests.
- Runtime recipe and evidence bundle proving native P1/P2 team identity and a
  typed cooperative action, or a truthful blocked record with next action.
- Updated project handoff only after all evidence and validation gates agree.
