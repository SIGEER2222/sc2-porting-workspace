"""轮询 SC2 API status，每 10 秒一次，持续 180 秒，观察 launched→menu 转换。"""
import asyncio, aiohttp, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "reference" / "SC2-Neuro-API-Integration"))
from s2clientprotocol import sc2api_pb2 as sc_pb

NAMES = {1: "launched", 2: "menu", 3: "in_game", 4: "in_replay"}

async def poll():
    url = "ws://127.0.0.1:5000/sc2api"
    start = time.time()
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(url, max_msg_size=0) as ws:
            print(f"轮询 SC2 status（每 10 秒，持续 180 秒）...")
            prev_status = None
            for i in range(18):
                # ping
                await ws.send_bytes(sc_pb.Request(ping=sc_pb.RequestPing()).SerializeToString())
                r = sc_pb.Response(); r.ParseFromString(await ws.receive_bytes())
                # observation 查 status
                await ws.send_bytes(sc_pb.Request(observation=sc_pb.RequestObservation()).SerializeToString())
                r = sc_pb.Response(); r.ParseFromString(await ws.receive_bytes())
                st = r.status if r.HasField("status") else 0
                err = list(r.error) if r.error else []
                elapsed = int(time.time() - start)
                changed = " *** 变化!" if st != prev_status else ""
                print(f"  [{elapsed:3d}s] status={st} ({NAMES.get(st, '?')}) error={err}{changed}")
                prev_status = st
                if st == 2:
                    print(f"  ✓ 已到达 menu 状态！耗时 {elapsed} 秒")
                    return 0
                if st == 3:
                    print(f"  已在 in_game 状态")
                    return 0
                await asyncio.sleep(10)
            print(f"✗ 180 秒内未到达 menu 状态（最终 status={prev_status}）")
            return 1

rc = asyncio.run(poll())
sys.exit(rc)
