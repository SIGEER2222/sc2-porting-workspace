# SC2 RL 训练系统设计文档（方案 C：python-sc2 + 自研 PPO + 混合 sim2real）

**日期**：2026-08-04
**状态**：待用户复核
**目标**：以开源 `python-sc2`(BurnySc2) 为真 SC2 框架，结合现有回放提取工具（`cmre-neuro-adapter` 的 JSONL 契约 + `cmre-porting/vibe/ml` 的 BC 管线），自研 PyTorch PPO，在 coop PvE 场景（Dead of Night / CMRE）上训练 SC2 AI，采用模拟器为主、真 SC2 为辅的混合 sim2real 路线。

---

## 0. 选型结论与已确认约束

| 维度 | 结论 |
|---|---|
| 训练范式 | 在线 RL（PvE，agent vs 环境），PPO |
| 博弈场景 | coop 任务（Dead of Night / CMRE），复用现有 JSONL 契约与回放 |
| 环境后端 | 混合 sim2real：`SimulatorSession` 主训练 + 真 SC2 评估/微调 |
| SC2 框架 | `reference/python-sc2`(BurnySc2)：BotAI 基类 + 回放解析 + `sc2/ids/` |
| RL 实现 | 自研 PPO（纯 PyTorch，与现有 `vibe/ml` 同栈） |
| 预训练 | 现有 `vibe/ml/training.py` BC 4 头模仿学习 |
| 项目落位 | 新建 `src/projects/cmre-rl-training/`（默认，最小侵入） |
| writeScope | 仅新项目目录；通过子类化扩展网络，不改 `vibe/ml` 现有文件 |

**硬约束（来自 AGENTS.md / 用户规则）**：
- 真 SC2 必须经 `tools/launchers/launch-cmre-alenger.ps1` 启动，禁止直接 `SC2_x64.exe`。
- launcher 退出码 0 只代表加载完成；还需复核 `GameLogs/*ScriptError*.txt` 并取得 runtime 证据。
- 不修改外部只读源（`reference/*` 仅 import/参考）。
- 证据分类：`static` / `runtime` / `inference`，log 必须记录证据路径与命令。

---

## 1. 架构总览

```text
┌─────────────────────────────────────────────────────────────┐
│  训练驱动 (hand-rolled PPO, PyTorch)                          │
│  rollout buffer → GAE → clipped objective + value + entropy  │
└───────────────┬─────────────────────────────────────────────┘
                │ policy.step(obs, action_mask)
┌───────────────▼─────────────────────────────────────────────┐
│  策略网络 P2AllyAC (子类化 P2AllyPolicyNet)                    │
│  共享 trunk + 4 BC 头 + value 头 + action 头 + param 头        │
│  obs = encode_observation(PublicMissionContext) 定长向量      │
└───────────────┬─────────────────────────────────────────────┘
                │ ActionCommand (复用现有契约)
┌───────────────▼─────────────────────────────────────────────┐
│  CmreRLEnv (统一环境接口, Gymnasium 风格)                      │
│  reset/step/action_mask/reward/terminated                     │
└───────┬───────────────────────────────┬─────────────────────┘
        │ SimulatorBackend              │ PythonSc2Backend
┌───────▼──────────────────┐  ┌────────▼─────────────────────────┐
│ SimulatorSession (现有)   │  │ python-sc2 BotAI 子类 (新建)      │
│ 数千步/秒, 确定性, 可 DR   │  │ launcher 启动真 SC2, ~几步/秒/实例 │
│ 训练主战场                │  │ 评估 + sim2real 微调              │
└──────────────────────────┘  └──────────────────────────────────┘
        ▲                                  ▲
        └──── PublicMissionContext (统一观测) ┘
        ┌──── 回放 BC 预训练 ─────────────────┐
        │ 现有 JSONL → build_examples → train_pytorch_policy (已有)
        │ + python-sc2 replay parser 补充解析(可选)
```

**核心思想**：现有 `PublicMissionContext` + `ActionCommand` 契约横跨模拟器与真 SC2；RL 看到的 obs/action 与 BC 预训练完全一致；sim2real 只换后端不换契约，零迁移成本。

---

## 2. 环境层（双后端统一接口）

新建 `CmreRLEnv`，保持 `reset()/step()/action_mask()` 与 Gymnasium 同形（不强制继承，便于自研 PPO 直接消费）。

### 2.1 SimulatorBackend
- 包装现有 `SimulatorSession` + `SimulatorSessionBackend`（`cmre-neuro-adapter/cmre_neuro_adapter/neuro/simulator_transport.py`）。
- `reset()`：重置场景 fixture + `MapScript` 脚本模型（`full_game_replay.build_full_game_replay` 同源输入）。
- `step(ActionCommand)`：经 `route_basic_action`（`neuro/basic_actions.py`）→ `SimulatorTransport.execute`；产出 `(PublicMissionContext, reward, terminated, info)`。
- **Domain Randomization**：每 episode 随机 `(seed, wave_strength_scale∈[0.8,1.2], time_scale, fog_range, 敌人组成扰动)`，缩小 sim2real gap。

