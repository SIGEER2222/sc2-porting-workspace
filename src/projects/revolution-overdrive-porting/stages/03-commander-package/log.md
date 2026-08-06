# Stage 03 Log

## Progress

- Copied the main directory Mod, seven verified extracted Mod dependencies, and all 31 source maps
  into `packages/` without changing the read-only source.
- Added commander/faction metadata, map metadata, an approved SC2Switcher launcher, and a WebUI
  route that preserves the existing CMRE lists while exposing Revolution Overdrive separately.
- Added a WebUI MVP test. It performs an actual HTTP `/api/launch` dry-run, invokes the real
  launcher, and verifies the selected map reaches the SC2 staging directory.

## Evidence

- `static`: `evidence/static/source-copy-hashes.json` records 39 source/owned records, all
  unchanged with no missing files.
- `static`: `evidence/static/owned-main-catalog.json` records 4,135 parsed main-Mod Catalog
  entries and zero errors; `owned-madness-catalog.json` records the 1,964-entry faction sample.
- `static`: `evidence/static/owned-galaxy-lint.json` records 74 Galaxy files and zero diagnostics.
- `static`: `artifacts/projects/revolution-overdrive-porting/stage03-commander-package/launcher/last-run.json`
  records the direct and WebUI-facilitated `-NoLaunch` staging effect for `traynor01.SC2Map` / Iron.
- `runtime`: blocked. The local SC2 installation does not contain `Campaigns/Void.SC2Campaign`.

## Changes

- `src/config/workspace.json`: registered the owned package for the existing catalog analyzer.
- `src/projects/revolution-overdrive-porting/packages/**`: owned Mod/map closure and metadata.
- `tools/launchers/launch-revolution-overdrive.ps1`: compliant staging and runtime evidence
  launcher; it does not inject Galaxy behavior.
- `tools/cmre-webui/server.py` and `webui/app.js`: package-aware Revolution Overdrive selection
  and launcher routing with CMRE backward compatibility.
- `tools/cmre-webui/test_revolution_overdrive.py`: registry and real dry-run routing MVP.

## Problems

- The installed SC2 distribution has no Void Campaign package required by the source dependency
  graph. A real game load would be invalid until that external dependency is installed or an
  approved owned replacement is provided.
- The faction preset is activated through the source's post-load chat trigger. Staging proves the
  command route exists but cannot prove the unit replacement in a game session.

## Handoff

Stage 04 must analyze each owned map's mission-defined alliance roster, establish a deterministic
adapter contract for the existing AI ally system, and run simulator/static validation. Native SC2
validation remains blocked by the campaign dependency and must stay classified as blocked.
