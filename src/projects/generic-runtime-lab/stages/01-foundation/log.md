# Stage 01 Log: Isolated Runtime Lab Foundation

## Progress

- 2026-08-08: Stage created. The supplied map-debug/battle map was extracted as a read-only reference under `artifacts/galaxy-vibe/reference-inspection/map-debug-battle`.
- Static evidence: its SHA-256 is `056F548F4D53B5F130595AB777D28AA10EFB6D59A61F2676A7522A6BBD8AD20E`; it exposes catalog browsing, unit placement, formation controls, effects/model tools, and damage statistics.
- Static evidence: the reference map depends on `Campaigns/Void.SC2Campaign` and `Mods/WarCoop/WarClassicSystem.SC2Mod`; the latter is absent locally. It remains a UI reference, not this stage's runtime baseline.
- 2026-08-09: Built the isolated RuntimeLab from the minimal skeleton, current Vibe Kernel sources, and current CMLib sources. The current packed map SHA-256 is `12a7dbd3cbc373a7097c5094ad2bfecfea2d1eabcb7c68877f1782c01bc1d499`.
- Static evidence: the build places the map-local `LibVibeInvokeDispatch.galaxy` in `Base.SC2Data`, registers `GalaxyVibe` for players 1 and 2 through `BankList.xml`, and explicitly calls `libVibeKernel_gf_RegisterEntryPoints()` after map-owned initialization. No VM or CMLib source was forked.
- Runtime evidence: an earlier BankList-enabled map load reached `CreateGame`, `JoinGame`, and `kernel_initialized`; its entrypoint registration was incomplete, so Bank RPC timed out. This was an implementation defect and is not used as an acceptance pass.
- Runtime evidence: later attempts used the corrected map but could not establish an attributable runtime window. Another CMRE runtime job repeatedly restarted debug SC2 on changing ports and wrote Stage 16 keys into the shared `GalaxyVibe` Bank.
- 2026-08-09: Corrected the generated map entry include from `TriggerLibs/NativeLib` to the skeleton's engine-recognized `TriggerLibs/natives` spelling. This removes the most direct static explanation for a map that loads but silently omits `InitMap`.
- Static evidence: `python -m pytest -q src/projects/generic-runtime-lab/tests` passed 4 tests; rebuilding emitted a 86-file map with SHA-256 `752a64905a3b3aaaa50c3336cc88900f7e0f71d59cee7efb82362e1090de871f`; Galaxy lint reported 0 diagnostics with 11 known resolver diagnostics suppressed.
- Blocked evidence: a concurrently active `SC2_x64.exe` is loading `亡者之夜.SC2Map` without an API listener, while all 17 `GalaxyVibe` Bank candidates contain shared task state. The RuntimeLab launcher and CMLib harness would terminate or reuse that instance, so no runtime command was issued against it.

## Evidence

- `static`: extracted map component list and `DocumentInfo`, command `tools/mpq/scripts/extract-sc2map.ps1`; artifact `artifacts/galaxy-vibe/reference-inspection/map-debug-battle`.
- `inference`: the reference map's UI concepts can be reintroduced later without retaining its external dependency. This requires a separate implementation stage.
- `static`: `python -m pytest -q src/projects/generic-runtime-lab/tests` passed 4 tests; `python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py` generated the current 86-file map package; `node tools/analysis/galaxy-lint.mjs ... --format text` reported 0 diagnostics with 11 known resolver diagnostics suppressed.
- `static`: the generated `MapScript.galaxy` now contains `include "TriggerLibs/natives"`, matching both `src/lib/_testmap_src/MapScript.galaxy` and `src/lib/_testmap_build/MapScript.galaxy`. The packed map SHA-256 is `752a64905a3b3aaaa50c3336cc88900f7e0f71d59cee7efb82362e1090de871f`.
- `runtime`: `tier100_live_probe.py` against the BankList-enabled build recorded API ping, `CreateGame`, `JoinGame`, and `kernel_initialized`; the verdict remained fail-closed because no entrypoint response was received. Evidence: `artifacts/projects/generic-runtime-lab/stage01-foundation/runtime/tier100-live-verdict-runtime-lab-with-bank-list.json`.
- `blocked`: corrected-map probes on ports 5002, 5003, and 5004 either lost the API before `CreateGame` or shared an active `GalaxyVibe` Bank with an unrelated CMRE job. Evidence: `artifacts/projects/generic-runtime-lab/stage01-foundation/runtime/runtime-blocked-20260809.json` and the recorded tier100 verdicts.

## Changes

- Added the standalone project, map builder, map-owned dispatcher, map-owned tactical fixture, regression tests, and stage evidence files.
- The builder uses the minimal skeleton plus current Kernel/CMLib sources and emits `BankList.xml`; it does not modify CMRE maps, commander packages, or generic-library sources.

## Problems

- The supplied `.doc` is locked by another process, so its content has not been used as evidence. The original file was not modified.
- Runtime completion is blocked until an exclusive debug SC2 API and `GalaxyVibe` Bank lease are available. No CMLib runtime-self-test success, tactical-arena success, or VM RPC success is claimed for the current package.
- The current external SC2 instance loads a different map and has no API listener. It must finish independently before the approved RuntimeLab launcher can create an attributable window; it was not stopped by this stage.

## Handoff

- Acquire an exclusive runtime lease, archive and pre-seed a no-history `GalaxyVibe` Bank using the existing arena-launcher format, then run the non-fresh tier100 probe and `cmlib_runtime_test.py` against the current map before creating Stage 02.
