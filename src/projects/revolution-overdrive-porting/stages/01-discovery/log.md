# Stage Log

## Progress

- Registered `revolution-overdrive-download` as a read-only local source and bound it through the
  ignored local-source file.
- Created the independent `revolution-overdrive-porting` project with Stage 01 write scope.
- Inventory completed: 31 `.SC2Map` directories, 8 `.SC2Mod` packages, 2,311 source files, and 68
  Galaxy files.
- Catalog analysis completed for the main Mod and all 31 maps. No parser errors were observed.
- MPQ verification completed for all seven file-based Mod archives.
- AI/ally static audit completed across all map scripts and the main Mod AI libraries.

## Evidence

- `static`: source counts and relative asset inventory are in
  `stages/01-discovery/evidence/static/source-inventory.json`, produced from the registered source
  binding by the inventory command in this stage plan.
- `static`: the main Mod dependency chain and five faction switch mappings are in
  `stages/01-discovery/evidence/static/dependency-boundary.json`; source launch script and
  `RevolutionOverdrive.SC2Mod/DocumentInfo` were read without modifying them.
- `static`: main Mod Catalog summary is in `stages/01-discovery/evidence/static/catalog-summary.json`;
  all 31 map summaries are in `catalog-map-summary.json` and `catalog-maps/*.json`.
- `static`: relative source hashes are in `stages/01-discovery/evidence/static/source-hashes.json`.
- `static`: map alliance/AI evidence is in `stages/01-discovery/evidence/static/ai-ally-discovery.json`.
- `inference`: commander extraction must treat the main Mod and faction archives as a dependency
  closure until Stage 02 proves a narrower split.
- `runtime`: not run in discovery. Runtime evidence is intentionally deferred to the launcher stage.

## Changes

- `src/config/workspace.json`: registered the read-only source before project creation.
- `src/projects/revolution-overdrive-porting/project.json`: declared the project goal, sources,
  target, current stage, and bounded write scope.
- `src/projects/revolution-overdrive-porting/stages/01-discovery/**`: plan, self-assessment,
  static reports, log, result, and issues for this stage.

## Problems

- The seven file-based faction/shared Mods are verified MPQ containers but their contents are not
  yet owned packages; extraction is required before selecting commander versus shared ownership.
- `tarcade.SC2Map` and `tstory01.SC2Map` do not contain the same explicit alliance setup as the
  mission maps. They are recorded as special/lobby/story cases and must not be forced into the
  cooperative map adapter without a runtime decision.
- Existing workspace warnings for unrelated missing bindings remain; workspace validation itself
  still returns `ok=true`.

## Handoff

Stage 02 can rely on the relative inventory, dependency declarations, zero-error Catalog reports,
source hashes, and AI/ally static findings. The next plan must define exact archive extraction
targets, the independent commander package boundary, and a source-unchanged check.
