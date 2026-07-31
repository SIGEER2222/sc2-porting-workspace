# Stage Plan: 05-objective-playtest

> 阶段目标：在亡者之夜地图上完成一个夜间波次的目标玩法测试，验证 Reborn 指挥官在完整游戏循环中的表现。

## 1. 前置条件（已满足）

- Stage 03 PASS：15 个指挥官单位替换全部 runtime 验证通过
- Stage 04 PASS：G1-G5 功能验证全部通过（生产面板/技能/战斗/双指挥官/无 ScriptError）
- Vibe 框架真机验证 PASS：P0 传输闭环 + P1 REPL 14/15 PASS + G3 战斗闭环 9/9 PASS

## 2. 阶段目标

依据 `self-assessment.md` 的 "Next quality bar"：

> Play the objective and one terminal path to completion, then repeat the same contract for a second commander before treating this as a reusable Reborn series port.

本阶段聚焦：
1. 在亡者之夜地图上完成至少 1 个夜间波次（普通模式，非 API）
2. 验证 Reborn 指挥官在完整游戏循环中的表现（基地运营 + 波次防守）
3. 通过 Bank 文件收集游戏运行证据

## 3. 验证方法

### 3.1 目标玩法测试（runtime）

- 用普通模式（非 API）启动带 Reborn mod 的游戏
- 选择 Raynor 或 Abathur 指挥官
- 让游戏自动运行 1-2 个夜间波次（或手动操作）
- 退出后检查 Bank 文件，确认：
  - 游戏正常运行（无 ScriptError）
  - 替换单位存活/参与战斗
  - 波次进度推进

### 3.2 游戏循环验证（runtime + Bank 证据）

- 检查 CMRERebornDebug.SC2Bank 中的游戏状态字段
- 检查是否有崩溃记录
- 检查 GameLogs 中的 ScriptError

## 4. 验收闸门

| 闸门 | 判据 | 证据类型 |
|---|---|---|
| G1 游戏启动 | Reborn mod 加载成功，游戏进入亡者之夜 | runtime |
| G2 波次推进 | 至少完成 1 个夜间波次（或游戏运行 5 分钟以上） | runtime |
| G3 替换单位存活 | Bank 文件显示替换单位存在 | runtime |
| G4 无崩溃 | 无新增 Crash/ScriptError | runtime |

## 5. Write Scope

- `src/projects/reborn-mods-cmre-integration/stages/05-objective-playtest/**`
- `artifacts/reborn-objective-playtest/**`

## 6. 非目标

- 完整战役通关（属 Stage 06+）
- 全部 15 个指挥官玩法测试（本阶段只验 1-2 个）
- 平衡性调整（属 Stage 06+）
- 修改 Reborn mod 源码（read-only）

## 7. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 普通模式下游戏需要手动操作 | 让 AI 自动运营，或仅观察波次防守 |
| Bank 文件可能不记录波次进度 | 改用 GameLogs 的时间戳作为游戏运行证据 |

## 8. Completion Gate

1. 1-2 个指挥官的 G1-G4 全部 PASS
2. `result.json` + `issues.json` + `log.md` 完整
3. 证据分类标注（static/runtime/inference）
4. 无新增 ScriptError
