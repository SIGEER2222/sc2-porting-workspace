# P0 Evidence — sc2_simulator 能力矩阵审计

- 日期：2026-07-30
- 审计目标：`tools/sc2-ally-bot/src/sc2_simulator`（候选规范引擎）
- 审计性质：**只读静态分析**（未运行代码；动态验证留待 P3 核心运行时验收）
- 证据分类：`static`（源码阅读）；能力裁决为 `inference`，待 P3 动态验证后升级
- 上游计划：`simulator-first-platform-plan.md` 第 9 节执行顺序第 2 步、P3 核心门

## 0. 仓库边界与外部依赖（先于能力裁决）

- `tools/sc2-ally-bot` **不是 git submodule**，是工作区内普通目录（无 `.git`，不在 `.gitmodules`）。
  `reference/sc2-ally-bot` 是另一份独立 submodule，二者非同一份代码。
- `sc2_simulator` 与 `ally_bot` **完全解耦**：`sc2_simulator` 不 import `ally_bot`；`ally_bot` 不 import
  `sc2_simulator`。`__init__.py` docstring 明示"不依赖 ally_bot"。
- **外部依赖**：纯 Python 标准库（`heapq/random/math/json/hashlib/dataclasses/enum/pathlib/argparse/typing/collections/types`）。
  无 numpy、无 burnysc2/python-sc2（`pyproject.toml` 列 burnysc2 为可选，包内 0 处 import）。
- **无 SC2 可执行文件 / SC2 API / Bank / GameLogs 依赖**（grep 0 命中）。
- 结论：`sc2_simulator` 是自包含、零外部依赖、纯 Python 的确定性规则引擎，可独立部署。
  **此条直接满足 P0 门「本地关键路径不依赖 SC2 可执行文件/API 端口/Bank/桌面截图/GameLogs」。**

## 1. 能力矩阵（对照 P3 核心门与 §4.2 IR 覆盖）

