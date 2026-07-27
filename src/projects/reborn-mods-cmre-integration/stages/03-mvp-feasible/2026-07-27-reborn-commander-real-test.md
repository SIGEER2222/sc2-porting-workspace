# Reborn 指挥官真实功能测试（Abathur 失败 + 架构冲突根因）

## 日期
2026-07-27

## 背景
之前声称"重生虫心移植达到疯批帝国同等完成度"是夸大的。实际只测试了 5 mod 加载链路，从未测试 Reborn 16 个指挥官的功能。本次进行真实功能测试。

## 测试环境
- **地图**: 亡者之夜.SC2Map
- **CMRE 侧指挥官**: TerranAlenger3 (Empire)
- **Reborn 侧指挥官**: Abathur（通过 `-RebornCommander Abathur` 预写 cryswarmcoop.SC2Bank）
- **启动参数**: `-PlayerMode -SkipCountdown -EnableReborn -RebornCommander Abathur -RebornDifficulty 3 -RebornSpeed 3`
- **加载时间**: 57.6s
- **Alerts.txt**: 27748 bytes
- **ScriptError**: 无
- **游戏运行**: 473 秒

## 真实测试结果：Abathur 失败

### 银行 IPC 单位清单（player_N_inventory）

证据文件：[NeuroIntegration.SC2Bank.20260727-abathur-fail](./evidence/NeuroIntegration.SC2Bank.20260727-abathur-fail)

| 玩家 | 单位列表 | Abathur 特有单位 |
|------|---------|----------------|
| P1 | `3diguolaogong=12; 3diguoqianshaojidi=1; ACHeroSpawnPlacement=1` | **无** |
| P2 | `3diguolaogong=12; 3diguoqianshaojidi=1; ACHeroSpawnPlacement=1` | **无** |

P1 和 P2 完全相同，都是 Empire Alenger3 的建筑（帝国前哨基地）和工人（帝国老工兵 x12），**没有任何 Abathur 特有单位**。

`worker_before=24` 是 12+12 个 Empire 工人，不是 Reborn 的单位。

## 根本原因：架构冲突

### 1. 前置条件冲突

