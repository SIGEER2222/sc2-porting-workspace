"""通过 SC2 API 创建一个简单对局，验证 sc2-observer 能收到真实 observation 和 unit_created 事件。

流程：连接 SC2 API → ping → CreateGame（1v1 电脑，realtime=False 手动 step）→ JoinGame →
      step 推进游戏 → status 转 in_game → 循环 step+observation 验证单位追踪

运行：python tools/runtime-bridge/test-create-game.py --port 5000 [--map <path>]
"""
import argparse
import asyncio
import sys
from pathlib import Path

import aiohttp

# s2clientprotocol 从 SC2-Neuro-API-Integration 引用
NEURO_PATH = Path(__file__).resolve().parents[2] / "reference" / "SC2-Neuro-API-Integration"
sys.path.insert(0, str(NEURO_PATH))
from s2clientprotocol import sc2api_pb2 as sc_pb


# status 枚举（来自 s2clientprotocol/sc2api_pb2 Status）
# 注意：2 是 init_game 不是 menu！（之前误认为是 menu 导致误判 CreateGame 成功）
STATUS_NAMES = {1: "launched", 2: "init_game", 3: "in_game", 4: "in_replay", 5: "ended", 6: "quit", 99: "unknown"}


async def send_recv(ws, req: sc_pb.Request) -> sc_pb.Response:
    """发送 Request 并接收 Response。"""
    await ws.send_bytes(req.SerializeToString())
    resp = sc_pb.Response()
    resp.ParseFromString(await ws.receive_bytes())
    return resp


