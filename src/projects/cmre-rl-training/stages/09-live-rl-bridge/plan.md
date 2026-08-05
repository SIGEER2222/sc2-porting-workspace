# Stage 09 Plan: Live RL Bridge

## Objective

将已验证的 raw SC2 websocket transport 接入正式 `RawSc2Backend`，让
Stage 07 的 map-aware PPO checkpoint 可以在真实 SC2 的 P1 participant 上
执行短 rollout，并可选完成一次 PPO 更新。该阶段验证真实 observation、action
mask、ActionGrounder、ActionRawUnitCommand 和 runtime evidence 的闭环；不把
native Computer P2 误报为外部 ML 控制对象。

## Contracts

- 只能通过 `tools/launchers/launch-cmre-alenger.ps1` 启动 SC2。
- `LiveRawSc2Session` 必须覆盖 CreateGame、JoinGame、Observation、RequestAction、
  RequestStep、LeaveGame，并暴露真实 transport 统计。
- raw Catalog unit IDs 必须归一化为现有 encoder/action-mask 使用的稳定 unit names。
- action dispatch 结果、实际 loop advancement、CreateGame/JoinGame 和同窗口
  ScriptError verdict 必须进入 JSON evidence。
- live bounded rollout 的 reward 明确标记为 observation-derived runtime proxy；
  没有真实 mission terminal event 时不得声称任务胜率或战术提升。
- P2 native Computer 仍只作为环境对手；本阶段只声称 P1 participant 的外部 ML
  action issuer 已接通。

## Outputs

```text
cmre_rl_training/live_sc2_session.py
tools/run_live_rl.py
tests/test_live_sc2_session.py
stages/09-live-rl-bridge/{plan,log,result,issues}.{md,json}
```

## Gates

| Gate | Verification |
|---|---|
| G1-contract | raw observation normalization and all 19 action specs pass focused tests |
| G2-offline-bridge | fake session drives `RawSc2Backend -> CmreRLEnv -> MapAwareEnv` with finite policy inputs |
| G3-live-rollout | approved launcher, API ready, CreateGame/JoinGame, advancing loops, action results |
| G4-script-error | same-window new ScriptError scan is clean or result is explicitly blocked |
| G5-evidence | report, launcher logs, runtime stats and stage records agree |

## Non-goals

- 不修改 launcher、canonical commander mod、注册地图或 external repositories。
- 不把 P1 bounded rollout 当作完整任务胜率。
- 不宣称 native Computer P2 已被外部 ML 控制。
- 不把 runtime proxy reward 当作真实 mission reward。
