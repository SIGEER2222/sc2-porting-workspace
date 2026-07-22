"""Send keyboard events to SC2 via SendInput to trigger PortingObserver player events."""
import ctypes
import ctypes.wintypes as w
import sys
import time
from pathlib import Path

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
VK_RETURN = 0x0D
VK_SPACE = 0x20
VK_ESCAPE = 0x1B
VK_BACK = 0x08


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


def make_key_input(vk: int, up: bool = False) -> INPUT:
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
    return user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))


def set_foreground(hwnd: int) -> bool:
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    time.sleep(0.1)
    return bool(user32.SetForegroundWindow(hwnd))


def get_foreground() -> int:
    return user32.GetForegroundWindow()


def read_bank_active(bank_path: Path) -> int:
    import xml.etree.ElementTree as ET

    try:
        tree = ET.parse(str(bank_path))
        root = tree.getroot()
        sec = root.find(".//Section[@name='game_state']")
        if sec is None:
            return -1
        key = sec.find("Key[@name='active']")
        if key is None:
            return -1
        val = key.find("Value")
        if val is None:
            return -1
        return int(val.get("int", "0"))
    except Exception as exc:
        print(f"read bank error: {exc}")
        return -1


def read_do_action(bank_path: Path) -> dict:
    import xml.etree.ElementTree as ET

    out = {}
    try:
        tree = ET.parse(str(bank_path))
        root = tree.getroot()
        sec = root.find(".//Section[@name='do_action']")
        if sec is None:
            return out
        for key in sec.findall("Key"):
            name = key.get("name", "")
            val = key.find("Value")
            if val is None:
                continue
            out[name] = list(val.attrib.items())
    except Exception as exc:
        print(f"read bank error: {exc}")
    return out


def main():
    hwnd = int(sys.argv[1]) if len(sys.argv) > 1 else 2887688
    bank_path = Path("C:/Users/22448/Documents/StarCraft II/Banks/NeuroIntegration.SC2Bank")

    if not set_foreground(hwnd):
        print("[ERR] SetForegroundWindow failed")
        return 1

    time.sleep(0.8)
    fg = get_foreground()
    if fg != hwnd:
        print(f"[ERR] Foreground mismatch: expected={hwnd} actual={fg}")
        return 1

    before_active = read_bank_active(bank_path)
    print(f"[INF] Bank active before: {before_active}")

    # Send Escape first to clear any UI dialog
    send_inputs(make_key_input(VK_ESCAPE), make_key_input(VK_ESCAPE, up=True))
    time.sleep(0.3)

    # Send Space (default key: "go to alert" / selects alert unit, triggering SelectionChanged)
    send_inputs(make_key_input(VK_SPACE), make_key_input(VK_SPACE, up=True))
    time.sleep(0.5)

    after_space = read_bank_active(bank_path)
    print(f"[INF] Bank active after SPACE: {after_space} (changed={after_space != before_active})")

    # Try Enter -> type text -> Enter (triggers ChatMessage)
    send_inputs(make_key_input(VK_RETURN), make_key_input(VK_RETURN, up=True))
    time.sleep(0.5)

    msg = "neuro e2e verified"
    for ch in msg:
        scan = ctypes.windll.user32.MapVirtualKeyW(ord(ch.upper()), 0)  # MAPVK_VK_TO_VSC
        # Best effort: send as unicode event
        inp_down = INPUT()
        inp_down.type = INPUT_KEYBOARD
        inp_down.ki = KEYBDINPUT(
            wVk=0,
            wScan=ctypes.wintypes.WORD(ord(ch)),
            dwFlags=ctypes.wintypes.DWORD(KEYEVENTF_UNICODE),
            time=0,
            dwExtraInfo=None,
        )
        inp_up = INPUT()
        inp_up.type = INPUT_KEYBOARD
        inp_up.ki = KEYBDINPUT(
            wVk=0,
            wScan=ctypes.wintypes.WORD(ord(ch)),
            dwFlags=ctypes.wintypes.DWORD(KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            time=0,
            dwExtraInfo=None,
        )
        send_inputs(inp_down, inp_up)
        time.sleep(0.05)

    time.sleep(0.4)
    send_inputs(make_key_input(VK_RETURN), make_key_input(VK_RETURN, up=True))
    time.sleep(1.2)

    after_chat = read_bank_active(bank_path)
    print(f"[INF] Bank active after chat: {after_chat} (changed={after_chat != after_space})")

    do_action = read_do_action(bank_path)
    print(f"[INF] do_action section: {do_action}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
