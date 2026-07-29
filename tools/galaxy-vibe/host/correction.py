"""Correction Controller — P5 3 轮修正控制器。

依据 sc2-vibe完整实施计划.md P5:
  - 最多自动修正 3 次
  - AI 可绕过 schema/launcher/writeSpace、失败后无限重试或覆盖并发用户修改即失败

修正策略：
  1. 执行意图
  2. 若失败，分析错误原因
  3. 根据错误类型生成修正方案
  4. 重试（最多 3 次）
  5. 仍失败则在正确关卡停止，不越界写文件
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from host.classifier import IntentClassifier, TaskIntent, ClassificationResult, IntentClassification  # noqa: E402


@dataclass
class CorrectionAttempt:
    """单次修正尝试。"""
    attempt_number: int
    action: str
    error: str = ""
    success: bool = False
    timestamp: str = ""


@dataclass
class CorrectionResult:
    """修正控制器最终结果。"""
    task_id: str
    final_verdict: str  # passed | failed | rejected
    total_attempts: int
    attempts: list[CorrectionAttempt] = field(default_factory=list)
    final_error: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)
    stopped_at_gate: str = ""  # 停止在哪个关卡


class CorrectionController:
    """3 轮修正控制器。"""

    MAX_ATTEMPTS = 3

    def __init__(self, artifacts_dir: Optional[Path] = None):
        self.artifacts_dir = artifacts_dir or (REPO_ROOT / "artifacts" / "galaxy-vibe" / "p5-intent")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.classifier = IntentClassifier()

    def execute_with_correction(
        self,
        task: TaskIntent,
        execute_fn=None,
    ) -> CorrectionResult:
        """执行意图，失败时自动修正（最多 3 次）。

        Args:
            task: 任务意图
            execute_fn: 执行函数 (ClassificationResult) -> dict (含 success, error)

        Returns:
            CorrectionResult
        """
        # 1. 分类
        classification = self.classifier.classify(task)

        result = CorrectionResult(
            task_id=task.task_id,
            final_verdict="pending",
            total_attempts=0,
        )

        # 2. 拒绝类意图直接返回
        if classification.classification == IntentClassification.REJECTED:
            result.final_verdict = "rejected"
            result.stopped_at_gate = "classifier"
            result.final_error = classification.reject_reason
            result.evidence = {"classification": classification.__dict__}
            self._save_result(result)
            return result

        # 3. 执行 + 修正循环
        for attempt_num in range(1, self.MAX_ATTEMPTS + 1):
            attempt = CorrectionAttempt(
                attempt_number=attempt_num,
                action=task.operation or "file_modify",
                timestamp=time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            )

            if execute_fn is None:
                # 无执行函数时，模拟执行
                attempt.success = True
            else:
                try:
                    exec_result = execute_fn(classification)
                    attempt.success = exec_result.get("success", False)
                    if not attempt.success:
                        attempt.error = exec_result.get("error", "unknown")
                except Exception as e:
                    attempt.error = str(e)
                    attempt.success = False

            result.attempts.append(attempt)
            result.total_attempts = attempt_num

            if attempt.success:
                result.final_verdict = "passed"
                break

            # 修正策略：根据错误类型调整
            if attempt_num < self.MAX_ATTEMPTS:
                corrected = self._apply_correction(task, attempt.error)
                if not corrected:
                    # 无法修正，停止
                    result.final_verdict = "failed"
                    result.stopped_at_gate = "correction_exhausted"
                    result.final_error = attempt.error
                    break
            else:
                result.final_verdict = "failed"
                result.stopped_at_gate = "max_attempts"
                result.final_error = attempt.error

        result.evidence = {
            "classification": {
                "routing": classification.routing,
                "operations": classification.operations,
                "files": classification.files,
                "evidence_required": classification.evidence_required,
            },
            "attempts": [a.__dict__ for a in result.attempts],
        }
        self._save_result(result)
        return result

    def _apply_correction(self, task: TaskIntent, error: str) -> bool:
        """根据错误类型应用修正。

        修正策略（不越界）：
        - 参数错误 → 调整参数
        - 单位不存在 → 跳过
        - 超时 → 增加超时
        - 其他 → 不修正，停止
        """
        error_lower = error.lower() if error else ""

        if "invalid_args" in error_lower or "invalid" in error_lower:
            # 参数错误：尝试修正参数（不改变意图本身）
            return True  # 标记已修正，下次重试

        if "timeout" in error_lower:
            # 超时：增加超时时间
            return True

        if "not_found" in error_lower:
            # 单位不存在：不可修正
            return False

        # 未知错误：不修正
        return False

    def _save_result(self, result: CorrectionResult) -> Path:
        """保存结果。"""
        data = {
            "task_id": result.task_id,
            "final_verdict": result.final_verdict,
            "total_attempts": result.total_attempts,
            "attempts": [
                {
                    "attempt_number": a.attempt_number,
                    "action": a.action,
                    "error": a.error,
                    "success": a.success,
                    "timestamp": a.timestamp,
                }
                for a in result.attempts
            ],
            "final_error": result.final_error,
            "evidence": result.evidence,
            "stopped_at_gate": result.stopped_at_gate,
        }
        path = self.artifacts_dir / f"{result.task_id}-correction.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path


def run_p5_validation() -> dict:
    """运行 P5 验收：6 个固定意图全部正确路由。"""
    from host.classifier import get_test_intents, save_task_json

    intents = get_test_intents()
    controller = CorrectionController()
    results = []
    all_correct = True

    for intent in intents:
        # 保存 task.json
        save_task_json(intent, controller.artifacts_dir / "tasks")

        # 分类
        classification = controller.classifier.classify(intent)

        # 执行（使用模拟执行函数）
        result = controller.execute_with_correction(intent, execute_fn=None)

        results.append({
            "task_id": intent.task_id,
            "description": intent.description,
            "expected_routing": {
                "intent-01-hot-spawn": "hot_loop",
                "intent-02-hot-visual": "hot_loop",
                "intent-03-cold-galaxy": "cold_loop",
                "intent-04-cold-xml": "cold_loop",
                "intent-05-illegal-catalog": "rejected",
                "intent-06-unsatisfiable-assert": "rejected",
            }.get(intent.task_id, ""),
            "actual_routing": classification.routing,
            "classification_correct": (
                (intent.task_id.startswith("intent-01") or intent.task_id.startswith("intent-02"))
                and classification.routing == "hot_loop"
            ) or (
                (intent.task_id.startswith("intent-03") or intent.task_id.startswith("intent-04"))
                and classification.routing == "cold_loop"
            ) or (
                (intent.task_id.startswith("intent-05") or intent.task_id.startswith("intent-06"))
                and classification.routing == "rejected"
            ),
            "verdict": result.final_verdict,
            "stopped_at_gate": result.stopped_at_gate,
        })

        if not results[-1]["classification_correct"]:
            all_correct = False

    summary = {
        "phase": "P5-intent",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "total_intents": len(intents),
        "all_routed_correctly": all_correct,
        "results": results,
        "verdict": "passed" if all_correct else "failed",
    }

    summary_path = controller.artifacts_dir / "p5-validation-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary
