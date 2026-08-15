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

### 2026-08-15 Static implementation checkpoint

- `static`: The user-provided map was extracted without modifying the source.
  Its source hash is recorded in the staging manifest as
  `056f548f4d53b5f130595ab777d28aa10ef6b59a61f2676a7522a6bbd8ad20e` and the
  staged map explicitly records `forbiddenMap=亡者之夜`.
- `static`: The Stage 27 startup contract now hashes the actual user-provided
  unmodified `MapScript.galaxy` (`bc05481b14450d569334b73d83df6a7b7a6265e545ab9919f501a3782dffeb7d`),
  instead of the repository's already-injected copy. This lets the approved
  launcher validate the real input before applying its runtime overlay.
- `static`: The Reaver `ScarabAttack` patch follows the native action definition
  and the Mengsk Thor rolling pattern. It retains `ImpactSiteOps` and
  `ImpactPhysics`, filters `Weapon` 10/11/13/14, and uses
  `::RollingIndex` driven by `ScarabLM`.
- `validation`: `python -m pytest -q src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin tools/cmre-webui/test_launch_async_contract.py tools/launchers/tests/test_launch_cmre_alenger_static.py` -> `111 passed`.
- `validation`: `tools/galaxy-vibe/run-all-validation.ps1` -> `52/52` passed;
  Python compilation of the Stage 27 probe/stager and VM module passed.
- `static`: Revised staging and StormLib packing completed at
  `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/dou-ququ-revised.packed.SC2Map`.
- `blocked`: A user-owned `zzerus03.SC2Map` `PlayerMode`/`KeepAlive` runtime
  currently owns the SC2 single-instance lock on port 5015 (launcher PID 27484,
  SC2 PID 29904). It is unrelated to 斗蛐蛐 and was not terminated. The Stage 27
  live probe therefore remains pending until an empty SC2 runtime window exists.

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

### 2026-08-15 Map event extraction and commander adapter verification

- `static`: `reference-map-unit-events.json` inventories 69 maps, 54,199
  preplaced units, 51 maps with airdrop events, and 19,225 classified unit-
  producing events across airdrops, initialization, script creation, spawns,
  waves, objectives, missions, and generic events.
- `static`: `map-commander-adapter-matrix.json` resolves 69 maps against 12
  commanders (828/828 resolutions, all using a commander profile). The launcher
  consumes the selected startup structure/worker, native removal list, and
  event replacement hints through the CMCoopLaunchProfile bank.
- `runtime`: WebUI remains online at `http://127.0.0.1:8767/`; a live GET of
  `/` returned HTTP 200 and `/api/status` reported no launcher running. The
  unconditional restart evidence remains in
  `runtime/webui-unconditional-restart-20260815.json`.
- `runtime`: `zzerus03.SC2Map` + `TerranAlenger3` resolved to
  `reborn-zerg-campaign`, with `3diguoqianshaojidi`/`3diguolaogong`, 12 workers,
  15 native removal types, and two event replacements. The launcher/API gate
  reached ready, KeepAlive was active, and the same-window ScriptError gate
  reported zero errors. The runtime Bank also recorded listener ready and a
  heartbeat; selected fields are summarized in
  `runtime/zzerus03-runtime-bank-summary-20260815.json`.
- `blocked`: The subsequent `CreateGame` attempt timed out after 120 seconds;
  direct-map inspection showed `reborn_adapter_native_opening_waiting=1`,
  `reborn_adapter_initialized=0`, and `initialization_complete=0`. The full
  Reborn map initialization is therefore still open and must not be reported
  as a runtime pass. Evidence:
  `runtime/map-commander-runtime-evidence-20260815.json`.
