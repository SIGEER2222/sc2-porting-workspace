# 原版 18 指挥官 Buff 补丁设计

**日期**：2026-07-26
**状态**：设计阶段
**关联**：CMRE 框架、LaunchProfile bank、WebUI

## 目标

为原版 18 个合作指挥官增加 buff 补丁系统，包含：
1. **威望优点加成**：提取每个指挥官 3 个威望（P1/P2/P3）的优点，作为可选独立加成（不应用缺点）
2. **精通满级默认**：所有精通项默认 30 点满级，玩家可在 WebUI 上覆盖
3. **保留原版系统**：原版威望选择和精通加点不动，buff 补丁是叠加层

参考实现：`E:\Code\MyMod\SC2\解包数据\海克斯合作PVP0.110.SC2Mod` 的天赋系统。

## 范围

### 首期范围（本设计文档覆盖）

- 18 个原版指挥官的威望优点 supplement upgrade 定义
- 18 个原版指挥官的精通满级默认应用
- WebUI 配置界面（威望优点勾选 + 精通点数滑块）
- Launcher 写入 bank 字段
- galaxy 读取 bank 并应用 buff

### 后续扩展（不在本设计内）

- 海克斯 PVP 风格的额外天赋（如 CatalogReferenceModify 动态修改）
- 起义指挥官（Alenger 系列）的 buff 补丁
- buff 预设方案保存/加载

## 架构

### 三层结构

```
┌─────────────────────────────────────────────────────┐
│ 层 1：数据层（CMRE_BuffPatch.SC2Mod）               │
│  ├─ UpgradeData.xml                                 │
│  │   └─ 54 个 CommanderPrestigeXxxBonus upgrade    │
│  │       (parent=CommanderPrestige, 只含优点)       │
│  └─ DocumentInfo 依赖 CMRE_Core_Base/Mengsk/Stetmann│
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│ 层 2：配置层（WebUI + Launcher + Bank）             │
│  ├─ WebUI: Buff 补丁 Tab                            │
│  │   ├─ 威望优点勾选 (3 checkbox / 指挥官)          │
│  │   └─ 精通点数滑块 (6 slider / 指挥官, 默认30)    │
│  ├─ Launcher: -Buffs / -Masteries 参数              │
│  └─ Bank: Player|N|PrestigeBonusMask (bitmask)     │
│           Player|N|EnableBuffPatch                  │
│           Player|N|Mastery|slot|Value               │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│ 层 3：应用层（galaxy 触发器）                       │
│  ├─ CMUIX_LaunchProfileApplyBuffs(bank, player)     │
│  │   ├─ 读 PrestigeBonus mask                       │
│  │   ├─ TechTreeUpgradeAddLevel(supplement)         │
│  │   └─ 读 Mastery values                           │
│  │       → libCOOC_gf_CC_PlayerMasteryUpgradeLevelSet│
│  └─ 在 CMUIX_LaunchProfileApplyCommanderCustomization│
│     末尾调用                                         │
└─────────────────────────────────────────────────────┘
```

### 数据流

1. 玩家在 WebUI 上勾选威望优点 + 调整精通点数
2. WebUI `/api/launch` 把 `buffs` 和 `masteries` 字段传给 launcher
3. Launcher `Write-CmreLaunchProfile` 把配置写入 `CMCoopLaunchProfile.SC2Bank`
4. SC2 启动加载地图，galaxy 触发器 `CMUIX_LaunchProfileTryLoadForStartup` 读取 bank
5. `CMUIX_LaunchProfileApply` 调用 `CMUIX_LaunchProfileApplyCommanderCustomization`
6. 在该函数末尾追加 `CMUIX_LaunchProfileApplyBuffs` 调用
7. `CMUIX_LaunchProfileApplyBuffs` 读取 buff 字段，应用 supplement upgrade 和精通点数

## 详细设计

### 层 1：数据层 — CMRE_BuffPatch.SC2Mod

#### 1.1 mod 包位置

```
e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\
  ├─ Base.SC2Data\
  │  └─ GameData\
  │     ├─ UpgradeData.xml      # 54 个 supplement upgrade
  │     └─ GameData.xml         # catalog includes
  ├─ zhCN.SC2Data\
  │  └─ LocalizedData\
  │     └─ GameStrings.txt      # buff 名称/描述本地化
  ├─ ComponentList.SC2Components
  ├─ DocumentHeader
  ├─ DocumentInfo               # 依赖 CMRE_Core_Base / Mengsk / Stetmann
  └─ DocumentInfo.version
```

#### 1.2 UpgradeData.xml 结构

每个原版威望对应一个 `CommanderPrestigeXxxBonus` upgrade，**只包含优点的 EffectArray**。

示例（Raynor P1 "死水元帅" 优点：生物单位生命值+100%）：

