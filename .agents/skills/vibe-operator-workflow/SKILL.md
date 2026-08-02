---
name: vibe-operator-workflow
description: Run and verify the SC2 Vibe porting workflow across task manifests, the deterministic simulator, Galaxy parser/static validation, project-local skills, compliant SC2 runtime launchers, assertions, ScriptError gates, and evidence bundles. Use when continuing a Vibe stage, validating a map-to-runtime task, diagnosing simulator/runtime drift, or preparing a stage result and next plan.
---

# Vibe Operator Workflow

Use this skill to drive one SC2 Vibe task from static inputs to verified evidence. Keep simulator, parser, skill, and runtime claims separate; never promote static or simulator output to runtime evidence.

## Workflow

1. Read src/config/workspace.json, the active project project.json, the current stage plan.md, and log.md.
2. Confirm the active writeScope before editing. Treat reference repositories, registered source maps/mods, and external tools as read-only.
3. Locate or generate the task manifest under artifacts/projects/cmre-porting/stage12-vibe-task-manifest. The manifest, scenario, runtime recipe, and .vtest must share the same task identity.
4. Run the deterministic simulator path first:
   powershell -NoProfile -ExecutionPolicy Bypass -File tools/galaxy-vibe/vibe.ps1 manifest -RunId <id>
5. Run the offline status path and inspect simulator, project_vibe, galaxy_parser, skills, runtime_vibe, evidence_bundle, and launchers lanes. A warning is not a runtime pass.
6. For live validation, use the approved launcher or stage harness only. Never launch SC2_x64.exe directly. Require launcher ready/API evidence, CreateGame/JoinGame, advancing frames, current assertions, and the same-window ScriptError verdict.
7. Generate an evidence bundle containing the manifest reference, packed map or source input, launcher output, assertion results, ScriptError verdict, combined verdict, and summary. Keep each artifact classified as static, simulator, runtime, blocked, or inference.
8. Update the current stage log.md, result.json, and issues.json with commands and evidence paths. Write the next stage plan only after the current result is verified.

## Runtime Rules

- A non-realtime SC2 API session needs RequestStep calls; wall-clock sleep alone leaves the game frame frozen.
- A Chinese or unpacked .SC2Map input may need staging and MPQ packing before CreateGame. `CreateGame` must receive a packed map file, not a staging directory; in this runtime setup the runner must resolve the packed path before calling SC2. Preserve only repo-relative source and artifact paths in committed evidence.
- Clear stale assertion/verdict files before a run. A missing assertion file is not a passing result.
- Use UTF-8-SIG when reading PowerShell-generated JSON or .vtest files.
- Use a real UTC Unix epoch for ScriptError launch windows.
- Use port fallback/retry when a prior SC2 process or API port is still settling; keep blocked runs separate from the last PASS bundle.

## Evidence Interpretation

- static: source inspection, parser/catalog definitions, schema checks, or compile/parse results.
- simulator: deterministic headless task execution and simulator assertions.
- runtime: SC2 process/API events, Bank/state observations, launcher output, screenshots, or GameLogs.
- blocked: a required runtime or dependency could not be reached; do not convert it to PASS.
- inference: a hypothesis or interpretation that still needs validation.

## Completion Checklist

- The operator command exits with a truthful status.
- The current task has a manifest and scenario identity.
- Simulator and parser/static lanes are recorded.
- Live runtime claims have launcher/API evidence and ScriptError evidence.
- Assertions are present, current, and all pass.
- result.json, log.md, issues.json, and the evidence bundle agree.
- Remaining warnings and next actions are recorded explicitly.
