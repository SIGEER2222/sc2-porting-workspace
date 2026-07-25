#!/usr/bin/env python3
"""CMRE 亡者之夜 WebUI 后端服务

提供因子（Mode/Difficulty/Enemy/Mutators）选择界面和启动游戏的 HTTP API。
仅使用 Python 标准库，无第三方依赖。

用法:
    python server.py [--port 8767] [--host 127.0.0.1]
"""

import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
WEBUI_DIR = SCRIPT_DIR / "webui"
DATA_DIR = SCRIPT_DIR / "data"
MUTATORS_JSON = DATA_DIR / "mutators.json"
# 配置目录：sc2-porting-workspace/src/config/alenger-mods.json
CONFIG_DIR = SCRIPT_DIR.parents[1] / "src" / "config"
ALENGER_MODS_JSON = CONFIG_DIR / "alenger-mods.json"
LAUNCH_SCRIPT = Path(__file__).resolve().parents[1] / "launchers" / "launch-cmre-alenger.ps1"

# CMRE 框架运行时根目录（Maps/Mods/Shared/scripts）
# SCRIPT_DIR.parents[2] = sc2-porting-workspace/tools/cmre-webui → tools → sc2-porting-workspace → SC2VibeTools
SC2VIBE_ROOT = SCRIPT_DIR.parents[2]
CMRE_RUNTIME_ROOT = SC2VIBE_ROOT / "cmre-runtime"
MAPS_CMRE_DIR = CMRE_RUNTIME_ROOT / "Maps" / "CMRE"
COMMANDER_METADATA_JSON = CMRE_RUNTIME_ROOT / "Shared" / "CommanderPower" / "commander-power-metadata.json"
MODS_7VS1_PACKAGES_DIR = SC2VIBE_ROOT / "sc2-porting-workspace" / "src" / "projects" / "cmre-porting" / "packages" / "Mods" / "7vs1"

# CMRE 因子上限：CMUIX_LAUNCH_PROFILE_MUTATOR_MAX = 20
MUTATOR_MAX = 20

# 指挥官种族前缀（launch-cmre-alenger.ps1 的 -Commander 正则只接受这三种前缀）
COMMANDER_RACES = ["Terran", "Zerg", "Protoss"]

# CMRE Legacy Root：合作指挥官-起义狂潮 仓库根目录。
# launch-cmre-alenger.ps1 默认从 $PSScriptRoot 推导，但本机目录结构是
# SC2VibeTools/sc2-porting-workspace 与 SC2/合作指挥官-起义狂潮 平级（都在 MyMod 下），
# 默认推导会指向不存在的 SC2VibeTools/合作指挥官-起义狂潮，因此必须显式覆盖。
# 可通过环境变量 CMRE_LEGACY_ROOT 覆盖默认值。
DEFAULT_LEGACY_ROOT = r"e:\Code\MyMod\SC2\合作指挥官-起义狂潮"
LEGACY_ROOT = os.environ.get("CMRE_LEGACY_ROOT", DEFAULT_LEGACY_ROOT)

# 因子元数据
FACTORS_DATA = {
    "modes": [
        {"id": 1, "name": "标准模式", "description": "正常合作模式，无突变因子"},
        {"id": 2, "name": "突变挑战", "description": "突变挑战模式，可启用突变因子"},
        {"id": 3, "name": "自定义模式", "description": "自定义模式，支持混沌循环"},
    ],
    "difficultyBase": {"min": 0, "max": 5, "default": 0, "name": "基础难度"},
    "difficultyPlus": {"min": 0, "max": 12, "default": 0, "name": "残酷+等级"},
    "enemies": [
        {"id": "", "name": "默认", "description": "使用地图默认敌方阵营"},
        {"id": "ZergAmonSwarm", "name": "虫族（埃蒙虫群）", "description": "亡者之夜默认敌方"},
        {"id": "ProtossCorruptedTemplar", "name": "星灵（堕落圣堂）", "description": "堕落星灵阵营"},
    ],
    "commanders": [
        "TerranAlenger3", "ZergAlenger3", "ProtossAlenger3",
    ],
}


def load_maps():
    """扫描 cmre-runtime/Maps/CMRE/ 目录，返回 [{id, name}]。

    id = 文件名（含 .SC2Map），name = 去掉 .SC2Map 扩展名的显示名。
    按 name 排序。目录不存在时返回空列表。
    """
    if not MAPS_CMRE_DIR.exists():
        print(f"[warn] CMRE 地图目录不存在: {MAPS_CMRE_DIR}")
        return []
    maps = []
    for entry in sorted(MAPS_CMRE_DIR.iterdir()):
        if entry.is_dir() and entry.name.endswith(".SC2Map"):
            maps.append({"id": entry.name, "name": entry.name[:-len(".SC2Map")]})
    return maps


