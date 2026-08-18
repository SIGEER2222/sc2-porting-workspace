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
