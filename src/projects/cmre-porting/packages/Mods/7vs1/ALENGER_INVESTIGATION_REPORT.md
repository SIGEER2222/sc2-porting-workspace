# 阿巴瑟之心 - 10个未移植指挥官mod调查报告

> 生成时间：2026-07-25
> 解包源目录：`C:\Users\22448\Downloads\阿巴瑟之心\Mods\Alenger`
> 解包目标目录：`e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\7vs1\`

## 1. 解包状态

| Mod编号 | 源文件 | 目标目录 | 状态 |
|---------|--------|----------|------|
| Alenger1 | 1钢铁.SC2Mod (1.4MB) | Alenger1.SC2Mod | ✅ 已解包 |
| Alenger2 | 2贝希摩斯虫群.SC2Mod (20.8MB) | Alenger2.SC2Mod | ✅ 已解包 |
| Alenger4 | 4塔达林.SC2Mod (53.4MB) | Alenger4.SC2Mod | ✅ 已解包 |
| Alenger7 | 7卡莱.SC2Mod (4.5MB) | Alenger7.SC2Mod | ✅ 已解包 |
| Alenger8 | 8扎加拉.SC2Mod (5.5MB) | Alenger8.SC2Mod | ✅ 已解包 |
| Alenger9 | 9海盗.SC2Mod (12.9MB) | Alenger9.SC2Mod | ✅ 已解包 |
| Alenger10 | 10埃蒙.SC2Mod (316KB) | Alenger10.SC2Mod | ✅ 已解包 |
| Alenger11 | 11群友.SC2Mod (6.4MB) | Alenger11.SC2Mod | ✅ 已解包 |
| Alenger12 | 12游骑兵.SC2Mod (189KB) | Alenger12.SC2Mod | ✅ 已解包 |
| Alenger13 | 13净化者.SC2Mod (11.8MB) | Alenger13.SC2Mod | ✅ 已解包 |

所有10个mod及对应的Adapter mod（AlengerXAdapter.SC2Mod）均已解包完成。

## 2. 各mod详细调查

### Alenger1 - 钢铁

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger1 / 钢铁 |
| 种族 | Terran (人类) |
| 指挥官ID | `1gangtie` |
| 起始建筑 | `1gangtieyaosai` (钢铁要塞) |
| 起始工人 | `1gangtiegongchengche` (钢铁工程车, SCV型) |
| 英雄单位 | `1jiguangzuanji` (激光钻机), `1gangtietaitan` (钢铁泰坦) |
| 建造能力ID | `1jianzao`, `1jianzao2`, `1jianzao5` |
| CommanderData.xml | ✅ 有 (1gangtie) |
| DocumentHeader依赖 | 通用效果.SC2Mod |
| 单位前缀 | `1` |

### Alenger2 - 贝希摩斯虫群

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger2 / 贝希摩斯虫群 |
| 种族 | Zerg (异虫) |
| 指挥官ID | ⚠️ 定义在通用效果.SC2Mod中（未解包） |
| 起始建筑 | `2chujichaoxue` (初级巢穴) |
| 起始工人 | `2gongchong` (工虫, Drone型) |
| 英雄单位 | `2tiyamate` (提亚玛特), `2chonghou` (虫后) |
| 建造能力ID | `2gongchongbianyi` (工虫变异), `2fuhuajuntanzhongliu` (孵化军探肿瘤) |
| CommanderData.xml | ❌ 无（在通用效果mod中） |
| DocumentHeader依赖 | 通用效果.SC2Mod |
| 单位前缀 | `2` |

### Alenger4 - 塔达林

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger4 / 塔达林 |
| 种族 | Protoss (星灵) |
| 指挥官ID | ⚠️ 定义在通用效果.SC2Mod中（未解包） |
| 起始建筑 | `4zhanzhengshuniu` (战争枢纽, Nexus型) |
| 起始工人 | `4zhanzhengtanji` (战争探机, Probe型) |
| 英雄单位 | `4alenger` (阿尔纳), `4heianwangzuo` (黑暗王座) |
| 建造能力ID | `4jianzhuzheyue` (建造折跃) |
| CommanderData.xml | ❌ 无（在通用效果mod中） |
| DocumentHeader依赖 | 通用效果.SC2Mod |
| 单位前缀 | `4` |

### Alenger7 - 卡莱

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger7 / 卡莱 |
| 种族 | Protoss (星灵) |
| 指挥官ID | ⚠️ 定义在通用效果.SC2Mod中（未解包） |
| 起始建筑 | `7xiangweishuniu` (相位枢纽, 充能折跃制) |
| 起始工人 | ⚠️ 无传统工人 - 采用充能折跃机制（建筑由枢纽通过charge直接折跃） |
| 英雄单位 | `7mujianhexin` (母舰核心) |
| 建造能力ID | `7zheyuejianzao` (折跃建造), `7zheyuexiangweishuniu` |
| CommanderData.xml | ❌ 无（在通用效果mod中） |
| DocumentHeader依赖 | 通用效果.SC2Mod |
| 单位前缀 | `7` |
| 备注 | 特殊机制：建筑通过 `7zheyuejianzao` 充能折跃，无传统工人单位 |

### Alenger8 - 扎加拉

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger8 / 扎加拉 |
| 种族 | Zerg (异虫) |
| 指挥官ID | `8zhajiala` |
| 起始建筑 | `8fuhuachang` (孵化场, 由工人变异) |
| 起始工人 | `8gongfeng` (工蜂, Drone型) |
| 英雄单位 | `8zhajiala` (扎加拉，同时为指挥官ID) |
| 建造能力ID | `8jianzhubianyi` (建造变异), `8fuhuajuntanzhongliu` |
| CommanderData.xml | ✅ 有 (8zhajiala) |
| DocumentHeader依赖 | 通用效果.SC2Mod |
| 单位前缀 | `8` |

### Alenger9 - 海盗

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger9 / 海盗 |
| 种族 | Terran (人类) |
| 指挥官ID | `9haidao` |
| 起始建筑 | `9qianxianzhihuizhongxin` (前线指挥中心, CommandCenter型) |
| 起始工人 | `9shihuangzhe` (噬皇者, SCV型带护盾, FlagArray Worker=1) |
| 英雄单位 | `9morizhadan` (末日炸弹), `9shenlongbaiwei` (神龙百威) |
| 建造能力ID | `9jianzao` (建造), `9bushumorizhadan` (部署末日炸弹) |
| CommanderData.xml | ✅ 有 (9haidao) |
| DocumentHeader依赖 | 通用效果.SC2Mod |
| 单位前缀 | `9` |

### Alenger10 - 埃蒙

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger10 / 埃蒙 |
| 种族 | 混合体（Hybrid，非传统种族） |
| 指挥官ID | ⚠️ 定义在通用效果.SC2Mod中（未解包） |
| 起始建筑 | ⚠️ 无传统建筑 - 通过能力召唤混合体 |
| 起始工人 | ⚠️ 无工人单位 |
| 英雄单位 | `10hunhetisiliezhe` (混合体撕裂者) |
| 建造能力ID | ⚠️ 无 CAbilBuild - 使用召唤能力（`10miejuechongji`, `10pingyijianglin`, `10shangshu`, `10xukongliexi` 等） |
| CommanderData.xml | ❌ 无（在通用效果mod中） |
| DocumentHeader依赖 | 通用效果.SC2Mod |
| 单位前缀 | `10` |
| 备注 | 纯召唤制mod，单位均为混合体系列（`10hunheti*`），通过能力直接召唤 |

### Alenger11 - 群友

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger11 / 群友 |
| 种族 | 多种族混合（Terran/Zerg/Protoss均有英雄） |
| 指挥官ID | ⚠️ 定义在通用效果.SC2Mod中（未解包） |
| 起始建筑 | ⚠️ 无传统建筑 - 英雄召唤制 |
| 起始工人 | ⚠️ 无工人单位 |
| 英雄单位 | 12+英雄单位（见下方列表） |
| 建造能力ID | ⚠️ 无 CAbilBuild - 使用 `11jietu` (结途), `11kongtoucang` (空投舱) 召唤 |
| CommanderData.xml | ❌ 无（在通用效果mod中） |
| DocumentHeader依赖 | 通用效果.SC2Mod |
| 单位前缀 | `11` |

英雄单位列表（EditorCategories=ObjectType:Hero）：
- `11xiaojianguo` (小坚果, Terran Marauder型)
- `11nuowalu` (诺瓦露, Protoss)
- `11yuyingweilai` (雨樱未来, Zerg)
- `11zishen` (紫神, Zerg)
- `11jddhsn` (Zerg)
- `11jibianti` (畸变体)
- `11jjgg`
- `11xingchen` (星辰)
- `11sepilongwang` (裂龙王)
- `11zaixiaheikong` (在下黑空)
- `11Ob`
- `11jibamaoxiaowo`
- `11qiuligao` (秋梨高)

### Alenger12 - 游骑兵

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger12 / 游骑兵 |
| 种族 | Terran (人类) |
| 指挥官ID | `12youqibing` |
| 起始建筑 | `12guidaokongzhijidi` (轨道控制基地, OrbitalCommand型) |
| 起始工人 | `12sishuigongchengche` (死水工程车, SCV型) |
| 英雄单位 | `12xiubolianhao` (休伯利安号, 战巡舰型英雄) |
| 建造能力ID | `12jianzao` (建造) |
| CommanderData.xml | ✅ 有 (12youqibing) |
| DocumentHeader依赖 | bnet:0通用效果/0.0/177877, 通用效果.SC2Mod |
| 单位前缀 | `12` |

### Alenger13 - 净化者

| 项目 | 值 |
|------|-----|
| Mod编号/名称 | Alenger13 / 净化者 |
| 种族 | Protoss (星灵) |
| 指挥官ID | `13tilate` |
| 起始建筑 | `13jinghuazheshuniu` (净化者枢纽, Nexus型) |
| 起始工人 | `13tanji` (探机, Probe型) |
| 英雄单位 | `13tianwangjuzhen` (天王巨阵, 母舰型英雄, HP13500/护盾4500) |
| 建造能力ID | `13zheyuejianzao` (折跃建造), `13bianxingjianzao` (变形建造), `13bushufuwuqi` (部署服务武器), `13zheyuejianzao5` |
| CommanderData.xml | ✅ 有 (13tilate) |
| DocumentHeader依赖 | bnet:0通用效果/0.0/177877, 通用效果.SC2Mod |
| 单位前缀 | `13` |

## 3. 汇总表格

| Mod | 名称 | 种族 | 指挥官ID | 起始建筑 | 工人 | 英雄单位 | 建造能力ID | CommanderData |
|-----|------|------|----------|----------|------|----------|------------|---------------|
| 1 | 钢铁 | Terran | 1gangtie | 1gangtieyaosai | 1gangtiegongchengche | 1jiguangzuanji, 1gangtietaitan | 1jianzao | ✅ |
| 2 | 贝希摩斯虫群 | Zerg | ⚠️通用效果mod | 2chujichaoxue | 2gongchong | 2tiyamate, 2chonghou | 2gongchongbianyi | ❌ |
| 4 | 塔达林 | Protoss | ⚠️通用效果mod | 4zhanzhengshuniu | 4zhanzhengtanji | 4alenger, 4heianwangzuo | 4jianzhuzheyue | ❌ |
| 7 | 卡莱 | Protoss | ⚠️通用效果mod | 7xiangweishuniu | 无(充能折跃) | 7mujianhexin | 7zheyuejianzao | ❌ |
| 8 | 扎加拉 | Zerg | 8zhajiala | 8fuhuachang | 8gongfeng | 8zhajiala | 8jianzhubianyi | ✅ |
| 9 | 海盗 | Terran | 9haidao | 9qianxianzhihuizhongxin | 9shihuangzhe | 9morizhadan, 9shenlongbaiwei | 9jianzao | ✅ |
| 10 | 埃蒙 | 混合体 | ⚠️通用效果mod | 无(召唤制) | 无 | 10hunhetisiliezhe | 无(召唤能力) | ❌ |
| 11 | 群友 | 多种族 | ⚠️通用效果mod | 无(召唤制) | 无 | 11xiaojianguo等12+英雄 | 无(召唤能力) | ❌ |
| 12 | 游骑兵 | Terran | 12youqibing | 12guidaokongzhijidi | 12sishuigongchengche | 12xiubolianhao | 12jianzao | ✅ |
| 13 | 净化者 | Protoss | 13tilate | 13jinghuazheshuniu | 13tanji | 13tianwangjuzhen | 13zheyuejianzao | ✅ |

## 4. vanillaRemovals 种族映射

根据 Alenger6 已有配置 `["Hatchery", "Drone", "Overlord", "CommandCenter", "SCV"]` 的模式，需移除对应种族的原版建筑和单位。

### 按种族分类的 vanillaRemovals

**Terran 系（Alenger1, 9, 12）：**
```json
["CommandCenter", "SCV", "SupplyDepot", "Barracks", "Refinery", "EngineeringBay", "Bunker", "MissileTurret", "Factory", "Starport", "Armory", "GhostAcademy", "FusionCore", "OrbitalCommand", "PlanetaryFortress", "TechLab", "Reactor", "SensorTower", "EBay"]
```

**Zerg 系（Alenger2, 8）：**
```json
["Hatchery", "Drone", "Overlord", "Extractor", "SpawningPool", "EvolutionChamber", "RoachWarren", "BanelingNest", "HydraliskDen", "Spire", "UltraliskCavern", "InfestationPit", "NydusNetwork", "Lair", "Hive", "GreaterSpire", "LurkerDenMP", "CreepTumor"]
```

**Protoss 系（Alenger4, 7, 13）：**
```json
["Nexus", "Probe", "Pylon", "Gateway", "CyberneticsCore", "Assimilator", "Forge", "PhotonCannon", "RoboticsFacility", "Stargate", "TwilightCouncil", "RoboticsBay", "FleetBeacon", "TemplarArchive", "DarkShrine", "WarpGate", "ShieldBattery", "KelMorianCombustionLamp"]
```

**混合体系（Alenger10）：**
```json
["CommandCenter", "SCV", "Hatchery", "Drone", "Overlord", "Nexus", "Probe", "Pylon", "Gateway", "Barracks", "SupplyDepot", "SpawningPool", "Extractor", "Refinery", "Assimilator"]
```
> 移除所有三族原版起始建筑和工人，因为混合体mod不使用传统建造系统。

**群友系（Alenger11）：**
```json
["CommandCenter", "SCV", "Hatchery", "Drone", "Overlord", "Nexus", "Probe"]
```
> 仅移除三族起始建筑和工人，群友mod为纯英雄召唤制。

### 各mod的 vanillaRemovals 推荐配置

| Mod | 种族 | vanillaRemovals |
|-----|------|-----------------|
| Alenger1 | Terran | Terran系 |
| Alenger2 | Zerg | Zerg系 |
| Alenger4 | Protoss | Protoss系 |
| Alenger7 | Protoss | Protoss系（注意：无传统工人，需保留充能折跃机制） |
| Alenger8 | Zerg | Zerg系 |
| Alenger9 | Terran | Terran系 |
| Alenger10 | 混合体 | 混合体系（全三族） |
| Alenger11 | 多种族 | 群友系（全三族起始单位） |
| Alenger12 | Terran | Terran系 |
| Alenger13 | Protoss | Protoss系 |

## 5. Adapter mod 信息

每个 mod 均有对应的 Adapter mod（`AlengerXAdapter.SC2Mod`），包含 galaxy 脚本用于：
1. 为玩家1升级全部科技
2. 解锁所有自定义能力（cmd 0-31 全解锁）
3. 解锁所有自定义单位（TechTreeUnitAllow）
4. 周期性重解锁（5秒×8次，覆盖40秒）

Adapter 文件结构：
- `LibA{X}ADAPTER.galaxy` - 主逻辑
- `LibA{X}ADAPTER_h.galaxy` - 头文件
- `LibA{X}ADAPTER_Catalog.galaxy` - 目录数据（仅7、13有）

## 6. 待确认事项

1. **通用效果.SC2Mod 未解包**：该mod（308KB，MPQ格式）无法用7z解包（7z报错"Cannot open the file as archive"）。Alenger2/4/7/10/11的指挥官ID定义在此mod中，需用MPQ专用工具（如SC2编辑器或mpqeditor）解包后确认。

2. **Alenger7 卡莱的特殊机制**：该mod无传统工人单位，建筑通过 `7zheyuejianzao` 充能折跃机制从 `7xiangweishuniu` 直接折跃。移植时需特殊处理起始单位配置。

3. **Alenger10 埃蒙的召唤机制**：该mod无建造能力（无CAbilBuild），所有单位通过能力召唤。移植时需确认召唤能力的触发逻辑。

4. **Alenger11 群友的多英雄机制**：该mod有12+英雄单位，分属不同种族。移植时需确认英雄选择/召唤逻辑。
