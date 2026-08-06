# Stage Log

## Progress

- Registered the generated Stage 02 extraction root so the existing Catalog analyzer could inspect
  it without bypassing its source-root safety check.
- Verified and extracted seven file-based `.SC2Mod` archives into
  `artifacts/projects/revolution-overdrive-porting/stage02-extraction/`.
- Analyzed all seven extracted Mod Catalog trees and recorded six Galaxy files and their symbol
  headers/includes.
- Recomputed the Stage 01 hash baseline against the read-only source; no file changed or went
  missing.
- Recorded the candidate commander/shared/map ownership boundary and the AI ally boundary.

## Evidence

- `static`: extraction status, package dependencies, component manifests, and catalog summaries are
  in `evidence/static/archive-extraction-manifest.json`.
- `static`: seven extracted Catalog reports and aggregate counts are in
  `evidence/static/mod-catalog-summary.json` and `evidence/static/mod-catalogs/`.
- `static`: Galaxy file paths, function names, includes, and lint statuses are in
  `evidence/static/galaxy-symbol-catalog.json` and `evidence/static/galaxy-lint/`.
- `static`: ownership and AI ally rules are in `evidence/static/ownership-boundary.json`.
- `static`: source immutability is proven by `evidence/static/source-unchanged.json`.
- `runtime`: not run. No owned commander/map package or approved Revolution Overdrive launcher
  exists yet.

## Changes

- `src/config/workspace.json`: registered the generated extraction root as a relative, read-only
  analysis input.
- `src/projects/revolution-overdrive-porting/project.json`: advanced current stage and scoped the
  workspace registration, Stage 02 records, and generated extraction artifacts.
- `src/projects/revolution-overdrive-porting/stages/02-static-extraction/**`: plan, evidence,
  self-assessment, log, result, and issues.
- `artifacts/projects/revolution-overdrive-porting/stage02-extraction/**`: generated unpacked Mod
  inputs; no source package is committed from this directory.

## Problems

- The candidate commander still has a dependency closure containing five faction packages plus
  campaign data; that closure must be staged consistently before runtime.
- Catalog-heavy packages without Galaxy files require runtime/compile validation rather than being
  silently treated as inert data.
- The source maps' scripted ally relations are mission-owned and have no native melee AI entry;
  the current AI ally improvement must be an adapter/observation contract, not a generic AI swap.

## Handoff

Stage 03 can name exact source packages, extract paths, and ownership rules. It should create the
owned commander package, map package manifest, faction preset metadata, and WebUI/launcher adapter
contract, then run static package validation before any live launch.
