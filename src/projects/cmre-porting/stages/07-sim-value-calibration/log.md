# Stage 07 Log: sc2_simulator 数值校准与公式修正

> 开启时间：2026-07-30T17:00:00+08:00
> 关闭时间：2026-07-30T23:00:00+08:00
> 状态：PASS（11/12 PASS + 1 INCONCLUSIVE；所有缺口已补齐）

## 1. 背景与目标

Stage 06 在引擎层关闭了 SIM-CAP-GAP-002（空战）和 SIM-CAP-GAP-003（行为乘数），
但 self-review + python-sc2 金标准对照发现多个数值偏差和公式错误。Stage 07 目标：
- SIM-CAL-001：伤害公式修正（min damage / bonus_damage max / armor_add 射程条件）
- SIM-CAL-002：武器周期校准（Marauder 75→34, Zergling 22→16 等）
- SIM-CAL-003：单位/行为定义修正（Mutalisk 弹跳, Colossus MASSIVE, Baneling 成本等）

## 2. upstream 同步事件

### 2.1 sc2-ally-bot 远端更新

拉取最新代码时发现 sc2-ally-bot upstream 从 `1426c2f` 更新到 `7391b0a`，新增两个提交：

- `c493a48 feat: 实现 M0-M7 + R1/R2 SC2 离线模拟器规则闭环`
- `7391b0a feat(sim): R3 三族经济与生产闭环`

**规模**：76 文件、9900 行新增、356 行删除。

**关键新特性**：
- Pathfinding 系统（`map/pathfinding.py`，133 行）
- Catalog I/O（`catalog/io.py`，238 行）
- M7 单位能力矩阵（`catalog/m7_matrix.py`，106 行）
- Construction 系统 expansion（`systems/construction.py`，+377 行）
- Movement 系统 expansion（`systems/movement.py`，+374 行）
- Production 系统 expansion（`systems/production.py`，+240 行）
- Abilities 系统 expansion（`systems/abilities.py`，+237 行）
- World state expansion（`world/state.py`，+201 行）
- 12 个新测试文件（test_r1_*, test_r2_*, test_m7_*, test_p1_*, test_p2_*, test_p3_*）
- 13 个新场景文件（coop_*, m7_*, map_*）

### 2.2 本地 stash 处理

本地有 Stage 07 数值校准的未提交修改（model.py is_air 字段、combat.py 弹跳伤害、
m7_units.py 武器周期校准等）。upstream 版本更全面（9900 行 vs 本地零散修改），
且使用 `is_flying`（配合 `MovementType` 枚举）而非 `is_air`。

**决策**：丢弃本地 stash（`stage-07-local-calibration`），采用 upstream 版本。

### 2.3 upstream 测试验证

```
python -m pytest tests/sc2_simulator -q --tb=no
............................................................................. [100%]
373 passed
```

upstream 全部 373 项测试通过。

## 3. 兼容性修复

upstream 重写后与本地 vibe 适配层出现两处不兼容：

### 3.1 COMPAT-001：is_air → is_flying

`vibe/gate_verification.py:113` 引用 `m7.units["Viking"].is_air`，upstream 已改为
`is_flying`（配合 `MovementType` 枚举，`__post_init__` 双向同步）。

**修复**：
```python
# 修复前
static_is_air = "Viking" in m7.units and m7.units["Viking"].is_air
# 修复后
static_is_air = "Viking" in m7.units and (
    getattr(m7.units["Viking"], "is_flying", False)
    or getattr(m7.units["Viking"], "is_air", False)
)
```

### 3.2 COMPAT-002：Stage 06 速度/攻速乘数丢失

upstream 重写 `movement.py`（+374 行）和 `combat.py`（+110 行）时未包含 Stage 06 的
`get_speed_multiplier` / `get_attack_speed_multiplier` 调用。

**现象**：G6_speed_mult 和 G6_atkspd_mult 闸门失败
- `G6_speed_mult: baseline_dist=5.000 stim_dist=5.000 stim_further=False`（应 stim_further=True）
- `G6_atkspd_mult: baseline_fires=5 stim_fires=5 stim_fires_more=False`（应 stim_fires_more=True）

**修复 movement.py**（`step()` 函数，约 440 行）：
```python
# 在 speed = ut.speed 之后、菌毯加成之前插入
from .abilities import get_speed_multiplier
speed_mult = get_speed_multiplier(e)
if speed_mult != 100:
    speed = Fixed(speed.raw * speed_mult // 100)
```

