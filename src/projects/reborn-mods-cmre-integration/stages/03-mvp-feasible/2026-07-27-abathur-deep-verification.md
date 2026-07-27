# Abathur 深度验证：单位/技能/属性对比（静态分析 vs 运行时）

## 日期
2026-07-27

## 背景
用户质疑之前只验证了 K5Kerrigan→HunterKiller 替换，没有验证：
1. 重生虫心有哪些指挥官
2. 每个指挥官的单位、技能属性是否列出
3. Abathur 的核心机制（单位购买技能升级）是否验证
4. 单位是否全

## 1. 重生虫心 16 个指挥官

信源：[Lib48DF4533.galaxy#L5016-L5167](file:///e:/Code/MyMod/SC2VibeTools/cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/Lib48DF4533.galaxy#L5016-L5167) CommanderStart_Func 分支

| # | 指挥官 | 种族 | K5Kerrigan 替换为 | 替换数量 |
|---|--------|------|-------------------|---------|
| 1 | Abathur | Zerg | HunterKiller | 1:1 |
| 2 | Dehaka | Zerg | Dehaka | 1:1 |
| 3 | Izsha | Zerg | Izsha | 1:1 |
| 4 | Karass | Protoss | Karass | 1:1 |
| 5 | Kerrigan | Zerg | (不替换，K5Kerrigan 即 Kerrigan) | - |
| 6 | Naktul | Zerg | Naktul | 1:1 |
| 7 | Narud | Protoss | Narud | 1:1 |
| 8 | Raynor | Terran | WarPig | 1:2 |
| 9 | Stukov | Zerg | Stukov | 1:1 |
| 10 | Tosh | Terran | Spectre | 1:1 |
| 11 | Urun | Protoss | VoidSeeker | 1:1 |
| 12 | Warfield | Terran | Warfield | 1:1 |
| 13 | Mengsk | Terran | Mengsk | 1:1 |
| 14 | Zagara | Zerg | Zagara | 1:1 |
| 15 | Zeratul | Protoss | Zeratul | 1:1 |
| 16 | Random | - | 随机选择上述之一 | - |

## 2. Abathur 完整机制（静态分析）

### 2.1 单位生产（UnitUnlocks_Func）

信源：[Lib48DF4533.galaxy#L5215-L5494](file:///e:/Code/MyMod/SC2VibeTools/cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/Lib48DF4533.galaxy#L5215-L5494)

通过 `TechTreeUnitAllow` 解锁虫族单位，基于战役进度银行字段 `Maps/*`：

| 战役地图 | 解锁建筑 | 解锁单位（进化分支） |
|---------|---------|-------------------|
| Rendezvous/Back in the Saddle | - | Queen |
| Harvest of Screams | RoachWarren + Lair | Roach/RoachCorpser/Igniter/Ravager/RoachVile |
| Shoot the Messenger | HydraliskDen + Lair | Hydralisk/HydraliskImpaler/HydraliskLurker/HunterKiller/Hydralisk2 |
| Hand of Darkness | UltraliskCavern + Lair + Hive | Ultralisk/UltraliskKaldir/HotSNoxious/UltraliskSavage/HotSTorrasque |
| Waking the Ancient | Spire | Mutalisk/MutaliskChar/Mamba/MutaliskAnkylos/Mesmer |
| Domination | BanelingNest | Baneling/HotSHunter/HotSSplitterlingBig/FrostFiend/BileTitan |
| The Crucible | InfestationPit | SwarmHost/SwarmHostSplitA/SwarmHostSplitB/BaneHost/VespidHost |
| Old Soldiers | - | InfestedAbomination |
| With Friends Like These | GreaterSpire | BroodLord/IzshaGuardian/Devourer/Kraken |
| Infested | InfestationPit | Infestor/Viper/DefilerMP |

共 **40+ 种虫族单位**（含进化分支）。

### 2.2 Abathur 特有机制（gt_Abathur_Func）

信源：[Lib48DF4533.galaxy#L10958-L11099](file:///e:/Code/MyMod/SC2VibeTools/cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/Lib48DF4533.galaxy#L10958-L11099)

前置条件：`TechTreeUpgradeCount(player, "Abathur", c_techCountCompleteOnly) == 1`

#### 2.2.1 能力商店启用（16 个可购买技能）

```galaxy
TechTreeAbilityAllow(player, AbilityCommand("CommanderUnits", 2), true);  // 启用 CommanderUnits 商店
TechTreeAbilityAllow(player, AbilityCommand("CommanderUnits", 1), true);
TechTreeAbilityAllow(player, AbilityCommand("CommanderUnits", 0), false);
TechTreeAbilityAllow(player, AbilityCommand("NaturalCamouflage", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("Cliffjumper", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("CombatDrone", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("MineralEfficiency", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("VespeneEfficiency", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("FastMorphing", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("AcidMortar", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("BroodlingInfestation", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("CloudofFlies", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("Range", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("RagingTentacle", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("AdrenalineOverdose", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("BanelingGestation", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("BileShield", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("MeleeStrain", 0), true);
TechTreeAbilityAllow(player, AbilityCommand("RoachlingInfestation", 0), true);
```

#### 2.2.2 单位技能添加（UnitAbilityAdd）

| 单位系 | 添加的 5 个技能 |
|--------|---------------|
| Zergling/HotSRaptor/HotSSwarmling/Pygalisk/ZerglingToxic | ArmoredCarapace, KetamineInfusion, Kleptomania, Moonrage, Stealthling |
| Overlord/Overseer | OverlordRadar, OverlordZerglings, OverlordGun, OverlordGirth, OverlordZoomies |
| Baneling/BileTitan/FrostFiend/HotSHunter/HotSSplitterlingBig | BanelingCreep, BanelingNuke, BanelingShields, BanelingSpeed, BanelingZerglings |
| Hydralisk/HydraliskImpaler/HydraliskLurker/HunterKiller/Hydralisk2 | HydraliskBroodlings, HydraliskCripple, HydraliskMechanical, HydraliskMelee, HydraliskRange |
| Roach/RoachCorpser/Igniter/Ravager/RoachVile | AdrenalineOverdose, BanelingGestation, BileShield, MeleeStrain, RoachlingInfestation |

#### 2.2.3 AbathurAbilities 触发器

信源：[Lib48DF4533.galaxy#L11109-L11175](file:///e:/Code/MyMod/SC2VibeTools/cmre-runtime/Mods/reborn/crys_the_swarm_reborn.SC2Mod/Base.SC2Data/Lib48DF4533.galaxy#L11109-L11175)

当新单位进入地图时自动添加对应技能（与 2.2.2 相同逻辑）。`TriggerEnable(lib48DF4533_gt_AbathurAbilities, true)` 在 gt_Abathur_Func 末尾启用。

## 3. 运行时验证结果

### 3.1 深度调试银行指标（CMRERebornDebug.SC2Bank）

证据文件：[CMRERebornDebug.SC2Bank.20260727-abathur-deep-debug](./evidence/CMRERebornDebug.SC2Bank.20260727-abathur-deep-debug)

| 指标 | 值 | 验证项 | 结果 |
|------|---|--------|------|
| deep_debug_ran | 1 | 深度调试代码执行 | ✅ |
| initlib_patch_ran | 1 | InitLib patch 执行 | ✅ |
| initlib_k5kerrigan_p1_count | 1 | InitLib 创建 K5Kerrigan | ✅ |
| k5kerrigan_patch_ran | 1 | SwarmSetup V2 patch 执行 | ✅ |
| k5kerrigan_p1_count | 1 | SwarmSetup 创建 K5Kerrigan | ✅ |
| **abathur_upgrade_count** | **1** | **CommanderStart SetUpgradeLevel("Abathur", 1)** | **✅ 成功** |
| k5kerrigan_p1_after_swarmsetup | 0 | K5Kerrigan 被替换掉 | ✅ |
| hunterkiller_p1_count | 0 | HunterKiller（查询别名返回 0） | ⚠️ 见说明 |
| hydraliskimpaler_p1_count | 1 | HydraliskImpaler（HunterKiller 内部 ID） | ✅ |
| zerg_p1_total_units | 4 | SwarmSetup 末尾 P1 单位总数 | ⚠️ 见说明 |
| **abathur_abilities_trigger_enabled** | **1** | **AbathurAbilities 触发器启用** | **✅ 成功** |

**说明**：
- `hunterkiller_p1_count=0` 但 `hydraliskimpaler_p1_count=1`：HunterKiller 是 HydraliskImpaler 的 co-op 别名，SC2 的 `UnitGroup("HunterKiller", ...)` 查询返回 0（因为单位实际类型是 HydraliskImpaler），但 `UnitGroup("HydraliskImpaler", ...)` 返回 1。这是 SC2 引擎行为，不是 bug。
- `zerg_p1_total_units=4`：深度调试在 SwarmSetup_Func 末尾执行，此时 P1 只有 1 个 HydraliskImpaler + 3 个其他单位（建筑等）。帝国工兵（3diguolaogong）由 CMRE 在后续阶段创建。

### 3.2 NeuroIntegration 银行单位清单（游戏运行后）

证据文件：[NeuroIntegration.SC2Bank.20260727-abathur-deep-debug](./evidence/NeuroIntegration.SC2Bank.20260727-abathur-deep-debug)

| 玩家 | 单位列表 | Abathur 特有单位 |
|------|---------|----------------|
| P1 | `3diguolaogong=12; HydraliskImpaler=3; 3diguoqianshaojidi=1; ACHeroSpawnPlacement=1` | **HydraliskImpaler=3** ✅ |
| P2 | `3diguolaogong=12; 3diguoqianshaojidi=1; ACHeroSpawnPlacement=1` | 无（P2 不是 coop_group） |

### 3.3 cryswarmcoop 银行预写内容

| Section | 内容 | 验证 |
|---------|------|------|
| Commanders/Commander | "Abathur" | ✅ |
| Settings/Difficulty | 3 | ✅ |
| Settings/Speed | 3 | ✅ |
| Evolutions | 9 个进化选择（Raptorling/Hunter/Corpser/Impaler/Char/Carrion/Indra/Brood Lord/Infestor） | ✅ |
| Maps | 8 个战役地图全部 flag=1 | ✅ |

## 4. 静态分析 vs 运行时对比

### 4.1 ✅ 已验证生效

| 机制 | 静态分析 | 运行时 | 结果 |
|------|---------|--------|------|
| K5Kerrigan→HunterKiller 替换 | CommanderStart Abathur 分支 | HydraliskImpaler=3 | ✅ |
| Abathur 升级设置 | SetUpgradeLevel("Abathur", 1) | abathur_upgrade_count=1 | ✅ |
| AbathurAbilities 触发器启用 | TriggerEnable(gt_AbathurAbilities, true) | abathur_abilities_trigger_enabled=1 | ✅ |
| 战役地图解锁 | Maps/* flag=1 | 银行已写入 8 个地图 | ✅ |
| 进化选择 | Evolutions/* | 银行已写入 9 个进化 | ✅ |
| CommanderUnits 商店启用 | TechTreeAbilityAllow(CommanderUnits, 2, true) | 间接验证（abathur_upgrade_count=1 触发了 gt_Abathur_Func） | ✅ |

### 4.2 ⚠️ 未完全验证

| 机制 | 静态分析 | 运行时状态 | 差距 |
|------|---------|----------|------|
| 单位技能添加 | UnitAbilityAdd(HunterKiller, HydraliskBroodlings/Cripple/Mechanical/Melee/Range) | AbathurAbilities 触发器已启用，但未直接验证技能是否添加到单位 | 需要进图手动检查 HunterKiller 的技能面板 |
| CommanderUnits 技能购买 | 16 个可购买技能（NaturalCamouflage/Cliffjumper/...） | 商店已启用，但玩家无资源购买 | 需要给玩家资源后手动购买并验证 |
| 虫族单位生产 | 40+ 种虫族单位（Zergling/Roach/Hydralisk/Baneling/Ultralisk/Mutalisk...） | **P1 只有 3 个 HunterKiller，没有其他虫族单位** | **核心差距：见 4.3** |

### 4.3 ❌ 核心差距：单位不全

**根本原因**：Reborn 的单位生产系统依赖虫族建筑体系，但 CMRE 给的是帝国建筑体系。

| 项目 | Reborn 期望 | CMRE 实际 | 结果 |
|------|------------|----------|------|
| 起始建筑 | Hatchery（虫族主基地） | 3diguoqianshaojidi（帝国前哨基地） | ❌ 不匹配 |
| 起始工兵 | Drone（虫族工兵） | 3diguolaogong（帝国老工兵） | ❌ 不匹配 |
| 种族 | Zerg（Abathur 分支 PlayerSetRace("Zerg")） | PlayerSetRace 已执行 | ✅ 种族已改 |
| 建筑生产链 | Hatchery → Spawning Pool → Roach Warren → HydraliskDen → ... | 帝国建筑无法训练虫族单位 | ❌ 生产链断裂 |

**详细分析**：
1. Abathur 的 CommanderStart 分支执行了 `PlayerSetRace(player, "Zerg")`，把玩家种族改为 Zerg ✅
2. UnitUnlocks_Func 通过 `TechTreeUnitAllow(player, "RoachWarren", true)` 等解锁了所有虫族建筑和单位 ✅
3. **但 CMRE 给的起始建筑是 `3diguoqianshaojidi`（帝国前哨基地），不是 `Hatchery`（虫族主基地）** ❌
4. 虫族单位需要虫族建筑训练：Zergling 需要 Spawning Pool，Roach 需要 Roach Warren，Hydralisk 需要 HydraliskDen
5. 虫族建筑需要 Drone（虫族工兵）建造，但 CMRE 给的是 `3diguolaogong`（帝国老工兵）
6. **结果**：即使科技树解锁了所有虫族单位，玩家也无法生产，因为没有虫族建筑和工兵

**P1 实际单位列表**：
- 3diguolaogong=12（帝国老工兵，不能建造虫族建筑）
- HydraliskImpaler=3（HunterKiller，由 K5Kerrigan 替换而来，不是生产的）
- 3diguoqianshaojidi=1（帝国前哨基地，不能训练虫族单位）
- ACHeroSpawnPlacement=1（CMRE 英雄放置点）

**缺失的 Abathur 单位**（静态分析有，运行时没有）：
- Zergling/HotSRaptor/HotSSwarmling/Pygalisk/ZerglingToxic（需要 Spawning Pool）
- Roach/RoachCorpser/Igniter/Ravager/RoachVile（需要 Roach Warren）
- Hydralisk/HydraliskImpaler/HydraliskLurker/Hydralisk2（需要 HydraliskDen，只有 HunterKiller 替换出来的 3 个）
- Baneling/HotSHunter/HotSSplitterlingBig/FrostFiend/BileTitan（需要 BanelingNest）
- Ultralisk/UltraliskKaldir/HotSNoxious/UltraliskSavage/HotSTorrasque（需要 UltraliskCavern）
- Mutalisk/MutaliskChar/Mamba/MutaliskAnkylos/Mesmer（需要 Spire）
- SwarmHost/SwarmHostSplitA/SwarmHostSplitB/BaneHost/VespidHost（需要 InfestationPit）
- BroodLord/IzshaGuardian/Devourer/Kraken（需要 GreaterSpire）
- Infestor/Viper/DefilerMP（需要 InfestationPit）
- Queen（需要 Lair）

## 5. 结论

### 5.1 已验证的部分

1. **16 个指挥官**已列出（Abathur/Dehaka/Izsha/Karass/Kerrigan/Naktul/Narud/Raynor/Stukov/Tosh/Urun/Warfield/Mengsk/Zagara/Zeratul/Random）
2. **K5Kerrigan→HunterKiller 替换**成功（HydraliskImpaler=3）
3. **Abathur 升级设置**成功（abathur_upgrade_count=1）
4. **AbathurAbilities 触发器启用**成功（abathur_abilities_trigger_enabled=1）
5. **CommanderUnits 技能商店启用**成功（间接验证）
6. **战役地图全解锁**（Maps/* flag=1）

### 5.2 未完全验证的部分

1. **单位技能添加**：AbathurAbilities 触发器启用了，但 HunterKiller 是否真的有 HydraliskBroodlings 等 5 个技能，需要进图手动检查
2. **CommanderUnits 技能购买**：商店启用了，但玩家无资源购买，需要给资源后手动购买验证

### 5.3 核心差距（单位不全）

**单位不全**。P1 只有 3 个 HunterKiller（K5Kerrigan 替换而来），没有 Zergling/Roach/Hydralisk/Baneling/Ultralisk/Mutalisk 等虫族单位。

根本原因：**Reborn 期望虫族建筑体系（Hatchery/Spawning Pool/Roach Warren 等），但 CMRE 给的是帝国建筑体系（3diguoqianshaojidi）**。即使 UnitUnlocks 解锁了所有虫族单位的科技树，玩家也无法生产，因为没有虫族建筑和工兵。

### 5.4 下一步建议

要让 Abathur 的完整单位生产体系工作，需要：
1. **替换起始建筑**：把 CMRE 的 `3diguoqianshaojidi` 替换为 `Hatchery`（虫族主基地）
2. **替换起始工兵**：把 `3diguolaogong` 替换为 `Drone`（虫族工兵）
3. **验证建筑生产链**：Drone 建造 Spawning Pool → 训练 Zergling → 升级 Lair → 建造 Roach Warren → 训练 Roach 等
4. **验证技能购买**：给玩家资源，手动购买 CommanderUnits 商店中的 16 个技能
5. **验证单位技能**：进图手动检查 HunterKiller 是否有 HydraliskBroodlings 等 5 个技能

或者，如果目标只是验证 K5Kerrigan 替换 + Abathur 机制触发（不要求完整单位生产），当前结果已足够：
- Abathur 升级设置 ✅
- AbathurAbilities 触发器启用 ✅
- HunterKiller 创建 ✅
- 战役地图全解锁 ✅
- 进化选择写入 ✅
