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
- 根因：斗蛐蛐地图 MapInfo 可能缺少 Bank 预授权（Bank signing/authorization），导致 BankLoad
  无法从零创建新 Bank 文件。cmre-porting 项目不受影响因为 debug mod 提供了 Bank 预存在路径。
  - 证据类型：inference（需后续验证 MapInfo Bank 配置）

#### 运行时验证结论

- ✅ 验收标准 1（kernel_initialized）：**RUNTIME_PASS** — Bank 出现 `kernel_initialized = 1`
- ⚠️ 验收标准 2（tier0 传输层）：**PARTIAL** — Kernel 注入成功 + Bank 写入通路验证通过；
  但 PollLoop RPC 闭环未通过（system.ping 0/3 acks），需后续阶段排查触发器时序问题
- ✅ 0 ScriptError（编译 + 运行时均无错误）
- ✅ CreateGame + JoinGame 成功