def load_extra_mods(bank_commander=""):
    """扫描 packages/Mods/7vs1/ 目录，返回 [{id, name}]。

    若提供 bank_commander（如 "Alenger6"），从 alenger-mods.json 的
    commanderToAlenger[bank_commander] 查出该指挥官会自动加载的 mod 包，
    从结果中排除它们。id = name = 目录名去掉 .SC2Mod 后缀。按 name 排序。
    """
    if not MODS_7VS1_PACKAGES_DIR.exists():
        print(f"[warn] 7vs1 mod 包目录不存在: {MODS_7VS1_PACKAGES_DIR}")
        return []

    excluded = set()
    if bank_commander:
        try:
            if ALENGER_MODS_JSON.exists():
                data = json.loads(ALENGER_MODS_JSON.read_text(encoding="utf-8"))
                mapping = data.get("commanderToAlenger", {})
                excluded = set(mapping.get(bank_commander, []))
        except Exception as exc:
            print(f"[warn] 读取 alenger-mods.json 失败（extra-mods 过滤跳过）: {exc}")

    mods = []
    for entry in sorted(MODS_7VS1_PACKAGES_DIR.iterdir()):
        if entry.is_dir() and entry.name.endswith(".SC2Mod"):
            mod_id = entry.name[:-len(".SC2Mod")]
            if mod_id in excluded:
                continue
            mods.append({"id": mod_id, "name": mod_id})
    return mods


def load_commanders():
    """从 commander-power-metadata.json 读取指挥官列表，返回 [{id, label, bank}]。

    id = runtime_commander（如 TerranAlenger3，race 前缀已正确）
    label = display_name（中文名，如"疯批帝国"）
    bank = bank_commander（如 Alenger3，供 /api/extra-mods 过滤使用）

    只返回 bank_commander 以 "Alenger" 开头的条目。metadata 不存在时回退到默认。
    """
    default_cmd = "TerranAlenger3"
    try:
        if COMMANDER_METADATA_JSON.exists():
            data = json.loads(COMMANDER_METADATA_JSON.read_text(encoding="utf-8"))
            commanders = []
            for cmd in data.get("commanders", []):
                bank = cmd.get("bank_commander", "")
                if not bank.startswith("Alenger"):
                    continue
                runtime = cmd.get("runtime_commander", "")
                display = cmd.get("display_name", "") or runtime
                if not runtime:
                    continue
                commanders.append({"id": runtime, "label": display, "bank": bank})
            if commanders:
                return commanders
            print(f"[warn] metadata 中无 Alenger 指挥官，回退默认: {COMMANDER_METADATA_JSON}")
    except Exception as exc:  # noqa: BLE001 - 解析失败则回退到默认
        print(f"[warn] 读取 commander-power-metadata.json 失败，使用默认: {exc}")
    return [{"id": default_cmd, "label": "疯批帝国", "bank": "Alenger3"}]


def build_factors_data():
    """构造 /api/factors 返回数据，指挥官每次实时从配置派生。"""
    data = dict(FACTORS_DATA)
    data["commanders"] = load_commanders()
    return data


