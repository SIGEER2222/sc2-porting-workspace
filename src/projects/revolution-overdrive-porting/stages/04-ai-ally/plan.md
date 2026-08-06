# Stage 04 Plan: Mission-Safe AI Ally Adapter

## Objective

Improve the current AI ally workflow for Revolution Overdrive without replacing mission-owned
alliance/AI setup. Extract a deterministic per-map ally roster contract, validate it against the
owned source maps, and prove the adapter issues only legal cooperative observations/actions.

## Inputs

- Stage 03 owned maps and commander package.
- Stage 01 AI ally discovery, which found 29 maps with explicit alliance setup and no map-owned
  generic `AIStart`/`AIMeleeStart` call.
- Current project-owned CMRE AI ally simulator contracts, used read-only as the proven behavioral
  reference unless an isolated compatibility adapter needs no shared change.

## Write scope

- `src/projects/revolution-overdrive-porting/project.json`
- `src/projects/revolution-overdrive-porting/stages/04-ai-ally/**`
- `artifacts/projects/revolution-overdrive-porting/stage04-ai-ally/**`
- `src/projects/revolution-overdrive-porting/vibe/**`
- `tools/cmre-webui/server.py`
- `tools/cmre-webui/webui/app.js`
- `tools/cmre-webui/test_revolution_overdrive.py`

## Tasks

1. Run read-only regressions against the current AI ally system and record its existing coverage,
   failures, and contract boundaries without overwriting active CMRE work.
2. Parse owned map scripts into a roster manifest: explicit alliance calls, player groups, possible
   ally/enemy owners, and whether a map is an ordinary mission, lobby, or story transition.
3. Implement a Revolution Overdrive adapter that exposes only mission-derived roster information
   to the AI ally layer. It must reject neutral/enemy targets and must not call generic melee AI.
4. Add deterministic tests for roster extraction, incomplete/ambiguous maps, command authorization,
   visible-allies-only targeting, and preservation of map-owned alliances.
5. Add an optional WebUI launch profile indicator only if it conveys package/mission compatibility;
   it must not imply a live runtime pass.
6. Write simulator/static evidence, self-assessment, result, issues, and a Stage 05 runtime plan
   only after the adapter tests pass.

## Validation

- Targeted current-AI regression tests run before and after adapter work.
- Deterministic owned-map roster extraction tests cover all 31 maps.
- Adapter tests prove no `AIStart`/`AIMeleeStart` injection and no non-ally target action.
- `python -m unittest tools/cmre-webui/test_revolution_overdrive.py -v`
- `node tools/utils/workspace.mjs validate`

## Stop conditions

- Complete only when the adapter is deterministic, all roster/static tests pass, and map alliances
  remain unchanged.
- Live runtime remains blocked until the declared campaign dependency is installed; record that
  separately rather than downgrading static/simulator evidence into a runtime claim.
