"""Directly write do_action section to bank and bump active.

Bypasses Integration's /api/action/trigger endpoint. Relies on NeuroActionPoller
(periodic 0.5s trigger in MapScript.galaxy) to detect do_action flag and call
TriggerSendEvent("execute_actions_global"), which causes ExecuteActionsGlobal_Func
to display the chat message and clear the flag.

Flow:
1. Read current bank.
2. Insert/refresh do_action section (chat_message=true, chat_message_arg_1=msg).
3. Bump active (0 -> 1).
4. Write back via trae-write-bin.ps1.
5. Poll bank for up to ~5s waiting for chat_message flag to flip to false
   (evidence that ExecuteActionsGlobal_Func ran).
"""
import os
import re
import subprocess
import sys
import time

BANK_PATH = r"C:\Users\22448\Documents\StarCraft II\Banks\NeuroIntegration.SC2Bank"
TMP_PATH = os.path.join(os.environ["TEMP"], "neuro_bank_direct.xml")
WRITE_BIN = r"c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-write-bin.ps1"


def read_bank():
    with open(BANK_PATH, "r", encoding="utf-8") as f:
        return f.read()


def write_bank(content):
    with open(TMP_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         WRITE_BIN, BANK_PATH, "-FromTmp", TMP_PATH],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print("trae-write-bin failed:", result.stderr)
        sys.exit(1)


def replace_or_insert_section(content, section_name, section_body):
    """Replace existing <Section name="...">...</Section> or insert before </Bank>."""
    pattern = re.compile(
        rf'<Section name="{re.escape(section_name)}">.*?</Section>',
        re.DOTALL
    )
    if pattern.search(content):
        return pattern.sub(section_body, content, count=1)
    # Insert before </Bank>
    return content.replace("</Bank>", f"    {section_body}\n</Bank>")


def bump_active(content):
    m = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"\s*/>', content)
    if not m:
        raise RuntimeError("active key not found")
    old_value = int(m.group(1))
    new_value = old_value + 1 if old_value < 2000000000 else 1
    old_block = m.group(0)
    new_block = old_block.replace(
        f'<Value int="{old_value}"', f'<Value int="{new_value}"'
    )
    return content.replace(old_block, new_block, 1), old_value, new_value


def build_do_action_section(msg):
    return (
        '<Section name="do_action">\n'
        '        <Key name="chat_message">\n'
        '            <Value flag="1"/>\n'
        '        </Key>\n'
        '        <Key name="chat_message_arg_1">\n'
        f'            <Value string="{msg}"/>\n'
        '        </Key>\n'
        '        <Key name="select_unit_type">\n'
        '            <Value flag="0"/>\n'
        '        </Key>\n'
        '        <Key name="order_selected">\n'
        '            <Value flag="0"/>\n'
        '        </Key>\n'
        '    </Section>'
    )


def check_chat_flag(content):
    m = re.search(
        r'<Section name="do_action">.*?<Key name="chat_message">\s*<Value flag="(\d)"\s*/>',
        content, re.DOTALL
    )
    return m.group(1) if m else None


def main():
    msg = f"blank_test_neuro e2e verified at {time.strftime('%H:%M:%S')}"
    print(f"Message: {msg}")

    print("=== Step 1: read bank ===")
    content = read_bank()
    print(f"  bank size: {len(content)} bytes")

    print("=== Step 2: insert/refresh do_action section ===")
    section = build_do_action_section(msg)
    content = replace_or_insert_section(content, "do_action", section)

    print("=== Step 3: bump active ===")
    content, old_a, new_a = bump_active(content)
    print(f"  active {old_a} -> {new_a}")

    print("=== Step 4: write bank via trae-write-bin.ps1 ===")
    write_bank(content)
    print(f"  bank written")

    print("=== Step 5: poll for chat_message flag flip (up to 6s) ===")
    deadline = time.time() + 6.0
    last_flag = None
    while time.time() < deadline:
        time.sleep(0.5)
        c = read_bank()
        flag = check_chat_flag(c)
        # Also show active value
        m = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"\s*/>', c)
        active_now = m.group(1) if m else "?"
        print(f"  t={time.strftime('%H:%M:%S')} chat_message flag={flag} active={active_now}")
        if flag == "0":
            print("SUCCESS: chat_message flag cleared by ExecuteActionsGlobal_Func")
            return 0
        last_flag = flag

    print(f"FAILURE: chat_message flag still {last_flag} after 6s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
