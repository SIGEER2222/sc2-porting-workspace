#!/usr/bin/env python3
"""cmre-webui 端到端冒烟测试。

启动真实 server.py（CMRE_WEBUI_DRY_RUN=1，只写银行不启动 SC2），
验证：
  1. /api/factors 返回从 commander-power-metadata.json 派生的 12 个 Alenger 指挥官（中文名）
  2. /api/mutators 和 /api/voice-packs 返回当前 CMRE 的可选目录
  3. /api/maps 返回 15 张 CMRE 地图
  4. /api/extra-mods 返回非空列表；?commander=Alenger6 过滤掉自动加载的 3 个 mod
  5. GET / 返回 200 且包含 UI 容器（mapName + extra-mods-list）
  6. POST /api/launch（标准模式+无残酷+ + 2 因子，复现"因子无效"场景）
     -> 服务端强制 Mode=2，启动脚本写出银行
  7. 读银行 XML 确认 Mode=2 / ModeInstance=MutatorChallenges /
     MutatorCount=2 / Mutator|1|Id=Avenger / Mutator|2|Id=Barrier(Enhanced=1)，以及双方语音配置
  8. POST /api/launch（自定义模式 + 2 因子）保留 Mode=3，并写入 Chaos|N|Id
"""
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
BANK = Path(r"C:\Users\22448\Documents\StarCraft II\Banks\CMCoopLaunchProfile.SC2Bank")
PORT = 8799
BASE = f"http://127.0.0.1:{PORT}"

results = []


def check(name, cond, detail=""):
    results.append((name, cond, detail))
    mark = "PASS" if cond else "FAIL"
    print(f"[{mark}] {name}" + (f" -> {detail}" if detail else ""))


