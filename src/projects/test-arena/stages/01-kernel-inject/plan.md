# Stage 01 — kernel-inject

## 目标

把斗蛐蛐调试地图（`地图调试和斗蛐蛐工具（完整功能版).SC2Map`）注入 LibVibeKernel，
搭出可被 `vibe_host` 连接的测试骨架。本阶段只做 tier0 传输层注入，不挂载 function.invoke
适配器分片；AI 盟友与 ML 训练在后续阶段承载。

## 背景

- 地图来源：`C:\Users\22448\Downloads\地图调试和斗蛐蛐工具（完整功能版).SC2Map`
- 地图 MapScript.galaxy 为混淆代码（`lll*` 变量名），但结构上有标准 `InitMap()`，
  NativeLib 初始化包在 `lllAtg()` 内（第 2 行 `void lllAtg(){libNtve_InitLib();}`）。
- 地图无 commander mod 依赖，是纯净独立地图，适合做测试沙盒。
- 现有注入流程研究结论（static 证据）：
  - 亡者之夜 `MapScript.galaxy` 第 14 行 `include "LibVibeKernel"`，第 21 行 `libVibeKernel_InitLib();`
    证明注入 = include 行 + InitLib 调用。
  - `tools/galaxy-vibe/kernel/LibVibeKernel.galaxy` 第 1-2 行自 include NativeLib + LibVibeKernel_h，
    自洽。
  - `tools/galaxy-vibe/mpq/mpq_patch_kernel.py` 只修 PollLoop bug，不做 include 注入；
    `mpq_build_gen_map.py` 假设地图已预埋 include + InitLib，且 GEN_SRC 硬编码亡者之夜。
  - 结论：首次注入需手动 patch MapScript.galaxy（无现成全自动入口）。

## 注入方案（tier0 最小骨架）

### MapScript.galaxy patch（2 处，最小侵入）

1. 第 1 行 `include "TriggerLibs/NativeLib"` 之后追加 3 行 include：
   ```
   include "LibVibeKernel"
   include "LibVibeHandles"
   include "LibVibeInvokeDispatch_active"
   ```
2. 第 2 行 `void lllAtg(){libNtve_InitLib();}` 改为
   `void lllAtg(){libVibeKernel_InitLib();libNtve_InitLib();}`
   （vibe kernel 最先初始化，与亡者之夜注释要求一致）。

### Base.SC2Data/ 内核文件（4 个）

从 `tools/galaxy-vibe/kernel/` 复制：
- `LibVibeKernel.galaxy`
- `LibVibeKernel_h.galaxy`
- `LibVibeHandles.galaxy`

tier0 stub（从 `src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map/Base.SC2Data/LibVibeInvokeDispatch_active.galaxy` 复制）：
- `LibVibeInvokeDispatch_active.galaxy`（tier0：所有 function_id 返回 FUNCTION_NOT_IN_MAP）

### include 闭包自洽性

- `LibVibeKernel.galaxy` 自 include `LibVibeKernel_h`（声明 `libVibeInvoke_gf_Dispatch` 原型）。
- `LibVibeInvokeDispatch_active.galaxy`（tier0）提供 `libVibeInvoke_gf_Dispatch` 函数体，
  依赖 `libVibeKernel_gf_MakeResponse` 原型与 `libVibeKernel_gv_currentSession` 等全局（来自 LibVibeKernel）。
- `LibVibeHandles.galaxy` 依赖 `libVibeKernel_gf_FindUnitByTag`（来自 LibVibeKernel）。
- 闭包顺序：LibVibeKernel → LibVibeHandles → LibVibeInvokeDispatch_active，均跟在 NativeLib 之后。

## writeScope

- `src/projects/test-arena/**`
- `tools/galaxy-vibe/consumers/test-arena/**`
- `tools/launchers/launch-test-arena.ps1`
- `tools/launchers/lib/test-arena-overlay.ps1`
- `artifacts/projects/test-arena/**`

## 步骤

1. 解包原始 .SC2Map 到 `src/projects/test-arena/packages/Maps/地图调试和斗蛐蛐工具（完整功能版).SC2Map/`（解包形式，与 CMRE packages 一致）。
2. patch MapScript.galaxy（2 处）。
3. 复制 4 个内核文件到 `Base.SC2Data/`。
4. 配置 `tools/galaxy-vibe/consumers/test-arena/consumer.json`（map/commander=null/launcher/recipe=tier0 ping）。
5. 新建 `tools/launchers/launch-test-arena.ps1`（独立地图启动入口，无 commander mod，挂 API 端口）。
6. 静态验证：galaxy 文件完整性 + include 闭包检查。
7. 运行时验证（下一步）：启动地图 → vibe_host 连接 → Bank 出现 kernel_initialized。

## 验证命令

- 静态：`python tools/galaxy-vibe/tests/test_kernel.py`（kernel 单元）+ 人工核对 include 闭包。
- 运行时：`launch-test-arena.ps1` 启动后 vibe_host P0 探针检查 kernel_initialized。

## 完成判据

- 地图解包结构完整，MapScript.galaxy 已 patch 且备份原文件。
- 4 个内核文件就位。
- consumer.json + launcher 就位。
- 静态验证通过。
- 运行时联调留待用户确认后执行（本阶段先交付骨架）。
