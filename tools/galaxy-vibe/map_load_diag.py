#!/usr/bin/env python3
"""map_load_diag.py — 判定一张打包地图在真机 SC2 里到底"活到哪一步"

背景：P0 探针只能看到"Bank 里没有 kernel 标记"，这个信号太粗——
它同时对应三种完全不同的失败：
    L1 地图根本没进游戏          -> create_game / join_game 失败
    L2 进了游戏但 MapScript 没跑 -> 观测里看不到任何脚本产物（单位 0 / 只有地形预置）
    L3 MapScript 跑了但 Kernel 没注册 -> 有单位、无 bank
    L4 Kernel 注册了但 Bank 不通 -> 有 bank 但缺 key（CMRE-RUNTIME-003）
本工具用"可观测单位通路"把 L2/L3 切开，这是 src/lib/cmlib_runtime_test.py
在真机验证过的技术（Ghost 哨兵 16/16 通过）。

用法:
    python map_load_diag.py --map "E:/SC2/.../VibeDeadOfNight.SC2Map" [--steps 900]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src" / "lib"))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402
from s2clientprotocol import common_pb2 as sc_common  # noqa: E402
from sc2_api_conn import acquire_launched, api_url  # noqa: E402

BANKS_ROOT = Path(os.environ.get("USERPROFILE", "C:/Users/22448")) / "Documents" / "StarCraft II" / "Banks"


def _sub_err(resp, field: str):
    """安全读取 Response 子消息里的 error 枚举，返回 None 表示"没报错"。

    **坑（实测钉死）**：`ResponseCreateGame.error` / `ResponseJoinGame.error`
    都是 proto2 的 optional enum。proto2 未设置的 optional enum 读出来是
    **默认值 = 枚举首项 = 1**（MissingMap / MissingParticipation）。
    所以 `if r.join_game.error:` 在**成功时也恒为真**，会把每一次成功
    误判成 L1 失败。唯一可靠判定是 HasField('error')。
    """
    if not resp.HasField(field):
        return None
    sub = getattr(resp, field)
    if not sub.HasField("error"):
        return None
    return int(sub.error)


def _local_map(mode: str, path: Path, data: bytes):
    """构造 LocalMap。map_path 用绝对路径；bytes 直传绕开 Maps 目录与账号态。"""
    if mode == "bytes":
        return sc_pb.LocalMap(map_data=data)
    if mode == "path":
        return sc_pb.LocalMap(map_path=str(path))
    return sc_pb.LocalMap(map_path=str(path), map_data=data)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", required=True)
    ap.add_argument("--wait", type=float, default=45.0, help="realtime 下观测总时长（秒）")
    ap.add_argument("--mode", default="bytes", choices=["bytes", "path", "both"],
                    help="地图传递方式：bytes=map_data 直传 / path=map_path / both=同时给")
    ap.add_argument("--out", default=str(REPO / "artifacts" / "galaxy-vibe" / "map-load-diag.json"))
    args = ap.parse_args()

    map_path = Path(args.map)
    if not map_path.is_file():
        print(f"[X] 地图不存在: {map_path}")
        return 2
    md = map_path.read_bytes()
    print(f"[i] map bytes = {len(md)}")

    report: dict = {"map": str(map_path), "bytes": len(md)}
    url = api_url()
    print(f"[i] SC2 API = {url}")
    client = acquire_launched(url)

    # --- L1: 进游戏 ---
    # NOTE: player_setup / realtime 必须与 src/lib/cmlib_runtime_test.py 一致
    # （单 Participant + realtime=True）。用 2 玩家 + realtime=False 会直接 MissingMap(1)，
    # 这是踩过的坑：SC2 对 local_map 字节直传的 setup 组合很挑。
    r = client.send(sc_pb.Request(create_game=sc_pb.RequestCreateGame(
        local_map=_local_map(args.mode, map_path, md),
        player_setup=[sc_pb.PlayerSetup(type=1, race=sc_common.Terran, player_name="P1")],
        realtime=True)), 240)
    report["create_game_error"] = [int(e) for e in r.error] if r.error else []
    report["create_game_details"] = list(r.error_details) if hasattr(r, "error_details") else []
    report["create_game_sub_error"] = _sub_err(r, "create_game")
    print(f"[i] create_game top_err={report['create_game_error']} "
          f"sub_err={report['create_game_sub_error']}")
    if r.error or report["create_game_sub_error"] is not None:
        report["level"] = "L1_create_game_failed"
        _dump(report, args.out)
        return 1

    time.sleep(1.0)   # 不等一下 join 会撞上还在 init 的局
    r = client.send(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
        race=sc_common.Terran, options=sc_pb.InterfaceOptions(raw=True))), 180)
    report["join_error"] = _sub_err(r, "join_game")
    if r.error or report["join_error"] is not None:
        report["level"] = "L1_join_game_failed"
        report["join_top_error"] = [int(e) for e in r.error] if r.error else []
        _dump(report, args.out)
        return 1
    print(f"[i] join_game OK player_id={r.join_game.player_id}")

    # 单位类型表
    data = client.send(sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True)), 120)
    names = {u.unit_id: u.name for u in data.data.units}

    # --- L2/L3: realtime 下靠墙钟等待并采样 ---
    samples = []
    deadline = time.time() + args.wait
    while time.time() < deadline:
        time.sleep(2.0)
        obs = client.send(sc_pb.Request(observation=sc_pb.RequestObservation()), 120)
        o = obs.observation.observation
        counts: dict[str, int] = {}
        for u in o.raw_data.units:
            counts[names.get(u.unit_type, str(u.unit_type))] = \
                counts.get(names.get(u.unit_type, str(u.unit_type)), 0) + 1
        chat = [c.message for c in obs.observation.chat]
        banks = sorted(p.name for p in BANKS_ROOT.rglob("GalaxyVibe.SC2Bank"))
        samples.append({"loop": o.game_loop, "units": sum(counts.values()),
                        "top": dict(sorted(counts.items(), key=lambda kv: -kv[1])[:12]),
                        "chat": chat, "bank_files": banks})
        print(f"    loop={o.game_loop:5d} units={sum(counts.values()):4d} "
              f"bank={len(banks)} top={dict(sorted(counts.items(), key=lambda kv: -kv[1])[:6])}")
        if obs.observation.player_result:
            print("[!] 游戏已结束（player_result），停止推进")
            report["player_result"] = [str(pr) for pr in obs.observation.player_result]
            break

    report["samples"] = samples
    last = samples[-1] if samples else {}
    units = last.get("units", 0)
    banks = last.get("bank_files", [])
    if units == 0:
        report["level"] = "L2_mapscript_not_running"
        report["note"] = "进了游戏但一个单位都没有 -> MapScript 未执行（编译失败/加载失败）"
    elif not banks:
        report["level"] = "L3_kernel_not_registered"
        report["note"] = "MapScript 在跑（有单位），但 Kernel 没写 bank -> RegisterEntryPoints 未执行或 BankSave 失败"
    else:
        report["level"] = "L4_bank_present"
        report["note"] = "bank 已出现，检查 key 完整性"
    print(f"\n=== LEVEL: {report['level']} ===\n{report['note']}")
    _dump(report, args.out)
    return 0


def _dump(report: dict, out: str) -> None:
    p = Path(out)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[i] report -> {p}")


if __name__ == "__main__":
    sys.exit(main())
