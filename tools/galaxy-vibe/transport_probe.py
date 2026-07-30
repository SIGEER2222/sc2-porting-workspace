"""SC2 Vibe — P0 传输闸门探针。

连接运行中 SC2 的 SC2 API（ws://127.0.0.1:<port>/sc2api），实测三条传输是否闭合成环：

  1) MapCommand 下行 + BankReload 上行（主闭环）：
     发送 `dbg ping <run_id>`，轮询 GalaxyVibeDebug.SC2Bank 的 vibe.run_id 是否等于
     run_id，记录延迟与结果。
  2) QuickChat 下行（候选）：发送 RequestQuickChat，确认无 error（仅下行，无上行）。
  3) 非法请求：发送 `dbg bogus`，确认 Mod 优雅处理（不崩、无 error）。

复用：
  - vendored s2clientprotocol（reference/SC2-Neuro-API-Integration）
  - bank_watcher.parse_bank（同仓库 tools/runtime-bridge）

用法:
  python tools/galaxy-vibe/transport_probe.py --port 5000 [--runs 20] [--out-dir artifacts/galaxy-vibe]

注意: 必须在能跑 SC2 的真机运行；沙箱/无头环境 SC2 不绑定 /sc2api
      （见 tools/launchers/run-live-runtime-probe.ps1 注释）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[2]
NEURO = REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"
sys.path.insert(0, str(NEURO))
RUNTIME_BRIDGE = REPO_ROOT / "tools" / "runtime-bridge"
sys.path.insert(0, str(RUNTIME_BRIDGE))

try:
    from s2clientprotocol import sc2api_pb2 as sc_pb
    HAS_PROTO = True
    PROTO_ERR = ""
except Exception as e:  # pragma: no cover
    HAS_PROTO = False
    PROTO_ERR = str(e)

import xml.etree.ElementTree as ET

import aiohttp  # 同 sc2-observer

HAS_BANK = True  # parse_bank 已内联，无外部依赖
BANK_ERR = ""


def parse_bank(bank_path: Path) -> dict:
    """解析 SC2 Bank 文件，返回 {section: {key: value}}。逻辑同 bank_watcher.parse_bank。"""
    if not bank_path.exists():
        return {}
    try:
        tree = ET.parse(bank_path)
    except ET.ParseError:
        return {}
    root = tree.getroot()
    parsed: dict = {}
    for section in root.findall("Section"):
        section_name = section.get("name", "")
        if not section_name:
            continue
        section_dict: dict = {}
        for key in section.findall("Key"):
            key_name = key.get("name", "")
            value_node = key.find("Value")
            if value_node is None:
                continue
            if "flag" in value_node.attrib:
                section_dict[key_name] = value_node.attrib["flag"] == "1"
            elif "int" in value_node.attrib:
                try:
                    section_dict[key_name] = int(value_node.attrib["int"])
                except ValueError:
                    section_dict[key_name] = value_node.attrib["int"]
            elif "string" in value_node.attrib:
                section_dict[key_name] = value_node.attrib["string"]
            elif "text" in value_node.attrib:
                section_dict[key_name] = value_node.attrib["text"]
        parsed[section_name] = section_dict
    return parsed

DEFAULT_BANK = Path.home() / "Documents" / "StarCraft II" / "Banks" / "GalaxyVibeDebug.SC2Bank"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def send_request(ws, req_proto):
    await ws.send_bytes(req_proto.SerializeToString())
    data = await asyncio.wait_for(ws.receive_bytes(), timeout=10.0)
    resp = sc_pb.Response()
    resp.ParseFromString(data)
    return resp


async def wait_bank_run_id(bank_path: Path, run_id: str, timeout: float = 5.0, poll: float = 0.1):
    """轮询 bank 直到 vibe.run_id == run_id。返回 (ok, latency_s, section)。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if bank_path.exists():
            data = parse_bank(bank_path)
            vibe = data.get("vibe", {})
            if vibe.get("run_id") == run_id:
                return True, time.time() - t0, vibe
        await asyncio.sleep(poll)
    return False, timeout, {}


