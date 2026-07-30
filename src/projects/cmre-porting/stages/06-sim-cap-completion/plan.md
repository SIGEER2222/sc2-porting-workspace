# Stage Plan: sc2_simulator 能力补全（SIM-CAP-GAP-002 + 003）

> **背景**：stage 05-vibe-framework 在本地关键路径上 PASS（12/12 回归），但两个 sc2_simulator 能力缺口
> 作为 open issue 保留：SIM-CAP-GAP-002（空战未接线）和 SIM-CAP-GAP-003（行为乘数未接线）。
> 本阶段扩展 writeScope 到 `sc2_simulator` 的精确文件，在模拟器引擎层关闭这两个缺口，
> 并同步更新 vibe 适配层的保真度标签与 G5 闸门。

## 1. 缺口分析（static 证据，已在 stage 05 issues.json 登记）

### SIM-CAP-GAP-002：空战未接线

| 位置 | 问题 |
|---|---|
| `combat.py:41-43` | `_is_air(unit_type)` 硬编码 `return False`，所有单位都被视为地面 |
| `combat.py:34-38` | `_weapon_for_target` 只查 `weapon_ground`，从不查 `weapon_air` |
| `combat.py:299,324` | `_try_fire` 只用 `attacker.weapon_ground_cd`，不用 `weapon_air_cd` |
| `model.py:134-154` | `UnitType` 无 `is_air` 字段（`Attribute` 枚举无 AIR；AIR 在 `TargetFilter`） |
| `m7_units.py` | Viking/Banshee/Phoenix/Mutalisk/Corruptor 已定义 `weapon_air` 但无法开火 |

**已有基础**：
- `entity.py:97` `weapon_air_cd: int = 0` 字段已存在（无需改 Entity）
- `WeaponType` 有 `target_filters` 字段（含 GROUND/AIR）
- m7 catalog 已定义 5 个空中单位的 `weapon_air`

### SIM-CAP-GAP-003：行为乘数未接线

| 位置 | 问题 |
|---|---|
| `abilities.py:361-366` | `get_speed_multiplier(e)` 存在但 `movement.py:137-139` 不调用 |
| `abilities.py:369-374` | `get_attack_speed_multiplier(e)` 存在但 `combat.py:_try_fire` 不调用 |
| `abilities.py:217-220` | `_apply_behavior_to_entity` 存储 `armor_add`/`damage_add` 但 combat.py 不应用 |

**已有基础**：
- `get_speed_multiplier` / `get_attack_speed_multiplier` 纯函数已实现，遍历 `active_behaviors`
- `active_behaviors` dict 已包含 `speed_multiplier`/`attack_speed_multiplier`/`armor_add`/`damage_add` 字段
- Stimpack 行为已定义（`behaviors_by_id` 中有 speed_multiplier 和 attack_speed_multiplier）

## 2. 修复方案

### 2.1 SIM-CAP-GAP-002 空战

**文件 1：`catalog/model.py`**
- `UnitType` 添加 `is_air: bool = False` 字段

**文件 2：`catalog/m7_units.py`**
- 标记 m7_units.py 中所有空中单位 `is_air=True`（Terran: Viking/Banshee/Raven/Battlecruiser；
  Protoss: Observer/WarpPrism/Phoenix/VoidRay/Carrier/Tempest/Oracle；
  Zerg: Mutalisk/Corruptor/BroodLord/Viper）—— 共 15 个
- Medivac 定义在 model.py 中，也在本 stage writeScope 内，同步标记 `is_air=True`
- **遗留**：Overlord 定义在 m3_units.py 中（不在 writeScope 内），未标记 `is_air=True`，
  记录为 SIM-CAP-GAP-006 遗留 issue，待后续 stage 扩展 writeScope 修复
- Liberator/Mothership/Overseer 当前不在 catalog 中，不涉及

**文件 3：`systems/combat.py`**
- `_is_air(unit_type)` → `return unit_type.is_air`
- `_weapon_for_target(attacker_type, target_type)`：
  - 目标空中 → 优先 `weapon_air`；若 None，检查 `weapon_ground.target_filters` 含 AIR 则用 ground
  - 目标地面 → 优先 `weapon_ground`；若 None，检查 `weapon_air.target_filters` 含 GROUND 则用 air
- `_try_fire`：根据使用的武器是 `attacker_type.weapon_air` 还是 `weapon_ground` 选择对应 cd 字段
  （`weapon_air_cd` vs `weapon_ground_cd`）

### 2.2 SIM-CAP-GAP-003 行为乘数

**文件 4：`systems/movement.py`**
- `step()` 中查 `ut.speed` 后，调用 `abilities.get_speed_multiplier(e)` 调整：
  `effective_speed = Fixed(speed.raw * mult // 100)`（mult=150 表示 1.5x）
- 无循环依赖：abilities.py 不导入 movement.py