def wait_ready(timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"{BASE}/api/factors", timeout=2)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def post_launch(payload):
    req = urllib.request.Request(
        f"{BASE}/api/launch",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return json.loads(urllib.request.urlopen(req, timeout=400).read())


def read_bank_keys():
    tree = ET.parse(BANK)
    keys = {}
    for key in tree.getroot().iter("Key"):
        value = key.find("Value")
        if value is None:
            continue
        if "int" in value.attrib:
            keys[key.get("name")] = ("int", value.get("int"))
        elif "string" in value.attrib:
            keys[key.get("name")] = ("string", value.get("string"))
    return keys


def main():
    # 备份银行，测试后还原
    backup = None
    if BANK.exists():
        backup = BANK.with_name(BANK.name + f".smoke-bak-{int(time.time())}")
        shutil.copy(BANK, backup)

    env = dict(os.environ)
    env["CMRE_WEBUI_DRY_RUN"] = "1"
    proc = subprocess.Popen(
        [sys.executable, "server.py", "--port", str(PORT), "--no-browser"],
        cwd=str(SERVER_DIR), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
    )
    try:
        if not wait_ready():
            out, err = proc.communicate(timeout=5)
            print("SERVER FAILED TO START.\nSTDOUT:\n" + out + "\nSTDERR:\n" + err)
            check("server 启动", False)
            return

        # 1) factors — 12 个 Alenger 指挥官（中文名）
        try:
            factors = json.loads(urllib.request.urlopen(f"{BASE}/api/factors", timeout=5).read())
            cmds = factors.get("commanders", [])
            check("factors: 12 Alenger 指挥官", len(cmds) == 12, f"count={len(cmds)}")
            # 每个指挥官必须有 id/label/bank，label 应为中文名（非空、非 "Terran AlengerX" 格式）
            bad = [c for c in cmds if not (isinstance(c, dict) and c.get("id") and c.get("label") and c.get("bank") and c["bank"].startswith("Alenger"))]
            check("factors: 每个指挥官有 id/label/bank 且 bank 以 Alenger 开头", len(bad) == 0, f"bad={bad}")
            # 抽查中文名：应包含"疯批帝国"（Alenger3）
            labels = [c.get("label", "") for c in cmds if isinstance(c, dict)]
            check("factors: 含'疯批帝国'(Alenger3 中文名)", "疯批帝国" in labels, f"labels={labels}")
            # 抽查 runtime_commander 前缀正确：ZergAlenger6 应存在（而非 TerranAlenger6）
            ids = [c["id"] for c in cmds if isinstance(c, dict)]
            check("factors: 含 ZergAlenger6（race 前缀正确）", "ZergAlenger6" in ids, f"ids={ids}")
            check("factors: 不含 TerranAlenger6（race 前缀错误项）", "TerranAlenger6" not in ids, f"ids={ids}")
            modes = {m["id"] for m in factors.get("modes", [])}
            check("factors: 含 3 种模式", modes == {1, 2, 3}, str(modes))
        except Exception as e:
            check("factors 请求", False, str(e))

        # 2) mutators
        try:
            muts = json.loads(urllib.request.urlopen(f"{BASE}/api/mutators", timeout=5).read())
            check("mutators 列表非空", isinstance(muts, list) and len(muts) > 0, f"count={len(muts) if isinstance(muts,list) else 'n/a'}")
            mutator_ids = {mutator.get("id") for mutator in muts if isinstance(mutator, dict)}
            check("mutators: 包含 Avenger 和 Barrier", {"Avenger", "Barrier"}.issubset(mutator_ids), f"sample={sorted(mutator_ids)[:8]}")
        except Exception as e:
            check("mutators 请求", False, str(e))

        # 2a) voice packs
        voice_pack_id = ""
        try:
            voices_resp = json.loads(urllib.request.urlopen(f"{BASE}/api/voice-packs", timeout=5).read())
            voices = voices_resp.get("voicePacks", [])
            check("voice-packs 列表非空", isinstance(voices, list) and len(voices) > 0, f"count={len(voices) if isinstance(voices, list) else 'n/a'}")
            bad_voices = [voice for voice in voices if not isinstance(voice, dict) or not voice.get("id") or not voice.get("name") or voice["id"] == "eSports"]
            check("voice-packs: id/name 完整且排除 eSports", not bad_voices, f"bad={bad_voices}")
            if voices:
                voice_pack_id = voices[0]["id"]
        except Exception as e:
            check("voice-packs 请求", False, str(e))

        # 2b) maps
        try:
            maps_resp = json.loads(urllib.request.urlopen(f"{BASE}/api/maps", timeout=5).read())
            maps_list = maps_resp.get("maps", [])
            check("maps: 返回 15 张 CMRE 地图", len(maps_list) == 15, f"count={len(maps_list)}")
            sample = maps_list[0] if maps_list else {}
            check("maps: 每个元素有 id(含.SC2Map) 和 name",
                  isinstance(sample, dict) and sample.get("id", "").endswith(".SC2Map") and "name" in sample,
                  f"sample={sample}")
            check("maps: 含'亡者之夜'", any(m["id"] == "亡者之夜.SC2Map" for m in maps_list), f"ids={[m['id'] for m in maps_list[:3]]}")
        except Exception as e:
            check("maps 请求", False, str(e))

        # 2c) extra-mods
        try:
            em_resp = json.loads(urllib.request.urlopen(f"{BASE}/api/extra-mods", timeout=5).read())
            em_list = em_resp.get("extraMods", [])
            check("extra-mods: 无过滤返回非空", len(em_list) > 0, f"count={len(em_list)}")
            # 过滤 Alenger6：应排除 Alenger6 / Alenger6Common / Alenger6Adapter
            em_filtered = json.loads(urllib.request.urlopen(f"{BASE}/api/extra-mods?commander=Alenger6", timeout=5).read())
            em_f_list = em_filtered.get("extraMods", [])
            em_f_ids = {m["id"] for m in em_f_list}
            excluded_ok = not (em_f_ids & {"Alenger6", "Alenger6Common", "Alenger6Adapter"})
            check("extra-mods: ?commander=Alenger6 排除自动加载的 3 个 mod", excluded_ok, f"过滤后仍含={em_f_ids & {'Alenger6','Alenger6Common','Alenger6Adapter'}}")
            check("extra-mods: 过滤后数量 < 无过滤数量", len(em_f_list) < len(em_list), f"过滤={len(em_f_list)} 无过滤={len(em_list)}")
        except Exception as e:
            check("extra-mods 请求", False, str(e))

        # 3) index.html
        try:
            html = urllib.request.urlopen(f"{BASE}/", timeout=5).read().decode("utf-8", "replace")
            check("GET / 200 且含 UI 容器",
                  ("id=\"commander\"" in html and "id=\"voicePack\"" in html and "id=\"mutator-list\"" in html and "id=\"mapName\"" in html and "id=\"extra-mods-list\"" in html),
                  f"len={len(html)}")
        except Exception as e:
            check("GET / 请求", False, str(e))

        # 4) launch in the "buggy default" scenario: Standard(1) + Brutal+=0 + 2 mutators
        payload = {
            "commander": "TerranAlenger3",
            "mapName": "亡者之夜.SC2Map",
            "mode": 1,
            "difficultyBase": 0,
            "difficultyPlus": 0,
            "enemy": "",
            "voicePack": voice_pack_id,
            "mutators": [
                {"id": "Avenger", "enhanced": False},
                {"id": "Barrier", "enhanced": True},
            ],
        }
        try:
            resp = post_launch(payload)
            check("launch 成功", resp.get("success") is True, resp.get("error", "")[:120])
            check("launch: 强制 effectiveMode=2", resp.get("effectiveMode") == 2, f"effectiveMode={resp.get('effectiveMode')}")
        except Exception as e:
            check("launch 请求", False, str(e))
            resp = {}

        # 5) read bank
        if BANK.exists():
            keys = read_bank_keys()
            print("  BANK KEYS:", json.dumps(keys, ensure_ascii=False))
            check("bank Mode=2", keys.get("Mode") == ("int", "2"), str(keys.get("Mode")))
            check("bank ModeInstance=MutatorChallenges", keys.get("ModeInstance") == ("string", "MutatorChallenges"), str(keys.get("ModeInstance")))
            check("bank MutatorCount=2", keys.get("MutatorCount") == ("int", "2"), str(keys.get("MutatorCount")))
            check("bank Mutator|1|Id=Avenger", keys.get("Mutator|1|Id") == ("string", "Avenger"), str(keys.get("Mutator|1|Id")))
            check("bank Mutator|2|Id=Barrier", keys.get("Mutator|2|Id") == ("string", "Barrier"), str(keys.get("Mutator|2|Id")))
            check("bank Mutator|2|Enhanced=1", keys.get("Mutator|2|Enhanced") == ("int", "1"), str(keys.get("Mutator|2|Enhanced")))
            check("bank ProfileConfigLocked=1", keys.get("ProfileConfigLocked") == ("int", "1"), str(keys.get("ProfileConfigLocked")))
            check("bank Player|1|CustomizationSaved=1", keys.get("Player|1|CustomizationSaved") == ("int", "1"), str(keys.get("Player|1|CustomizationSaved")))
            check("bank Player|2|CustomizationSaved=1", keys.get("Player|2|CustomizationSaved") == ("int", "1"), str(keys.get("Player|2|CustomizationSaved")))
            check("bank Player|1|VoicePack", keys.get("Player|1|VoicePack") == ("string", voice_pack_id), str(keys.get("Player|1|VoicePack")))
            check("bank Player|2|VoicePack", keys.get("Player|2|VoicePack") == ("string", voice_pack_id), str(keys.get("Player|2|VoicePack")))
        else:
            check("bank 写入", False, "bank 文件不存在")

        # 6) CustomMutators uses the CMRE Chaos queue and must not be coerced to mode 2.
        chaos_payload = {
            "commander": "TerranAlenger3",
            "mapName": "亡者之夜.SC2Map",
            "mode": 3,
            "difficultyBase": 0,
            "difficultyPlus": 0,
            "mutators": [
                {"id": "Avenger", "enhanced": True},
                {"id": "Barrier", "enhanced": False},
            ],
        }
        try:
            chaos_resp = post_launch(chaos_payload)
            check("custom launch 成功", chaos_resp.get("success") is True, chaos_resp.get("error", "")[:120])
            check("custom launch: 保留 effectiveMode=3", chaos_resp.get("effectiveMode") == 3, f"effectiveMode={chaos_resp.get('effectiveMode')}")
        except Exception as e:
            check("custom launch 请求", False, str(e))

        if BANK.exists():
            keys = read_bank_keys()
            print("  CHAOS BANK KEYS:", json.dumps(keys, ensure_ascii=False))
            check("chaos bank Mode=3", keys.get("Mode") == ("int", "3"), str(keys.get("Mode")))
            check("chaos bank ModeInstance=CustomMutators", keys.get("ModeInstance") == ("string", "CustomMutators"), str(keys.get("ModeInstance")))
            check("chaos bank ChaosCount=2", keys.get("ChaosCount") == ("int", "2"), str(keys.get("ChaosCount")))
            check("chaos bank Chaos|1|Id=Avenger", keys.get("Chaos|1|Id") == ("string", "Avenger"), str(keys.get("Chaos|1|Id")))
            check("chaos bank Chaos|2|Id=Barrier", keys.get("Chaos|2|Id") == ("string", "Barrier"), str(keys.get("Chaos|2|Id")))
        else:
            check("chaos bank 写入", False, "bank 文件不存在")

    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        if backup and BANK.exists():
            shutil.copy(backup, BANK)
            backup.unlink(missing_ok=True)
            print("银行已还原为测试前状态")


if __name__ == "__main__":
    main()
    failed = [n for n, c, _ in results if not c]
    print(f"\n==== 结果: {len(results)-len(failed)}/{len(results)} 通过 ====")
    sys.exit(1 if failed else 0)
