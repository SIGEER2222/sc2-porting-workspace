"""
Send a chat message to SC2 via SendInput to fire ChatMessage event,
which triggers execute_actions_global -> ExecuteActionsGlobal_Func,
which displays do_action.chat_message and clears the flag.

Usage: python trigger_chat_to_sc2.py <HWND>
"""
import ctypes
import ctypes.wintypes
import sys
import time
from pathlib import Path

# Win32 API constants
INPUT_KEYBOARD = 1
INPUT_MOUSE = 0
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.wintypes.WORD),
        ("wScan", ctypes.wintypes.WORD),
        ("dwFlags", ctypes.wintypes.DWORD),
        ("time", ctypes.wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT)]
    _anonymous_ = ("_input",)
    _fields_ = [("type", ctypes.wintypes.DWORD), ("_input", _INPUT)]


def send_key(vk, down=True):
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    inp.ki.wScan = 0
    inp.ki.dwFlags = 0 if down else KEYEVENTF_KEYUP
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def send_unicode_char(ch):
    inp_down = INPUT()
    inp_down.type = INPUT_KEYBOARD
    inp_down.ki.wVk = 0
    inp_down.ki.wScan = ord(ch)
    inp_down.ki.dwFlags = KEYEVENTF_UNICODE
    inp_up = INPUT()
    inp_up.type = INPUT_KEYBOARD
    inp_up.ki.wVk = 0
    inp_up.ki.wScan = ord(ch)
    inp_up.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
    user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
    user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))


def type_string(s):
    for ch in s:
        send_unicode_char(ch)
        time.sleep(0.03)


def send_enter():
    send_key(VK_RETURN, True)
    time.sleep(0.05)
    send_key(VK_RETURN, False)
    time.sleep(0.1)


def main():
    if len(sys.argv) < 2:
        print("Usage: python trigger_chat_to_sc2.py <HWND>")
        sys.exit(1)
    hwnd = int(sys.argv[1])
    print(f"[*] Target HWND: {hwnd}")

    # Bring SC2 to foreground
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)

    fg = user32.GetForegroundWindow()
    print(f"[*] Foreground window after SetForegroundWindow: {fg} (match={fg == hwnd})")

    # Read bank BEFORE
    bank_path = Path(r"C:\Users\22448\Documents\StarCraft II\Banks\NeuroIntegration.SC2Bank")
    before = bank_path.read_text(encoding="utf-8")
    before_chat_flag = '<Key name="chat_message">\n            <Value flag="1" />' in before
    before_active = None
    for line in before.splitlines():
        if '<Key name="active">' in line:
            import re
            m = re.search(r'<Value int="(\d+)"', before)
            if m:
                before_active = int(m.group(1))
    print(f"[*] Bank BEFORE: chat_message_flag={before_chat_flag}, active={before_active}")
    print(f"[*] Bank last modified: {time.ctime(bank_path.stat().st_mtime)}")

    # Send ESC first to clear any modal UI
    print("[*] Sending ESC to clear UI...")
    send_key(VK_ESCAPE, True)
    time.sleep(0.05)
    send_key(VK_ESCAPE, False)
    time.sleep(0.3)

    # Send Enter to open chat
    print("[*] Sending Enter to open chat box...")
    send_enter()

    # Type the message
    msg = "neuro e2e trigger"
    print(f"[*] Typing chat message: '{msg}'")
    type_string(msg)
    time.sleep(0.3)

    # Send Enter to send the chat
    print("[*] Sending Enter to submit chat...")
    send_enter()

    # Wait for SC2 to process the event chain
    print("[*] Waiting 2.0s for SC2 trigger chain...")
    time.sleep(2.0)

    # Read bank AFTER
    after = bank_path.read_text(encoding="utf-8")
    after_chat_flag = '<Key name="chat_message">\n            <Value flag="1" />' in after
    after_active = None
    for line in after.splitlines():
        if '<Key name="active">' in line:
            import re
            m = re.search(r'<Value int="(\d+)"', after)
            if m:
                after_active = int(m.group(1))
    print(f"[*] Bank AFTER: chat_message_flag={after_chat_flag}, active={after_active}")
    print(f"[*] Bank last modified: {time.ctime(bank_path.stat().st_mtime)}")

    # Result
    if before_chat_flag and not after_chat_flag:
        print("[+] SUCCESS! do_action.chat_message was processed (flag cleared)")
        print("[+] ExecuteActionsGlobal_Func ran and displayed the chat message in SC2!")
    elif before_active != after_active:
        print("[+] PARTIAL SUCCESS! active value changed (trigger chain ran)")
        if after_chat_flag:
            print("[-] But do_action.chat_message is still true (unexpected)")
    else:
        print("[-] FAIL: bank state unchanged, trigger chain did not fire")
        print("[-] SC2 may be in a non-interactive state (loading/menu/paused)")


if __name__ == "__main__":
    main()
