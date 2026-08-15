# Stage 27 Log: 斗蛐蛐 Behavior Plugin

## 2026-08-15

### Scope and design

- `static`: The source map remains a read-only input. The behavior is isolated in
  a new project-owned plugin and an opt-in commander-map overlay.
- `static`: The Python VM uses explicit `douququ.*` function ids and the existing
  typed `DebugVm`; no reflection or arbitrary function invocation is added.
- `inference`: The selected default unit ids and numeric values follow the user
  description and are configuration-backed. They require live confirmation on
  the staged 斗蛐蛐 map.

Validation and runtime evidence will be appended after implementation.

## 2026-08-15 WebUI unconditional restart

- `static`: The WebUI launch paths now perform an unconditional restart for
  exact SC2 process names (`SC2.exe`, `SC2_x64.exe`, `SC2Switcher.exe`, and
  `SC2Switcher_x64.exe`). Ownership checks remain on the explicit stop path;
  launch no longer refuses an externally started SC2 session.
- `static`: Stale runtime ownership records are removed only after the process
  table is empty. A failed taskkill is logged and does not masquerade as a
  successful cleanup.
- `runtime`: An approved launcher started external `thorner03` SC2 PID `23712`.
  POST `/api/launch-async` with `revolution-overdrive / thanson01 / Coverts`
  returned HTTP `200` and launcher PID `29728`; the old PID was terminated and
  new SC2 PID `24424` appeared for the requested map.
- `runtime`: The new launcher completed with `ready=true`, zero ScriptErrors,
  and `scriptErrorFree=true`. Evidence:
  `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/webui-unconditional-restart-20260815.json`.
- `validation`: `python -m pytest -q tools/cmre-webui/test_launch_async_contract.py`
  -> `25 passed`; runtime contract and Revolution Overdrive tests -> `3
  passed`; WebUI root -> HTTP `200`, factors -> 45 commanders, maps -> 15.
