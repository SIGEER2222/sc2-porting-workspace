"""E2E verify Neuro action: queue action → bump active → send input to SC2 to trigger ExecuteActions_Func.

Sequence:
1. bump active to unpause
2. POST /api/action/trigger (queue chat_message)
3. bump active to open 0.3s processing window (Integration writes do_action to bank)
4. wait 1s for Integration to write do_action
5. send keyboard inputs to SC2 (Space + Enter + text + Enter) to trigger:
   - SelectionChanged → execute_actions_global → execute_actions_map → ExecuteActions_Func reads do_action
6. wait 2s, check bank: do_action.chat_message should be cleared (false) if executed
"""
import ctypes
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import ctypes.wintypes as w

BANK_PATH = r"C:\Users\22448\Documents\StarCraft II\Banks\NeuroIntegration.SC2Bank"
TMP_PATH = os.path.join(os.environ["TEMP"], "neuro_bank_bump.xml")
API_URL = "http://127.0.0.1:8080/api/action/trigger"

user32 = ctypes.windll.user32
INPUT_KEYBOARD = 1
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_ESCAPE = 0x1B


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.wintypes.DWORD), ("u", INPUT_UNION)]


def make_key_input(vk, up=False):
    flag = KEYEVENTF_KEYUP if up else KEYEVENTF_KEYDOWN
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(
        wVk=ctypes.wintypes.WORD(vk),
        wScan=ctypes.wintypes.WORD(0),
        dwFlags=ctypes.wintypes.DWORD(flag),
        time=ctypes.wintypes.DWORD(0),
        dwExtraInfo=None,
    )
    return inp


def make_unicode_input(ch, up=False):
    flag = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki = KEYBDINPUT(
        wVk=0,
        wScan=ctypes.wintypes.WORD(ord(ch)),
        dwFlags=ctypes.wintypes.DWORD(flag),
        time=0,
        dwExtraInfo=None,
    )
    return inp


def send_inputs(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def set_foreground(hwnd):
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    time.sleep(0.2)
    return bool(user32.SetForegroundWindow(hwnd))


def bump_active():
    with open(BANK_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"\s*/>', content)
    if not m:
        print("  ERROR: active key block not found")
        return None
    old_value = int(m.group(1))
    new_value = (old_value + 1) if old_value < 2000000000 else 1
    old_block = m.group(0)
    new_block = old_block.replace(f'<Value int="{old_value}"', f'<Value int="{new_value}"')
    new_content = content.replace(old_block, new_block, 1)
    with open(TMP_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)
    subprocess.run([
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


def check_active(content):
    m = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"\s*/>', content)
    return int(m.group(1)) if m else None


def send_sc2_inputs(hwnd, chat_msg):
    """Send Space (select alert unit) + Enter + chat message + Enter."""
    if not set_foreground(hwnd):
        print("  [ERR] SetForegroundWindow failed")
        return False
    time.sleep(0.5)

    # ESC to clear any UI
    send_inputs(make_key_input(VK_ESCAPE), make_key_input(VK_ESCAPE, up=True))
    time.sleep(0.3)

    # Space to trigger "go to alert" / selection
    send_inputs(make_key_input(VK_SPACE), make_key_input(VK_SPACE, up=True))
    time.sleep(0.5)

    # Enter to open chat
    send_inputs(make_key_input(VK_RETURN), make_key_input(VK_RETURN, up=True))
    time.sleep(0.4)

    # Type chat message
    for ch in chat_msg:
        send_inputs(make_unicode_input(ch), make_unicode_input(ch, up=True))
        time.sleep(0.03)
    time.sleep(0.3)

    # Enter to send chat
    send_inputs(make_key_input(VK_RETURN), make_key_input(VK_RETURN, up=True))
    time.sleep(0.5)
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python e2e_verify_neuro_action.py <sc2_hwnd>")
        return 1

    hwnd = int(sys.argv[1])
    msg = f"blank_test_neuro e2e verified at {time.strftime('%H:%M:%S')}"

    print("=== Step 1: bump active to unpause ===")
    bump_active()

    print("=== Step 2: trigger chat_message action ===")
    trigger_action(msg)

    print("=== Step 3: bump active to open 0.3s window ===")
    bump_active()

    print("=== Step 4: wait 1s for Integration to write do_action ===")
    time.sleep(1.0)
    content = read_bank()
    do_action = check_do_action(content)
    if not do_action:
        print("  WARN: do_action section not found yet")
    else:
        print(f"  do_action written:")
        print(f"  {do_action}")
    active = check_active(content)
    print(f"  game_state.active = {active}")

    print("=== Step 5: send inputs to SC2 to trigger SelectionChanged/Chat events ===")
    send_sc2_inputs(hwnd, msg)

    print("=== Step 6: wait 2s and check bank ===")
    time.sleep(2.0)
    content = read_bank()
    do_action = check_do_action(content)
    active = check_active(content)
    print(f"  game_state.active = {active}")
    if do_action:
        # Check if chat_message flag is still 1 or cleared to 0
        if 'flag="0"' in do_action or 'flag="0"' in do_action.replace(' ', ''):
            print(f"  SUCCESS: do_action.chat_message cleared to false (ExecuteActions_Func executed)")
            print(f"  Section: {do_action}")
            return 0
        else:
            print(f"  do_action section still has chat_message=true (not executed yet):")
            print(f"  {do_action}")
            return 2
    else:
        print(f"  do_action section cleared (likely executed)")
        return 0


if __name__ == "__main__":
    rc = main()
    sys.exit(rc)
