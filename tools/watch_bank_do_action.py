"""Write do_action to bank and watch file mtime + chat_message flag for 10s.

This proves whether SC2's NeuroActionPoller is running and whether
ExecuteActionsGlobal_Func successfully clears the chat_message flag.
"""
import os
import re
import subprocess
import sys
import time

BANK_PATH = r"C:\Users\22448\Documents\StarCraft II\Banks\NeuroIntegration.SC2Bank"
TMP_PATH = os.path.join(os.environ["TEMP"], "neuro_bank_watch.xml")
WRITE_BIN = r"c:\Users\22448\.trae-cn\skills\file-ops\scripts\trae-write-bin.ps1"


def read_bank():
    with open(BANK_PATH, "r", encoding="utf-8") as f:
        return f.read()


def write_bank(content):
    with open(TMP_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    r = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
         WRITE_BIN, BANK_PATH, "-FromTmp", TMP_PATH],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print("write failed:", r.stderr)
        sys.exit(1)


def replace_or_insert_section(content, section_name, section_body):
    pattern = re.compile(
        rf'<Section name="{re.escape(section_name)}">.*?</Section>',
        re.DOTALL
    )
    if pattern.search(content):
        return pattern.sub(section_body, content, count=1)
    return content.replace("</Bank>", f"    {section_body}\n</Bank>")


def bump_active(content):
    m = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"\s*/?>', content)
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
        '            <Value flag="1" />\n'
        '        </Key>\n'
        '        <Key name="chat_message_arg_1">\n'
        f'            <Value string="{msg}" />\n'
        '        </Key>\n'
        '        <Key name="select_unit_type">\n'
        '            <Value flag="0" />\n'
        '        </Key>\n'
        '        <Key name="order_selected">\n'
        '            <Value flag="0" />\n'
        '        </Key>\n'
        '    </Section>'
    )


def get_status(content):
    """Return (chat_flag, active_value, mtime)."""
    m_flag = re.search(
        r'<Section name="do_action">.*?<Key name="chat_message">\s*<Value flag="(\d)"',
        content, re.DOTALL
    )
    flag = m_flag.group(1) if m_flag else None
    m_act = re.search(r'<Key name="active">\s*<Value int="(-?\d+)"', content)
    active = m_act.group(1) if m_act else "?"
    mtime = os.path.getmtime(BANK_PATH)
    return flag, active, mtime


def main():
    msg = f"blank_test_neuro e2e verified at {time.strftime('%H:%M:%S')}"
    print(f"Message: {msg}")

    content = read_bank()
    flag0, active0, mtime0 = get_status(content)
    print(f"BEFORE: chat_flag={flag0} active={active0} mtime={time.strftime('%H:%M:%S', time.localtime(mtime0))}")

    # Insert do_action + bump active
    content = replace_or_insert_section(content, "do_action", build_do_action_section(msg))
    content, old_a, new_a = bump_active(content)
    print(f"WRITE: active {old_a} -> {new_a}")
    write_bank(content)

    print("POLL for 10s:")
    start = time.time()
    last_mtime = mtime0
    while time.time() - start < 10:
        time.sleep(0.5)
        try:
            c = read_bank()
        except Exception as e:
            print(f"  read error: {e}")
            continue
        flag, active, mtime = get_status(c)
        mtime_str = time.strftime('%H:%M:%S', time.localtime(mtime))
        mtime_changed = "MTIME-CHANGED" if mtime != last_mtime else ""
        if mtime != last_mtime:
            last_mtime = mtime
        print(f"  t={time.strftime('%H:%M:%S')} chat_flag={flag} active={active} mtime={mtime_str} {mtime_changed}")
        if flag == "0":
            print("SUCCESS: chat_message flag cleared by ExecuteActionsGlobal_Func")
            return 0

    print("FAILURE: chat_message flag still set after 10s")
    return 1


if __name__ == "__main__":
    sys.exit(main())
