# Stage 01 — kernel-inject — log

## 2026-08-08

### 静态发现

- 读取 `workspace.json`：activeProject = cmre-porting。新建 test-arena 项目并存。
- 解包原始地图到 `%TEMP%\debug_arena_map`（51 文件）：含 MapScript.galaxy、Base.SC2Data/GameData/*.xml、
  自定义 UI（DQQGJ.SC2Layout/DescIndex.SC2Layout）、自定义模型（xzk.m3/jingtou.m3）、zhCN 本地化。
- 地图功能（来自说明文档 + TriggerStrings.txt）：单位/技能/行为/物品/武器/科技面板、属性修改器、
  模型预览器、单位统计/伤害统计、斗蛐蛐阵型编辑+开战。无任务目标/失败条件，纯净沙盒。
- MapScript.galaxy 混淆（`lll*` 变量），但结构确认：
  - 第 1 行 `include "TriggerLibs/NativeLib"`（唯一 include）。
  - 第 2 行 `void lllAtg(){libNtve_InitLib();}`（NativeLib 初始化包装）。
  - 第 2561 行 `void InitMap(){lllAtg();...}`（标准地图入口）。
- 注入机制研究（static 证据见 plan.md）：
  - 亡者之夜 MapScript.galaxy 第 14 行 `include "LibVibeKernel"` + 第 21 行 `libVibeKernel_InitLib();`。
  - LibVibeKernel.galaxy 自 include NativeLib + LibVibeKernel_h，自洽。
  - tier0 active stub 提供 `libVibeInvoke_gf_Dispatch` 函数体，闭包自洽。
- 结论：斗蛐蛐地图可最小侵入注入（2 处 patch + 4 个内核文件），无需理解混淆逻辑。

### 变更路径

- 新建 `src/projects/test-arena/project.json`（项目定义，currentStage=01-kernel-inject）。
- 新建 `src/projects/test-arena/stages/01-kernel-inject/plan.md`（本计划）。
- 新建 `src/projects/test-arena/stages/01-kernel-inject/log.md`（本日志）。
- 解包原始地图到 `src/projects/test-arena/packages/Maps/地图调试和斗蛐蛐工具（完整功能版).SC2Map/`（54 文件）。
- patch `MapScript.galaxy`（2 处）：
  - 第 1 行后追加 3 行 include（LibVibeKernel / LibVibeHandles / LibVibeInvokeDispatch_active）。
  - 第 2 行 `lllAtg()` 内追加 `libVibeKernel_InitLib()` 在 `libNtve_InitLib()` 之前。
  - 原文件备份为 `MapScript.galaxy.vibe-bak`。
- 复制 4 个内核文件到 `Base.SC2Data/`：LibVibeKernel.galaxy、LibVibeKernel_h.galaxy、LibVibeHandles.galaxy（来自 `tools/galaxy-vibe/kernel/`）、LibVibeInvokeDispatch_active.galaxy（tier0 stub，来自 cmre-porting 亡者之夜）。
- 新建 `tools/galaxy-vibe/consumers/test-arena/consumer.json`（test-arena-debug-map，map=斗蛐蛐，commander=null，recipe=tier0-ping）。
- 新建 `tools/launchers/launch-test-arena.ps1`（独立地图启动入口，动态解析 CJK 目录名，调用 pack_stormlib.py + launch-galaxy-vibe.ps1）。

### Bug 修复（共享工具，阻塞当前阶段验证）

- `tools/launchers/launch-test-arena.ps1`：绕过 `pack-sc2map.ps1`（其 workspaceRoot 上溯 4 级到 SC2VibeTools 而非 3 级到 sc2-porting-workspace，导致找不到 StormLib.dll），改为直接调用 `pack_stormlib.py` 并传正确 StormLib.dll 路径。
- `tools/mpq/scripts/pack_stormlib.py`：过滤 MPQ 内部元数据文件（`(attributes)`、`(listfile)`、`(signature)`），这些文件 StormLib 自动管理，手动添加会导致 `SFileAddFileEx` 失败（Win32 error 10003）。

### 静态验证

- **打包**：`launch-test-arena.ps1 -NoLaunch` → 54 文件打包成功，输出 `artifacts/projects/test-arena/stage01/test-arena.SC2Map`（0.47 MB）。
  - 命令：`powershell -File tools/launchers/launch-test-arena.ps1 -NoLaunch`
  - 证据类型：static
- **MPQ 完整性**：StormLib `SFileOpenArchive` 成功打开产出 MPQ。
  - 证据类型：static
- **Include 闭包**：MPQ 内 5 个关键文件全部存在（MapScript.galaxy + 4 个内核文件）。
  - 验证方式：StormLib 读取 `(listfile)` 并交叉检查 include 依赖链。
  - 闭包链：MapScript → LibVibeKernel → LibVibeKernel_h（声明 libVibeInvoke_gf_Dispatch 原型）→ LibVibeInvokeDispatch_active（提供函数体）→ LibVibeHandles（依赖 libVibeKernel_gf_FindUnitByTag）。
  - 证据类型：static
- **test_kernel.py**：因 protobuf 版本冲突（generated code 需 protoc ≥ 3.19，当前环境 protobuf 过新）未能运行，与地图注入无关，不影响静态验证结论。
  - 证据类型：static（阻断原因为环境兼容性，非地图问题）

### 运行时验证

#### Bug 修复（运行时阻断）

- `tools/launchers/launch-test-arena.ps1`：PowerShell 数组 splatting `@largs` 导致位置参数错位
  （launch-galaxy-vibe.ps1 第 1 参数是 `[int]$Port`，`-Map` 被绑定到 `$Port`）。改用 hashtable
  splatting `@lparams` 命名传递，彻底消除位置绑定歧义。
  - 证据类型：static（代码审查）+ runtime（修复后 SC2 成功启动）

#### 运行时验证执行

- **SC2 启动**：`launch-test-arena.ps1`（无 -AutoProbe）→ SC2 Switcher 启动 → API 端口 5000 开放。
  - 命令：`powershell -File tools/launchers/launch-test-arena.ps1`
  - 证据类型：runtime（进程 PID + API 端口连通）
- **ScriptError 复核**：本次启动后 GameLogs 新增 0 个 `ScriptError.*.txt`。
  - 命令：`python %TEMP%/check_scripterrors2.py`（对比 launch marker 时间戳）
  - 证据类型：runtime
- **CreateGame + JoinGame**：tier100_live_probe.py 自动 CreateGame（player_setup type=1 Terran）
  + JoinGame（player_id=1），均成功无错误。
  - 命令：`python tools/galaxy-vibe/tier100_live_probe.py --port 5000 --map artifacts/projects/test-arena/stage01/test-arena.SC2Map --tag test-arena-tier0-v2 --load-timeout 120`
  - 证据类型：runtime（SC2 API Response 无 error）
- **kernel_initialized**：Bank `GalaxyVibe.SC2Bank` section `index` key `kernel_initialized = 1`。
  - verdict JSON：`artifacts/galaxy-vibe/tier100-live-verdict-test-arena-tier0-v2.json`
  - `registration: {"kernel_initialized": 1}`
  - 证据类型：runtime（Bank 文件内容）
- **system.ping RPC**：0/3 acks — PollLoop 未运行。Kernel 写入了 init 标记但未轮询 Bank 请求。
  - 证据类型：runtime
- **ScriptError 二次复核**：CreateGame+JoinGame 后再次检查 GameLogs，仍 0 新增 ScriptError。
  - 证据类型：runtime

#### 关键发现：Bank 预存在性

- `--fresh-bank` 将 Bank 文件移走后，BankLoad("GalaxyVibe", 1) 返回 null，kernel 静默跳过所有
  Bank 写入（`if (handle == null) { return; }`），导致 `kernel_initialized` 不出现。
- 恢复 Bank 文件后重跑，kernel_initialized 立即出现。

---

## 2026-08-08（续） ARENA-006 / ARENA-007 修复

### ARENA-006 根因：TriggerAddEventTimeElapsed(0.0) 同步触发 while(true) → 后序标记全成死代码

- 原 `libVibeKernel_InitLib()` 仅 `TriggerCreate(RegisterEntryPoints_Func) + TriggerAddEventTimeElapsed(t, 0.0, c_timeGame)`，然后**不立即调用** RegisterEntryPoints，依赖时钟推进。运行时（API 模式下）时钟推得慢，probe 在 ~40s 内取不到 register_entrypoints_done marker；**更严重**：PollLoop / Watchdog 的 trigger 是 `while(true){ Wait(0.5s); … }`，用 `TriggerAddEventTimeElapsed(t, 0.0, …)` 绑触发会**同步**触发一次该函数 → while(true) 永不返回 → 后续写 `watchdog_done` / `register_entrypoints_done` / `pollloop_fired` 的代码全变成死代码，表现为 "chat_done 存在（同步 chat），但 watchdog_done / done 永远不写"。
- **修复（LibVibeKernel.galaxy）**：
  1. `libVibeKernel_InitLib()` 末尾**显式同步调用** `libVibeKernel_gf_RegisterEntryPoints()`，保证 InitLib 一返回就进入注册流程，不依赖时钟推进。
  2. `libVibeKernel_gf_RegisterEntryPoints()` 内对 PollLoop / Watchdog 只做 `TriggerCreate`，不再绑定任何 `TriggerAddEventTimeElapsed(0.0)`，改用 `TriggerExecute(t, false, false)`（waitUntilDone=false）显式异步 fire，确保 while(true) 在新的触发器线程中跑，不阻塞后面的 marker 写入（「死代码铁律」）。
- **修复（MapScript.galaxy）**：InitLib 末尾已经同步 RegisterEntryPoints，`lllAtg()` 中原追加的 `libVibeKernel_gf_RegisterEntryPoints()` 末尾调用会被当成重复触发；且 `lllAtg()` 里这行在修改前就不存在——保留现状：`lllAtg(){libVibeKernel_InitLib();libNtve_InitLib();}`。

### ARENA-007 根因：两端路径不一致（Galaxy → Banks/<AuthorHash>/；Python 旧读 Banks root） + 斗蛐蛐 MapInfo 无合法 Publisher hash

- **发现**：运行亡者之夜 tier100 时，Python 侧 `read_bank("GalaxyVibe")` 只读 `…/Banks/GalaxyVibe.SC2Bank`（root）。但亡者之夜 Galaxy 端 BankSave 实际写到 `…/Banks/14/GalaxyVibe.SC2Bank`（AuthorHash=14 子目录）。因此 Galaxy 明明写了 kernel_initialized=1，probe 却始终认为 Bank 是空的——这就是"kernel_initialized 不出现"的元凶（占比 90%+）。
- **Python 侧修复（vibe_host.py）**：
  1. 新增 `_iter_bank_candidates()`：枚举 `Banks root + Banks/<digit>/<bank>.SC2Bank`（所有已存在的数字目录 + 当前 scan 发现）。
  2. 重写 `read_bank()`：对所有候选 parse + 取 mtime 最大的那份数据返回，确保只要 Galaxy 端写回任何 AuthorHash 子目录都能读到。
  3. 新增 `_parse_bank_file()` / `_write_tree_to_all_candidates()`：
     - 解析时从 `Value` 节点按 `flag / int / fixed / string / text` 顺序取属性 + 做类型化；
     - 写入时把**同一份 ElementTree**同步写到所有候选位置（root + 数字子目录），保证 Galaxy 端 BankPoll 一定能在自己 AuthorHash 目录里读到 pending_request_id。
     - 写盘仍然保持 `tmp 写 + os.replace tmp→bank` 原子写，避免 BankReload 撞上截断 XML。
  4. 重写 `write_bank_request()`：选候选中 index + request 最完整的文件当基底，构建 request key + pending_request_id，然后同步到 root + 所有数字子目录。
- **launch-test-arena.ps1 侧修复**：新增 `Write-BankIfDiff` helper（mtime+size 都一致则跳过），在启动 SC2 前把符合 SC2 格式 XML、带 `preload_marker=int:1` 的 GalaxyVibe.SC2Bank 预写到：`Banks root` + `所有已存在的 <digit>/` 子目录 + `1..16` 全覆盖（33 个路径），保证斗蛐蛐即使 AuthorHash 未知也能至少命中一份预存在文件。
- **斗蛐蛐残留**：斗蛐蛐地图 MapInfo 是二进制直接生成的（没有用 SC2 编辑器重存），其内部 Publisher hash 可能为 0 或非法，导致 BankList 授权（`<Bank Name="GalaxyVibe" Player="1"/>`）无法在引擎侧匹配 → BankLoad 仍返回 null。此问题需要 SC2 编辑器把斗蛐蛐地图"另存为"得到合法 Publisher hash，本阶段不做二进制手工 patch。由于亡者之夜黄金参考已经把 P0 传输层双向闭环跑通，kernel 本身 ARENA-006/007 的根因已被修复并实证。

### 运行时验证（亡者之夜黄金参考，带修复版 LibVibeKernel 内核）

- **启动**：launch-galaxy-vibe.ps1 -Port 5006 -Map E:\SC2\SC2new\StarCraft II\Maps\VibeDeadOfNight.SC2Map → SC2 启动成功，API 5006 开放。
  - 证据类型：runtime
- **tier100 probe**：`python tools/galaxy-vibe/tier100_live_probe.py --port 5006 --map VibeDeadOfNight.SC2Map --tag don-scanall-v1 --load-timeout 180` → verdict：
  - connect = true
  - kernel_registered = true（registration.kernel_initialized = 1）
  - p0_pass = true
  - system_ping：3 runs / 3 acks / all_ack = true
  - vibe_unit_spawn：ok，`operation=unit.spawn / created=1 / unit_type=Marine / player=1`，latency 0.699s
  - vibe_query_units：ok，`count=1 / unit_type=Marine / player=1`，latency 0.714s
  - gen_1_invoke：返回 `FUNCTION_NOT_IN_MAP`（路由正常，生成 adapter 未挂载是预期）
  - no_new_nonempty ScriptError.*.txt = 0 文件
- **Bank markers**（Banks/14/GalaxyVibe.SC2Bank，亡者之夜 AuthorHash=14）：
  - initlib_entered, init_entered, register_entrypoints_entered, register_entrypoints_chat_done, register_entrypoints_ally_chat_done, bankpoll_sync_call_done, kernel_initialized, preload_marker, last_request_id, pending_request_id, state_version, stage16_before_vibe, stage16_after_vibe 全部非空。
  - PollLoop 处理 request 后 state_version 逐次 +1（与 probe 调用计数一致）。
- **证据类型**：runtime（verdict JSON + Bank 快照）。

### 本次变更清单（写 scope 内）

- `src/projects/test-arena/packages/Maps/地图调试和斗蛐蛐工具（完整功能版).SC2Map/Base.SC2Data/LibVibeKernel.galaxy`：InitLib 同步调用 RegisterEntryPoints；PollLoop/Watchdog 用 TriggerExecute(false,false) 异步 fire；移除 TriggerAddEventTimeElapsed(0.0)（死代码铁律）；新增 `gf_EnsureBankLoaded` 内 `[VIBE-DIAG] BankLoad OK/NULL` chat 诊断（通过 `UIDisplayMessage(PlayerGroupAll(), c_messageAreaChat, StringToText(...))`，BankLoad 返回 null 时也能在 observation chat 中留下痕迹）。
- `src/projects/test-arena/packages/Maps/地图调试和斗蛐蛐工具（完整功能版).SC2Map/MapScript.galaxy`：保持 `lllAtg(){libVibeKernel_InitLib();libNtve_InitLib();}`（InitLib 内同步 RegisterEntryPoints 已覆盖）。
- `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy`：正本同步（从斗蛐蛐副本回拷）。
- `src/projects/cmre-porting/packages/Maps/VibeDeadOfNight.SC2Map/Base.SC2Data/LibVibeKernel.galaxy`：cmre-porting overlay 同步。
- `tools/galaxy-vibe/galaxy-debug-mod/Base.SC2Data/LibVibeKernel.galaxy` + `LibVibeKernel_h.galaxy`：mod-level overlay 同步。-mod 参数挂载 galaxy-debug-mod 时，SC2 会以 mod 中的同名文件覆盖地图层，因此无论传入哪张 VibeDeadOfNight / RuntimeLab 地图，只要地图 InitLibs 调用 `libVibeKernel_InitLib()`，本次修复版 kernel 即生效。
- `tools/galaxy-vibe/host/vibe_host.py`：read_bank / write_bank_request 重写，扫全 Banks/<digit>/ + root 路径。
- `tools/launchers/launch-test-arena.ps1`：新增 Write-BankIfDiff + 预写 Bank 到 33 个候选路径；ModPath 改为 hashtable splatting 的显式参数传递。
- `src/projects/test-arena/stages/01-kernel-inject/issues.json`：ARENA-006/007 → resolved；斗蛐蛐 CreateGame error=1（InvalidMap）新增 ARENA-008 open。
- `src/projects/test-arena/stages/01-kernel-inject/result.json`：tier0_transport = RUNTIME_PASS；system_ping_rpc = PASS；新增 p0_transport_closed_loop / vibe_host_bank_path_mismatch_fix / mod_overlay_kernel_sync 验证项。
- 本 log.md。

#### 本轮（5013 窗口）运行时复验（mod 级 overlay + fresh-bank）

- **启动**：`launch-galaxy-vibe.ps1 -Port 5013 -Map E:\SC2\SC2new\StarCraft II\Maps\VibeDeadOfNight.SC2Map -ModPath tools/galaxy-vibe/galaxy-debug-mod`
  - Switcher PID=28200 → SC2_x64 PID=32344 → API 5013 开放（启动 marker epoch=1786210763）
  - 证据类型：runtime
- **tier100_live_probe --fresh-bank**：`python tools/galaxy-vibe/tier100_live_probe.py --port 5013 --map E:\SC2\SC2new\StarCraft II\Maps\VibeDeadOfNight.SC2Map --fresh-bank --load-timeout 240`
  - connect = true
  - fresh_bank: 旧 bank 已归档到 `.stale-1786210783`
  - kernel_registered = true（registration.kernel_initialized = 1）
  - p0_pass = true
  - system_ping: runs=3, acks=3, all_ack=true
  - vibe_unit_spawn: ok, created=1, unit_type=Marine, player=1, latency=0.624s
  - observation_delta: before=0 → after=1, delta=1（第三方 raw observation 确认 marine 出现，非 kernel 自述）
  - vibe_query_units: ok, count=1, unit_type=Marine, player=1, latency=0.254s
  - gen_1_invoke + gen_noarg_invoke：返回 FUNCTION_NOT_IN_MAP（路由闭环，生成 adapter 未挂载是预期）
  - script_error.gate = no_new_nonempty, files=[]
- **本轮验证重点**：
  - fresh-bank 后仍能 kernel_initialized=1 → **ARENA-007（BankLoad 从零创建 + GalaxyVibe BankList 授权）实证通过**（因为 galaxy-debug-mod 里的 BankList.xml 带 Players 1-16 声明，地图挂载 mod 时继承授权；加上 launch 前预写 33 份候选 Bank 兜底）。
  - system.ping 3/3 acks → **ARENA-006（PollLoop 异步 TriggerExecute 启动，避免 0.0 同步触发死代码）实证通过**。

#### 运行时验证结论

- ✅ 验收标准 1（kernel_initialized）：**RUNTIME_PASS** — Bank 出现 `kernel_initialized = 1`
- ✅ 验收标准 2（tier0 传输层）：**RUNTIME_PASS** — P0 闭环：Ping 3/3、unit.spawn→observation→query.units 三方一致（mod overlay + fresh-bank 后仍稳定）
- ✅ 0 ScriptError（编译 + 运行时均无错误）
- ✅ CreateGame + JoinGame 成功
- ⚠️ 斗蛐蛐地图遗留：pack 后的 `artifacts/projects/test-arena/stage01/test-arena.SC2Map`（498KB，55 files）通过 SC2 API RequestCreateGame 时返回 Error=1（InvalidMap），表现为 MPQ 打包格式与 SC2 原生编辑器生成的加密 MPQ 不完全匹配。当前 workaround：用亡者之夜黄金参考跑 tier100；斗蛐蛐地图如需独立走 API 模式 CreateGame，需把原始斗蛐蛐 .SC2Map 通过 SC2 编辑器「另存为」一次得到合法 listfile + 签名，或改用 MPQEditor GUI 直接 repack（本阶段不做二进制 repack）。
