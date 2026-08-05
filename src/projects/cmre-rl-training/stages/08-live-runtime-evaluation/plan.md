# Stage 08 Plan: Live Runtime Evaluation

## Objective

在真实 SC2 窗口中验证当前 live observation/action transport，并确认已有
PyTorch P1 policy 能被 runner 加载、做出决策并经过 typed dispatch。该阶段同时
明确 Stage 07 simulator PPO checkpoint 与真实 SC2 runner 之间尚未完成的接入边界。

## Contracts

- 只能通过 `tools/launchers/launch-cmre-alenger.ps1` 启动 SC2。
- 必须记录 API ready、CreateGame、JoinGame、RequestStep/frame advancement、动作结果和同窗口 ScriptError verdict。
- live runner 失败时必须保留真实报告，不得把 `INCONCLUSIVE` 提升为 victory 或 ML pass。
- `p1-action.pt` 只作为现有 P1 imitation checkpoint 的 runtime probe；不得将其标记为
  `cmre-rl-training` 的 map-aware PPO checkpoint。

## Outputs

```text
artifacts/stage-08-live-smoke/20260805-dead-of-night/
artifacts/stage-08-live-smoke/20260805-dead-of-night-p1-ml/
stages/08-live-runtime-evaluation/{plan,result,log,issues}.{md,json}
```

## Next Work

- 接入 `RawSc2Backend` 到注册 launcher 的 CreateGame/JoinGame/RequestStep/RequestAction/Leave 生命周期。
- 让 map-aware PPO checkpoint 使用与 live observation 相同的 schema，并在至少一个真实地图上运行 held-out evaluation。
- 解决可控 participant topology；native Computer ally 不能作为外部 ML action issuer。

## Non-goals

- 不修改注册源地图或 canonical commander mod。
- 不把 1500 loop bounded smoke 当作完整任务胜率。
- 不以 simulator report 替代真实 SC2 runtime evidence。
