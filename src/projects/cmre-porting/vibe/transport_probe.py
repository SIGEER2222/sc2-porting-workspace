#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P0 传输闸门 — transport probe + verdict（离线可验核心 + 真机 guarded 适配器）。

离线（MockTransport）即可验证协议层 P0 验收：20 次顺序 ping 全 ack、5 重复 ID 仅执行一次、
5 非法请求零副作用、p95 延迟、session 恢复拒绝旧请求。三种真机 transport
（BankReload / SC2API Chat / 输入回退）以 guarded 适配器存在，沙箱无头环境直接跳过，
待桌面 `launch-cmre-alenger.ps1` 启动 SC2 后实测选型并产出 `transport-verdict.json`。

用法：
  python transport_probe.py --selftest
  python transport_probe.py --transport mock        # 离线等效
  python transport_probe.py --transport bank        # 桌面：BankReload 通道（guarded）
  python transport_probe.py --transport sc2api      # 桌面：SC2API Chat 通道（guarded）
  python transport_probe.py --transport input       # 桌面：输入回退通道（guarded）

证据分类：本文件协议/幂等/校验逻辑属 static 验证；真机 ack/延迟/去重需 desktop runtime 证据。
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from protocol import (
    PROTOCOL_VERSION,
    ErrorCode,
    Request,
    Response,
    make_request,
    SessionRegistry,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_VERDICT = REPO_ROOT / "artifacts" / "galaxy-vibe" / "transport-verdict.json"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Transport:
    name = "abstract"

    def send(self, req: Request) -> Response:  # pragma: no cover
        raise NotImplementedError


class MockTransport(Transport):
    """离线 transport：实现 ack/result 语义并计数，用于协议层自测。"""

    name = "mock"

    def __init__(self):
        self.calls = 0

    def send(self, req: Request) -> Response:
        self.calls += 1
        started = time.time()
        kind = "ack" if req.operation == "system.ping" else "result"
        completed = time.time()
        return Response(
            kind,
            req.session_id,
            req.request_id,
            req.sequence,
            req.operation,
            started,
            completed,
            0,
            {"echo": req.operation},
            1,
        )


class _DesktopGuardedTransport(Transport):
    """真机 transport 基类：非桌面环境直接跳过，不产生副作用、不写 verdict。"""

    def _require_desktop(self):
        # 沙箱无头：SC2 起不来（Switcher 丢 -listenPort）。真机实现应在此建立到运行 SC2 的通道。
        raise RuntimeError(
            f"transport '{self.name}' 需要桌面运行中的 SC2（批准 launcher 启动）；沙箱跳过"
        )

    def send(self, req: Request) -> Response:
        self._require_desktop()


class BankReloadTransport(_DesktopGuardedTransport):
    name = "bank_reload"


class Sc2ApiChatTransport(_DesktopGuardedTransport):
    name = "sc2api_chat"


class InputFallbackTransport(_DesktopGuardedTransport):
    name = "input_fallback"


REAL_TRANSPORTS = {
    "bank": BankReloadTransport,
    "sc2api": Sc2ApiChatTransport,
    "input": InputFallbackTransport,
}


class Probe:
    def __init__(self, transport: Transport, registry: Optional[SessionRegistry] = None):
        self.transport = transport
        self.registry = registry or SessionRegistry()
        self.cache: dict[tuple, Response] = {}  # (session_id, request_id) -> Response
        self.latencies_ms: list[float] = []
        self.executed = 0
        self.dup_suppressed = 0
        self.illegal_rejected = 0
        self.transport_unavailable = False

    def submit(self, req: Request) -> tuple[Response, bool]:
        key = (req.session_id, req.request_id)
        # 1) session / 校验和 / 操作 / 序列号 校验必须先于幂等缓存：
        #    已关闭（过期）的 session 旧请求必须显式拒绝，即使该 request_id 曾执行过。
        code = self.registry.validate(req)
        if code != ErrorCode.OK:
            if code in (ErrorCode.UNKNOWN_OP, ErrorCode.OUT_OF_RANGE):
                self.illegal_rejected += 1
            resp = Response(
                "error",
                req.session_id,
                req.request_id,
                req.sequence,
                req.operation,
                0.0,
                0.0,
                int(code),
                {"reason": code.name},
                0,
            )
            # 首结果胜出：仅当该 request_id 尚无记录时才写，绝不以错误覆盖已成功的结果（幂等）
            self.cache.setdefault(key, resp)
            return resp, False
        # 2) 开放 session 内的重复 request_id：返回原结果，不重复执行（幂等）
        if key in self.cache:
            self.dup_suppressed += 1
            return self.cache[key], False
        try:
            resp = self.transport.send(req)
        except RuntimeError as e:
            # 真机 transport 在非桌面环境抛错 → 降级为不可用，不崩溃
            self.transport_unavailable = True
            resp = Response(
                "error",
                req.session_id,
                req.request_id,
                req.sequence,
                req.operation,
                0.0,
                0.0,
                int(ErrorCode.EXEC_FAILED),
                {"reason": "transport_unavailable", "detail": str(e)},
                0,
            )
            self.cache.setdefault(key, resp)
            return resp, False
        self.executed += 1
        self.latencies_ms.append((resp.completed_at - resp.started_at) * 1000.0)
        self.cache[key] = resp
        self.registry.mark(req)
        return resp, True

    def run_p0_scenario(self, session_id: str = "sess-p0") -> dict:
        self.registry.open(session_id)
        seq = 0
        # 20 次顺序 ping（唯一 request_id）
        for i in range(20):
            seq += 1
            self.submit(make_request(session_id, f"ping-{i}", seq, "system.ping"))
        # 5 次重复 ID（与 ping-0 同 request_id，新 sequence）→ 仅首次执行
        for _ in range(5):
            seq += 1
            self.submit(make_request(session_id, "ping-0", seq, "system.ping"))
        # 5 次非法操作（未知 operation）→ 零副作用
        for i in range(5):
            seq += 1
            self.submit(
                make_request(session_id, f"illegal-{i}", seq, "unit.unknown_op_xyz")
            )
        # session 恢复：关闭旧 session，旧请求应被拒绝
        self.registry.close(session_id)
        seq += 1
        old_resp, _ = self.submit(
            make_request(session_id, "ping-0", seq, "system.ping")
        )
        recovery_ok = old_resp.error_code == int(ErrorCode.STALE_SESSION)
        return self.metrics(recovery_ok)

    def metrics(self, recovery_ok: bool) -> dict:
        ack_or_result = sum(
            1 for v in self.cache.values() if v.kind in ("ack", "result")
        )
        p95 = (
            round(statistics.quantiles(self.latencies_ms, n=20)[-1], 3)
            if self.latencies_ms
            else 0.0
        )
        return {
            "transport": self.transport.name,
            "total_submitted": 20 + 5 + 5 + 1,
            "ack_or_result": ack_or_result,
            "executed": self.executed,
            "dup_suppressed": self.dup_suppressed,
            "illegal_rejected": self.illegal_rejected,
            "p95_latency_ms": p95,
            "session_recovery_ok": recovery_ok,
            "transport_unavailable": self.transport_unavailable,
        }

    def evaluate(self, m: dict) -> tuple[bool, dict]:
        checks = {
            "20_ping_ack": m["ack_or_result"] >= 20,
            "dup_once": m["executed"] == 20 and m["dup_suppressed"] >= 5,
            "illegal_zero_sideeffect": m["illegal_rejected"] == 5,
            "p95_le_2s": m["p95_latency_ms"] <= 2000.0,
            "session_recovery": m["session_recovery_ok"],
        }
        passed = all(checks.values()) and not m["transport_unavailable"]
        return passed, checks


def emit_verdict(m: dict, passed: bool, checks: dict, out: Path) -> None:
    verdict = {
        "tool": "transport_probe",
        "protocol_version": PROTOCOL_VERSION,
        "transport": m["transport"],
        "passed": passed,
        "checks": checks,
        "metrics": m,
        "checked_at": utcnow(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description="P0 传输闸门 transport probe")
    ap.add_argument("--selftest", action="store_true", help="用 MockTransport 离线验证协议层 P0 验收")
    ap.add_argument(
        "--transport",
        choices=["mock", "bank", "sc2api", "input"],
        default="mock",
        help="transport 通道（bank/sc2api/input 仅桌面可用，沙箱跳过）",
    )
    ap.add_argument("--session", default="sess-p0")
    ap.add_argument("--out", default=str(DEFAULT_VERDICT))
    a = ap.parse_args()

    if a.selftest:
        probe = Probe(MockTransport())
        m = probe.run_p0_scenario()
        passed, checks = probe.evaluate(m)
        print(json.dumps({"passed": passed, "checks": checks, "metrics": m}, indent=2, ensure_ascii=False))
        raise SystemExit(0 if passed else 1)

    transport = MockTransport() if a.transport == "mock" else REAL_TRANSPORTS[a.transport]()
    probe = Probe(transport)
    m = probe.run_p0_scenario(a.session)
    passed, checks = probe.evaluate(m)
    emit_verdict(m, passed, checks, Path(a.out))
    print(f"TRANSPORT VERDICT: {'PASS' if passed else 'FAIL'} ({a.transport}) -> {a.out}")
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
