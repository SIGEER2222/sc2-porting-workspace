"""SC2API 运行时探针：直接连接 SC2 的 /sc2api websocket，查询劳工可建造建筑。

依赖 s2clientprotocol（vendored 在 reference/SC2-Neuro-API-Integration/）和 aiohttp。

核心 API：
  1. RequestObservation  - 拉取场上单位，定位 3diguolaogong（劳工）和 3diguoqianshaojidi（前哨基地）
  2. RequestQueryAvailableAbilities - 查询劳工当前可用的所有能力（SC2 引擎真实判定）
  3. RequestQueryBuildingPlacement  - 测试每个建造能力在多个位置的放置合法性

用法:
  python tools/runtime-bridge/sc2api_worker_probe.py --port 5000 [--out-dir <dir>]

前置条件:
  SC2 必须以 -listen 127.0.0.1 -port <port> 启动。launch-cmre-alenger.ps1 已支持 -ListenPort。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
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

# 待探测的劳工建造能力及其 cmd 索引（来自 AbilData.xml 静态分析）
# CAbilBuild 的 InfoArray index="BuildN" 对应 cmd=N-1（SC2 引擎 cmd 从 0 开始）
WORKER_BUILD_PROBES = [
    # (abil_id, cmd_index, expected_unit_id, label_zh)
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


async def send_request(ws, request: sc_pb.Request) -> sc_pb.Response:
    """发送 protobuf 请求并等待响应。"""
    await ws.send_bytes(request.SerializeToString())
    resp_bytes = await asyncio.wait_for(ws.receive_bytes(), timeout=15.0)
    resp = sc_pb.Response()
    resp.ParseFromString(resp_bytes)
    if resp.error:
        raise RuntimeError(f"SC2 API 返回错误: {resp.error}")
    return resp


async def find_units(obs: Any, unit_type_name: str, owner: int | None = None) -> list[Any]:
    """从 Observation 中找出指定类型的所有单位。"""
    matches = []
    for u in obs.observation.raw.units:
        if u.unit_type != unit_type_name:
            continue
        if owner is not None and u.owner != owner:
            continue
        matches.append(u)
    return matches


async def query_worker_abilities(ws, worker_tag: int) -> list[int]:
    """查询劳工当前所有可用能力（SC2 引擎真实判定，含 tech tree 解锁状态）。"""
    req = sc_pb.Request(
        query=query_pb2.RequestQuery(
            abilities=(query_pb2.RequestQueryAvailableAbilities(unit_tag=worker_tag),),
        )
    )
    resp = await send_request(ws, req)
    if not resp.query.abilities:
        return []
    # 每个 RequestQueryAvailableAbilities 对应一个 AvailableAbilities
    return list(resp.query.abilities[0].abilities)


async def query_placement(
    ws,
    ability_id: int,
    positions: list[tuple[float, float]],
    ignore_resources: bool = True,
) -> list[bool]:
    """测试某建造能力在多个位置是否可放置。

    SC2 query.placements 的 result 枚举：1=Success（可放置），其他=失败原因。
    """
    req = sc_pb.Request(
        query=query_pb2.RequestQuery(
            placements=(
                query_pb2.RequestQueryBuildingPlacement(
                    ability_id=ability_id,
                    target_pos=query_pb2.Point2D(x=x, y=y),
                )
                for x, y in positions
            ),
            ignore_resource_requirements=ignore_resources,
        )
    )
    resp = await send_request(ws, req)
    # result == 1 表示 Success
    return [p.result == 1 for p in resp.query.placements]


async def probe(ws, out_dir: Path) -> dict:
    """主探针流程。"""
    result = {
        "schemaVersion": 1,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": "sc2api_query",
        "worker_unit_type": WORKER_UNIT_TYPE,
        "probes": [],
        "summary": {},
    }

    # 1. Observation 找劳工和前哨基地
    obs_resp = await send_request(ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
    obs = obs_resp.observation

    workers = await find_units(obs, WORKER_UNIT_TYPE)
    ccs = await find_units(obs, COMMAND_CENTER_TYPE)
    result["worker_count"] = len(workers)
    result["command_center_count"] = len(ccs)
    print(f"  场上劳工: {len(workers)} 个", file=sys.stderr)
    print(f"  场上前哨基地: {len(ccs)} 个", file=sys.stderr)

    if not workers:
        result["error"] = "no_worker_found"
        return result

    # 选第一个劳工作为探针
    worker = workers[0]
    worker_tag = worker.tag
    worker_pos = (worker.pos.x, worker.pos.y)
    print(f"  选用劳工 tag={worker_tag} pos={worker_pos}", file=sys.stderr)

    # 2. 查询劳工所有可用能力（这是最权威的判定，包含 tech tree 状态）
    print(f"  查询劳工可用能力...", file=sys.stderr)
    available_abilities = await query_worker_abilities(ws, worker_tag)
    result["available_abilities"] = available_abilities
    print(f"  劳工可用能力数: {len(available_abilities)}", file=sys.stderr)

    # 3. 对每个预期能力做 placement 探测
    # 准备一组候选位置：劳工周围 5 个偏移点（避免单点失败误判）
    offsets = [(0, 0), (3, 0), (-3, 0), (0, 3), (0, -3), (5, 5), (-5, -5)]
    placements_positions = [(worker_pos[0] + dx, worker_pos[1] + dy) for dx, dy in offsets]

    # 若有前哨基地，再补一个前哨基地附近的位置
    if ccs:
        cc = ccs[0]
        placements_positions.append((cc.pos.x + 5, cc.pos.y + 5))

    for abil_id_str, cmd_idx, expected_unit, label in WORKER_BUILD_PROBES:
        probe_entry = {
            "abil_id": abil_id_str,
            "cmd_index": cmd_idx,
            "expected_unit": expected_unit,
            "label": label,
        }

        # ability_id 在 SC2API 中是整数 hash，不是字符串。
        # 我们用 RequestQueryAvailableAbilities 的结果反查：先查劳工可用能力列表，
        # 然后单独对每个能力做 placement 测试。但 ability_id 需要从 GameData 查询。
        # SC2 提供 RequestQueryAvailableAbilities 返回的是 ability_id 整数列表。
        # 为了把 abil_id_str 映射到整数，我们需要用 RequestData 获取能力目录。
        # 简化方案：直接用 placement 探测时传入字符串 ability_id 会被拒绝，
        # 所以这里只能依赖 available_abilities 列表做粗判。
        #
        # 更可靠做法：先 RequestData 拿到 ability_id → ability_name 映射，
        # 然后用对应的整数 ability_id 做 placement 测试。
        probe_entry["in_available_list"] = "pending"  # 后续补全
        result["probes"].append(probe_entry)

    # 4. 用 RequestData 获取 ability_id ↔ ability_name 映射
    print(f"  查询 ability 目录...", file=sys.stderr)
    data_req = sc_pb.Request(
        data=sc_pb.RequestData(
            ability_id=True,
            unit_type_id=True,
        )
    )
    data_resp = await send_request(ws, data_req)
    ability_map: dict[int, str] = {}
    unit_map: dict[int, str] = {}
    if data_resp.HasField("data"):
        for aid, aname in data_resp.data.abilities.items():
            ability_map[aid] = aname
        for uid, uname in data_resp.data.units.items():
            unit_map[uid] = uname
    result["ability_catalog_size"] = len(ability_map)
    result["unit_catalog_size"] = len(unit_map)

    # 反向映射：ability_name → ability_id
    name_to_aid: dict[str, int] = {v: k for k, v in ability_map.items()}

    # 5. 用 available_abilities 列表判定每个 build 能力是否在可用列表
    # 注意：available_abilities 的元素是 AvailableAbility 消息（含 ability_id 字段），
    # 不是 uint32。必须用 a.ability_id 索引 ability_map，否则会触发 unhashable 错误。
    available_names = {ability_map.get(a.ability_id, f"unknown_{a.ability_id}") for a in available_abilities}
    # 提取 ability_id 整数集合，用于后续 in 判断（不能直接用消息对象做 in 比较）
    available_ability_ids = {a.ability_id for a in available_abilities}
    result["available_ability_names"] = sorted(available_names)

    for probe_entry in result["probes"]:
        abil_str = probe_entry["abil_id"]
        # CAbilBuild 的能力名通常是 "<abil_id>" 或 "<abil_id><BuildN>"
        # SC2API 的 ability_id 对应的是 AbilityCommand，格式为 "<abil_id>:<cmd>"
        # 我们需要查找 ability_map 里所有以 abil_str 开头的项
        matching_aids = [aid for aid, name in ability_map.items() if name.startswith(abil_str)]
        probe_entry["matching_ability_ids"] = [
            {"aid": aid, "name": ability_map[aid]} for aid in matching_aids
        ]

        # 判断该能力是否在 available_abilities 中
        in_list = any(aid in available_ability_ids for aid in matching_aids)
        probe_entry["in_available_list"] = in_list

        # 若在可用列表中，尝试做 placement 测试
        if matching_aids:
            # 取第一个匹配的 ability_id 做 placement 测试
            test_aid = matching_aids[0]
            try:
                placement_results = await query_placement(ws, test_aid, placements_positions)
                probe_entry["placement_results"] = {
                    "ability_id": test_aid,
                    "ability_name": ability_map[test_aid],
                    "positions_tested": len(placements_positions),
                    "any_placeable": any(placement_results),
                    "results": placement_results,
                }
            except Exception as e:
                probe_entry["placement_error"] = str(e)
        else:
            probe_entry["placement_results"] = None
            probe_entry["placement_note"] = "ability_id not found in catalog"

    # 6. 汇总
    in_list_count = sum(1 for p in result["probes"] if p.get("in_available_list"))
    placeable_count = sum(
        1 for p in result["probes"]
        if p.get("placement_results") and p["placement_results"]["any_placeable"]
    )
    result["summary"] = {
        "total_probes": len(result["probes"]),
        "in_available_list": in_list_count,
        "placeable": placeable_count,
        "not_in_list": len(result["probes"]) - in_list_count,
    }

    return result


async def main_async(port: int, out_dir: Path) -> int:
    url = f"ws://127.0.0.1:{port}/sc2api"
    print(f"连接 SC2 API: {url}", file=sys.stderr)

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "sc2api_worker_probe.json"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, max_msg_size=0) as ws:
                print("连接已建立", file=sys.stderr)

                # ping 确认
                ping_resp = await send_request(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
                if ping_resp.HasField("ping"):
                    print(
                        f"  服务器版本: {ping_resp.ping.game_version} "
                        f"(base_build={ping_resp.ping.base_build})",
                        file=sys.stderr,
                    )

                result = await probe(ws, out_dir)

    except aiohttp.ClientConnectorError as e:
        print(f"连接失败: {e}", file=sys.stderr)
        print(f"  确认 SC2 已以 -listen 127.0.0.1 -port {port} 启动", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"探针异常: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 2

    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"结果已写入: {out_path}", file=sys.stderr)
    print(f"汇总: {result['summary']}", file=sys.stderr)
    return 0


def main():
    parser = argparse.ArgumentParser(description="SC2API 劳工可建造建筑探针")
    parser.add_argument("--port", type=int, default=5000, help="SC2 API 监听端口")
    parser.add_argument("--out-dir", type=str, default=None, help="输出目录")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "artifacts" / "runtime" / "sc2api-probe"
    return asyncio.run(main_async(args.port, out_dir))


if __name__ == "__main__":
    sys.exit(main())
