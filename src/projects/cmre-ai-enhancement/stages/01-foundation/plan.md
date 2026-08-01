# Stage Plan: Foundation — AresSC2 集成与架构对齐

> **背景**：cmre-porting 项目已关闭，DefendBasePolicy（防守死守型）在亡者之夜 3500 loop 存活但零扩张、零进攻。本阶段引入 AresSC2 框架，建立 MacroPlan + CombatManeuver 架构，替换经济与战斗决策核心，保留 vibe 传输层。

## 1. 目标

| 目标 | 说明 |
|---|---|
| **引用 AresSC2** | 只读引用 `reference/ares-sc2`，不复制外部源码；锁定 upstream revision 与 Python 依赖要求 |
| **架构对齐** | 将 DefendBasePolicy 逻辑映射为：`MacroPlan`（优先级串行）+ `CombatManeuver`（行为组合）+ 自定义 Behavior |
| **基线验证** | 在亡者之夜跑通 3500 loop，输出同等或更好存活指标，且新增：≥3 基地、≥50 人口军队、<20% SCV 损失 |

## 2. 任务分解

### 2.1 Vendor AresSC2 核心模块
| 文件/目录 | 来源 | 说明 |
|---|---|---|
| `reference/ares-sc2` | `AresSC2/ares-sc2` | 只读框架依赖 |
| `reference/ares-sc2-bot-template` | `AresSC2/ares-sc2-bot-template` | 参考原生 `AresBot` 生命周期 |

### 2.2 策略模块重构
**新建文件**：`src/projects/cmre-ai-enhancement/vibe/`

| 文件 | 职责 | 对应 DefendBasePolicy 片段 |
|---|---|---|
| `macro_plan.py` | 定义 `MacroPlan`：AutoSupply → BuildWorkers → GasBuildingController → ExpansionController → SpawnController → ProductionController | `_decide_economy` 全部逻辑 |
| `combat_maneuver.py` | 定义 `DeadOfNightCombatManeuver`：威胁响应、低血撤退、SiegeTank 决策、焦火、风筝 | `decide()` 战斗决策片段 |
| `unit_roles.py` | 单位角色常量（DEFENDING, ATTACKING, HARASSING, MINING, BUILDING 等） | `_gathering_scvs`、producer 追踪 |
| `enhanced_policy.py` | 统一入口：`EnhancedPolicy.decide(obs, loop) -> list[Action]`，内部调用 MacroPlan + CombatManeuver | `DefendBasePolicy.decide()` |

### 2.3 传输层适配
- 不把 raw WebSocket runner 强行包装为 AresBot；先提供原生 `CmreEnhancedBot` 入口，后续再通过 launcher 接入正式 Ares 进程。

### 2.4 配置与 Build Runner
- `config.yml`：种族、bot 名称、game_step、地图路径
- `terran_builds.yml`：Ares `BuildOrderRunner` 可解析的开局序列。

## 3. Gate 验收

| Gate | 验证内容 | 证据类型 |
|---|---|---|
| G0-reference | `reference/ares-sc2` 可导入，`from ares import AresBot` 无报错 | static |
| G1-macro-plan | MacroPlan 执行顺序正确：供给→工人→气→扩基地→造兵→加产建筑 | runtime (sim) |
| G2-combat | CombatManeuver 能处理：基地威胁 attack、低血退、SiegeTank siege/unsiege、焦火 | runtime (sim) |
| G3-live-3500 | 亡者之夜 3500 loop：verdict=victory、bases≥3、army_supply≥50、scv_loss_pct<20% | runtime (live) |
| G4-regression | P0/P1 REPL、vibe gate G1-G8 全 PASS | runtime |

## 4. writeScope

```
src/projects/cmre-ai-enhancement/stages/01-foundation/**
src/projects/cmre-ai-enhancement/vibe/**
src/projects/cmre-ai-enhancement/config.yml
src/projects/cmre-ai-enhancement/terran_builds.yml
```

## 5. 非目标

- 不实现多线作战/骚扰/空投（留 Stage 02+）
- 不引入 LLM 决策树生成（留后续阶段）
- 不修改 SC2 协议层、vibe kernel、Galaxy 脚本
- 不做全指挥官适配（仅 TerranRaynor + Dead of Night）

## 6. 证据分类

- `static`：导入测试、代码结构、配置文件语法
- `runtime`：simulator 场景、live 真机回放、vibe gate

## 7. Completion Gate

1. G0-G4 全部 PASS
2. `result.json`/`issues.json`/`log.md` 完整
3. `project.json` 更新 `currentStage: "02-expansion-combat"`
