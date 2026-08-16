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

## 2026-08-15 Traceable map details in WebUI

- `static`: `MapEventExtractor` now emits schema `cmre-map-unit-events.v2`
  with source objects (`file`, `line`) for `MapScript.galaxy`, `Objects`,
  `Regions`, and GameData XML. It resolves `Wait`, `TimerStart`, and time-
  trigger calls, region references/random points, shape centers/radii, Chinese
  unit names, translated event text, trigger function context, and raw source
  evidence.
- `static`: The extractor rejects trigger/function symbols such as `gt_*`,
  `gf_*`, `gv_*`, `lib*`, `obj*`, and `*_Func` when they appear as string
  literals, so `TriggerCreate` is not reported as a unit.
- `runtime`: `GET /api/map-details` was exercised through the restarted
  WebUI. The endpoint returned `cmre-map-details.v1`, `evidence_type=static`,
  1319 preplaced units, 132 script events, 282 timing records, 52 regions,
  and 414 timeline records for `亡者之夜.SC2Map`. Evidence:
  `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/webui-map-details-20260815.json`.
- `runtime`: The map tab now exposes the full timeline, event filters/search,
  selected-record detail, preplaced unit coordinates, region shapes, and the
  selected commander adapter. Failed source scans remain explicitly marked
  `尚未扫描`; no placeholder results are generated.
- `validation`: Stage 27 plus launcher/WebUI tests -> `113 passed`; focused
  extractor/API tests -> `4 passed`; JavaScript `node --check` and Python
  compilation passed.

## 2026-08-15 Runtime-first live verification

- `static`: Re-staged the read-only user map with only the live runtime module:
  `python tools/cmre-webui/stage_map_vm_runtime.py --source <user-map> --output artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/dou-ququ-runtime-vm --enable-dou-ququ-runtime --replace`.
  The manifest now records `stage=27-dou-ququ-behavior-plugin`,
  `douQuquBehavior.enabled=false`, and `douQuquRuntime.enabled=true`.
- `static`: StormLib packed the staged directory into
  `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/dou-ququ-runtime-vm.packed.SC2Map`.
- `runtime`: Using the existing approved SC2 API session on `127.0.0.1:5896`
  (SC2 PID `17784`), `CreateGame + JoinGame + RequestStep` drove the real map
  through `douququ.*`. The final probe returned `8/8 PASS`:
  runtime module active; Reaver Zealot chance; Vulture +2 storage and 50-mineral
  refill; three death mines; Infested Banshee energy hatch; Brood Lord Baneling
  chance; Hydralisk +25 heal; and Kerrigan two Broodlings.
- `runtime`: The death-mine check returned three real SC2 unit tags and the
  in-game `douququ.snapshot` returned `mineCount=3`. Raw observation omits the
  burrowed mine units, which is recorded as a protocol note rather than treated
  as a failed game-state assertion.
- `runtime`: From the SC2 process start window, the GameLogs ScriptError gate
  found no new `*ScriptError*.txt` files. API listener remained on port `5896`.
- `validation`: `python -m pytest -q tools/cmre-webui/test_stage_map_vm_runtime.py src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin` -> `26 passed`.
- `validation`: `python -m pytest -q tools/cmre-webui/test_launch_async_contract.py tools/launchers/tests/test_launch_cmre_alenger_static.py src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin` -> `117 passed`.
- `validation`: `python -m py_compile tools/cmre-webui/dou_ququ_runtime_probe.py tools/cmre-webui/stage_map_vm_runtime.py src/projects/cmre-porting/vibe/dou_ququ_behavior.py` -> passed.
- `runtime evidence`: `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-runtime-vm-live-final/dou-ququ-runtime-evidence.json`.

The Stage 27 overall result remains `IN_PROGRESS` only because the unrelated
zzerus03/Reborn map-commander initialization issue is still open; the runtime-first
斗蛐蛐 plugin itself is no longer pending.

## 2026-08-15 Map-detail extraction correction

- `static`: Rebuilt `reference-map-unit-events.json` from the 69 read-only
  reference maps using `cmre-map-unit-events.v2`: 54,199 preplaced units,
  11,692 unit-producing events, 8,882 time/trigger records, and 3,591 region
  definitions. The earlier v1 event count is superseded by this stricter pass.
- `static`: The direct-create classifier now excludes all `Trigger*` event
  registration calls. Full-artifact validation found `0` `Trigger*` calls with
  a reported unit, preventing button/ability ids and unit-event filters from
  being presented as spawned units.