```xml
<CUpgrade id="CommanderPrestigeRaynorBioBonus" parent="CommanderPrestige">
    <EffectArray Reference="Unit,Marine,LifeMax" Value="100"/>
    <EffectArray Reference="Unit,Marine,LifeStart" Value="100"/>
    <EffectArray Reference="Unit,Marauder,LifeMax" Value="100"/>
    <EffectArray Reference="Unit,Marauder,LifeStart" Value="100"/>
    <EffectArray Reference="Unit,Firebat,LifeMax" Value="100"/>
    <EffectArray Reference="Unit,Firebat,LifeStart" Value="100"/>
    <EffectArray Reference="Unit,Medic,LifeMax" Value="100"/>
    <EffectArray Reference="Unit,Medic,LifeStart" Value="100"/>
    <EditorCategories value="Race:Terran,UpgradeType:Talents"/>
    <MaxLevel value="1"/>
</CUpgrade>
```

注意：原版 `CommanderPrestigeRaynorBio` 的 EffectArray 包含优点和缺点，supplement upgrade 只取优点部分。

#### 1.3 威望优点提取规则

提取流程：
1. 从 `commander-power-metadata.json` 读取每个威望的 `tooltip` 字段
2. 解析 tooltip 中 `<s val="Coop_Prestige_Advantage">优点</s>` 段落，得到优点描述
3. 从 `UpgradeData.xml` 找到对应 `primary_upgrade` 的 CUpgrade
4. 分析 EffectArray：
   - `Operation="Add"` 或无 Operation：通常是优点（增加属性）
   - `Operation="Subtract"`：需要看上下文
     - `Subtract` Cost/Cooldown → 优点（降价/降CD）
     - `Subtract` LifeMax/MoveSpeed → 缺点（减血/减速）
5. 用海克斯 PVP 的天赋定义交叉验证（海克斯已为每个指挥官定义了优点函数）
6. 人工审核疑难项

**54 个威望优点清单**（部分示例）：

| 指挥官 | 威望 | 优点 | supplement upgrade id |
|--------|------|------|----------------------|
| Raynor | P1 死水元帅 | 生物单位生命+100% | CommanderPrestigeRaynorBioBonus |
| Raynor | P2 狂暴骑手 | 后燃器攻速+100%, CD-30s | CommanderPrestigeRaynorMechAfterburnersBonus |
| Raynor | P3 不可思议机器 | 战列舰伤害+100% | CommanderPrestigeRaynorBattlecruiserBonus |
| Mengsk | P1 毒性暴君 | 火炮CD-20s, 能量-5, 恐惧+10s | CommanderPrestigeMengskArtilleryBonus |
| ... | ... | ... | ... |

#### 1.4 精通处理

**不新建 supplement upgrade**，直接复用原版 mastery 系统：
- bank 写入 `Player|N|Mastery|slot|Value = 30`（默认满级）
- galaxy 已有 `libCOOC_gf_CC_PlayerMasteryUpgradeLevelSet` 函数应用精通点数
- 玩家在 WebUI 上可调整每项点数（0-30）

### 层 2：配置层

#### 2.1 WebUI 界面

在 cmre-webui 前端新增"Buff 补丁"Tab，包含：

**威望优点区**：
- 指挥官下拉框（默认当前选中指挥官）
- 3 个 checkbox：P1 优点 / P2 优点 / P3 优点
- 每个 checkbox 旁边显示优点描述文本（从 metadata.json 读取）

**精通点数区**：
- 6 个滑块（0-30），默认 30
- 每个滑块旁边显示精通名称和当前点数
- "全部满级"快捷按钮

**配置存储**：
- 前端 localStorage 保存每个指挥官的 buff 配置
- `/api/launch` 时把配置作为 `buffs` 和 `masteries` 字段发送

#### 2.2 WebUI 后端（server.py）

`_handle_launch` 新增参数处理：

```python
buffs = body.get("buffs", {})  # {"P1": true, "P2": false, "P3": true}
masteries = body.get("masteries", [30, 30, 30, 30, 30, 30])

args.append("-Buffs")
args.append(_encode_buffs(buffs))  # "P1,P3" 格式
args.append("-Masteries")
args.append(",".join(str(m) for m in masteries))  # "30,30,30,30,30,30"
```

新增 API：
- `GET /api/buff-metadata`：返回 18 个指挥官的威望优点描述 + 精通项列表（从 metadata.json 派生）

#### 2.3 Launcher（launch-cmre-alenger.ps1）

新增参数：
```powershell
[string]$Buffs = "",        # "P1,P3" 格式，启用哪些威望优点
[string]$Masteries = "",    # "30,30,30,30,30,30" 格式，6 个精通点数
[switch]$EnableBuffPatch    # 是否启用 buff 补丁（默认 false）
```

`Write-CmreLaunchProfile` 函数扩展：

