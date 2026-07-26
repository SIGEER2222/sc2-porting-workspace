#!/usr/bin/env python3
"""从 prestige-bonus-extract.json 生成 CMRE_BuffPatch.SC2Mod 的 UpgradeData.xml。

输出 N 个 CommanderPrestigeXxxBonus upgrade，每个只包含优点的 EffectArray。
对 needs_manual_review=true 的威望，跳过并打印警告（不生成空 upgrade）。

bonus_upgrade_id 字段不存在时，从 primary_upgrade + "Bonus" 派生。
"""
import json
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


def get_bonus_upgrade_id(prestige: dict) -> str:
    """优先用 bonus_upgrade_id，否则从 primary_upgrade + 'Bonus' 派生。"""
    if prestige.get("bonus_upgrade_id"):
        return prestige["bonus_upgrade_id"]
    primary = prestige.get("primary_upgrade", "")
    if not primary:
        return ""
    return f"{primary}Bonus"


def build_upgrade_element(commander: dict, prestige: dict) -> tuple[ET.Element, str]:
    """构建单个 CUpgrade XML 元素。返回 (元素, upgrade_id)。

    对 needs_manual_review=True 仍跳过；对无优点的 flag-only 威望，
    生成最小 upgrade (parent + EditorCategories + MaxLevel) 作为 galaxy dispatch 的 flag。
    """
    upgrade_id = get_bonus_upgrade_id(prestige)
    if not upgrade_id:
        return None, ""

    if prestige.get("needs_manual_review", False):
        print(f"[WARN] 跳过需人工审核: {commander['runtime_commander']} P{prestige['slot']} ({prestige['name']})")
        return None, upgrade_id

    effect_arrays = prestige.get("effect_arrays", [])
    advantages = [ea for ea in effect_arrays if ea.get("is_advantage", False)]
    race = detect_race(commander["runtime_commander"])

    upgrade = ET.Element("CUpgrade", {
        "id": upgrade_id,
        "parent": "CommanderPrestige",
    })
    # 添加优点 EffectArray（如果有）
    for ea in advantages:
        attrs = {"Reference": ea["reference"], "Value": ea["value"]}
        op = ea.get("operation", "Add")
        if op and op != "Add":
            attrs["Operation"] = op
        ET.SubElement(upgrade, "EffectArray", attrs)
    ET.SubElement(upgrade, "EditorCategories", {"value": f"Race:{race},UpgradeType:Talents"})
    ET.SubElement(upgrade, "MaxLevel", {"value": "1"})

    if not advantages:
        # flag-only upgrade：galaxy dispatch 需要应用额外 upgrade/ability
        print(f"[INFO] 生成 flag-only upgrade: {commander['runtime_commander']} P{prestige['slot']} ({prestige['name']})")

    return upgrade, upgrade_id


def main():
    if not EXTRACT_JSON.exists():
        print(f"[ERROR] 提取数据不存在: {EXTRACT_JSON}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(EXTRACT_JSON.read_text(encoding="utf-8"))

    catalog = ET.Element("Catalog")
    generated = 0
    skipped = 0
    skipped_items = []
    all_bonus_ids = []  # 所有生成的 + 跳过的 bonus_upgrade_id，供 galaxy dispatch 使用

    for commander in data.get("commanders", []):
        for prestige in commander.get("prestiges", []):
            upgrade, upgrade_id = build_upgrade_element(commander, prestige)
            if upgrade_id:
                all_bonus_ids.append({
                    "runtime_commander": commander["runtime_commander"],
                    "bank_commander": commander.get("bank_commander", ""),
                    "display_name": commander.get("display_name", ""),
                    "slot": prestige.get("slot", 0),
                    "name": prestige.get("name", ""),
                    "bonus_upgrade_id": upgrade_id,
                    "needs_manual_review": prestige.get("needs_manual_review", False),
                    "generated": upgrade is not None,
                    "galaxy_dispatch_required": prestige.get("galaxy_dispatch_required", False),
                    "galaxy_dispatch_actions": prestige.get("galaxy_dispatch_actions", []),
                    "review_notes": prestige.get("review_notes", ""),
                })
            if upgrade is None:
                skipped += 1
                skipped_items.append(f"{commander['runtime_commander']} P{prestige.get('slot', '?')}")
                continue
            catalog.append(upgrade)
            generated += 1

    # 美化输出
    rough = ET.tostring(catalog, encoding="utf-8")
    pretty = minidom.parseString(rough).toprettyxml(indent="    ", encoding="utf-8")
    OUTPUT_XML.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_XML.write_bytes(pretty)

    # 同时输出 bonus_upgrade_id 索引，供 Task 7 的 galaxy dispatch 使用
    index_path = EXTRACT_JSON.parent / "prestige-bonus-index.json"
    index_path.write_text(json.dumps(all_bonus_ids, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"[OK] 生成 {generated} 个 supplement upgrade -> {OUTPUT_XML}")
    print(f"[OK] 索引写入 -> {index_path}")
    print(f"[SKIP] 跳过 {skipped} 个需人工审核或无优点的威望:")
    for item in skipped_items:
        print(f"  - {item}")


if __name__ == "__main__":
    main()
