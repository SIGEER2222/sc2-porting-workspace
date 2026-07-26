# SC2 Porting Workspace Agent Contract

## Scope

This repository is the control plane for AI-assisted SC2 map and mod porting. Existing maps, mods,
data mirrors, and external repositories are inputs. Do not modify them unless a project stage
explicitly grants a narrow write scope.

## Required workflow

1. Read `src/config/workspace.json` and the active project's `project.json`.
2. Read the current stage `plan.md` and `log.md`.
3. Select the required project-local Skills.
4. Run static discovery before proposing dependency or adapter changes.
5. Make only the files listed in `writeScope`.
6. Run the stage validation commands.
7. Update `log.md`, `result.json`, and `issues.json`.
8. Write the next stage's `plan.md` only after the current result is verified.

## Hard constraints

- Do not treat any existing project as the workspace root or canonical owner.
- Do not edit registered read-only sources or external repositories.
- Do not add files outside the active project, approved adapter package, or tooling wrapper.
- Do not use absolute workspace paths in committed files.
- Put generated reports, logs, extracted data, caches, and live-sync output under `artifacts/`.
- Do not create a shared abstraction until at least two real consumers require the same behavior.
- Prefer a map-commander adapter over changing a canonical commander mod for one map.
- Prefer a map adapter over changing a map when compatibility behavior is not mission-owned.
- Do not report completion from static analysis alone.
- Do not report completion from process startup alone; dynamic verification requires runtime evidence.
- Do not create helper scripts for one-off operations when an existing tool can perform the operation.
- Keep every diff bounded by the current stage. Split work when unrelated concerns appear.
- Preserve user changes and stop if an approved write-scope file contains unexplained concurrent edits.

## SC2 launch rules

- **禁止直接启动 `SC2_x64.exe`**：必须通过 `tools/launchers/` 下的 launcher 脚本启动 SC2。
  - 原因：直接启动会跳过 mod 同步、test lock、地图同步、ready 信号监控、ScriptError 复核等保障流程，导致无法判断游戏是否真正进入可观测状态。
  - 例外：仅当 launcher 脚本本身损坏或缺失时，可临时使用 `SC2Switcher_x64.exe`（注意：Switcher 会吞掉 `-listen` 参数，不能用于 API 模式）。
  - 正确入口：
    - CMRE 移植项目：`launch-cmre-alenger.ps1 -MapName <map> -Commander <cmdr> [-ListenPort <port>]`
    - 7vs1 合作测试：`E:\Code\MyMod\SC2\合作指挥官-起义狂潮\scripts\launch-7vs1-coop-test.ps1`
    - Live runtime probe（无 mod 依赖）：`run-live-runtime-probe.ps1 -Port <port> -Map <map>`
- launcher 退出码 0 视为加载完成；退出后必须复核 `C:\Users\22448\Documents\StarCraft II\GameLogs` 是否有本次启动新增的 `ScriptError.*.txt`。
- 禁止用固定时间盲等 SC2 启动；依赖 launcher 自带的 `Wait-GameReady` 信号检测。

## Evidence rules

Every technical claim must be classified as one of:

- `static`: derived from document dependencies, Catalog definitions, Galaxy analysis, or source files.
- `runtime`: observed from SC2 events, Banks, logs, process state, screenshots, or action results.
- `inference`: a hypothesis that still requires validation.

The active stage log must record the evidence path and command for each verified claim.

## Package boundaries

- Commander mods contain canonical commander behavior.
- Shared mods contain behavior proven reusable by multiple consumers.
- Series adapters contain compatibility common to a map series.
- Map adapters contain compatibility specific to one map.
- Commander-map adapters contain compatibility specific to one pairing.
- Maps retain mission-owned initialization, objectives, rewards, cinematics, and local scripting.
- External tool source remains in its own Git repository and is consumed through a documented interface.

## Completion gate

A stage is complete only when:

- its declared outputs exist;
- validation commands pass;
- `result.json` matches the stage schema;
- unresolved issues are recorded;
- `log.md` contains evidence and changed paths;
- the next stage has a concrete `plan.md`.
