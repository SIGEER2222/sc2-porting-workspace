"""Chat 传输 Probe — P0 传输闸门测试（备用 transport）。

测试通过 SC2API 聊天消息触发 Kernel（聊天前缀 "!dbg"）。
与 Bank probe 执行相同的测试矩阵，验证 chat 作为 transport 的可行性。

使用：
  python -m tools.galaxy-vibe.transport.chat_probe --port 5000 --out-dir artifacts/galaxy-vibe/p0-transport
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from host.vibe_host import VibeHost  # noqa: E402
# 复用 bank_probe 的结局分类器作为**单一事实源**，避免两份实现漂移。
# 关键语义：`INTERNAL_ERROR` 只由 host 侧产生（内核 .galaxy 从不产生），
# 因此它代表「没拿到裁决」，不可读作「内核给出了错误裁决」。
from bank_probe import _classify_outcome  # noqa: E402


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
            "outcome": _classify_outcome(resp, latency_ms, 5.0),
        })
    ok_count = sum(1 for r in results if r["is_ok"])
    timeout_count = sum(1 for r in results if r["outcome"] == "timeout")
    latencies = sorted(r["latency_ms"] for r in results)
    # 与 bank_probe 同步修正：原 `latencies[int(n*0.95)]` 在 n=20 时取 index 19 = 最大值（实为 p100）。
    # 改用标准 nearest-rank p95，并记录 max/median/超阈样本；verdict 判据不放宽。
    n = len(latencies)
    p95 = latencies[min(n - 1, math.ceil(0.95 * n) - 1)] if n else 0
    over_2s = [r["index"] for r in results if r["latency_ms"] > 2000]
    return {
        "test": "sequential_pings_chat",
        "count": count,
        "ok_count": ok_count,
        "all_acked": ok_count == count,
        "p95_ms": round(p95, 2),
        "p95_within_2s": p95 <= 2000,
        "timeout_count": timeout_count,
        "p95_right_censored": timeout_count > 0,
        "median_ms": round(latencies[n // 2], 2) if n else 0,
        "max_ms": round(latencies[-1], 2) if n else 0,
        "min_ms": round(latencies[0], 2) if n else 0,
        "over_2s_count": len(over_2s),
        "over_2s_indices": over_2s,
        "p95_statistically_meaningful": n >= 100,
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
        t0 = time.time()
        resp = host.request(op, args, transport="chat", timeout=3.0)
        latency_ms = (time.time() - t0) * 1000
        results.append({
            "index": i,
            "operation": op,
            "error_code": resp.error_code,
            "latency_ms": round(latency_ms, 2),
            "outcome": _classify_outcome(resp, latency_ms, 3.0),
            "rejected": resp.error_code in ("UNKNOWN_OPERATION", "INVALID_ARGS",
                                            "COUNT_OUT_OF_RANGE", "PLAYER_OUT_OF_RANGE"),
        })
    adjudicated = [r for r in results if r["outcome"] != "timeout"]
    adjudication_complete = len(adjudicated) == len(results)
    all_rejected_adjudicated = all(r["rejected"] for r in adjudicated)
    return {
        "test": "illegal_requests_chat",
        "count": count,
        # 与旧口径严格等价，仅把失败原因拆得可读（详见 bank_probe 同名字段注释）。
        "all_rejected": adjudication_complete and all_rejected_adjudicated,
        "all_rejected_adjudicated": all_rejected_adjudicated,
        "adjudication_complete": adjudication_complete,
        "indeterminate_count": len(results) - len(adjudicated),
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