**文件 3：`systems/combat.py`**（同一文件，多处修改）
- `_try_fire`：调用 `abilities.get_attack_speed_multiplier(attacker)` 调整冷却周期：
  `effective_period = weapon.period * 100 // mult`（mult=150 → 更快攻击 → 更短周期）
- `apply_damage_breakdown`：应用攻击者 `damage_add` 行为加成（增加 final_raw）；
  应用目标 `armor_add` 行为加成（增加 armor 抵扣）
- 需要传入 attacker Entity（当前 `apply_damage_breakdown` 只接收 `attacker_entity_id`，
  需改为也接收 attacker Entity 或从 world 查询）

### 2.3 vibe 适配层同步更新

**文件 5：`vibe/catalog_bridge.py`**
- Viking/Banshee/Phoenix/Mutalisk/Corruptor 等单位的 fidelity label 从 `unsupported`（空战缺口）
  更新为 `approximate`（空战已接线，但仍为手写 IR，非 XML 导入）
- `exact` 留待后续 stage 引入真实 CMRE XML 导入后标注

**文件 6：`vibe/gate_verification.py`**
- G5 air-combat 闸门检查反转：当前 assert "Viking vs Viking → 0 damage events"
  （确认空战无法开火）；修复后改为 assert "Viking vs Viking → damage events > 0"
- `G5_air_unsupported_known` 检查项重命名为 `G5_air_combat_wired`

## 3. 闸门（验证标准）

| 闸门 | 要求 | 证据类 |
|---|---|---|
| G5-air-wired | Viking vs Viking 对空战斗产生 damage events > 0 | runtime |
| G5-ground-stable | 修复不破坏现有地面战斗（Marine vs Zergling end_loop 仍为 132） | runtime |
| G5-weapon-selection | 空中目标用 weapon_air/可对空 weapon_ground；地面目标用 weapon_ground | runtime |
| G6-speed-mult | Stimpack 后单位速度提升 1.5x（移动距离对比） | runtime |
| G6-atkspd-mult | Stimpack 后攻击周期缩短（同样 loop 内开火次数增加） | runtime |
| G6-armor-add | 行为 armor_add 生效（目标有效护甲增加，伤害降低） | runtime |
| G6-damage-add | 行为 damage_add 生效（攻击者伤害增加） | runtime |
| P1-P9-regression | vibe 平台 12/12 回归仍 PASS（不破坏既有消费者） | runtime |
| no-fidelity-regression | catalog_bridge 保真度标签只升级不降级 | static |

## 4. Write Scope（精确，需 project.json 扩展）

**sc2_simulator 文件（writeScope 扩展）**：
- `tools/sc2-ally-bot/src/sc2_simulator/catalog/model.py`
- `tools/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py`
- `tools/sc2-ally-bot/src/sc2_simulator/systems/combat.py`
- `tools/sc2-ally-bot/src/sc2_simulator/systems/movement.py`

**vibe 适配层文件（已有 writeScope）**：
- `src/projects/cmre-porting/vibe/catalog_bridge.py`
- `src/projects/cmre-porting/vibe/gate_verification.py`

**stage 文件**：
- `src/projects/cmre-porting/stages/06-sim-cap-completion/**`

**禁止修改**：
- `tools/sc2-ally-bot/src/sc2_simulator/systems/abilities.py`（multiplier getters 已存在，只需被调用）
- `tools/sc2-ally-bot/src/sc2_simulator/world/entity.py`（weapon_air_cd 已存在）
- `tools/sc2-ally-bot/src/sc2_simulator/**` 中未列出的文件
- 所有只读源和外部仓库

## 5. 证据分类

- `static`：model.py 字段定义、m7_units.py 标记审计、combat.py/movement.py 代码审查
- `runtime`：G5/G6 闸门动态验证（damage events、速度/攻击周期对比）、P1-P9 回归

## 6. 非目标

- 不修改 abilities.py（getter 已存在）
- 不修改 entity.py（weapon_air_cd 已存在）
- 不修改 sc2_simulator 的其他 systems（projectile/economy/construction/production 等）
- 不做真实 SC2 校准（仍为 P9 可选）
- 不做 Catalog XML 导入（未来阶段）
- 不改变 vibe 平台的 typed operation 契约

## 7. Completion Gate

1. SIM-CAP-GAP-002 状态从 `open` 改为 `resolved-fixed`（引擎层修复，非适配层）
2. SIM-CAP-GAP-003 状态从 `open` 改为 `resolved-fixed`
3. G5-air-wired / G6-speed-mult / G6-atkspd-mult / G6-armor-add / G6-damage-add 闸门 PASS
4. P1-P9 回归 12/12 PASS（不破坏既有消费者）
5. catalog_bridge 保真度标签正确反映修复
6. `result.json`/`issues.json`/`log.md` 完整，每项结论带证据分类与路径
7. 失败可从 task+源哈希+Catalog 哈希+snapshot+trace+seed 复现
