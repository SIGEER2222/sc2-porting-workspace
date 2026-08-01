# SC2 Porting Workspace Agent Contract

## Scope

This repository is the control plane for AI-assisted SC2 map and mod porting. Existing maps, mods,
data mirrors, and external repositories are inputs. Do not modify them unless a project stage
explicitly grants a narrow write scope.

## Required workflow

1. Read `src/config/workspace.json`, resolve the active project, then use its `project.json.currentStage`.
2. Read that stage's `plan.md` and `log.md`.
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
- 常用入口：`launch-cmre-alenger.ps1 -MapName <map> -Commander <cmdr> [-ListenPort <port>]`；7vs1 使用其专用 launcher；无 mod probe 使用 `run-live-runtime-probe.ps1`。
- launcher 只能负责编排、staging、配置和调用 overlay；不要在启动脚本内嵌大段 Galaxy/patch 代码。
- launcher 退出码 0 只表示加载流程完成；还必须复核 GameLogs 本次新增的 `*ScriptError*.txt`，并取得 runtime listener 证据。
- 禁止用固定时间盲等 SC2 启动；依赖 launcher 自带的 `Wait-GameReady` 信号检测。
- 修改 `tools/launchers/` 或 `.galaxy` 后，`-NoLaunch` 不足以验收；必须实际启动游戏并确认 runtime listener/heartbeat。

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

## Session closeout

At the end of every agent session that changed repository files:

- Run `git fetch` before finalizing, then `git pull --rebase` after local commits are ready, and `git push` before ending the session.
- Split changes into coherent, categorized commits instead of one mixed checkpoint.
- Use the Lore Commit Protocol for every commit message.
- Do not leave verified, in-scope work only in the working tree; either commit it, or document why it is intentionally left uncommitted.
- Do not commit external read-only sources, local caches, or bulky generated artifacts unless the active stage explicitly requires them.
