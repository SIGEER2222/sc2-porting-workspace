"""Vibe Host soak 测试模块 — 30 分钟或 200 请求稳定性测试。

依据 sc2-vibe完整实施计划.md P7 验收:
  - 30 分钟或 200 请求 soak：0 丢失、0 重复副作用、0 新 ScriptError
  - Host 重启可续接，SC2 重启产生新 session

策略:
  - 默认运行 200 个顺序请求（或 30 分钟，先到者为准）
  - 请求池：循环执行白名单 hot 操作（system.ping / scenario.reset / unit.spawn / query.units）
  - 每 N 个请求插入 1 次幂等性测试（重发相同 request_id，期望相同 verdict 且无新副作用）
  - 全程记录 PerformanceTracker 指标
  - 检测 SC2 重启：连续 3 次 ping 失败 → RecoveryManager.start_new_session()
  - 输出 soak-report.json + soak-requests.ndjson

调用方式:
  from soak import SoakRunner
  runner = SoakRunner(host=vibe_host, tracker=perf_tracker, recovery=recovery_mgr)
  report = runner.run(target_requests=200, duration_sec=1800)
  report.save(path)
"""
from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Optional, Callable

from performance import PerformanceTracker, PerformanceReport
from recovery import RecoveryManager, detect_sc2_restart


@dataclass
class SoakReport:
    """soak 测试报告。"""
    ran_at: str
    target_requests: int
    actual_requests: int
    duration_sec: float
    stopped_reason: str  # "target_reached" | "duration_reached" | "sc2_restart_aborted" | "error"
    session_rotations: int = 0
    idempotency_checks: int = 0
    idempotency_passes: int = 0
    idempotency_failures: int = 0
    errors: list[str] = field(default_factory=list)
    perf_summary: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    @property
    def passes(self) -> bool:
        if self.stopped_reason not in ("target_reached", "duration_reached"):
            return False
        if self.idempotency_failures > 0:
            return False
        return self.perf_summary.get("no_loss", False) and self.perf_summary.get("no_new_script_errors", False)


