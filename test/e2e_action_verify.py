"""End-to-end action verification:

1. Trigger chat_message via API
2. Immediately SendInput space key to SC2 (triggers PortingObserver SelectionChanged)
3. Wait briefly
4. Read bank: check if do_action.chat_message was written and game_state.active incremented
5. Capture screenshot of SC2 window
"""
import ctypes
import ctypes.wintypes as w
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

import xml.etree.ElementTree as ET

USER32 = ctypes.windll.user32

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


def make_key(vk: int, up: bool = False) -> INPUT:
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


def send_inputs(*inputs: INPUT) -> int:
    arr = (INPUT * len(inputs))(*inputs)
    return USER32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def set_foreground(hwnd: int) -> bool:
    USER32.ShowWindow(hwnd, 9)
    time.sleep(0.2)
    return bool(USER32.SetForegroundWindow(hwnd))


def read_bank(bank_path: Path) -> dict:
    try:
        tree = ET.parse(str(bank_path))
        root = tree.getroot()
        data = {"sections": {}}
        for sec in root.findall("Section"):
            sec_name = sec.get("name", "")
            keys = {}
            for key in sec.findall("Key"):
                k_name = key.get("name", "")
                val = key.find("Value")
                if val is None:
                    keys[k_name] = {}
                    continue
                keys[k_name] = dict(val.attrib)
            data["sections"][sec_name] = keys
        return data
    except Exception as exc:
        return {"error": str(exc)}


def trigger_action(action_name: str, args: dict) -> dict:
    payload = json.dumps({"action_name": action_name, "args": args}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8080/api/action/trigger",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        return {"error": f"HTTP {e.code}", "body": body}
    except Exception as e:
        return {"error": str(e)}


def main():
    hwnd = int(sys.argv[1]) if len(sys.argv) > 1 else 1053394
    bank_path = Path("C:/Users/22448/Documents/StarCraft II/Banks/NeuroIntegration.SC2Bank")

    print(f"[INF] hwnd={hwnd} bank={bank_path}")

    # Step 0: read bank before
    before = read_bank(bank_path)
    active_before = before.get("sections", {}).get("game_state", {}).get("active", {}).get("int", "?")
    print(f"[INF] active before: {active_before}")

    # Step 1: trigger chat_message via API
    msg = "CMRE e2e verified"
    r = trigger_action("chat_message", {"arg_1": msg})
    print(f"[INF] trigger_action: {r}")

    # Step 2: immediately focus SC2 and send space key
    if not set_foreground(hwnd):
        print("[ERR] SetForegroundWindow failed")
        return 1
    time.sleep(0.3)

    fg = USER32.GetForegroundWindow()
    if fg != hwnd:
        print(f"[ERR] foreground mismatch: {fg} != {hwnd}")
        return 1

    # Send Escape first to dismiss any dialog
    send_inputs(make_key(VK_ESCAPE), make_key(VK_ESCAPE, up=True))
    time.sleep(0.2)

    # Send Space (default keybind: select alert unit / camera jump)
    send_inputs(make_key(VK_SPACE), make_key(VK_SPACE, up=True))
    time.sleep(0.5)

    # Step 3: read bank mid-state
    mid = read_bank(bank_path)
    active_mid = mid.get("sections", {}).get("game_state", {}).get("active", {}).get("int", "?")
    do_action_mid = mid.get("sections", {}).get("do_action", {})
    print(f"[INF] after SPACE: active={active_mid} do_action={do_action_mid}")

    # If space did not trigger, try Enter+text+Enter (ChatMessage)
    if active_mid == active_before:
        print("[INF] SPACE didn't trigger. Trying chat message...")
        send_inputs(make_key(VK_RETURN), make_key(VK_RETURN, up=True))
        time.sleep(0.3)
        for ch in "hi neuro":
            scan = ord(ch)
            inp_down = INPUT()
            inp_down.type = INPUT_KEYBOARD
            inp_down.ki = KEYBDINPUT(
                wVk=0, wScan=ctypes.wintypes.WORD(scan),
                dwFlags=ctypes.wintypes.DWORD(KEYEVENTF_UNICODE),
                time=0, dwExtraInfo=None,
            )
            inp_up = INPUT()
            inp_up.type = INPUT_KEYBOARD
            inp_up.ki = KEYBDINPUT(
                wVk=0, wScan=ctypes.wintypes.WORD(scan),
                dwFlags=ctypes.wintypes.DWORD(KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
                time=0, dwExtraInfo=None,
            )
            send_inputs(inp_down, inp_up)
            time.sleep(0.05)
        time.sleep(0.3)
        send_inputs(make_key(VK_RETURN), make_key(VK_RETURN, up=True))
        time.sleep(1.0)

    after = read_bank(bank_path)
    active_after = after.get("sections", {}).get("game_state", {}).get("active", {}).get("int", "?")
    do_action_after = after.get("sections", {}).get("do_action", {})
    print(f"[INF] after chat: active={active_after} do_action={do_action_after}")

    # Step 4: try one more time with a long wait to see if action queue processes
    print("[INF] waiting 3s for action queue worker...")
    time.sleep(3.0)
    final = read_bank(bank_path)
    active_final = final.get("sections", {}).get("game_state", {}).get("active", {}).get("int", "?")
    do_action_final = final.get("sections", {}).get("do_action", {})
    print(f"[INF] final: active={active_final} do_action={do_action_final}")

    # Result summary
    success = (
        active_final != active_before
        and len(do_action_after) > 0
    )
    print(f"[RESULT] success={success}")
    print(f"[RESULT] active: {active_before} -> {active_final}")
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