| 门领域 | 裁决 | 关键证据（file:line） | 主要缺口 |
|---|---|---|---|
| G1 时间/事件/RNG/快照/trace | **COMPLETE** | `clock.py:16-69`（整数 loop、`tick`/`restore`）；`events.py:22-35,75-81`（`sort_key=(loop,sys_pri,entity_id,seq)`，`MappingProxyType` 冻结 payload）；`rng.py:17-22,139-144`（4 流独立 seed，`getstate` hex 编码入快照）；`world/snapshot.py:18-39`（SHA256+clone）；`reporting/trace.py:58-78`（JSONL+SHA256） | **无 replay 重放器**（只写不读）；`snapshot_interval` 字段存在但 runner 未消费；`SPEED_DIV=22` 对 22.4 有 1.8% 误差 |
| G2 实体生命周期与稳定身份 | **COMPLETE** | `world/state.py:92-94,99-125`（`_next_entity_id` 单调从 1，入快照）；`world/entity.py:23-36`（`UnitState` 11 态）；`entity.py:156-162`（`is_alive`/`is_structure_complete`）；`state.py:170-174`（`remove_dead`） | spawn 无显式事件（仅 `entity_removed`）；`facing` 字段未使用 |
| G3 资源/供给/建造/生产/研究 | **COMPLETE**（简化标注） | `systems/economy.py:38-250`（采集状态机、`recompute_supply`）；`systems/construction.py:46-238`（BUILD/CANCEL，预扣+完工结算）；`systems/production.py:44-247`（TRAIN/CANCEL/RALLY）；`systems/upgrades.py:33-135`（RESEARCH+效果应用）；`world/state.py:22-68`（`Resources` 含 reserved） | 不实现多工人共享资源点产能；无 Refinery 完整流程；单队列（无 TechLab/Reactor 双队列）；取消全额退款；每建筑同时仅 1 项研究 |
| G4 移动/寻路/占位/碰撞/视野/迷雾 | **PARTIAL** | `systems/movement.py:30-65`（直线移动+到达吸附）；`world/terrain.py`（height/buildable/pathable 网格）；`systems/vision.py:31-123`（sight/隐形/高地减半） | **无寻路**（纯直线不绕障）；**无单位碰撞**（可重叠）；**无占地冲突**（建筑仅半径近似）；**无持久迷雾记忆**；**无视野遮挡射线**；LINE 溅射按 CIRCLE 近似 |
| G5 武器/护盾/护甲/弹体/伤害/死亡/归属 | **COMPLETE**（空军缺口） | `systems/combat.py:46-108`（完整伤害公式 base+bonus-type_mult-armor，`Fixed.raw`）；`combat.py:360-432`（护盾先扣+死亡归属 `killer_player`）；`systems/projectile.py:83-318`（飞行+命中+splash 衰减）；`systems/shields.py`（10 loop/1 护盾）；`systems/repair.py`（SCV 维修） | **`_is_air` 恒 False**（`combat.py:41-43`），`weapon_air` 定义但从不查询 → Viking/Phoenix/Mutalisk 空对空武器实际不开火；damage_point/backswing 未使用；ConcussiveShells 减速复用 FungalBehavior（stub） |
| G6 技能/效果/行为/校验器/升级 | **PARTIAL** | `systems/abilities.py:232-358`（CAST 校验+冷却+能量+效果执行）；`catalog/abilities.py:27-306`（11 EffectKind/8 BehaviorKind/18 标准技能）；行为推进+能量恢复 | **无 validators**（`CValidator` 完全缺失）；**无 charges**；多技能是 stub（NeuralParasite/ConcussiveShells/GravitonBeam/Cloak）；**行为 multiplier 未接入规则**：`get_speed_multiplier`/`get_attack_speed_multiplier` 存在但 `movement.py`/`combat.py` 不调用 → Stimpack 加速、Fungal 定身实际不生效；`armor_add`/`damage_add` 行为字段未应用 |
| G7 触发器/区域/波次/目标/终局 | **STUB** | `tools/triggers.py:7-29`（Trigger 模型+`maybe_fire`）；`tools/dsl.py`（ScenarioBuilder fluent）；`scenario/runner.py:160-175`（`check_win_condition` 按 annihilation） | **`TriggerEngine` 是死代码**：runner 主循环从未调用 `TriggerEngine.step`；**无区域系统**（无 Region/Area）；**无波次系统**；**无目标系统**（仅 annihilation）；**无法承载任务剧本**——这是整个模拟器最大功能空白 |
| G8 货舱/召唤/变形/Add-on/种族机制 | **PARTIAL** | `systems/morph.py:24-170`（MORPH+Larva 生成，覆盖 Larva→12 单位/Drone→14 建筑/Hatchery 链/Spire 链）；`systems/repair.py`（Terran 维修）；`systems/shields.py`（Protoss 护盾） | **无货舱/运输**（`LOAD`/`UNLOAD` 枚举有定义但 runner 无 handler）；**无召唤**（Broodling/Locust 无生成机制）；**无 Add-on 构建**（TechLab/Reactor 仅占位，无 BUILD Addon 命令/双队列）；**无 Pylon 供电**；**无 Warp-in**；**无菌毯**；**无攻城武器切换**；**无 Queen 注卵** |

## 2. Catalog / IR 层（对照 §4.2、§4.4）

- **IR Schema**：手写 Python `frozen=True` dataclass，非 XML 导入。`CatalogSnapshot`（`catalog/model.py:160-174`）
  含 `schema_version`/`units: MappingProxyType`/`content_hash`。规则用独立 dataclass（`BuildRule`/`ProductionRule`/
  `MorphRule`/`UpgradeType`/`AddonType`）。
- **已定义单位**：约 70 个 UnitType，按里程碑分层（M0/M1/M2/M3/M7）。
- **源溯源 / 保真度追踪**：
  - `content_hash` 是**静态字符串**（如 `"m7-standard"`，`m7_units.py:1876`），**不是计算出的内容哈希** → 无法检测 catalog 内容漂移。
  - **无逐单位保真度标签**（无 exact/approximate/partial/unsupported）。
  - `catalog/coverage.py` 是**手工自声明**覆盖清单（IMPLEMENTED/PARTIAL/UNSUPPORTED），非从代码或 catalog 派生；
    部分标注与实际实现有出入（如 `terran.addon` 标 PARTIAL 但实际 add-on 完全无构建逻辑）。
  - runner 用 `coverage.mark_used()` 标记运行时实际触发的条目，写入 `summary.json`（capability 使用覆盖的雏形）。
