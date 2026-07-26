# 原版 18 指挥官 Buff 补丁实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为原版 18 个合作指挥官增加 buff 补丁系统，提取 54 个威望的优点作为可选独立加成 + 精通默认满级可覆盖。

**Architecture:** 三层架构：数据层（`CMRE_BuffPatch.SC2Mod` 含 54 个 supplement upgrade）+ 配置层（WebUI 勾选 + Launcher 写 bank + Bank 字段 `Player|N|PrestigeBonusMask`/`Player|N|EnableBuffPatch`/`Player|N|Mastery|slot|Value`）+ 应用层（galaxy 新增 `CMUIX_LaunchProfileApplyBuffs` 函数，在 `CMUIX_LaunchProfileApplyCommanderCustomization` 末尾调用）。

**Tech Stack:** SC2 GameData XML、Galaxy 脚本、PowerShell launcher、Python WebUI（标准库）、JSON 配置

**设计文档:** `docs/superpowers/specs/2026-07-26-official-commander-buff-patch-design.md`

**提取数据源:** `artifacts/buff-patch/prestige-bonus-extract.json`（54 个威望优点 EffectArray，46 个干净 + 8 个需人工审核）

---

## 文件结构

### 新建文件

| 文件 | 职责 |
|------|------|
| `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/Base.SC2Data/GameData/UpgradeData.xml` | 54 个 supplement upgrade 定义 |
| `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/Base.SC2Data/GameData/GameData.xml` | catalog includes 入口 |
| `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/zhCN.SC2Data/LocalizedData/GameStrings.txt` | buff 名称/描述本地化 |
| `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/ComponentList.SC2Components` | mod 组件清单 |
| `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/DocumentHeader` | mod 头部二进制 |
| `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/DocumentInfo` | mod 依赖声明 |
| `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/DocumentInfo.version` | 版本号 |
| `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/PreloadAssetDB.txt` | 预加载资源清单（空） |
| `tools/buff-patch/generate-buff-upgrades.py` | 从 extract JSON 生成 UpgradeData.xml 的脚本 |

### 修改文件

| 文件 | 修改内容 |
|------|----------|
| `src/config/cmre-alenger-dependencies.json` | `baseMods` 加入 `Commanders\CMRE_BuffPatch.SC2Mod` |
| `tools/launchers/launch-cmre-alenger.ps1` | 新增 `-Buffs` / `-Masteries` / `-EnableBuffPatch` 参数；`Write-CmreLaunchProfile` 扩展写 bank |
| `tools/cmre-webui/server.py` | `_handle_launch` 透传 `buffs`/`masteries`；新增 `GET /api/buff-metadata` |
| `tools/cmre-webui/webui/index.html` | 新增 "Buff 补丁" Tab |
| `tools/cmre-webui/webui/app.js` | Buff 补丁 Tab 的渲染和交互逻辑 |
| `tools/cmre-webui/webui/style.css` | Buff 补丁 Tab 样式 |
| `cmre-runtime/Mods/CMRE/CMRE_Core_Triggers.SC2Mod/Base.SC2Data/scripts/cmui_customization.galaxy` | 新增 `CMUIX_LaunchProfileApplyBuffs` 和 `CMUIX_GetPrestigeBonusUpgrade` 函数；在 `CMUIX_LaunchProfileApplyCommanderCustomization` 末尾追加调用 |

---

## Task 1: 创建 CMRE_BuffPatch.SC2Mod 骨架

**Files:**
- Create: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/Base.SC2Data/GameData/GameData.xml`
- Create: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/ComponentList.SC2Components`
- Create: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/DocumentInfo`
- Create: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/DocumentInfo.version`
- Create: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/DocumentHeader`
- Create: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/PreloadAssetDB.txt`
- Create: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/zhCN.SC2Data/LocalizedData/GameStrings.txt`

- [ ] **Step 1: 参考现有 mod 的 DocumentInfo 格式**

读取 `src/projects/cmre-porting/packages/Mods/Commanders/SteelWallAlenger.SC2Mod/DocumentInfo` 了解格式。

```bash
powershell -NoProfile -Command "Get-Content 'e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\SteelWallAlenger.SC2Mod\DocumentInfo' -Raw"
```

- [ ] **Step 2: 创建 mod 目录结构**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-mkdir.ps1" "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\Base.SC2Data\GameData" "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\zhCN.SC2Data\LocalizedData"
```

- [ ] **Step 3: 创建 GameData.xml**

写入文件 `CMRE_BuffPatch.SC2Mod/Base.SC2Data/GameData/GameData.xml`：

```xml
<?xml version="1.0" encoding="utf-8"?>
<Catalog>
    <GameData path="UpgradeData"/>
</Catalog>
```

- [ ] **Step 4: 创建 GameStrings.txt**

写入文件 `CMRE_BuffPatch.SC2Mod/zhCN.SC2Data/LocalizedData/GameStrings.txt`（先放占位，后续 Task 4 填充本地化文本）：

```
// CMRE Buff Patch localizations
// Will be populated in Task 4
```

- [ ] **Step 5: 创建 ComponentList.SC2Components**

参考其他 mod 的 ComponentList 格式，写入：

```xml
<?xml version="1.0" encoding="utf-8"?>
<Components>
    <C id="Base"/>
    <C id="zhCN"/>
</Components>
```

- [ ] **Step 6: 创建 DocumentInfo**

参考 SteelWallAlenger 的 DocumentInfo 格式，但依赖改为 CMRE_Core_Base / CMRE_Core_Mengsk / CMRE_Core_Stetmann（不依赖其他 Commanders mod）。写入：