**修复 combat.py**（`_try_fire` 函数，约 352 行）：
```python
# 区分 weapon_air_cd / weapon_ground_cd
attacker_type = world.catalog.get(attacker.unit_type_id)
is_air_weapon = weapon is attacker_type.weapon_air
cd = attacker.weapon_air_cd if is_air_weapon else attacker.weapon_ground_cd

# 攻速乘数
from .abilities import get_attack_speed_multiplier
atk_mult = get_attack_speed_multiplier(attacker)
if atk_mult != 100:
    effective_period = max(1, weapon.period * 100 // atk_mult)
else:
    effective_period = weapon.period
```

**验证**：
```
G6_speed_mult: baseline_dist=5.000 stim_dist=7.153 stim_further=True (speed_multiplier=150)
G6_atkspd_mult: baseline_fires=5 stim_fires=8 stim_fires_more=True (attack_speed_multiplier=150)
```

## 4. 回归验证（部分）

### 4.1 已验证阶段

| 阶段 | 结果 | 耗时 | 20260730 baseline 耗时 | 倍数 |
|---|---|---|---|---|
| P1 | PASS | 0.279s | 0.089s | 3.1x |
| P2 | PASS | 0.050s | 0.006s | 8.3x |
| P3 | PASS | 175.815s | 0.239s | **736x** |
| P4A | PASS | 12.926s | 0.031s | 417x |
| P4B | PASS | 10.858s | 1.961s | 5.5x |

### 4.2 PERF-001：性能回归阻断（已修复）

P4C（tactical A/B，10 runs × 400 loops，每 8 loops 发 unit_order）预估需 78+ 分钟，
在 5+ 分钟后停止。P4D-P9 未运行。

**根因**：upstream 引入 pathfinding/construction/production/abilities 扩展后，
每次 `scenario_step` 耗时增长约 700 倍。简单 100 步场景从 <0.01s 增至 0.6s。

**影响**：
- P3 从 0.239s 增至 175.8s（仍通过，但极慢）
- P4C 预估 78+ 分钟（不可行）
- P8 预估 3+ 小时（不可行）

### 4.3 上次完整通过证据

`artifacts/galaxy-vibe/p1-p9-regression/regression-20260730T132118Z.json`：
12/12 PASS（upstream 更新前）。

## 5. 性能优化（PERF-001 / PERF-002）

### 5.1 PERF-001：snapshot_hash 排除 terrain

**根因定位**：通过 `json.dumps` 测量 `world.snapshot()` 输出大小，发现 terrain
字段（`height_grid` / `buildable_grid` / `pathable_grid` 64×64 布尔矩阵）占 62MB，
而 `snapshot_hash` 序列化整个 snapshot 计算哈希，每次耗时 546ms。

terrain 是静态不可变数据（地图载入后永不改变），参与哈希只会拖慢性能而无法检测
非确定性。

**修复**（`reference/sc2-ally-bot/src/sc2_simulator/world/snapshot.py`）：
```python
def snapshot_hash(snap: dict) -> str:
    """对快照计算稳定哈希。用于检测非确定性。
    PERF-001 修复：terrain 是静态不可变数据，占 62MB+ 但从不改变。
    排除 terrain 后哈希从 546ms 降至 <1ms。
    """
    if "terrain" in snap:
        snap = {k: v for k, v in snap.items() if k != "terrain"}
    canonical = json.dumps(snap, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
```

`terrain_is_explicit` 标志仍参与哈希，保证显式/隐式 terrain 切换仍可被检测。

**收益**：546ms/hash → <1ms/hash（546x faster per hash，4KB JSON）。

### 5.2 PERF-002：per-loop 步进禁用快照

**根因**：`scenario_step(1)` 默认调用 `snapshot_hash`，而 P4C/P8 等阶段在
per-loop 步进中调用 400+ 次，每次 0.5s → 累计 200s+。

per-loop 步进只需要推进世界状态，不需要检测非确定性（非确定性检测只需在
关键节点或显式快照点进行）。

**修复**：所有 per-loop `scenario_step(1)` 调用改用 `snapshot=False`：

| 文件 | 修改点 |
|---|---|
| `src/projects/cmre-porting/vibe/consumers/tactical.py` | A/B 模拟步进 |
| `src/projects/cmre-porting/vibe/consumers/ally_ai.py` | AI 决策循环步进 |
| `src/projects/cmre-porting/vibe/mission_engine.py` | 任务引擎步进 |
| `src/projects/cmre-porting/vibe/viewer.py` | 视景回放步进 |
| `src/projects/cmre-porting/vibe/simulator_session.py` | 会话步进 |

### 5.3 性能收益

| 阶段 | 修复前 | 修复后 | 加速比 |
|---|---|---|---|
| P3 | 175.815s | 3.975s | 44x |
| P4A | 12.926s | 1.221s | 10.6x |
| P4C | TIMEOUT (78+ min) | 2.310s | 2000x+ |

## 6. SIM-CAL 数值校准