信源：[Lib48DF4533.galaxy#L10994](file:///e:/Code/MyMod/SC2VibeTools/cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/Lib48DF4533.galaxy#L10994)

```galaxy
bool lib48DF4533_gt_Abathur_Func (bool testConds, bool runActions) {
    ...
    if ((TechTreeUpgradeCount(autoCAD46FB3_var, "Abathur", c_techCountCompleteOnly) == 1)) {
        // 启用 Abathur 特有能力 + 给 Zergling 添加能力
    }
}
```

gt_Abathur_Func 只在玩家已研究 "Abathur" 升级时执行。但 CMRE/Empire 体系不设置这个升级，所以条件不满足，gt_Abathur 不会执行。

### 2. 单位体系冲突

gt_Abathur_Func 期望玩家有 Zergling/Pygalisk/HotSRaptor/HotSSwarmling/ZerglingToxic（L11017-11021）和 Overlord/Overseer（L11033-11034），它给这些单位添加 Abathur 特有能力。

但 CMRE/Empire 体系给玩家的是帝国单位（3diguolaogong=帝国老工兵, 3diguoqianshaojidi=帝国前哨基地），**没有 Zergling/Overlord 等虫族基础单位**。

### 3. SwarmSetup 触发但无效

信源：[Lib48DF4533.galaxy#L4705-L4710](file:///e:/Code/MyMod/SC2VibeTools/cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/Lib48DF4533.galaxy#L4705-L4710)

```galaxy
// CMRE 移植补丁：原版重生虫心 mod 中 gt_SwarmSetup 没有被任何事件触发，
// 必须在此显式调用才能执行 15 个指挥官的初始化流程
TriggerExecute(lib48DF4533_gt_SwarmSetup, false, false);
```

SwarmSetup 被显式触发，并执行了所有 16 个指挥官的子触发器（gt_Abathur/gt_Kerrigan/gt_Zagara 等）。但每个子触发器都有前置条件（如 TechTreeUpgradeCount），这些条件在 CMRE 环境下不满足，所以实际没有执行任何指挥官特有逻辑。

### 4. CommanderStart 读取银行但不设置升级

信源：[Lib48DF4533.galaxy#L4964-L4966](file:///e:/Code/MyMod/SC2VibeTools/cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/Lib48DF4533.galaxy#L4964-L4966)

```galaxy
BankLoad("cryswarmcoop", auto4B26A745_var);
if (((libSwaC_gf_CurrentMap() != "ZZerus3") && (libSwaC_gf_CurrentMap() != "ZSpace2"))) {
    if ((BankValueGetAsString(BankLastCreated(), "Commanders", "Commander") == "Random")) {
        // 随机选择一个指挥官并写入银行
    }
}
```

CommanderStart 从 cryswarmcoop 银行读取 Commander 值（如 "Abathur"），但**只处理 Random 情况**（随机选择一个写入银行）。对于明确指定的 Commander（如 Abathur），它不做任何操作。

而且 CommanderStart **不设置对应的升级**（如 "Abathur" 升级），所以后续的 gt_Abathur_Func 的前置条件不满足。

## 影响范围：5 个代表性指挥官真实测试全部失败

为验证根因分析，实际启动了 5 个代表性 Reborn 指挥官的测试（覆盖 Zerg 系/非 Zerg 系/人族系），全部失败，证据如下：

| # | 指挥官 | 加载时间 | ScriptError | P1 单位列表 | Reborn 特有单位 | 证据文件 |
|---|--------|---------|-------------|------------|----------------|---------|
| 1 | Abathur (Zerg) | 57.6s | 无 | 3diguolaogong=12; 3diguoqianshaojidi=1; ACHeroSpawnPlacement=1 | **无** | [NeuroIntegration.SC2Bank.20260727-abathur-fail](./evidence/NeuroIntegration.SC2Bank.20260727-abathur-fail) |
| 2 | Kerrigan (Zerg) | 57.7s | 无 | 3diguolaogong=12; 3diguoqianshaojidi=1; ACHeroSpawnPlacement=1 | **无** | [NeuroIntegration.SC2Bank.20260727-kerrigan](./evidence/NeuroIntegration.SC2Bank.20260727-kerrigan) |
| 3 | Zagara (Zerg) | 57.6s | 无 | 3diguolaogong=12; 3diguoqianshaojidi=1; ACHeroSpawnPlacement=1 | **无** | [NeuroIntegration.SC2Bank.20260727-zagara](./evidence/NeuroIntegration.SC2Bank.20260727-zagara) |
| 4 | Dehaka (PrimalZerg) | 57.6s | 无 | 3diguolaogong=12; 3diguoqianshaojidi=1; ACHeroSpawnPlacement=1 | **无** | [NeuroIntegration.SC2Bank.20260727-dehaka](./evidence/NeuroIntegration.SC2Bank.20260727-dehaka) |
| 5 | Raynor (Terran) | 57.6s | 无 | 3diguolaogong=12; 3diguoqianshaojidi=1; ACHeroSpawnPlacement=1 | **无** | [NeuroIntegration.SC2Bank.20260727-raynor](./evidence/NeuroIntegration.SC2Bank.20260727-raynor) |

**关键观察**：
1. 5 个指挥官的 P1 单位列表**完全相同**，都是 Empire Alenger3 的建筑和工人
2. 5 个测试的银行大小都是 5532 字节（无变化）
3. P1 和 P2 单位列表完全相同（都是 Empire 单位）
4. 5 个指挥官覆盖了 Zerg/PrimalZerg/Terran 三种不同体系，全部失败
5. 无 ScriptError 表明 galaxy 代码无崩溃，但前置条件不满足导致 gt_<Commander>_Func 静默跳过

这证实了架构冲突根因分析的正确性：所有 16 个 Reborn 指挥官都会遇到相同问题（gt_<Commander>_Func 的 TechTreeUpgradeCount 前置条件不满足 + 期望虫族基础单位但 CMRE 给的是帝国单位）。

## 测试覆盖范围说明

Reborn 共 16 个指挥官（Abathur/Dehaka/Izsha/Karass/Kerrigan/Mengsk/Naktul/Narud/Raynor/Stukov/Tosh/Urun/Warfield/Zagara/Zeratul/Random）。

本次真实测试了 5 个代表性指挥官（Abathur/Kerrigan/Zagara/Dehaka/Raynor），覆盖：
- Zerg 系主力（Abathur/Kerrigan/Zagara）
- 非 Zerg 系（Dehaka，PrimalZerg）
- 人族系（Raynor）

剩余 11 个指挥官（Izsha/Karass/Mengsk/Naktul/Narud/Stukov/Tosh/Urun/Warfield/Zeratul/Random）未单独测试，但由于：
1. 5 个测试的银行单位列表完全相同
2. 所有指挥官的 gt_<Commander>_Func 都用相同的 TechTreeUpgradeCount 模式
3. 所有指挥官都期望虫族基础单位

因此剩余 11 个指挥官预期都会遇到相同的架构冲突。如需进一步验证，可单独测试。

## 修复方案（待实施）

要让 Reborn 指挥官功能正常工作，需要以下改动之一：

### 方案 A：在 CommanderStart 中设置对应升级（最小改动）
在 CommanderStart_Func 读取银行 Commander 值后，根据值设置对应的升级：
```galaxy
string lv_cmd = BankValueGetAsString(BankLastCreated(), "Commanders", "Commander");
if (lv_cmd == "Abathur") {
    TechTreeUpgradeAddLevel(auto4B26A745_var, "Abathur", 1);
}
// ... 其他 15 个指挥官
```

但这只解决前置条件问题，不解决单位体系冲突（玩家没有 Zergling）。

### 方案 B：让 Reborn 完全接管 P1 的单位生成（中等改动）
1. launcher 不为 P1 创建 Empire 起始单位
2. Reborn 的 SwarmSetup 为 P1 创建虫族基础单位（Hatchery/Drone/Overlord/Zergling）
3. 然后各指挥官的 gt_<Commander>_Func 替换为基础单位为指挥官特有单位

### 方案 C：使用 Reborn 的地图选择 UI（大改动）
用 `-ShowSelectionUI` 让 Reborn 显示自己的指挥官选择界面，完全走 Reborn 的原生流程。但这与 CMRE 的 launcher 流程冲突。

## 真实完成度对照（修正）

| 指标 | 疯批帝国 | 重生虫心（真实状态） | 达标 |
|------|---------|----------------|------|
| Mod 加载链路 | ✅ | ✅ 5 mod 加载，无 ScriptError | ✅ |
| Reborn 指挥官功能 | N/A | ❌ Abathur 测试失败，无 Abathur 单位 | ❌ |
| Reborn galaxy 代码运行 | N/A | ⚠️ SwarmSetup 被触发，但子触发器前置条件不满足 | ⚠️ |
| 单位生产验证 | ✅ | ❌ 未验证（无 Reborn 特有单位可生产） | ❌ |
| Reborn 特有机制 | N/A | ❌ 未验证 | ❌ |

## 结论

之前的"重生虫心移植完成"声明是错误的。实际状态：
- **5 mod 加载链路确实完成**（无 ScriptError，无崩溃）
- **Reborn 16 个指挥官功能完全未正常工作**（前置条件不满足 + 单位体系冲突）
- **需要架构层面的修复**才能让 Reborn 指挥官功能正常

下一步需要与用户确认选择哪个修复方案（A/B/C），然后实施。
