# Stage 10 Plan: Runtime Policy Evaluation

## Objective

在 Stage 09 已验证的 P1 raw bridge 上，运行更长的 held-out 多地图评估，补齐
mission-owned terminal/reward 事件、replay-backed action attribution 和可重复的
policy-vs-baseline 指标。目标是判断跨地图自适应是否真实改善，而不是把短 rollout
的 proxy reward 当作胜率。

## Contracts

- 真实 SC2 仍只能通过 approved launcher 启动；每个 run 必须有独立端口、launcher
  输出、runtime report 和同窗口 ScriptError verdict。
- 评估至少覆盖 `dead-of-night` 与一个未参与 checkpoint 训练选择的 held-out map，
  固定种子/配置并保存 map profile、checkpoint hash 和 action trace。
- terminal reward 必须来自 mission-owned runtime event、PlayerResult 或明确的
  map objective，不得由 wall-clock 或 loop budget 伪造胜利。
- 对比至少包含当前 map-aware PPO、未更新 checkpoint 和 deterministic baseline；
  报告样本数、胜率/终局类型、代理 reward、动作成功率和 ScriptError。
- P2 native Computer 仍只作为环境对手；在获得双 participant/API 控制证据前，
  不声称 P2 被 ML 控制。

## Outputs

```text
stages/10-runtime-policy-eval/{plan,log,result,issues}.{md,json}
tools/evaluate_live_policy.py
tests/test_live_policy_eval.py
artifacts/stage-10-runtime-policy-eval/<run-id>/{report,trace,script-error-verdict}.json
```

## Gates

| Gate | Verification |
|---|---|
| G1-terminal-contract | mission event / PlayerResult reaches normalized observation and terminates correctly |
| G2-held-out-maps | same checkpoint schema and action mask run on at least two map profiles |
| G3-baseline-comparison | PPO, frozen checkpoint, and deterministic baseline produce comparable metrics |
| G4-runtime-evidence | each run has fresh launcher/API evidence and clean same-window ScriptError verdict |
| G5-attribution | replay/trace links decisions, dispatch results, loop ranges, and terminal outcome |

## Non-goals

- 不把 bounded runtime proxy reward 当作任务胜率。
- 不修改 canonical commander mod、注册地图或 external repositories。
- 不把 native Computer P2 当成外部 ML participant。
- 不在没有 terminal/replay evidence 时宣称战术提升。
