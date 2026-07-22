---
name: sc2-runtime-analysis
description: Run backend-neutral dynamic analysis of an SC2 map/mod composition using Banks, game logs, process state, event streams, screenshots, or Neuro-compatible services. Use after static validation, when proving initializers/triggers/objectives/rewards/actions execute, when comparing static predictions with observed behavior, or when diagnosing runtime-only failures.
---

# SC2 Runtime Analysis

Collect real game evidence. Neuro and Gary are optional backends, not required architecture dependencies.

## Preconditions

1. Read the active project, stage plan, static dependency graph, and composition manifest.
2. Confirm static validation passed or record the explicitly accepted static gap.
3. Use the registered launcher and test lock for the target map type.
4. Confirm only one runtime observer and one selected backend own each action channel.

## Observation workflow

1. Record launch command, map, mods, adapters, commander, run ID, and pre-launch process state.
2. Launch SC2 through the target-specific launcher.
3. Wait for the complete readiness procedure; process startup alone is not success.
4. Capture initialization, trigger, objective, reward, Bank, selection, command, resource, and unit events.
5. Capture ScriptError and process exit state.
6. Exercise the stage's declared scenarios.
7. Compare observed events with static predictions and acceptance criteria.
8. Store raw evidence and write a stage result.

## Required evidence

- map and composition identity;
- SC2 PID and observed runtime;
- readiness result;
- ScriptError status;
- initializer and trigger observations relevant to the stage;
- player action and resulting game state for action tests;
- objective/reward progression for mission tests;
- observer/backend process state;
- exact evidence paths.

Never use mock-only evidence when the stage requires a real service or game process.

Read [runtime-contract.md](references/runtime-contract.md) before launching.

## SC2 API observer

For passive runtime observation (human plays, AI reads game state), use the
SC2 API websocket observer. This complements Bank/log-based observation with
live game state:

```powershell
# 启动观察（默认 120 秒，事件输出到 artifacts/runtime/）
node tools/utils/workspace.mjs observe --port 5000

# 指定时长 + scenario 断言
node tools/utils/workspace.mjs observe --port 5000 --duration 60 --scenario evidence/runtime/scenario.json

# 自定义输出目录
node tools/utils/workspace.mjs observe --port 5000 --out-dir evidence/runtime/run-001
```

输出：
- `events.ndjson` — 逐帧事件流（资源/单位快照/游戏错误/alert/游戏结束）
- `verdict.json` — scenario 断言结果（仅当指定 `--scenario` 时）

底层调用 `tools/runtime-bridge/sc2-observer.py`，复用
`reference/SC2-Neuro-API-Integration/s2clientprotocol/` 的 vendored protobuf 包。
依赖 `aiohttp`（`pip install aiohttp`）。

SC2 启动时需加 `-listenPort 5000` 参数开放 API 端口。observer 只读不写，
不会影响游戏进程。
