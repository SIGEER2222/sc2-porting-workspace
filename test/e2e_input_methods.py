"""Try multiple input methods to trigger SC2 PortingObserver."""
import ctypes
import ctypes.wintypes as w
import sys
import time
import json
import urllib.request
from pathlib import Path
import xml.etree.ElementTree as ET

USER32 = ctypes.windll.user32

# Old keybd_event API
USER32.keybd_event.argtypes = [
    ctypes.wintypes.BYTE, ctypes.wintypes.BYTE,
    ctypes.wintypes.DWORD, ctypes.c_size_t,
]
USER32.keybd_event.restype = None

USER32.mouse_event.argtypes = [
    ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
    ctypes.wintypes.DWORD, ctypes.wintypes.DWORD,
    ctypes.c_size_t,
]
USER32.mouse_event.restype = None

USER32.SetCursorPos.argtypes = [ctypes.wintypes.LONG, ctypes.wintypes.LONG]
USER32.SetCursorPos.restype = ctypes.wintypes.BOOL

VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_ESCAPE = 0x1B
VK_F1 = 0x70
VK_F2 = 0x71
VK_H = 0x48
VK_S = 0x53
KEYEVENTF_KEYUP = 0x2

MOUSEEVENTF_LEFTDOWN = 0x2
MOUSEEVENTF_LEFTUP = 0x4
MOUSEEVENTF_RIGHTDOWN = 0x8
MOUSEEVENTF_RIGHTUP = 0x10


def keybd(vk, up=False):
    USER32.keybd_event(ctypes.wintypes.BYTE(vk), 0,
                      ctypes.wintypes.DWORD(KEYEVENTF_KEYUP if up else 0), 0)


def type_key(vk, hold=0.05):
    keybd(vk)
    time.sleep(hold)
    keybd(vk, up=True)


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


def read_do_action(bank_path):
    try:
        tree = ET.parse(str(bank_path))
        sec = tree.getroot().find(".//Section[@name='do_action']")
        if sec is None:
            return {}
        out = {}
        for key in sec.findall("Key"):
            name = key.get("name", "")
            val = key.find("Value")
            out[name] = dict(val.attrib) if val is not None else {}
        return out
    except Exception:
        return {}


def trigger_action_api(action_name, args):
    payload = json.dumps({"action_name": action_name, "args": args}).encode("utf-8")
    req = urllib.request.Request(
        "http://127.0.0.1:8080/api/action/trigger",
        data=payload, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def main():
    hwnd = int(sys.argv[1]) if len(sys.argv) > 1 else 1053394
    bank_path = Path("C:/Users/22448/Documents/StarCraft II/Banks/NeuroIntegration.SC2Bank")
    print(f"[INF] hwnd={hwnd}")

    if not set_foreground(hwnd):
        print("[ERR] SetForegroundWindow failed")
        return 1
    time.sleep(1.0)
    fg = USER32.GetForegroundWindow()
    if fg != hwnd:
        print(f"[ERR] foreground mismatch: {fg} != {hwnd}")
        return 1
    print("[INF] SC2 is foreground")

    # Queue the action first
    r = trigger_action_api("chat_message", {"arg_1": "neuro e2e"})
    print(f"[INF] trigger: {r}")

    active_before = read_bank_active(bank_path)
    print(f"[INF] active before: {active_before}")

    # Method 1: mouse click at center
    print("[INF] Method 1: left-click center")
    USER32.SetCursorPos(1280, 720)
    time.sleep(0.2)
    USER32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    USER32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.5)

    a1 = read_bank_active(bank_path)
    print(f"[INF] after L-click: active={a1}")

    # Method 2: right-click (issue order)
    print("[INF] Method 2: right-click")
    USER32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
    time.sleep(0.05)
    USER32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
    time.sleep(0.5)

    a2 = read_bank_active(bank_path)
    print(f"[INF] after R-click: active={a2}")

    # Method 3: F1 (select HQ)
    print("[INF] Method 3: F1")
    type_key(VK_F1)
    time.sleep(0.5)
    a3 = read_bank_active(bank_path)
    print(f"[INF] after F1: active={a3}")

    # Method 4: F2 (select army)
    print("[INF] Method 4: F2")
    type_key(VK_F2)
    time.sleep(0.5)
    a4 = read_bank_active(bank_path)
    print(f"[INF] after F2: active={a4}")

    # Method 5: Space key
    print("[INF] Method 5: Space")
    type_key(VK_SPACE)
    time.sleep(0.5)
    a5 = read_bank_active(bank_path)
    print(f"[INF] after Space: active={a5}")

    # Method 6: ESC
    print("[INF] Method 6: ESC")
    type_key(VK_ESCAPE)
    time.sleep(0.5)
    a6 = read_bank_active(bank_path)
    print(f"[INF] after ESC: active={a6}")

    # Method 7: drag selection box (left down + move + left up)
    print("[INF] Method 7: drag-select")
    USER32.SetCursorPos(800, 600)
    time.sleep(0.2)
    USER32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(0.1)
    USER32.SetCursorPos(1700, 900)
    time.sleep(0.2)
    USER32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
    time.sleep(0.5)
    a7 = read_bank_active(bank_path)
    print(f"[INF] after drag: active={a7}")

    # Method 8: Enter + chat + Enter (in-game chat)
    print("[INF] Method 8: Enter + chat + Enter")
    type_key(VK_RETURN)
    time.sleep(0.5)
    for ch in "hello neuro":
        USER32.keybd_event(ctypes.wintypes.BYTE(ord(ch.upper())), 0, 0, 0)
        time.sleep(0.05)
        USER32.keybd_event(ctypes.wintypes.BYTE(ord(ch.upper())), 0, KEYEVENTF_KEYUP, 0)
        time.sleep(0.05)
    time.sleep(0.3)
    type_key(VK_RETURN)
    time.sleep(1.0)
    a8 = read_bank_active(bank_path)
    print(f"[INF] after chat: active={a8}")

    do = read_do_action(bank_path)
    print(f"[INF] final do_action: {do}")
    print(f"[RESULT] active: {active_before} -> {a8}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
