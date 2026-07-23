"""诊断 CreateGame + JoinGame 的完整响应，找出 status 倒退的原因。"""
import asyncio, aiohttp, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "reference" / "SC2-Neuro-API-Integration"))
from s2clientprotocol import sc2api_pb2 as sc_pb
from google.protobuf import text_format

NAMES = {1: "launched", 2: "menu", 3: "in_game", 4: "in_replay"}

async def send_recv(ws, req):
    await ws.send_bytes(req.SerializeToString())
    resp = sc_pb.Response()
    resp.ParseFromString(await ws.receive_bytes())
    return resp

async def main():
    # 尝试官方战役地图 Campaign\thorner01.SC2Map
    map_file = r"E:\SC2\SC2new\StarCraft II\Maps\Campaign\thorner01.SC2Map"
    map_path_relative = r"Campaign\thorner01.SC2Map"
    url = "ws://127.0.0.1:5000/sc2api"
    print(f"连接 {url}")
    async with aiohttp.ClientSession() as s:
        async with s.ws_connect(url, max_msg_size=0) as ws:
            # ping
            r = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
            print(f"\n=== ping ===\n{r.ping}")

            # 查当前 status
            r = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
            st = r.status if r.HasField("status") else 0
            print(f"\n=== 当前 status ===\nstatus={st} ({NAMES.get(st,'?')}) error={list(r.error)}")

            # 如果在游戏中，先离开
            if st == 3:
                await send_recv(ws, sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()))
                await asyncio.sleep(2)

            # CreateGame：尝试用 map_data（直接传文件内容）绕过路径问题
            with open(map_file, "rb") as f:
                map_data = f.read()
            print(f"\n地图文件: {map_file} ({len(map_data)} bytes)")
            create_req = sc_pb.Request(
                create_game=sc_pb.RequestCreateGame(
                    local_map=sc_pb.LocalMap(map_path=map_path_relative, map_data=map_data),
                    realtime=False,
                    player_setup=[
                        sc_pb.PlayerSetup(type=1),  # Participant，不设 race
                        sc_pb.PlayerSetup(type=2, race=2, difficulty=1),  # Computer Zerg VeryEasy
                    ],
                )
            )
            r = await send_recv(ws, create_req)
            st = r.status if r.HasField("status") else 0
            print(f"\n=== CreateGame 响应 ===")
            print(f"status={st} ({NAMES.get(st,'?')})")
            print(f"error={list(r.error)}")
            print(f"has_create_game={r.HasField('create_game')}")
            if r.HasField("create_game"):
                print(f"create_game.error={r.create_game.error}")
                print(f"create_game.error_details={r.create_game.error_details}")
                print(f"create_game.has_error={r.create_game.HasField('error')}")
            print(f"完整响应:\n{text_format.MessageToString(r, as_one_line=True)[:1000]}")

            # CreateGame 后查 status
            r = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
            st2 = r.status if r.HasField("status") else 0
            print(f"\n=== CreateGame 后 status ===\nstatus={st2} ({NAMES.get(st2,'?')}) error={list(r.error)}")

            # JoinGame（python-sc2 格式）
            join_req = sc_pb.Request(
                join_game=sc_pb.RequestJoinGame(
                    race=1,  # Terran
                    options=sc_pb.InterfaceOptions(
                        raw=True, score=True, show_cloaked=True,
                        show_burrowed_shadows=True, raw_affects_selection=False,
                        raw_crop_to_playable_area=False, show_placeholders=True,
                    ),
                    player_name="Diag-Test",
                )
            )
            r = await send_recv(ws, join_req)
            st = r.status if r.HasField("status") else 0
            print(f"\n=== JoinGame 响应 ===")
            print(f"status={st} ({NAMES.get(st,'?')})")
            print(f"error={list(r.error)}")
            print(f"has_join_game={r.HasField('join_game')}")
            if r.HasField("join_game"):
                jg = r.join_game
                print(f"join_game.player_id={jg.player_id}")
                print(f"join_game.has_player_id={jg.HasField('player_id')}")
            print(f"完整响应:\n{text_format.MessageToString(r, as_one_line=True)[:1000]}")

            # 等几秒，再查 status
            print("\n等待 5 秒后查 status...")
            await asyncio.sleep(5)
            r = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
            st3 = r.status if r.HasField("status") else 0
            print(f"status={st3} ({NAMES.get(st3,'?')}) error={list(r.error)}")

            # 再等 10 秒
            print("等待 10 秒后查 status...")
            await asyncio.sleep(10)
            r = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
            st4 = r.status if r.HasField("status") else 0
            print(f"status={st4} ({NAMES.get(st4,'?')}) error={list(r.error)}")

            # 尝试 step
            print("\n尝试 step...")
            r = await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=1)))
            st5 = r.status if r.HasField("status") else 0
            print(f"step 后 status={st5} ({NAMES.get(st5,'?')}) error={list(r.error)}")

asyncio.run(main())
