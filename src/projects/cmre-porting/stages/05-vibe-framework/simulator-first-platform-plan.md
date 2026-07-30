# SC2 Simulator-First Vibe Platform Plan

## 1. Plan Status

- Status: proposed canonical direction
- Scope: headless SC2 rules platform, tool validation, Vibe development, and optional real-SC2 calibration
- Primary environment: a workstation without a local StarCraft II installation
- First integration project: `cmre-porting`
- Core principle: the simulator is the primary development and test runtime; real SC2 is an optional adapter and calibration target

This plan does not declare the existing simulator, Vibe prototype, or runtime adapters complete. It defines the target architecture, migration path, phase gates, and evidence required before any capability may be promoted.

## 2. Product Positioning

The target is not a Mod-only balance simulator. It is a deterministic, headless SC2 rules runtime that provides a common test foundation for multiple consumers:

| Consumer | Uses the platform for | Primary acceptance |
|---|---|---|
| Mod development | Catalog changes, production chains, abilities, upgrades, combat and balance | Source-to-IR traceability, A/B results, focused regressions |
| Ally AI | Observations, legal actions, fog of war, resources, objectives and command feedback | Follow/support/defend behavior, no hidden-state access, no command conflicts |
| Tactical validation | Target selection, focus fire, movement, formations, retreat and ability timing | Multi-seed win rate, exchange ratio, survival, time and resource efficiency |
| Mission and wave tooling | Regions, timers, triggers, waves, rewards and win/loss conditions | Deterministic mission progression and difficulty curves |
| Vibe development tools | Typed operations, snapshots, assertions, traces and hot/cold loops | One-command reproducible task execution without SC2 |
| External automation | Stable Catalog, Scenario, Observation, Action and Replay APIs | Adapter conformance and reproducible failures |
| Real-SC2 integration | Optional comparison against a real client on another machine | Simulator-to-SC2 differential evidence and calibration |

The platform must never claim visual equivalence with the SC2 renderer. Its visual surface is an authoritative debug view of simulated rules and state.

## 3. Target Workflow

```text
SC2 Mod / Map source
  -> dependency and static discovery
  -> Catalog / supported Galaxy extraction
  -> versioned Simulator IR
  -> capability and fidelity report
  -> scenario execution through SimulatorTransport
  -> state snapshots + trace + assertions
  -> balance sweep / AI evaluation / tactical comparison
  -> 2D state visualization and replay
  -> candidate source change
  -> cold reload and focused regression
  -> result.json evidence package
  -> optional real-SC2 differential run
```

The final local entry point is:

```powershell
.\tools\launchers\vibe.ps1 run-task `
  -Project cmre-porting `
  -Backend simulator `
  -Task <task.json>
