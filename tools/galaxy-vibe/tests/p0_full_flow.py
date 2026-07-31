"""P0 完整验收：连接已有 SC2 → CreateGame → JoinGame → MapCommand → 银行轮询"""
import asyncio, json, os, sys, time, socket
from pathlib import Path
from xml.etree import ElementTree as ET

REPO_ROOT = Path(r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = "python"
from s2clientprotocol import sc2api_pb2 as sc_pb
import aiohttp

MAP = r"E:\SC2\SC2new\StarCraft II\Maps\亡者之夜_p0_default_packed.SC2Map"
PORT = 5000
BANK_FILE = Path.home() / "Documents/StarCraft II/Banks/GalaxyVibe.SC2Bank"

def log(m): print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)

def port_open(p):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try: s.connect(("127.0.0.1", p)); s.close(); return True
    except: return False

def read_bank():
    if not BANK_FILE.exists(): return None
    try:
        tree = ET.parse(BANK_FILE)
        root = tree.getroot()
        sections = {}
        for sec in root.findall("Section"):
            sname = sec.get("name", "")
            keys = {}
            for k in sec.findall("Key"):
                kn = k.get("name", "")
                v = k.find("Value")
                if v is not None: keys[kn] = dict(v.attrib)
            sections[sname] = keys
        return sections
    except Exception as e:
        return {"error": str(e)}

async def send_recv(ws, req, timeout=30):
    await ws.send_bytes(req.SerializeToString())
    data = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    if isinstance(data, str): data = data.encode("utf-8")
    resp = sc_pb.Response()
    resp.ParseFromString(data)
    return resp

