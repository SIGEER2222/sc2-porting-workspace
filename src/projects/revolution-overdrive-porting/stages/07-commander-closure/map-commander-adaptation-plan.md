# Commander x Map Adaptation Plan

## Goal

Close the five selectable Revolution Overdrive commanders against every non-arcade map in
the owned 31-map package. A cell is complete only after the approved launcher and the same
real-time SC2 window prove the map-owned opening plus the commander replacement. Static
catalog coverage or a successful launcher start is not a runtime pass.

## Scope and ownership

- Maps remain map-owned: opening units, bases, objectives, rewards, cinematics, alliances, and
  mission progression stay in each unpacked `MapScript.galaxy`.
- Commander behavior remains in the owned Commander Mods and their declared dependencies.
- The launcher may inject only the runtime Galaxy bootstrap declared by
  `vibe/map_commander_adapters.json`; it must not rewrite map-authored unit creation.
- `tarcade.SC2Map` is excluded from commander runtime closure because Stage 04 classifies it as
  an entry-flow/arcade map with no cooperative P1 contract. `tstory01.SC2Map` stays in the
  matrix as `runtime_pending` until a live window proves that its entry-flow lifecycle is
  compatible.
- The read-only download source, the existing assets mirror, and every map source remain
  untouched.

## Matrix

The machine-readable matrix is
`artifacts/projects/revolution-overdrive-porting/stage07-commander-closure/map-commander-matrix.json`.
It contains 30 maps x 5 commanders = 150 cells and records the static map roster source,
runtime adapter rule, target Catalog IDs, protected players, evidence directory, and current
verdict for each cell.

Current runtime evidence:

- `thanson01`: Iron, Coverts, Umojan, Pirate, and Madness are `runtime_pass`.
- `thanson02`: Iron is `runtime_pass`; the other four cells are `runtime_pending`.
- `thanson03a`: Iron is `runtime_pass`; the other four cells are `runtime_pending`.
- Every remaining eligible cell is `runtime_pending`.

## Per-cell procedure

1. Read the Stage 04 map roster and the map's `MapScript.galaxy`; record P1 opening units,
   base/worker creation, trigger entry points, mission phase or gate, and protected players.
2. Resolve the commander adapter and validate every target Catalog ID before launch. Missing
   targets remain `blocked` or `unsupported`; do not invent a replacement ID.
3. Stage and pack the map through `launch-revolution-overdrive.ps1` on a fresh listener port.
   Never invoke `SC2_x64.exe` directly and never use faction chat to select a commander.
4. Run the commander runtime probe in real-time. Require `CreateGame=init_game`,
   `JoinGame=in_game`, non-empty Catalog data, increasing game loops with
   `requestStepsSent=0`, the map-owned opening/progression, expected P1 replacement units,
   and zero new same-window `*ScriptError*.txt` files.
5. Store launcher output, probe JSON, ScriptError verdict, and a short cell summary under the
   cell's evidence directory. A failed prerequisite is recorded as `blocked`, never inferred
   as pass.
6. Only add a map-specific adapter override after the runtime trace identifies a real
   map-owned difference. Keep the override narrow and rerun all five commanders for that map.

## Execution order

1. Pilot closure: `thanson02` for all five commanders; reuse the proven `thanson01` and
   `thanson03a` Iron evidence only as regression anchors.
2. Complete the rest of the Hanson group: `thanson03b`.
3. Complete `thorner01` through `thorner05s`, then `traynor01` through `traynor03`.
4. Complete `ttosh01` through `ttosh03b`, `ttychus01` through `ttychus05`,
   `tvalerian01` through `tvalerian03`, and `tzeratul01` through `tzeratul04`.
5. Revisit `tstory01` only with a dedicated entry-flow probe. It is not promoted merely
   because the generic adapter pattern matches it.

Each map is closed commander-by-commander, and each commander is closed map-by-map. The stop
condition for a batch is the first unexplained ScriptError, missing Catalog target, map lifecycle
failure, or evidence window that does not advance in real time.

## Completion gate

The rollout is complete only when all 150 cells are either `runtime_pass` with current evidence
or explicitly `unsupported`/`blocked` with a reproducible reason and next action. The final
stage result, log, issues list, and runtime evidence index must agree with the matrix.
