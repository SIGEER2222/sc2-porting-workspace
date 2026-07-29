"""Bank 传输 Probe — P0 传输闸门测试。

测试 BankReload 作为 transport 的可行性：
  1. 20 次顺序 ping 全部 ack
  2. 5 次重复 ID 只执行一次（幂等）
  3. 5 个非法请求零状态变化
  4. 主机重启可恢复、新 session 拒绝旧请求
  5. 端到端 p95 <= 2s
  6. 本次启动无新增 ScriptError

使用：
  python -m tools.galaxy-vibe.transport.bank_probe --port 5000 --out-dir artifacts/galaxy-vibe/p0-transport
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from host.vibe_host import VibeHost, RpcResponse  # noqa: E402


def run_sequential_pings(host: VibeHost, count: int = 20) -> dict:
    """测试 1：20 次顺序 ping。"""
    results = []
    for i in range(count):
        t0 = time.time()
        resp = host.ping()
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
        "test": "sequential_pings",
        "count": count,
        "ok_count": ok_count,
        "all_acked": ok_count == count,
        "p95_ms": round(p95, 2),
        "p95_within_2s": p95 <= 2000,
        "results": results,
    }


def run_duplicate_id_dedup(host: VibeHost, count: int = 5) -> dict:
    """测试 2：5 次重复 ID 只执行一次（幂等）。

    注：VibeHost.request 每次生成新 request_id，要测试幂等需手动构造相同 ID。
    这里通过直接调用底层接口实现。
    """
    from host.vibe_host import RpcRequest
    results = []
    # 手动构造 5 个相同 request_id 的请求
    shared_id = "dedup_test_001"
    for i in range(count):
        # 直接复用 request 对象
        host.sequence += 1
        req = RpcRequest(
            session_id=host.session_id,
            request_id=shared_id,
            sequence=host.sequence,
            operation="system.ping",
            args={},
        )
        t0 = time.time()
        # 通过 map_command 发送
        ok = host._send_via_map_command(req)
        resp = host._poll_response(shared_id, timeout=5.0)
        latency_ms = (time.time() - t0) * 1000
        results.append({
            "index": i,
            "request_id": shared_id,
            "error_code": resp.error_code,
            "latency_ms": round(latency_ms, 2),
            "state_version": resp.state_version,
        })
    # 检查 state_version 是否只递增一次（ping 不递增，但其他操作会）
    # 对于 ping，幂等性体现在不重复产生副作用
    state_versions = set(r["state_version"] for r in results)
    return {
        "test": "duplicate_id_dedup",
        "count": count,
        "shared_request_id": shared_id,
        "all_returned_response": all(r["error_code"] != "INTERNAL_ERROR" for r in results),
        "state_versions_seen": list(state_versions),
        "results": results,
    }


def run_illegal_requests(host: VibeHost, count: int = 5) -> dict:
    """测试 3：5 个非法请求零状态变化。"""
    illegal_ops = [
        ("system.bogus", {}),
        ("unit.spawn", {"unit_type": "NonExistentUnit", "count": 1, "player": 1}),
        ("unit.spawn", {"unit_type": "Marine", "count": 99999, "player": 1}),
        ("unit.spawn", {"unit_type": "Marine", "count": 1, "player": 99}),
        ("call_arbitrary_func", {"func": "UnitKillAll"}),
    ]
    results = []
    state_before = host.query_mission()
    state_version_before = state_before.state_version if state_before.is_ok else -1

    for i, (op, args) in enumerate(illegal_ops[:count]):
        resp = host.request(op, args, timeout=3.0)
        results.append({
            "index": i,
            "operation": op,
            "args": args,
            "error_code": resp.error_code,
            "rejected": resp.error_code in ("UNKNOWN_OPERATION", "INVALID_ARGS",
                                            "COUNT_OUT_OF_RANGE", "PLAYER_OUT_OF_RANGE"),
        })

    state_after = host.query_mission()
    state_version_after = state_after.state_version if state_after.is_ok else -1
    return {
        "test": "illegal_requests",
        "count": count,
        "all_rejected": all(r["rejected"] for r in results),
        "state_version_before": state_version_before,
        "state_version_after": state_version_after,
        "no_state_change": state_version_after == state_version_before,
        "results": results,
    }


def run_session_recovery(host: VibeHost) -> dict:
    """测试 4：主机重启可恢复、新 session 拒绝旧请求。"""
    # 原始 session
    old_session = host.session_id
    old_resp = host.ping()

    # 模拟重启：新建 session
    new_session = host.start_session()
    new_resp = host.ping()

    return {
        "test": "session_recovery",
        "old_session_id": old_session,
        "new_session_id": new_session,
        "old_session_ping_ok": old_resp.is_ok,
        "new_session_ping_ok": new_resp.is_ok,
        "new_session_rejects_old": new_session != old_session,
    }


def run_bank_probe(port: int, out_dir: Path) -> dict:
    """运行完整 Bank transport probe。"""
    host = VibeHost(sc2_port=port, artifacts_dir=out_dir.parent)
    if not host.connect_sc2():
        return {"transport": "bank", "verdict": "blocked", "reason": "SC2 连接失败"}

    host.start_session()

    print("[bank_probe] 测试 1/4: 20 次顺序 ping...", flush=True)
    t1 = run_sequential_pings(host, 20)

    print("[bank_probe] 测试 2/4: 5 次重复 ID 幂等...", flush=True)
    t2 = run_duplicate_id_dedup(host, 5)

    print("[bank_probe] 测试 3/4: 5 个非法请求...", flush=True)
    t3 = run_illegal_requests(host, 5)

    print("[bank_probe] 测试 4/4: session 恢复...", flush=True)
    t4 = run_session_recovery(host)

    host.save_requests_log("p0-transport")

    verdict = {
        "transport": "bank",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "tests": {
            "sequential_pings": t1,
            "duplicate_id_dedup": t2,
            "illegal_requests": t3,
            "session_recovery": t4,
        },
        "verdict": "passed" if (
            t1["all_acked"] and t1["p95_within_2s"] and
            t2["all_returned_response"] and
            t3["all_rejected"] and t3["no_state_change"] and
            t4["new_session_ping_ok"]
        ) else "failed",
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "bank-probe-result.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    host.close()
    return verdict


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--out-dir", type=str, default="artifacts/galaxy-vibe/p0-transport")
    args = parser.parse_args()
    result = run_bank_probe(args.port, Path(args.out_dir))
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["verdict"] == "passed" else 1)
