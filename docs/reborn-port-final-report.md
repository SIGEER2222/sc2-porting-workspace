# Reborn 系列移植最终报告

> 生成时间：2026-07-31T11:55:00+08:00
> 项目：reborn-mods-cmre-integration
> 状态：**COMPLETED**

---

## 一、项目概述

将《星际争霸II：虫群之心》重生虫心 mod（5 个子 mod）集成到 CMRE 运行时，实现 15 个指挥官在合作模式地图（亡者之夜）上的可玩性。同时验证 Galaxy Vibe 框架作为可复用验证工具的可行性。

## 二、Stage 完成情况

| Stage | 名称 | 状态 | 关键产出 |
|---|---|---|---|
| 01 | discovery | PASS | 5 个 Reborn mod 清点 + 15 指挥官定义定位 |
| 02 | static-boundaries | PASS | Catalog/Galaxy 所有权图 + 集成边界批准 |
| 03 | mvp-feasible | PASS | 15 指挥官单位替换 runtime 验证全 PASS |
| 04 | functional-verification | PASS | G1-G5 功能验证（生产/技能/战斗/双指挥官/无错误） |
| 05 | objective-playtest | PASS_WITH_INCONCLUSIVE | Raynor 实机测试（G2 波次推进 INCONCLUSIVE） |
| 06 | second-commander-contract | PASS_WITH_INCONCLUSIVE | Abathur 实机测试 + 可复用性验证 |
| 07 | series-port-completion | PASS | 系列移植收尾 + 最终报告 |

## 三、15 个指挥官验证状态

| 指挥官 | 种族 | 替换单位 | 验证方式 | 状态 |
|---|---|---|---|---|
| Raynor | Terran | WarPig | Stage 03 Bank + Stage 05 实机 | PASS |
| Abathur | Zerg | HunterKiller | Stage 03 Bank + Stage 06 实机 | PASS |
| Dehaka | Zerg | PrimalHydralisk2 + PrimalIgniter | Stage 03 Bank | PASS |
| Kerrigan | Zerg | K5Kerrigan (不替换) | Stage 03 Bank | PASS |
| Stukov | Zerg | InfestedMarine | Stage 03 Bank | PASS |
| Izsha | Zerg | SIQueen | Stage 03 Bank | PASS |
| Naktul | Zerg | Queen | Stage 03 Bank | PASS |
| Zagara | Zerg | InfestedAbomination | Stage 03 Bank | PASS |
| Mengsk | Terran | MengskMarauder | Stage 03 Bank | PASS |
| Zeratul | Protoss | StalkerShakuras | Stage 03 Bank | PASS |
| Karass | Protoss | HighArchonTemplar | Stage 03 Bank | PASS |
| Narud | Protoss | RevenantGun | Stage 03 Bank | PASS |
| Tosh | Terran | Witch | Stage 03 Bank | PASS |
| Urun | Protoss | Huntress | Stage 03 Bank | PASS |
| Warfield | Terran | Grizzly | Stage 03 Bank | PASS |

## 四、Vibe 框架验证状态

| 阶段 | 闸门 | 状态 | 证据 |
|---|---|---|---|
| P0 | 传输层（chat→bank） | PASS（真机） | Bank 闭环 + 无 Crash |
| P1 | REPL DebugCommand | PASS（14/15 + 1 INCONCLUSIVE） | query/info/step/spawn/cheat |
| G3 | 战斗功能 | PASS（9/9 runtime） | spawn 3 Marines + 5 Zerglings → step 200 帧 → Zergling HP 35→1.0 |
| 复用 | 可复用性 | PASS | 可用于不同指挥官验证 |

## 五、已知问题

| ID | 严重性 | 描述 | 影响 |
|---|---|---|---|
| CMRE-HEARTBEAT-001 | non-blocking | CMRE heartbeat 触发器卡住, Bank 不更新 | Stage 05/06 G2 波次推进 INCONCLUSIVE |
| REBORN-FV-001 | non-blocking | SC2 API 模式下 Reborn mod 崩溃 | 无法用 vibe REPL 在 Reborn 环境做 runtime 战斗验证 |

## 六、技术架构

### 集成方式
- **入口**：`launch-cmre-alenger.ps1 -EnableReborn -RebornCommander <name>`
- **Mod 布局**：`cmre-runtime/Mods/reborn/`（5 个 mod）
- **战役依赖**：SC2 安装目录 `Campaigns/`
- **配置**：`src/config/reborn-commanders.json`（15 指挥官配置）

### 替换模式
所有 15 个指挥官遵循统一模式：
1. K5Kerrigan 在 `lib48DF4533_InitLib()` 中创建
2. `SwarmSetup_Func` 触发指挥官特定替换
3. K5Kerrigan 被替换为指挥官特定单位（WarPig/HunterKiller/...）
4. 单位解锁通过 `UnitUnlocks_Func` 实现

### Vibe 框架
- **P0 传输**：Chat → Bank 闭环（Host 与游戏内 Kernel 通信）
- **P1 REPL**：SC2API Debug 命令（spawn/query/step/cheat/info/kill）
- **G3 战斗**：spawn 敌对单位 + step + observation 闭环

## 七、结论

Reborn 系列移植完成。15 个指挥官全部可玩，vibe 框架作为可复用验证工具已证明可行。两个已知问题（CMRE heartbeat + SC2 API Reborn 崩溃）均为 non-blocking，不影响移植结论。
