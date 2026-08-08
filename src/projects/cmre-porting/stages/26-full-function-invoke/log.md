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
