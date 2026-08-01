# Stage Plan: sc2_simulator 语义缺口收口

> 开启时间：2026-07-31T20:55:00+08:00  
> 范围：关闭 Stage 07 遗留的两个非阻塞模拟器语义缺口，不触碰真实 SC2 / Bank / Galaxy 传输通道。

## 1. 背景

Stage 07 完成数值校准后仍保留两个后续项：

| Issue | 当前问题 | 根因文件 |
|---|---|---|
| SIM-CAP-GAP-006 | m3_catalog() 中 Overlord 仍由 m7 组装层补飞行属性 | catalog/m3_units.py + catalog/m7_units.py |
| SIM-CAP-GAP-007 | 常规 splash 对次目标复用主目标 damage breakdown | systems/combat.py + systems/projectile.py |

## 2. 修复方案

1. 将 Overlord 的飞行属性下沉到 catalog/m3_units.py 源定义：
   - is_flying=True
   - movement_type=MovementType.FLYING
   - 补齐 Armored / Massive 属性
   - 从 m7_catalog() 的 flying_unit_ids 组装补丁中移除 Overlord
2. 将 splash 伤害改为逐目标结算：
   - combat._compute_splash_damage_breakdown(...) 统一按次目标重算 armor / attributes / behaviors
   - instant splash 使用该 helper
   - projectile splash 通过 weapon_id 找回 WeaponType 后按次目标重算
   - damage payload 增加 splash_target_recalc 以便追踪 fidelity
3. 增加 targeted regression：
   - m3 Overlord source catalog 飞行属性测试
   - Hellion splash 主目标 Light / 次目标 Armored 混编测试，锁定 final damage = 7

## 3. Write Scope

```
src/projects/cmre-porting/stages/09-sim-semantic-completion/**
src/projects/cmre-porting/stages/07-sim-value-calibration/issues.json
src/projects/cmre-porting/project.json
reference/sc2-ally-bot/src/sc2_simulator/catalog/m3_units.py
reference/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py
reference/sc2-ally-bot/src/sc2_simulator/systems/combat.py
reference/sc2-ally-bot/src/sc2_simulator/systems/projectile.py
reference/sc2-ally-bot/tests/sc2_simulator/test_m1_combat.py
reference/sc2-ally-bot/tests/sc2_simulator/test_m3_races.py
```

## 4. Completion Gate

1. SIM-CAP-GAP-006 和 SIM-CAP-GAP-007 标记 resolved-fixed
2. Targeted tests PASS
3. M1/M3 file-level regression PASS
4. Full tests/sc2_simulator regression PASS
5. Stage 09 result.json / issues.json / log.md 完整记录 static/runtime 证据
