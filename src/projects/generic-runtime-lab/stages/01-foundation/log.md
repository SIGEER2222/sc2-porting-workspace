# Stage 01 Log: Isolated Runtime Lab Foundation

## Progress

- 2026-08-08: Stage created. The supplied map-debug/battle map was extracted as a read-only reference under `artifacts/galaxy-vibe/reference-inspection/map-debug-battle`.
- Static evidence: its SHA-256 is `056F548F4D53B5F130595AB777D28AA10EFB6D59A61F2676A7522A6BBD8AD20E`; it exposes catalog browsing, unit placement, formation controls, effects/model tools, and damage statistics.
- Static evidence: the reference map depends on `Campaigns/Void.SC2Campaign` and `Mods/WarCoop/WarClassicSystem.SC2Mod`; the latter is absent locally. It remains a UI reference, not this stage's runtime baseline.
- 2026-08-09: Built the isolated RuntimeLab from the minimal skeleton, current Vibe Kernel sources, and current CMLib sources. The current packed map SHA-256 is `12a7dbd3cbc373a7097c5094ad2bfecfea2d1eabcb7c68877f1782c01bc1d499`.
- Static evidence: the earlier build placed the map-local `LibVibeInvokeDispatch.galaxy` in `Base.SC2Data`, registered `GalaxyVibe` for players 1 and 2 through `BankList.xml`, and explicitly called `libVibeKernel_gf_RegisterEntryPoints()` after map-owned initialization. No VM or CMLib source was forked.
- Runtime evidence: an earlier BankList-enabled map load reached `CreateGame`, `JoinGame`, and `kernel_initialized`; its entrypoint registration was incomplete, so Bank RPC timed out. This was an implementation defect and is not used as an acceptance pass.
- Runtime evidence: later attempts used the corrected map but could not establish an attributable runtime window. Another CMRE runtime job repeatedly restarted debug SC2 on changing ports and wrote Stage 16 keys into the shared `GalaxyVibe` Bank.
- 2026-08-09: Corrected the generated map entry include from `TriggerLibs/NativeLib` to the skeleton's engine-recognized `TriggerLibs/natives` spelling. This removes the most direct static explanation for a map that loads but silently omits `InitMap`.
- Static evidence: `python -m pytest -q src/projects/generic-runtime-lab/tests` passed 4 tests; rebuilding emitted a 86-file map with SHA-256 `752a64905a3b3aaaa50c3336cc88900f7e0f71d59cee7efb82362e1090de871f`; Galaxy lint reported 0 diagnostics with 11 known resolver diagnostics suppressed.
- Blocked evidence: a concurrently active `SC2_x64.exe` is loading `亡者之夜.SC2Map` without an API listener, while all 17 `GalaxyVibe` Bank candidates contain shared task state. The RuntimeLab launcher and CMLib harness would terminate or reuse that instance, so no runtime command was issued against it.
- 2026-08-09: Added a generated `CMLibControl.SC2Map` to make the CMLib runtime dependency check repeatable. It uses the current 43 CMLib sources and the existing self-test, has no Kernel or RuntimeLab code, and only declares `Campaigns/Void.SC2Campaign`.
- Static evidence: `python -m pytest -q src/projects/generic-runtime-lab/tests` passed 6 tests; both `RuntimeLab.SC2Map` and `CMLibControl.SC2Map` built successfully. Their SHA-256 values are respectively `041097a1c7e896518bc5ae4c7ce3c09e9c816638b786196a3205f8feb6d6f39a` and `c6ae6468f3f4479a3ca673ec3a3b3e235014187f2ffff21cc8be13ef4edeb046`.
- Static evidence: Galaxy lint reported 0 diagnostics for both generated entry files; `check_cmlib.py` reported 0 errors and 0 warnings; `check_g1001.py` passed for both entry files.
- Runtime evidence: an approved launcher created an attributable no-mod API instance for the earlier `RuntimeLab-CMLibClean.SC2Map.mpq` control. `CreateGame` and `JoinGame` succeeded and game loops reached 222, but every sample contained only the 12 skeleton units, not the immediate Ghost sentinel. The foreign automation then replaced that instance before the diagnostic completed, so the connection loss is not attributed to the control package. The same launch window had no new `ScriptError` files.
- Blocked evidence: after that probe, another runtime workflow continuously owned port 5000 with a separate `SC2_x64.exe -listen 127.0.0.1 -port 5000 -debug` instance. Its known CMRE lease is detached and names `亡者之夜.SC2Map`; it is not attributable to RuntimeLab. No command that could reuse, stop, or replace that process was issued.
- 2026-08-09: Hardened the current map entry sequence: Kernel init is followed by CMLib self-test, then the map-owned fixture; the map no longer synchronously invokes the Kernel's delayed entrypoint registration. Player setup, control-panel construction, and unit spawning now start from the one-second game-time trigger instead of map-init execution.
- Static evidence: the post-fix build passed 6 project tests, Galaxy lint, CMLib static checks, and G1001. The current packed RuntimeLab SHA-256 is `912e34c6a95abb00373b7d13c283cf337f77216368c7dd4b0302eaae434cb3ad`.
- Blocked evidence: the post-fix live attempt began at Unix epoch `1786287290`, but the API instance disappeared before `CreateGame`; the guard then identified PID `23084` loading `亡者之夜.SC2Map` without an API listener and refused to clear it. The real-user-directory ScriptError scan found zero new files, but no RuntimeLab runtime claim is made from this attempt. Evidence: `artifacts/projects/generic-runtime-lab/stage01-foundation/runtime/runtime-lab-map-load-fixed-script-error-verdict.json`.