```

Changing `-Backend simulator` to a future `-Backend sc2` must preserve the task, observation, action, assertion and result contracts.

## 4. Architecture

### 4.1 Source Inspector

Responsibilities:

- Resolve document dependencies and package ownership.
- Parse Catalog XML through schema-aware tooling.
- Trace inheritance, references and source provenance.
- Discover supported Galaxy registration and configuration patterns statically.
- Reject missing dependencies and unresolved identifiers.
- Never modify registered read-only sources.

Galaxy is not treated as an arbitrary language that can be completely interpreted. Only explicitly supported, testable patterns enter the simulator IR. Other logic is reported as unsupported.

### 4.2 Simulator IR

The versioned intermediate representation covers:

- units, structures, attributes and footprints;
- weapons, target filters and damage bonuses;
- effects, validators, behaviors and periodic execution;
- abilities, commands, cooldowns, charges and costs;
- production, construction, morphing, research and upgrades;
- requirements and technology ownership;
- map terrain, regions, blockers, pathing and vision;
- mission triggers, waves, rewards and win/loss rules.

Every imported rule carries:

- source package and source path;
- editor/catalog ID;
- resolved parent and references;
- source hash and IR schema version;
- fidelity: `exact`, `approximate`, `partial`, or `unsupported`;
- capability IDs exercised by each scenario.

Silent fallback is forbidden. Strict mode fails when a scenario uses `partial` or `unsupported` behavior unless the scenario explicitly authorizes that approximation.

### 4.3 Deterministic Simulation Runtime

The runtime owns:

- fixed game loops and deterministic event ordering;
- seeded random number generation;
- complete snapshot, clone, restore and replay;
- entity identity and lifecycle;
- economy, construction, production and research;
- movement, pathfinding, collision, vision and fog memory;
- weapons, projectiles, damage, shields, armor, death and kill attribution;
- abilities, effects, behaviors, validators and upgrades;
- orders, queues, cargo, summons, morphs and add-ons;
- triggers, regions, waves, objectives and terminal states.

Systems must consume immutable Catalog definitions and explicit world state. Runtime behavior must not be hidden in process-global mutable registries or dynamically attached fields that bypass snapshots.

### 4.4 Stable Tool Contracts

Consumers depend on contracts, not simulator internals:

| Contract | Responsibility |
|---|---|
| Catalog API | Definitions, provenance, resolved references and capabilities |
| Scenario API | Initial state, map, seed, players, recipes, triggers and assertions |
| Observation API | Player-visible state, optional omniscient test state and deltas |
| Action API | Legal commands, rejection reasons, issue loop and execution result |
| Query API | Units, players, mission, pathing, abilities and calculated values |
| Snapshot API | Create, restore, clone, hash and compare |
| Trace/Replay API | Ordered events, commands, decisions and deterministic playback |
| Capability API | Fidelity, supported rules and scenario usage coverage |

All adapters must pass the same conformance suite. A tool that works with `SimulatorTransport` must not need its own Fake SC2 implementation.

### 4.5 Vibe Host and Kernel

The Vibe Host receives a structured task, selects a backend, runs the task, evaluates evidence and may attempt at most three evidence-driven corrections.

The typed operation surface initially includes:

- `system.ping` and capability negotiation;
- `scenario.load/reset/step/run/pause`;
- `unit.spawn/kill/set_vital/order`;
- `player.set_resource`;
- `query.units/unit/player/mission/pathing/abilities`;
- `snapshot.create/restore/compare`;
- `assert.exists/not_exists/count/equals/range/eventually`;
- `balance.sweep/compare`;
- `replay.open/seek/step`.

Requests retain the existing protocol fields for session, request ID, sequence, checksum and timestamps. Duplicate requests return the original result without repeating side effects. Stale sessions, invalid ordering, unknown operations and invalid parameters are explicit errors.

`SimulatorTransport` is the mandatory first transport. Bank, SC2 API, MapCommand and input transports are optional real-SC2 adapters and cannot block local platform progress.

### 4.6 Balance Lab

The balance layer supports:

- parameter sweeps over cost, time, health, shields, armor, damage, attack period, range and cooldown;
- baseline/candidate Catalog comparison;
- multiple seeds and controlled random streams;
- resource curves, DPS, time-to-kill, survival, losses, exchange ratio and completion time;
- wave difficulty and mission completion metrics;
- sensitivity analysis and threshold detection;
- machine-readable and human-readable reports.

Every comparison binds the source hash, Catalog hash, scenario version, seed set, metric definition and simulator version. A single battle outcome is not sufficient evidence for a balance conclusion.

### 4.7 AI and Tactical Evaluation

AI receives only the configured Observation view. Omniscient world state remains available to the evaluator but is not exposed to the policy.

The platform must support:

- configurable observation and action intervals;
- simulated action latency and command rejection;
- self, ally, enemy and neutral alliances;
- fog of war and last-known positions;
- task objectives and priority changes;
- deterministic policy replays;
- per-unit command conflict detection;
- strategy A/B runs from identical snapshots and random streams.

AI evaluation includes decision quality and runtime safety. It must detect deadlocks, oscillation, command storms, hidden-state access, illegal commands and repeated no-op actions.

### 4.8 Offline Visual Observer

The primary visual tool is a 2D debug client that renders simulator state:

- unit position, footprint, range, target and path;
- projectiles, regions, blockers and vision;
- health, shields, energy, behaviors and orders;
- production, research, resources and objectives;
- play, pause, single step, speed, seek and snapshot restore;
- event timeline and selected-entity calculation details;
- baseline/candidate synchronized playback and differences.

The visual client reads the same snapshot and trace contracts used by tests. It does not maintain a second authoritative state model.

## 5. Implementation Phases

### P0 - Direction and Ownership Reset

Deliverables:

- Mark this document as the simulator-first platform direction.
- Reclassify the existing `tools/galaxy-vibe` implementation as a spike.
- Keep reusable assertion, visual diff, cold-cycle and verdict code as candidates, not canonical behavior.
- Reclassify SC2 API, Bank and launcher work as optional adapters.
- Decide repository ownership for `sc2_simulator` without copying or editing an external repository through an undeclared boundary.

Gate:

- The local critical path contains no requirement for an SC2 executable, SC2 API port, Bank, desktop screenshot or GameLogs.
- The approved write scopes and package ownership are explicit before implementation starts.

### P1 - Unified Protocol and SimulatorTransport

Deliverables:

- Shared request/response schemas.
- `SimulatorTransport` adapter.
- Capability negotiation.
- Session, ordering, checksum and idempotency enforcement.
- First local `vibe.ps1 run-task` path.

Gate:

- Twenty sequential pings succeed.
- Five duplicate request IDs cause one execution total.
- Five illegal requests cause zero state changes.
- Closed sessions reject old requests.
- Same task, Catalog, seed and simulator version produce the same result and trace hash.

### P2 - Catalog Bridge and Fidelity Accounting

Deliverables:

- Schema-aware Catalog extractor.
- Versioned Simulator IR.
- Reference closure and provenance records.
- Fidelity and unsupported-rule reports.
- First CMRE Catalog slice for `Dead of Night x TerranAlenger3`.

The first slice covers a real starting structure, worker, production ability, representative combat unit, weapon, damage chain and upgrade.

Gate:

- Every IR field traces to a source field, declared default or documented derivation.
- Missing references and unsupported fields fail strict import.
- Re-import without source changes produces an identical Catalog hash.
- No absolute workspace paths appear in committed output.

### P3 - Core Runtime Acceptance

Work closes in dependency order:

1. time, events, RNG, snapshot and replay;
2. entity lifecycle and stable identity;
3. resources, supply, construction, production and research;
4. movement, pathfinding, occupancy, collision, vision and fog;
5. weapons, shields, armor, projectiles, damage, death and attribution;
6. abilities, effects, behaviors, validators and upgrades;
7. triggers, regions, waves, objectives and terminal states;
8. cargo, summons, morphs, add-ons and race-specific mechanics.

Gate:

- Snapshot and restore preserve all state required for future execution.
- Clone and original produce identical traces under identical actions.
- Event ordering matches the declared system priority.
- IDs are unique and stable across long runs and restore.
- Strict scenarios cannot pass while using unapproved partial behavior.
- Capability coverage reports only behavior exercised at runtime.

### P4A - Mod Development Consumer

Deliverables:

- Source-to-Catalog import for the first real Mod slice.
- Production, combat and upgrade scenarios.
- Baseline/candidate balance comparison.
- Candidate patch validation workflow.

Gate:

- A real unit cost, damage or production-time change is imported and compared.
- The report shows expected mechanical changes and unrelated focused regressions remain stable.
- Unsupported source behavior is visible in the verdict.

### P4B - Ally AI Consumer

Deliverables:

- Observation and Action adapters for the ally AI.
- Follow, support, defend and objective scenarios.
- Command feedback, latency and action-error model.
- Deterministic AI decision traces.

Gate:

- The AI cannot inspect hidden world state.
- Human-force movement causes follow behavior.
- A nearby threat causes support or attack behavior.
- An objective threat overrides lower-priority follow behavior.
- One unit receives at most one accepted final command per loop.
- Ten simulated minutes complete without deadlock, oscillation or command storm.

### P4C - Tactical Validation Consumer

Deliverables:

- Tactical scenario templates.
- Strategy plug-in contract.
- Focus-fire, positioning, retreat and ability-timing metrics.
- Controlled multi-seed A/B runner.

Gate:

- Two strategies run from identical initial snapshots and random streams.
- Target filters, range, movement, collision, vision and ability availability affect decisions.
- Reports include confidence-aware multi-run metrics rather than a single win/loss.
- Every claimed improvement links to traceable events and state changes.

### P4D - Mission and Wave Consumer

Deliverables:

- Region, timer, trigger, wave, reward and terminal-condition DSL.
- Difficulty curve and mission feasibility reports.
- Survival, defense, escort, capture and custom assertion scenarios.

Gate:

- Positive and negative terminal paths are exercised.
- Reset and replay reproduce wave timing and outcomes.
- Difficulty changes are measured using declared metrics and seed sets.

### P5 - Offline WYSIWYG and Replay

Deliverables:

- 2D simulator viewer.
- Timeline, entity inspection and calculation detail views.
- Snapshot seek and deterministic replay.
- Baseline/candidate synchronized comparison.

Gate:

- Rendered entity counts and values match the authoritative snapshot.
- Seeking to a loop restores the same snapshot hash.
- Viewer interaction cannot mutate simulation state outside typed operations.
- A failed assertion opens at the relevant loop and entities.

### P6 - Hot and Cold Development Loops

Hot loop:

- manipulate the running simulation through typed operations;
- query, assert, snapshot and rewind without rebuilding sources.

Cold loop:

- detect source changes;
- run static validation and re-import the IR;
- rebuild the scenario from its recipe;
- execute focused and required regressions;
- update balance and visual evidence.

Gate:

- One source value change completes reload, A/B, assertion, visualization and verdict through one command.
- Failed imports do not replace the last valid Catalog snapshot.
- Scenario reset yields the same initial snapshot hash.

### P7 - Intent-Driven Vibe Host

Deliverables:

- Natural-language intent to versioned `task.json`.
- Hot/cold routing.
- Candidate patch generation.
- At most three evidence-driven correction attempts.
- Complete iteration history.

Gate:

- Fixed tasks correctly cover simulation operations, Mod source changes, AI evaluation, tactical comparison, invalid Catalog edits and unsatisfiable assertions.
- The Host cannot claim success without passing declared assertions and required regressions.
- Every correction states which evidence changed the next attempt.

### P8 - Multi-Consumer Conformance and Shared Extraction

Deliverables:

- Adapter conformance suite.
- Cross-consumer scenario fixtures.
- Shared packages only for behavior proven by at least two consumers.
- Compatibility and migration policy for contract versions.

Gate:

- Mod, ally AI, tactical and mission consumers pass their own acceptance suites.
- At least two consumers pass the same shared contract implementation before extraction.
- Simulator changes cannot silently break an external tool contract.

### P9 - Optional Real-SC2 Differential Calibration

Deliverables:

- Real-SC2 backend using the same task contracts.
- Remote or separately executed evidence package.
- Simulator-versus-SC2 differential report.
- Calibration fixtures and known-divergence registry.

Gate:

- Real-SC2 absence never blocks local P0-P8 work.
- Real evidence is labelled `runtime`; simulator evidence remains labelled `simulator`.
- Divergences update fidelity records and regression fixtures rather than being hidden.

## 6. Acceptance Model

### 6.1 Core Engine Acceptance

Core acceptance is consumer-independent:

- deterministic clock, event order and RNG;
- complete snapshot and restore;
- stable identities and event attribution;
- strict unsupported-rule rejection;
- deterministic replay;
- long-run state integrity;
- explicit capability usage coverage.

Passing a large test count does not replace contract-specific negative tests and independent counterexamples.

### 6.2 Rule-Domain Acceptance

Each domain is accepted independently and retains its own fidelity status:

- economy and resources;
- construction and production;
- movement, pathfinding and collision;
- vision, fog and memory;
- weapons, armor, shields and damage;
- abilities, effects, behaviors and validators;
- upgrades, technology and requirements;
- tasks, triggers, waves and terminal conditions;
- cargo, summons, morphs and add-ons.

A platform release states exactly which domains and rule variants are accepted.

### 6.3 Consumer Acceptance

Each consumer has a separate acceptance package. The simulator is not declared complete merely because one Mod scenario works. Conversely, an AI consumer can be accepted for a declared capability set without claiming complete SC2 rule coverage.

### 6.4 Evidence Classes

Technical claims use these evidence classes:

- `static`: source, dependency, schema or Catalog analysis;
- `simulator`: deterministic execution inside the headless runtime;
- `visual`: output from the offline debug viewer;
- `runtime`: optional observation from a real SC2 process;
- `inference`: a hypothesis awaiting one of the above validations.

Simulator evidence must not be relabelled as real-SC2 runtime evidence.

## 7. Required Evidence Package

Every completed task produces a named directory under `artifacts/` containing:

- `task.json`;
- source manifest and hashes;
- `catalog.snapshot.json` and Catalog hash;
- `capabilities.json` and `unsupported-rules.json`;
- scenario definition and seed set;
- initial and final snapshots;
- ordered JSONL trace;
- action and decision records where applicable;
- assertion results;
- balance or tactical comparison report where applicable;
- visual/replay manifest where applicable;
- final `result.json` with evidence classes and failure reasons.

The package must be sufficient to reproduce a failure without the original running process.

## 8. Repository and Tool Disposition

| Existing area | Planned role |
|---|---|
| `tools/sc2-ally-bot/src/sc2_simulator` | Candidate canonical engine in its own repository boundary; requires acceptance, not blind adoption |
| `src/projects/cmre-porting/vibe` | Project-local first consumer and protocol integration |
| `tools/galaxy-vibe` | Spike; mine reusable offline components after contract review |
| `tools/runtime-bridge` | Optional real-SC2 observer and adapter evidence |
| `tools/sc2api-baseline` | Optional SC2 API backend and protocol reference |
| `tools/launchers` | Single approved entry points; simulator path must not launch SC2 |
| `artifacts/galaxy-vibe` | Existing evidence area; future output should use named task/run subcategories |

No shared abstraction is extracted solely because similar code exists. At least two real consumers must demonstrate the same contract and behavior.

## 9. Immediate Execution Order

1. Approve simulator-first direction and repository ownership.
2. Audit current `sc2_simulator` behavior against P3 core gates and produce a current capability matrix.
3. Define versioned Catalog, Scenario, Observation, Action, Snapshot, Trace and Capability schemas.
4. Implement `SimulatorTransport` against the existing Vibe protocol.
5. Close one end-to-end scenario using hand-authored IR before adding import complexity.
6. Build the first real CMRE Catalog slice and compare it with the hand-authored fixture.
7. Attach the ally AI as the second consumer through public contracts only.
8. Add tactical A/B evaluation as the third consumer.
9. Add the offline 2D viewer over snapshots and traces.
10. Implement the hot/cold Vibe loops and unified `vibe.ps1` entry.
11. Add intent routing only after deterministic task execution is stable.
12. Add optional real-SC2 calibration after the local multi-consumer platform passes.

## 10. Platform Completion Gate

The simulator-first platform reaches its initial complete state only when all of the following are true:

1. A real Mod/Catalog slice completes import, simulation, balance A/B and regression.
2. An ally AI completes follow, support and defend scenarios through the public Observation/Action contracts.
3. Two tactical strategies complete controlled multi-seed comparison with traceable metrics.
4. A mission/wave scenario exercises positive and negative terminal flows.
5. Vibe Host controls all of these through the same typed operation and task contracts.
6. Offline visualization reproduces authoritative snapshots and deterministic replays.
7. Every failure can be reproduced from task, source hash, Catalog hash, snapshot, trace and seed.
8. Unsupported behavior cannot pass strict mode silently.
9. No local completion gate requires an SC2 installation.
10. Optional real-SC2 evidence, when available, is used for differential calibration and does not replace simulator evidence.

The smallest proof of the complete workflow is not only a CMRE number edit. It is one Mod change, one ally-AI behavior, one tactical comparison and one mission scenario executed through the same simulator platform and evidence pipeline.
