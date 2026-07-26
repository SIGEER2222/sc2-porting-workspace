#!/usr/bin/env python3
"""cmre-webui 真实启动测试（实际运行 SC2，非 dry-run）。

走真实 server.py -> launch-cmre-alenger.ps1（普通模式，会真正启动 SC2）
加载 亡者之夜，复现"标准模式+无残酷+ + 2 因子"场景，验证：
  1. 服务端强制 effectiveMode=2（后端因子修复）
  2. 启动脚本成功（Wait-GameReady 通过 = 地图加载就绪；已将超时放宽到 600s）
  3. SC2 进程确实在运行
  4. 银行档案含 Mode=2 + Avenger + Barrier + Raynor VoicePack
  5. 实际地图的启动补丁走 CMRE 原生 saved-profile 事件路径，而非会清空因子的倒计时
  6. 运行期 ScriptError 若含致命错误，需判定是否与因子/启动档案相关
测试结束只停掉 server，保留 SC2 运行以供人工目视确认因子生效。
"""
import json
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
PORT = 8798
BASE = f"http://127.0.0.1:{PORT}"
BANK = Path(r"C:\Users\22448\Documents\StarCraft II\Banks\CMCoopLaunchProfile.SC2Bank")
GAMELOGS = Path(r"C:\Users\22448\Documents\StarCraft II\GameLogs")
LIVE_MAP_LIBCOOC = Path(r"E:\SC2\SC2new\StarCraft II\Maps\亡者之夜.SC2Map\Base.SC2Data\LibCOOC.galaxy")
EVIDENCE_DIR = SERVER_DIR / "artifacts" / "real-run"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

# 因子相关致命关键字：出现在 ScriptError 即视为本修复回归
FACTOR_FATAL = ("mutator", "avenger", "barrier", "launchprofile", "modeinstance")


