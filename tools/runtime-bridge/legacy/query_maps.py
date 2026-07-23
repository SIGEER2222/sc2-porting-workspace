"""查询 SC2 API 可用地图列表 + 重启游戏测试不同地图。"""
import asyncio, aiohttp, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "reference" / "SC2-Neuro-API-Integration"))
from s2clientprotocol import sc2api_pb2 as sc_pb

async def query():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("ws://127.0.0.1:5000/sc2api", max_msg_size=0) as ws:
            # ping
            await ws.send_bytes(sc_pb.Request(ping=sc_pb.RequestPing()).SerializeToString())
            r = sc_pb.Response(); r.ParseFromString(await ws.receive_bytes())
            print("ping:", r.ping.game_version, "base_build=", r.ping.base_build)

            # 查询可用地图
            await ws.send_bytes(sc_pb.Request(available_maps=sc_pb.RequestAvailableMaps()).SerializeToString())
            r = sc_pb.Response(); r.ParseFromString(await ws.receive_bytes())
            if r.error:
                print("available_maps error:", list(r.error))
                return
            am = r.available_maps
            print("\n=== ResponseAvailableMaps 字段 ===")
            print(am.DESCRIPTOR.fields_by_name.keys())
            print("\n=== 完整内容 ===")
            print(str(am)[:2000])

asyncio.run(query())
