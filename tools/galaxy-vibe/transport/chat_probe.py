"""Chat 传输 Probe — P0 传输闸门测试（备用 transport）。

测试通过 SC2API 聊天消息触发 Kernel（聊天前缀 "!dbg"）。
与 Bank probe 执行相同的测试矩阵，验证 chat 作为 transport 的可行性。

使用：
  python -m tools.galaxy-vibe.transport.chat_probe --port 5000 --out-dir artifacts/galaxy-vibe/p0-transport
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from host.vibe_host import VibeHost  # noqa: E402


def run_sequential_pings_chat(host: VibeHost, count: int = 20) -> dict:
    """通过 chat transport 发送 20 次顺序 ping。"""
    results = []
    for i in range(count):
        t0 = time.time()
        resp = host.request("system.ping", {}, transport="chat", timeout=5.0)
        latency_ms = (time.time() - t0) * 1000
        results.append({
            "index": i,
            "request_id": resp.request_id,
            "error_code": resp.error_code,
            "latency_ms": round(latency_ms, 2),
            "is_ok": resp.is_ok,
        })
    ok_count = sum(1 for r in results if r["is_ok"])
    latencies = sorted(r["latency_ms"] for r in results)
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    return {
        "test": "sequential_pings_chat",
        "count": count,
        "ok_count": ok_count,
        "all_acked": ok_count == count,
        "p95_ms": round(p95, 2),
        "p95_within_2s": p95 <= 2000,
        "results": results,
    }


def run_illegal_requests_chat(host: VibeHost, count: int = 5) -> dict:
    """通过 chat transport 发送 5 个非法请求。"""
    illegal_ops = [
        ("system.bogus", {}),
        ("unit.spawn", {"unit_type": "NonExistentUnit", "count": 1, "player": 1}),
        ("unit.spawn", {"unit_type": "Marine", "count": 99999, "player": 1}),
        ("unit.spawn", {"unit_type": "Marine", "count": 1, "player": 99}),
        ("call_arbitrary_func", {"func": "UnitKillAll"}),
    ]
    results = []
    for i, (op, args) in enumerate(illegal_ops[:count]):
        resp = host.request(op, args, transport="chat", timeout=3.0)
        results.append({
            "index": i,
            "operation": op,
            "error_code": resp.error_code,
            "rejected": resp.error_code in ("UNKNOWN_OPERATION", "INVALID_ARGS",
                                            "COUNT_OUT_OF_RANGE", "PLAYER_OUT_OF_RANGE"),
        })
    return {
        "test": "illegal_requests_chat",
        "count": count,
        "all_rejected": all(r["rejected"] for r in results),
        "results": results,
    }


def run_chat_probe(port: int, out_dir: Path) -> dict:
    """运行完整 Chat transport probe。"""
    host = VibeHost(sc2_port=port, artifacts_dir=out_dir.parent)
    if not host.connect_sc2():
        return {"transport": "chat", "verdict": "blocked", "reason": "SC2 连接失败"}

    host.start_session()

    print("[chat_probe] 测试 1/2: 20 次顺序 ping（chat transport）...", flush=True)
    t1 = run_sequential_pings_chat(host, 20)

    print("[chat_probe] 测试 2/2: 5 个非法请求（chat transport）...", flush=True)
    t2 = run_illegal_requests_chat(host, 5)

    verdict = {
        "transport": "chat",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "tests": {
            "sequential_pings": t1,
            "illegal_requests": t2,
        },
        "verdict": "passed" if (t1["all_acked"] and t1["p95_within_2s"] and t2["all_rejected"]) else "failed",
        "notes": "chat transport 适合人工调试，程序化触发可能被聊天限流",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "chat-probe-result.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    host.close()
    return verdict


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--out-dir", type=str, default="artifacts/galaxy-vibe/p0-transport")
    args = parser.parse_args()
    result = run_chat_probe(args.port, Path(args.out_dir))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["verdict"] == "passed" else 1)
