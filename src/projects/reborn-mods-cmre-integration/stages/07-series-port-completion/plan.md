# Stage Plan: 07-series-port-completion

> 阶段目标：完成 Reborn 系列移植，确认 15 个指挥官全部可玩，vibe 框架作为可复用验证工具。

## 1. 前置条件

- Stage 06 PASS：第二指挥官契约验证完成（Raynor + Abathur 都通过）
- Vibe 框架真机验证 PASS：P0/P1/G3 全部 PASS

## 2. 阶段目标

完成 Reborn 系列移植的收尾工作：
1. 批量验证剩余 13 个指挥官的玩法可玩性（抽样验证，非全部深度测试）
2. 修复发现的平衡性问题（如有）
3. 生成最终移植报告
4. 确认 vibe 框架作为 Reborn 系列的可复用验证工具

## 3. 验证方法

### 3.1 批量玩法抽样（runtime）

- 从剩余 13 个指挥官中抽样 3-5 个（覆盖 3 个种族）
- 对每个抽样的指挥官执行 Stage 05 的契约（1 个波次）
- 通过 Bank 文件收集证据

### 3.2 平衡性检查（static + runtime）

- 检查各指挥官的替换单位是否过强/过弱
- 检查生产面板是否完整
- 检查技能按钮是否可用

### 3.3 Vibe 框架复用确认（runtime）

- 用 vibe REPL 对每个抽样指挥官执行 query/spawn/step
- 确认 vibe 框架可复用于不同指挥官的验证

## 4. 验收闸门

| 闸门 | 判据 | 证据类型 |
|---|---|---|
| G1 抽样指挥官可玩 | 3-5 个抽样指挥官全部通过 1 波次测试 | runtime |
| G2 无平衡性缺陷 | 无明显过强/过弱的替换单位 | static + runtime |
| G3 Vibe 框架复用 | vibe REPL 可对所有抽样指挥官执行验证 | runtime |
| G4 无 ScriptError | 全部测试无新增 ScriptError | runtime |
| G5 最终报告 | 生成完整移植报告，覆盖 15 个指挥官 | static |

## 5. Write Scope

- `src/projects/reborn-mods-cmre-integration/stages/07-series-port-completion/**`
- `artifacts/reborn-series-port-completion/**`
- `docs/reborn-port-final-report.md`

## 6. 非目标

- 修改 Reborn mod 源码（read-only）
- 完整战役通关（超出本项目范围）
- 15 个指挥官全部深度测试（抽样验证即可）

## 7. Completion Gate

1. G1-G5 全部 PASS
2. `result.json` + `issues.json` + `log.md` 完整
3. 最终报告生成
4. 项目 `currentStage` 标记为 `completed`