- `runtime`: After the final WebUI restart, `/` returned HTTP `200` and
  `/api/map-details` returned 132 unit events, 282 time records, 52 regions,
  and 414 timeline rows for `亡者之夜.SC2Map`; the sampled record links
  `MapScript.galaxy:728` to a translated random-point event in the northwest
  barricade destroyer spawn region. Evidence:
  `runtime/webui-map-details-20260815.json`.

## 2026-08-15 Runtime session recovery

- `static`: `RuntimeConsole` no longer treats the largest Bank `sequence` as
  the current session. Bank entries are presented as candidates, and the
  connection handshake probes each candidate with the side-effect-free
  `douququ.runtime.status` call. `SESSION_EXPIRED` candidates are skipped;
  the same joined WebSocket is reused so fallback does not recreate the map.
- `static`: The WebUI no longer writes `sessions[0]` into the session input.
  Users can still select a candidate manually, while an empty input lets the
  backend try a fresh session and known Bank candidates. `/api/vibe/status`
  now exposes `session_recovery` for auditability.
- `runtime`: On WebUI `8777`, an explicit stale request for
  `dou-ququ-runtime-8bd8c9e11051` returned `status=connected` with the live
  session `repl_9ba6176be879`. The recovered connection then returned
  `douququ.runtime.status` with `active=true, mode=live-vm`, and a real
  `douququ.unit.spawn` created Marine tag `786433`, both with `error_code=OK`.
  Evidence:
  `runtime/webui-session-recovery-live-20260815.json`.
- `runtime`: The follow-up attempt after restarting the WebUI could not open a
  second SC2 WebSocket because the existing long-lived SC2 process had closed
  new client connections. The earlier recovery and mutation evidence remains
  valid; no SC2 process was forcibly terminated during this check. This is a
  runtime boundary note, not a plugin behavior failure.
- `validation`: `python -m pytest -q src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin tools/cmre-webui/test_stage_map_vm_runtime.py tools/cmre-webui/test_launch_async_contract.py tools/launchers/tests/test_launch_cmre_alenger_static.py` -> `120 passed`.
- `validation`: `node --check tools/cmre-webui/webui/app.js` and
  `python -m py_compile tools/cmre-webui/server.py` -> passed.
- `validation`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> `52/52` passed, `0` warnings.

## 2026-08-15 天界封锁地图详情浏览器修复

- `static`: WebUI JSON、HTML、JavaScript 和 CSS 现在均发送 `Cache-Control:
  no-store, max-age=0`；地图详情请求也显式使用 `fetch(..., { cache:
  "no-store" })`。切换地图或指挥官会中止已过期的详情请求，避免旧响应覆盖当前选择。
- `static`: 读取或渲染失败不再显示误导性的“尚未扫描”。面板会显示“静态扫描失败”、清空旧表格计数，并展示实际错误文本。
- `runtime`: 重启后的 `127.0.0.1:8767` 对 `天界封锁.SC2Map` 返回 HTTP `200`
  和 `Cache-Control: no-store, max-age=0`，载荷包含 1,713 个预置单位、13 个
  脚本事件、81 条时间记录、40 个区域及 94 条时间线记录。
- `runtime`: 通过 Edge 无头浏览器在真实 WebUI 中点击“天界封锁”，面板状态为
  “静态扫描完成”，渲染 94 条时间线、1,713 条预置单位和 40 条区域，无错误提示。
- `validation`: `python -m pytest -q src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin tools/cmre-webui/test_map_details.py tools/cmre-webui/test_launch_async_contract.py tools/launchers/tests/test_launch_cmre_alenger_static.py` -> `118 passed`；`node --check tools/cmre-webui/webui/app.js` 以及 `python -m py_compile tools/cmre-webui/server.py src/projects/cmre-porting/vibe/map_event_extractor.py` -> passed.

## 2026-08-15 Runtime VM entry and traceable call log

