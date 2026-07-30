# Stage Plan: SC2 Simulator-First Vibe Platform

> **Canonical direction**: `simulator-first-platform-plan.md`（本目录）。本 plan 是该方向在本阶段的落地说明。
>
> 方向重置（P0）：原「WYSIWYG 双循环 Vibe 框架」以真实 SC2 为首要运行时，被 `VIBE-RUNTIME-001`
> （沙箱无桌面 SC2）阻塞。`simulator-first-platform-plan.md` 把**确定性 headless 模拟器**定为首要开发/测试
> 运行时，真实 SC2 降为**可选适配器与差分校准目标**（P9）。本地关键路径不再依赖 SC2 可执行文件/API 端口/
> Bank/桌面截图/GameLogs。

## 1. 方向与重分类（P0 已完成）

依据 `simulator-first-platform-plan.md` §5 P0 与 §8：

| 既有区域 | 重分类后角色 | 处置 |
|---|---|---|
| `simulator-first-platform-plan.md` | **canonical 方向文档** | 本 plan 引用它，不复制 |
| `tools/sc2-ally-bot/src/sc2_simulator` | **只读候选规范引擎** | 不编辑、不复制；P1+ 消费者经项目本地适配层 import；提升为 owned 包需 P3 验收 + writeScope 扩展 |
| `tools/galaxy-vibe/*` | **spike** | 不原样搬入 canonical；`script_error_check`/`cold_cycle`/`visual_loop`/`summarize_verdict` 仅作候选，待对应阶段复用 |
| `tools/sc2api-baseline`、SC2 API、Bank、`launch-cmre-alenger.ps1` | **可选真实-SC2 适配器**（P9） | 不阻塞本地 P0-P8；`vibe.ps1` simulator 路径不得启动 SC2 |
| `src/projects/cmre-porting/vibe/protocol.py`、`transport_probe.py` | **协议层候选**（原 P0 离线核心） | 协议 schema + 幂等/拒绝逻辑保留，作为新 P1 `SimulatorTransport` 的协议基础；真机 transport 占位降级为 P9 |
| `artifacts/galaxy-vibe/**` | **证据区** | 命名任务/运行子目录 |

P0 证据：
- `evidence/p0-sc2-simulator-capability-matrix-2026-07-30.md`（能力矩阵审计）
- `evidence/p0-ownership-decision-2026-07-30.md`（所有权决策 + 重分类 + P0 门校验）

## 2. 阶段映射（simulator-first P0-P9）

| 阶段 | 交付物（节选） | 闸门（节选） | 状态 |
|---|---|---|---|
| **P0 方向与所有权** | 标记 canonical、重分类 galaxy-vibe/SC2/Bank/launcher、决策 sc2_simulator 所有权 | 本地关键路径无 SC2 依赖；writeScope 与所有权显式 | **PASS** |
| **P1 统一协议 + SimulatorTransport** | 共享请求/响应 schema、`SimulatorTransport` 适配器、能力协商、session/序号/校验和/幂等、首个本地 `vibe.ps1 run-task` | 20 顺序 ping ack；5 重复 ID 仅执行一次；5 非法零状态变化；关闭 session 拒绝旧请求；同 task/catalog/seed/版本同结果同 trace 哈希 | pending |
| **P2 Catalog 桥接 + 保真度记账** | schema-aware Catalog 提取器、版本化 Simulator IR、引用闭包+溯源、保真度/不支持规则报告、首个 CMRE Catalog 切片 | 每 IR 字段可溯源；缺失引用/不支持字段在 strict 模式失败；无源变更重导入同 Catalog 哈希；无绝对路径 | pending |
| **P3 核心运行时验收** | 按依赖序关闭 G1-G8（时间/事件/RNG/快照→实体→经济/建造/生产/研究→移动/寻路/碰撞/视野/迷雾→武器/护盾/弹体/伤害/死亡→技能/效果/行为/校验器/升级→触发器/区域/波次/目标/终局→货舱/召唤/变形/Addon/种族机制） | 快照/恢复保全状态；克隆与原体同 trace；事件序匹配声明优先级；ID 长期稳定；strict 场景不能用未批准 partial 行为；能力覆盖仅报运行时实际触发 | pending |
| **P4A Mod 开发消费者** | 首个真实 Mod 切片源→Catalog 导入、生产/战斗/升级场景、baseline/candidate 平衡对比、候选补丁验证 | 真实单位成本/伤害/生产时间变更可导入对比；报告显示预期机械变化且无关回归稳定；不支持行为在 verdict 可见 | pending |
| **P4B 盟友 AI 消费者** | Observation/Action 适配器、跟随/支援/防御/目标场景、命令反馈/延迟/动作错误模型、确定性 AI 决策 trace | AI 不能查隐藏状态；人力移动触发跟随；近距威胁触发支援/攻击；目标威胁覆盖低优先跟随；每单位每 loop 至多一条接受命令；10 模拟分钟无死锁/振荡/命令风暴 | pending |
| **P4C 战术验证消费者** | 战术场景模板、策略插件契约、集火/走位/撤退/技能时机指标、受控多种子 A/B runner | 两策略从相同初始快照+随机流运行；目标过滤/射程/移动/碰撞/视野/技能可用性影响决策；报告含置信度多种子指标而非单胜负 | pending |
| **P4D 任务与波次消费者** | 区域/计时器/触发器/波次/奖励/终局 DSL、难度曲线与可行性报告、生存/防御/护航/占领/自定义断言场景 | 正负终局路径被演练；重置/重放复现波次时机与结果；难度变化用声明指标与种子集测量 | pending |
| **P5 离线 WYSIWYG + 回放** | 2D 模拟器 viewer、时间线/实体检视/计算详情视图、快照 seek + 确定性回放、baseline/candidate 同步对比 | 渲染实体数/值匹配权威快照；seek 到某 loop 恢复同快照哈希；viewer 交互不能在 typed op 外改模拟态；失败断言打开到相关 loop/实体 | pending |
| **P6 热冷开发循环** | 热循环 typed op 操纵+查询/断言/快照/回退；冷循环源变更检测→静态校验→IR 重导入→场景重建→回归→证据 | 一个源值变更经一条命令完成 reload/A-B/断言/可视化/verdict；失败导入不替换上次有效 Catalog 快照；场景重置同初始快照哈希 | pending |
| **P7 意图驱动 Vibe Host** | 自然语言意图→版本化 `task.json`、热冷路由、候选补丁生成、≤3 轮证据驱动修正、完整迭代历史 | 固定 task 正确覆盖模拟 op/Mod 源变更/AI 评估/战术对比/非法 Catalog/不可满足断言；Host 不能在断言+回归未过时宣告成功；每次修正说明证据如何改变下次尝试 | pending |
| **P8 多消费者一致性 + 共享抽取** | 适配器一致性套件、跨消费者场景 fixture、仅对≥2 消费者证明的行为抽共享包、契约版本兼容/迁移策略 | Mod/盟友AI/战术/任务消费者各过自身验收；至少两消费者过同一共享契约实现才抽取；模拟器变更不能静默破坏外部工具契约 | pending |
| **P9 可选真实-SC2 差分校准** | 同任务契约的真实-SC2 backend、远程/独立执行证据包、模拟器-vs-SC2 差分报告、校准 fixture + 已知分歧注册表 | 真实 SC2 缺席不阻塞本地 P0-P8；真实证据标 `runtime`、模拟器证据标 `simulator`；分歧更新保真度记录与回归 fixture 而非隐藏 | pending |

