# Stage Log: sc2_simulator 能力补全（SIM-CAP-GAP-002 + 003）

## Progress

Stage opened after `05-vibe-framework` closed with `status: PASS` (12/12 回归 PASS,
third pass closed M10 + position-unit bug). 本阶段在模拟器引擎层关闭两个 open issue：
SIM-CAP-GAP-002（空战未接线）和 SIM-CAP-GAP-003（行为乘数未接线）。

### Stage opened (2026-07-30)

- 静态发现完成：读取 combat.py / movement.py / abilities.py / model.py / entity.py / m7_units.py，
  确认缺口位置和修复范围（见 plan.md §1）。
- writeScope 扩展：project.json 新增 4 个 sc2_simulator 文件（model.py / m7_units.py /
  combat.py / movement.py）；abilities.py 和 entity.py 不需修改（已有 weapon_air_cd 和
  multiplier getters）。
- plan.md 创建：包含缺口分析、修复方案、闸门、writeScope、证据分类、非目标、Completion Gate。

### SIM-CAP-GAP-002 修复实施 (2026-07-30)

- `catalog/model.py`：UnitType 添加 `is_air: bool = False` 字段；Medivac 标记 `is_air=True`（self-review 修复）
- `catalog/m7_units.py`：标记 15 个空中单位 `is_air=True`（Terran: Viking/Banshee/Raven/Battlecruiser；
  Protoss: Observer/WarpPrism/Phoenix/VoidRay/Carrier/Tempest/Oracle；
  Zerg: Mutalisk/Corruptor/BroodLord/Viper）
- **遗留**：Overlord 定义在 m3_units.py 中（不在 writeScope 内），未标记 `is_air=True`，
  记录为 SIM-CAP-GAP-006 open issue
- `systems/combat.py`：
  - `_is_air(unit_type)` → `return unit_type.is_air`
  - `_weapon_for_target(attacker_type, target_type)` → 返回 `(weapon, use_air_cd)`，
    根据目标是否空中选 weapon_air/weapon_ground，含跨类型武器 fallback
  - `_try_fire` → 接收 `attacker_type` 和 `use_air_cd`，根据 use_air_cd 选择 `weapon_air_cd`/`weapon_ground_cd`

### SIM-CAP-GAP-003 修复实施 (2026-07-30)

- `systems/movement.py`：`step()` 中调用 `abilities.get_speed_multiplier(e)` 调整速度：
  `effective_speed = Fixed(ut.speed.raw * speed_mult // 100)`
- `systems/combat.py`：
  - `_try_fire` 中调用 `abilities.get_attack_speed_multiplier(attacker)` 调整冷却周期：
    `effective_period = weapon.period * 100 // atk_mult`
  - `_compute_damage_breakdown(weapon, target_type, attacker, target)` → 新增 attacker/target Entity 参数，
    应用 `damage_add`（attacker 行为）和 `armor_add`（target 行为）到伤害公式
  - damage 事件 payload 新增 `damage_add_raw`/`armor_add_raw`/`effective_armor_raw` 字段

### vibe 适配层同步更新 (2026-07-30)

- `vibe/contracts.py`：`_unit_fidelity` 移除 weapon_air → unsupported 判断；
  所有单位标 approximate（手写 IR，非 XML 导入）
- `vibe/catalog_bridge.py`：`validate_strict` 更新注释；`p2_selftest` 中
  `unsupported_unit_present` → `viking_fidelity_upgraded`（验证 Viking 从 unsupported 升级为 approximate）；
  strict 逻辑用手动注入 unsupported handle 测试
- `vibe/gate_verification.py`：`p3_selftest` 中
  `G5_air_unsupported_known` → `G5_air_combat_wired`（检查 0 damage → damage > 0）；
  新增 `_g6_behavior_multiplier_test` 验证 G6-speed-mult/G6-atkspd-mult/G6-armor-add/G6-damage-add
- `vibe/consumers/mod_dev.py`：`p4a_selftest` 中
  `unsupported_visible` → `no_unsupported_after_stage06`（反转检查逻辑）

### 回归验证 (2026-07-30T08:55:03Z)

- P1-P9 回归 12/12 PASS（regression-20260730T085503Z.json）
- G5-air-wired PASS：Viking vs Viking damage_events=6
- G6-speed-mult PASS：baseline_dist=5.078 stim_dist=7.666
- G6-atkspd-mult PASS：baseline_fires=5 stim_fires=8
- G6-armor-add PASS：no_armor_dmg=5120 with_armor_dmg=3072
- G6-damage-add PASS：no_buff_dmg=5120 with_buff_dmg=8192

## Evidence

### static 证据

