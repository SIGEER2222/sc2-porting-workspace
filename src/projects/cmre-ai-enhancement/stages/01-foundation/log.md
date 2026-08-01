# Stage 01 Log: Foundation — AresSC2 集成与架构对齐

> 开启时间：2026-08-01T00:00:00+08:00
> 状态：IN_PROGRESS

## 1. 背景

cmre-porting 项目已关闭（Stage 08 PASS）。DefendBasePolicy 在亡者之夜实现了 3500 loop 存活（victory，14 单位存活），但存在根本缺陷：
- 零扩基地（全程 1 基地）
- 零主动进攻（纯死守）
- 矿物长期卡 50（reserve 池阻塞 SCV 训练）
- 无 SiegeTank siege/unsiege、无焦火、无风筝微操

本阶段目标：引入 AresSC2 框架，用 MacroPlan + CombatManeuver 替换经济与战斗决策核心，保留 vibe 传输层。

## 2. 执行记录

### 2.1 项目创建
- 创建 `src/projects/cmre-ai-enhancement/` 目录结构
- 编写 `project.json`：目标 TerranRaynor + Dead of Night，writeScope 覆盖新项目 + launcher
- 编写 Stage 01 plan.md、issues.json

### 2.2 已完成的静态工作
- `macro_plan.py` 使用真实 Ares `MacroPlan`、`AutoSupply`、`BuildWorkers`、`GasBuildingController`、`ExpansionController`、`SpawnController`、`ProductionController` 构造器。
- `combat_maneuver.py` 使用真实 Ares `CombatManeuver`、`KeepUnitSafe`、`ShootTargetInRange`、`SiegeTankDecision`、`AMove` 构造器。
- `ares_bot.py` 提供继承 `AresBot` 的原生生命周期入口；不再尝试在 raw WebSocket runner 中伪造 Ares 状态。
- `config.yml` 改为 Ares 原生配置键；`terran_builds.yml` 改为 `BuildOrderRunner` 可解析的 `Builds/OpeningBuildOrder` 格式。
- `python3.11 -m py_compile` 已通过。

### 2.3 当前阻断
- 完整 `from ares import AresBot` 导入需要 Python 3.11 依赖 `cython-extensions-sc2`、`map-analyzer` 等；当前环境缺少这些依赖。
- 尚未通过正式 Ares launcher 启动真机，因此 G1-G4 不得标记 PASS。

## 3. 变更文件清单（进行中）

```
src/projects/cmre-ai-enhancement/project.json
src/projects/cmre-ai-enhancement/stages/01-foundation/plan.md
src/projects/cmre-ai-enhancement/stages/01-foundation/issues.json
src/projects/cmre-ai-enhancement/stages/01-foundation/log.md
src/projects/cmre-ai-enhancement/stages/01-foundation/result.json
src/projects/cmre-ai-enhancement/vibe/__init__.py
src/projects/cmre-ai-enhancement/vibe/macro_plan.py
src/projects/cmre-ai-enhancement/vibe/combat_maneuver.py
src/projects/cmre-ai-enhancement/vibe/unit_roles.py
src/projects/cmre-ai-enhancement/vibe/enhanced_policy.py
src/projects/cmre-ai-enhancement/config.yml
src/projects/cmre-ai-enhancement/builds/terran_macro.yml
reference/ares-sc2 (read-only external dependency)
```
