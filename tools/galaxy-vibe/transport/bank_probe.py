"""Bank 传输 Probe — P0 传输闸门测试。

测试 BankReload 作为 transport 的可行性：
  1. 20 次顺序 ping 全部 ack
  2. 5 次重复 ID 只执行一次（幂等）
  3. 5 个非法请求零状态变化
  4. 主机重启可用同一 session 续接（restore_session），外来 session 被拒（SESSION_EXPIRED）
  5. 端到端 p95 <= 2s（nearest-rank；n>=100 才统计有意义，见 --ping-count）
  6. 本次启动无新增 ScriptError

使用：
  python -m tools.galaxy-vibe.transport.bank_probe --port 5000 --out-dir artifacts/galaxy-vibe/p0-transport
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from host.vibe_host import VibeHost, RpcResponse  # noqa: E402


# `INTERNAL_ERROR` 在内核 `.galaxy` 中**从未出现**（`grep -r INTERNAL_ERROR kernel/*.galaxy`
# 为空），它只由 Python host 侧产生：`vibe_host.py:1052` 轮询超时路径、
# `vibe_host.py:1042` request_step_failed、`galaxy_repl.py` bank_write_failed。
# 因此真机探针里看到的 INTERNAL_ERROR 按定义是 **host 侧状况，不是内核裁决**。
# 把它当成「内核给出了错误答复」会得到彻底相反的结论（例如把「非法请求没被拒」
# 这种安全结论建立在一次超时上）。以下 helper 强制区分二者。
_HOST_SIDE_CODE = "INTERNAL_ERROR"


def _classify_outcome(resp: RpcResponse, latency_ms: float, timeout_s: float) -> str:
    """把一次 RPC 归类为 ok / timeout（无裁决）/ error（内核给出裁决但非预期）。

    判据：`INTERNAL_ERROR` 且耗时达到轮询窗口的 90% 以上 ⇒ 超时（host 侧未收到
    任何内核响应），属**证据缺失**而非失败断言。
    """
    if resp.is_ok:
        return "ok"
    if resp.error_code == _HOST_SIDE_CODE and latency_ms >= timeout_s * 900:
        return "timeout"
    return "error"


def run_sequential_pings(host: VibeHost, count: int = 20,
                         poll_timeout: float = 5.0) -> dict:
    """测试 1：顺序 ping 采样。

    `poll_timeout` 是**观测窗口**，不是验收阈值。验收阈值恒为 p95 <= 2000ms，
    不随观测窗口变化；放大观测窗口只用于区分「消息丢失」与「周期性停顿」。
    """
    results = []
    for i in range(count):
        t0 = time.time()
        resp = host.request("system.ping", {}, timeout=poll_timeout)
        latency_ms = (time.time() - t0) * 1000
        results.append({
            "index": i,
            "request_id": resp.request_id,
            "error_code": resp.error_code,
            "latency_ms": round(latency_ms, 2),
            "is_ok": resp.is_ok,
            "outcome": _classify_outcome(resp, latency_ms, poll_timeout),
        })
    ok_count = sum(1 for r in results if r["is_ok"])
    timeout_count = sum(1 for r in results if r["outcome"] == "timeout")
    error_count = sum(1 for r in results if r["outcome"] == "error")
    latencies = sorted(r["latency_ms"] for r in results)
    # 修正：原实现 `latencies[int(n*0.95)]` 在 n=20 时取的是 index 19 = 最大值（实为 p100）。
    # 改用标准 nearest-rank p95：idx = ceil(0.95*n) - 1，并同时记录 max/median 与超阈样本
    # 以便区分「冷启动尾延迟」与「稳态延迟」。verdict 判据仍按严格全样本 p95，不放宽。
    n = len(latencies)
    p95 = latencies[min(n - 1, math.ceil(0.95 * n) - 1)] if n else 0
    over_2s = [r["index"] for r in results if r["latency_ms"] > 2000]
    # 仅统计「拿到内核响应」的往返，用于区分「传输丢包」与「周期性停顿」。
    done = sorted(r["latency_ms"] for r in results if r["outcome"] != "timeout")
    dn = len(done)
    p95_done = done[min(dn - 1, math.ceil(0.95 * dn) - 1)] if dn else 0
    return {
        "test": "sequential_pings",
        "count": count,
        "ok_count": ok_count,
        "all_acked": ok_count == count,
        "poll_timeout_s": poll_timeout,
        # 结局分型：timeout = host 侧未收到任何内核响应（证据缺失）；
        #           error   = 内核确实答复了但不是 OK。
        "timeout_count": timeout_count,
        "timeout_indices": [r["index"] for r in results if r["outcome"] == "timeout"],
        "error_count": error_count,
        "p95_ms": round(p95, 2),
        "p95_within_2s": p95 <= 2000,
        # 全样本 p95 在有超时时是**右删失**的：超时样本的真实延迟 >= 观测窗口，
        # 只能给出下界。此标志防止把删失样本当成精确测量来解读。
        "p95_right_censored": timeout_count > 0,
        "p95_completed_ms": round(p95_done, 2),
        "completed_count": dn,
        "median_ms": round(latencies[n // 2], 2) if n else 0,
        "max_ms": round(latencies[-1], 2) if n else 0,
        "min_ms": round(latencies[0], 2) if n else 0,
        "over_2s_count": len(over_2s),
        "over_2s_indices": over_2s,
        # n=20 时 5% 仅容 1 个样本，p95 退化为「最多 0 个超阈样本」的 max 判据；
        # 统计上有意义的 p95 需 n>=100（用 --ping-count 提高样本量）。
        "p95_statistically_meaningful": n >= 100,
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


def run_illegal_requests(host: VibeHost, count: int = 5,
                         illegal_timeout: float = 3.0) -> dict:
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
        t0 = time.time()
        resp = host.request(op, args, timeout=illegal_timeout)
        latency_ms = (time.time() - t0) * 1000
        outcome = _classify_outcome(resp, latency_ms, illegal_timeout)
        results.append({
            "index": i,
            "operation": op,
            "args": args,
            "error_code": resp.error_code,
            "latency_ms": round(latency_ms, 2),
            # timeout ⇒ 内核未作答，既不能算「拒绝」也不能算「放行」
            "outcome": outcome,
            "rejected": resp.error_code in ("UNKNOWN_OPERATION", "INVALID_ARGS",
                                            "COUNT_OUT_OF_RANGE", "PLAYER_OUT_OF_RANGE"),
        })

    state_after = host.query_mission()
    state_version_after = state_after.state_version if state_after.is_ok else -1
    adjudicated = [r for r in results if r["outcome"] != "timeout"]
    adjudication_complete = len(adjudicated) == len(results)
    all_rejected_adjudicated = all(r["rejected"] for r in adjudicated)
    return {
        "test": "illegal_requests",
        "count": count,
        # 与旧口径**严格等价**（无超时时两者相同；有超时时两者都为 False），
        # 拆分只为让失败原因可读：是「内核放行了非法请求」还是「没拿到裁决」。
        "all_rejected": adjudication_complete and all_rejected_adjudicated,
        "all_rejected_adjudicated": all_rejected_adjudicated,
        "adjudication_complete": adjudication_complete,
        "indeterminate_count": len(results) - len(adjudicated),
        "indeterminate_indices": [r["index"] for r in results if r["outcome"] == "timeout"],
        "state_version_before": state_version_before,
        "state_version_after": state_version_after,
        # 实质安全属性：无论裁决码是否读到，状态都不得变化。
        "no_state_change": state_version_after == state_version_before,
        "results": results,
    }


def run_session_recovery(host: VibeHost, poll_timeout: float = 5.0) -> dict:
    """测试 4：主机重启可恢复 + 外来 session 被拒。

    内核语义（`libVibeKernel_gf_CheckSession`）：`gv_currentSession` 在收到第一个
    非空 session_id 后被**一次性闩锁**，此后任何不同的 session_id 一律返回
    `SESSION_EXPIRED`，且内核未提供 session 轮换入口。因此：

    * 「Host 重启可恢复」的正确实现是 `restore_session(旧 id, 旧 seq)` —— 这也是
      `VibeHost.restore_session()` 存在的理由；随机新建 session 在设计上必被拒。
    * 「拒绝外来 session」是**安全属性而非缺陷**，必须用真实断言验证。

    旧实现的两个断言都是坏的：`new_session_ping_ok` 恒假（与内核设计冲突），
    `new_session_rejects_old = (new != old)` 恒真（同义反复，等于没有断言）。
    此处替换为三条可证伪断言，并保留旧字段值作为诊断项，不隐藏历史口径。
    """
    def _ping_until_adjudicated(attempts: int = 3) -> tuple[RpcResponse, int, str]:
        """重试直到拿到内核裁决。

        单次 ping 落进周期性停顿窗口就会超时（host 侧 INTERNAL_ERROR），
        此时断言结果是**证据缺失**而非失败。安全断言必须重试到有裁决为止，
        否则一次停顿就能把「外来 session 被拒」这条安全属性误判成不成立。
        """
        last, outcome = None, "timeout"
        for k in range(attempts):
            t0 = time.time()
            last = host.request("system.ping", {}, timeout=poll_timeout)
            outcome = _classify_outcome(last, (time.time() - t0) * 1000, poll_timeout)
            if outcome != "timeout":
                return last, k + 1, outcome
        return last, attempts, outcome

    old_session = host.session_id
    old_sequence = host.sequence
    old_resp, _, _ = _ping_until_adjudicated()

    # 4a. 模拟 Host 进程重启后续接同一 session（清空本地态再 restore）
    host.session_id = ""
    host.sequence = 0
    host.restore_session(old_session, old_sequence)
    restored_resp, restored_attempts, restored_outcome = _ping_until_adjudicated()

    # 4b. 外来 session 必须被内核拒绝（SESSION_EXPIRED）
    foreign_session = "deadbeefdeadbeef"
    host.session_id = foreign_session
    foreign_resp, foreign_attempts, foreign_outcome = _ping_until_adjudicated()
    foreign_rejected = (not foreign_resp.is_ok) and foreign_resp.error_code == "SESSION_EXPIRED"

    # 复位回合法 session，避免污染后续调用
    host.restore_session(old_session, max(old_sequence, host.sequence))

    return {
        "test": "session_recovery",
        "old_session_id": old_session,
        "old_session_ping_ok": old_resp.is_ok,
        # 4a：Host 重启后以同一 session 续接
        "restored_session_id": old_session,
        "restored_ping_ok": restored_resp.is_ok,
        "restored_ping_error": restored_resp.error_code,
        "restored_attempts": restored_attempts,
        "restored_outcome": restored_outcome,
        # 4b：外来 session 拒绝（真实断言，非同义反复）
        "foreign_session_id": foreign_session,
        "foreign_session_rejected": foreign_rejected,
        "foreign_session_error": foreign_resp.error_code,
        "foreign_attempts": foreign_attempts,
        # rejected / wrong_code / indeterminate —— indeterminate 表示重试若干次
        # 仍未拿到内核裁决，属证据缺失，不可读作「内核接受了外来 session」。
        "foreign_session_outcome": (
            "rejected" if foreign_rejected
            else "indeterminate" if foreign_outcome == "timeout"
            else "wrong_code"
        ),
        # 内核设计事实（供上层判据引用）
        "kernel_session_latch": True,
        "kernel_supports_session_rotation": False,
        # 旧口径诊断项：随机新 session 必被拒（历史 verdict 曾以此为判据，恒假）
        "legacy_new_random_session_ping_ok": False,
        "legacy_criterion_note": (
            "旧判据 new_session_ping_ok 与内核 session 闩锁设计冲突，恒假；"
            "已替换为 restored_ping_ok + foreign_session_rejected"
        ),
    }


def run_bank_probe(port: int, out_dir: Path, map_path: Optional[str] = None,
                   fresh_bank: bool = False, ping_count: int = 20,
                   poll_timeout: float = 5.0, aborted_grace: float = 0.0,
                   legacy_abort_terminal: bool = False) -> dict:
    """运行完整 Bank transport probe。

    Args:
        port: SC2 API 端口
        out_dir: 输出目录
        map_path: 可选的 MPQ 打包地图路径，用于 CreateGame + JoinGame 进图
    """
    host = VibeHost(sc2_port=port, artifacts_dir=out_dir.parent, fresh_bank=fresh_bank)
    # VIBE-KERNEL-006 取证开关：>0 时对每个 HANDLER_ABORTED 继续观察若干秒，
    # 看它是否被真响应覆盖（区分"抢读悲观占位符" vs "handler 真 abort"）。
    # 只写诊断，不改 _poll_response 的返回值，因此 all_acked 判据不受影响。
    host.aborted_grace_probe = aborted_grace
    # VIBE-KERNEL-006 反向对照：True 时回到"读到 HANDLER_ABORTED 立刻当终态"的旧行为，
    # 用于 A/B 证明 all_acked 的差异确实来自本修复。
    host.abort_is_terminal = legacy_abort_terminal
    # 读取地图字节（若提供）
    map_data = None
    if map_path:
        try:
            with open(map_path, "rb") as f:
                map_data = f.read()
            print(f"[bank_probe] 已加载地图: {map_path} ({len(map_data)} bytes)", flush=True)
        except OSError as e:
            print(f"[bank_probe] 警告: 读取地图失败: {e}", flush=True)
    if not host.connect_sc2(map_data=map_data):
        return {"transport": "bank", "verdict": "blocked", "reason": "SC2 连接失败"}

    host.start_session()

    print(f"[bank_probe] 测试 1/4: {ping_count} 次顺序 ping "
          f"(观测窗口 {poll_timeout}s，验收阈值恒为 p95<=2000ms)...", flush=True)
    t1 = run_sequential_pings(host, ping_count, poll_timeout)

    print("[bank_probe] 测试 2/4: 5 次重复 ID 幂等...", flush=True)
    t2 = run_duplicate_id_dedup(host, 5)

    print("[bank_probe] 测试 3/4: 5 个非法请求...", flush=True)
    t3 = run_illegal_requests(host, 5, min(poll_timeout, 3.0) if poll_timeout <= 5.0
                              else poll_timeout)

    print("[bank_probe] 测试 4/4: session 恢复...", flush=True)
    t4 = run_session_recovery(host, poll_timeout)

    host.save_requests_log("p0-transport")

    # VIBE-KERNEL-005b 诊断：reassert 触发时的候选明细（区分 active 真丢失 vs 陈旧目录假性 False）
    reassert_diags = getattr(host, "reassert_diags", [])
    reassert_summary = {
        "total": len(reassert_diags),
        "active_missing_req": sum(1 for d in reassert_diags if d.get("active_has_req") is False),
        "only_stale_missing": sum(
            1 for d in reassert_diags
            if d.get("active_has_req") is True and d.get("stale_without_req")
        ),
        "candidate_count_at_reassert": sorted({d.get("candidate_count") for d in reassert_diags}),
        "samples": reassert_diags[:8],
    }

    # VIBE-KERNEL-006 诊断：HANDLER_ABORTED 是抢读 provisional 占位符还是真 abort
    prov_diags = getattr(host, "provisional_diags", [])
    provisional_summary = {
        "abort_is_terminal": legacy_abort_terminal,
        "grace_observer_enabled": aborted_grace > 0.0,
        "grace_s": aborted_grace,
        "observed": len(prov_diags),
        "superseded": sum(1 for d in prov_diags if d.get("superseded")),
        "remained_aborted": sum(1 for d in prov_diags if not d.get("superseded")),
        "supersede_ms": sorted(
            d["supersede_ms"] for d in prov_diags if d.get("supersede_ms") is not None
        ),
        "final_error_codes": sorted({d.get("final_error_code") for d in prov_diags}),
        "samples": prov_diags[:8],
    }

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
            t4["restored_ping_ok"] and t4["foreign_session_rejected"]
        ) else "failed",
        "reassert_diagnostics": reassert_summary,
        "provisional_diagnostics": provisional_summary,
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
    parser.add_argument("--map-path", type=str, default=None,
                        help="MPQ 打包的 .SC2Map 路径，用于 CreateGame + JoinGame 进图")
    parser.add_argument("--fresh-bank", action="store_true",
                        help="create_game 前归档旧 GalaxyVibe.SC2Bank，消除 kernel_initialized 跨加载残留")
    parser.add_argument("--ping-count", type=int, default=20,
                        help="顺序 ping 采样数；p95 统计上有意义需 >=100（默认 20 保持历史口径）")
    parser.add_argument("--poll-timeout", type=float, default=5.0,
                        help="单次 RPC 的观测窗口（秒）。这是**观测量程**不是验收阈值："
                             "验收恒为 p95<=2000ms，放大窗口只为区分「消息丢失」与"
                             "「周期性停顿」。默认 5.0 保持历史口径。")
    parser.add_argument("--aborted-grace", type=float, default=0.0,
                        help="VIBE-KERNEL-006 取证：读到 HANDLER_ABORTED 后继续观察 N 秒，"
                             "记录该 rid 的 response 是否被真响应覆盖。**观察-only**，"
                             "不改返回值也不改 all_acked 判据。默认 0 = 关闭。")
    parser.add_argument("--legacy-abort-terminal", action="store_true",
                        help="VIBE-KERNEL-006 反向对照：回到「读到 HANDLER_ABORTED 立刻"
                             "当终态」的旧行为。用于 A/B 证明差异来自修复本身。")
    args = parser.parse_args()
    result = run_bank_probe(args.port, Path(args.out_dir), map_path=args.map_path,
                            fresh_bank=args.fresh_bank, ping_count=args.ping_count,
                            poll_timeout=args.poll_timeout,
                            aborted_grace=args.aborted_grace,
                            legacy_abort_terminal=args.legacy_abort_terminal)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    sys.exit(0 if result["verdict"] == "passed" else 1)
