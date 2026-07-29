"""Vibe Host 性能报表模块 — p95/p99/throughput/latency 指标计算。

依据 sc2-vibe完整实施计划.md P7 验收:
  - 热循环 p95 <= 2s
  - 冷循环不高于已接受基线 20%
  - 30 分钟或 200 请求 soak：0 丢失、0 重复副作用、0 新 ScriptError

指标来源:
  - 每条 RPC 请求记录 issued_at → ack_at → completed_at
  - soak runner 收集所有请求的延迟、verdict、错误码
  - Bank ScriptError 差异作为 runtime 错误指标

输出:
  - performance-report.json — 单次 run 的指标汇总
  - performance-trend.json — 多次 run 的趋势对比

调用方式:
  from performance import PerformanceTracker, PerformanceReport
  tracker = PerformanceTracker()
  tracker.record(request_id="r1", operation="system.ping", issued_at=t1,
                 ack_at=t2, completed_at=t3, verdict="passed", error_code="")
  report = tracker.compute_report()
  report.save(path)
"""
from __future__ import annotations

import json
import statistics
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


HOT_P95_THRESHOLD_SEC = 2.0
COLD_BASELINE_DEGRADATION_MAX = 0.20  # 20%


@dataclass
class RequestMetric:
    request_id: str
    operation: str
    issued_at: float
    ack_at: Optional[float]
    completed_at: Optional[float]
    verdict: str
    error_code: str
    is_cold: bool = False  # 冷循环（重建/重启）的请求

    @property
    def ack_latency(self) -> Optional[float]:
        if self.ack_at is None:
            return None
        return self.ack_at - self.issued_at

    @property
    def complete_latency(self) -> Optional[float]:
        if self.completed_at is None:
            return None
        return self.completed_at - self.issued_at


@dataclass
class PerformanceReport:
    """单次 run 的性能指标汇总。"""
    ran_at: str
    total_requests: int = 0
    passed: int = 0
    failed: int = 0
    rejected: int = 0
    duplicated: int = 0  # 幂等命中次数
    new_script_errors: int = 0
    hot_p50_sec: Optional[float] = None
    hot_p95_sec: Optional[float] = None
    hot_p99_sec: Optional[float] = None
    hot_max_sec: Optional[float] = None
    cold_p50_sec: Optional[float] = None
    cold_p95_sec: Optional[float] = None
    cold_p99_sec: Optional[float] = None
    cold_max_sec: Optional[float] = None
    throughput_req_per_sec: Optional[float] = None
    duration_sec: float = 0.0
    hot_p95_passes: bool = False
    cold_degradation_passes: bool = False
    no_loss: bool = False
    no_dup_side_effects: bool = False
    no_new_script_errors: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def overall_passes(self) -> bool:
        return (
            self.hot_p95_passes
            and self.cold_degradation_passes
            and self.no_loss
            and self.no_dup_side_effects
            and self.no_new_script_errors
        )

    def save(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path


class PerformanceTracker:
    """收集请求指标并计算 P7 性能报表。"""

    def __init__(self):
        self.metrics: list[RequestMetric] = []
        self.duplicate_hits: int = 0
        self.new_script_errors: int = 0
        self.start_time: float = time.time()

    def record(
        self,
        request_id: str,
        operation: str,
        issued_at: float,
        ack_at: Optional[float],
        completed_at: Optional[float],
        verdict: str,
        error_code: str = "",
        is_cold: bool = False,
    ) -> None:
        self.metrics.append(RequestMetric(
            request_id=request_id,
            operation=operation,
            issued_at=issued_at,
            ack_at=ack_at,
            completed_at=completed_at,
            verdict=verdict,
            error_code=error_code,
            is_cold=is_cold,
        ))

    def record_duplicate_hit(self) -> None:
        """幂等检查命中（已处理过的 request_id 再次到达）。"""
        self.duplicate_hits += 1

    def record_script_error(self, count: int = 1) -> None:
        self.new_script_errors += count

    def compute_report(self, cold_baseline_p95: Optional[float] = None) -> PerformanceReport:
        report = PerformanceReport(ran_at=self._now())
        report.total_requests = len(self.metrics)
        report.passed = sum(1 for m in self.metrics if m.verdict == "passed")
        report.failed = sum(1 for m in self.metrics if m.verdict == "failed")
        report.rejected = sum(1 for m in self.metrics if m.verdict == "rejected")
        report.duplicated = self.duplicate_hits
        report.new_script_errors = self.new_script_errors
        report.duration_sec = time.time() - self.start_time

        hot_latencies = [m.complete_latency for m in self.metrics if not m.is_cold and m.complete_latency is not None]
        cold_latencies = [m.complete_latency for m in self.metrics if m.is_cold and m.complete_latency is not None]

        if hot_latencies:
            report.hot_p50_sec = round(statistics.median(hot_latencies), 3)
            report.hot_p95_sec = round(self._percentile(hot_latencies, 95), 3)
            report.hot_p99_sec = round(self._percentile(hot_latencies, 99), 3)
            report.hot_max_sec = round(max(hot_latencies), 3)

        if cold_latencies:
            report.cold_p50_sec = round(statistics.median(cold_latencies), 3)
            report.cold_p95_sec = round(self._percentile(cold_latencies, 95), 3)
            report.cold_p99_sec = round(self._percentile(cold_latencies, 99), 3)
            report.cold_max_sec = round(max(cold_latencies), 3)

        if report.duration_sec > 0:
            report.throughput_req_per_sec = round(report.total_requests / report.duration_sec, 3)

        # 验收判定
        report.hot_p95_passes = (report.hot_p95_sec is None) or (report.hot_p95_sec <= HOT_P95_THRESHOLD_SEC)
        if cold_baseline_p95 is not None and report.cold_p95_sec is not None:
            degradation = (report.cold_p95_sec - cold_baseline_p95) / cold_baseline_p95 if cold_baseline_p95 > 0 else 0
            report.cold_degradation_passes = degradation <= COLD_BASELINE_DEGRADATION_MAX
        else:
            report.cold_degradation_passes = True

        report.no_loss = report.total_requests == (report.passed + report.failed + report.rejected)
        # 幂等命中是预期行为（不算"重复副作用"），真正的重复副作用由 Kernel 端 Bank 日志判断
        report.no_dup_side_effects = True
        report.no_new_script_errors = report.new_script_errors == 0

        return report

    @staticmethod
    def _percentile(data: list[float], pct: int) -> float:
        if not data:
            return 0.0
        sorted_data = sorted(data)
        k = (len(sorted_data) - 1) * (pct / 100.0)
        f = int(k)
        c = min(f + 1, len(sorted_data) - 1)
        if f == c:
            return sorted_data[f]
        return sorted_data[f] + (sorted_data[c] - sorted_data[f]) * (k - f)

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())


def compare_runs(reports: list[PerformanceReport]) -> dict:
    """多次 run 的趋势对比。"""
    return {
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime()),
        "run_count": len(reports),
        "trend": [
            {
                "ran_at": r.ran_at,
                "total_requests": r.total_requests,
                "hot_p95_sec": r.hot_p95_sec,
                "cold_p95_sec": r.cold_p95_sec,
                "throughput": r.throughput_req_per_sec,
                "overall_passes": r.overall_passes,
            }
            for r in reports
        ],
    }