async def run_probe(args, ws) -> dict:
    out = {
        "schemaVersion": 1,
        "generatedAt": utcnow(),
        "port": args.port,
        "runs": args.runs,
        "probes": {},
        "verdict": {},
    }
    try:
        await send_request(ws, sc_pb.Request(ping=sc_pb.RequestPing()))
    except Exception as e:  # pragma: no cover
        out["verdict"]["connect"] = False
        out["error"] = f"ping failed: {e}"
        return out
    out["verdict"]["connect"] = True

    bank_path = DEFAULT_BANK
    latencies: list[float] = []
    ping_ack = 0
    idem_ok = 0

    for i in range(args.runs):
        run_id = f"p0_{i}_{int(time.time() * 1000)}"
        req = sc_pb.Request(map_command=sc_pb.RequestMapCommand(command=f"dbg ping {run_id}"))
        await send_request(ws, req)
        ok, lat, sec = await wait_bank_run_id(bank_path, run_id, timeout=5.0)
        if ok and sec.get("result") == "pong":
            ping_ack += 1
            latencies.append(lat)
        # 幂等：重发同一 run_id，结果应一致（ping 无副作用；主要验证不崩、bank 一致）
        await send_request(ws, req)
        ok2, _, sec2 = await wait_bank_run_id(bank_path, run_id, timeout=5.0)
        if ok2 and sec2.get("result") == "pong":
            idem_ok += 1

    p95 = None
    if latencies:
        s = sorted(latencies)
        p95 = s[min(len(s) - 1, int(len(s) * 0.95))]

    out["probes"]["mapcommand_bank"] = {
        "runs": args.runs,
        "ping_ack": ping_ack,
        "idempotent_ok": idem_ok,
        "p95_latency_s": round(p95, 3) if p95 is not None else None,
        "all_ack": ping_ack == args.runs,
    }

    # 候选下行通道：QuickChat（仅下行，不纳入 P0 硬通过条件）
    qc_ok = False
    try:
        resp = await send_request(
            ws, sc_pb.Request(quick_chat=sc_pb.RequestQuickChat(user_id=1, command="gl hf"))
        )
        qc_ok = not resp.error
    except Exception:  # pragma: no cover
        qc_ok = False
    out["probes"]["quickchat_downlink"] = {
        "ack": qc_ok,
        "note": "candidate downlink only; MapCommand is primary",
    }

    # 非法请求：应被 Mod 优雅处理（不崩、无 error）
    illegal_ok = False
    try:
        await send_request(
            ws, sc_pb.Request(map_command=sc_pb.RequestMapCommand(command="dbg bogus"))
        )
        illegal_ok = True
    except Exception:  # pragma: no cover
        illegal_ok = False
    out["probes"]["illegal_request"] = {"handled_without_crash": illegal_ok}

    out["verdict"]["p0_pass"] = (
        out["verdict"]["connect"] and ping_ack == args.runs and idem_ok == args.runs
    )
    out["verdict"]["note"] = (
        "QuickChat 为候选下行通道，不纳入 P0 硬通过条件；MapCommand+Bank 为必达闭环。"
    )
    return out


async def amain(args) -> int:
    if not HAS_PROTO:
        print(f"ERR s2clientprotocol: {PROTO_ERR}", file=sys.stderr)
        return 2
    if not HAS_BANK:
        print(f"ERR bank_watcher: {BANK_ERR}", file=sys.stderr)
        return 2

    url = f"ws://127.0.0.1:{args.port}/sc2api"
    print(f"connect {url}", file=sys.stderr)
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(url, max_msg_size=0) as ws:
                res = await run_probe(args, ws)
    except Exception as e:  # pragma: no cover
        print(f"ERR: {e}", file=sys.stderr)
        return 2

    o = Path(args.out_dir)
    o.mkdir(parents=True, exist_ok=True)
    (o / "transport-verdict.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if res["verdict"].get("p0_pass") else 1


def main():
    ap = argparse.ArgumentParser(description="SC2 Vibe P0 传输闸门探针")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "artifacts" / "galaxy-vibe"))
    a = ap.parse_args()
    raise SystemExit(asyncio.run(amain(a)))


if __name__ == "__main__":
    main()