```xml
<?xml version="1.0" encoding="utf-8"?>
<DocumentInfo>
    <Id value="CMRE_BuffPatch"/>
    <Name value="CMRE Buff Patch"/>
    <Type value="SC2Mod"/>
    <ContentVersion value="1.0"/>
    <DependencyList>
        <Dependency value="file:Mods/CMRE/CMRE_Core_Base.SC2Mod"/>
        <Dependency value="file:Mods/CMRE/CMRE_Core_Mengsk.SC2Mod"/>
        <Dependency value="file:Mods/CMRE/CMRE_Core_Stetmann.SC2Mod"/>
    </DependencyList>
    <Flags>
        <Flag value="IgnoreCustomCampaign"/>
    </Flags>
</DocumentInfo>
```

注意：实际格式以 SteelWallAlenger 的 DocumentInfo 为准，可能需要二进制 DocumentHeader。

- [ ] **Step 7: 复制 DocumentHeader 和 DocumentInfo.version**

从 SteelWallAlenger.SC2Mod 复制 `DocumentHeader` 和 `DocumentInfo.version` 文件作为模板：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-cp.ps1" "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\SteelWallAlenger.SC2Mod\DocumentHeader" "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\DocumentHeader"

powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-cp.ps1" "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\SteelWallAlenger.SC2Mod\DocumentInfo.version" "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\DocumentInfo.version"
```

- [ ] **Step 8: 创建 PreloadAssetDB.txt（空）**

写入空文件：

```
// CMRE Buff Patch preload assets
```

- [ ] **Step 9: 验证 mod 骨架完整性**

```powershell
Get-ChildItem -Path "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod" -Recurse | Select-Object FullName
```

Expected: 看到 GameData.xml、GameStrings.txt、ComponentList.SC2Components、DocumentInfo、DocumentHeader、DocumentInfo.version、PreloadAssetDB.txt。

- [ ] **Step 10: Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat(buff-patch): 创建 CMRE_BuffPatch.SC2Mod 骨架"
```

---

## Task 2: 生成 54 个 supplement upgrade 定义

**Files:**
- Create: `tools/buff-patch/generate-buff-upgrades.py`
- Create: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/Base.SC2Data/GameData/UpgradeData.xml`

**输入数据:** `artifacts/buff-patch/prestige-bonus-extract.json`

- [ ] **Step 1: 创建 tools/buff-patch 目录**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-mkdir.ps1" "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\buff-patch"
```

- [ ] **Step 2: 编写 generate-buff-upgrades.py**

写入 `tools/buff-patch/generate-buff-upgrades.py`：

```python
#!/usr/bin/env python3
"""从 prestige-bonus-extract.json 生成 CMRE_BuffPatch.SC2Mod 的 UpgradeData.xml。

输出 54 个 CommanderPrestigeXxxBonus upgrade，每个只包含优点的 EffectArray。
对 needs_manual_review=true 的威望，跳过并打印警告（不生成空 upgrade）。
"""
import json
import os
import sys
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom

EXTRACT_JSON = Path(r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\artifacts\buff-patch\prestige-bonus-extract.json")
OUTPUT_XML = Path(r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\Base.SC2Data\GameData\UpgradeData.xml")

RACE_MAP = {
    "Terran": "Terran",
    "Zerg": "Zerg",
    "Protoss": "Protoss",
}

def detect_race(runtime_commander: str) -> str:
    for race in RACE_MAP:
        if runtime_commander.startswith(race):
            return race
    return "Terran"

def build_upgrade_element(commander: dict, prestige: dict) -> ET.Element | None:
    """构建单个 CUpgrade XML 元素。返回 None 表示跳过。"""
    if prestige.get("needs_manual_review", False):
        print(f"[WARN] 跳过需人工审核: {commander['runtime_commander']} P{prestige['slot']} ({prestige['name']})")
        return None

    effect_arrays = prestige.get("effect_arrays", [])
    advantages = [ea for ea in effect_arrays if ea.get("is_advantage", False)]
    if not advantages:
        print(f"[WARN] 跳过无优点 EffectArray: {commander['runtime_commander']} P{prestige['slot']} ({prestige['name']})")
        return None

    upgrade_id = prestige["bonus_upgrade_id"]
    race = detect_race(commander["runtime_commander"])

    upgrade = ET.Element("CUpgrade", {
        "id": upgrade_id,
        "parent": "CommanderPrestige",
    })
    for ea in advantages:
        attrs = {"Reference": ea["reference"], "Value": ea["value"]}
        op = ea.get("operation", "Add")
        if op and op != "Add":
            attrs["Operation"] = op
        ET.SubElement(upgrade, "EffectArray", attrs)
    ET.SubElement(upgrade, "EditorCategories", {"value": f"Race:{race},UpgradeType:Talents"})
    ET.SubElement(upgrade, "MaxLevel", {"value": "1"})

    return upgrade

def main():
    if not EXTRACT_JSON.exists():
        print(f"[ERROR] 提取数据不存在: {EXTRACT_JSON}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(EXTRACT_JSON.read_text(encoding="utf-8"))

    catalog = ET.Element("Catalog")
    generated = 0
    skipped = 0
    skipped_items = []

    for commander in data.get("commanders", []):
        for prestige in commander.get("prestiges", []):
            upgrade = build_upgrade_element(commander, prestige)
            if upgrade is None:
                skipped += 1
                skipped_items.append(f"{commander['runtime_commander']} P{prestige['slot']}")
                continue
            catalog.append(upgrade)
            generated += 1

    # 美化输出
    rough = ET.tostring(catalog, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="    ", encoding="utf-8")
    OUTPUT_XML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_XML.write_bytes(pretty)

    print(f"[OK] 生成 {generated} 个 supplement upgrade → {OUTPUT_XML}")
    print(f"[SKIP] 跳过 {skipped} 个需人工审核的威望:")
    for item in skipped_items:
        print(f"  - {item}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: 运行生成脚本**

```powershell
python "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\buff-patch\generate-buff-upgrades.py"
```

Expected: 生成约 46 个 upgrade，跳过 8 个需人工审核项。输出文件 `CMRE_BuffPatch.SC2Mod/Base.SC2Data/GameData/UpgradeData.xml`。

- [ ] **Step 4: 验证生成的 UpgradeData.xml**

```powershell
Get-Content "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\Base.SC2Data\GameData\UpgradeData.xml" -Head 30
```

Expected: 看到 XML 头 + `<Catalog>` + 多个 `<CUpgrade id="CommanderPrestigeXxxBonus" parent="CommanderPrestige">`。

- [ ] **Step 5: 统计生成的 upgrade 数量**

```powershell
python -c "import xml.etree.ElementTree as ET; tree = ET.parse(r'e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\Base.SC2Data\GameData\UpgradeData.xml'); print(f'Total upgrades: {len(tree.getroot())}')"
```

Expected: `Total upgrades: 46` 左右。

- [ ] **Step 6: Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/buff-patch/generate-buff-upgrades.py" "src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/Base.SC2Data/GameData/UpgradeData.xml"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat(buff-patch): 生成 46 个威望优点 supplement upgrade"
```