- `static`: The attribution dialog cleanup is staging-only. `stage_map_vm_runtime.py` and the approved CMRE on-demand overlay remove the exact `Param/Expression/265C2CBF` dialog block and four related `zhCN` strings from the isolated copy; the source map still contains the original expression and author text. The staging manifest records `stagedCleanup.scope=staged-copy-only`.
- `static`: The source map already contained the Vibe kernel bootstrap from an earlier external staging state. Runtime staging now reuses existing Vibe includes/init without duplicating them, adds only the runtime registration marker and `LibDouQuquRuntime`, and keeps `douQuquBehavior.enabled=false`.
- `static`: `POST /api/vibe/invoke` is the direct live function entry and `POST /api/vibe/run-vm` is the `vibe-debug/1` program entry. `GET /api/vibe/catalog`, `GET /api/vibe/trace`, and `GET /api/vibe/call-log?limit=200` expose the registry, current trace, and persisted JSONL call history. Each persisted call contains UTC timestamp, session, port, origin, function id, args, result, error, status, and duration.
- `runtime`: The staged runtime map was repacked to `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/dou-ququ-runtime-vm-logged.packed.SC2Map` because the long-lived SC2 process held the previous packed path open. The source/staged cleanup check returned `sourcePopup=true`, `stagedPopup=false`, `sourceAuthor=true`, `stagedAuthor=false`, `stagedStaticBehavior=false`.
- `runtime`: Approved live probe against port `5896` performed real `CreateGame + JoinGame + RequestStep` on the cleaned runtime-only map and returned `8/8 PASS`. Evidence: `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-runtime-logged-live/dou-ququ-runtime-evidence.json`.
- `runtime`: Restarted the project WebUI on `8777`, connected to the existing SC2 session, skipped an expired candidate, and accepted `dou-ququ-runtime-9b4e43be0b9a`. Direct `/api/vibe/invoke` created a Reaver tag `262146` and enemy Marine tag `3932163`, both `error_code=OK`; `/api/vibe/run-vm` returned `success=true`, `status=passed`.
- `runtime`: The validation snapshot of the persisted call log contained 42 records: `connect=10`, `api=2`, `vm=30`, covering 14 function ids. The append-only log is now 44 after two later reconnect probes (`connect=12`, `api=2`, `vm=30`). Evidence: `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-runtime-vm-call-log.jsonl`; read-only API evidence was `GET http://127.0.0.1:8777/api/vibe/call-log?limit=500`.
- `runtime`: The SC2 PID `5460` process window started at `2026-08-15T21:56:18+08:00`; the GameLogs scan found zero new `*ScriptError*.txt` files after the direct API calls and VM run.
- `validation`: `python -m pytest -q tools/cmre-webui/test_runtime_call_log.py tools/cmre-webui/test_stage_map_vm_runtime.py tools/launchers/tests/test_launch_cmre_alenger_static.py tools/cmre-webui/test_launch_async_contract.py` -> `103 passed`.
- `validation`: `python -m pytest -q src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin tools/cmre-webui/test_runtime_call_log.py tools/cmre-webui/test_stage_map_vm_runtime.py tools/cmre-webui/test_map_details.py tools/cmre-webui/test_launch_async_contract.py tools/launchers/tests/test_launch_cmre_alenger_static.py` -> `128 passed`.
- `validation`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> `52/52 passed`, `0 warnings`.
- `validation`: `python -m py_compile tools/cmre-webui/server.py tools/cmre-webui/stage_map_vm_runtime.py`, `node --check tools/cmre-webui/webui/app.js`, and `git diff --check` -> passed.

## 2026-08-15 Final runtime gate and validation closeout

- `runtime`: The approved same-window ScriptError gate was rerun with the real
  SC2 PID `5460` start time (`2026-08-15T21:56:18.2356109+08:00`) as the
  boundary. `script_error_check.py` returned exit code `0`, `count=0`, and an
  empty file list. Evidence:
  `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-script-error-verdict-20260815.json`.
- `validation`: `python -m pytest -q src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin tools/cmre-webui/test_runtime_call_log.py tools/cmre-webui/test_stage_map_vm_runtime.py tools/cmre-webui/test_map_details.py tools/cmre-webui/test_launch_async_contract.py tools/launchers/tests/test_launch_cmre_alenger_static.py` -> `129 passed`.
- `validation`: `powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/run-all-validation.ps1` -> `52/52 passed`, `0` warnings.
- `validation`: Python compilation, `node --check tools/cmre-webui/webui/app.js`,
  and `git diff --check` -> passed.
- `runtime`: The 斗蛐蛐 runtime-first plugin remains `8/8 PASS` on the real
  staged user map. The only open issue in this stage is the unrelated
  `zzerus03` Reborn map-commander initialization blocker; it is kept separate
  from the verified `douququ.*` development surface.

## 2026-08-15 Runtime challenge recheck without pausing the game

- `runtime`: The previous SC2 process was absent, so no live game was paused or
  taken over. The approved WebUI launcher was started from the read-only user
  map, with `douQuquBehavior.enabled=false` and `douQuquRuntime.enabled=true`.
  SC2 PID `14424` reached API listener `127.0.0.1:5896` and remained alive with
  `KeepAlive`; the launcher output reports zero new ScriptErrors at map load.
