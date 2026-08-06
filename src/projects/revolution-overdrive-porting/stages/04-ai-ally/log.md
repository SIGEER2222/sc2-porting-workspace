# Stage 04 Log

## Progress

- Read the Stage 01 AI ally discovery and audited the existing CMRE ally contract before making
  changes. The existing contract already enforces reciprocal roster validation, visible-allies-only
  observations, P2 command ownership, and friendly-fire blocking.
- Added a project-local read-only Galaxy parser and contract builder under `vibe/ai_ally.py`.
- Added deterministic tests for all 31 owned maps, explicit mission edges, entry-flow fail-closed
  behavior, target rejection, source preservation, and low-level alliance/player-group evidence.

## Evidence

- `static`: `evidence/static/map-roster-manifest.json` records all 31 map rosters, 29 mission maps,
  two entry-flow maps, zero generic AI-start calls, and unchanged source hashes.
- `static`: `evidence/static/contract-samples.json` records valid P1/P2 contracts for
  `thanson01.SC2Map` and `tzeratul04.SC2Map`, plus rejected contracts for `tarcade.SC2Map` and
  `tstory01.SC2Map`.
- `static`: `python -m unittest ...test_ai_ally_adapter.py -v` passed 5 tests.
- `simulator`: the targeted current CMRE ally capability regression passed 5 tests; the runtime
  matrix passed 9 tests.
- `static`: the existing WebUI Revolution Overdrive MVP passed 2 tests and still reaches the
  approved launcher staging path.
- `blocked`: native runtime remains blocked by the missing Void Campaign dependency from
  `RO-PKG-001`.

## Changes

- `src/projects/revolution-overdrive-porting/vibe/__init__.py`: exports the project-local adapter.
- `src/projects/revolution-overdrive-porting/vibe/ai_ally.py`: parses literal player aliases,
  alliance calls, low-level alliance channels, player groups, and generic AI-start calls; builds
  a mission-derived fail-closed ally contract.
- `src/projects/revolution-overdrive-porting/stages/04-ai-ally/test_ai_ally_adapter.py`: added
  deterministic adapter coverage.
- `src/projects/revolution-overdrive-porting/stages/04-ai-ally/evidence/static/**`: generated
  roster and contract evidence.

## Problems

- `RO-PKG-001` remains blocked: the local SC2 installation lacks `Campaigns/Void.SC2Campaign`.
- `RO-AI-001`: 24 maps contain at least one alliance call whose player expression is dynamic or
  otherwise unresolved. The adapter deliberately excludes those edges from authorization.
- `RO-AI-002`: the full Stage 25 capability suite exceeded the bounded 60-second command window;
  targeted ally tests and the runtime matrix passed.

## Handoff

Stage 05 must install or otherwise provide the declared official campaign dependency, then use
the approved Revolution Overdrive launcher with a runtime listener, heartbeat, faction-state
assertion, and same-window ScriptError scan. Static and simulator evidence must not be promoted to
native runtime evidence.