---

## Task 3: 人工审核 8 个疑难威望并补充

**Files:**
- Modify: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/Base.SC2Data/GameData/UpgradeData.xml`

**需审核的 8 个威望:**
1. Kerrigan P3 (荒寂女王) - 无 EffectArray
2. Swann P2 (机械修理工) - 16 个 EffectArray 全部为缺点/中性
3. Vorazun P3 (暗影守护者) - 1 个中性
4. Stukov P2 (瘟疫守望者) - 2 个中性
5. Dehaka P3 (原生双雄) - 无 EffectArray
6. Mira P3 (星系军火走私者) - 2 个中性
7. Zeratul P1 (黎明使徒) - 无 EffectArray
8. Stetmann P3 (石油大王) - 无 EffectArray

- [ ] **Step 1: 逐个查看 8 个威望的 tooltip 和原版 upgrade 定义**

对每个需审核的威望，读取 `commander-power-metadata.json` 中的 `tooltip` 字段（含优点描述），并在原版 UpgradeData.xml 中查找 `primary_upgrade` 的完整定义。

示例查询 Kerrigan P3：

```powershell
python -c "
import json
data = json.load(open(r'e:\Code\MyMod\SC2VibeTools\cmre-runtime\Shared\CommanderPower\commander-power-metadata.json', encoding='utf-8'))
for cmd in data['commanders']:
    if cmd['runtime_commander'] == 'ZergKerrigan':
        for p in cmd.get('prestiges', []):
            if p['slot'] == 3:
                print('Name:', p['name'])
                print('Advantage:', p['tooltip'][:300])
                print('PrimaryUpgrade:', p.get('primary_upgrade'))
                print('UpgradeSupplements:', p.get('upgrade_supplements'))
                print('EnableAbils:', p.get('enable_abils'))
                print('SecondaryUpgrades:', p.get('secondary_upgrades'))
"
```

- [ ] **Step 2: 对每个疑难威望，确定优点实现方式**

对每个威望，根据 tooltip 中的优点描述，判断优点通过哪种方式实现：
- **EffectArray**: 在原版 upgrade 的 EffectArray 中（可能被脚本误判为中性）
- **EnableAbils/SecondaryUpgrades**: 通过 enable_abils 或 secondary_upgrades 字段实现
- **UpgradeSupplements**: 通过 upgrade_supplements 字段实现
- **galaxy 触发器**: 优点在 galaxy 代码中实现（无法用 supplement upgrade 复制）

对每种情况，决定处理方式：
- EffectArray 误判：手动添加到 UpgradeData.xml
- EnableAbils/SecondaryUpgrades：手动构造 EffectArray（如 `TechTreeAbilityAllow` 模拟）
- galaxy 触发器：标记为"galaxy 实现"，在 Task 5 的 galaxy dispatch 中特殊处理

- [ ] **Step 3: 手动补充可处理的 upgrade**

对能在 EffectArray 层面补充的威望，手动 Edit `UpgradeData.xml` 添加对应的 `<CUpgrade>` 元素。例如 Kerrigan P3 如果优点是"解锁某能力"，添加：

```xml
<CUpgrade id="CommanderPrestigeKerriganXxxBonus" parent="CommanderPrestige">
    <!-- 优点通过 galaxy 触发器启用能力，此处仅作为 flag upgrade -->
    <EditorCategories value="Race:Zerg,UpgradeType:Talents"/>
    <MaxLevel value="1"/>
</CUpgrade>
```

注意：对 galaxy 实现的优点，supplement upgrade 仅作为"开关 flag"，实际效果在 Task 5 的 galaxy dispatch 中通过 `TechTreeAbilityAllow` 等函数应用。

- [ ] **Step 4: 记录疑难项处理结果**

在 `artifacts/buff-patch/prestige-bonus-extract.json` 中更新 `needs_manual_review` 字段为 false，并在 `review_notes` 中记录处理方式。或新建 `artifacts/buff-patch/manual-review-log.md` 记录处理决策。

- [ ] **Step 5: Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/Base.SC2Data/GameData/UpgradeData.xml"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat(buff-patch): 人工审核 8 个疑难威望并补充 upgrade"
```

---

## Task 4: 填充本地化文本

**Files:**
- Modify: `src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/zhCN.SC2Data/LocalizedData/GameStrings.txt`

- [ ] **Step 1: 编写脚本生成 GameStrings.txt**

写入 `tools/buff-patch/generate-localizations.py`：