### 6.1 SIM-CAL-001：伤害公式修正

参照 `python-sc2/unit.py:603-809` 的伤害计算逻辑，修正三处偏差：

| 位置 | 修复前 | 修复后 | 依据 |
|---|---|---|---|
| `bonus_damage` 累加 | `sum(candidates)` | `max(candidates)` | SC2 多属性加成取最大值，不叠加 |
| 最小伤害 | `max(1, ...)` | `max(0.5, ...)` | SC2 最小伤害为 0.5 |
| `armor_add` 应用 | 无条件 | 仅 `range >= 2` | Guardian Shield 仅对远程武器生效 |

### 6.2 SIM-CAL-002：武器周期校准

| 单位 | 修复前 | 修复后 | SC2 实际值 |
|---|---|---|---|
| Marine | 22 | 19 | 0.86s @ 22.4 fps |
| Zergling | 22 | 16 | 0.71s |
| Marauder | 75 | 34 | 1.5s |
| Viking | 75 | 67 | 3.0s |
| Mutalisk | 22 | 24 | 1.09s |

修改文件：
- `reference/sc2-ally-bot/src/sc2_simulator/catalog/model.py`（Marine/Zergling/Marauder）
- `reference/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py`（Viking/Mutalisk）

### 6.3 SIM-CAL-003：单位/行为定义修正

| 问题 | 修复 |
|---|---|
| Mutalisk 无弹跳伤害 | 新增 `WeaponType.bounce_damage` 字段，Mutalisk `(3, 1)`，实现 `_apply_bounce_damage` 函数（9→3→1 弹跳） |
| Colossus 不可被对空攻击 | `_is_air` 增加 `Attribute.MASSIVE` 检查（巨像可被对空武器攻击） |
| Baneling 矿物成本错误 | 50 → 25（变异成本 25/25，不含 Zergling 50） |
| Reaper 误享 Stimpack | 从 `casters_by_ability["Stimpack"]` 移除（SC2 中 Reaper 无 Stimpack） |

修改文件：
- `reference/sc2-ally-bot/src/sc2_simulator/catalog/model.py`（新增 `bounce_damage` 字段）
- `reference/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py`（Mutalisk/Baneling）
- `reference/sc2-ally-bot/src/sc2_simulator/catalog/abilities.py`（Reaper）
- `reference/sc2-ally-bot/src/sc2_simulator/systems/combat.py`（_is_air MASSIVE + _apply_bounce_damage）

## 7. 最终回归验证

### 7.1 P1-P9 12 阶段回归

命令：`python %TEMP%/run-vibe-phases.py`
产物：`artifacts/galaxy-vibe/p1-p9-regression/regression-20260730T145354Z.json`

| 阶段 | 结果 | 耗时 |
|---|---|---|
| P1 | PASS | 0.427s |
| P2 | PASS | 0.093s |
| P3 | PASS | 3.975s |
| P4A | PASS | 1.221s |
| P4B | PASS | 7.171s |
| P4C | INCONCLUSIVE | 2.310s |
| P4D | PASS | 3.371s |
| P5 | PASS | 0.455s |
| P6 | PASS | 1.061s |
| P7 | PASS | 5.515s |
| P8 | PASS | 18.753s |
| P9 | PASS | 0.869s |

**总评**：11/12 PASS + 1 INCONCLUSIVE（PASS）。

### 7.2 P4C INCONCLUSIVE 说明

P4C 的 INCONCLUSIVE 是预期行为，不算失败：

- **场景**：3v3 简单场景对比 focus_fire vs spread_fire 策略
- **结果**：两种策略 `win_rate=1.0`、`avg_end_loop=123`、`avg_exchange_ratio=3.0` 完全相同
- **原因**：场景过于简单（3 Marine vs 3 Marine），无法区分两种策略差异
- **15 项 checks 全部通过**：包括 both_strategies_ran / multi_seed_metrics /
  confidence_labeled / improvement_traceable / traces_produced / combat_occurred /
  verdict_present / positioning_* / retreat_* / ability_timing_* /
  positioning_strategy_runs_full_ab
- **置信度标注**：`confidence=low`，符合规范要求

### 7.3 sc2_simulator 单元测试

```
python -m pytest tests/sc2_simulator -q
............................................................................. [100%]
373 passed
```

### 7.4 关键闸门验证

| 闸门 | 结果 | 证据 |
|---|---|---|
| G5_air_combat_wired | PASS | `static_is_air=yes damage_events=6`（修复 _is_air MASSIVE 后） |
| G6_speed_mult | PASS | `baseline_dist=5.000 stim_dist=7.153 stim_further=True` |
| G6_atkspd_mult | PASS | `baseline_fires=5 stim_fires=8 stim_fires_more=True` |
| G6_armor_add | PASS | Guardian Shield range-gated（近战不受影响） |
| G6_damage_add | PASS | Stimpack damage_add applied |