async def main():
    log("=== P0 完整验收 ===")

    # 0. 检查端口
    if not port_open(PORT):
        log(f"FAILED: 端口 {PORT} 未开放，请先启动 SC2")
        return {"status": "FAIL", "reason": "port closed"}

    # 备份旧银行
    if BANK_FILE.exists():
        bak = BANK_FILE.with_suffix(f".SC2Bank.bak-{int(time.time())}")
        BANK_FILE.rename(bak)
        log(f"旧银行备份: {bak.name}")

    log(f"[1] 连接 ws://127.0.0.1:{PORT}/sc2api ...")
    try:
        session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=300))
        ws = await session.ws_connect(f"ws://127.0.0.1:{PORT}/sc2api")
    except Exception as e:
        log(f"连接失败: {e}")
        return {"status": "FAIL", "reason": f"connect fail: {e}"}

    try:
        # 2. Ping
        r = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
        log(f"[2] Ping: has_ping={r.HasField('ping')}")

        # 3. LeaveGame（清理之前状态，忽略错误）
        try:
            await send_recv(ws, sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), timeout=10)
            log("[3] LeaveGame sent (清理之前状态)")
        except Exception:
            log("[3] LeaveGame skipped (not in game)")
        await asyncio.sleep(2)

        # 4. CreateGame
        log(f"[4] CreateGame: {Path(MAP).name}")
        local_map = sc_pb.LocalMap(map_path=MAP)
        req = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=local_map,
            player_setup=[
                sc_pb.PlayerSetup(type=1, race=1, player_name="P1"),
                sc_pb.PlayerSetup(type=2, race=1, difficulty=2, player_name="AI"),
            ],
            realtime=True,
        ))
        r = await send_recv(ws, req, timeout=180)
        if r.error:
            log(f"  CreateGame error: {list(r.error)}")
        if r.HasField('create_game') and r.create_game.HasField('error'):
            log(f"  CreateGame failed: {r.create_game.error} details={r.create_game.error_details}")
            return {"status": "FAIL", "reason": f"CreateGame failed: {r.create_game.error}"}
        log("  CreateGame OK!")

        # 5. 等地图加载（最多 60s）
        log("[5] 等地图加载（最多 60s）...")
        loaded = False
        for i in range(30):
            await asyncio.sleep(2)
            try:
                r = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=10)
                if r.HasField('observation') and r.observation.HasField('observation'):
                    units = len(r.observation.observation.raw_data.units)
                    game_loop = r.observation.observation.game_loop
                    log(f"  [{i*2}s] units={units} game_loop={game_loop}")
                    if units > 0:
                        loaded = True
                        break
            except Exception as e:
                log(f"  [{i*2}s] observation error: {e}")

        # 6. JoinGame（如果还没在游戏中）
        if not loaded:
            log("[6] JoinGame (尝试加入游戏)...")
            try:
                r = await send_recv(ws, sc_pb.Request(join_game=sc_pb.RequestJoinGame(
                    race=1, options=sc_pb.InterfaceOptions(raw=True),
                )), timeout=60)
                if r.error:
                    log(f"  JoinGame error: {list(r.error)}")
                if r.HasField('join_game') and r.join_game.HasField('error'):
                    log(f"  JoinGame failed: {r.join_game.error} details={r.join_game.error_details}")
                else:
                    log(f"  JoinGame OK! player_id={r.join_game.player_id}")
            except Exception as e:
                log(f"  JoinGame exception: {e}")

            # 等 15s 让脚本初始化
            log("  等 15s 让脚本初始化...")
            await asyncio.sleep(15)

        # 7. Observation 检查
        try:
            r = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=15)
            if r.HasField('observation') and r.observation.HasField('observation'):
                units = len(r.observation.observation.raw_data.units)
                game_loop = r.observation.observation.game_loop
                log(f"[7] In game: units={units} game_loop={game_loop}")
                if units == 0:
                    log("  WARNING: 0 units，地图脚本可能未初始化")
            else:
                log(f"[7] Not in game? error={list(r.error) if r.error else 'none'}")
        except Exception as e:
            log(f"[7] Observation failed: {e}")

        # 8. 发送 MapCommand "dbg ping xxx"
        run_id = f"p0_{int(time.time())}"
        cmd = f"dbg ping {run_id}"
        log(f"[8] 发送 MapCommand: {cmd}")
        try:
            r = await send_recv(ws, sc_pb.Request(map_command=sc_pb.RequestMapCommand(trigger_cmd=cmd)), timeout=10)
            log(f"  resp: status={r.status} error={list(r.error) if r.error else 'none'}")
        except Exception as e:
            log(f"  MapCommand exception: {e}")

        # 9. 轮询银行响应
        log("[9] 轮询银行响应（最多 20s）...")
        t0 = time.time()
        found = False
        bank_data = None
        while time.time() - t0 < 20:
            bank_data = read_bank()
            if bank_data:
                for sec_name in ("response", "vibe", "request", "heartbeat", "system"):
                    sec = bank_data.get(sec_name, {})
                    if run_id in sec:
                        log(f"  FOUND in [{sec_name}]! latency={time.time()-t0:.3f}s")
                        log(f"  value: {sec[run_id]}")
                        found = True
                        break
                if found: break
            await asyncio.sleep(0.5)

        if not found:
            log("  TIMEOUT: 20s 内未在银行找到响应")
            if bank_data:
                log(f"  银行内容:\n{json.dumps(bank_data, ensure_ascii=False, indent=2)[:3000]}")
            else:
                log(f"  银行文件不存在: {BANK_FILE}")
            return {"status": "FAIL", "reason": "no bank response",
                    "run_id": run_id, "bank": bank_data}

        return {
            "status": "PASS", "run_id": run_id,
            "latency_sec": round(time.time() - t0, 3),
            "bank_file": str(BANK_FILE),
            "bank_data": bank_data,
        }
    finally:
        try:
            await ws.close()
            await session.close()
        except Exception:
            pass

if __name__ == "__main__":
    result = asyncio.run(main())
    print("\n=== RESULT ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    sys.exit(0 if result.get("status") == "PASS" else 1)