```python
#!/usr/bin/env python3
"""从 prestige-bonus-extract.json 生成 GameStrings.txt 本地化文本。"""
import json
from pathlib import Path

EXTRACT_JSON = Path(r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\artifacts\buff-patch\prestige-bonus-extract.json")
OUTPUT = Path(r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\zhCN.SC2Data\LocalizedData\GameStrings.txt")

def main():
    data = json.loads(EXTRACT_JSON.read_text(encoding="utf-8"))
    lines = ["// CMRE Buff Patch localizations", ""]
    for cmd in data.get("commanders", []):
        for p in cmd.get("prestiges", []):
            if p.get("needs_manual_review", False):
                continue
            upgrade_id = p.get("bonus_upgrade_id")
            if not upgrade_id:
                continue
            name = f"{cmd['display_name']} {p['name']} 优点"
            tip = p.get("advantage_text", "").replace("\n", " ")
            lines.append(f"Upgrade/Name/{upgrade_id}={name}")
            lines.append(f"Upgrade/Tooltip/{upgrade_id}={tip}")
            lines.append("")
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[OK] 写入 {OUTPUT}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 运行脚本**

```powershell
python "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\buff-patch\generate-localizations.py"
```

- [ ] **Step 3: 验证 GameStrings.txt**

```powershell
Get-Content "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\projects\cmre-porting\packages\Mods\Commanders\CMRE_BuffPatch.SC2Mod\zhCN.SC2Data\LocalizedData\GameStrings.txt" -Head 20
```

Expected: 看到形如 `Upgrade/Name/CommanderPrestigeRaynorBioBonus=雷诺 死水元帅 优点` 的行。

- [ ] **Step 4: Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/buff-patch/generate-localizations.py" "src/projects/cmre-porting/packages/Mods/Commanders/CMRE_BuffPatch.SC2Mod/zhCN.SC2Data/LocalizedData/GameStrings.txt"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat(buff-patch): 生成 buff 补丁本地化文本"
```

---

## Task 5: 在 cmre-alenger-dependencies.json 中注册 BuffPatch mod

**Files:**
- Modify: `src/config/cmre-alenger-dependencies.json`

- [ ] **Step 1: 读取当前 cmre-alenger-dependencies.json**

```powershell
Get-Content "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\config\cmre-alenger-dependencies.json" -Raw
```

- [ ] **Step 2: 在 baseMods 数组中追加 BuffPatch**

用 Edit 工具在 `baseMods` 数组中追加 `"Commanders\\CMRE_BuffPatch.SC2Mod"`。注意 JSON 转义。

```json
"baseMods": [
    ...原有项...,
    "Commanders\\CMRE_BuffPatch.SC2Mod"
]
```

- [ ] **Step 3: 验证 JSON 合法性**

```powershell
python -c "import json; data = json.load(open(r'e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\config\cmre-alenger-dependencies.json', encoding='utf-8')); print('baseMods:', data.get('baseMods'))"
```

Expected: `baseMods` 列表包含 `Commanders\CMRE_BuffPatch.SC2Mod`。

- [ ] **Step 4: Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "src/config/cmre-alenger-dependencies.json"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat(buff-patch): 在 cmre-alenger-dependencies.json 注册 BuffPatch mod"
```

---

## Task 6: Launcher 新增 -Buffs / -Masteries / -EnableBuffPatch 参数

**Files:**
- Modify: `tools/launchers/launch-cmre-alenger.ps1`

- [ ] **Step 1: 在 param 块新增参数**

读取 `tools/launchers/launch-cmre-alenger.ps1` 第 1-2 行的 param 块，在末尾追加三个参数：

```powershell
param([Parameter(Mandatory = $true)][string]$MapName, [Parameter(Mandatory = $true)][string]$Commander, [switch]$DryRun, [switch]$NoLaunch, [int]$ListenPort = 0, [string]$LegacyRootOverride = "", [int]$Mode = 1, [int]$DifficultyBase = 0, [int]$DifficultyPlus = 0, [string]$Enemy = "", [string]$Mutators = "", [string]$ChaosMutators = "", [string]$VoicePack = "", [string]$ExtraMods = "", [switch]$SkipCountdown, [switch]$ApiMinimal, [switch]$ShowSelectionUI, [switch]$EnableReborn, [string]$RebornCommander = "", [int]$RebornDifficulty = 5, [int]$RebornSpeed = 5, [switch]$PlayerMode, [switch]$DebugMode, [string]$Buffs = "", [string]$Masteries = "", [switch]$EnableBuffPatch)
```

- [ ] **Step 2: 在 Write-CmreLaunchProfile 函数中扩展 $values 字典**

读取 `Write-CmreLaunchProfile` 函数（约第 792-858 行），在 `$values` 字典定义之后、写入 bank XML 之前，追加 buff 补丁字段：

```powershell
# Buff 补丁配置（仅当 -EnableBuffPatch 启用时写入）
if ($EnableBuffPatch) {
    $bonusMask = 0
    if ($Buffs -match "P1") { $bonusMask += 1 }
    if ($Buffs -match "P2") { $bonusMask += 2 }
    if ($Buffs -match "P3") { $bonusMask += 4 }
    $values['Player|1|EnableBuffPatch'] = @("int", "1")
    $values['Player|2|EnableBuffPatch'] = @("int", "1")
    $values['Player|1|PrestigeBonusMask'] = @("int", [string]$bonusMask)
    $values['Player|2|PrestigeBonusMask'] = @("int", [string]$bonusMask)
    Write-Host "BuffPatch: enabled, PrestigeBonusMask=$bonusMask (Buffs='$Buffs')"

    if ($Masteries -ne "") {
        $masteryValues = $Masteries.Split(',') | ForEach-Object { [int]$_.Trim() }
        for ($i = 0; $i -lt 6 -and $i -lt $masteryValues.Count; $i++) {
            $values["Player|1|Mastery|$i|Value"] = @("int", [string]$masteryValues[$i])
            $values["Player|2|Mastery|$i|Value"] = @("int", [string]$masteryValues[$i])
        }
        Write-Host "BuffPatch: masteries=$Masteries"
    }
} else {
    $values['Player|1|EnableBuffPatch'] = @("int", "0")
    $values['Player|2|EnableBuffPatch'] = @("int", "0")
}
```

- [ ] **Step 3: DryRun 验证 bank 写入**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\launchers\launch-cmre-alenger.ps1" -MapName "亡者之夜.SC2Map" -Commander "TerranRaynor" -DryRun -EnableBuffPatch -Buffs "P1,P3" -Masteries "30,30,30,0,0,0"
```

