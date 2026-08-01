# Stage Plan: AI ally Vibe application on Dead of Night

> Start condition: Stage 14 operator workflow PASS, with a nonblocking parser warning.
> Scope: use the stable manifest/simulator/runtime/evidence loop to validate an actual AI ally application scenario.

## 1. Background

Stage 14 established the control plane for the project: one operator command can generate the task manifest, run simulator smoke, select a runtime attempt, launch SC2 through the approved launcher, advance non-realtime frames, evaluate assertions, check ScriptError, and produce a hashed evidence bundle. The next milestone should consume that workflow for behavior with meaningful game-state consequences instead of another isolated Marine smoke.

The detailed candidate behavior is recorded in `src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/ai-ally-dead-of-night-plan.md`. This stage promotes the smallest verifiable slice of that plan into the active project workflow.

## 2. Goals

1. Define an AI ally task/scenario contract that is executable in the simulator and expressible through the live runtime adapter.
2. Validate ally policy decisions over a bounded deterministic scenario: threat selection, defense/dispatch policy, resource or unit-state transition, and completion outcome.
3. Run the same scenario through `vibe.ps1 workflow -Live`, preserving simulator, runtime, ScriptError, and evidence classifications.
4. Keep application behavior in project-owned `vibe/` consumers or a narrow commander-map adapter; do not alter read-only source maps, external repositories, or canonical commander behavior for this one map.
5. Record a reproducible evidence bundle with runtime assertions stronger than the Stage 14 2/2 transport smoke.

## 3. Inputs

- `artifacts/projects/cmre-porting/stage12-vibe-task-manifest/manifest.json`
- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/live-attempts/stage14-live-final3/port-5001/runtime-summary.json`
- `artifacts/projects/cmre-porting/stage14-vibe-operator-workflow/bundles/bundle-stage14-live-final3/evidence-bundle.json`
- `src/projects/cmre-porting/stages/13-vibe-runtime-evidence-pack/ai-ally-dead-of-night-plan.md`
- `src/projects/cmre-porting/vibe/consumers/ally_ai.py`
- `src/projects/cmre-porting/vibe/run_dead_of_night.py`
- `src/projects/cmre-porting/vibe/run_dead_of_night_live.py`

## 4. Work plan

1. Extract the first bounded ally behavior from the existing plan and define its simulator/live assertions and stop conditions.
2. Add or adapt only the project-owned task, consumer, and runtime adapter files required by two concrete consumers.
3. Run deterministic simulator tests first, including regression coverage for the existing Stage 14 transport contract.
4. Run the scenario through the operator workflow in non-live mode and inspect the generated manifest/evidence status.
5. Run the live scenario through the compliant launcher with current assertions, frame advancement, and same-window ScriptError verification.
6. Compare simulator and runtime outcomes; any divergence becomes an explicit issue rather than a silent pass.

### Startup scope extension

The current runtime is blocked before map entry when CMRE falls back to the commander-selection
screen. This stage therefore has a narrow additional write scope for the CMRE launcher staging
overlay only:

- `tools/launchers/launch-cmre-alenger.ps1`
- `tools/launchers/lib/cmre-on-demand-overlay.ps1`
- `tools/launchers/overlays/cmre-alenger/startup/**`
- `tools/launchers/tests/test_launch_cmre_alenger_static.py`

The registered source map remains read-only. The overlay removes the selection fallback only from
the staged runtime map. `亡者之夜.SC2Map` permanently rejects `-ShowSelectionUI`, and the staged
map is validated across all Base.SC2Data Galaxy files so the selection trigger cannot be restored
by an accidental alternate startup path.

## 5. Completion gate

1. The AI ally task/scenario and its assertions exist under the project-owned scope.
2. Targeted simulator tests pass and preserve the existing workflow regression surface.
3. A real live run passes through the approved launcher/API path with current runtime evidence, not process startup alone.
4. Assertions cover at least one policy decision and one resulting game-state transition; ScriptError has no new errors.
5. A Stage 15 evidence bundle and status report exist, with static/simulator/runtime/inference classifications intact.
6. `result.json`, `log.md`, and `issues.json` agree, and any remaining warnings are explicit.

## 6. Non-goals

- Do not implement the entire AI ally strategy in one pass.
- Do not edit registered read-only maps, mods, reference repositories, or the legacy toolkit.
- Do not weaken the Stage 14 operator gates to make a behavior scenario pass.
- Do not treat simulator success as live runtime success.
