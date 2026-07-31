# Vibe 诊断报告 — marine-baseline

- 地图: `e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\artifacts\live-maps\亡者之夜_live_packed.SC2Map`
- 时间: 2026-07-31T13:58:33+08:00
- 总计: 3  PASS: 0  FAIL: 0  ERROR: 3

| check | status | actual | expected | notes |
|---|---|---|---|---|
| marine_base_armor | ERROR | {} | {"armor": "== 0"} | unit.spawn 失败: INTERNAL_ERROR |
| marine_with_shield_wall | ERROR | {} | {"armor": "== 3", "tech_tree_unlocked": true} | upgrade.set_level 失败: INTERNAL_ERROR |
| marine_nonexistent_upgrade | ERROR | {} | {"tech_tree_unlocked": false} | upgrade.set_level 失败: INTERNAL_ERROR |
