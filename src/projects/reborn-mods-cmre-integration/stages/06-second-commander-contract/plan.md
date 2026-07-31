# Stage Plan: 06-second-commander-contract

> 阶段目标：对第二个指挥官重复 MVP 契约，证明 Reborn 移植的可复用性。

## 1. 前置条件

- Stage 05 PASS：目标玩法测试完成（1 个指挥官完成 1 个波次）
- Vibe 框架真机验证 PASS：可用于战斗和状态验证

## 2. 阶段目标

依据 `self-assessment.md` 的 "Next quality bar"：

> Repeat the same contract for a second commander before treating this as a reusable Reborn series port.

本阶段聚焦：
1. 选择第二个指挥官（Abathur，与 Stage 05 的 Raynor 不同）
2. 重复 Stage 05 的契约：完成 1 个夜间波次
3. 验证 Abathur 的替换单位（HunterKiller）在完整游戏循环中的表现
4. 对比两个指挥官的差异，确认 Reborn 移植的可复用性

## 3. 验证方法

### 3.1 第二指挥官玩法测试（runtime）

- 用普通模式（非 API）启动带 Reborn mod 的游戏，选择 Abathur
- 让游戏自动运行 1-2 个夜间波次
- 退出后检查 Bank 文件，确认 HunterKiller 存活/参与战斗

### 3.2 可复用性验证（static + runtime）

- 对比 Raynor 和 Abathur 的测试结果
- 确认 Reborn mod 的 15 个指挥官都遵循相同的替换模式
- 确认 vibe 框架可复用于不同指挥官的验证

## 4. 验收闸门

| 闸门 | 判据 | 证据类型 |
|---|---|---|
| G1 Abathur 游戏启动 | Reborn mod 加载成功，Abathur 替换生效 | runtime |
| G2 Abathur 波次推进 | 至少完成 1 个夜间波次 | runtime |
| G3 HunterKiller 存活 | Bank 文件显示 hunterkiller_p1_count ≥ 1 | runtime |
| G4 无崩溃 | 无新增 Crash/ScriptError | runtime |
| G5 可复用性 | Raynor + Abathur 都通过 G1-G4，模式一致 | runtime + static |

## 5. Write Scope

- `src/projects/reborn-mods-cmre-integration/stages/06-second-commander-contract/**`
- `artifacts/reborn-second-commander/**`

## 6. 非目标

- 完整战役通关（属 Stage 07）
- 全部 15 个指挥官玩法测试（本阶段只验 2 个）
- 平衡性调整（属 Stage 07）

## 7. Completion Gate

1. Abathur 的 G1-G4 全部 PASS
2. G5 可复用性 PASS（Raynor + Abathur 模式一致）
3. `result.json` + `issues.json` + `log.md` 完整
4. 无新增 ScriptError