```powershell
if ($EnableBuffPatch) {
    # 威望优点 mask
    $bonusMask = 0
    if ($Buffs -match "P1") { $bonusMask += 1 }
    if ($Buffs -match "P2") { $bonusMask += 2 }
    if ($Buffs -match "P3") { $bonusMask += 4 }
    $values['Player|1|PrestigeBonusMask'] = @("int", [string]$bonusMask)
    $values['Player|2|PrestigeBonusMask'] = @("int", [string]$bonusMask)
    $values['Player|1|EnableBuffPatch'] = @("int", "1")
    $values['Player|2|EnableBuffPatch'] = @("int", "1")

    # 精通点数
    if ($Masteries -ne "") {
        $masteryValues = $Masteries.Split(',') | ForEach-Object { [int]$_.Trim() }
        for ($i = 0; $i -lt 6 -and $i -lt $masteryValues.Count; $i++) {
            $values["Player|1|Mastery|$i|Value"] = @("int", [string]$masteryValues[$i])
            $values["Player|2|Mastery|$i|Value"] = @("int", [string]$masteryValues[$i])
        }
    }
}
```

依赖配置：在 `cmre-alenger-dependencies.json` 的 `baseMods` 中加入 `Commanders\CMRE_BuffPatch.SC2Mod`，所有指挥官都加载。

### 层 3：应用层 — galaxy 触发器

#### 3.1 新增函数

在 `cmui_customization.galaxy` 中新增：

```galaxy
// 应用 buff 补丁
// 在 CMUIX_LaunchProfileApplyCommanderCustomization 末尾调用
void CMUIX_LaunchProfileApplyBuffs (bank lp_bank, int lp_player, string lp_commander) {
    int lv_enableBuffPatch;
    int lv_bonusMask;
    int lv_masteryValue;
    int lv_slot;
    string lv_commanderKey;
    string lv_bonusUpgrade;

    lv_commanderKey = libCOOC_gf_CC_CommanderToBankKey(lp_commander);

    // 1. 检查是否启用 buff 补丁
    lv_enableBuffPatch = BankValueGetAsInt(lp_bank, CMUIX_LAUNCH_PROFILE_SECTION,
        CMUIX_LaunchProfilePlayerKey(lp_player, "EnableBuffPatch"));
    if (lv_enableBuffPatch != 1) {
        return;
    }

    // 2. 应用威望优点 supplement upgrade
    lv_bonusMask = BankValueGetAsInt(lp_bank, CMUIX_LAUNCH_PROFILE_SECTION,
        CMUIX_LaunchProfilePlayerKey(lp_player, "PrestigeBonusMask"));

    // 3. 按指挥官 dispatch 到对应 buff 列表
    // P1 优点 (bit 0)
    if ((lv_bonusMask & 1) != 0) {
        lv_bonusUpgrade = CMUIX_GetPrestigeBonusUpgrade(lp_commander, 1);
        if (StringLength(lv_bonusUpgrade) > 0) {
            TechTreeUpgradeAddLevel(lp_player, lv_bonusUpgrade, 1);
        }
    }
    // P2 优点 (bit 1)
    if ((lv_bonusMask & 2) != 0) {
        lv_bonusUpgrade = CMUIX_GetPrestigeBonusUpgrade(lp_commander, 2);
        if (StringLength(lv_bonusUpgrade) > 0) {
            TechTreeUpgradeAddLevel(lp_player, lv_bonusUpgrade, 1);
        }
    }
    // P3 优点 (bit 2)
    if ((lv_bonusMask & 4) != 0) {
        lv_bonusUpgrade = CMUIX_GetPrestigeBonusUpgrade(lp_commander, 3);
        if (StringLength(lv_bonusUpgrade) > 0) {
            TechTreeUpgradeAddLevel(lp_player, lv_bonusUpgrade, 1);
        }
    }

    // 4. 应用精通点数（覆盖原版精通设置）
    for (lv_slot = 0; lv_slot < 6; lv_slot += 1) {
        lv_masteryValue = BankValueGetAsInt(lp_bank, CMUIX_LAUNCH_PROFILE_SECTION,
            CMUIX_LaunchProfilePlayerSlotKey(lp_player, "Mastery", lv_slot, "Value"));
        if (lv_masteryValue >= 0 && lv_masteryValue <= 30) {
            libCOOC_gf_CC_PlayerMasteryUpgradeLevelSet(lp_player, lv_slot, lv_masteryValue);
        }
    }
}

// 查询指挥官威望优点对应的 supplement upgrade id
string CMUIX_GetPrestigeBonusUpgrade (string lp_commander, int lp_prestigeSlot) {
    // Raynor
    if (StringEqual(lp_commander, "TerranRaynor", true)) {
        if (lp_prestigeSlot == 1) { return "CommanderPrestigeRaynorBioBonus"; }
        if (lp_prestigeSlot == 2) { return "CommanderPrestigeRaynorMechAfterburnersBonus"; }
        if (lp_prestigeSlot == 3) { return "CommanderPrestigeRaynorBattlecruiserBonus"; }
    }
    // Mengsk
    if (StringEqual(lp_commander, "TerranMengsk", true)) {
        if (lp_prestigeSlot == 1) { return "CommanderPrestigeMengskArtilleryBonus"; }
        // ...
    }
    // ... 其他 16 个指挥官
    return "";
}
```

