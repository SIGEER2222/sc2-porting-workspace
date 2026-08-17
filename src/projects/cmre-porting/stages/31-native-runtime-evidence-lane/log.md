# Stage 31 Log: Native Runtime Evidence Lane

## 2026-08-17

- `static`: Opened Stage 31 after Stage 30 comparator implementation and focused validation completed.
- `scope`: Stage 31 is the only remaining roadmap stage allowed to claim native mission completion. It requires a fresh launcher-owned SC2 window, runtime listener, advancing API frames, terminal mission result, same-window ScriptError verdict, and evidence bundle.
- `scope`: Simulator PASS, adapter clearance, historical runtime artifacts, and replay-only evidence are not sufficient for this stage.

## Initial evidence paths

- `src/projects/cmre-porting/stages/31-native-runtime-evidence-lane/plan.md`
- `src/projects/cmre-porting/stages/31-native-runtime-evidence-lane/result.json`
- `src/projects/cmre-porting/stages/31-native-runtime-evidence-lane/issues.json`
- `src/projects/cmre-porting/stages/30-differential-validation-layer/result.json`
- `artifacts/projects/cmre-porting/stage30-differential-validation-layer/differential-report-20260817.json`

## Runtime status

- `inference`: No Stage 31 launcher window has been promoted yet. The next action is a fresh approved launcher run with a unique port/map-copy suffix and a recorded UTC epoch.

## Runtime preflight 2026-08-17T09:17:13Z

- `static`: The declared source map `src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map` exists.
- `blocked`: `E:/SC2/SC2new/StarCraft II` does not exist. The configured `Versions/Base97563/SC2_x64.exe` is absent; common roots `C:/Program Files (x86)/StarCraft II`, `C:/Program Files/StarCraft II`, and `D:/SC2` are also absent.
- `blocked`: `tasklist` reported no `SC2_x64.exe` process. No approved launcher invocation was attempted because its hard-coded executable boundary is missing.
- `static`: `py -3.13 -m pytest -q tools/launchers/tests/test_launch_cmre_alenger_static.py --tb=short` passed: 64 tests in 0.31s. This validates launcher source only and is not runtime evidence.
- `blocked`: Map packing, launcher readiness, runtime listener, CreateGame, JoinGame, RequestStep, mission result, and ScriptError gates remain unexercised. The full preflight evidence is `artifacts/projects/cmre-porting/stage31-native-runtime-evidence-lane/runtime-preflight-20260817.json`.
- `scope`: Stage 31 remains `BLOCKED`; Stage 32 must not be opened or promoted until a supported SC2 installation makes the full native evidence chain executable.

## Simulation-First reprioritization 2026-08-17

- `scope`: The Simulation-First roadmap makes simulator correctness and fidelity its primary workstream. A new simulator-only Stage 32 may proceed independently of this blocked native lane.
- `scope`: This does not change the Stage 31 native completion gate: a simulator matrix, adapter clearance, or static result cannot become a native mission-completion claim.