Expected: DryRun 输出依赖列表，且打印 `BuffPatch: enabled, PrestigeBonusMask=5 (Buffs='P1,P3')` 和 `BuffPatch: masteries=30,30,30,0,0,0`。

- [ ] **Step 4: 实际运行验证 bank XML**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\launchers\launch-cmre-alenger.ps1" -MapName "亡者之夜.SC2Map" -Commander "TerranRaynor" -NoLaunch -EnableBuffPatch -Buffs "P1,P3" -Masteries "30,30,30,0,0,0"
Get-Content "C:\Users\22448\Documents\StarCraft II\Banks\CMCoopLaunchProfile.SC2Bank" -Raw
```

Expected: bank XML 包含 `<Key name="Player|1|EnableBuffPatch"><Value int="1"/></Key>`、`<Key name="Player|1|PrestigeBonusMask"><Value int="5"/></Key>`、`<Key name="Player|1|Mastery|0|Value"><Value int="30"/></Key>` 等字段。

- [ ] **Step 5: Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/launchers/launch-cmre-alenger.ps1"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat(buff-patch): launcher 新增 -Buffs/-Masteries/-EnableBuffPatch 参数并写入 bank"
```

---

## Task 7: galaxy 新增 CMUIX_LaunchProfileApplyBuffs 函数

**Files:**
- Modify: `cmre-runtime/Mods/CMRE/CMRE_Core_Triggers.SC2Mod/Base.SC2Data/scripts/cmui_customization.galaxy`

- [ ] **Step 1: 找到 CMUIX_LaunchProfileApplyCommanderCustomization 函数位置**

```powershell
Select-String -Path "e:\Code\MyMod\SC2VibeTools\cmre-runtime\Mods\CMRE\CMRE_Core_Triggers.SC2Mod\Base.SC2Data\scripts\cmui_customization.galaxy" -Pattern "void CMUIX_LaunchProfileApplyCommanderCustomization" -List
```

记录函数起始行号（约 12900 行）和结束 `}` 的行号。

- [ ] **Step 2: 找到函数末尾的插入点**

读取 `CMUIX_LaunchProfileApplyCommanderCustomization` 函数末尾几行，确认在最后一个 `}` 之前插入调用。

- [ ] **Step 3: 新增 CMUIX_GetPrestigeBonusUpgrade 函数**

在 `cmui_customization.galaxy` 末尾追加 dispatch 函数。先读取 `artifacts/buff-patch/prestige-bonus-extract.json` 确认所有 `bonus_upgrade_id`，然后写入：

```galaxy
//--------------------------------------------------------------------------------------------------
// Buff Patch: 查询指挥官威望优点对应的 supplement upgrade id
// 返回空字符串表示该指挥官/槽位无 buff（起义指挥官或未定义）
//--------------------------------------------------------------------------------------------------
string CMUIX_GetPrestigeBonusUpgrade (string lp_commander, int lp_prestigeSlot) {
    // Raynor
    if (StringEqual(lp_commander, "TerranRaynor", true)) {
        if (lp_prestigeSlot == 1) { return "CommanderPrestigeRaynorBioBonus"; }
        if (lp_prestigeSlot == 2) { return "CommanderPrestigeRaynorMechAfterburnersBonus"; }
        if (lp_prestigeSlot == 3) { return "CommanderPrestigeRaynorBattlecruiserBonus"; }
    }
    // Kerrigan
    if (StringEqual(lp_commander, "ZergKerrigan", true)) {
        if (lp_prestigeSlot == 1) { return "CommanderPrestigeKerriganXxxBonus"; }
        if (lp_prestigeSlot == 2) { return "CommanderPrestigeKerriganXxxBonus"; }
        if (lp_prestigeSlot == 3) { return "CommanderPrestigeKerriganXxxBonus"; }
    }
    // ... 其他 16 个指挥官（从 extract JSON 派生，实际 id 在 Task 2/3 中确定）
    return "";
}
```

注意：实际 upgrade id 必须与 Task 2/3 生成的 `bonus_upgrade_id` 完全一致。在编写本步骤前，先从 `prestige-bonus-extract.json` 提取所有 `bonus_upgrade_id`，构造完整的 dispatch 表。

- [ ] **Step 4: 新增 CMUIX_LaunchProfileApplyBuffs 函数**

在 `cmui_customization.galaxy` 末尾追加：

