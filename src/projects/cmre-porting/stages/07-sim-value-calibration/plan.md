# Stage Plan: sc2_simulator 数值校准与公式修正

> **背景**：stage 06 在引擎层关闭了 SIM-CAP-GAP-002（空战）和 SIM-CAP-GAP-003（行为乘数），
> 但 self-review + python-sc2 金标准对照发现多个数值偏差和公式错误。本阶段用
> python-sc2 的 `calculate_damage_vs_target`（社区金标准，经 damagetest_bot.py 实测校验）
> 和 Sharky 的 `DamageService.CanDamage`（C# 社区实现）作为参照，校准 sc2_simulator 的
> 伤害公式、武器周期、行为定义和单位数值。

## 1. 缺口分析（static 证据，对照 python-sc2 + Sharky）

### SIM-CAL-001：伤害公式偏差

| 位置 | 问题 | 金标准来源 |
|---|---|---|
| `combat.py:_compute_damage_breakdown` | 最小伤害用 `max(1, ...)`（整数 1 点） | python-sc2 `unit.py:734,745,748` 每发 `max(0.5, ...)` |
| `combat.py:_compute_damage_breakdown` | bonus_damage 累加所有匹配属性 | python-sc2 `unit.py:723` `max(boni)` 取最大值 |
| `combat.py:_compute_damage_breakdown` | armor_add 无射程条件 | python-sc2 `unit.py:652-653` Guardian Shield +2 仅对射程 ≥2 远程武器 |

### SIM-CAL-002：武器周期严重偏差

| 单位 | sc2_simulator period | python-sc2 weapon.speed | 换算 period (×22.4) | 偏差 |
|---|---|---|---|---|
| Marauder | 75 | 1.5s | ~34 | **+123% 严重** |
| Zergling | 22 | 0.696s | ~16 | +41% |
| Marine | 22 | 0.86s | ~19 | +14% |
| Viking | 75 | 3.0s | ~67 | +12% |
| Mutalisk | 22 | 1.09s | ~24 | -10% |

### SIM-CAL-003：单位/行为定义错误

| 位置 | 问题 | 金标准来源 |
|---|---|---|
| `abilities.py:649` | Reaper 误享 Stimpack（casters_by_ability 含 "Reaper"） | python-sc2 `unit.py:783-785` 只有 Marine/Marauder |
| `abilities.py:119` | Stimpack 持续 336 loops (15s) | SC2 实际 ~15.6s ≈ 350 loops |
| `m7_units.py` Mutalisk | 无弹跳伤害 | SC2 实际 9→3→1 三段弹跳 |
| `m7_units.py` Baneling | UnitType minerals=50, MorphRule minerals=25 | python-sc2 `game_data.py:59` 校正为 25 |
| `combat.py:_is_air` | 仅看 `unit_type.is_air` | Sharky `DamageService.cs:13` 巨像/引力束双判定 |

## 2. 修复方案

### 2.1 SIM-CAL-001 伤害公式修正（combat.py）

**文件 1：`systems/combat.py`**

`_compute_damage_breakdown` 修正：
- bonus_damage：从累加改为 `max(boni)`（取最大匹配属性的加成，不叠加）
- 最小伤害：保持 `max(1, ...)` 作为单次攻击最小值（sc2_simulator 用 Fixed/SCALE，
  0.5 点 = 512 raw，与 python-sc2 的 0.5 一致；但当前 `Fixed.from_int(1)` = 1024 raw = 1 点，
  偏高。改为 `Fixed.from_float(0.5)` = 512 raw）
- armor_add 射程条件：Guardian Shield 类行为（armor_add > 0）仅对 `weapon.range >= 2` 生效

### 2.2 SIM-CAL-002 武器周期校准（m7_units.py + model.py）

**文件 2：`catalog/m7_units.py` + `catalog/model.py`**