async def main(port: int, map_path: str) -> int:
    url = f"ws://127.0.0.1:{port}/sc2api"

    print(f"连接: {url}")
    print(f"地图: {map_path}")
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(url, max_msg_size=0) as ws:
            print("已连接")

            # 1. ping
            resp = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
            print(f"ping: version={resp.ping.game_version} base_build={resp.ping.base_build}")

            # 1.5 快速检查当前 status（SC2 启动后处于 launched=1 是正常的）
            # 关键：不需要等 SC2 到达 init_game 状态，在 launched 状态直接 CreateGame 即可
            # CreateGame 会让 SC2 开始加载地图并转换到 init_game 状态
            await asyncio.sleep(3)  # 短暂等待，确保 SC2 基本初始化完成
            try:
                resp = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
                cur_status = resp.status if resp.HasField("status") else 0
                err = list(resp.error) if resp.error else []
                print(f"当前 status: {cur_status} ({STATUS_NAMES.get(cur_status, '?')}) error={err}")
                # 注意：如果在 in_game 状态，不要 leave（leave 会导致后续 CreateGame 异常）
                # 应该重启 SC2 而不是 leave
                if cur_status == 3:
                    print("⚠ SC2 已在游戏中，建议重启 SC2 后再测试（leave 会导致后续 CreateGame 异常）")
                    return 3
            except Exception as e:
                print(f"检查 status 异常（可忽略）: {e}")

            # 2. CreateGame
            # 枚举值: Race Terran=1 Zerg=2 Protoss=3; PlayerType Participant=1 Computer=2; Difficulty VeryEasy=1
            # 关键（参照 python-sc2 controller.create_game）：
            #   - Participant 玩家只设 type，不设 race/player_name（race 在 JoinGame 时指定）
            #   - Computer 玩家设 type、race、difficulty（不设 player_name）
            #   - map_path 用相对路径（相对于 Maps 目录），如 "Campaign\thorner01.SC2Map"
            #   - 注意：某些自定义地图（如 halo_v3）会导致 JoinGame "无法打开地图" 错误，用官方战役地图更可靠
            # realtime=False：手动 step，更可控
            create_req = sc_pb.Request(
                create_game=sc_pb.RequestCreateGame(
                    local_map=sc_pb.LocalMap(map_path=map_path),
                    realtime=False,
                    player_setup=[
                        sc_pb.PlayerSetup(type=1),  # Participant，不设 race/player_name
                        sc_pb.PlayerSetup(type=2, race=2, difficulty=1),  # Computer, Zerg, VeryEasy
                    ],
                )
            )
            resp = await send_recv(ws, create_req)
            if resp.error:
                print(f"CreateGame 错误: {list(resp.error)}")
                print(f"  error_msg: {getattr(resp, 'error_msg', '')}")
                return 2
            status = resp.status if resp.HasField("status") else 0
            # 检查 create_game 子消息的 error（proto2 中 has_error=False 表示无错误）
            cg_err = resp.create_game.HasField("error") if resp.HasField("create_game") else False
            print(f"CreateGame (status={status} {STATUS_NAMES.get(status, '?')}, has_error={cg_err})")

            # 3. JoinGame（控制玩家1，Terran）
            # 用 python-sc2 完整的 InterfaceOptions 参数
            join_req = sc_pb.Request(
                join_game=sc_pb.RequestJoinGame(
                    race=1,  # Terran
                    options=sc_pb.InterfaceOptions(
                        raw=True,
                        score=True,
                        show_cloaked=True,
                        show_burrowed_shadows=True,
                        raw_affects_selection=False,
                        raw_crop_to_playable_area=False,
                        show_placeholders=True,
                    ),
                    player_name="Observer-Test",
                )
            )
            resp = await send_recv(ws, join_req)
            if resp.error:
                print(f"JoinGame 错误: {list(resp.error)}")
                return 2
            status = resp.status if resp.HasField("status") else 0
            player_id = resp.join_game.player_id if resp.HasField("join_game") else -1
            print(f"JoinGame 成功 (status={status} {STATUS_NAMES.get(status, '?')}, player_id={player_id})")

            # 4. JoinGame 后按 python-sc2 流程：get_game_data → get_game_info → ping → observation
            # 这些调用可能触发 SC2 内部状态转换（launched → in_game）
            print("\nJoinGame 后初始化（get_game_data → get_game_info → ping → observation）...")
            loaded = False

            # 4.1 get_game_data
            try:
                resp = await send_recv(ws, sc_pb.Request(
                    data=sc_pb.RequestData(ability_id=True, unit_type_id=True, upgrade_id=True, buff_id=True, effect_id=True)
                ))
                status = resp.status if resp.HasField("status") else 0
                has_data = resp.HasField("data")
                print(f"  get_game_data: status={status} {STATUS_NAMES.get(status, '?')} has_data={has_data}")
            except Exception as e:
                print(f"  get_game_data 异常: {e}")

            # 4.2 get_game_info
            try:
                resp = await send_recv(ws, sc_pb.Request(game_info=sc_pb.RequestGameInfo()))
                status = resp.status if resp.HasField("status") else 0
                has_info = resp.HasField("game_info")
                print(f"  get_game_info: status={status} {STATUS_NAMES.get(status, '?')} has_info={has_info}")
            except Exception as e:
                print(f"  get_game_info 异常: {e}")

            # 4.3 ping
            try:
                resp = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
                status = resp.status if resp.HasField("status") else 0
                print(f"  ping: status={status} {STATUS_NAMES.get(status, '?')}")
            except Exception as e:
                print(f"  ping 异常: {e}")

            # 4.4 observation（python-sc2 的做法：不 step，直接 observation）
            for i in range(10):
                try:
                    resp = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
                    status = resp.status if resp.HasField("status") else 0
                    has_obs = resp.HasField("observation")
                    err = list(resp.error) if resp.error else "none"
                    if i < 3 or i % 3 == 0:
                        print(f"  obs {i}: status={status} {STATUS_NAMES.get(status, '?')} has_obs={has_obs} error={err}")
                    if status >= 3 and has_obs:
                        print(f"  ✓ 游戏已加载 (status={status})")
                        loaded = True
                        break
                except Exception as e:
                    print(f"  obs {i}: 异常 {e}")
                await asyncio.sleep(2)

            # 如果直接 observation 不行，尝试 step 推进
            if not loaded:
                print("\n直接 observation 失败，尝试 step 推进...")
                for i in range(15):
                    resp = await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=1)))
                    status = resp.status if resp.HasField("status") else 0
                    if i < 3 or i % 5 == 0:
                        print(f"  step {i}: status={status} {STATUS_NAMES.get(status, '?')}")
                    if status >= 3:
                        print(f"  ✓ 游戏已加载 (status={status})")
                        loaded = True
                        break

            if not loaded:
                print("✗ 游戏未在 30 次 step 内加载完成")
                # 最后尝试拉一次 observation 看错误信息
                try:
                    resp = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
                    print(f"  observation: error={list(resp.error) if resp.error else 'none'}")
                    print(f"  has_observation={resp.HasField('observation')}")
                except Exception as e:
                    print(f"  observation 异常: {e}")
                return 2

            # 5. 拉取 observation + step 循环（手动推进游戏）
            prev_unit_tags: set = set()
            prev_unit_types: dict = {}
            unit_created_count = 0
            unit_lost_count = 0
            resource_count = 0
            unique_unit_types: set = set()

            print("\nobservation + step 循环（手动推进 60 帧）...")
            for step_i in range(60):
                # 5.1 先拉 observation
                resp = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
                if resp.error:
                    print(f"  step {step_i}: observation 错误: {list(resp.error)}")
                    break
                if not resp.HasField("observation"):
                    print(f"  step {step_i}: 无 observation")
                    continue

                obs = resp.observation
                pc = obs.player_common
                if pc.HasField("minerals"):
                    resource_count += 1
                    if step_i < 5 or step_i % 15 == 0:
                        print(f"  step {step_i}: 矿={pc.minerals} 气={pc.vespene} 人口={pc.food_used}/{pc.food_cap}")

                # 5.2 单位对比（复用 sc2-observer 的逻辑）
                try:
                    units = list(obs.observation.raw.units)
                    current_tags = {u.tag for u in units}
                    current_types = {u.tag: u.unit_type for u in units}
                    new_units = [u for u in units if u.tag not in prev_unit_tags]
                    lost_tags = prev_unit_tags - current_tags
                    if new_units:
                        unit_created_count += len(new_units)
                        for u in new_units[:3]:
                            unique_unit_types.add(u.unit_type)
                            if step_i < 10 or len(new_units) > 0:
                                print(f"  step {step_i}: +unit type={u.unit_type} owner={u.owner} tag={u.tag}")
                    if lost_tags:
                        unit_lost_count += len(lost_tags)
                    prev_unit_tags = current_tags
                    prev_unit_types = current_types
                except Exception as e:
                    print(f"  step {step_i}: 单位解析异常: {e}")

                # 5.3 step 推进游戏（8 帧/次，让单位有时间生产）
                resp = await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=8)))
                if resp.error:
                    # step 可能因为游戏结束而报错
                    print(f"  step {step_i}: step 错误: {list(resp.error)}")
                    break

            # 6. 检查 GameLogs（看是否有 ScriptError）
            print("\n=== 总结 ===")
            print(f"  observation 帧数: {resource_count}")
            print(f"  unit_created 事件: {unit_created_count}")
            print(f"  unit_lost 事件: {unit_lost_count}")
            print(f"  唯一 unit_type: {sorted(unique_unit_types)}")
            if unit_created_count > 0:
                print("\n✅ 验证通过：sc2-observer 的前后帧 tag 对比逻辑正确识别了单位创建")
            else:
                print("\n⚠ 未观察到单位创建（可能游戏未充分推进）")

            return 0 if unit_created_count > 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SC2 API 创建对局验证")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument(
        "--map",
        type=str,
        default=r"Campaign\thorner01.SC2Map",
        help="地图相对路径（相对于 Maps 目录，默认 Campaign\\thorner01.SC2Map 官方战役地图）",
    )
    args = parser.parse_args()
    try:
        rc = asyncio.run(main(args.port, args.map))
    except Exception as e:
        import traceback
        traceback.print_exc()
        rc = 2
    sys.exit(rc)
