"""快速检查 SC2 API status。"""
import asyncio, aiohttp, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "reference" / "SC2-Neuro-API-Integration"))
from s2clientprotocol import sc2api_pb2 as sc_pb

NAMES = {1: "launched", 2: "menu", 3: "in_game", 4: "in_replay"}

async def check():
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect("ws://127.0.0.1:5000/sc2api", max_msg_size=0) as ws:
            await ws.send_bytes(sc_pb.Request(ping=sc_pb.RequestPing()).SerializeToString())
            r = sc_pb.Response(); r.ParseFromString(await ws.receive_bytes())
            print("ping:", r.ping.game_version, "base_build=", r.ping.base_build)
            await ws.send_bytes(sc_pb.Request(observation=sc_pb.RequestObservation()).SerializeToString())
            r = sc_pb.Response(); r.ParseFromString(await ws.receive_bytes())
            st = r.status if r.HasField("status") else 0
            err = list(r.error) if r.error else "none"
            print("status=" + str(st) + " (" + NAMES.get(st, "?") + ") error=" + str(err))

asyncio.run(check())
