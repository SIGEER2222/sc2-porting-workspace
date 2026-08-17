# Stage 10 Plan: All Commander Runtime Adaptation

## Objective

Expose every WebUI-selectable commander on every supported Revolution Overdrive map through a
Git-managed runtime patch manifest. The launcher must stage only the selected dependency closure,
write the patch only into the staged `MapScript.galaxy`, and fail closed if a map, commander,
dependency, or target Catalog cannot be resolved.

## Scope

- 50 selectable commanders: 18 official, 12 Alenger, 15 Reborn, and 5 native Revolution Overdrive.
- 31 registered maps: 30 supported campaign maps and `tarcade.SC2Map` as an explicit unsupported
  entry-flow target.
- `亡者之夜.SC2Map` is never an input to this stage and is rejected by the patch policy.
- Canonical commander Mods and source maps remain read-only. Only SC2 staging copies are changed.

## Execution

1. Generate and validate `vibe/commander_map_patches.json` and the 31 x 50 matrix.
2. Route all Revolution Overdrive map selections through `launch-revolution-overdrive.ps1 -Commander`.
3. Stage only the selected patch dependencies, add them to the staged map dependency list, validate
   every required target Catalog, and inject the standalone Galaxy template.
4. Preserve the existing Stage 07 native-faction bridge for the five native factions.
5. Run static, WebUI, and `-NoLaunch` MVP tests for native, Alenger, and Reborn representatives.
6. Run one approved-launcher realtime pilot when an independent SC2 runtime slot is available. A
   static/staged result is never promoted to `runtime_pass`.

## Acceptance

- The manifest has exactly 50 unique commanders and declares every target Catalog/dependency.
- The matrix has 1,550 cells, no `亡者之夜` cell, and exactly 50 unsupported `tarcade` cells.
- A selected non-native commander reaches the Revolution Overdrive launcher with `-Commander`.
- `-NoLaunch` changes only a staging map copy, includes the selected template marker, and records
  dependency and Catalog evidence.
- Runtime cells retain their evidence-based status until a matching realtime probe passes.

## Progress Snapshot: 2026-08-18

- The manifest and generated matrix cover all 50 WebUI commanders and all 31 registered maps.
- Native Stage 07 evidence contributes seven runtime-passed cells. Stage 10 now adds the first
  non-native pass: `thanson01.SC2Map` x `TerranAlenger3`.
- The generic realtime probe is manifest-driven. It requires `CreateGame=init_game`,
  `JoinGame=in_game`, naturally advancing realtime observations without manual stepping, P1
  starting structure and worker observation, and a same-window ScriptError scan.
- Maps that begin with mission-only P1 units now receive the selected commander base and worker
  initialization from the staged Galaxy overlay. This fallback is runtime-proven only for the
  Alenger3 pilot and must be revalidated for every remaining map-commander cell.

## Next Runtime Batches

1. Use the generic probe for one remaining commander from each group on `thanson01`: official,
   Reborn, and each remaining Alenger commander. Keep the target checks manifest-derived.
2. Repeat the proven Alenger3 pairing on a second map with a different opening lifecycle before
   treating the base fallback as a series-level behavior.
3. Sweep one map at a time across the 50 commander entries. A cell becomes `runtime_pass` only
   after the staged launcher evidence and its matching realtime probe are indexed.
4. Keep `tarcade.SC2Map` unsupported and reject `亡者之夜.SC2Map`; neither may be used to pad
   coverage or substitute for a Revolution Overdrive map.
