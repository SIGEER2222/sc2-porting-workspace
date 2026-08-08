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

### 待办（运行时验证）

- 启动地图（`launch-test-arena.ps1 -AutoProbe`）→ vibe_host 连接 → Bank 出现 `kernel_initialized` 标记。
- 复核 GameLogs 是否有本次启动新增的 `ScriptError.*.txt`。
- 运行时验证需用户确认后执行。