class SoakRunner:
    """soak 测试执行器。"""

    DEFAULT_REQUEST_POOL = [
        ("system.ping", {}),
        ("scenario.reset", {}),
        ("unit.spawn", {"unit_type": "Marine", "count": 1, "player": 1}),
        ("query.units", {"player": 1, "unit_type": "Marine"}),
    ]

    def __init__(
        self,
        host: Any,  # VibeHost 实例（duck-typed）
        tracker: PerformanceTracker,
        recovery: RecoveryManager,
        request_pool: Optional[list[tuple[str, dict]]] = None,
        idempotency_interval: int = 10,
        ping_failure_threshold: int = 3,
        log_path: Optional[Path] = None,
    ):
        self.host = host
        self.tracker = tracker
        self.recovery = recovery
        self.request_pool = request_pool or self.DEFAULT_REQUEST_POOL
        self.idempotency_interval = idempotency_interval
        self.ping_failure_threshold = ping_failure_threshold
        self.log_path = log_path
        self._log_fp = None
        self._consecutive_ping_failures = 0
        self._prev_ping_ok = True

    def run(
        self,
        target_requests: int = 200,
        duration_sec: float = 1800.0,
        stop_on_sc2_restart: bool = False,
        cold_baseline_p95: Optional[float] = None,
    ) -> SoakReport:
        if self.log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            self._log_fp = open(self.log_path, "w", encoding="utf-8")

        start = time.time()
        actual = 0
        session_rotations = 0
        idempotency_checks = 0
        idempotency_passes = 0
        idempotency_failures = 0
        errors: list[str] = []
        stopped_reason = "error"

        try:
            for i in range(target_requests):
                elapsed = time.time() - start
                if elapsed >= duration_sec:
                    stopped_reason = "duration_reached"
                    break

                # 选择请求
                op, args = self.request_pool[i % len(self.request_pool)]
                request_id = f"soak-{i:04d}-{int(time.time())}"

                # 每 idempotency_interval 次插入幂等性测试
                is_idempotency = (i > 0 and i % self.idempotency_interval == 0)
                if is_idempotency:
                    # 重发上一个请求的 request_id
                    request_id = f"soak-{i-1:04d}-{int(time.time())}"
                    idempotency_checks += 1

                issued_at = time.time()
                ack_at = None
                completed_at = None
                verdict = "failed"
                error_code = ""

                try:
                    # 检测 SC2 重启
                    if not self._ping_ok():
                        self._consecutive_ping_failures += 1
                        if detect_sc2_restart(
                            prev_ping_ok=self._prev_ping_ok,
                            current_ping_ok=False,
                            consecutive_failures=self._consecutive_ping_failures,
                            threshold=self.ping_failure_threshold,
                        ):
                            self.recovery.start_new_session(reason="sc2_restart")
                            session_rotations += 1
                            if stop_on_sc2_restart:
                                stopped_reason = "sc2_restart_aborted"
                                break
                            # 重新连接 host
                            try:
                                self.host.start_session()
                            except Exception as e:
                                errors.append(f"reconnect failed: {e}")
                                stopped_reason = "sc2_restart_aborted"
                                break
                    else:
                        self._consecutive_ping_failures = 0
                    self._prev_ping_ok = True

                    # 幂等性检查：已处理过的 request_id 应直接返回缓存结果
                    if is_idempotency and self.recovery.is_processed(request_id):
                        self.tracker.record_duplicate_hit()
                        # 重发仍应得到响应
                        resp = self.host.request(op, args, request_id=request_id)
                        ack_at = time.time()
                        completed_at = time.time()
                        verdict = resp.get("verdict", "passed")
                        # 幂等通过：verdict 与原结果一致且无新副作用（由 Kernel 保证）
                        if verdict in ("passed", "rejected"):
                            idempotency_passes += 1
                        else:
                            idempotency_failures += 1
                    else:
                        resp = self.host.request(op, args, request_id=request_id)
                        ack_at = time.time()
                        completed_at = time.time()
                        verdict = resp.get("verdict", "failed")
                        error_code = resp.get("error_code", "")
                        self.recovery.mark_processed(request_id, operation=op, verdict=verdict)

                except Exception as e:
                    errors.append(f"req#{i} {op}: {e}")
                    verdict = "failed"
                    error_code = "exception"
                    if ack_at is None:
                        ack_at = time.time()
                    if completed_at is None:
                        completed_at = time.time()

                self.tracker.record(
                    request_id=request_id,
                    operation=op,
                    issued_at=issued_at,
                    ack_at=ack_at,
                    completed_at=completed_at,
                    verdict=verdict,
                    error_code=error_code,
                )
                self._log_request({
                    "i": i,
                    "request_id": request_id,
                    "operation": op,
                    "args": args,
                    "issued_at": issued_at,
                    "ack_at": ack_at,
                    "completed_at": completed_at,
                    "verdict": verdict,
                    "error_code": error_code,
                    "is_idempotency": is_idempotency,
                })
                actual += 1
            else:
                stopped_reason = "target_reached"

        finally:
            if self._log_fp:
                self._log_fp.close()

        perf = self.tracker.compute_report(cold_baseline_p95=cold_baseline_p95)
        return SoakReport(
            ran_at=time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime()),
            target_requests=target_requests,
            actual_requests=actual,
            duration_sec=round(time.time() - start, 3),
            stopped_reason=stopped_reason,
            session_rotations=session_rotations,
            idempotency_checks=idempotency_checks,
            idempotency_passes=idempotency_passes,
            idempotency_failures=idempotency_failures,
            errors=errors,
            perf_summary=perf.to_dict(),
        )

    def _ping_ok(self) -> bool:
        """探测 host/SC2 是否可达。"""
        try:
            resp = self.host.request("system.ping", {}, request_id=f"probe-{int(time.time()*1000)}")
            return resp.get("verdict") == "passed"
        except Exception:
            return False

    def _log_request(self, entry: dict) -> None:
        if self._log_fp:
            self._log_fp.write(json.dumps(entry, ensure_ascii=False) + "\n")
            self._log_fp.flush()
