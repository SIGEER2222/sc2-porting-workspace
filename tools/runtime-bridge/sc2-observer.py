"""SC2 运行时观察器：连接 SC2 进程的 SC2 API websocket，被动收集事件流。

复用 SC2-Neuro-API-Integration 的 s2clientprotocol（vendored 包），但不依赖其
TerminalApp GUI 集成。只读模式：不发送任何 action 指令，只拉取 Observation。

用法:
  python tools/runtime-bridge/sc2-observer.py --port 5000 [--duration 120] [--scenario <file>] [--out-dir <dir>]

输出:
  <out-dir>/events.ndjson   逐帧事件流（每行一个 JSON 事件）
  <out-dir>/verdict.json    断言结果（仅当指定 --scenario 时）
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

# 复用 SC2-Neuro 的 vendored s2clientprotocol 包
REPO_ROOT = Path(__file__).resolve().parents[2]
NEURO_PROTOCOL_PATH = REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"
sys.path.insert(0, str(NEURO_PROTOCOL_PATH))

try:
    from s2clientprotocol import sc2api_pb2 as sc_pb
    HAS_PROTOBUF = True
except ImportError as e:
    HAS_PROTOBUF = False
    PROTOBUF_IMPORT_ERROR = str(e)

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False


# ---------- 事件提取 ----------

def extract_events_from_observation(
    obs: Any,
    frame: int,
    t: float,
    prev_unit_tags: set[int],
    prev_unit_types: dict[int, int],
) -> list[dict]:
    """从 Observation protobuf 提取事件。每帧可能有 0 到 N 个事件。

    单位事件通过前后帧 tag 对比识别真正的创建/消失，避免每帧都误报 unit_created。
    prev_unit_tags / prev_unit_types 会被本函数更新（引用修改）。
    """
    events = []

    # 1. 资源状态
    try:
        player_common = obs.player_common
        if player_common.HasField("minerals") or player_common.HasField("vespene"):
            events.append({
                "t": round(t, 3),
                "frame": frame,
                "type": "resource",
                "minerals": player_common.minerals,
                "gas": player_common.vespene,
                "food_used": player_common.food_used,
                "food_cap": player_common.food_cap,
            })
    except Exception:
        pass

    # 2. 单位创建/死亡事件：对比前后帧 tag 集合
    try:
        units = list(obs.observation.raw.units)
        current_tags: set[int] = set()
        current_types: dict[int, int] = {}
        new_units: list[Any] = []
        for u in units:
            current_tags.add(u.tag)
            current_types[u.tag] = u.unit_type
            if u.tag not in prev_unit_tags:
                new_units.append(u)

        # 新出现的单位 → unit_created 事件（含 unit_type 和 owner，方便按类型/玩家过滤）
        for u in new_units:
            events.append({
                "t": round(t, 3),
                "frame": frame,
                "type": "unit_created",
                "unit_type": u.unit_type,
                "tag": u.tag,
                "owner": u.owner,
            })

        # 消失的单位 → unit_lost 事件
        for tag in prev_unit_tags - current_tags:
            events.append({
                "t": round(t, 3),
                "frame": frame,
                "type": "unit_lost",
                "unit_type": prev_unit_types.get(tag, 0),
                "tag": tag,
            })

        # 更新 prev 状态供下一帧使用
        prev_unit_tags.clear()
        prev_unit_tags.update(current_tags)
        prev_unit_types.clear()
        prev_unit_types.update(current_types)
    except Exception:
        pass

    # 3. 游戏错误事件（ScriptError 是最关键的）
    try:
        for error in obs.errors:
            events.append({
                "t": round(t, 3),
                "frame": frame,
                "type": "game_error",
                "code": error.code,
                "message": str(error),
            })
    except Exception:
        pass

    # 4. 触发器事件（如果有）
    try:
        for te in obs.observation.alerts:
            events.append({
                "t": round(t, 3),
                "frame": frame,
                "type": "alert",
                "alert": te,
            })
    except Exception:
        pass

    # 5. 游戏结束事件
    try:
        if obs.HasField("game_status") and obs.game_status == 22:  # ended
            events.append({
                "t": round(t, 3),
                "frame": frame,
                "type": "game_ended",
            })
    except Exception:
        pass

    return events


def extract_initial_state(obs: Any, t: float) -> dict:
    """提取游戏启动时的初始状态（地图/玩家信息等）。"""
    state = {"t": round(t, 3), "type": "game_info"}
    try:
        gi = obs.game_info
        state["map_name"] = gi.map_name
        state["local_map_path"] = gi.local_map_path
        state["player_count"] = len(gi.player_info)
    except Exception:
        pass
    return state


# ---------- 断言 ----------

def evaluate_verdict(events: list[dict], scenario: dict) -> dict:
    """根据 scenario 中的 expectations 评估事件流，生成 verdict。"""
    expectations = scenario.get("expectations", [])
    results = []
    all_passed = True

    for i, exp in enumerate(expectations):
        exp_type = exp.get("type", "")
        result = {"id": exp.get("id", f"exp-{i}"), "type": exp_type, "passed": False, "evidence": []}

        if exp_type == "no_script_error":
            errors = [e for e in events if e.get("type") == "game_error"]
            result["passed"] = len(errors) == 0
            result["evidence"] = [{"frame": e.get("frame"), "message": e.get("message")} for e in errors[:5]]
            if not result["passed"]:
                all_passed = False

        elif exp_type == "unit_created":
            # 字段约定：unit_type（int，UnitTypeID）；from_player（int，玩家 ID）；within（frame 上限）
            expected_unit_type = exp.get("unit_type")
            within = exp.get("within", 9999)
            from_player = exp.get("from_player")
            matching = []
            for e in events:
                if e.get("type") != "unit_created":
                    continue
                if e.get("frame", 0) > within:
                    continue
                if expected_unit_type is not None and e.get("unit_type") != expected_unit_type:
                    continue
                if from_player is not None and e.get("owner") != from_player:
                    continue
                matching.append(e)
            result["passed"] = len(matching) > 0
            result["evidence"] = [
                {"frame": e.get("frame"), "unit_type": e.get("unit_type"), "tag": e.get("tag"), "owner": e.get("owner")}
                for e in matching[:3]
            ]
            if not result["passed"]:
                all_passed = False

        elif exp_type == "game_ended":
            ended = any(e.get("type") == "game_ended" for e in events)
            result["passed"] = ended
            if not result["passed"]:
                all_passed = False

        else:
            result["passed"] = False
            result["evidence"] = [{"message": f"未知断言类型: {exp_type}"}]
            all_passed = False

        results.append(result)

    return {
        "schemaVersion": 1,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenario_id": scenario.get("id", "unknown"),
        "overall_passed": all_passed,
        "expectations": results,
        "total_events": len(events),
    }


# ---------- 主连接逻辑 ----------

async def observe_game(port: int, duration: float, out_dir: Path, scenario: dict | None = None) -> int:
    """连接 SC2 API websocket，被动收集事件流。"""
    if not HAS_PROTOBUF:
        print(f"错误：无法导入 s2clientprotocol。{PROTOBUF_IMPORT_ERROR}", file=sys.stderr)
        print(f"  检查路径: {NEURO_PROTOCOL_PATH}", file=sys.stderr)
        return 2

    if not HAS_AIOHTTP:
        print("错误：缺少 aiohttp 依赖。请运行: pip install aiohttp", file=sys.stderr)
        return 2

    out_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / "events.ndjson"
    verdict_path = out_dir / "verdict.json"

    url = f"ws://127.0.0.1:{port}/sc2api"

    print(f"连接到 SC2 API: {url}", file=sys.stderr)
    print(f"事件输出: {events_path}", file=sys.stderr)
    if scenario:
        print(f"断言模式: {len(scenario.get('expectations', []))} 条 expectations", file=sys.stderr)

    all_events = []
    start_time = time.time()
    frame = 0
    # 前一帧的单位 tag 集合与 tag→unit_type 映射，用于识别真正的 unit_created / unit_lost。
    # 首帧 prev 为空，所有单位都会被记为 unit_created（这是预期行为：表示初始场上单位）。
    prev_unit_tags: set[int] = set()
    prev_unit_types: dict[int, int] = {}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, max_msg_size=0) as ws:
                print("连接已建立", file=sys.stderr)

                # 1. ping 确认连接
                ping_req = sc_pb.Request(ping=sc_pb.RequestPing())
                await ws.send_bytes(ping_req.SerializeToString())
                ping_resp_data = await ws.receive_bytes()
                ping_resp = sc_pb.Response()
                ping_resp.ParseFromString(ping_resp_data)
                if ping_resp.HasField("ping"):
                    ping_event = {
                        "t": round(time.time() - start_time, 3),
                        "frame": 0,
                        "type": "ping",
                        "server_version": ping_resp.ping.base_version,
                        "data_version": ping_resp.ping.data_version,
                    }
                    all_events.append(ping_event)
                    print(f"  服务器版本: {ping_resp.ping.base_version}", file=sys.stderr)

                # 2. 循环拉取 Observation
                with open(events_path, "w", encoding="utf-8") as f:
                    while True:
                        elapsed = time.time() - start_time
                        if duration > 0 and elapsed > duration:
                            print(f"达到时长上限 {duration}s，停止观察", file=sys.stderr)
                            break

                        # 发送 Observation 请求（不 step）
                        obs_req = sc_pb.Request(observation=sc_pb.RequestObservation())
                        await ws.send_bytes(obs_req.SerializeToString())

                        try:
                            resp_data = await asyncio.wait_for(ws.receive_bytes(), timeout=10.0)
                        except asyncio.TimeoutError:
                            print("警告：observation 请求超时（10s）", file=sys.stderr)
                            continue
                        except Exception as e:
                            if "closed" in str(e).lower():
                                print("连接已关闭（游戏可能结束）", file=sys.stderr)
                                break
                            raise

                        resp = sc_pb.Response()
                        resp.ParseFromString(resp_data)

                        if resp.error:
                            print(f"响应错误: {resp.error}", file=sys.stderr)
                            break

                        if not resp.HasField("observation"):
                            print("响应无 observation 字段", file=sys.stderr)
                            continue

                        # 提取事件（extract_events_from_observation 会就地更新 prev_unit_* ）
                        t = elapsed
                        frame_events = extract_events_from_observation(
                            resp.observation, frame, t, prev_unit_tags, prev_unit_types
                        )
                        for evt in frame_events:
                            all_events.append(evt)
                            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
                            f.flush()
                        frame += 1

                        # 简短休眠避免刷屏（SC2 自己在推进游戏）
                        await asyncio.sleep(0.1)

    except aiohttp.ClientConnectorError as e:
        print(f"连接失败: {e}", file=sys.stderr)
        print(f"  确认 SC2 已启动并在端口 {port} 监听", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"观察过程异常: {e}", file=sys.stderr)
        return 2

    # 计算 verdict 一次，避免重复 evaluate_verdict 调用造成的不一致
    verdict = evaluate_verdict(all_events, scenario) if scenario else None
    if verdict is not None:
        with open(verdict_path, "w", encoding="utf-8") as f:
            json.dump(verdict, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"断言结果: {verdict_path} (overall_passed={verdict['overall_passed']})", file=sys.stderr)

    print(f"共收集 {len(all_events)} 个事件，{frame} 帧", file=sys.stderr)
    return 0 if (verdict is None or verdict["overall_passed"]) else 1


def main():
    parser = argparse.ArgumentParser(description="SC2 运行时观察器：被动收集事件流")
    parser.add_argument("--port", type=int, required=True, help="SC2 API 监听端口")
    parser.add_argument("--duration", type=float, default=120.0, help="最长观察时长（秒，0=无限）")
    parser.add_argument("--scenario", type=str, default=None, help="断言 scenario JSON 文件路径")
    parser.add_argument("--out-dir", type=str, default=None, help="输出目录（默认 artifacts/runtime/）")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "artifacts" / "runtime"

    scenario = None
    if args.scenario:
        scenario_path = Path(args.scenario)
        if not scenario_path.exists():
            print(f"错误：scenario 文件不存在: {scenario_path}", file=sys.stderr)
            return 1
        with open(scenario_path, "r", encoding="utf-8") as f:
            scenario = json.load(f)

    return asyncio.run(observe_game(args.port, args.duration, out_dir, scenario))


if __name__ == "__main__":
    sys.exit(main())
