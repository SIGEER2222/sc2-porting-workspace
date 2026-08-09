# Stage 26 Log: Full Function Invoke Expansion

## 2026-08-06

### Governance
- `project.json`: currentStage=26-full-function-invoke; writeScope 增补 stage 26
  目录、kernel/**（含 generated/）、debug-mod 与亡者之夜副本、overlay 库及测试、
  debug_vm/vibe_host、stage 26 artifacts。
- 决策记录写入本目录 plan.md：推翻 Stage 25 `inventory_only_functions_are_not_runtime_callable`
  （owned-package 范围内），`arbitrary_reflection: false` 保持不变（编译期静态
  显式分派，非运行时反射）。

### Generator & plan
- `generate_invoke_adapters.py`（stage 26 目录）：读 Stage 25 function-catalog，
  按 name 级去重产出调用计划。结果：23,019 声明 → 11,890 callable + 7 ambiguous
  排除（AICampaignDiffSelect、gf_AttackWaveatTime、gf_CreateEscortUnit、
  gf_SendEscortUnit、gf_TimerColor、gf_UpdateBonusObjectiveTimer、
  gf_UpdateBonusObjectiveUI）；funcref 静态查值表 667 候选。
- 证据：`artifacts/projects/cmre-porting/stage26-full-function-invoke/invoke-plan.json`
- function-registry.json 重写：11,890 gen.* 条目（debug_only=true、generated=true、
  类型化 args schema）+ 20 条手写条目原样保留 = 11,910。
- whitelist.json 新增 handle.drop/handle.clear/handle.query 与越界/未知 id
  rejected 场景；rpc-schema.json operation enum 同步。

### 路由缺陷修复（关键）
- 自审发现：顶层两级区间分派按 `SHARD_SIZE` 全局区间路由，而分片按 available
  列表位置切分；每图 available 子集存在空洞（如 ids 2548/2549 缺失）导致
  6,108 个函数会错片（FUNCTION_NOT_IN_MAP 假阴性）。
- 修复：分片改为按全局 id 区间切分（空洞区间跳过，分片号 = 区间号），顶层路由
  与片内成员构造性一致；新增回归测试
  `test_dispatch_routes_each_adapter_to_its_global_id_range_shard`。
- 修复后每图 bundle：8,734 函数 / 24 分片 / 53 文件（含 tier dispatch 变体）。

### Galaxy 侧产物
- `LibVibeHandles.galaxy`：22 种句柄类型 int→handle 登记表（容量 512/类型，
  unit 用引擎 tag），Acquire/Get/Has/Drop/Clear/Count + kernel handle.drop/
  handle.clear/handle.query 三 handler（marker 幂等补丁 STAGE26_FULL_INVOKE）。
- kernel `function.invoke`：`gen.` 前缀整数 id → 生成分派；字符串 id 保留 20
  个手写 handler（向后兼容）。
- generated/**：15 图 bundle，每 bundle = Common + 24 分片（体/头）+ Dispatch
  + Dispatch_h + tier100/tier1000 dispatch 变体。

### 静态验收
- 解析门（reference/sc2-galaxy-toolkit Parser）：798 文件 0 错误。
  证据：`artifacts/projects/cmre-porting/stage26-full-function-invoke/static/parse-generated.json`
- stage 26 单测：24 passed（计划覆盖/无重复 id/编解码方案齐全/funcref+structref
  标注/注册表契约/whitelist/产物与路由/tier 变体/整数 id 优先/strategy 拒绝/
  fake-bridge 基础类型+句柄往返+未知句柄+FUNCREF 拒绝）。
  命令：`python -m pytest -q src/projects/cmre-porting/stages/26-full-function-invoke/test_generate_invoke_adapters.py`
- test_kernel.py：53 passed（含新增三副本 hash 一致性
  TestKernelMirrorConsistency：kernel → galaxy-debug-mod → 亡者之夜 逐文件
  sha256，generated 全 bundle 对比）。
- run-all-validation.ps1：52/52 PASS（两次：生成后与 overlay 改动后）。
  证据：`artifacts/galaxy-vibe/static-validation-report.json`
- Stage 19/20/22/23/25 回归：67 passed + 6 subtests（Stage 25
  `test_catalog_artifact_is_complete_and_registry_aligned` 适配生成 adapter 族：
  手写条目保持 handler ⊆ callable_names 不变量，生成条目改按 galaxy_name ⊆
  catalog 名校验）。

### Overlay 挂载
- `cmre-on-demand-overlay.ps1`：$vibeKernelFiles 增 LibVibeHandles.galaxy；
  bundle 扁平拷入 Base.SC2Data；MapScript 在 `include "LibVibeKernel"` 后注入
  LibVibeHandles/LibVibeInvokeCommon/各分片/LibVibeInvokeDispatch。
- 分档放量：新增 `-InvokeTier 0|100|1000`（默认 0=全量）：tier>0 时仅拷
  lo≤tier 的分片、tier dispatch 变体改名为 LibVibeInvokeDispatch.galaxy，
  超出 tier 的 id 结构化拒绝（FUNCTION_NOT_IN_MAP）。
- 测试：`tools/launchers/tests/test_launch_cmre_alenger_static.py`
  新增 test_observer_overlay_mounts_invoke_bundle_with_rollout_tiers；全套通过。

### 宿主侧
- `function_registry.py`：新增 normalize_function_id——整数/数字串 function_id
  归一化为 gen.<int>（整数 id 优先），validate_invocation / normalize_request_args /
  wire_function_args 全部接入。
- `vibe_host.py`：requests_log 策略审计为 function.invoke 增加 family 字段
  （invoke.generated / invoke.handwritten）。
- debug_vm 无需改动（注册表驱动）：gen.* 条目自动生效，strategy 模式按
  debug_only 拒绝（有单测覆盖）。

### 运行时（部分阻塞）
- 本机无 SC2（E:\SC2\SC2new\StarCraft II 与常见安装位均不存在）→ 分档放量实测、
  类型族抽样实调、只读普查、同窗口 ScriptError 门均无法在本机执行。
- 已交付可执行机制与准备证据：
  - tier dispatch 变体 + overlay -InvokeTier（放量开关就绪）；
  - `runtime_invoke_probe.py`：类型族抽样（55 族样本）+ 只读普查（候选按
    观察类/未知分类，预算+超时保护）+ live 执行入口；
  - `--plan-only` 准备证据：`artifacts/projects/cmre-porting/stage26-full-function-invoke/runtime/probe-selection.json`
- 下一步（需有 SC2 的机器）：launcher -InvokeTier 100→1000→0 逐档记录编译
  时间与包体积，执行 --sample 与 --census，走 Assert-CmreNoNewScriptErrors 门。
- 2026-08-06 补充：穷尽排查确认本机无任何 SC2（注册表卸载项/Blizzard 键、
  全部盘符 8 类候选安装位、SC2_x64/SC2 进程、sc2-runtime-lease.json 均无），
  运行时 live 验收确认阻塞于环境，已更新 issues.json 阻塞条目详情。

### 恢复执行后补强（同日）
- 发现并纠正 writeScope 误判：project.json writeScope 实际含
  `tools/launchers/launch-cmre-alenger.ps1`。实现顶层 `-InvokeTier 0|100|1000`
  参数并透传给 Install-CmreObserverOverlay；新增静态测试
  `test_launcher_top_level_passes_invoke_tier_to_observer_overlay`；
  launchers 全套 23 passed；PS1 AST 校验通过。issues.json
  INVOKE-TIER-LAUNCHER-PASSTHROUGH → resolved。
- debug_vm 一致性修复：`_call` 接入 normalize_function_id——DebugVm 程序
  可用整数/数字串 fn 调用生成族（与宿主整数 id 优先一致）；strategy 模式
  对整数 debug_only id 同样拒绝。新增 2 个测试；stage 26 单测 26 passed、
  Stage 25 debug_vm 回归 12 passed。
- 复验：run-all-validation 52/52；Stage 19/20/22/23 回归 25 passed + 6 subtests。

### 提交策略（Session closeout）
- 代码/文档/手写 Galaxy/注册表/测试按类别拆分提交（Lore Commit Protocol）。
- 刻意不提交：`tools/galaxy-vibe/kernel/generated/**`（795 文件 106.5MB）、
  `galaxy-debug-mod/Base.SC2Data/generated/**`（795 文件 106.5MB）、亡者之夜
  `Base.SC2Data/generated/**`（53 文件 7.1MB）——属 AGENTS.md 的 bulky generated
  artifacts，可由 `generate_invoke_adapters.py` 确定性重生成（三副本 hash
  测试保障一致性），故保留在工作树不入库。

### 2026-08-08 live runtime 推进（tier100 真机探针）
- 环境变更：本机 SC2 现已确认安装（E:\SC2\SC2new\StarCraft II，SC2Switcher +
  Versions\Base97563\SC2_x64.exe）。经 `SC2Switcher_x64.exe -listen 127.0.0.1
  -port 5000 -debug` 以 API 模式拉起 live 窗口（PID 视拉起批次浮动）。
- 新增自包含探针 `tools/galaxy-vibe/tier100_live_probe.py`：连运行中 SC2 →
  加载 VibeDeadOfNight.SC2Map（含 Vibe Kernel）→ 轮询 Bank 标记
  kernel_initialized/register_entrypoints_done → 经 Bank-poll RPC 实测
  system.ping / vibe.unit.spawn / vibe.query.units / function.invoke gen.*，
  并补同窗口 ScriptError 门（create_game 起算，比对 GameLogs 新增非空文件）。
- 实证结论（artifact: artifacts/galaxy-vibe/tier100-live-verdict.json）：
  - Kernel 自注册：kernel_initialized=1 + register_entrypoints_done=1 ✓
  - system.ping 闭环：3/3 ack ✓
  - vibe.unit.spawn 真机原生执行：刷 Marine 经 **SC2 原始观测独立确认 +1** ✓
    （第三方证据，绕开 Bank/Kernel 自述）
  - vibe.query.units 自查：count=1 与观测一致 ✓
  - function.invoke 路由：gen.1/gen.11800 到达 Kernel 并返回结构化响应 ✓
    （transport + 整数 id 路由已实证）
  - 同窗口 ScriptError 门：零新增非空文件 ✓
- 未达成：gen.* 真机原生执行。加载地图未挂载生成 adapter 包，gen.1/gen.11800
  均返 FUNCTION_NOT_IN_MAP。修复探针 verdict 逻辑（原误将"收到响应"判为成功，
  实为 FUNCTION_NOT_IN_MAP 假阳性，已改为要求 error_code==OK）。
- 阻塞根因（build-blocked，非逻辑缺陷）：需同时含有效 Kernel 与生成包的
  『打包后 .SC2Map 文件』。standalone VibeDeadOfNight.SC2Map 有效但缺包；
  packages/亡者之夜.SC2Map 含包但为解包目录，SC2 API 的 local_map.map_path
  仅接受打包文件 → create_game 报 InvalidMap(sub_error=2)。待 MPQ 打包闭环。
- 计划指定三档 run（launcher -InvokeTier 100/1000/0）与 runtime_invoke_probe.py
  --sample/--census 待含包有效地图就绪后补；当前 runtime-staged-rollout /
  runtime-tier100-custom-probe 标记 PARTIAL，runtime-script-error-gate 标记 PASS。

### 2026-08-08 固定 Empire 启动与选择界面移除
- 改动：`launch-cmre-alenger.ps1` 删除顶层 `-Commander`、`-EnableReborn`、
  `-RebornCommander` 输入，固定为 `Empire`；`LibCOOC.galaxy` 与 staged overlay
  改用 `CMRE_ON_DEMAND_FIXED_EMPIRE_STARTUP`，直接完成 P1/P2 commander 状态，
  不再调用 saved-profile 或 `CommanderSelectionScreen`。
- static：`python -m pytest -q tools/launchers/tests` → 59 passed；两个 PowerShell
  文件 AST 解析通过。
- static/MVP staging：`powershell -NoProfile -ExecutionPolicy Bypass -File
  tools/launchers/launch-cmre-alenger.ps1 -MapName '亡者之夜.SC2Map' -NoLaunch
  -MapCopySuffix 'fixed-empire-20260808-final'` 成功。实际 staged `LibCOOC.galaxy`
  含固定启动标记与 P1/P2 Empire 写入，不含 `CommanderSelectionScreen` 或
  `libCMFE_gf_CMUIX_StartupApplySavedConfiguration`。旧 `-Commander Empire`
  参数被 PowerShell 参数绑定拒绝。
- blocked runtime：检查发现一个既有 `SC2_x64` 进程持有当前 GameLogs；为避免中断
  外部运行中的游戏，本次未停止、复用或覆盖该进程，故没有新 live UI/listener/
  ScriptError 证据。详情见
  `artifacts/projects/cmre-porting/stage26-full-function-invoke/runtime/fixed-empire-startup-validation-20260808.json`。

### 2026-08-08 WebUI 预选指挥官修正
- 用户澄清 WebUI 仍必须选择地图和指挥官；此前固定 Empire 的实现不符合该契约，作为错误前向提交被本次修正取代。
- 恢复 `launch-cmre-alenger.ps1` 的强制 `-Commander`、`-EnableReborn`、
  `-RebornCommander`、`-RebornDifficulty`、`-RebornSpeed` 参数。WebUI 的
  `-MapName/-Commander` 组合继续原样传入 launcher。
- 删除固定 Empire 启动资产，新增 `player-commander.galaxy.tpl` 与
  `preselected-commander-startup.galaxy.tpl`。覆盖器每次根据 `$Commander`
  重写已有预选块、旧 saved-profile 块或原始 CMUIX startup 分支；随后直接设置
  P1/P2、完成 `libCOOC_gf_CC_DevStartupFinish`，不调用
  `CommanderSelectionScreen` 或 `libCMFE_gf_CMUIX_StartupApplySavedConfiguration`。
- `static`: `python -m pytest -q tools/launchers/tests tools/cmre-webui/test_launch_async_contract.py`
  -> 63 passed；两个 PowerShell 文件 AST 解析通过；launcher `-DryRun` 接受
  `ZergAlenger6` 并解析为 Abathur。
- `static/MVP`: 对真实 CMRE `LibCOOC.galaxy` 副本执行
  `Install-CmrePreselectedCommanderStartupOverlay -Commander ZergAlenger6`，
  检查 P1/P2 均为 `ZergAlenger6`，且两个选择入口均不存在。证据：
  `artifacts/projects/cmre-porting/stage26-full-function-invoke/runtime/preselected-commander-overlay-20260808.json`。
- `blocked`: 真实 launcher `-NoLaunch` staging 在同步 `CM_ArtPack_Base.SC2Mod`
  时被已有 `SC2_x64` 进程占用；没有终止该外部会话，故 live UI、listener、
  同窗口 ScriptError 仍待空闲 SC2 会话补验。

### 2026-08-09 source catalog hygiene and regeneration

- `src/config/local.sources.json` 已确认存在且可解析；不再把“缺少 local source binding”
  作为当前事实。
- 修正 `discover_function_catalog.mjs`：owned package 扫描排除
  `Base.SC2Data/generated/**`、`LibVibe*` 镜像和 `LibVibeInvoke*` 生成文件；canonical
  kernel 通过独立 `vibe-kernel` source 扫描，保留 20 条手写 RPC handler 的来源证明。
- 清洁 catalog：`function-catalog.json` 共 **23,022** 条声明，其中 owned source
  **22,780**、canonical kernel **242**，各 source `parse_errors=0`。
- 清洁 full-source 对账：`function-catalog-full-clean.json` 共 **35,314** 条声明，
  owned **22,780** + cmre-dev **12,534**；按 `(name, return_type, parameter types)`
  去重后 cmre-dev 新增唯一签名 **0**。历史 `35,404` 基线仍差 **90**，保留为 open
  reconciliation issue，不把声明数量差异误判为 adapter 缺失。
- Stage 26 重新生成：**11,676** callable、**155** explicit exclusions、603 funcref
  candidates；亡者之夜 bundle **6,671** functions / **28** shards。
- 新鲜验证：Stage 25 debug VM/catalog **13 passed**；Stage 26 generator **33 passed**；
  Kernel **59 passed**；generated parser **862 files / 0 errors**；Vibe static **52/52**。
- runtime 仍为 blocked/PARTIAL：不得把静态生成成功提升为 gen.* 原生执行成功；继续等待
  含 generated bundle 的有效打包 `.SC2Map` 与同窗口 launcher/API/ScriptError 证据。

### 2026-08-09 08:0x live runtime 复跑（tier100 探针 + standalone 对照）

- 环境：当前 live SC2 实例 PID 3556（02:28 拉起，API 模式端口 5000）在 08:07 崩溃重启为
  25904，再重启为 8284（同 cmdline `-listen 127.0.0.1 -port 5000 -debug`）。无 ScriptError.txt
  写出 → 引擎级硬崩溃，非 Galaxy script error。
- 复跑 `tier100_live_probe.py --map C:/tmp/VibeDeadOfNight-Gen.SC2Map --fresh-bank`：加载成功、
  Kernel 自注册、ping 3/3、spawn 经 bank 返回 ok，但在『post-spawn observation』
  （`owned_counts`，脚本 line 360）处 SC2 连接被重置（`ClientConnectionResetError`），
  进程重启（3556→25904）。verdict 未落盘（崩溃早于写盘）。
- **standalone 对照** `tier100_live_probe.py --fresh-bank`（默认 VibeDeadOfNight.SC2Map，无生成包）：
  同样在 line 360 post-spawn observation 处硬崩溃（25904→8284）。
- 关键判定：standalone 图无生成包仍崩溃 → 崩溃与 gen.* adapter 无关，纯属 SC2 实例在
  『spawn 单位 + 推进仿真』时硬崩溃。与 06:2x（同 PID 3556）standalone 对照 5/5 通、gen 图
  2/2 全绿形成对照——同一地图、同一安装，仅 SC2 实例状态不同，结论从 PASS 退化为崩溃。
- 结论：当前实例仿真不稳定，gen.* 真机执行**当前不可复现**；06:2x 2/2 闭环为有效历史证据
  （result.json `runtime-tier100-custom-probe=PASS`，证据 `tier100-live-verdict-gen007-fix-v1/v2`
  + `gen007-standalone-ctl`）。Stage 26 保持 PARTIAL，不据当前崩溃或历史证据单方面晋升/降级。
- 处置：不反复重跑崩溃探针（浪费且加剧实例不稳定）。同步更新 result.json summary/verification
  （新增 `runtime-reproducibility-blocked`）、issues.json `RUNTIME-LIVE-VALIDATION-BLOCKED`
  （build-blocked 已解除 → 实例仿真阻塞）、MEMORY.md 修正“已闭环”为“06:2x 全绿、当前不可复现”。
  待稳定实例复跑三档放量（-InvokeTier 100/1000/0）。

### 2026-08-09 WebUI 真实启动回归
- runtime：先通过 `POST http://127.0.0.1:8767/api/stop` 清理遗留 `SC2_x64`，再以
  `POST http://127.0.0.1:8767/api/launch-async` 提交 `TerranAlenger3 + 亡者之夜.SC2Map`。
  WebUI 返回 `success=true`、launcher PID `18200`；轮询 `/api/status` 直到
  `launcherRunning=false`，无固定时间盲等。
- runtime：本次窗口新增 `Alerts.txt`，没有新增非空 `*ScriptError*.txt`；
  `Documents/StarCraft II/Banks/CMRERebornDebug.SC2Bank` 写入
  `runtime_listener_started=1`、`runtime_listener_ready=1`、`bridge_heartbeat=135`、
  `initialization_complete=1`，P1/P2 building/unit readiness 均为 `1`。
- 结论：WebUI → launcher → SC2 地图加载 → runtime listener/heartbeat → 初始化 Bank
  闭环 PASS。证据：
  `artifacts/projects/cmre-porting/stage26-full-function-invoke/runtime/webui-launch-runtime-20260809.json`。
  Stage 26 仍保持 PARTIAL，因为全量 generated-adapter 三档探针和 commander-specific
  起始状态断言仍是独立未完成项。

### 2026-08-09 晚间运行时证据对账与分档产物审计

- `runtime`：重新读取 `artifacts/galaxy-vibe/tier100-live-verdict-1829.json`
  （2026-08-09T10:33:05Z）与 `tier100-live-verdict-1924.json`
  （2026-08-09T11:32:32Z）。两份均为打包的完整生成图
  `C:/tmp/VibeDeadOfNight-Gen.SC2Map`（5,493,770B）通过：CreateGame/JoinGame，
  `kernel_initialized=1`、`register_entrypoints_done=1`，`system.ping` 3/3，
  `vibe.unit.spawn` 的 SC2 raw observation Marine `+1`，`query.units` 一致，
  `gen.1` 返回 fixed 0、`gen.202` 返回 int 2，并且同窗口没有新增非空 ScriptError。
  这是 full-map 的连续 2/2 真机通过；先前 08:0x 的 SC2 引擎崩溃保留为环境历史，
  不能再表述为“当前不可复现”。
- `static`：最新 `artifacts/galaxy-vibe/static-validation-report.json`
  （2026-08-09T20:19:26+08:00）为 52/52 passed、0 failed、0 warnings。
- `static`：审计 `C:/tmp/VibeDeadOfNight-Gen-T100.SC2Map` 与
  `C:/tmp/VibeDeadOfNight-Gen-T1000.SC2Map`：均为 5,496,293B，SHA-256 均为
  `15CD6E3150AB50ABDEC741E7136F34BFEAD0E4EA736F5C079B1EA9D273421EEA`。
  `tools/galaxy-vibe/mpq/mpq_build_gen_map.py` 没有 tier CLI 参数，且固定构建
  full dispatch bundle；因此这两个按文件名区分的副本不是有效的 100/1000 分档证据。
- `runtime`：端口 5000 当时由 API 模式 `SC2_x64.exe`（PID 22720，父 PID 24796
  已不存在）监听，无法追溯为本阶段 approved launcher 所启动。按 SC2 launch 规则，
  未连接、未复用、未停止该外部会话；待可归属的 launcher 窗口再执行分档和 census。
- 阶段结论保持 `PARTIAL`：full-map 运行时闭环与静态门均通过；正式
  `-InvokeTier 100 -> 1000 -> 0` 的 staged/package/probe 以及
  `runtime_invoke_probe.py --sample/--census` 尚未获得合规运行时证据。

### 2026-08-09 阶段记录后续静态回归

- `static`：`python -m pytest -q
  src/projects/cmre-porting/stages/26-full-function-invoke/test_generate_invoke_adapters.py
  tools/galaxy-vibe/tests/test_kernel.py` -> **92 passed**（Stage 26 生成器 33，
  kernel 59）。
- `static`：`node src/projects/cmre-porting/stages/26-full-function-invoke/parse_generated.mjs`
  -> `{"files":862,"parseErrors":0,"failures":0}`。
- `runtime`：复核端口 5000，仍归 PID 22720 的 API 模式 `SC2_x64.exe` 监听，
  无可存活父 launcher 进程可归属；不连接或操作该会话，阶段运行时动作维持待办。
