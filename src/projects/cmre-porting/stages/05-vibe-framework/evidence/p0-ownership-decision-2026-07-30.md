# P0 Evidence — sc2_simulator 仓库所有权决策

- 日期：2026-07-30
- 决策对象：`tools/sc2-ally-bot/src/sc2_simulator`（候选规范引擎）
- 上游约束：
  - `simulator-first-platform-plan.md` §8「Candidate canonical engine in its own repository boundary; requires acceptance, not blind adoption」
  - `simulator-first-platform-plan.md` P0「Decide repository ownership for `sc2_simulator` without copying or editing an external repository through an undeclared boundary」
  - `AGENTS.md`「Do not edit registered read-only sources or external repositories」「Do not add files outside the active project, approved adapter package, or tooling wrapper」
  - `project.json` writeScope：`src/projects/cmre-porting/stages/05-vibe-framework/**`、`src/projects/cmre-porting/vibe/**`、`tools/launchers/vibe.ps1`、`artifacts/galaxy-vibe/**`
- 证据分类：`static`（边界与依赖分析，见 capability matrix §0）

## 1. 现状

- `tools/sc2-ally-bot` 是工作区内**普通目录**（非 submodule、非 `.gitmodules` 注册项）。
  `workspace.json` 的 `tools` 列表**未登记 `sc2-ally-bot`** → 当前是**未声明边界**。
- `sc2_simulator` 与 `ally_bot` 完全解耦（零互相 import），自包含纯 Python，零外部依赖。
- 现有 `project.json` writeScope **不含** `tools/sc2-ally-bot/**`，故本阶段**无权修改 `sc2_simulator`**。

## 2. 决策

**P0 阶段：将 `tools/sc2-ally-bot/src/sc2_simulator` 声明为只读候选参考引擎，不提升为 owned 包、不编辑、不复制。**

具体：

1. **不编辑**：本阶段（P0）及后续 P1/P2 阶段，**不得修改 `tools/sc2-ally-bot/src/sc2_simulator/**` 任何文件**。
   它是候选引擎，需经 P3 核心运行时验收后才可考虑提升。在此之前的所有消费者集成，必须通过
   **项目本地适配层**（`src/projects/cmre-porting/vibe/**`，在 writeScope 内）以 import 方式消费其公共符号，
   或通过新建的 §4.4 顶层契约层适配，绝不在 `sc2_simulator` 内打补丁。

2. **不复制**：不在 `src/projects/cmre-porting/**` 或其他位置复制 `sc2_simulator` 源码副本。
   复制会制造两份漂移源，违反「single source of truth」与 AGENTS.md「Do not create a shared abstraction
   until at least two real consumers require the same behavior」。消费方式是 import，不是 fork。

3. **不盲采纳**：`sc2_simulator` 当前公共 API 缺失（`__init__.py` 仅导出 `cli`）、Catalog 无内容哈希/无保真度、
   G7 触发器是死代码、空军战斗未接入、行为 multiplier 未接入规则（见 capability matrix）。
   **这些缺口必须在 P1/P2/P3 通过验收后才能称其为规范引擎**。验收前，消费者代码不得假设其行为正确。

4. **边界声明**：建议在后续 `workspace.json` 维护中把 `tools/sc2-ally-bot` 登记为
   `kind: external-repository`、`writePolicy: read-only`（与 `galaxy-toolkit` 等同级），使其边界显式化。
   该登记是 `workspace.json` 的变更，不在本阶段 writeScope 内，**记为 follow-up，不在 P0 执行**。

## 3. 提升路径（非 P0 执行，仅声明闸门）

`sc2_simulator` 从「只读候选」提升为「owned 规范引擎」须满足全部：

- P3 核心运行时验收通过（G1-G8 八门动态验证，特别是 G7 触发器接入、空军战斗、行为 multiplier 接入）。
- §4.4 顶层契约（Catalog/Scenario/Observation/Action/Snapshot/Trace/Capability）建立并通过一致性测试。
- §4.2 IR 字段溯源（source hash + IR schema version + fidelity）补齐，Catalog 内容哈希可计算。
- 届时需单独申请 writeScope 扩展（新增 `tools/sc2-ally-bot/src/sc2_simulator/**` 或迁移到独立 owned 包），
  并在该 writeScope 批准后才可编辑。

提升前，对 `sc2_simulator` 的任何行为差异，消费者侧用**项目本地适配层**吸收，而非改引擎。