- `tools/sc2-ally-bot/src/sc2_simulator/catalog/model.py:155`（UnitType.is_air 字段）
- `tools/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py`（15 个空中单位标记 is_air=True）
- `tools/sc2-ally-bot/src/sc2_simulator/systems/combat.py:34-60`（_weapon_for_target + _is_air）
- `tools/sc2-ally-bot/src/sc2_simulator/systems/combat.py:109-148`（_compute_damage_breakdown 行为加成）
- `tools/sc2-ally-bot/src/sc2_simulator/systems/combat.py:329-335`（_try_fire 攻击速度乘数）
- `tools/sc2-ally-bot/src/sc2_simulator/systems/movement.py:139-144`（step 速度乘数）
- `src/projects/cmre-porting/vibe/contracts.py:56-67`（_unit_fidelity 修复后无 unsupported）
- `src/projects/cmre-porting/vibe/gate_verification.py:107-149`（G5_air_combat_wired）
- `src/projects/cmre-porting/vibe/gate_verification.py:190-418`（_g6_behavior_multiplier_test）

### runtime 证据

- `artifacts/galaxy-vibe/p1-p9-regression/regression-20260730T085503Z.json`（12/12 PASS）
- G5_air_combat_wired: `static_weapon_air=yes static_is_air=yes damage_events=6 end_health=[('Viking', 67584), ('Viking', 67584)]`
- G6_speed_mult: `baseline_dist=5.078 stim_dist=7.666 stim_further=True (speed_multiplier=150)`
- G6_atkspd_mult: `baseline_fires=5 stim_fires=8 stim_fires_more=True (attack_speed_multiplier=150)`
- G6_armor_add: `no_armor_dmg=5120 with_armor_dmg=3072 armor_reduced_dmg=True (armor_add=2)`
- G6_damage_add: `no_buff_dmg=5120 with_buff_dmg=8192 buff_increased_dmg=True (damage_add=3)`

## Changed paths

### sc2_simulator 引擎层（writeScope 扩展）

- `tools/sc2-ally-bot/src/sc2_simulator/catalog/model.py`
- `tools/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py`
- `tools/sc2-ally-bot/src/sc2_simulator/systems/combat.py`
- `tools/sc2-ally-bot/src/sc2_simulator/systems/movement.py`

### vibe 适配层

- `src/projects/cmre-porting/vibe/contracts.py`
- `src/projects/cmre-porting/vibe/catalog_bridge.py`
- `src/projects/cmre-porting/vibe/gate_verification.py`
- `src/projects/cmre-porting/vibe/consumers/mod_dev.py`

### stage 文件

- `src/projects/cmre-porting/stages/06-sim-cap-completion/plan.md`
- `src/projects/cmre-porting/stages/06-sim-cap-completion/result.json`
- `src/projects/cmre-porting/stages/06-sim-cap-completion/issues.json`
- `src/projects/cmre-porting/stages/06-sim-cap-completion/log.md`

## Problems

- SIM-CAP-GAP-002（resolved-fixed）：空战未接线，已在引擎层修复
- SIM-CAP-GAP-003（resolved-fixed）：行为乘数未接线，已在引擎层修复
- SIM-CAP-GAP-006（open，self-review 发现）：Overlord 定义在 m3_units.py 中，不在 stage 06 writeScope 内，
  未标记 `is_air=True`。影响：Overlord 会被地面武器攻击。待后续 stage 扩展 writeScope 修复。
- SIM-CAP-GAP-007（open，self-review 发现）：splash 伤害使用主目标 breakdown（含主目标 armor_add），
  对次要目标不重新计算护甲加成。M1 既有设计近似，stage 06 添加行为加成后更显著。
  影响场景较少（splash + 行为加成交叠），不阻塞 stage 06 完成。

## Completion Gate

1. ✅ SIM-CAP-GAP-002 状态从 `open` 改为 `resolved-fixed`（引擎层修复）
2. ✅ SIM-CAP-GAP-003 状态从 `open` 改为 `resolved-fixed`
3. ✅ G5-air-wired / G6-speed-mult / G6-atkspd-mult / G6-armor-add / G6-damage-add 闸门 PASS
4. ✅ P1-P9 回归 12/12 PASS（不破坏既有消费者）
5. ✅ catalog_bridge 保真度标签正确反映修复（Viking unsupported → approximate）
6. ✅ `result.json`/`issues.json`/`log.md` 完整，每项结论带证据分类与路径
7. ✅ 失败可从 task+源哈希+Catalog 哈希+snapshot+trace+seed 复现
8. ✅ self-review 发现已记录：SIM-CAP-GAP-006（Overlord is_air 遗留）+ SIM-CAP-GAP-007（splash 近似）作为 open issue 留待后续 stage
