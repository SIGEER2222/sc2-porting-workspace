#!/usr/bin/env python3
"""从 CMRE mod 提取 mutator 目录到 JSON。

数据源：
  - UserData.xml 的 <CUser id="Mutators"> 块（提取 CustomAllowed=1 的实例）
  - GameStrings.txt 的 UserData/Mutators/<Id>_Name 和 _Description

用法: python extract_mutators.py
输出: data/mutators.json
"""

import json
import re
import sys
from pathlib import Path

# CMRE mod 路径
CMRE_MOD_ROOT = Path(
    r"E:\Code\MyMod\SC2\合作指挥官-起义狂潮\Mods\CMRE\CMRE_Core_Triggers.SC2Mod"
)
USERDATA_XML = CMRE_MOD_ROOT / "Base.SC2Data" / "GameData" / "UserData.xml"
GAMESTRINGS_TXT = CMRE_MOD_ROOT / "zhCN.SC2Data" / "LocalizedData" / "GameStrings.txt"

# 输出路径
OUTPUT_JSON = Path(__file__).resolve().parent / "data" / "mutators.json"


def extract_mutator_instances():
    """从 UserData.xml 提取 Mutators CUser 块中 CustomAllowed=1 的实例 ID。"""
    content = USERDATA_XML.read_text(encoding="utf-8")

    # 定位 <CUser id="Mutators"> 块
    block_match = re.search(
        r'<CUser\s+id="Mutators"[^>]*>([\s\S]*?)</CUser>', content
    )
    if not block_match:
        print("ERROR: <CUser id=\"Mutators\"> 块未找到", file=sys.stderr)
        sys.exit(1)

    block = block_match.group(1)

    # 提取所有 <Instances Id="...">...</Instances> 块
    instances = []
    for m in re.finditer(
        r'<Instances\s+Id="([^"]+)"[^>]*>([\s\S]*?)</Instances>', block
    ):
        inst_id = m.group(1)
        body = m.group(2)

        # 过滤：必须有 CustomAllowed=1
        # 格式: <Int Int="1"><Field Id="CustomAllowed"/></Int>
        # 或: <Int Int="1"><Field Id="MA - Custom Allowed"/></Int>
        if not re.search(
            r'<Int\s+Int="1">\s*<Field\s+Id="(?:CustomAllowed|MA - Custom Allowed)"/>\s*</Int>',
            body,
        ):
            continue

        instances.append(inst_id)

    return instances


def extract_gamestrings():
    """从 GameStrings.txt 提取 mutator 名称和描述。"""
    content = GAMESTRINGS_TXT.read_text(encoding="utf-8", errors="replace")

    strings = {}
    for line in content.splitlines():
        if not line or line.startswith("//"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        # 只收集 UserData/Mutators/ 相关的键
        if key.startswith("UserData/Mutators/"):
            strings[key] = value

    return strings


def build_mutator_catalog():
    """构建 mutator 目录。"""
    print(f"读取 UserData.xml: {USERDATA_XML}")
    instances = extract_mutator_instances()
    print(f"找到 {len(instances)} 个 CustomAllowed=1 的 mutator 实例")

    print(f"读取 GameStrings.txt: {GAMESTRINGS_TXT}")
    strings = extract_gamestrings()
    print(f"找到 {len(strings)} 条 UserData/Mutators/ 字符串")

    catalog = []
    for inst_id in instances:
        name_key = f"UserData/Mutators/{inst_id}_Name"
        desc_key = f"UserData/Mutators/{inst_id}_Description"
        name = strings.get(name_key, inst_id)
        desc = strings.get(desc_key, "")
        catalog.append(
            {
                "id": inst_id,
                "name": name,
                "description": desc,
            }
        )

    # 按名称排序
    catalog.sort(key=lambda x: x["name"])

    return catalog


def main():
    catalog = build_mutator_catalog()

    OUTPUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_JSON.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n输出: {OUTPUT_JSON}")
    print(f"总数: {len(catalog)} 个 mutator")
    if catalog:
        print("\n前 10 个示例:")
        for m in catalog[:10]:
            print(f"  {m['id']}: {m['name']} - {m['description'][:50]}")


if __name__ == "__main__":
    main()
