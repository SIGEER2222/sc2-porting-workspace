# Stage Plan: Vibe task manifest

> 开启时间：2026-07-31T21:36:00+08:00  
> 范围：把 map_extractor 的静态地图提取结果收敛为 simulator / SC2 stub / live runtime 共用的 task manifest。

## 1. 背景

Stage 11 已经把 simulator、Galaxy parser/runtime、skills、launcher 和 evidence surfaces 汇总到 vibe.ps1 status。下一步需要让这些能力共享同一份 scenario/task 契约，而不是各自维护不同输入。

## 2. 本阶段目标

1. 新增 project-side manifest 生成器，把 MapData 转为统一 manifest.json、scenario.json、task contracts、runtime recipe 和 .vtest。
2. 复用 Stage 09/10 后的 TaskContract 形状，产出 simulator、SC2 stub、live runtime 三类 task。
3. 接入 tools/galaxy-vibe/vibe.ps1 manifest，让统一入口可一键生成 manifest 并跑本地 simulator smoke。
4. 将 manifest 生成器纳入 run-all-validation.ps1 静态自检。
5. 生成 Stage 12 artifacts，并明确 live runtime 仍是 runtime-pending，不冒充真机证据。

## 3. Write Scope

- src/projects/cmre-porting/project.json
- src/projects/cmre-porting/stages/12-vibe-task-manifest/**
- src/projects/cmre-porting/vibe/task_manifest.py
- tools/galaxy-vibe/workflow_status.py
- tools/galaxy-vibe/vibe.ps1
- tools/galaxy-vibe/run-all-validation.ps1
- artifacts/projects/cmre-porting/stage12-vibe-task-manifest/**

## 4. Completion Gate

1. task_manifest.py py_compile 通过。
2. manifest 生成器可生成 manifest.json、scenario.json、三类 task、runtime recipe 和 .vtest。
3. simulator smoke 通过，且证据为轻量 simulator-smoke-result.json，不生成大型完整 snapshot bundle。
4. vibe.ps1 manifest 通过。
5. vibe.ps1 validate 通过，且 validation 覆盖 task_manifest.py。
6. workflow_status.py 识别 vibe.task_manifest。
7. JSON outputs 可解析，git diff --check 无 whitespace error。
