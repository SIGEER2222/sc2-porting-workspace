"""SC2 API 运行时探针：通过 RequestCreateGame + RequestJoinGame 加载地图，
然后用 RequestQuery.abilities 查询劳工真实可用能力。

权威运行时判定流程：
  1. SC2 由 launcher 以 -listen 127.0.0.1 -port <port> 启动（不传地图路径）
  2. 本脚本连接 ws://127.0.0.1:<port>/sc2api
  3. RequestCreateGame{local_map: {map_path}, player_setup, realtime=true} 加载地图
  4. RequestJoinGame{race=Terran, options={raw=true}} 加入游戏
  5. 等游戏初始化（StartingUnits 触发器 Wait 5s + 创建单位）
  6. RequestData{ability_id=true, unit_type_id=true} 拿到 ability_id ↔ (link_name, link_index) 映射
  7. RequestObservation 找场上 3diguolaogong 的 unit_tag
  8. RequestQuery.abilities 查询劳工所有可用能力（SC2 引擎真实判定，含 TechTree/State/Requirement）
  9. 对比静态 AbilData.xml 中定义的 13 个建造槽位，输出运行时可见性报告

用法:
  python tools/runtime-bridge/sc2api_runtime_probe.py --map-path <绝对路径> [--port 5000]

前置条件:
  SC2 必须已由 launch-cmre-alenger.ps1 -ListenPort <port> 启动。
  launcher 会打印 "Live map for RequestCreateGame: <path>"，将该路径传给 --map-path。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import time
from pathlib import Path
from typing import Any

# 复用 SC2-Neuro 的 vendored s2clientprotocol
REPO_ROOT = Path(__file__).resolve().parents[2]
NEURO_PROTOCOL_PATH = REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"
sys.path.insert(0, str(NEURO_PROTOCOL_PATH))

from s2clientprotocol import sc2api_pb2 as sc_pb
from s2clientprotocol import query_pb2
import aiohttp

# 待探测的劳工建造能力（来自 AbilData.xml 静态分析）
# CAbilBuild 的 InfoArray index="BuildN" 对应 ability cmd=N-1（SC2 引擎 cmd 从 0 开始）
# (abil_link, cmd_index, expected_unit_id, label_zh)
WORKER_BUILD_PROBES = [
    ("3jianzao1", 0,  "3diguoqianshaojidi",       "前哨基地"),
    ("3jianzao1", 3,  "3diguobingying",            "兵营"),
    ("3jianzao1", 10, "3diguogongchang",           "工厂"),
    ("3jianzao1", 11, "3diguoxinggang",            "星港"),
    ("3jianzao2", 1,  "3bujidibao",                "补给地堡"),
    ("3jianzao2", 4,  "3diguogongchengzhan",       "工程站"),
    ("3jianzao2", 5,  "3huangjiafangkongta",       "皇家防空塔"),
    ("3jianzao2", 6,  "3shenkongzhenliepingtai",   "深空阵列平台"),
    ("3jianzao2", 9,  "3diguoyanjiuyuan",          "研究院"),
    ("3jianzao2", 12, "MercCompound",              "佣兵集合站"),
    ("3jianzao2", 13, "3diguozhuzaochang",         "铸造厂"),
    ("3jianzao2", 15, "3diguokexueyuan",           "科学院"),
    ("3jianzao2", 18, "3zidonghuajinglianchang",   "自动化精炼厂"),
]

WORKER_UNIT_TYPE = "3diguolaogong"
COMMAND_CENTER_TYPE = "3diguoqianshaojidi"

# Status 枚举（sc2api.proto）
STATUS_NAMES = {1: "launched", 2: "init_game", 3: "in_game", 4: "in_replay", 5: "ended", 6: "quit"}


async def send_recv(ws, req: sc_pb.Request, timeout: float = 20.0) -> sc_pb.Response:
    """发送 protobuf 请求并等待响应。"""
    await ws.send_bytes(req.SerializeToString())
    resp_bytes = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    resp = sc_pb.Response()
    resp.ParseFromString(resp_bytes)
    return resp


async def wait_for_port(host: str, port: int, max_attempts: int = 60) -> bool:
    """TCP 端口预检，等待 SC2 启动并监听端口。"""
    for i in range(max_attempts):
        try:
            with socket.create_connection((host, port), timeout=1.0):
                print(f"  端口 {host}:{port} 可达（尝试 {i+1}）", file=sys.stderr)
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            await asyncio.sleep(1.0)
    return False


async def create_and_join_game(ws, map_path: str) -> dict:
    """RequestCreateGame + RequestJoinGame，返回 join 结果。"""
    # === RequestCreateGame ===
    # 尝试多种 map_path 格式（绝对路径 / Maps\xxx.SC2Map / 文件名）
    candidates = [
        map_path,
        f"Maps\\{Path(map_path).name}",
        Path(map_path).name,
    ]
    success = False
    last_error = ""
    for map_str in candidates:
        print(f"  尝试 map_path={map_str!r}", file=sys.stderr)
        create_req = sc_pb.Request(
            create_game=sc_pb.RequestCreateGame(
                local_map=sc_pb.LocalMap(map_path=map_str),
                realtime=True,
            )
        )
        # Player 1: Computer（AI 对手，自动填充，无需 join_game）
        p1 = create_req.create_game.player_setup.add()
        p1.type = 2  # Computer
        p1.race = 1  # Terran
        p1.difficulty = 1  # VeryEasy
        # Player 2: Participant（我们 JoinGame 时占用）
        p2 = create_req.create_game.player_setup.add()
        p2.type = 1  # Participant
        p2.race = 1  # Terran

        resp = await send_recv(ws, create_req)
        if resp.create_game.HasField("error"):
            err = resp.create_game.error
            detail = resp.create_game.error_details if resp.create_game.HasField("error_details") else ""
            last_error = f"error={err} detail={detail}"
            print(f"    失败: {last_error}", file=sys.stderr)
            continue
        print(f"    成功！", file=sys.stderr)
        success = True
        break

    if not success:
        raise RuntimeError(f"RequestCreateGame 所有路径格式都失败。最后错误: {last_error}")

    # === RequestJoinGame ===
    # race=Terran 作为 Participant 加入。单机模式不需要 server_ports/client_ports
    # （仅 multiplayer 才需要）。之前设置 server_ports 会导致游戏卡在 init_game
    # 状态（疑似 SC2 等待 multiplayer 握手）。
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
        )
    )
    print(f"  RequestJoinGame: race=Terran (无 server_ports，单机模式)", file=sys.stderr)
    resp = await send_recv(ws, join_req)
    if resp.error:
        raise RuntimeError(f"RequestJoinGame 失败: {list(resp.error)}")
    print(f"  join_game 成功: player_id={resp.join_game.player_id}", file=sys.stderr)
    return {"player_id": resp.join_game.player_id}


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("", 0))
    p = s.getsockname()[1]
    s.close()
    return p


async def fetch_catalog(ws) -> tuple[dict[int, str], dict[int, str], dict[tuple[str, int], int]]:
    """RequestData 获取 ability_id ↔ (link_name, link_index) 映射和 unit_type_id ↔ name 映射。

    返回:
        ability_id_to_name: {ability_id(int) -> link_name(str)}
        unit_id_to_name: {unit_type_id(int) -> name(str)}
        (link_name, link_index) -> ability_id 映射
    """
    print(f"  查询 catalog (RequestData ability_id + unit_type_id)...", file=sys.stderr)
    req = sc_pb.Request(data=sc_pb.RequestData(ability_id=True, unit_type_id=True))
    resp = await send_recv(ws, req)
    data = resp.data

    ability_id_to_name: dict[int, str] = {}
    name_index_to_aid: dict[tuple[str, int], int] = {}
    for ab in data.abilities:
        ability_id_to_name[ab.ability_id] = ab.link_name
        name_index_to_aid[(ab.link_name, ab.link_index)] = ab.ability_id

    unit_id_to_name: dict[int, str] = {}
    for u in data.units:
        unit_id_to_name[u.unit_id] = u.name

    print(f"    catalog: abilities={len(ability_id_to_name)} units={len(unit_id_to_name)}", file=sys.stderr)
    return ability_id_to_name, unit_id_to_name, name_index_to_aid


async def find_worker_tag(ws, unit_id_to_name: dict[int, str], max_iterations: int = 30) -> tuple[int | None, dict]:
    """循环 step + observation，直到 3diguolaogong 出现或超时。

    realtime=True 模式下游戏自动推进，但仍需定期 step 保持 API 连接活跃
    （长时间无请求会导致 SC2 关闭 websocket）。每轮 step 推进 8 帧（约 1 个游戏秒），
    然后 observation 检查单位是否出现。StartingUnits 触发器内 Wait(5.0, c_timeReal)
    约 5 秒，max_iterations=30 约 30 秒足够覆盖。
    """
    debug = {}
    for i in range(max_iterations):
        # step 推进游戏（保持连接活跃）
        await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=8)))
        await asyncio.sleep(1.0)  # realtime 模式下给游戏时间执行触发器

        resp = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
        obs = resp.observation
        status = resp.status if resp.HasField("status") else 0
        game_loop = obs.observation.game_loop if obs.HasField("observation") else 0

        units = list(obs.observation.raw.units) if obs.HasField("observation") and obs.observation.HasField("raw_data") else []
        workers = []
        ccs = []
        for u in units:
            name = unit_id_to_name.get(u.unit_type, f"unknown_{u.unit_type}")
            if name == WORKER_UNIT_TYPE:
                workers.append(u)
            elif name == COMMAND_CENTER_TYPE:
                ccs.append(u)

        debug = {
            "status": status,
            "status_name": STATUS_NAMES.get(status, "?"),
            "game_loop": game_loop,
            "total_units": len(units),
            "worker_count": len(workers),
            "cc_count": len(ccs),
            "iterations": i + 1,
        }
        print(f"  [{i+1}/{max_iterations}] Observation: status={debug['status_name']} loop={game_loop} units={len(units)} workers={len(workers)} cc={len(ccs)}", file=sys.stderr)

        if workers:
            worker = workers[0]
            debug["worker_pos_x"] = worker.pos.x
            debug["worker_pos_y"] = worker.pos.y
            debug["worker_owner"] = worker.owner
            print(f"  选用劳工: tag={worker.tag} pos=({worker.pos.x:.1f},{worker.pos.y:.1f}) owner={worker.owner}", file=sys.stderr)
            return worker.tag, debug

    return None, debug


async def query_worker_abilities(ws, worker_tag: int) -> list[int]:
    """RequestQuery.abilities 查询劳工所有可用能力（SC2 引擎真实判定）。"""
    req = sc_pb.Request(
        query=query_pb2.RequestQuery(
            abilities=[query_pb2.RequestQueryAvailableAbilities(unit_tag=worker_tag)],
        )
    )
    resp = await send_recv(ws, req)
    if not resp.query.abilities:
        return []
    return list(resp.query.abilities[0].abilities)


async def query_placement(ws, ability_id: int, positions: list[tuple[float, float]]) -> list[bool]:
    """RequestQuery.placements 测试某建造能力在多个位置的放置合法性。result==1 表示 Success。"""
    req = sc_pb.Request(
        query=query_pb2.RequestQuery(
            placements=[
                query_pb2.RequestQueryBuildingPlacement(
                    ability_id=ability_id,
                    target_pos=query_pb2.Point2D(x=x, y=y),
                )
                for x, y in positions
            ],
            ignore_resource_requirements=True,
        )
    )
    resp = await send_recv(ws, req)
    return [p.result == 1 for p in resp.query.placements]


async def probe(ws, map_path: str, out_dir: Path) -> dict:
    """主探针流程。"""
    result = {
        "schemaVersion": 2,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "sc2api_creategame_join_query",
        "map_path": map_path,
        "worker_unit_type": WORKER_UNIT_TYPE,
        "probes": [],
        "summary": {},
    }

    # 1. 创建并加入游戏
    join_info = await create_and_join_game(ws, map_path)
    result["join_info"] = join_info

    # 2. 获取 catalog（尽早获取，避免后续连接断开）
    ability_id_to_name, unit_id_to_name, name_index_to_aid = await fetch_catalog(ws)
    result["catalog_sizes"] = {
        "abilities": len(ability_id_to_name),
        "units": len(unit_id_to_name),
    }

    # 4. 找劳工 tag（循环 step + observation 直到出现）
    worker_tag, obs_debug = await find_worker_tag(ws, unit_id_to_name)
    result["observation"] = obs_debug

    if worker_tag is None:
        result["error"] = "no_worker_found"
        print(f"  错误：场上未找到 {WORKER_UNIT_TYPE} 单位", file=sys.stderr)
        print(f"  可能原因：StartingUnits 触发器未执行 / Wait 时间不够 / 地图加载失败", file=sys.stderr)
        return result

    # 保存劳工当前位置（placement 测试用）
    worker_pos = (obs_debug.get("worker_pos_x", 50.0), obs_debug.get("worker_pos_y", 50.0))

    # 5. 查询劳工所有可用能力（最权威的运行时判定）
    print(f"  查询劳工可用能力 (RequestQuery.abilities)...", file=sys.stderr)
    available_abilities = await query_worker_abilities(ws, worker_tag)
    available_ability_names = sorted({ability_id_to_name.get(a, f"unknown_{a}") for a in available_abilities})
    result["available_abilities"] = available_abilities
    result["available_ability_names"] = available_ability_names
    print(f"  劳工可用能力数: {len(available_abilities)}", file=sys.stderr)
    for name in available_ability_names:
        print(f"    - {name}", file=sys.stderr)

    # 6. 对每个预期能力做对比
    # 准备候选放置位置（劳工周围 5 个偏移点）
    # 注意：这里用劳工位置作为参考，但 RequestQueryBuildingPlacement 需要 ability_id
    # 先从 (link_name, link_index) 查 ability_id
    for abil_link, cmd_idx, expected_unit, label in WORKER_BUILD_PROBES:
        probe_entry = {
            "abil_link": abil_link,
            "cmd_index": cmd_idx,
            "expected_unit": expected_unit,
            "label": label,
        }

        # 查 ability_id
        key = (abil_link, cmd_idx)
        if key not in name_index_to_aid:
            probe_entry["status"] = "ability_id_not_found_in_catalog"
            probe_entry["in_available_list"] = False
            result["probes"].append(probe_entry)
            continue

        aid = name_index_to_aid[key]
        probe_entry["ability_id"] = aid
        probe_entry["in_available_list"] = aid in available_abilities

        # 如果在可用列表中，尝试做 placement 测试
        if aid in available_abilities:
            # 用劳工位置周围偏移点测试放置
            try:
                test_positions = [
                    (worker_pos[0] + dx, worker_pos[1] + dy)
                    for dx, dy in [(0, 0), (3, 0), (-3, 0), (0, 3), (0, -3), (5, 5), (-5, -5)]
                ]
                placement_results = await query_placement(ws, aid, test_positions)
                probe_entry["placement"] = {
                    "positions_tested": len(test_positions),
                    "any_placeable": any(placement_results),
                    "results": placement_results,
                }
                probe_entry["status"] = "placeable" if any(placement_results) else "in_list_but_no_valid_position"
            except Exception as e:
                probe_entry["placement_error"] = str(e)
                probe_entry["status"] = "in_list_placement_failed"
        else:
            probe_entry["status"] = "not_in_available_list"

        result["probes"].append(probe_entry)

    # 7. 汇总
    in_list_count = sum(1 for p in result["probes"] if p.get("in_available_list"))
    placeable_count = sum(1 for p in result["probes"] if p.get("placement", {}).get("any_placeable"))
    not_in_list_count = len(result["probes"]) - in_list_count
    result["summary"] = {
        "total_probes": len(result["probes"]),
        "in_available_list": in_list_count,
        "placeable": placeable_count,
        "not_in_list": not_in_list_count,
    }

    return result


async def main_async(port: int, map_path: str, out_dir: Path) -> int:
    url = f"ws://127.0.0.1:{port}/sc2api"
    print(f"SC2 API 运行时探针", file=sys.stderr)
    print(f"  URL: {url}", file=sys.stderr)
    print(f"  Map: {map_path}", file=sys.stderr)

    # 等待 SC2 启动并监听端口
    print(f"  等待 SC2 端口 {port} 可达...", file=sys.stderr)
    if not await wait_for_port("127.0.0.1", port, max_attempts=60):
        print(f"  错误：SC2 端口 {port} 60s 内未可达", file=sys.stderr)
        print(f"  请确认 launcher 已以 -ListenPort {port} 启动 SC2", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sc2api_runtime_probe.json"

    # WebSocket 连接重试（SC2 TCP 端口可达后，HTTP websocket 服务可能还需几秒才就绪）
    ws = None
    session = None
    last_err = None
    for attempt in range(15):
        try:
            session = aiohttp.ClientSession()
            ws = await session.ws_connect(url, max_msg_size=0)
            print(f"  WebSocket 连接已建立（尝试 {attempt+1}）", file=sys.stderr)
            break
        except (aiohttp.ClientConnectorError, aiohttp.ServerDisconnectedError, ConnectionResetError) as e:
            last_err = e
            if session:
                await session.close()
                session = None
            await asyncio.sleep(2.0)
    else:
        print(f"  错误：WebSocket 连接 15 次重试后仍失败: {last_err}", file=sys.stderr)
        return 2

    try:
        # Ping 确认
        resp = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
        if resp.HasField("ping"):
            print(f"  服务器版本: {resp.ping.game_version} (base_build={resp.ping.base_build})", file=sys.stderr)

        result = await probe(ws, map_path, out_dir)

    except aiohttp.ClientConnectorError as e:
        print(f"  连接失败: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"  探针异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 2
    finally:
        if ws is not None:
            await ws.close()
        if session is not None:
            await session.close()

    # 写入结果
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n结果已写入: {out_path}", file=sys.stderr)

    # 打印汇总
    print(f"\n=== 运行时探针汇总 ===", file=sys.stderr)
    print(f"总探测能力数: {result['summary'].get('total_probes', 0)}", file=sys.stderr)
    print(f"在可用列表中: {result['summary'].get('in_available_list', 0)}", file=sys.stderr)
    print(f"可放置: {result['summary'].get('placeable', 0)}", file=sys.stderr)
    print(f"不在可用列表: {result['summary'].get('not_in_list', 0)}", file=sys.stderr)

    # 详细列表
    print(f"\n=== 详细能力状态 ===", file=sys.stderr)
    for p in result.get("probes", []):
        status = p.get("status", "?")
        in_list = "✓" if p.get("in_available_list") else "✗"
        label = p.get("label", "")
        abil = f"{p.get('abil_link')},Build{p.get('cmd_index')+1}"
        unit = p.get("expected_unit", "")
        print(f"  [{in_list}] {label:12s} {abil:25s} -> {unit:30s} ({status})", file=sys.stderr)

    return 0


def main():
    parser = argparse.ArgumentParser(description="SC2 API 运行时探针：CreateGame + JoinGame + RequestQuery.abilities")
    parser.add_argument("--map-path", type=str, required=True,
                        help="地图绝对路径（launcher 打印的 Live map for RequestCreateGame）")
    parser.add_argument("--port", type=int, default=5000, help="SC2 API 监听端口（默认 5000）")
    parser.add_argument("--out-dir", type=str, default=None, help="输出目录")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "artifacts" / "runtime" / "sc2api-probe"
    return asyncio.run(main_async(args.port, args.map_path, out_dir))


if __name__ == "__main__":
    sys.exit(main())
