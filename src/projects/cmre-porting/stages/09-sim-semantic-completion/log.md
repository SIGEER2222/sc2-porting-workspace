# Stage 09 Log: sc2_simulator 语义缺口收口

> 开启时间：2026-07-31T20:55:00+08:00  
> 关闭时间：2026-07-31T20:55:00+08:00  
> 状态：PASS

## 1. 执行摘要

本阶段关闭 Stage 07 留下的两个非阻塞模拟器语义缺口：

- SIM-CAP-GAP-006：Overlord 飞行属性从 m7 组装层补丁下沉到 m3 源 Catalog。
- SIM-CAP-GAP-007：常规 splash 对次目标按自身 armor / attributes / behaviors 重算 damage breakdown。

没有修改真实 SC2 / Bank / MapCommand / Galaxy 传输通道。

## 2. Static 证据

- reference/sc2-ally-bot/src/sc2_simulator/catalog/m3_units.py
  - OVERLORD 设置 is_flying=True
  - movement_type=MovementType.FLYING
  - attributes 补齐 ARMORED / MASSIVE / BIOLOGICAL / PSIONIC
- reference/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py
  - flying_unit_ids 移除 Overlord，避免 m7 组装层继续承担源定义职责
  - 保留已启用的 Mutalisk bounce_damage=(3, 1) 校准改动
- reference/sc2-ally-bot/src/sc2_simulator/systems/combat.py
  - 新增 _compute_splash_damage_breakdown(...)
  - instant splash 改为调用 target-specific breakdown
  - damage payload 增加 splash_target_recalc
- reference/sc2-ally-bot/src/sc2_simulator/systems/projectile.py
  - projectile splash 通过 weapon_id 找回 WeaponType
  - _resolve_splash / _resolve_splash_at_position 改为 target-specific breakdown
  - 保留旧 snapshot / incomplete Catalog fallback，并标记 fallback_launch_breakdown

## 3. Runtime 证据

| 验证 | 命令 | 结果 |
|---|---|---|
| targeted tests | PYTHONPATH=src python -m pytest tests/sc2_simulator/test_m1_combat.py::TestSplash::test_splash_recomputes_damage_for_secondary_target_armor tests/sc2_simulator/test_m3_races.py::TestZergSupply::test_overlord_is_flying_in_source_catalog -q | 2 passed |
| M1/M3 回归 | PYTHONPATH=src python -m pytest tests/sc2_simulator/test_m1_combat.py tests/sc2_simulator/test_m3_races.py -q | PASS |
| 全量模拟器回归 | PYTHONPATH=src python -m pytest tests/sc2_simulator -q | 448 passed |
| 收集数 | PYTHONPATH=src python -m pytest tests/sc2_simulator --collect-only -q -o addopts= | 448 tests collected |
| Catalog probe | inline Python | m3=True/FLYING; m7=True/FLYING |
| Splash probe | inline Python | bonus_raw=0; armor_raw=1024; final_raw=7168; splash_target_recalc=target_specific |

## 4. 改动文件

- src/projects/cmre-porting/project.json
- src/projects/cmre-porting/stages/07-sim-value-calibration/issues.json
- src/projects/cmre-porting/stages/09-sim-semantic-completion/plan.md
- src/projects/cmre-porting/stages/09-sim-semantic-completion/issues.json
- src/projects/cmre-porting/stages/09-sim-semantic-completion/result.json
- src/projects/cmre-porting/stages/09-sim-semantic-completion/log.md
- reference/sc2-ally-bot/src/sc2_simulator/catalog/m3_units.py
- reference/sc2-ally-bot/src/sc2_simulator/catalog/m7_units.py
- reference/sc2-ally-bot/src/sc2_simulator/systems/combat.py
- reference/sc2-ally-bot/src/sc2_simulator/systems/projectile.py
- reference/sc2-ally-bot/tests/sc2_simulator/test_m1_combat.py
- reference/sc2-ally-bot/tests/sc2_simulator/test_m3_races.py

## 5. 结论

Stage 09 PASS。两个 Stage 07 residual semantic gaps 均已关闭，sc2_simulator 全量回归通过（448/448）。

## 6. 收尾交接

- handoff.md 已补充当前方案、已完成进度、真正剩余项、历史账本待整理项、推荐下一阶段和工作区拆分建议。
- Stage 09 不改写 Stage 05 / Stage 06 / Stage 08 的历史账本文件；这些文件不在当前 writeScope，后续应通过独立 hardening / reconciliation stage 处理。