## 4. 既有 `tools/galaxy-vibe/*` 处置（P0 交付物之一）

依据 `simulator-first-platform-plan.md` §8 与 P0：

- `tools/galaxy-vibe/*` 重分类为 **spike**（前期 P0-P4 原型），**不得原样搬入 canonical 路径**。
  特别是 `galaxy_repl.py` 用 `call`（任意 `TriggerExecuteByName`），与「Kernel 不提供任意 call」冲突。
- 可复用离线内核仅作**候选**，非 canonical 行为：
  - `script_error_check.py`（ScriptError 闸门）→ 候选，待 P9 真机校准时复用。
  - `cold_cycle.py`（冷循环变更分类）→ 候选，待 P6 冷循环实现时复用。
  - `visual_loop.py`（ROI 差异 + 采集适配器抽象）→ 候选，待 P5 离线 2D viewer 时复用。
  - `summarize_verdict.py`（verdict 汇总）→ 候选，待 P1 证据包汇总时复用。
- canonical 代码落 `src/projects/cmre-porting/vibe/**`（writeScope 内）+ `artifacts/galaxy-vibe/**`（证据）。
  spike 仅作参考，不直接 import。

## 5. SC2 API / Bank / launcher 重分类（P0 交付物之一）

依据 `simulator-first-platform-plan.md` P0「Reclassify SC2 API, Bank and launcher work as optional adapters」：

- **SC2 API**（`tools/sc2api-baseline`、`reference/SC2-Neuro-API-Integration` 等）：重分类为**可选真实-SC2 适配器**，
  属 P9 差分校准，不阻塞本地 P0-P8。原 `transport_probe.py` 中 `Sc2ApiChatTransport` 的 guarded 占位保留，
  但不再是 P0 闸门候选。
- **Bank**（`NeuroIntegration.SC2Bank`、`CMRE-RUNTIME-003`）：重分类为**可选真实-SC2 适配器**。
  原 P0 传输闸门的 `BankReloadTransport` 候选路径降级为 P9。`CMRE-RUNTIME-003` 从「P0 transport 前提」降级为
  「P9 可选适配器 follow-up」。
- **launcher**（`tools/launchers/launch-cmre-alenger.ps1` 等）：重分类为**可选真实-SC2 入口**。
  `tools/launchers/vibe.ps1`（统一入口，writeScope 内）的 simulator 路径**不得启动 SC2**；
  仅在 P9 真机校准时通过批准 launcher 调用 SC2。
- **后果**：原 `VIBE-RUNTIME-001`（P0 runtime 阻塞于桌面 SC2）在 simulator-first 方向下**对本地关键路径不再阻塞**——
  本地关键路径是 `SimulatorTransport`，无 SC2 依赖。`VIBE-RUNTIME-001` 重分类为 P9 可选校准项。

## 6. P0 门校验

P0 门要求（`simulator-first-platform-plan.md` §5 P0 Gate）：

1. **「本地关键路径不依赖 SC2 可执行文件/API 端口/Bank/桌面截图/GameLogs」** —— 满足。
   证据：capability matrix §0，`sc2_simulator` 零 SC2/Bank/GameLogs 依赖；`SimulatorTransport`（P1 将建）
   以 `sc2_simulator` 为后端，纯 Python 本地运行。原 `transport_probe.py` 的真机 transport 已 guarded。
2. **「approved write scopes and package ownership are explicit before implementation starts」** —— 满足。
   - `project.json` writeScope 已精确声明（P0 不扩写）。
   - 本决策明确 `sc2_simulator` = 只读候选、`galaxy-vibe` = spike、SC2/Bank/launcher = 可选适配器。
   - 后续 P1+ 实现仅在 `src/projects/cmre-porting/vibe/**` + `tools/launchers/vibe.ps1` + `artifacts/galaxy-vibe/**` 内。

P0 交付物清单（`simulator-first-platform-plan.md` §5 P0 Deliverables）：

- [x] 标记 simulator-first-platform-plan.md 为 canonical 方向（见 plan.md 更新）。
- [x] 重分类 `tools/galaxy-vibe` 为 spike（本文件 §4）。
- [x] 保留可复用 assertion/visual diff/cold-cycle/verdict 代码为候选（本文件 §4）。
- [x] 重分类 SC2 API/Bank/launcher 为可选适配器（本文件 §5）。
- [x] 决策 `sc2_simulator` 仓库所有权（本文件 §1-§3）。
