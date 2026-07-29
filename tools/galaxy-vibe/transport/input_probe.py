"""Input 传输 Probe — P0 传输闸门测试（最后回退 transport）。

通过模拟键盘输入到 SC2 窗口触发 Kernel（聊天前缀 "!dbg"）。
需要 SC2 窗口焦点，不稳定，仅作最后手段。

使用：
  python -m tools.galaxy-vibe.transport.input_probe --out-dir artifacts/galaxy-vibe/p0-transport
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))


def find_sc2_window() -> dict:
    """查找 SC2 窗口句柄（PowerShell 调用）。"""
    ps_script = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
using System.Diagnostics;
public class Win {
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    public static IntPtr FindSC2() {
        Process[] ps = Process.GetProcessesByName("SC2");
        if (ps.Length == 0) return IntPtr.Zero;
        return ps[0].MainWindowHandle;
    }
}
"@
$h = [Win]::FindSC2()
if ($h -eq [IntPtr]::Zero) { Write-Output "NOT_FOUND" }
else { Write-Output $h.ToString() }
'''
    result = subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps_script],
        capture_output=True, text=True, timeout=5,
    )
    handle = result.stdout.strip()
    return {"found": handle != "NOT_FOUND" and handle != "", "handle": handle}


def run_input_probe(out_dir: Path) -> dict:
    """运行 Input transport probe。

    注：input transport 需要 pyautogui 或类似库，且需要 SC2 窗口焦点。
    PoC 阶段仅检测可行性，不实际发送（避免干扰用户操作）。
    """
    window = find_sc2_window()

    # 检查 pyautogui 是否可用
    try:
        import pyautogui  # type: ignore  # noqa: F401
        has_pyautogui = True
    except ImportError:
        has_pyautogui = False

    verdict = {
        "transport": "input",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "tests": {
            "sc2_window_found": window["found"],
            "pyautogui_available": has_pyautogui,
            "input_feasible": window["found"] and has_pyautogui,
        },
        "verdict": "passed" if (window["found"] and has_pyautogui) else "degraded",
        "notes": (
            "input transport 作为最后回退，需要 SC2 窗口焦点 + pyautogui。"
            "实际运行时会干扰用户操作，仅用于无 SC2API 的场景。"
            if not (window["found"] and has_pyautogui)
            else "input transport 可用，但不推荐用于自动化测试。"
        ),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "input-probe-result.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    return verdict


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=str, default="artifacts/galaxy-vibe/p0-transport")
    args = parser.parse_args()
    result = run_input_probe(Path(args.out_dir))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["verdict"] != "failed" else 1)
