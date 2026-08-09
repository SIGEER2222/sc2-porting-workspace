# ML Autonomous Game Completion Plan

## Objective

Build a repeatable ML training loop that can learn across repeated runs and eventually complete a real `dead-of-night` SC2 match autonomously. A completed match must be proven by real runtime terminal evidence, not by simulator score or bounded rollout reward.

## Hard Acceptance Rules

- The current MVP target is `dead-of-night` with P1 ML control. Multi-map generalization is a later extension.
- Victory is accepted only from real runtime `player_result` / mission-owned terminal evidence.
- Bounded rollouts without `player_result` are bridge evidence only; they do not count as wins.
- Every live run must use an approved launcher under `tools/launchers/`; never launch `SC2_x64.exe` directly.
- Every live run must include launcher log, action trace, replay when available, same-window ScriptError verdict, and runtime report.
- P2 remains native Computer until a separate two-participant/API topology is proven.

## Commander Runtime Requirement

- Every commander used for training or evaluation must default to max level and full mastery / full point allocation.
- A run where the commander appears underleveled, such as Raynor showing as roughly level 7, is invalid for ML evidence.
- Launcher/WebUI/runtime config must explicitly record the commander level/mastery profile used for each run.
- The training report must include commander identity, level profile, mastery allocation source, and whether the max-level gate passed.
- If max-level state cannot be proven from bank/config/runtime evidence, the run status is `blocked`, not `passed`.

## Stage 1: Terminal Contract

Goal: make sure real SC2 terminal state reaches the RL loop.

Tasks:

- Verify `player_result` flows through `LiveRawSc2Session -> RawSc2Backend -> CmreRLEnv -> rollout`.
- Normalize victory/defeat/tie/undecided names consistently.
- Stop rollouts immediately on terminal result when `--stop-on-terminal` is set.
- Record terminal reason in `live-rl-report.json` and action trace footer.

Gate:

- Offline tests prove terminal parsing.
- One live run reaches either victory or defeat and reports it truthfully.

## Stage 2: Commander Power Baseline

Goal: ensure all ML evaluations use the intended high-power commander state.

Tasks:

- Audit launcher bank/profile writes for commander level, mastery, prestige/buffs, and commander-specific allocations.
- Add a preflight validator that rejects non-max commander state before training/eval.
- Add report fields for commander level and mastery configuration.
- Re-run a visible Raynor launch and verify the UI/runtime state shows max level and full allocation.

Gate:

- Raynor and at least one Alenger commander pass the max-level/full-mastery gate.
- Underleveled profiles are detected and rejected before rollout collection.

## Stage 3: Offline Curriculum

Goal: train reliable subskills before attempting long live matches.

Curriculum order:

1. Survive early night window.
2. Maintain worker/economy loop.
3. Build supply and production structures.
4. Produce an army consistently.
5. Defend base waves.
6. Attack/clear enemy targets.

Required metrics per curriculum run:

- Mean reward.
- Action entropy.
- Action distribution.
- Illegal action rate.
- Production/build/attack ratios.
- Terminal or cutoff reason.
- Checkpoint hash.

Gate:

- Each curriculum scenario has a measurable pass threshold before advancing to the next scenario.

## Stage 4: Training/Evaluation Loop

Goal: automate repeatable train -> evaluate -> promote checkpoint cycles.

Proposed entrypoint:

```text
src/projects/cmre-rl-training/tools/train_eval_loop.py
```

Loop:

1. Train simulator curriculum for N iterations.
2. Save checkpoint and metadata.
3. Run bounded live evaluation when runtime lease is available.
4. Compare latest checkpoint against random and previous best.
5. Promote only if runtime gates pass and metrics improve.
6. Archive failed traces for analysis.

Gate:

- The loop can resume from the last promoted checkpoint.
- Failed live runs do not overwrite the best checkpoint.

## Stage 5: Live Short-Horizon Evaluation

Goal: prove the policy can act in real SC2 without claiming victory.

Run ladder:

- 512 steps: startup/action sanity.
- 2048 steps: early economy/defense sanity.
- 8192 steps: extended survival and production sanity.

Required evidence:

- `live-rl-report.json`
- action trace
- replay if available
- launcher log
- clean ScriptError verdict
- commander max-level gate result
- runtime action success/error summary

Gate:

- No ScriptError.
- No API/launcher mismatch.
- Commander max-level gate passes.
- Actions are not collapsed to one degenerate mode.

## Stage 6: Long-Horizon Terminal Run

Goal: run until real mission terminal result.

Rules:

- Use `--stop-on-terminal`.
- Use a horizon long enough to cover a full match.
- Save replay and trace.
- Do not convert timeout/cutoff into victory.

Gate:

- `player_result=Victory` reaches report and trace.
- ScriptError verdict clean.
- Commander max-level gate passes.
- Replay exists or the report explains why replay capture failed.

## Stage 7: Reporting

Stage 10 remains `blocked` until real terminal evidence exists.

Report fields to add or preserve:

- checkpoint hash
- map profile hash
- commander ID
- commander level/mastery profile
- terminal result
- reward summary
- action distribution
- illegal action rate
- runtime action success rate
- ScriptError verdict
- replay path

## Immediate Next Tasks

1. Implement commander max-level/full-mastery validation and reporting.
2. Add action distribution and illegal-action metrics to training and live reports.
3. Implement `train_eval_loop.py` dry-run mode.
4. Run a visible Raynor launch and verify max-level state before collecting ML evidence.
5. Run a 512-step live evaluation only after the commander max-level gate passes.