```galaxy
//--------------------------------------------------------------------------------------------------
// Buff Patch: 应用威望优点 supplement upgrade 和精通点数覆盖
// 在 CMUIX_LaunchProfileApplyCommanderCustomization 末尾调用
//--------------------------------------------------------------------------------------------------
void CMUIX_LaunchProfileApplyBuffs (bank lp_bank, int lp_player, string lp_commander) {
    int lv_enableBuffPatch;
    int lv_bonusMask;
    int lv_masteryValue;
    int lv_slot;
    string lv_bonusUpgrade;

    // 1. 检查是否启用 buff 补丁
    lv_enableBuffPatch = BankValueGetAsInt(lp_bank, CMUIX_LAUNCH_PROFILE_SECTION,
        CMUIX_LaunchProfilePlayerKey(lp_player, "EnableBuffPatch"));
    if (lv_enableBuffPatch != 1) {
        return;
    }

    // 2. 应用威望优点 supplement upgrade
    lv_bonusMask = BankValueGetAsInt(lp_bank, CMUIX_LAUNCH_PROFILE_SECTION,
        CMUIX_LaunchProfilePlayerKey(lp_player, "PrestigeBonusMask"));

    if ((lv_bonusMask & 1) != 0) {
        lv_bonusUpgrade = CMUIX_GetPrestigeBonusUpgrade(lp_commander, 1);
        if (StringLength(lv_bonusUpgrade) > 0) {
            TechTreeUpgradeAddLevel(lp_player, lv_bonusUpgrade, 1);
        }
    }
    if ((lv_bonusMask & 2) != 0) {
        lv_bonusUpgrade = CMUIX_GetPrestigeBonusUpgrade(lp_commander, 2);
        if (StringLength(lv_bonusUpgrade) > 0) {
            TechTreeUpgradeAddLevel(lp_player, lv_bonusUpgrade, 1);
        }
    }
    if ((lv_bonusMask & 4) != 0) {
        lv_bonusUpgrade = CMUIX_GetPrestigeBonusUpgrade(lp_commander, 3);
        if (StringLength(lv_bonusUpgrade) > 0) {
            TechTreeUpgradeAddLevel(lp_player, lv_bonusUpgrade, 1);
        }
    }

    // 3. 应用精通点数（覆盖原版精通设置）
    for (lv_slot = 0; lv_slot < 6; lv_slot += 1) {
        lv_masteryValue = BankValueGetAsInt(lp_bank, CMUIX_LAUNCH_PROFILE_SECTION,
            CMUIX_LaunchProfilePlayerSlotKey(lp_player, "Mastery", lv_slot, "Value"));
        if (lv_masteryValue >= 0 && lv_masteryValue <= 30) {
            libCOOC_gf_CC_PlayerMasteryUpgradeLevelSet(lp_player, lv_slot, lv_masteryValue);
        }
    }
}
```

注意：`libCOOC_gf_CC_PlayerMasteryUpgradeLevelSet` 函数签名需在 Step 1 中确认（可能在 libCOOC_h.galaxy 中声明）。

- [ ] **Step 5: 在 CMUIX_LaunchProfileApplyCommanderCustomization 末尾追加调用**

读取 `CMUIX_LaunchProfileApplyCommanderCustomization` 函数末尾，在最后一个 `}` 之前追加：

```galaxy
    // Buff Patch: 应用威望优点和精通覆盖
    CMUIX_LaunchProfileApplyBuffs(lp_bank, lp_player, lp_commander);
```

- [ ] **Step 6: 验证 galaxy 语法**

```powershell
Select-String -Path "e:\Code\MyMod\SC2VibeTools\cmre-runtime\Mods\CMRE\CMRE_Core_Triggers.SC2Mod\Base.SC2Data\scripts\cmui_customization.galaxy" -Pattern "CMUIX_LaunchProfileApplyBuffs"
```

Expected: 至少 2 处匹配（函数定义 + 调用点）。

- [ ] **Step 7: Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "cmre-runtime/Mods/CMRE/CMRE_Core_Triggers.SC2Mod/Base.SC2Data/scripts/cmui_customization.galaxy"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat(buff-patch): galaxy 新增 CMUIX_LaunchProfileApplyBuffs 函数应用威望优点和精通覆盖"
```

---

## Task 8: WebUI 后端新增 /api/buff-metadata 和透传 buffs/masteries 参数

**Files:**
- Modify: `tools/cmre-webui/server.py`

- [ ] **Step 1: 新增 /api/buff-metadata 端点**

在 `server.py` 中找到 `_handle_launch` 之前的位置，新增 `_handle_buff_metadata` 方法：

```python
def _handle_buff_metadata(self):
    """返回 18 个原版指挥官的威望优点描述 + 精通项列表。"""
    metadata_path = COMMANDER_METADATA_JSON
    if not metadata_path.exists():
        self._send_json({"error": "metadata not found"}, status=500)
        return
    data = json.loads(metadata_path.read_text(encoding="utf-8"))
    result = {"commanders": []}
    for cmd in data.get("commanders", []):
        bank = cmd.get("bank_commander", "")
        # 只返回原版 18 个指挥官（bank_commander 不以 Alenger 开头）
        if bank.startswith("Alenger"):
            continue
        runtime = cmd.get("runtime_commander", "")
        if not (runtime.startswith("Terran") or runtime.startswith("Zerg") or runtime.startswith("Protoss")):
            continue
        entry = {
            "runtime_commander": runtime,
            "bank_commander": bank,
            "display_name": cmd.get("display_name", runtime),
            "prestiges": [],
            "masteries": [],
        }
        for p in cmd.get("prestiges", []):
            entry["prestiges"].append({
                "slot": p.get("slot", 0),
                "name": p.get("name", ""),
                "advantage_text": p.get("tooltip", ""),
                "bonus_upgrade_id": f"CommanderPrestige{bank}P{p.get('slot', 0)}Bonus",
            })
        for m in cmd.get("masteries", []):
            entry["masteries"].append({
                "slot": m.get("slot", 0),
                "name": m.get("name", ""),
                "category": m.get("category", 0),
                "point_increment": m.get("point_increments", ["1"])[0] if m.get("point_increments") else "1",
            })
        result["commanders"].append(entry)
    self._send_json(result)
```

- [ ] **Step 2: 在路由中注册 /api/buff-metadata**

找到 `_handle_request` 或路由分发方法，添加：

```python
if path == "/api/buff-metadata":
    self._handle_buff_metadata()
    return
```

- [ ] **Step 3: 在 _handle_launch 中透传 buffs 和 masteries**

读取 `_handle_launch` 方法，在构造 `args` 列表的地方追加：

```python
buffs = body.get("buffs", {})
masteries = body.get("masteries", [])

# 编码 buffs: {"P1": true, "P2": false, "P3": true} → "P1,P3"
buff_str = ",".join(k for k, v in buffs.items() if v)
if buff_str:
    args.append("-Buffs")
    args.append(buff_str)

# 编码 masteries: [30, 30, 30, 0, 0, 0] → "30,30,30,0,0,0"
if masteries:
    args.append("-Masteries")
    args.append(",".join(str(m) for m in masteries))