- `runtime`: `python tools/cmre-webui/dou_ququ_runtime_probe.py --port 5896
  --map-path artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/dou-ququ-runtime-vm-proc-config.packed.SC2Map
  --out-dir artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-runtime-vm-live-manual-20260815`
  performed real `CreateGame + JoinGame + RequestStep` on the running SC2 host
  and returned `8/8 PASS`. The evidence keeps a visible showcase pair for
  Reaver, Vulture, InfestedBanshee, BroodLord, Hydralisk, and K5Kerrigan, plus
  their enemy units and generated effects.
- `runtime`: The WebUI reconnected to the live session
  `dou-ququ-runtime-cd7fe0bc8810` without creating or leaving another game.
  `/api/vibe/observe` returned `game_loop=1721` and `unit_count=38`, including
  friendly Reaver/Vulture/InfestedBanshee/BroodLord/Hydralisk/K5Kerrigan and
  enemy Marine/Vulture/Overlord/CommandCenter units, as well as Zealot,
  Baneling, and Broodling results. `douququ.snapshot` returned
  `zealotCount=2`, `mineCount=6`, `marineCount=6`, `banelingCount=2`, and
  `broodlingCount=2` before the VM repeat.
- `runtime`: `POST /api/vibe/run-vm` was executed with the full 49-instruction
  program after removing only the standalone `douququ.reset` step. It returned
  `success=true`, `status=passed`; all behavior assertions passed, including
  Reaver Zealot spawn, Vulture `storedMines=5` after a 50-mineral refill,
  three death mines, Banshee hatch, BroodLord Baneling projectile, Hydralisk
  `healed=25.0`, and two Kerrigan broodlings. Proc chances were restored to
  20/30/15 by `douququ.runtime.reset_proc_chances`.
- `runtime`: The persisted call log now contains `116` records. The current
  live repeat contributed `89` passed `origin=vm` calls; the log retains the
  earlier failed probes (two timeout calls and stale-session attempts) for
  auditability. Evidence:
  `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-runtime-vm-call-log.jsonl`.
- `runtime`: `python tools/galaxy-vibe/script_error_check.py --logs-dir
  "C:\\Users\\22448\\Documents\\StarCraft II\\GameLogs" --since 1786806860
  --out artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-script-error-manual-20260815.json`
  returned exit code `0`, `has_new_errors=false`, and `count=0` for the current
  SC2 window. The SC2 process and WebUI session remain running after the check.

## 2026-08-15 起义狂潮地图详情兼容修复

- `static`: 地图详情 API 现在同时接受持久化地图 ID 和 UI 显示名；`[起义狂潮] 欢迎来到丛林` 会规范化为 `ttosh02.SC2Map`，不再依赖旧前端必须传文件名。
- `static`: 前端详情请求先读取响应文本再解析 JSON；若错误端口或旧服务返回 HTML，面板会显示 HTTP 状态、Content-Type 和响应片段，而不是只显示 `Unexpected token '<'`。
- `runtime`: 8767 和 8777 两个重启后的 WebUI 对显示名请求均返回 HTTP `200`、`no-store`，并返回 `ttosh02.SC2Map` 的 814 个预置单位、346 个脚本事件、498 条时间线和 67 个区域。
- `runtime`: Edge 无头浏览器实际点击 `[起义狂潮] 欢迎来到丛林` 后显示“静态扫描完成”，渲染 498 条时间线、814 条预置单位和 67 条区域，无错误提示。
- `validation`: `python -m pytest -q tools/cmre-webui/test_map_details.py` -> `4 passed`；`node --check tools/cmre-webui/webui/app.js` 和 `python -m py_compile tools/cmre-webui/server.py` -> passed。

## 2026-08-16 Runtime VM replay and serialized WebUI queue