### 2.2 PythonSc2Backend
- 新建 `python-sc2` `BotAI` 子类（参考 `reference/python-sc2/examples/competitive/bot.py`）。
- `on_step` 内把 `bot.units/bot.enemy_units/bot.mineral_field` 等投影成 `PublicMissionContext`，复用 `MissionContextProjector`（`neuro/mission_projection.py`）思路。
- `ActionCommand` → python-sc2 `UnitCommand`/`AbilityId`，用 `sc2/ids/ability_id.py`、`unit_typeid.py` 翻译。
- 由 `tools/launchers/launch-cmre-alenger.ps1 -MapName <map> -Commander TerranRaynor` 启动。

### 2.3 向量化与节奏
- 模拟器：`SubprocVecEnv` 风格多进程，N=8~16。
- 真 SC2：有限实例（2~4）做评估/微调，避免算力爆炸。
- step 节奏：模拟器 1 step = 1 模拟 loop；真 SC2 `step_mul` 8~16（游戏步/决策），决策频率与模拟器对齐（注意 `step_mul` 是游戏步数，与 JSONL 的 `time_scale` 单位不同，此处仅对齐决策频率而非数值）。

---

## 3. 观测与动作空间（复用现有契约）

### 3.1 观测
直接用 `vibe/ml/encoder.py` 的 `encode_observation(context)` → `FEATURE_NAMES` 定长 float 向量（schema `cmre-ally-observation.v2` + `feature_schema_hash()` 校验）。两后端都产出 `PublicMissionContext`，编码后向量同形，BC 预训练与 RL 微调无 schema 漂移。

### 3.2 动作空间
复用 `neuro/basic_actions.py` 的 `BASIC_ACTION_ROUTES`（move/stop/hold/patrol/attack_move/attack/gather/build/produce/research/cast×3/repair/morph/cancel/load/unload/rally，约 20 种）作为离散动作 id。每个动作带参数槽：
- `target_entity_id`（从可见单位选）
- `target_x, target_y`（归一化坐标）
- `unit_type_id`（build/produce/research 时）

### 3.3 动作掩码
每步根据 `PublicMissionContext` 计算合法动作集（无兵则 attack/move 掩掉、无资源则 build/produce 掩掉），策略 logits 在掩码位置置 `-inf`。解决 SC2 动作空间大半非法的核心痛点。

### 3.4 策略输出
- 4 个 BC 头（economy/production/tactical/command，与 `HEAD_LABELS` 一致）
- 动作 id 分类头（`Linear→num_actions`，带 mask）
- 参数回归头：目标坐标归一化、目标 unit 从可见单位列表选

---

## 4. 策略网络与 PPO 循环

### 4.1 网络 P2AllyAC
子类化 `P2AllyPolicyNet`（不改原文件）：
- 保留共享 trunk + 4 BC 头（BC 预训练权重直接加载）
- 新增 `value_head`（`Linear(hidden,1)`）
- 新增 `action_head`（`Linear(hidden,num_actions)`，前向应用 mask）
- 新增 `param_heads`（坐标回归 + unit 选择）

### 4.2 PPO 循环（自研，纯 PyTorch）
- **Rollout**：N 个并行 env 各跑 T 步，存 `(obs, action, logprob, value, reward, done, mask)`。
- **GAE-λ** 估优势 `Â_t`。
- **目标**：`L = -L_clip + c1·L_value - c2·H[π]`，`clip=0.2`，`c1=0.5`，`c2=0.01`。
- **优化器**：`AdamW`，与 BC 同。
- **多 epoch minibatch**：每批 rollout 跑 K=4~10 epoch。

### 4.3 BC→RL 衔接
- 先 `train_pytorch_policy` 跑 BC（已有），checkpoint 加载到 `P2AllyAC` 的 trunk + 4 头。
- RL 阶段只新初始化 value/action/param 头。
- 可选 BC 正则项（`+ λ·L_bc`）防 RL 早期崩坏。

### 4.4 checkpoint
复用 `save_checkpoint` schema，扩展记录 value/action/param 头与 PPO 训练元数据（timesteps、reward 均值、entropy）。

---

## 5. 奖励设计（从 mission context 导出）

逐 step 增量（密集）+ 终止（稀疏）：

| 信号 | 来源 | 奖励 |
|---|---|---|
| 基地存活 | `resources`/`own_units` | `+ε·base_hp_ratio`，受损 `-Δbase_hp` |
| 夜晚存活 | `mission.night` + `events[].kind=night_started/ended` | 期间每步 `+ε`，被攻破 `-大` |
| 造兵/经济 | `events[].kind=train_completed/build_completed` | 事件 `+`，`supply_used` 增长 `+ε`，闲置 worker `-ε` |
| 杀敌 | 敌方 unit 死亡 | `+`，按 unit 价值加权 |
| 任务进度 | `mission.progress` 增量 | `+` |
| 终止 | `mission.terminated` | 胜 `+10`，败 `-10` |

