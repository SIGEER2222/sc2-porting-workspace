# Stage 06 Plan: Multi-Map Adaptive Self-Training

> Start condition: Stage 05 transport smoke is available, but its python-sc2
> adapter and real reward loop are not accepted as strategy evidence.

## 1. Objective

建立一个跨地图共享的策略训练闭环：同一个 policy 读取固定维度的地图上下文，
通过地图配置和当前观察把高层动作落地为合法目标，并在多个地图环境之间轮换
进行 PPO 自训练。真实 SC2 使用 raw `s2clientprotocol` session contract；
`python-sc2` 保留为可选的 replay/parser 参考，不作为 RL runtime 的权威接口。

## 2. Outputs

```text
cmre_rl_training/map_profiles.py
cmre_rl_training/map_aware.py
cmre_rl_training/action_grounding.py
cmre_rl_training/raw_sc2_backend.py
cmre_rl_training/self_training.py
tests/test_map_profiles.py
tests/test_map_aware.py
tests/test_action_grounding.py
tests/test_raw_sc2_backend.py
tests/test_self_training.py
stages/06-multi-map-self-training/{plan,result,log,issues}.{md,json}
```

## 3. Contracts

- `MapProfileRegistry.resolve(map_name)` always returns a deterministic profile,
  including an unknown-map fallback.
- `MapAwareEnv` appends a stable map-context vector without changing the existing
  49-feature BC encoder contract.
- `MapAwareP2AllyAC` loads the existing BC trunk and learns map-conditioned action
  and value heads with PPO.
- `ActionGrounder` converts a selected high-level action into canonical
  `entity_ids` / target / ability arguments and reports unavailable targets.
- `RawSc2Backend` consumes an injected raw SC2 session that owns Create/Join,
  observation, RequestAction, RequestStep, and Leave lifecycle. The backend never
  fabricates loop or mission progression.
- `MultiMapSelfTrainer` shares one policy across map factories and emits per-map
  metrics plus checkpoint metadata.

## 4. Gates

| Gate | Verification |
|---|---|
| G1-map-context | Known and unknown maps resolve to stable profiles and fixed context width |
| G2-action-grounding | Actions receive valid canonical arguments from observation and map context |
| G3-map-aware-policy | BC trunk loads and contextual policy produces masked logits/value |
| G4-raw-backend | Injected raw session preserves real loop, enemies, action result, and termination |
| G5-self-training | One shared policy trains on at least two map profiles and emits per-map metrics |
| G6-regression | Existing Stage 01-05 tests remain green |

## 5. Non-goals

- 不在本阶段声称已完成所有真实地图的胜率泛化。
- 不修改 `reference/`、launcher、canonical commander mod 或外部模拟器。
- 不把静态 ability ID 写入策略层；真实 ID 解析留给 raw session/catalog client。
- 不在 fake reward 上宣称 BC/PPO 的任务收益提升。

## 6. Validation

```text
PYTHONPATH=.;..\cmre-neuro-adapter;..\cmre-porting python -m unittest discover -s tests -v
python -m json.tool project.json
```

The stage result must distinguish runtime-local multi-map training evidence from
real-SC2 runtime evidence. A full live map matrix remains a follow-up runtime gate.

## 6. Completion

- [x] G1 map context registry and fixed-width schema
- [x] G2 observation-driven action grounding and strict target masks
- [x] G3 map-aware policy, BC trunk warm start, and checkpoint roundtrip
- [x] G4 injected raw SC2 session contract with loop/action/termination evidence
- [x] G5 shared PPO self-training across two map profiles
- [x] G6 full Stage 01-05 regression suite
