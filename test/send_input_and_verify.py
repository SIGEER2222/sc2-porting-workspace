"""Send keyboard events to SC2 and verify execute_actions_global is triggered.

This script sends Enter + text + Enter to trigger ChatMessage event, then checks bank
to see if active value increased (which would indicate PortingObserver trigger fired).
"""
import ctypes
import ctypes.wintypes as w
import os
import re
import time
import xml.etree.ElementTree as ET

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


def read_active():
    bank_path = r"C:\Users\22448\Documents\StarCraft II\Banks\NeuroIntegration.SC2Bank"
    try:
        tree = ET.parse(bank_path)
        sec = tree.getroot().find(".//Section[@name='game_state']")
        if sec is None:
            return None
        key = sec.find("Key[@name='active']")
        if key is None:
            return None
        val = key.find("Value")
        return int(val.get("int", "0"))
    except Exception as exc:
        print(f"  read bank error: {exc}")
        return None


def read_do_action_chat_flag():
    bank_path = r"C:\Users\22448\Documents\StarCraft II\Banks\NeuroIntegration.SC2Bank"
    try:
        tree = ET.parse(bank_path)
        sec = tree.getroot().find(".//Section[@name='do_action']")
        if sec is None:
            return None
        key = sec.find("Key[@name='chat_message']")
        if key is None:
            return None
        val = key.find("Value")
        return val.get("flag", "0")
    except Exception as exc:
        print(f"  read bank error: {exc}")
        return None


def set_foreground(hwnd):
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    time.sleep(0.5)
    ok = bool(user32.SetForegroundWindow(hwnd))
    time.sleep(1.0)  # longer wait
    fg = user32.GetForegroundWindow()
    print(f"  SetForegroundWindow result: {ok}, foreground={fg}, target={hwnd}, match={fg == hwnd}")
    return fg == hwnd


def main():
    import sys
    hwnd = int(sys.argv[1]) if len(sys.argv) > 1 else 3476572

    print(f"=== Setting SC2 (hwnd={hwnd}) as foreground ===")
    if not set_foreground(hwnd):
        print("  [ERR] Failed to set foreground")
        return 1

    print("=== Reading bank state before ===")
    active_before = read_active()
    print(f"  active before: {active_before}")

    print("=== Sending ESC to clear any dialog ===")
    send_inputs(make_key_input(VK_ESCAPE), make_key_input(VK_ESCAPE, up=True))
    time.sleep(0.5)

    print("=== Sending Space (trigger alert selection) ===")
    send_inputs(make_key_input(VK_SPACE), make_key_input(VK_SPACE, up=True))
    time.sleep(1.0)
    active_after_space = read_active()
    print(f"  active after SPACE: {active_after_space} (changed={active_after_space != active_before})")

    print("=== Sending Enter + chat text + Enter ===")
    send_inputs(make_key_input(VK_RETURN), make_key_input(VK_RETURN, up=True))
    time.sleep(0.8)

    msg = "neuro e2e"
    for ch in msg:
        send_inputs(make_unicode_input(ch), make_unicode_input(ch, up=True))
        time.sleep(0.05)
    time.sleep(0.5)

    send_inputs(make_key_input(VK_RETURN), make_key_input(VK_RETURN, up=True))
    time.sleep(2.0)

    active_after_chat = read_active()
    chat_flag = read_do_action_chat_flag()
    print(f"  active after chat: {active_after_chat}")
    print(f"  do_action.chat_message flag: {chat_flag}")

    if active_after_chat != active_before:
        print("  SUCCESS: active value changed - PortingObserver trigger fired!")
        return 0
    else:
        print("  WARN: active value unchanged - SC2 trigger did not fire")
        return 2


if __name__ == "__main__":
    sys_rc = main()
    import sys
    sys.exit(sys_rc)