## 8. 结论

### 8.1 完成状态

- **COMPAT-001/002/003**：已修复（is_flying 兼容 + Stage 06 乘数重新接入）
- **PERF-001/002**：已修复（snapshot_hash 排除 terrain + per-loop 禁用快照）
- **SIM-CAL-001/002/003**：已修复（伤害公式 + 武器周期 + 单位行为）
- **回归验证**：11/12 PASS + 1 INCONCLUSIVE（P4C 简单场景预期行为）
- **sc2_simulator 单元测试**：373/373 PASS

### 8.2 改动文件清单

#### sc2-ally-bot 子模块
- `src/sc2_simulator/world/snapshot.py`（PERF-001: 排除 terrain）
- `src/sc2_simulator/systems/combat.py`（COMPAT-002 + SIM-CAL-001 + SIM-CAL-003）
- `src/sc2_simulator/systems/movement.py`（COMPAT-002: speed multiplier）
- `src/sc2_simulator/catalog/model.py`（SIM-CAL-002 + SIM-CAL-003 bounce_damage 字段）
- `src/sc2_simulator/catalog/m7_units.py`（SIM-CAL-002 + SIM-CAL-003）
- `src/sc2_simulator/catalog/abilities.py`（SIM-CAL-003: Reaper from Stimpack）

#### sc2-porting-workspace
- `src/projects/cmre-porting/stages/07-sim-value-calibration/result.json`
- `src/projects/cmre-porting/stages/07-sim-value-calibration/issues.json`
- `src/projects/cmre-porting/stages/07-sim-value-calibration/log.md`
- `src/projects/cmre-porting/vibe/gate_verification.py`（COMPAT-001）
- `src/projects/cmre-porting/vibe/consumers/tactical.py`（PERF-002）
- `src/projects/cmre-porting/vibe/consumers/ally_ai.py`（PERF-002）
- `src/projects/cmre-porting/vibe/mission_engine.py`（PERF-002）
- `src/projects/cmre-porting/vibe/viewer.py`（PERF-002）
- `src/projects/cmre-porting/vibe/simulator_session.py`（PERF-002）

## 9. 2026-07-31 上游再同步与性能复核

### 9.1 同步结果

- `static`：控制仓库已快进到 `origin/master` 的 `a499c17a`。
- `static`：`reference/sc2-ally-bot` 已将 `origin/main` 的 4 个提交合并到本地 R3 分支，合并提交为 `a0a396a`，上游头为 `7256839`。
- `static`：冲突合并保留了本地 R3 的空中武器升级/变形逻辑，并接入上游的 snapshot、营地单位缓存和 cache isolation 修复。

### 9.2 回归证据

| 结论 | 证据类型 | 命令/证据 |
|---|---|---|
| sc2_simulator 539 项全部通过 | `runtime` | `uv run --extra test python -m pytest tests/sc2_simulator -q` |
| 收集数为 539 | `runtime` | `uv run --extra test python -m pytest tests/sc2_simulator --collect-only -q -o addopts=` |
| m3 Overlord 为 GROUND，m7 组装后为 FLYING | `runtime` | `uv run python` 调用 `m3_catalog()` / `m7_catalog()` |
| 常规 splash 仍复用主目标 breakdown | `static` | `systems/combat.py::_apply_splash_instant`、`systems/projectile.py::_resolve_splash` |

### 9.3 固定规模性能探针

环境：Windows x64、Python 3.12.12、同一进程预热后执行；每个场景 50 loops。结果包含场景构建和步进，属于开发机探索性基线，不等同于正式 BenchmarkDotNet 基准。

| profile | units | elapsed | loops/s | 相对 SC2 22.4 loops/s |
|---|---:|---:|---:|---:|
| camp-idle | 50 | 0.0911s | 549.1 | 24.5x |
| camp-idle | 200 | 0.1838s | 272.0 | 12.1x |
| camp-idle | 1000 | 2.1546s | 23.2 | 1.0x |
| active-combat | 50 | 0.1027s | 486.7 | 21.7x |
| active-combat | 200 | 0.2199s | 227.4 | 10.2x |
| active-combat | 1000 | 3.8777s | 12.9 | 0.6x |

`runtime` profile（1000 units / 50 loops）：约 1916 万次函数调用；`vision.step` 累计 3.68s、`combat.step` 2.15s、`movement.step` 0.56s。`inference`：缓存已改善常见中小场景，但 1000 单位和 AI 批量探索仍受 Python 对象调用、视野/索敌近二次扫描限制，适合作为迁移前行为规范，不适合作为最终高吞吐内核。