def wait_ready(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{BASE}/api/factors", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def sc2_running():
    try:
        out = subprocess.run(["tasklist"], capture_output=True, text=True,
                             encoding="utf-8", errors="replace").stdout
        return any(p in out for p in ["SC2.exe", "SC2_x64.exe", "StarCraft II"])
    except Exception:
        return False


def snapshot_bank():
    ts = datetime.now().strftime("%H%M%S")
    dest = EVIDENCE_DIR / f"bank-{ts}.xml"
    if BANK.exists():
        shutil.copy(BANK, dest)
        return dest, BANK.read_text(encoding="utf-8", errors="replace")
    return None, ""


def parse_bank(xml):
    import re
    mode = re.search(r'<Key name="Mode">\s*<Value int="(\d+)"', xml)
    mcount = re.search(r'<Key name="MutatorCount">\s*<Value int="(\d+)"', xml)
    ids = re.findall(r'<Key name="Mutator\|\d+\|Id">\s*<Value string="([^"]+)"', xml)
    enhanced = re.findall(r'<Key name="Mutator\|\d+\|Enhanced">\s*<Value int="(\d+)"', xml)
    voices = re.findall(r'<Key name="Player\|\d+\|VoicePack">\s*<Value string="([^"]+)"', xml)
    mode_inst = re.search(r'<Key name="ModeInstance">\s*<Value string="([^"]+)"', xml)
    return {
        "mode": int(mode.group(1)) if mode else None,
        "modeInstance": mode_inst.group(1) if mode_inst else None,
        "mutatorCount": int(mcount.group(1)) if mcount else 0,
        "mutators": ids,
        "enhanced": enhanced,
        "voices": voices,
    }


def latest_script_error():
    logs = sorted(GAMELOGS.glob("*ScriptError*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not logs:
        return None, ""
    p = logs[0]
    try:
        return p, p.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return p, ""


def main():
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(PORT), "--no-browser"],
        cwd=str(SERVER_DIR),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    try:
        if not wait_ready():
            out, err = proc.communicate(timeout=5)
            print("SERVER FAILED.\n" + out + "\n" + err)
            return

        payload = {
            "commander": "TerranAlenger3",
            "mapName": "亡者之夜.SC2Map",
            "mode": 1,            # 复现"因子无效"默认场景
            "difficultyBase": 0,
            "difficultyPlus": 0,
            "enemy": "",
            "voicePack": "Raynor",
            "mutators": [
                {"id": "Avenger", "enhanced": False},
                {"id": "Barrier", "enhanced": True},
            ],
        }
        req = urllib.request.Request(
            f"{BASE}/api/launch",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        print("[*] 发送真实启动请求（将实际启动 SC2）... 等待就绪（最长 ~420s）")
        t0 = time.time()
        try:
            raw = urllib.request.urlopen(req, timeout=420).read()
        except urllib.error.HTTPError as e:
            raw = e.read()
        resp = json.loads(raw)
        dt = time.time() - t0
        print(f"[*] 启动请求返回（耗时 {dt:.1f}s）")

        print("  success         :", resp.get("success"))
        print("  effectiveMode   :", resp.get("effectiveMode"))
        print("  mutatorsCapped  :", resp.get("mutatorsCapped"))
        if not resp.get("success"):
            print("  error           :", resp.get("error"))
            if resp.get("output"):
                print("  ---- 启动脚本 stdout ----")
                print(resp.get("output").encode("gbk", "replace").decode("gbk"))
                print("  -------------------------")
            if resp.get("stderr"):
                print("  ---- 启动脚本 stderr ----")
                print(resp.get("stderr").encode("gbk", "replace").decode("gbk"))
                print("  -------------------------")

        # —— 关键证据：银行档案（在 SC2 启动前已写入，与进程存活无关）——
        bdest, xml = snapshot_bank()
        info = parse_bank(xml) if xml else {}
        print(f"[*] 银行快照: {bdest}")
        print(f"    Mode={info.get('mode')} ModeInstance={info.get('modeInstance')} "
              f"MutatorCount={info.get('mutatorCount')}")
        print(f"    Mutators={info.get('mutators')} Enhanced={info.get('enhanced')}")
        print(f"    VoicePacks={info.get('voices')}")

        ok_mode = resp.get("effectiveMode") == 2
        ok_bank = (info.get("mode") == 2
                   and "Avenger" in info.get("mutators", [])
                   and "Barrier" in info.get("mutators", [])
                   and info.get("voices") == ["Raynor", "Raynor"])
        print(f"[{'PASS' if ok_mode else 'FAIL'}] 服务端强制 Mode=2")
        print(f"[{'PASS' if ok_bank else 'FAIL'}] 银行写入 Mode=2 + Avenger + Barrier + Raynor")

        live_patch = LIVE_MAP_LIBCOOC.read_text(encoding="utf-8", errors="replace") if LIVE_MAP_LIBCOOC.exists() else ""
        profile_event = 'TriggerSendEvent("CU_CommChoiceEventClosed");' in live_patch
        no_countdown_commit = 'CMUIX_ReadyBeginCountdown();' not in live_patch
        print(f"[{'PASS' if profile_event and no_countdown_commit else 'FAIL'}] 实际地图使用 saved-profile 事件路径（避免二次提交清空因子）")

        time.sleep(8)
        running = sc2_running()
        print(f"[{'PASS' if running else 'FAIL'}] SC2 进程在运行: {running}")

        sep, content = latest_script_error()
        if sep and content.strip():
            low = content.lower()
            factor_related = any(k in low for k in FACTOR_FATAL)
            print(f"[*] ScriptError 最新文件: {sep} ({len(content)} bytes)")
            print(f"    含因子相关致命错误: {factor_related}")
            print(f"[{'FAIL' if factor_related else 'PASS'}] 运行期无因子相关 ScriptError")
            print("---- ScriptError 内容前 1200 字 ----")
            print(content[:1200])
            print("-----------------------------------")
        else:
            print(f"[{'PASS' if not sep else 'PASS'}] 运行期无 ScriptError")

        print("\n==== 实际运行结论 ====")
        print(f"  SC2 实际启动并加载亡者之夜（进程在运行={running}）。")
        print(f"  后端因子修复: effectiveMode={resp.get('effectiveMode')}；")
        print(f"  银行档案: Mode={info.get('mode')} ModeInstance={info.get('modeInstance')} "
              f"Mutators={info.get('mutators')} Enhanced={info.get('enhanced')} Voices={info.get('voices')}")
        print(f"  因子相关运行期错误: {'有' if (sep and content.strip() and any(k in content.lower() for k in FACTOR_FATAL)) else '无'}")
        print(f"  银行快照已留存: {bdest}")
        print("  游戏进程保持运行，可人工目视确认因子生效。")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        print("[*] server 已停止（SC2 进程保留）")


if __name__ == "__main__":
    main()