## Evidence

- `static`: extracted map component list and `DocumentInfo`, command `tools/mpq/scripts/extract-sc2map.ps1`; artifact `artifacts/galaxy-vibe/reference-inspection/map-debug-battle`.
- `inference`: the reference map's UI concepts can be reintroduced later without retaining its external dependency. This requires a separate implementation stage.
- `static`: `python -m pytest -q src/projects/generic-runtime-lab/tests` passed 4 tests; `python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py` generated the current 86-file map package; `node tools/analysis/galaxy-lint.mjs ... --format text` reported 0 diagnostics with 11 known resolver diagnostics suppressed.
- `static`: the generated `MapScript.galaxy` now contains `include "TriggerLibs/natives"`, matching both `src/lib/_testmap_src/MapScript.galaxy` and `src/lib/_testmap_build/MapScript.galaxy`. The packed map SHA-256 is `752a64905a3b3aaaa50c3336cc88900f7e0f71d59cee7efb82362e1090de871f`.
- `runtime`: `tier100_live_probe.py` against the BankList-enabled build recorded API ping, `CreateGame`, `JoinGame`, and `kernel_initialized`; the verdict remained fail-closed because no entrypoint response was received. Evidence: `artifacts/projects/generic-runtime-lab/stage01-foundation/runtime/tier100-live-verdict-runtime-lab-with-bank-list.json`.
- `blocked`: corrected-map probes on ports 5002, 5003, and 5004 either lost the API before `CreateGame` or shared an active `GalaxyVibe` Bank with an unrelated CMRE job. Evidence: `artifacts/projects/generic-runtime-lab/stage01-foundation/runtime/runtime-blocked-20260809.json` and the recorded tier100 verdicts.
- `static`: `python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py --cmlib-control` generated an isolated CMLib control map from the same current source tree as RuntimeLab. Evidence: `artifacts/projects/generic-runtime-lab/stage01-foundation/maps/cmlib-control-build-report.json`.
- `runtime`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/launch-galaxy-vibe.ps1 -Port 5000 -Map artifacts/projects/generic-runtime-lab/stage01-foundation/diagnostics/RuntimeLab-CMLibClean.SC2Map.mpq -ModPath ''` reached an API-ready instance; `python tools/galaxy-vibe/map_load_diag.py ... --wait 12` recorded loops 46 through 222 with only skeleton units. Evidence: `artifacts/projects/generic-runtime-lab/stage01-foundation/diagnostics/cmlib-clean-map-load-exclusive-20260809.json`.
- `runtime`: `python tools/galaxy-vibe/script_error_check.py --out artifacts/projects/generic-runtime-lab/stage01-foundation/runtime/cmlib-clean-exclusive-script-error-verdict.json` found zero new ScriptError files in that launch window.
- `blocked`: current port ownership was observed with `Get-CimInstance Win32_Process -Filter "Name='SC2_x64.exe'"` and `Get-NetTCPConnection -State Listen`. The current process is not from this stage and no generic-map launcher supports a non-destructive concurrent session.

## Changes

- Added the standalone project, map builder, generated CMLib control, map-owned dispatcher, map-owned tactical fixture, regression tests, and stage evidence files.
- The builder uses the minimal skeleton plus current Kernel/CMLib sources and emits `BankList.xml`; it does not modify CMRE maps, commander packages, or generic-library sources.
- Adjusted only the generic map initialization boundary and its regression coverage; no Kernel or CMLib source was copied or modified.

## Problems

- The supplied `.doc` is locked by another process, so its content has not been used as evidence. The original file was not modified.
- Runtime completion is blocked until an exclusive debug SC2 API and `GalaxyVibe` Bank lease are available. No CMLib runtime-self-test success, tactical-arena success, or VM RPC success is claimed for the current package.
- The current external SC2 instance loads a different map and has no API listener. It must finish independently before the approved RuntimeLab launcher can create an attributable window; it was not stopped by this stage.
- The fresh CMLib control and fresh RuntimeLab package require an exclusive API window for their acceptance tests. Existing old control observations do not prove behavior of the current packages.
- The post-fix package still lacks attributable live evidence because the external `亡者之夜.SC2Map` process remains active. The zero-error ScriptError scan is not a substitute for the missing CreateGame/JoinGame, Bank, and assertion evidence.

## Handoff

- 2026-08-10: Pivoted the runtime baseline to the supplied debug/battle map derivative because the minimal skeleton could load but did not execute map-owned Kernel sentinels in real SC2. The reference map remains read-only; the generated derivative removes its unavailable WarClassicSystem.SC2Mod dependency.
- Static evidence: python -m pytest -q src/projects/generic-runtime-lab/tests passed 10 tests. python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py rebuilt the current RuntimeLab map from the arena base with SHA-256 de3df6320275c4b112653d90262f12366c2b43913913677a11a4212fa16c12bc.
- Static evidence: current diagnostic builds are CMLibControl.SC2Map SHA-256 596de4cd9c0b8428dbf785ea4467e0a503c444021d785a580a04359c111e9125, ArenaKernelControl.SC2Map SHA-256 0a3bb61fbd8f48fb49cb35053fbe496c2aafb6aac0dd45386281144514b09d25, and KernelCMLibControl.SC2Map SHA-256 42422bed92eb08448d8fc646799b207abb4c77c01dc34151c98779e98210c3db.
- Static evidence: Galaxy lint on the current RuntimeLab entry file returned 0 diagnostics; G1001 returned 0 violations; CMLib static validation returned 0 errors and 1 pre-existing comment-only warning for c_MK_Snipe.
- Source fix: the map-local generated-dispatch adapter now reads Kernel's arg_value wire key, and the project test rejects the old value key. This is not yet promoted to runtime evidence.
- Runtime evidence: the earlier arena-base Kernel control window reached CreateGame, JoinGame, observed a player-1 Ghost, and produced one passing assertion with zero same-window ScriptErrors. Evidence: runtime/launcher-arena-kernel-control-port5002.*, runtime/assert-results-arena-kernel-control-port5002.json, and runtime/script-error-verdict-arena-kernel-control-port5002.json.
- Runtime evidence, pre-current-fix: the earlier arena-base RuntimeLab window observed Ghost=1, system.ping pong, kernel_initialized=1, register_entrypoints_done=1, and CMLib Bank magic 13371337, but CMLib reported 623/624 with ai.state.read failing; function.invoke still reported generated_invoke_disabled. These files are retained as historical pre-fix evidence only: runtime/cmlib-runtime-runtime-lab-arena-base*.stdout.txt and runtime/runtime-lab-bank-rpc-port5003.json.
- Blocked evidence: the current live attempt on port 5004 was fail-closed by sc2_proc_guard; the latest observation is PID 33380, a responding SC2 window loading 亡者之夜.SC2Map without an API listener. Evidence: runtime/live-blocked-external-owner-20260810.json. No current de3df632 runtime claim is made.

## Current Evidence

- static: current sources and packed maps are under src/projects/generic-runtime-lab and artifacts/projects/generic-runtime-lab/stage01-foundation/maps.
- runtime: arena-base Kernel control pass is limited to the exact historical map window named above; it proves the arena base can host Kernel, not the current RuntimeLab SHA.
- runtime: pre-fix RuntimeLab evidence proves the old arena-base integration reached VM Bank transport and CMLib self-test, with the recorded one-test residual.
- blocked: current map validation is blocked before launcher/CreateGame because an active external SC2 owner is present. This is a resource gate, not a pass/fail result for the current map.

## Current Problems

- The supplied .doc remains locked by another process and is not used as technical evidence.
- The current RuntimeLab SHA has no attributable live evidence for system.ping, function.invoke gen.1, tactical readiness, or same-window ScriptError status. The external owner was replaced by PID 33380 during this session and remains active.
- The arena-base CMLib run has a residual ai.state.read failure (623/624) that must be rechecked against the isolated CMLib control before it can be treated as a base-map limitation.

- Wait for the foreign SC2 API process to exit, then use the approved launcher to run `CMLibControl.SC2Map` first and capture Ghost/Thor/Bank evidence plus the same-window ScriptError verdict. Only if that passes, launch current `RuntimeLab.SC2Map` without reusing another job's Bank, then verify VM ping, CMLib evidence, tactical readiness, and ScriptError in one attributable window before creating Stage 02.

- Current handoff: do not create Stage 02 yet. Once PID 33380 and any other external SC2 owner exit, run the current CMLibControl control first, then current RuntimeLab through tools/galaxy-vibe/launch-galaxy-vibe.ps1 with a clean Bank lease. Verify system.ping, function.invoke gen.1 value=123 returning clamped 100, nonzero tactical readiness/count keys, raw unit assertions, and the same-window ScriptError verdict.

## Final Verification

- 2026-08-11: The user authorized termination and restart of the SC2 test slot. The stage archived all 17 active `GalaxyVibe` Bank candidates and seeded each with only `index/preload_marker=1`; the final backup is `artifacts/projects/generic-runtime-lab/stage01-foundation/runtime/bank-backup-runtime-lab-final-20260811T103203Z`.
- Static evidence: `python -m pytest -q src/projects/generic-runtime-lab/tests` passed 10 tests. `python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py` produced the final 101-file RuntimeLab package with SHA-256 `c30195bc298edf70caf733b32502e90b9e72158e80051f53bab18820b95dec64`. Galaxy lint reported 0 diagnostics; `check_cmlib.py` reported 0 errors and its existing comment-only warning; G1001 reported 0 violations.
- Static evidence: `python src/projects/generic-runtime-lab/scripts/build_runtime_lab.py --cmlib-control` rebuilt the 86-file CMLib control at unchanged SHA-256 `596de4cd9c0b8428dbf785ea4467e0a503c444021d785a580a04359c111e9125`. Its earlier same-SHA live control window passed Ghost, Thor, Battlecruiser, and Banshee assertions with zero ScriptErrors: `runtime/assert-results-cmlib-control-live-retry-port5005.json` and `runtime/script-error-cmlib-control-live-retry-port5005.json`.
- Runtime evidence: `tools/galaxy-vibe/launch-galaxy-vibe.ps1 -Port 5006 -Map artifacts/projects/generic-runtime-lab/stage01-foundation/maps/RuntimeLab.SC2Map -ModPath '' -ForceRestart` produced the attributable API window. `tier100_live_probe.py` then recorded CreateGame, JoinGame, Kernel registration, `system.ping`, a real `unit.spawn` observation delta of +1 Marine, matching `query.units`, and `function.invoke gen.1`, all passing. Evidence: `runtime/tier100-live-verdict-runtime-lab-final.json`.
- Runtime evidence: a map-local wire request with `function_id=gen.1` and `arg_value=123` returned `OK` with `value=100`, proving the RuntimeLab CMLib clamp adapter rather than the generic host registry route. Evidence: `runtime/runtime-lab-clamp-runtime-final-port5006.json`.
- Runtime evidence: the active map Bank reported `runtime_vm_initialized=1`, `generic_library_loaded=1`, `tactical_arena_started=1`, `control_panel_ready=1`, `tactical_arena_ready=1`, P1=8, P2=12, and 20 managed units. The API raw observation intentionally cannot list the inactive P2 slot, so the map-owned Bank is the authoritative P2 count evidence. Evidence: `runtime/runtime-lab-tactical-runtime-final-port5006.json`.
- Runtime evidence: `script_error_check.py` found zero nonempty ScriptError files newer than the final launcher marker. Evidence: `runtime/script-error-runtime-lab-final-port5006.json`.

## Closure

- RuntimeLab no longer invokes the full CMLib self-test inside the arena map. The isolated CMLibControl map owns that broad library test; RuntimeLab owns VM transport, the map-local CMLib clamp adapter, and the tactical fixture. This removes the arena base's debug-state interference from tactical validation without forking Kernel or CMLib sources.
- Stage 01 is complete. Stage 02 planning is available at `stages/02-scenario-expansion/plan.md`; it is not active until the project explicitly advances to it.
