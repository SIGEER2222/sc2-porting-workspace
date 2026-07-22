"""Bump NeuroIntegration bank active value to trigger Integration 0.3s processing window.

Reads current active value from bank, increments by 1, writes back.
"""
import os
import re
import subprocess
import sys

BANK_PATH = r"C:\Users\22448\Documents\StarCraft II\Banks\NeuroIntegration.SC2Bank"
TMP_PATH = os.path.join(os.environ["TEMP"], "neuro_bank_bump.xml")

with open(BANK_PATH, "r", encoding="utf-8") as f:
    content = f.read()

# Find active key block: <Key name="active">\n  <Value int="N"/>\n</Key>
m = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"\s*/>', content)
if not m:
    print("ERROR: active key block not found")
    sys.exit(1)

old_value = int(m.group(1))
new_value = (old_value + 1) if old_value < 2000000000 else 1

old_block = m.group(0)
new_block = old_block.replace(f'<Value int="{old_value}"', f'<Value int="{new_value}"')
new_content = content.replace(old_block, new_block, 1)

with open(TMP_PATH, "w", encoding="utf-8") as f:
    f.write(new_content)

print(f"Active bumped {old_value} -> {new_value}")

result = subprocess.run([
    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
    r"c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-write-bin.ps1",
    BANK_PATH, "-FromTmp", TMP_PATH
], capture_output=True, text=True)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("Return code:", result.returncode)
