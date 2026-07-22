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
