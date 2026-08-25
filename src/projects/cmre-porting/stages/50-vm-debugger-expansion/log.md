# Stage 50 Log: Ares-Inspired Tactical Validation Layer

## 2026-08-18 implementation pass

- `static`: Reviewed `C:/Users/Sigeer/Downloads/sc2-simulator-implementation-plan-20260818.md` against the existing Stage50 roadmap and live `vibe` code. The plan's multi-seed, deterministic runner, A/B comparison, and Observation/Action separation requirements match the Stage50 direction.
- `static`: Confirmed write scope includes `src/projects/cmre-porting/vibe/**`, `src/projects/cmre-porting/stages/50-vm-debugger-expansion/**`, and Stage50 artifacts.
- `static`: Extended `src/projects/cmre-porting/vibe/consumers/tactical.py` instead of creating a parallel runner. Added `tactical_report.v1` fields, scenario identity hashing, seed-batch summaries, A/B compare rule, capability coverage, reliability flags, determinism health check, and Stage50 runner surfaces.
- `static`: Added `SimulatorSession.query_observation()` so strategy input crosses a session facade rather than constructing `Observation` directly at the policy boundary.
- `simulator`: Added `src/projects/cmre-porting/stages/50-vm-debugger-expansion/test_tactical_validation_layer.py`, covering `tactical_report.v1`, multi-seed batch identity, deterministic same-seed checks, and seed-batch sweep behavior.
- `simulator`: Generated Stage50 sample report artifacts:
  - `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/stage50-tactical-report-v1.json`
  - `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/stage50-tactical-report-v1.md`

## Verification

- `simulator`: `PYTHONPATH=src/projects/cmre-porting py -3.13 -m vibe.consumers.tactical` -> PASS; existing tactical selftest passed 16/16 checks.
- `simulator`: `py -3.13 -m unittest discover -s src/projects/cmre-porting/stages/50-vm-debugger-expansion -p test_tactical_validation_layer.py -v` -> PASS; 3 tests passed.
- `static`: `py -3.13 -m json.tool src/projects/cmre-porting/stages/50-vm-debugger-expansion/result.json` -> PASS.

## Remaining issue

- `static`: `STAGE50-STAT-SURFACE-001` remains open. Strategy input is now facade-bound, but per-run aggregate metrics still use the existing tactical consumer's direct simulator-state reads. This is acceptable for the Stage50 report-contract MVP, but should be moved behind session query helpers if Stage50 continues deeper into architecture enforcement.

- `static`: `py -3.13 -m json.tool artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/stage50-tactical-report-v1.json` -> PASS.

## WebUI Revolution Commander Route Fix - 2026-08-18

- `static`: `tools/cmre-webui/server.py` rejects `RevolutionOverdrive*` commander ids and `commanderPackage=revolution-overdrive` on non-Revolution maps before launcher spawn; `tools/cmre-webui/webui/app.js` mirrors the guard.
- `runtime`: Temporary WebUI smoke POST for `虚空降临.SC2Map` / `RevolutionOverdriveCoverts` returned HTTP 400, with `/api/status` reporting `launcherRunning=false`, `pid=null`; valid Revolution Overdrive dry-run remained routable.
- `static`: `CMRE_WEBUI_DRY_RUN=1 python -m pytest -q tools/cmre-webui/test_launch_async_contract.py tools/cmre-webui/test_revolution_overdrive.py` -> PASS, `43 passed`.

## Runtime VM Spot-Check - 2026-08-18

- `runtime`: User-requested current VM progress check captured in `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/runtime-vm-current-check-20260818.json`.
- `runtime`: WebUI `127.0.0.1:8777` is alive, but `/api/status` reports `launcherRunning=false` and `pid=null`; TCP probes show `5896=false` and `5897=false`.
- `runtime`: `/api/vibe/status` reports `status=error` with no active current Vibe session; last candidate `repl_c9dc144c3fa8` ended as `INTERNAL_ERROR timeout` for request `33e8a4809297`.
- `runtime`: Bank signals show prior runtime init/bridge readiness (`runtime_listener_ready=1`, `bridge_heartbeat=12`) and a stale pending request, but `/api/vibe/event-log` count is `0` and `/api/vibe/rules` count is `0`.
- `static`: This spot-check does not change the Stage50 tactical simulator PASS or native/runtime claim boundary; it records that fresh VM RPC/gameplay-event claims are currently blocked by inactive session binding.

## dq-webui Recovery - 2026-08-19

- `runtime`: `dq-webui` supervisor reported exit code `1073807364`; pre-restart TCP probe showed `127.0.0.1:8777` closed while the separate `8767` WebUI process remained open.
- `runtime`: Restarted `dq-webui` through the supervisor with `py -3.13 tools/cmre-webui/server.py --host 127.0.0.1 --port 8777 --dou-ququ-map src/projects/test-arena/packages/Maps/地图调试和斗蛐蛐工具（完整功能版).SC2Map`; supervisor reported port `8777` ready.
- `runtime`: Smoke endpoints passed: `/api/status`, `/api/vibe/status`, `/api/maps`, `/api/factors`, and `/api/vibe/call-log?limit=5` all returned HTTP 200.
- `runtime`: Recovery artifact `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/dq-webui-recovery-20260819.json` records WebUI recovered, `launcherRunning=false`, `vibe_status=disconnected`, and VM ports `5896/5897` still closed.
- `static`: This recovery only restores the WebUI control plane; it does not claim SC2 launcher readiness, VM RPC availability, or automatic gameplay event evidence.

## Offline SC2 Asset Reference Check - 2026-08-25

- `static`: Converted the read-only `reference/SC2plusSCBW/SC Evo Complete/SCEvo_Assets.SC2Mod/Base.SC2Assets/Assets/Units/Zerg/ZerglingSCBW/ZerglingSCBW.m3` with `node convert-m3.js <input.m3> <output.glb>` into `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/sc2-model-reference/zergling-scbw-reference.glb`; conversion reported 16 animation clips.
- `static`: Blender 4.5.5 GLB import produced an Armature and actions including Stand, Walk, Attack, Burrow, and Unburrow. The clean working preview `zergling-scbw-reference-clean.blend` removes converter helper meshes and assigns Walk.
- `static`: A Blender frame-sampling check of Walk at frames 0, 24, and 48 found 111 F-Curves and maximum mesh-vertex deltas of `0.0520525` for both intervals. The visible clean action frame is `artifacts/projects/cmre-porting/stage50-vm-debugger-expansion/sc2-model-reference/zergling-scbw-walk-frame-clean.png`.
- `static`: This is offline converter/Blender evidence only; it does not claim SC2 engine, Previewer, Data Editor, or in-game compatibility. The input is the locally available SCBW Zergling variant, not an asserted standard modern SC2 Zergling asset.
