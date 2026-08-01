# Stage Plan: Vibe operator workflow

> 开启时间：待执行  
> 范围：把 Stage 12/13 已验证的 manifest、simulator、SC2 runtime evidence 串成一个可复用的 Vibe 工作流入口，并补齐 Galaxy parser / project-local skill / runtime launcher 的操作闭环。

## 1. 背景

Stage 12 已生成统一 task/scenario manifest，证明静态 map extraction 可以喂给 simulator 与 live runtime contract。Stage 13 已通过真实 SC2 runtime：packed map、CreateGame/JoinGame、frame advance、2/2 assertions、ScriptError 0。下一阶段不再扩大单点 smoke，而是把这些能力收敛成项目本身需要的 vibe workflow。

## 2. 目标

1. 提供一个单一 operator workflow，能从同一份 task manifest 执行 simulator、SC2 stub/live、evidence bundle 和 workflow status。
2. 将 Galaxy parser lane 纳入 workflow status：能明确区分 parser present / parser degraded / parser blocked，而不是只靠旧 warning。
3. 将 project-local skill surface 纳入 workflow：至少有一个技能说明能指导“如何跑 simulator、如何跑 live runtime、如何解释 evidence”。
4. 将 runtime launcher 的 flake 点固化：port fallback/retry、PASS/blocked run 分目录保存、ScriptError window 使用可信 UTC epoch。
5. 输出 operator-facing status：一句命令可看到 simulator/runtime/parser/skill/evidence 五条 lane 的 PASS/WARN/FAIL。

## 3. Inputs

- artifacts/projects/cmre-porting/stage12-vibe-task-manifest/manifest.json
- artifacts/projects/cmre-porting/stage12-vibe-task-manifest/task.simulator.json
- artifacts/projects/cmre-porting/stage12-vibe-task-manifest/task.live.json
- artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/runtime-summary.json
- artifacts/projects/cmre-porting/stage13-vibe-runtime-evidence-pack/evidence-bundle.json
- tools/galaxy-vibe/vibe.ps1
- tools/galaxy-vibe/workflow_status.py
- project-local skills under .agents/skills/

## 4. Work plan

1. Audit current Vibe commands and workflow status lanes.
2. Add/extend an operator command, tentatively vibe.ps1 workflow, that runs manifest/status and can optionally run simulator/live gates.
3. Add parser lane detection for the registered Galaxy parser/toolkit path, with explicit degraded status and remediation text.
4. Add project-local skill docs for the Vibe workflow: simulator, parser, runtime launcher, evidence interpretation.
5. Add runtime robustness: port fallback/retry and run-specific artifact directories so failed launches do not overwrite the last PASS evidence.
6. Validate with static checks plus a non-launch workflow status run; live SC2 rerun only if the runtime command path changes materially.

## 5. Completion gate

1. workflow status contains simulator, galaxy_parser, skill, runtime_vibe, evidence_bundle lanes.
2. At least one operator command emits a compact PASS/WARN/FAIL summary that references Stage 12 and Stage 13 artifacts.
3. The project-local skill surface documents exactly how to run the Vibe workflow and how to interpret runtime evidence.
4. Runtime launcher changes, if any, pass parser/py_compile checks and preserve Stage 13 PASS artifacts.
5. result.json, log.md, issues.json are updated, and the next stage plan is written only after this stage verifies.

## 6. Non-goals

- Do not rework commander gameplay behavior in this stage.
- Do not treat AI ally strategy as the main milestone yet; it remains an application layer after the Vibe workflow is stable.
- Do not edit read-only external repositories.