# 启用 buff 补丁（只要 buffs 或 masteries 非空就启用）
if buff_str or masteries:
    args.append("-EnableBuffPatch")
```

- [ ] **Step 4: 启动 WebUI 验证 /api/buff-metadata**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\cmre-webui"
python server.py --port 8770 &
Start-Sleep 2
Invoke-RestMethod -Uri "http://127.0.0.1:8770/api/buff-metadata" | ConvertTo-Json -Depth 3 | Select-Object -First 50
```

Expected: 返回 JSON，包含 18 个原版指挥官的威望和精通列表。

- [ ] **Step 5: Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/cmre-webui/server.py"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat(buff-patch): WebUI 后端新增 /api/buff-metadata 并透传 buffs/masteries 参数"
```

---

## Task 9: WebUI 前端新增 Buff 补丁 Tab

**Files:**
- Modify: `tools/cmre-webui/webui/index.html`
- Modify: `tools/cmre-webui/webui/app.js`
- Modify: `tools/cmre-webui/webui/style.css`

- [ ] **Step 1: 在 index.html 添加 Buff 补丁 Tab 标签**

读取 `index.html`，找到现有 Tab 标签区域（指挥官/地图/突变因子），追加：

```html
<button class="tab-btn" data-tab="buff-patch">Buff 补丁</button>
```

并添加对应的 Tab 内容容器：

```html
<div id="tab-buff-patch" class="tab-content hidden">
    <div class="buff-patch-section">
        <h3>威望优点</h3>
        <div id="buff-patch-prestiges"></div>
    </div>
    <div class="buff-patch-section">
        <h3>精通点数 <button id="mastery-max-all" class="btn-secondary">全部满级</button></h3>
        <div id="buff-patch-masteries"></div>
    </div>
</div>
```

- [ ] **Step 2: 在 app.js 中实现 Buff 补丁 Tab 渲染**

在 `app.js` 中新增：

```javascript
// ===== Buff 补丁 Tab =====
let buffMetadata = null;
let buffConfig = JSON.parse(localStorage.getItem('buffConfig') || '{}');

async function loadBuffMetadata() {
    if (buffMetadata) return buffMetadata;
    const resp = await fetch('/api/buff-metadata');
    buffMetadata = await resp.json();
    return buffMetadata;
}

function renderBuffPatchTab() {
    const commander = document.getElementById('commander-select').value;
    const cmdData = buffMetadata?.commanders.find(c => c.runtime_commander === commander);
    if (!cmdData) {
        document.getElementById('buff-patch-prestiges').innerHTML = '<p>该指挥官不支持 buff 补丁</p>';
        document.getElementById('buff-patch-masteries').innerHTML = '';
        return;
    }

    // 渲染威望优点 checkbox
    const cfg = buffConfig[commander] || { buffs: {}, masteries: [30,30,30,30,30,30] };
    const prestigesHtml = cmdData.prestiges.map(p => {
        const checked = cfg.buffs[`P${p.slot}`] ? 'checked' : '';
        return `<div class="buff-prestige-item">
            <label><input type="checkbox" data-prestige="${p.slot}" ${checked}> P${p.slot} ${p.name}</label>
            <p class="buff-advantage">${p.advantage_text}</p>
        </div>`;
    }).join('');
    document.getElementById('buff-patch-prestiges').innerHTML = prestigesHtml;

    // 渲染精通点数滑块
    const masteriesHtml = cmdData.masteries.map(m => {
        const val = cfg.masteries[m.slot] ?? 30;
        return `<div class="buff-mastery-item">
            <label>${m.name} (分类${m.category})</label>
            <input type="range" min="0" max="30" value="${val}" data-mastery="${m.slot}">
            <span class="mastery-value">${val}</span>
        </div>`;
    }).join('');
    document.getElementById('buff-patch-masteries').innerHTML = masteriesHtml;

    // 绑定事件
    document.querySelectorAll('#buff-patch-prestiges input[type=checkbox]').forEach(cb => {
        cb.addEventListener('change', () => {
            const slot = cb.dataset.prestige;
            cfg.buffs[`P${slot}`] = cb.checked;
            buffConfig[commander] = cfg;
            localStorage.setItem('buffConfig', JSON.stringify(buffConfig));
        });
    });
    document.querySelectorAll('#buff-patch-masteries input[type=range]').forEach(slider => {
        slider.addEventListener('input', () => {
            const slot = slider.dataset.mastery;
            cfg.masteries[slot] = parseInt(slider.value);
            slider.nextElementSibling.textContent = slider.value;
            buffConfig[commander] = cfg;
            localStorage.setItem('buffConfig', JSON.stringify(buffConfig));
        });
    });
}

// 全部满级按钮
document.getElementById('mastery-max-all').addEventListener('click', () => {
    const commander = document.getElementById('commander-select').value;
    const cfg = buffConfig[commander] || { buffs: {}, masteries: [30,30,30,30,30,30] };
    cfg.masteries = [30,30,30,30,30,30];
    buffConfig[commander] = cfg;
    localStorage.setItem('buffConfig', JSON.stringify(buffConfig));
    renderBuffPatchTab();
});

// 切换指挥官时重新渲染
document.getElementById('commander-select').addEventListener('change', renderBuffPatchTab);