#### 3.2 集成点

在 `CMUIX_LaunchProfileApplyCommanderCustomization`（cmui_customization.galaxy 第 12900 行）末尾追加：

```galaxy
// 原有代码末尾追加
CMUIX_LaunchProfileApplyBuffs(lp_bank, lp_player, lp_commander);
```

#### 3.3 Bank 字段约定

| 字段 | 类型 | 说明 |
|------|------|------|
| `Player\|N\|EnableBuffPatch` | int | 0=禁用, 1=启用 buff 补丁 |
| `Player\|N\|PrestigeBonusMask` | int | bitmask: bit0=P1优点, bit1=P2优点, bit2=P3优点 |
| `Player\|N\|Mastery\|0..5\|Value` | int | 6 个精通槽的点数（0-30），覆盖原版 |

注意：`Player|N|Mastery|slot|Value` 字段需要与原版 mastery 应用逻辑协调，避免双重应用。具体做法：
- 原版 mastery 应用（`CMUIX_LaunchProfileApplyCommanderCustomization` 第 12938-12941 行）先执行
- buff 补丁的 mastery 覆盖后执行，调用 `libCOOC_gf_CC_PlayerMasteryUpgradeLevelSet` 覆盖

## 验证计划

### 单元验证

1. **数据层验证**：54 个 supplement upgrade 的 EffectArray 正确性
   - 用 sc2-galaxy-toolkit 静态分析检查 upgrade 定义
   - 与原版 PrimaryUpgrade 对比，确认只包含优点
2. **配置层验证**：WebUI → launcher → bank 链路
   - 手动调用 launcher `-Buffs "P1,P3" -Masteries "30,30,30,0,0,0" -EnableBuffPatch`
   - 检查生成的 bank XML 字段正确
3. **应用层验证**：galaxy 读取 bank 并应用
   - 进图检查单位属性是否正确（如 Marine 生命值是否 +100%）

### 集成验证

1. 选择 Raynor + 启用 P1 优点 → 进图检查 Marine 生命值
2. 选择 Mengsk + 启用 P1 优点 → 进图检查火炮 CD
3. 调整精通点数为 0 → 进图检查精通效果消失
4. 不启用 buff 补丁 → 进图检查原版行为不变

### 兼容性验证

1. 与原版威望选择兼容（玩家选 P1 + 启用 P1 优点 → 效果叠加，符合预期）
2. 与起义指挥官兼容（Alenger 系列不启用 buff 补丁，`CMUIX_GetPrestigeBonusUpgrade` 返回空字符串）
3. 与突变因子兼容（buff 补丁不影响突变因子逻辑）

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| 威望优点提取错误（误把缺点当优点） | 用海克斯 PVP 定义交叉验证 + 人工审核疑难项 |
| supplement upgrade 与原版威望叠加导致过强 | 这是预期行为（用户选择"保留原版+可选开关"） |
| galaxy 修改侵入 cmui_customization.galaxy | 只在函数末尾追加一行调用，不修改原有逻辑 |
| bank 字段与原版 mastery 冲突 | buff 补丁的 mastery 覆盖后执行，明确文档说明 |
| 54 个 supplement upgrade 工作量大 | 首期可先做 3-5 个指挥官验证流程，再扩展 |

## 依赖

- `commander-power-metadata.json`：威望/精通元数据（已有）
- `UpgradeData.xml`（CMRE_Core_Base/Mengsk/Stetmann）：原版 EffectArray 数据（已有）
- 海克斯 PVP mod：交叉验证参考（已有）
- `cmui_customization.galaxy`：galaxy 修改点（已有）
- `launch-cmre-alenger.ps1`：launcher 修改点（已有）
- `server.py` + WebUI 前端：WebUI 修改点（已有）

## 后续扩展

1. **海克斯 PVP 天赋集成**：在 `CMRE_BuffPatch.SC2Mod` 中新增 `TalentXxx` upgrade，galaxy 中新增 `CMUIX_ApplyTalent` dispatch
2. **起义指挥官 buff**：Alenger 系列也加类似 buff 补丁
3. **buff 预设方案**：WebUI 上保存/加载 buff 配置方案
4. **动态天赋选择**：游戏内 UI 面板选择（类似海克斯 PVP）
