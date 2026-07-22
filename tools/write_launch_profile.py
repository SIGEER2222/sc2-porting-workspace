"""Create CMCoopLaunchProfile.SC2Bank for Stetmann commander.

This bank tells CoreRuntime which commander to spawn for player 1.
"""
import time
import xml.etree.ElementTree as ET
from pathlib import Path

bank_path = Path("C:/Users/22448/Documents/StarCraft II/Banks/CMCoopLaunchProfile.SC2Bank")

# Build a fresh bank XML
root = ET.Element("Bank", version="1")
sec = ET.SubElement(root, "Section", name="CMUI|LaunchProfile")

values = [
    ("Valid", "int", "1"),
    ("Version", "int", "1"),
    ("CreatedAt", "int", str(int(time.time()))),
    ("TimeoutSeconds", "int", "600"),
    ("Mode", "int", "1"),
    ("ModeInstance", "string", "Standard"),
    ("DifficultyBase", "int", "0"),
    ("DifficultyPlus", "int", "0"),
    ("TargetMission", "string", "AC_BlankTest"),
    ("TargetMap", "string", "AC_BlankTest"),
    ("Player|1|Commander", "string", "Stetmann"),
    ("Player|2|Commander", "string", "Stetmann"),
]
for name, typ, val in values:
    key = ET.SubElement(sec, "Key", name=name)
    value = ET.SubElement(key, "Value")
    value.set(typ, val)

tree = ET.ElementTree(root)
ET.indent(tree, space="    ")
xml_str = '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(root, encoding="unicode")

# Write via standard Python (this is a user document file, not a workspace file)
bank_path.write_text(xml_str, encoding="utf-8")
print(f"Wrote {bank_path} size={bank_path.stat().st_size}")
print(xml_str)
