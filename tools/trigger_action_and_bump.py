"""Trigger chat_message action and bump active in rapid sequence to fit 0.3s processing window.

Sequence:
1. bump active (解除 paused 状态)
2. POST /api/action/trigger (queue action)
3. bump active (trigger 0.3s processing window)
4. wait 1s, check bank do_action section
"""
import os
import re
import subprocess
import sys
import time
import urllib.request
import json

BANK_PATH = r"C:\Users\22448\Documents\StarCraft II\Banks\NeuroIntegration.SC2Bank"
TMP_PATH = os.path.join(os.environ["TEMP"], "neuro_bank_bump.xml")
API_URL = "http://127.0.0.1:8080/api/action/trigger"


def bump_active():
    with open(BANK_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"\s*/>', content)
    if not m:
        print("ERROR: active key block not found")
        return None
    old_value = int(m.group(1))
    new_value = (old_value + 1) if old_value < 2000000000 else 1
    old_block = m.group(0)
    new_block = old_block.replace(f'<Value int="{old_value}"', f'<Value int="{new_value}"')
    new_content = content.replace(old_block, new_block, 1)
    with open(TMP_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    result = subprocess.run([
        "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
        r"c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-write-bin.ps1",
        BANK_PATH, "-FromTmp", TMP_PATH
    ], capture_output=True, text=True)
    print(f"  Active bumped {old_value} -> {new_value}")
    return new_value


def trigger_action(msg):
    body = json.dumps({
        "action_name": "chat_message",
        "args": {"arg_1": msg}
    }).encode("utf-8")
    req = urllib.request.Request(API_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    print(f"  Action triggered: {data}")
    return data


def read_bank():
    with open(BANK_PATH, "r", encoding="utf-8") as f:
        return f.read()


def check_do_action(content):
    m = re.search(r'<Section name="do_action">(.*?)</Section>', content, re.DOTALL)
    if m:
        return m.group(0)
    return None


if __name__ == "__main__":
    msg = f"blank_test_neuro e2e verified at {time.strftime('%H:%M:%S')}"

    print("=== Step 1: bump active to unpause ===")
    bump_active()

    print("=== Step 2: trigger chat_message action ===")
    trigger_action(msg)

    print("=== Step 3: bump active to open 0.3s window ===")
    bump_active()

    print("=== Step 4: wait 1s and check bank ===")
    time.sleep(1.0)
    content = read_bank()
    do_action = check_do_action(content)
    if do_action:
        print(f"SUCCESS: do_action section found:")
        print(do_action)
    else:
        print("do_action section NOT FOUND yet")

    # Show game_state.active
    m = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"\s*/>', content)
    if m:
        print(f"game_state.active = {m.group(1)}")
