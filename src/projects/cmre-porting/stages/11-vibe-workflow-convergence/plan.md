# Stage Plan: Vibe workflow convergence

> 开启时间：2026-07-31T21:20:00+08:00  
> 范围：把 simulator、Galaxy 解析/运行时、repo-local skills、launcher/ScriptError 规则收束成一个可执行 Vibe workflow 入口。

## 1. 背景

当前项目目标不是单独完成 sc2_simulator，而是形成一个能持续支持 SC2 地图/Mod vibe 开发的工作流。已有组件包括：

- simulator：本地确定性 headless runtime，用于快速规则回归、任务场景和 AI policy 验证。
- Galaxy parser/static lane：读取 Galaxy/Catalog/MapScript，提取依赖、任务、波次、触发器与候选 scenario。
- Galaxy runtime lane：真机热循环、REPL、MapCommand/Bank/SC2API、状态断言、视觉判定、ScriptError gate。
- skills lane：把 Galaxy / SC2Data / unit reference 的编辑知识显式化，避免每次靠记忆写脚本和 XML。
- launch/evidence lane：所有真机验证必须通过 launcher，产物落 artifacts，并带 ScriptError 复核。

## 2. 本阶段目标

1. 新增离线 workflow status 检查器，汇总 simulator / project vibe / Galaxy runtime / parser / skills / launcher readiness。
2. 将该检查器接入统一入口 tools/galaxy-vibe/vibe.ps1 status。
3. 将 status 脚本纳入 tools/galaxy-vibe/run-all-validation.ps1 静态自检。
4. 生成 Stage 11 工作流状态 artifact。

## 3. Write Scope

- src/projects/cmre-porting/project.json
- src/projects/cmre-porting/stages/11-vibe-workflow-convergence/**
- tools/galaxy-vibe/vibe.ps1
- tools/galaxy-vibe/run-all-validation.ps1
- tools/galaxy-vibe/workflow_status.py
- artifacts/projects/cmre-porting/stage11-vibe-workflow-convergence/**

## 4. Completion Gate

1. workflow_status.py py_compile 通过。
2. python tools/galaxy-vibe/workflow_status.py --out ... 可生成 JSON。
3. powershell -File tools/galaxy-vibe/vibe.ps1 status 可生成同一状态报告。
4. powershell -File tools/galaxy-vibe/vibe.ps1 validate 通过静态自检。
5. Stage 11 result/log/issues 完整记录证据。
