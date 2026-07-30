# Stage 07 Log: sc2_simulator 数值校准与公式修正

> 开启时间：2026-07-30T17:00:00+08:00
> 状态：BLOCKED（upstream 同步 + 兼容性修复完成；P4C+ 被 700x 性能回归阻断）

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

### 4.2 PERF-001：性能回归阻断

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

## 5. SIM-CAL 缺口评估

对照 Stage 07 plan.md 中的三个缺口，检查 upstream 现状：

### SIM-CAL-001：伤害公式偏差 — 仍存在

| 位置 | 问题 | upstream 现状 |
|---|---|---|
| `_compute_damage_breakdown` 最小伤害 | 应 max(0.5,...) | 仍用 `max(1, ...)`（line 114） |
| `bonus_damage` 计算 | 应取 max | 仍用 `sum()` 累加（line 77） |
| `armor_add` 射程条件 | 应仅 range≥2 | 仍无条件应用（line 110-111） |

**注**：upstream 已有更完整的 attacker/target entity 加成支持（升级 `weapon_damage_bonus`、
行为 `damage_buff`/`armor_buff`/`guardian_shield`），但三个核心公式偏差未修正。

### SIM-CAL-002：武器周期偏差 — 仍存在

| 单位 | upstream period | 应有 period | 偏差 |
|---|---|---|---|
| Marauder | 75 | 34 | +123% |
| Zergling | 22 | 16 | +41% |
| Marine | 22 | 19 | +14% |
| Viking | 75 | 67 | +12% |
| Mutalisk | 22 | 24 | -10% |

### SIM-CAL-003：单位/行为定义 — 部分仍存在

| 问题 | upstream 现状 |
|---|---|
| Mutalisk 弹跳伤害 | 无 `bounce_damage` 字段 — 仍缺 |
| Colossus MASSIVE 对空 | `_is_air` 仅检查 `is_flying`，不检查 MASSIVE — 仍缺 |
| Baneling 矿物成本 | 待核实 |
| Reaper 误享 Stimpack | 待核实 |

## 6. 结论与下一步

### 当前状态

- **COMPAT-001/002**：已修复（is_flying 兼容 + Stage 06 乘数重新接入）
- **SIM-CAL-001/002/003**：仍存在（upstream 未修正这些公式/数值偏差）
- **PERF-001**：阻断 P4C-P9 回归验证

### 下一步建议

1. **性能优化**（最高优先级）：优化 pathfinding 查询（缓存/惰性）、减少
   construction/production 每步扫描、或为 vibe 回归提供轻量 catalog/配置
2. **SIM-CAL 校准**：在性能优化后，按 plan.md 逐项修正 SIM-CAL-001/002/003
3. **完整回归**：重新运行 P1-P9 12 阶段回归，确认 12/12 PASS

## 7. 改动文件清单

### 本阶段新建
- `src/projects/cmre-porting/stages/07-sim-value-calibration/result.json`
- `src/projects/cmre-porting/stages/07-sim-value-calibration/issues.json`
- `src/projects/cmre-porting/stages/07-sim-value-calibration/log.md`

### 本阶段修改
- `src/projects/cmre-porting/vibe/gate_verification.py`（COMPAT-001: is_air → is_flying）
- `reference/sc2-ally-bot/src/sc2_simulator/systems/movement.py`（COMPAT-002: speed multiplier）
- `reference/sc2-ally-bot/src/sc2_simulator/systems/combat.py`（COMPAT-002: atkspd multiplier + weapon_air_cd）

### 未修改（保留 upstream 版本）
- `reference/sc2-ally-bot/src/sc2_simulator/catalog/model.py`（SIM-CAL-001/002/003 待修正）
- `reference/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py`（SIM-CAL-002 待校准）
- `reference/sc2-ally-bot/src/sc2_simulator/systems/abilities.py`（SIM-CAL-003 待核实）
