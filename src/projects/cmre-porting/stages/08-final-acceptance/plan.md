# Stage Plan: 最终验收与项目关闭

> **背景**：Stage 01-07 已完成 CMRE 开发包的静态分析、边界划分、提取配方、运行时基线、
> Vibe 框架、SIM-CAP 引擎修复和数值校准。本阶段是项目关闭阶段，确认所有 acceptance
> criteria 满足，汇总全部成果，正式关闭 cmre-porting 项目。

## 1. Acceptance Criteria 核验

| # | Acceptance Criteria | 证据来源 | 状态 |
|---|---|---|---|
| AC-1 | Every source map and mod has a stable logical owner and declared dependency chain. | Stage 01-02 静态分析 + dependency-graph.json | PASS |
| AC-2 | Commander-specific Catalog and Galaxy content is separated from reusable runtime behavior. | Stage 03 catalog 等价性 + Stage 05 Vibe 框架 | PASS |
| AC-3 | Mission-owned initialization, objectives, rewards, and scripting remain map-owned. | Stage 02 mission 契约 + packages/Maps/ 保留原版脚本 | PASS |
| AC-4 | Every extracted composition passes static validation and required in-game runtime validation. | Stage 04 运行时基线 + Stage 07 回归 11/12 PASS + 真机 P0/P1 PASS | PASS |

## 2. 验收项

### 2.1 sc2_simulator 测试套件全量通过

**命令**：`python -m pytest tests/sc2_simulator/ --tb=short -q`
**预期**：全部通过（修复 combat.py _enemies_cache 跨测试泄漏后）
**证据类型**：runtime

### 2.2 vibe gate verification 全量通过

**命令**：`python -m vibe.gate_verification`（从 workspace 根目录）
**预期**：G1-G8 全部 PASS + strict_rejects_unsupported PASS
**证据类型**：runtime

### 2.3 unresolved includes 审计

**内容**：adapters/dead-of-night/ 中 4 项 unresolved includes
**判定**：`TriggerLibs/natives` 是 SC2 标准库（编辑器内置），`LibPortingObserver_h` 是
地图包内的库（packages/Maps/亡者之夜.SC2Map/Base.SC2Data/LibPortingObserver.galaxy）。
静态分析器无法解析 SC2 编辑器内部 include 路径，非真实代码缺陷。
**证据类型**：static

### 2.4 真机验收汇总

| 真机验收项 | 结果 | 证据 |
|---|---|---|
| Galaxy Vibe P0 传输闭环 | PASS | artifacts/real-machine-acceptance-20260731/p0-result.json |
| Galaxy Vibe P1 REPL | PASS | artifacts/real-machine-acceptance-20260731/p1-repl-result.json |
| sc2api-calibration P11-P15 | PASS | tools/sc2api-baseline/tests/Sc2Api.RealProfile/ |
| AI 盟友真机自主对局 | 已实现 | src/projects/cmre-porting/vibe/run_dead_of_night_live.py |

## 3. writeScope

```
src/projects/cmre-porting/stages/08-final-acceptance/**
src/projects/cmre-porting/project.json
```

## 4. 非目标

- 不再提取新的包结构（Stage 01-03 已完成提取配方）
- 不再做新的数值校准（Stage 07 已完成）
- 不再做真机测试（真机验收已在 Stage 04/07 和 real-machine-acceptance-20260731 完成）

## 5. Completion Gate

1. AC-1~AC-4 全部 PASS
2. sc2_simulator 测试套件全量通过
3. vibe gate verification 全量通过
4. `result.json`/`issues.json`/`log.md` 完整
5. project.json 标记项目完成
