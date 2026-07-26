"""SC2 API 观察探针：连接已运行的游戏（launcher 普通模式 + -listen/-port），
读取场上劳工单位并查询其可用建造能力。

前置条件：
  SC2 已由 launch-cmre-alenger.ps1 -ListenPort <port> 启动，
  launcher 通过 Wait-GameReady 等待游戏进入 in_game 状态。
  本脚本只需连接 API、观察、查询，无需 CreateGame/JoinGame。

用法:
  python sc2api_observe_probe.py --port <port> [--out-dir <dir>]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
NEURO_PROTOCOL_PATH = REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"
sys.path.insert(0, str(NEURO_PROTOCOL_PATH))

from s2clientprotocol import sc2api_pb2 as sc_pb
from s2clientprotocol import query_pb2
import aiohttp

# 待探测的劳工建造能力（来自 AbilData.xml 静态分析）
# CAbilBuild 的 InfoArray index="BuildN" 对应 ability cmd=N-1（SC2 引擎 cmd 从 0 开始）
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

STATUS_NAMES = {1: "launched", 2: "init_game", 3: "in_game", 4: "in_replay", 5: "ended", 6: "quit"}


async def send_recv(ws, req: sc_pb.Request, timeout: float = 30.0) -> sc_pb.Response:
    await ws.send_bytes(req.SerializeToString())
    resp_bytes = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    resp = sc_pb.Response()
    resp.ParseFromString(resp_bytes)
    return resp


async def wait_for_port(host: str, port: int, max_attempts: int = 60) -> bool:
    for i in range(max_attempts):
        try:
            with socket.create_connection((host, port), timeout=1.0):
                print(f"  端口 {host}:{port} 可达（尝试 {i+1}）", file=sys.stderr)
                return True
        except (ConnectionRefusedError, socket.timeout, OSError):
            await asyncio.sleep(1.0)
    return False


async def fetch_catalog(ws) -> tuple[dict[int, str], dict[int, str], dict[tuple[str, int], int]]:
    """RequestData 获取 ability_id ↔ (link_name, link_index) 映射和 unit_type_id ↔ name 映射。"""
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
    """循环 observation 查找 3diguolaogong 单位。游戏已在 in_game 状态，单位应已存在。"""
    debug = {}
    for i in range(max_iterations):
        # step 推进游戏（保持连接活跃）
        await send_recv(ws, sc_pb.Request(step=sc_pb.RequestStep(count=8)))
        await asyncio.sleep(0.5)

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


async def query_worker_abilities(ws, worker_tag: int) -> list:
    """RequestQuery.abilities 查询劳工所有可用能力。"""
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
    """RequestQuery.placements 测试建造能力放置合法性。result==1 表示 Success。"""
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


async def probe(ws, out_dir: Path, join_init_game: bool, join_timeout: float) -> dict:
    """主探针流程。"""
    result = {
        "schemaVersion": 3,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "sc2api_observe_only",
        "worker_unit_type": WORKER_UNIT_TYPE,
        "probes": [],
        "summary": {},
    }

    # 1. Ping 确认
    resp = await send_recv(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
    if resp.HasField("ping"):
        result["sc2_version"] = resp.ping.game_version
        result["sc2_base_build"] = resp.ping.base_build
        print(f"  服务器版本: {resp.ping.game_version} (base_build={resp.ping.base_build})", file=sys.stderr)

    # 2. 当前状态
    resp = await send_recv(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
    status = resp.status if resp.HasField("status") else 0
    result["initial_status"] = STATUS_NAMES.get(status, str(status))
    print(f"  当前状态: {result['initial_status']}", file=sys.stderr)

    if join_init_game and status == 2:
        join_req = sc_pb.Request(
            join_game=sc_pb.RequestJoinGame(
                race=1,
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
        print(f"  InitGame -> JoinGame（单次，最长 {join_timeout:.0f}s）...", file=sys.stderr)
        resp = await send_recv(ws, join_req, timeout=join_timeout)
        status = resp.status if resp.HasField("status") else 0
        result["join"] = {
            "status": STATUS_NAMES.get(status, str(status)),
            "player_id": resp.join_game.player_id if resp.HasField("join_game") else 0,
            "errors": list(resp.error),
        }
        print(f"  JoinGame: status={result['join']['status']} player_id={result['join']['player_id']} errors={result['join']['errors']}", file=sys.stderr)
        if status != 3:
            raise RuntimeError(f"JoinGame did not enter in_game: {result['join']}")

    # 3. 获取 catalog
    ability_id_to_name, unit_id_to_name, name_index_to_aid = await fetch_catalog(ws)
    result["catalog_sizes"] = {
        "abilities": len(ability_id_to_name),
        "units": len(unit_id_to_name),
    }

    # 4. 找劳工 tag
    worker_tag, obs_debug = await find_worker_tag(ws, unit_id_to_name)
    result["observation"] = obs_debug

    if worker_tag is None:
        result["error"] = "no_worker_found"
        print(f"  错误：场上未找到 {WORKER_UNIT_TYPE} 单位", file=sys.stderr)
        return result

    worker_pos = (obs_debug.get("worker_pos_x", 50.0), obs_debug.get("worker_pos_y", 50.0))

    # 5. 查询劳工所有可用能力
    print(f"  查询劳工可用能力 (RequestQuery.abilities)...", file=sys.stderr)
    available_abilities = await query_worker_abilities(ws, worker_tag)
    available_ability_names = sorted({ability_id_to_name.get(a, f"unknown_{a}") for a in available_abilities})
    result["available_abilities"] = available_abilities
    result["available_ability_names"] = available_ability_names
    print(f"  劳工可用能力数: {len(available_abilities)}", file=sys.stderr)
    for name in available_ability_names:
        print(f"    - {name}", file=sys.stderr)

    # 6. 对每个预期能力做对比
    for abil_link, cmd_idx, expected_unit, label in WORKER_BUILD_PROBES:
        probe_entry = {
            "abil_link": abil_link,
            "cmd_index": cmd_idx,
            "expected_unit": expected_unit,
            "label": label,
        }

        key = (abil_link, cmd_idx)
        if key not in name_index_to_aid:
            probe_entry["status"] = "ability_id_not_found_in_catalog"
            probe_entry["in_available_list"] = False
            result["probes"].append(probe_entry)
            continue

        aid = name_index_to_aid[key]
        probe_entry["ability_id"] = aid
        probe_entry["in_available_list"] = aid in available_abilities

        if aid in available_abilities:
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


async def main_async(port: int, out_dir: Path, join_init_game: bool, join_timeout: float) -> int:
    url = f"ws://127.0.0.1:{port}/sc2api"
    print(f"SC2 API 观察探针（仅观察，不创建游戏）", file=sys.stderr)
    print(f"  URL: {url}", file=sys.stderr)

    print(f"  等待 SC2 端口 {port} 可达...", file=sys.stderr)
    if not await wait_for_port("127.0.0.1", port, max_attempts=60):
        print(f"  错误：SC2 端口 {port} 60s 内未可达", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sc2api_observe_probe.json"

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
        result = await probe(ws, out_dir, join_init_game, join_timeout)
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

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"\n结果已写入: {out_path}", file=sys.stderr)

    print(f"\n=== 运行时探针汇总 ===", file=sys.stderr)
    print(f"总探测能力数: {result['summary'].get('total_probes', 0)}", file=sys.stderr)
    print(f"在可用列表中: {result['summary'].get('in_available_list', 0)}", file=sys.stderr)
    print(f"可放置: {result['summary'].get('placeable', 0)}", file=sys.stderr)
    print(f"不在可用列表: {result['summary'].get('not_in_list', 0)}", file=sys.stderr)

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
    parser = argparse.ArgumentParser(description="SC2 API 观察探针（连接已运行的游戏）")
    parser.add_argument("--port", type=int, default=5000, help="SC2 API 监听端口（默认 5000）")
    parser.add_argument("--out-dir", type=str, default=None, help="输出目录")
    parser.add_argument("--join-init-game", action="store_true", help="仅当会话已处于 InitGame 时发送一次 JoinGame")
    parser.add_argument("--join-timeout", type=float, default=45.0, help="JoinGame 响应上限秒数（默认 45，最大 300）")
    args = parser.parse_args()

    if not 1 <= args.join_timeout <= 300:
        parser.error("--join-timeout 必须在 1 到 300 秒之间")

    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "artifacts" / "runtime" / "sc2api-observe"
    return asyncio.run(main_async(args.port, out_dir, args.join_init_game, args.join_timeout))


if __name__ == "__main__":
    sys.exit(main())
