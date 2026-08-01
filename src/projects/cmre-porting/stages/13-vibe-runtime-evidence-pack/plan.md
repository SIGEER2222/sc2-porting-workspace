# Stage Plan: Vibe runtime evidence pack

> 开启时间：待执行  
> 范围：消费 Stage 12 的 manifest/live contract，通过合规 launcher 获取 runtime 证据，并打包 ScriptError / assertion / visual / summary 产物。

## 1. 背景

Stage 12 已生成统一 manifest，并将 live runtime contract 明确标记为 runtime-pending。Stage 13 要把这个 pending contract 变成真实 runtime evidence，而不是继续停留在静态或 simulator 证据。

## 2. 输入

- artifacts/projects/cmre-porting/stage12-vibe-task-manifest/manifest.json
- artifacts/projects/cmre-porting/stage12-vibe-task-manifest/task.live.json
- artifacts/projects/cmre-porting/stage12-vibe-task-manifest/runtime-recipe.json
- artifacts/projects/cmre-porting/stage12-vibe-task-manifest/scenario.vtest

## 3. 目标

1. 使用 tools/galaxy-vibe/launch-galaxy-vibe.ps1 执行 Stage 12 scenario.vtest。
2. 确认 launcher ready signal，而不是固定时间盲等。
3. 复核本次启动后新增 ScriptError 文件。
4. 收集 assertion/verdict/launcher logs/ScriptError check 到 Stage 13 artifact 目录。
5. 生成 runtime evidence summary，并把 evidence_type 标为 runtime。
6. 若 live runtime 不可用，记录为 blocked-runtime-unavailable，不把 simulator 或 stub 证据重标为 runtime。

## 4. Write Scope

- src/projects/cmre-porting/project.json
- src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/**
- tools/galaxy-vibe/vibe.ps1
- tools/galaxy-vibe/launch-galaxy-vibe.ps1
- tools/galaxy-vibe/galaxy_repl.py
- tools/galaxy-vibe/script_error_check.py
- tools/galaxy-vibe/evidence_bundle.py
- artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/**
- artifacts/galaxy-vibe/**

## 5. Completion Gate

1. Launcher command exits 0 or blocked-runtime-unavailable is recorded with concrete reason.
2. New ScriptError check is recorded for the same launch window.
3. Runtime verdict artifact exists and is parsed.
4. Evidence bundle includes manifest reference, launcher output, assertion result, ScriptError result, and evidence classification.
5. result.json, log.md, issues.json are updated.