- **缺口**：无 Catalog 内容哈希、无 XML 导入、无逐单位 provenance、无保真度标签。
  **这直接对应 §4.2「每个导入规则携带 source hash / IR schema version / fidelity」与 P2 闸门尚未满足。**

## 3. Scenario / 断言 / CLI / 定点数 / 报告 / 公共 API

- **Scenario**（`scenario/model.py:43-59`）：`ScenarioDefinition` 含 players/spawns/commands/max_loops/seed/
  strict/win_condition/initial_resources/terrain。**无 per-step 断言**、无 expected-state 校验、无期望事件序列断言。
  runner 主循环顺序固定（注入→movement→combat→projectile→economy→construction→production→upgrades→repair→
  morph→shields→vision→abilities→supply→events→remove_dead→win_check→tick）。
- **CLI**（`cli.py:153-189`）：5 子命令 `run/step/compare/sweep/inspect`，`python -m sc2_simulator run --scenario ...`。
- **定点数**（`fixed.py`）：`Fixed` `SCALE=1024`，加减乘完整，显式 round-half-up；**无除法、无 sqrt/trig**。
- **报告**（`reporting/trace.py`/`tools/report.py`/`compare.py`/`batch.py`）：JSONL trace+SHA256、summary.json、
  A/B 对比、参数扫描、批量、Markdown 表；**无 replay 播放器、无可视化**。
- **公共 API**：`__init__.py` 仅 `from . import cli`，**无 `__all__`、无 re-export 核心类**。
  无 `Catalog`/`Scenario`/`Observation`/`Action`/`Snapshot`/`Trace`/`Capability` 顶层契约（§4.4 全缺）。
  **这是作为「候选规范引擎」的显著缺口，消费者当前必须深入子模块 import。**

## 4. 关键发现（影响 P1+ 规划）

1. **G7 是最大功能空白**：TriggerEngine 死代码，runner 不调用。模拟器当前**只能做纯战斗/经济闭环，无法承载任务剧本**。
   若要作为「任务规则平台」（§2 消费者「Mission and wave tooling」），G7 是首要实现优先级。
2. **空军战斗未接入**：`_is_air` 恒 False，`weapon_air` 从不查询。所有对空武器（Viking/Phoenix/Mutalisk/
   Corruptor/MissileTurret/SporeCrawler）实际无法开火。这是 G5 的隐性重大缺口，静态阅读才能发现。
3. **行为 multiplier 未接入规则**：`get_speed_multiplier`/`get_attack_speed_multiplier` 存在但 movement/combat 不调用，
   导致 Stimpack 加速、Fungal 定身**看似实现实则无效**。这是「假完成」陷阱，必须用动态场景验证。
4. **无稳定公共 API**：消费者无法依赖顶层契约，必须深 import。**P1（统一协议+SimulatorTransport）的首要工作
   之一是建立 §4.4 的顶层契约层**，而非直接复用现有子模块。
5. **Catalog 无内容哈希/无保真度**：`content_hash` 是静态字符串，无法检测漂移；无 XML 导入。**P2（Catalog 桥接）
   必须先补内容哈希与保真度标签**，否则 §4.2「source hash + IR schema version + fidelity」与 P2 闸门无法满足。
6. **确定性基础扎实**：时钟、事件排序、RNG 状态、快照、trace 哈希全闭环——这是作为「确定性规则引擎」的最强基础，
   也是 P0 选定 simulator-first 方向的核心理由。
7. **仓库边界清晰**：`sc2_simulator` 自包含、零外部依赖、与 `ally_bot` 解耦，可独立提取为独立仓库。
   详见 `p0-ownership-decision-2026-07-30.md`。

## 5. 待动态验证项（P3 核心运行时验收）

本审计基于静态阅读，以下结论需 P3 动态场景验证：
- 行为 multiplier 是否真的不生效（Stimpack 加速、Fungal 定身）。
- 空军武器是否真的不触发（Viking 对空）。
- 快照/恢复后 trace 哈希是否一致。
- 长时间运行 ID 是否稳定。
- 11 个现有场景（`scenarios/sc2-simulator/*.json`）+ 10 个测试文件（`tests/sc2_simulator/test_m0_*.py`~
  `test_m7_content.py`）的动态通过情况。