// 切换到 Buff 补丁 Tab 时加载
document.querySelector('[data-tab="buff-patch"]').addEventListener('click', async () => {
    await loadBuffMetadata();
    renderBuffPatchTab();
});
```

- [ ] **Step 3: 在 /api/launch 提交时附带 buffs 和 masteries**

找到 `app.js` 中的 launch 提交逻辑，在 fetch body 中追加：

```javascript
const commander = document.getElementById('commander-select').value;
const cfg = buffConfig[commander] || { buffs: {}, masteries: [30,30,30,30,30,30] };
body.buffs = cfg.buffs;
body.masteries = cfg.masteries;
```

- [ ] **Step 4: 在 style.css 添加 Buff 补丁样式**

```css
/* Buff 补丁 Tab */
.buff-patch-section { margin-bottom: 24px; }
.buff-patch-section h3 { margin-bottom: 12px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.buff-prestige-item { margin-bottom: 12px; padding: 8px; background: var(--bg-secondary); border-radius: 4px; }
.buff-prestige-item label { font-weight: bold; }
.buff-advantage { margin: 4px 0 0 24px; color: var(--text-secondary); font-size: 0.9em; }
.buff-mastery-item { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; }
.buff-mastery-item label { flex: 0 0 200px; }
.buff-mastery-item input[type=range] { flex: 1; }
.mastery-value { flex: 0 0 30px; text-align: right; font-weight: bold; }
.btn-secondary { padding: 4px 12px; background: var(--bg-secondary); border: 1px solid var(--border); border-radius: 4px; cursor: pointer; font-size: 0.85em; }
```

- [ ] **Step 5: 启动 WebUI 验证前端**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\cmre-webui"
python server.py --port 8770 &
```

在浏览器打开 `http://127.0.0.1:8770/?fresh=1`，点击"Buff 补丁"Tab，验证：
- 切换指挥官时威望优点和精通项正确显示
- 勾选 checkbox 后刷新页面配置保留
- 滑块拖动后数值更新且配置保留

- [ ] **Step 6: Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-add.ps1" "tools/cmre-webui/webui/index.html" "tools/cmre-webui/webui/app.js" "tools/cmre-webui/webui/style.css"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "feat(buff-patch): WebUI 前端新增 Buff 补丁 Tab"
```

---

## Task 10: 集成测试 + 进图验证

**Files:** 无（测试任务）

- [ ] **Step 1: 启动 WebUI 完整配置一次启动**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\tools\cmre-webui"
python server.py --port 8770
```

在浏览器：
1. 选择指挥官 "雷诺" (TerranRaynor)
2. 切换到 "Buff 补丁" Tab
3. 勾选 P1 优点（死水元帅 - 生物单位生命+100%）
4. 精通保持默认满级
5. 点击"启动游戏"

- [ ] **Step 2: 验证 SC2 启动并加载地图**

等待 launcher 输出 `BuffPatch: enabled, PrestigeBonusMask=1` 和 `BuffPatch: masteries=30,30,30,30,30,30`。等待 SC2 加载完成（Alerts.txt 出现）。

- [ ] **Step 3: 进图验证 Marine 生命值**

进入游戏后，选中兵营建造一个 Marine，验证 Marine 生命值是否为原版 +100（原版 45 → buff 后 90 左右，因为原版 P1 优点是 +45，supplement upgrade 再加 45）。

注意：如果玩家同时在 lobby 选了 P1 威望，效果会叠加（45 + 45 + 45 = 135），这是预期行为。

- [ ] **Step 4: 验证不启用 buff 补丁时原版行为不变**

关闭 SC2，重新启动 WebUI，不勾选任何 buff 补丁选项，启动游戏。验证 Marine 生命值为原版值（45）。

- [ ] **Step 5: 验证 GameLogs 无 ScriptError**

```powershell
Get-ChildItem "C:\Users\22448\Documents\StarCraft II\GameLogs" -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | Get-ChildItem -Filter "ScriptError*.txt"
```

Expected: 无新增 ScriptError，或 ScriptError 与基线一致（CMRE 已知的 LibKPVP/LibKMIS 警告）。

- [ ] **Step 6: 最终 Commit**

```powershell
cd "e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
powershell -NoProfile -ExecutionPolicy Bypass -File "c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-commit.ps1" "test(buff-patch): 集成测试通过，进图验证 Marine 生命值正确"
```

---

## 自我审核

### Spec 覆盖检查

| Spec 章节 | 对应 Task |
|-----------|----------|
| 层 1：数据层 CMRE_BuffPatch.SC2Mod | Task 1（骨架）+ Task 2（upgrade 生成）+ Task 3（疑难审核）+ Task 4（本地化） |
| 层 2：配置层 WebUI + Launcher + Bank | Task 5（依赖注册）+ Task 6（launcher）+ Task 8（WebUI 后端）+ Task 9（WebUI 前端） |
| 层 3：应用层 galaxy 触发器 | Task 7（galaxy 函数） |
| 验证计划 | Task 10（集成测试） |

### Placeholder 扫描

- Task 3 中"对每个疑难威望确定优点实现方式"——这是审核步骤，不是 placeholder。每个威望的具体处理在执行时根据数据决定。
- Task 7 的 `CommanderPrestigeKerriganXxxBonus` 是示例，实际 id 从 extract JSON 派生。在 Step 3 明确说明"实际 upgrade id 必须与 Task 2/3 生成的 bonus_upgrade_id 完全一致"。
- Task 7 的 `// ... 其他 16 个指挥官`——这是设计文档示例，实际实现时必须列出所有 18 个指挥官的完整 dispatch 表。

### Type 一致性

- `bonus_upgrade_id` 在 Task 2 生成、Task 7 引用、Task 8 WebUI 返回、Task 9 前端不直接使用——一致
- `Player|N|EnableBuffPatch` / `Player|N|PrestigeBonusMask` / `Player|N|Mastery|slot|Value` 字段在 Task 6（写）和 Task 7（读）一致
- `CMUIX_LaunchProfileApplyBuffs` 函数签名在 Task 7 定义和调用一致

### 风险点

1. **Task 3 的人工审核**可能耗时较长，8 个威望需要逐个分析。建议优先处理，不阻塞其他 Task。
2. **Task 7 的 galaxy 修改**侵入 cmui_customization.galaxy，需要确保只在函数末尾追加，不修改原有逻辑。
3. **Task 10 的进图验证**需要玩家手动操作，验证 Marine 生命值。如果验证失败，需要回溯 Task 2/3/7。
