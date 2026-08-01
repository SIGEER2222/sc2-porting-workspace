# Stage Plan: post-acceptance hardening

> 开启时间：2026-07-31T21:05:00+08:00  
> 范围：最终验收后的账本一致化与 catalog 静态可观测性硬化；不修改 simulator 行为，不启动真实 SC2。

## 1. 背景

Stage 09 已关闭 Stage 07 残留的两个 simulator semantic gaps，并通过 tests/sc2_simulator 全量回归（448 passed）。当前剩余工作主要分为两类：

1. 历史阶段 issue 文件仍有陈旧状态，需要与 Stage 06 / Stage 09 的修复证据对齐。
2. Stage 08 catalog issue 中有两个工具链项可通过静态报告先收口：UpgradeType.effects 引用闭包校验和 catalog 覆盖率统计。

## 2. 本阶段目标

1. 将 Stage 05 的 SIM-CAP-GAP-002/003 从 open 账面状态对齐为 Stage 06 已修复。
2. 将 Stage 06 的 SIM-CAP-GAP-006/007 从 open 账面状态对齐为 Stage 09 已修复。
3. 为 UpgradeType.effects 生成静态闭包报告，并根据结果更新 Stage 08 catalog issue。
4. 为 catalog 覆盖率生成静态报告，并根据结果更新 Stage 08 catalog issue。
5. 保留 AI-ALLY-LIVE-002 open；关闭它需要真实 SC2 launcher smoke，不在本阶段执行。

## 3. Write Scope

- src/projects/cmre-porting/project.json
- src/projects/cmre-porting/stages/05-vibe-framework/issues.json
- src/projects/cmre-porting/stages/06-sim-cap-completion/issues.json
- src/projects/cmre-porting/stages/08-final-acceptance/issues.json
- src/projects/cmre-porting/stages/08-final-acceptance/catalog-issues.json
- src/projects/cmre-porting/stages/10-post-acceptance-hardening/**
- artifacts/projects/cmre-porting/stage10-post-acceptance-hardening/**

## 4. Completion Gate

1. Stage 10 issues.json, result.json, log.md 存在。
2. 历史 issue 状态与已完成阶段证据一致。
3. upgrade-effects-closure.json 和 catalog-coverage-report.json 生成。
4. JSON 文件可解析。
5. git diff --check 对本阶段 touched files 通过。