class CmreWebUIHandler(SimpleHTTPRequestHandler):
    """处理 WebUI 的 HTTP 请求。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEBUI_DIR), **kwargs)

    def _send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        if self.path == "/api/mutators":
            self._handle_get_mutators()
            return
        if self.path == "/api/factors":
            self._send_json(build_factors_data())
            return
        if self.path == "/api/maps":
            self._send_json({"maps": load_maps()})
            return
        if self.path.startswith("/api/extra-mods"):
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            bank = qs.get("commander", [""])[0]
            self._send_json({"extraMods": load_extra_mods(bank)})
            return
        if self.path == "/" or self.path == "":
            self.path = "/index.html"
        return super().do_GET()

    def _handle_get_mutators(self):
        if MUTATORS_JSON.exists():
            content = MUTATORS_JSON.read_text(encoding="utf-8")
            self._send_json(json.loads(content))
        else:
            self._send_json([], 200)

    def do_POST(self):
        if self.path == "/api/launch":
            self._handle_launch()
            return
        self._send_json({"success": False, "error": "未知端点"}, 404)

    def _handle_launch(self):
        body = self._read_body()
        commander = body.get("commander", "TerranAlenger3")
        map_name = body.get("mapName", "亡者之夜.SC2Map")
        mode = int(body.get("mode", 1))
        difficulty_base = int(body.get("difficultyBase", 0))
        difficulty_plus = int(body.get("difficultyPlus", 0))
        enemy = body.get("enemy", "")
        mutators = body.get("mutators", []) or []
        extra_mods = body.get("extraMods", []) or []

        # 因子数量上限保护：CMUIX_LAUNCH_PROFILE_MUTATOR_MAX = 20
        capped = False
        if len(mutators) > MUTATOR_MAX:
            mutators = mutators[:MUTATOR_MAX]
            capped = True

        # 因子生效关键修复（"选择的因子无效"根因）：
        # CMRE 仅在 Mode=2 (MutatorChallenges) 或 Mode=1 (Standard) 且 Brutal+ > 0 时
        # 才会读取银行中的 Mutator|N|Id 并启用对应因子。若用户勾选了因子但当前处于
        # 标准模式且残酷+=0（UI 默认状态），或处于自定义模式，因子会被静默丢弃。
        # 这里在后端强制切换到 MutatorChallenges，确保所选因子一定生效。
        if mutators:
            if (mode == 1 and difficulty_plus == 0) or mode == 3:
                mode = 2

        if not LAUNCH_SCRIPT.exists():
            self._send_json(
                {"success": False, "error": f"启动脚本不存在: {LAUNCH_SCRIPT}"}, 500
            )
            return

        # 构建 mutators 参数：逗号分隔的 id 列表，可选 ":enhanced" 后缀
        mutator_str = ",".join(
            f"{m['id']}:enhanced" if m.get("enhanced") else m["id"]
            for m in mutators
            if m.get("id")
        )

        args = [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(LAUNCH_SCRIPT),
            "-MapName",
            map_name,
            "-Commander",
            commander,
            "-LegacyRootOverride",
            LEGACY_ROOT,
            "-Mode",
            str(mode),
            "-DifficultyBase",
            str(difficulty_base),
            "-DifficultyPlus",
            str(difficulty_plus),
        ]
        if enemy:
            args.extend(["-Enemy", enemy])
        if mutator_str:
            args.extend(["-Mutators", mutator_str])
        if extra_mods:
            extra_str = ",".join(m for m in extra_mods if m)
            if extra_str:
                args.extend(["-ExtraMods", extra_str])

        # 测试/CI 用：设置 CMRE_WEBUI_DRY_RUN 时追加 -NoLaunch，
        # 只暂存地图 + 写银行、不启动 SC2。正常启动不受影响。
        if os.environ.get("CMRE_WEBUI_DRY_RUN"):
            args.append("-NoLaunch")

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="gbk",
                errors="replace",
            )
            # 等待上限须大于 wait-for-game-ready.ps1 的 MaxWaitSeconds(600)，
            # 否则 SC2 正常加载（~340s+20s grace）时会被误判超时。
            stdout, stderr = proc.communicate(timeout=720)

            if proc.returncode == 0:
                self._send_json(
                    {
                        "success": True,
                        "message": "SC2 已启动",
                        "effectiveMode": mode,
                        "mutatorsCapped": capped,
                        "output": stdout[-800:] if stdout else "",
                    }
                )
            else:
                self._send_json(
                    {
                        "success": False,
                        "error": f"启动脚本退出码 {proc.returncode}",
                        "output": stdout[-800:] if stdout else "",
                        "stderr": stderr[-800:] if stderr else "",
                    },
                    500,
                )
        except subprocess.TimeoutExpired:
            proc.kill()
            self._send_json({"success": False, "error": "启动脚本超时（720s）"}, 504)
        except Exception as e:
            self._send_json({"success": False, "error": str(e)}, 500)

    def log_message(self, format, *args):
        sys.stderr.write(f"[{self.log_date_time_string()}] {format % args}\n")


def open_browser_delayed(url, delay=1.0):
    import time
    time.sleep(delay)
    webbrowser.open(url)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="CMRE 亡者之夜 WebUI 后端服务")
    parser.add_argument("--port", type=int, default=8767, help="监听端口")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), CmreWebUIHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"CMRE 亡者之夜 WebUI 服务已启动: {url}")
    print(f"WebUI 目录: {WEBUI_DIR}")
    print(f"Mutator 数据: {MUTATORS_JSON}")
    print(f"启动脚本: {LAUNCH_SCRIPT}")
    print("按 Ctrl+C 停止服务")

    if not args.no_browser:
        threading.Thread(target=open_browser_delayed, args=(url,), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
        server.server_close()


if __name__ == "__main__":
    main()