按 python-sc2 `weapon.speed × 22.4` 换算校准 period（四舍五入）：
- Marauder: 75 → 34
- Zergling: 22 → 16
- Marine: 22 → 19
- Viking: 75 → 67
- Mutalisk: 22 → 24
- 其他单位逐一核对（Hellion 43→37, Medivac heal 22→22, Roach 90→90, 等）

### 2.3 SIM-CAL-003 单位/行为定义修正

**文件 3：`systems/abilities.py`**
- `casters_by_ability["Stimpack"]`：移除 "Reaper"，只保留 ("Marine", "Marauder")
- Stimpack 行为持续时间：336 → 350

**文件 4：`catalog/model.py`**
- `WeaponType` 新增 `bounce_damage: tuple[int, ...] = ()` 字段（弹跳伤害序列）
- Mutalisk weapon_ground 添加 `bounce_damage=(3, 1)`（9→3→1 三段）

**文件 5：`catalog/m7_units.py`**
- Mutalisk weapon_ground 添加 bounce_damage
- Baneling UnitType minerals: 50 → 25（与 MorphRule 一致）

**文件 6：`systems/combat.py`**
- `_is_air` 增加巨像双判定：`unit_type.is_air or Attribute.MASSIVE in unit_type.attributes`
  （Colossus 有 MASSIVE 属性，可被对空武器攻击；SC2 实际规则更细，但 MASSIVE 近似足够）
- `_weapon_for_target`：目标为 MASSIVE 空中近似时，weapon_air 也可选中

### 2.4 vibe 适配层同步更新

**文件 7：`vibe/gate_verification.py`**
- 新增 G7-calibration 闸门：验证 Marauder period 修正后伤害输出更频繁
- 新增 G7-bounce 闸门：验证 Mutalisk 弹跳伤害命中次要目标
- 新增 G7-colossus-air 闸门：验证 Colossus 可被对空武器攻击

## 3. 闸门

| 闸门 | 验证内容 | 证据类型 |
|---|---|---|
| G7-formula-min-dmg | 0.5 最小伤害规则生效（高护甲目标伤害不低于 0.5/发） | runtime |
| G7-formula-bonus-max | bonus damage 取 max 而非累加 | runtime |
| G7-marauder-period | Marauder period 34 后 100 loop 内开火 ≥2 次（修正前 75 只能 1 次） | runtime |
| G7-reaper-no-stim | Reaper 无法施放 Stimpack | runtime |
| G7-mutalisk-bounce | Mutalisk 攻击密集阵型时次要目标受到弹跳伤害 | runtime |
| G7-colossus-air | Colossus（MASSIVE）可被 Viking weapon_air 攻击 | runtime |
| P1-P9 回归 | 12/12 PASS（不破坏既有消费者） | runtime |

## 4. writeScope

```
src/projects/cmre-porting/stages/07-sim-value-calibration/**
src/projects/cmre-porting/vibe/**
tools/sc2-ally-bot/src/sc2_simulator/catalog/model.py
tools/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py
tools/sc2-ally-bot/src/sc2_simulator/systems/combat.py
tools/sc2-ally-bot/src/sc2_simulator/systems/abilities.py
```

## 5. 非目标

- 不引入 python-sc2 依赖（仅用其公式作为参照，手写到 sc2_simulator）
- 不从 pickle 文件批量提取数值（留待后续 stage，本阶段只校准已发现的偏差）
- 不实现升级 effects 速度/射程/攻速加成（留待后续 stage）
- 不实现 Guardian Shield 技能本身（只修正 armor_add 的射程条件）
- 不修改 entity.py / movement.py（stage 06 已修复）

## 6. 证据分类

- `static`：python-sc2 `unit.py:603-809` 伤害公式、`constants.py` 乘数表、Sharky `DamageService.cs:13-20`
- `runtime`：G7 闸门验证 + P1-P9 回归

## 7. Completion Gate

1. SIM-CAL-001/002/003 全部 resolved-fixed
2. G7 闸门全 PASS
3. P1-P9 回归 12/12 PASS
4. `result.json`/`issues.json`/`log.md` 完整，每项结论带证据分类与路径