## 3. 统一入口与 Write Scope

本地最终入口（`simulator-first-platform-plan.md` §3）：

```powershell
.\tools\launchers\vibe.ps1 run-task `
  -Project cmre-porting `
  -Backend simulator `
  -Task <task.json>
```

`-Backend simulator` 不启动 SC2；未来 `-Backend sc2` 须保持 task/observation/action/assertion/result 契约不变（P9）。

**本阶段 Write Scope（精确，源自 `project.json`，P0 不扩写）：**

- `src/projects/cmre-porting/stages/05-vibe-framework/**`（阶段目录 + 证据）
- `src/projects/cmre-porting/vibe/**`（项目本地 Kernel / Host / SimulatorTransport 适配层）
- `tools/launchers/vibe.ps1`（唯一批准入口 launcher，simulator 路径仅调本地 Python，不启动 SC2）
- `artifacts/galaxy-vibe/**`（所有运行证据与 verdict，命名任务/运行子目录）

**禁止**：修改 `tools/sc2-ally-bot/src/sc2_simulator/**`（只读候选）、修改只读源或自动生成的
`MapScript.galaxy`/`LibHASH*.galaxy`、新建 SC2 直启路径、运行时编译任意 Galaxy、进程/DLL 注入。

## 4. 当前焦点与下一步（P1）

P0 已关闭。下一阶段 **P1（统一协议 + SimulatorTransport）** 目标：

1. 在 `src/projects/cmre-porting/vibe/**` 内建立 §4.4 顶层契约的**项目本地适配层**（Catalog/Scenario/
   Observation/Action/Snapshot/Trace/Capability 的薄抽象），消费 `sc2_simulator` 公共符号（import，非 fork），
   不假设其行为正确（见 capability matrix 缺口）。
2. 复用既有 `protocol.py` 的 RPC schema + `SessionRegistry` 幂等/拒绝逻辑，实现 `SimulatorTransport`
   （以 `sc2_simulator` runner 为后端），满足 P1 闸门：20 ping ack / 重复 ID 去重 / 非法零副作用 /
   session 恢复 / 同 task+catalog+seed+版本同结果同 trace 哈希。
3. 落地首个本地 `vibe.ps1 run-task -Backend simulator` 路径（仅调本地 Python，不启动 SC2）。
4. 用手写 IR 关闭一个端到端场景（`simulator-first-platform-plan.md` §9 第 5 步），先不加导入复杂度。

P1 不做：Catalog XML 导入（P2）、改 `sc2_simulator` 源码（需 writeScope 扩展）、真机 transport（P9）。

## 5. 非目标

运行时编译任意 Galaxy；进程/DLL 注入；修改只读源；以端口/进程存活代替 ready；在多人正式环境开放调试命令；
声称与 SC2 渲染器视觉等价；把模拟器证据重标为真实-SC2 runtime 证据。

## 6. 证据分类

每项技术结论带分类与路径（`simulator-first-platform-plan.md` §6.4）：

- `static`：源码/依赖/schema/Catalog 分析
- `simulator`：headless 运行时内确定性执行
- `visual`：离线 debug viewer 输出
- `runtime`：真实 SC2 进程观测（P9 可选）
- `inference`：待上述验证的假设

## 7. Completion Gate（阶段完成 = 全部满足）

1. 声明产物存在；2. 各阶段验证命令通过；3. `result.json`/`issues.json`/`log.md` 完整；
4. 每项技术结论带证据分类与路径；5. 无新增 ScriptError（P9 真机时适用）；6. 热/冷路由正确；
7. 截图与结构化状态一致（P5 viewer）；8. 第二消费者通过后才完成共享抽取（P8）；
9. **本地完成门不依赖 SC2 安装**（§10 第 9 条）；10. 失败可从 task+源哈希+Catalog 哈希+快照+trace+seed 复现。

仅 static/编译/启动/端口/launcher 退出 0 任一单项不能宣告完成。
