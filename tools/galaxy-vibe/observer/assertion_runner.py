"""Assertion Runner — P2 断言运行器。

依据 sc2-vibe完整实施计划.md P2 验收：
  - exists/count/equals/range/eventually/not_exists 正负样例全部给出预期 verdict
  - 重跑同 recipe 的关键状态一致
  - 每条断言可追到 request 和采样时间

支持的断言类型：
  - assert.exists       单位/建筑存在
  - assert.count        单位数量等于
  - assert.equals       状态字段等于
  - assert.range        状态字段在范围内
  - assert.eventually   最终成立（带超时重试）
  - assert.not_exists   单位/建筑不存在

每个断言关联一个 snapshot_id 和 request_id，确保可追溯。
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from host.vibe_host import VibeHost  # noqa: E402
from observer.state_observer import StateObserver, Snapshot  # noqa: E402


class AssertionVerdict(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class AssertionResult:
    """断言结果。"""
    assertion_id: str
    kind: str  # exists | count | equals | range | eventually | not_exists
    verdict: AssertionVerdict
    expected: Any
    actual: Any
    snapshot_id: str
    request_id: str
    sampled_at: str
    detail: str = ""
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "assertion_id": self.assertion_id,
            "kind": self.kind,
            "verdict": self.verdict.value,
            "expected": self.expected,
            "actual": self.actual,
            "snapshot_id": self.snapshot_id,
            "request_id": self.request_id,
            "sampled_at": self.sampled_at,
            "detail": self.detail,
            "duration_ms": self.duration_ms,
        }


class AssertionRunner:
    """断言运行器：执行 recipe 中的断言序列。"""

    def __init__(self, host: VibeHost, observer: Optional[StateObserver] = None):
        self.host = host
        self.observer = observer or StateObserver(host)
        self.results: list[AssertionResult] = []

    def run_assertion(self, assertion: dict[str, Any]) -> AssertionResult:
        """执行单条断言。

        断言格式：
          {"kind": "exists", "unit_type": "Marine", "player": 1}
          {"kind": "count", "unit_type": "Marine", "player": 1, "expected": 3}
          {"kind": "equals", "path": "players.0.minerals", "value": 1000}
          {"kind": "range", "path": "players.0.minerals", "min": 500, "max": 2000}
          {"kind": "eventually", "inner": {...}, "timeout": 10}
          {"kind": "not_exists", "unit_type": "Marine", "player": 1}
        """
        kind = assertion.get("kind", "")
        assertion_id = assertion.get("id", f"assert-{len(self.results)}")
        request_id = assertion.get("request_id", "")

        t0 = time.time()
        snapshot = self.observer.capture_for_request(request_id)
        duration_ms = (time.time() - t0) * 1000

        if kind == "exists":
            return self._assert_exists(assertion, assertion_id, snapshot, duration_ms)
        elif kind == "not_exists":
            return self._assert_not_exists(assertion, assertion_id, snapshot, duration_ms)
        elif kind == "count":
            return self._assert_count(assertion, assertion_id, snapshot, duration_ms)
        elif kind == "equals":
            return self._assert_equals(assertion, assertion_id, snapshot, duration_ms)
        elif kind == "range":
            return self._assert_range(assertion, assertion_id, snapshot, duration_ms)
        elif kind == "eventually":
            return self._assert_eventually(assertion, assertion_id, request_id)
        else:
            return AssertionResult(
                assertion_id=assertion_id, kind=kind,
                verdict=AssertionVerdict.ERROR,
                expected=None, actual=None,
                snapshot_id=snapshot.snapshot_id,
                request_id=request_id,
                sampled_at=snapshot.sampled_at,
                detail=f"未知断言类型: {kind}",
                duration_ms=duration_ms,
            )

    def _assert_exists(self, a: dict, aid: str, snap: Snapshot, dur: float) -> AssertionResult:
        unit_type = a.get("unit_type", "")
        player = a.get("player", 1)
        count = self.observer.get_unit_count(snap, player, unit_type)
        verdict = AssertionVerdict.PASSED if count > 0 else AssertionVerdict.FAILED
        return AssertionResult(
            assertion_id=aid, kind="exists",
            verdict=verdict, expected=">0", actual=count,
            snapshot_id=snap.snapshot_id,
            request_id=a.get("request_id", ""),
            sampled_at=snap.sampled_at,
            detail=f"player={player} unit_type={unit_type} count={count}",
            duration_ms=dur,
        )

    def _assert_not_exists(self, a: dict, aid: str, snap: Snapshot, dur: float) -> AssertionResult:
        unit_type = a.get("unit_type", "")
        player = a.get("player", 1)
        count = self.observer.get_unit_count(snap, player, unit_type)
        verdict = AssertionVerdict.PASSED if count == 0 else AssertionVerdict.FAILED
        return AssertionResult(
            assertion_id=aid, kind="not_exists",
            verdict=verdict, expected=0, actual=count,
            snapshot_id=snap.snapshot_id,
            request_id=a.get("request_id", ""),
            sampled_at=snap.sampled_at,
            detail=f"player={player} unit_type={unit_type} count={count}",
            duration_ms=dur,
        )

    def _assert_count(self, a: dict, aid: str, snap: Snapshot, dur: float) -> AssertionResult:
        unit_type = a.get("unit_type", "")
        player = a.get("player", 1)
        expected = a.get("expected", 0)
        count = self.observer.get_unit_count(snap, player, unit_type)
        verdict = AssertionVerdict.PASSED if count == expected else AssertionVerdict.FAILED
        return AssertionResult(
            assertion_id=aid, kind="count",
            verdict=verdict, expected=expected, actual=count,
            snapshot_id=snap.snapshot_id,
            request_id=a.get("request_id", ""),
            sampled_at=snap.sampled_at,
            detail=f"player={player} unit_type={unit_type} expected={expected} actual={count}",
            duration_ms=dur,
        )

    def _assert_equals(self, a: dict, aid: str, snap: Snapshot, dur: float) -> AssertionResult:
        path = a.get("path", "")
        expected = a.get("value")
        actual = self.observer.get_field(snap, path)
        verdict = AssertionVerdict.PASSED if actual == expected else AssertionVerdict.FAILED
        return AssertionResult(
            assertion_id=aid, kind="equals",
            verdict=verdict, expected=expected, actual=actual,
            snapshot_id=snap.snapshot_id,
            request_id=a.get("request_id", ""),
            sampled_at=snap.sampled_at,
            detail=f"path={path}",
            duration_ms=dur,
        )

    def _assert_range(self, a: dict, aid: str, snap: Snapshot, dur: float) -> AssertionResult:
        path = a.get("path", "")
        min_val = a.get("min", float("-inf"))
        max_val = a.get("max", float("inf"))
        actual = self.observer.get_field(snap, path)
        if actual is None:
            verdict = AssertionVerdict.FAILED
        else:
            try:
                actual_num = float(actual)
                verdict = AssertionVerdict.PASSED if min_val <= actual_num <= max_val else AssertionVerdict.FAILED
            except (TypeError, ValueError):
                verdict = AssertionVerdict.FAILED
        return AssertionResult(
            assertion_id=aid, kind="range",
            verdict=verdict, expected=[min_val, max_val], actual=actual,
            snapshot_id=snap.snapshot_id,
            request_id=a.get("request_id", ""),
            sampled_at=snap.sampled_at,
            detail=f"path={path} min={min_val} max={max_val}",
            duration_ms=dur,
        )

    def _assert_eventually(self, a: dict, aid: str, request_id: str) -> AssertionResult:
        """eventually 断言：带超时重试内部断言。"""
        inner = a.get("inner", {})
        timeout = a.get("timeout", 10.0)
        deadline = time.time() + timeout
        t0 = time.time()

        last_result: Optional[AssertionResult] = None
        while time.time() < deadline:
            last_result = self.run_assertion(inner)
            if last_result.verdict == AssertionVerdict.PASSED:
                return AssertionResult(
                    assertion_id=aid, kind="eventually",
                    verdict=AssertionVerdict.PASSED,
                    expected="passed within timeout",
                    actual="passed",
                    snapshot_id=last_result.snapshot_id,
                    request_id=request_id,
                    sampled_at=last_result.sampled_at,
                    detail=f"passed in {time.time()-t0:.2f}s",
                    duration_ms=(time.time() - t0) * 1000,
                )
            time.sleep(0.5)  # 500ms 重试间隔

        return AssertionResult(
            assertion_id=aid, kind="eventually",
            verdict=AssertionVerdict.TIMEOUT,
            expected="passed within timeout",
            actual="timed out",
            snapshot_id=last_result.snapshot_id if last_result else "",
            request_id=request_id,
            sampled_at=last_result.sampled_at if last_result else "",
            detail=f"timeout after {timeout}s",
            duration_ms=(time.time() - t0) * 1000,
        )

    def run_recipe(self, recipe: dict[str, Any]) -> dict[str, Any]:
        """运行完整 recipe（断言序列）。

        Recipe 格式：
          {
            "recipe_id": "...",
            "steps": [
              {"action": "spawn", "unit_type": "Marine", "count": 3, "player": 1},
              {"action": "assert", "kind": "count", "unit_type": "Marine", "player": 1, "expected": 3},
              ...
            ]
          }
        """
        recipe_id = recipe.get("recipe_id", "default")
        steps = recipe.get("steps", [])
        results = []
        passed = 0
        failed = 0

        for i, step in enumerate(steps):
            action = step.get("action", "")
            if action == "assert":
                result = self.run_assertion(step)
                results.append(result.to_dict())
                if result.verdict == AssertionVerdict.PASSED:
                    passed += 1
                else:
                    failed += 1
            elif action == "spawn":
                resp = self.host.spawn_units(
                    step.get("unit_type", "Marine"),
                    step.get("count", 1),
                    step.get("player", 1),
                )
                results.append({
                    "step": i,
                    "action": "spawn",
                    "request_id": resp.request_id,
                    "error_code": resp.error_code,
                    "is_ok": resp.is_ok,
                })
            elif action == "kill":
                resp = self.host.kill_units(
                    step.get("player", 1),
                    step.get("unit_type", ""),
                    step.get("all", False),
                )
                results.append({
                    "step": i,
                    "action": "kill",
                    "request_id": resp.request_id,
                    "error_code": resp.error_code,
                    "is_ok": resp.is_ok,
                })
            elif action == "set_resource":
                resp = self.host.set_resource(
                    step.get("player", 1),
                    step.get("resource", "minerals"),
                    step.get("value", 0),
                )
                results.append({
                    "step": i,
                    "action": "set_resource",
                    "request_id": resp.request_id,
                    "error_code": resp.error_code,
                    "is_ok": resp.is_ok,
                })
            elif action == "reset":
                resp = self.host.reset_scenario()
                results.append({
                    "step": i,
                    "action": "reset",
                    "request_id": resp.request_id,
                    "error_code": resp.error_code,
                    "is_ok": resp.is_ok,
                })

        verdict = "passed" if failed == 0 and passed > 0 else "failed" if failed > 0 else "empty"
        return {
            "recipe_id": recipe_id,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            "total_steps": len(steps),
            "assertions_passed": passed,
            "assertions_failed": failed,
            "verdict": verdict,
            "results": results,
        }
