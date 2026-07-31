# Stage Plan: 04-functional-verification

> 阶段目标：在 vibe 框架真机验证通过的前提下，对重生虫心指挥官进行功能验证（技能/生产面板/战斗），完成 self-assessment 中定义的 "Next quality bar"。

## 1. 前置条件（已满足）

- Stage 03 PASS：15 个指挥官单位替换全部 runtime 验证通过
- Vibe 框架真机验证 PASS：P0 传输闭环 + P1 REPL 14/15 PASS
- Vibe REPL 工具可用：`tools/galaxy-vibe/galaxy_repl.py` 支持 spawn/query/step/cheat/info/kill

## 2. 阶段目标

依据 `reborn-zexpedition03-raynor-mvp/stages/04-mvp-feasible/self-assessment.md` 的 "Next quality bar"：

> Play the objective and one terminal path to completion, then repeat the same contract for a second commander before treating this as a reusable Reborn series port.

本阶段聚焦：
1. 验证 Reborn 指挥官的**生产面板**完整性（建筑可建、单位可产）
2. 验证 Reborn 指挥官的**技能可用性**（指挥官技能按钮存在且可触发）
3. 验证 Reborn 指挥官的**战斗功能**（替换单位可攻击、可受伤）
4. 至少对 2 个指挥官（Abathur + Raynor）重复验证契约

## 3. 验证方法

### 3.1 生产面板验证（static + runtime）

- **static**：通过 galaxy-toolkit 解析 Reborn mod 的 Catalog，列出每个指挥官的生产建筑和可产单位
- **runtime**：用 vibe REPL 进入游戏后，用 `cheat minerals on` / `cheat gas on` 开启资源作弊，用 `spawn` 创建生产建筑，用 `query` 检查生产面板按钮

### 3.2 技能可用性验证（static + runtime）

- **static**：解析 Catalog 中每个指挥官的 ability 定义，确认技能按钮存在
- **runtime**：用 vibe REPL 的 `obs` 命令查看单位能力列表，确认技能已挂载

### 3.3 战斗功能验证（runtime）

- 用 `spawn` 创建替换单位 + 敌方单位
- 用 `step` 推进游戏循环
- 用 `query` 确认伤害事件发生（单位血量变化或单位死亡）

## 4. 验收闸门

| 闸门 | 判据 | 证据类型 |
|---|---|---|
| G1 生产面板 | 至少 1 个建筑可生产至少 1 个单位 | static + runtime |
| G2 技能按钮 | 指挥官技能按钮存在于 Catalog 且单位有对应 ability | static + runtime |
| G3 战斗功能 | 替换单位可对敌方造成伤害（单位死亡或血量下降） | runtime |
| G4 双指挥官契约 | Abathur + Raynor 都通过 G1-G3 | runtime |
| G5 无新增 ScriptError | 验证过程无新增 ScriptError | runtime |

## 5. Write Scope

- `src/projects/reborn-mods-cmre-integration/stages/04-functional-verification/**`
- `artifacts/reborn-functional-verification/**`

## 6. 非目标

- 完整战役通关（属 Stage 05+）
- 全部 15 个指挥官功能验证（本阶段只验 2 个）
- 平衡性调整（属 Stage 06+）
- 修改 Reborn mod 源码（read-only）

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| SC2 API 模式下 Reborn mod 崩溃（ACCESS_VIOLATION） | 使用普通模式启动游戏，仅用 vibe REPL 做观察；若 API 崩溃则改用 Bank 文件收集证据 |
| 生产面板按钮无法通过 API 直接查询 | 用 `spawn` 创建建筑后 `step` 若干帧，再 `query` 检查是否有新单位被自动生产（AI 控制） |
| 技能触发无法通过 API 验证 | 降级为 static 验证（Catalog 解析）+ inference 分类 |

## 8. Completion Gate

1. 2 个指挥官（Abathur + Raynor）的 G1-G3 全部 PASS
2. `result.json` + `issues.json` + `log.md` 完整
3. 证据分类标注（static/runtime/inference）
4. 无新增 ScriptError