- runtime: On the still-running SC2 process PID 10984 with API 127.0.0.1:5896, the updated WebUI at 127.0.0.1:8778 reconnected using an empty mapPath. It reused the current game session without CreateGame, LeaveGame, pause, or launcher restart.
- runtime: POST /api/vibe/run-vm with tools/cmre-webui/dou_ququ_runtime_full.json returned success=true, status=passed, instructions_executed=48, and failed_steps=0. The runtime spawned Zealot tag 262149; the Vulture refill reached storedMines=5 and minerals=0; Vulture death returned mine tags 14680065, 14942209, and 15204353; Infested Banshee spawned Marines; Brood Lord launched Baneling tag 13369346; Hydralisk healed 25.0; and Kerrigan spawned broodlings 13893635 and 17301506. Final snapshot reported zealotCount=2, mineCount=9, marineCount=8, banelingCount=3, and broodlingCount=4. Proc chances were restored to 20/30/15.
- runtime: Raw observation from the same session returned game_loop=954 and unit_count=16 with visible Marines, Zealots, Baneling, Brood Lord, Hydralisk, and Kerrigan. Burrowed death-mine visibility is diagnostic only; the three runtime spawn tags are the authoritative creation evidence.
- static: RuntimeConsole now serializes connect, invoke, observe, step, and VM operations through one event-loop queue. The regression test drives overlapping API, observe, and VM calls and verifies peak concurrent SC2 transactions is 1.
- validation: python -m pytest -q tools/cmre-webui/test_runtime_call_log.py tools/cmre-webui/test_stage_map_vm_runtime.py tools/cmre-webui/test_launch_async_contract.py tools/launchers/tests/test_launch_cmre_alenger_static.py -> 106 passed.
- validation: Python compilation, JavaScript syntax, and git diff --check passed. The same-window ScriptError scan for SC2 PID 10984 returned has_new_errors=false and count=0 at artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/douququ-script-error-20260816-post-vm.json.
- runtime: The append-only call log retains the successful VM calls and earlier stale-session or failed calls for auditability; historical failures are not counted as failures of this replay.

## 2026-08-16 Galaxy Script Lab reload and fresh runtime verification

- `static`: The editable `LibDouQuquUser.galaxy` was staged only into the
  isolated runtime copy and repacked as
  `runtime/galaxy-user-script-stage-fixed.packed.SC2Map`. Its staging marker
  appears exactly once, so the reloaded map has one kernel, runtime, and user
  extension include each. The read-only user-provided 斗蛐蛐 source map was not
  modified.
- `runtime`: After the approved WebUI launcher reloaded the staged 斗蛐蛐 map
  (SC2 PID `10984`, API `127.0.0.1:5896`), the session handshake returned
  `douququ.runtime.status={active:true, mode:live-vm}`. Direct WebUI invocation
  of the real Galaxy entry `douququ.user.run` created a `Marine` at `(90,90)`
  for player 1 and increased minerals from `0` to `25`. The Galaxy response
  returned `unit_tag=1572866`; raw observation returned `MARINE` tag
  `4296540162`, whose low 22 bits equal `1572866`, at the requested position.
- `runtime`: A clean `CreateGame + JoinGame + RequestStep` probe then used the
  newly packed map rather than the old SC2 session. It returned `8/8 PASS`:
  runtime activation, Reaver-to-Zealot proc, Vulture five-mine refill after a
  50-mineral charge, three Vulture death mines, Infested Banshee 20-energy
  Marine hatch, Brood Lord Baneling proc, Hydralisk +25 kill heal, and two
  Kerrigan broodlings. Death-mine RPC returned three distinct tags and the
  live runtime snapshot reported `mineCount=3`; raw SC2 observation correctly
  omits burrowed mines. Evidence:
  `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/galaxy-user-script-live-fixed-20260816/dou-ququ-runtime-evidence.json`.
- `runtime`: The same-window GameLogs gate for the SC2 process started at
  `2026-08-16T00:50:10Z` returned `has_new_errors=false` and `count=0`.
  Evidence:
  `artifacts/projects/cmre-porting/stage27-dou-ququ-behavior-plugin/runtime/galaxy-user-script-live-fixed-20260816/script-error-verdict-after-probe.json`.
- `validation`: `python -m py_compile tools/cmre-webui/dou_ququ_runtime_probe.py; python -m pytest -q tools/cmre-webui/test_stage_map_vm_runtime.py src/projects/cmre-porting/stages/27-dou-ququ-behavior-plugin` -> `30 passed`. The full live probe returned exit code `0` with `8/8 PASS`.
- `inference`: A long-lived WebUI VM program can inherit units from an earlier
  run, so the authoritative behavior validation remains the fresh-game probe.
  The VM fixture moves its Vulture victim away from the attacking Vulture,
  preventing newly created Spider Mines from immediately triggering during a
  future in-session replay.

## 2026-08-16 Runtime behavior verdict corrected

- `runtime`: A manual in-game check found that normal combat did not trigger the requested effects. The previous `8/8` and 48-step results came from explicit `douququ.*` VM/RPC calls, which directly invoked the behavior functions and therefore did not exercise an event-to-VM path.
- `static`: `tools/launchers/overlays/cmre-alenger/startup/LibDouQuquRuntime.galaxy` explicitly states that it has no map triggers and changes the game only for an explicit RPC. Source inspection confirms no attack, death, kill, or periodic subscription in that module.
- `inference`: The existing staged-map runtime provides a typed execution transport and manual debugging surface, not automatic combat behavior. Until a runtime event source feeds actual game events to the VM and each result is observed, the behavior contract is blocked rather than passed.
