"""Trigger PortingObserver via mouse click events."""
import ctypes
import ctypes.wintypes as w
import sys
import time
import json
import urllib.request
import urllib.error
from pathlib import Path

import xml.etree.ElementTree as ET

USER32 = ctypes.windll.user32

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_ABSOLUTE = 0x8000
VK_RETURN = 0x0D
VK_SPACE = 0x20
KEYEVENTF_KEYDOWN = 0
KEYEVENTF_KEYUP = 0x2


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.wintypes.LONG),
        ("dy", ctypes.wintypes.LONG),
        ("mouseData", ctypes.wintypes.DWORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", ctypes.wintypes.DWORD), ("u", INPUT_UNION)]


def send_inputs(*inputs):
    arr = (INPUT * len(inputs))(*inputs)
    return USER32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def mouse_click(left=True, down=True):
    flag = 0
    if left:
        flag |= MOUSEEVENTF_LEFTDOWN if down else MOUSEEVENTF_LEFTUP
    else:
        flag |= MOUSEEVENTF_RIGHTDOWN if down else MOUSEEVENTF_RIGHTUP
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(dx=0, dy=0, mouseData=0, dwFlags=flag, time=0, dwExtraInfo=None)
    return inp


def mouse_move_abs(x, y, screen_w=2560, screen_h=1440):
    """Move mouse to absolute screen coordinates."""
    # SendInput absolute coords are 0..65535 mapped to primary monitor
    dx = int(x * 65535 / screen_w)
    dy = int(y * 65535 / screen_h)
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.mi = MOUSEINPUT(
        dx=ctypes.wintypes.LONG(dx),
        dy=ctypes.wintypes.LONG(dy),
        mouseData=0,
        dwFlags=ctypes.wintypes.DWORD(MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE),
        time=0,
        dwExtraInfo=None,
    )
    return inp


def key_press(vk):
    down = INPUT()
    down.type = INPUT_KEYBOARD
    down.ki = KEYBDINPUT(
        wVk=ctypes.wintypes.WORD(vk), wScan=0,
        dwFlags=ctypes.wintypes.DWORD(KEYEVENTF_KEYDOWN), time=0, dwExtraInfo=None,
    )
    up = INPUT()
    up.type = INPUT_KEYBOARD
    up.ki = KEYBDINPUT(
        wVk=ctypes.wintypes.WORD(vk), wScan=0,
        dwFlags=ctypes.wintypes.DWORD(KEYEVENTF_KEYUP), time=0, dwExtraInfo=None,
    )
    return (down, up)


def set_foreground(hwnd):
    USER32.ShowWindow(hwnd, 9)
    time.sleep(0.2)
    return bool(USER32.SetForegroundWindow(hwnd))


def read_bank_active(bank_path):
    try:
        tree = ET.parse(str(bank_path))
        sec = tree.getroot().find(".//Section[@name='game_state']")
        if sec is None:
            return None
        key = sec.find("Key[@name='active']")
        if key is None:
            return None
        val = key.find("Value")
        return int(val.get("int", "0"))
    except Exception:
        return None


def read_bank_do_action(bank_path):
    try:
        tree = ET.parse(str(bank_path))
        sec = tree.getroot().find(".//Section[@name='do_action']")
        if sec is None:
            return {}
        out = {}
        for key in sec.findall("Key"):
            name = key.get("name", "")
            val = key.find("Value")
            if val is None:
                continue
            out[name] = dict(val.attrib)
        return out
    except Exception:
        return {}


def trigger_action(action_name, args):
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
    except Exception as e:
        return {"error": str(e)}


def main():
    hwnd = int(sys.argv[1]) if len(sys.argv) > 1 else 1053394
    bank_path = Path("C:/Users/22448/Documents/StarCraft II/Banks/NeuroIntegration.SC2Bank")
    msg = "CMRE e2e verified"

    print(f"[INF] hwnd={hwnd}")

    # Bring SC2 to foreground
    if not set_foreground(hwnd):
        print("[ERR] SetForegroundWindow failed")
        return 1
    time.sleep(0.8)

    fg = USER32.GetForegroundWindow()
    if fg != hwnd:
        print(f"[ERR] foreground mismatch: {fg} != {hwnd}")
        return 1
    print("[INF] SC2 is foreground")

    # First, queue the action via API
    r = trigger_action("chat_message", {"arg_1": msg})
    print(f"[INF] trigger_action: {r}")

    active_before = read_bank_active(bank_path)
    print(f"[INF] active before: {active_before}")

    # Move mouse to center of screen
    send_inputs(mouse_move_abs(1280, 720))
    time.sleep(0.2)

    # Left click (selects unit under cursor -> SelectionChanged)
    send_inputs(mouse_click(left=True, down=True))
    time.sleep(0.05)
    send_inputs(mouse_click(left=True, down=False))
    time.sleep(0.4)

    active_after_left = read_bank_active(bank_path)
    do_after_left = read_bank_do_action(bank_path)
    print(f"[INF] after left-click: active={active_after_left} do_action={do_after_left}")

    # Right click (issue order -> UnitOrder)
    send_inputs(mouse_click(left=False, down=True))
    time.sleep(0.05)
    send_inputs(mouse_click(left=False, down=False))
    time.sleep(0.6)

    active_after_right = read_bank_active(bank_path)
    do_after_right = read_bank_do_action(bank_path)
    print(f"[INF] after right-click: active={active_after_right} do_action={do_after_right}")

    # Press space (default: select alert unit)
    send_inputs(*key_press(VK_SPACE))
    time.sleep(0.5)

    active_after_space = read_bank_active(bank_path)
    do_after_space = read_bank_do_action(bank_path)
    print(f"[INF] after space: active={active_after_space} do_action={do_after_space}")

    # Try chat (Enter + text + Enter)
    send_inputs(*key_press(VK_RETURN))
    time.sleep(0.4)
    for ch in msg:
        inp_down = INPUT()
        inp_down.type = INPUT_KEYBOARD
        inp_down.ki = KEYBDINPUT(
            wVk=0, wScan=ctypes.wintypes.WORD(ord(ch)),
            dwFlags=ctypes.wintypes.DWORD(0x4), time=0, dwExtraInfo=None,
        )
        inp_up = INPUT()
        inp_up.type = INPUT_KEYBOARD
        inp_up.ki = KEYBDINPUT(
            wVk=0, wScan=ctypes.wintypes.WORD(ord(ch)),
            dwFlags=ctypes.wintypes.DWORD(0x4 | 0x2), time=0, dwExtraInfo=None,
        )
        send_inputs(inp_down, inp_up)
        time.sleep(0.05)
    time.sleep(0.3)
    send_inputs(*key_press(VK_RETURN))
    time.sleep(1.2)

    active_after_chat = read_bank_active(bank_path)
    do_after_chat = read_bank_do_action(bank_path)
    print(f"[INF] after chat: active={active_after_chat} do_action={do_after_chat}")

    # Wait longer for action queue worker
    print("[INF] waiting 3s for action queue...")
    time.sleep(3.0)
    active_final = read_bank_active(bank_path)
    do_final = read_bank_do_action(bank_path)
    print(f"[INF] final: active={active_final} do_action={do_final}")

    success = active_final != active_before and len(do_after_chat) > 0
    print(f"[RESULT] success={success} active: {active_before} -> {active_final}")
    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