奖励用 running mean/std 归一化，跨 episode 对齐。所有信号都来自现有 `frame`/`action`/`events` 字段，无需新观测。

---

## 6. sim2real 与训练调度

- **主训练**：`SimulatorBackend` + 多进程，百万级 PPO step。
- **Domain Randomization**：每 episode 随机 `(seed, wave_strength_scale, time_scale, fog_range, 敌人组成)`。
- **周期性真 SC2 评估**：每 K step 用 `PythonSc2Backend` 跑 N 局，记录胜率/存活夜晚数/基地血；**必须**经 launcher 启动 + 复核 `GameLogs/*ScriptError*.txt`（遵守 SC2 launch rules）。
- **sim2real 微调**（二阶段可选）：真 SC2 上小步 PPO 微调，发现 sim 缺失行为后回灌模拟器补 DR。
- **证据**：训练曲线（TensorBoard/W&B）+ 评估局 JSONL + GameLogs 复核记录，全部落 `artifacts/projects/cmre-rl-training/`。

---

## 7. 回放预训练与 python-sc2 补充

- **BC 预训练**：现有 JSONL（模拟器 + `manual_replay_capture.py` 真实抓取产物）→ `build_examples` → `train_pytorch_policy`，产出 `P2AllyPolicyNet` checkpoint，作为 RL 起点。
- **python-sc2 回放补充**（可选）：用 `reference/python-sc2` 的 `observer_ai`/`test/test_replays.py` 模式解析更多 `.SC2Replay`，转成同形 `PublicMissionContext` JSONL，扩充 BC 数据。

---

## 8. 项目结构与阶段切分

### 8.1 项目落位
新建 `src/projects/cmre-rl-training/`，带 `project.json` + 阶制 `stages/`，符合 AGENTS.md 工作流。

`project.json` 关键字段：
- `id`: `cmre-rl-training`
- `goal`: 在 coop PvE 场景用 python-sc2 + 自研 PPO 训练 SC2 AI，复用现有回放契约与 BC 管线
- `sources`: `cmre-neuro-adapter`(contracts/transports/simulator)、`cmre-porting/vibe/ml`(encoder/model/training)、`python-sc2`(reference，真 SC2 框架)
- `target`: `{map: dead-of-night, commander: TerranRaynor, series: cmre-coop-missions, aiProfile: rl-policy}`
- `writeScope`: `["src/projects/cmre-rl-training/**"]`

### 8.2 阶段切分（粗）
1. `01-env-contracts`：`CmreRLEnv` 接口 + `action_mask` + reward 计算离线单测
2. `02-simulator-backend`：`SimulatorBackend` 跑通 reset/step，DR 参数化
3. `03-ppo-loop`：`P2AllyAC` + 自研 PPO，模拟器上收敛性验证（mini 场景）
4. `04-bc-pretrain`：现有 JSONL BC 预训练，checkpoint 加载到 `P2AllyAC`
5. `05-sim2real-eval`：`PythonSc2Backend` + launcher 评估，GameLogs 复核

### 8.3 关键依赖
- `torch`（已有）、`python-sc2`(burnysc2，pip)、`gymnasium`（仅接口参考，可选）、`tensorboard`
- 真 SC2 实例经 launcher，不直接依赖 `s2clientprotocol`（python-sc2 自带）

---

## 9. 验收标准

- `CmreRLEnv` 两后端产出同形 `(obs, reward, terminated, info)`，`feature_schema_hash` 一致。
- BC 预训练 checkpoint 可加载到 `P2AllyAC`，4 头指标不低于现有 `vibe/ml` 基线。
- 自研 PPO 在模拟器 mini 场景上 reward 单调上升、entropy 下降（runtime-local 证据）。
- 真 SC2 评估至少完成一局完整任务，launcher 退出码 0 + `GameLogs` 无新增 `ScriptError` + runtime listener 证据（runtime 证据）。
- `result.json`/`issues.json`/`log.md` 符合 stage schema，证据分类明确。

---

## 10. 风险与对策

| 风险 | 对策 |
|---|---|
| sim2real gap 大 | 强化 DR；真 SC2 微调二阶段；记录失败 case 回灌 |
| 真 SC2 实例吞吐低 | 仅评估/微调用，主训练在模拟器 |
| 动作空间稀疏合法 | 动作掩码 + BC 预训练暖启动 |
| python-sc2 与现有 Sc2ApiTransport 重叠 | 各司其职：RL 真环境用 python-sc2 BotAI（方案 C 选型）；Neuro 适配器保留 Sc2ApiTransport。两者共享 `PublicMissionContext` 契约，不互相替换 |
| 自研 PPO 实现错误 | mini 场景先与 BC 策略对齐验证；保留随机/BC baseline 对比 |
