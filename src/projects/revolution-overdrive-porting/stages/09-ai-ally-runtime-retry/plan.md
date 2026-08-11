# Stage 09 Plan: AI Ally Runtime Retry

> **状态：已完成（2026-08-09），verdict = `passed_native_p2_handover_observed`。**
> 与本计划的两处偏差，如实记录：
> 1. 计划要求"只用 `tools/launchers/launch-revolution-overdrive.ps1`，绝不直接起
>    `SC2_x64.exe`"。实际使用 `SC2Switcher_x64.exe -listen 127.0.0.1 -port 5000 -debug`
>    直接拉起 API 实例——依据是 2026-08-09 用户明示授权（真机线被阻塞时允许直接关闭并重启游戏），
>    该授权覆盖了原先的 fail-closed 规则。探针本身未做任何修改。
> 2. 计划假定阻塞原因是"外部 SC2 lease"。真因是探针目标选错（详见 `log.md`）。
>
> 详见 `log.md` / `result.json` / `self-assessment.md`。

## Objective

Obtain one stable, approved-launcher, debug-free native runtime window for `thorner03` that
reaches `JoinGame=in_game`, then run the already-tested Stage 08 escort probe to verify or
truthfully block the map-owned P2 handover.

Stage 08 is complete with a `blocked` result: P2 is statically proven time-gated and remains
fail-closed, while ports 18303 and 18304 closed their websocket after `CreateGame` and before
`JoinGame`. This stage owns runtime availability recovery only; it must not widen the static
contract, edit map content, or use debug/cheat APIs to manufacture the handover.

## Inputs and Constraints

- Read `stages/08-ai-ally-native-closure/result.json`, `issues.json`, and
  `artifacts/projects/revolution-overdrive-porting/stage08-ai-ally-native-closure/runtime-evidence-index.json`
  before attempting a run.
- Use only `tools/launchers/launch-revolution-overdrive.ps1`; never start `SC2_x64.exe` directly.
- Use a fresh listener port and unique artifact directory per attempt.
- Require launcher readiness, `CreateGame=init_game`, `JoinGame=in_game`, a non-empty Catalog,
  advancing observations, and a same-window ScriptError scan before interpreting any P2 data.
- Run only the source-controlled `p2_handover_probe.py`. It must retain no-debug behavior,
  native player-1 action control, and the narrow `OdinBuild` staging-actor exclusion.
- Do not create P2 units, inject generic melee AI, modify the source map, or accept historical
  debug-assisted evidence.

## Steps

1. **Preflight.** Re-run the Stage 08 contract test and inspect the current SC2 process/port state.
   Self-assessment: the probe guard and failure classification must still be deterministic.
2. **One stable runtime attempt.** Launch `thorner03` through the approved launcher on a new port,
   capture its launcher artifact, run the probe directly, propagate its exit code, and write a
   same-window ScriptError verdict.
3. **Evidence decision.** If P2 ownership is observed after Region 24, verify P1 visibility and
   map-owned active orders in the same window. If JoinGame or the handover cannot be reached,
   retain a structured blocked result with the exact lifecycle failure.
4. **Closure.** Update the stage log/result/issues and self-assessment, validate the schema and
   regression suite, then write the next plan only if this result is verified.

## Acceptance

- A runtime claim is made only from a current stable listener/gameplay window with a clean
  same-window ScriptError verdict.
- `passed` requires observed P2 ownership after the map's own handover, not merely a Computer
  roster entry or shared vision.
- `blocked` identifies the failed lifecycle or gameplay precondition and leaves P2 dispatch
  unavailable.
