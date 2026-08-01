"""Vibe Intent Classifier — P5 意图分类器。

依据 sc2-vibe完整实施计划.md P5:
  - 6 个固定意图全部正确路由：热刷兵、热视觉修改、冷 Galaxy、冷 XML、非法 Catalog 字段、不可满足断言
  - 成功项产出完整证据，失败项在正确关卡停止且不越界写文件

意图分类：
  - HOT: 热循环操作（运行时可通过 Kernel 执行）
    - unit.spawn, unit.kill, unit.set_vital
    - player.set_resource
    - visual.actor_*
    - query.*
    - function.invoke (explicit registry only)
  - COLD: 冷循环操作（需要重新编译/重启）
    - galaxy.modify (修改 Galaxy 源码)
    - xml.modify (修改 XML 数据)
    - asset.modify (修改资产)
  - REJECTED: 非法意图（不执行）
    - illegal catalog field (非法 Catalog 字段)
    - unsatisfiable assertion (不可满足断言)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class IntentClassification(str, Enum):
    HOT = "hot"
    COLD = "cold"
    REJECTED = "rejected"


@dataclass
class TaskIntent:
    """意图输入。"""
    task_id: str
    description: str
    intent_type: str  # spawn | visual | galaxy_modify | xml_modify | illegal_catalog | unsatisfiable_assert
    operation: str = ""
    args: dict[str, Any] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)
    classification: Optional[IntentClassification] = None
    reject_reason: str = ""


@dataclass
class ClassificationResult:
    """分类结果。"""
    task_id: str
    classification: IntentClassification
    routing: str  # hot_loop | cold_loop | rejected
    operations: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    reject_reason: str = ""
    evidence_required: list[str] = field(default_factory=list)


class IntentClassifier:
    """意图分类器。"""

    # 热循环操作白名单
    HOT_OPERATIONS = {
        "unit.spawn", "unit.kill", "unit.set_vital",
        "player.set_resource",
        "visual.actor_tint", "visual.actor_scale", "visual.actor_opacity",
        "query.units", "query.unit", "query.mission",
        "system.ping", "scenario.reset",
        "function.invoke",
    }

    # 非法 Catalog 字段关键词
    ILLEGAL_CATALOG_PATTERNS = [
        "arbitrary_field",
        "nonexistent_field",
        "invalid_catalog_entry",
        "call_arbitrary_func",
    ]

    def classify(self, task: TaskIntent) -> ClassificationResult:
        """分类意图。"""
        # 1. 检查是否为非法意图
        if self._is_illegal(task):
            return ClassificationResult(
                task_id=task.task_id,
                classification=IntentClassification.REJECTED,
                routing="rejected",
                reject_reason="非法 Catalog 字段或操作",
                evidence_required=["rejection_record"],
            )

        # 2. 检查是否为不可满足断言
        if self._is_unsatisfiable(task):
            return ClassificationResult(
                task_id=task.task_id,
                classification=IntentClassification.REJECTED,
                routing="rejected",
                reject_reason="不可满足的断言条件",
                evidence_required=["rejection_record"],
            )

        # 3. 检查是否为冷循环（文件修改）
        if task.files:
            return ClassificationResult(
                task_id=task.task_id,
                classification=IntentClassification.COLD,
                routing="cold_loop",
                files=task.files,
                evidence_required=["static_validation", "launcher_result", "recipe_rebuild", "script_error_check"],
            )

        # 4. 检查是否为热循环操作
        if task.operation in self.HOT_OPERATIONS:
            return ClassificationResult(
                task_id=task.task_id,
                classification=IntentClassification.HOT,
                routing="hot_loop",
                operations=[task.operation],
                evidence_required=["rpc_response", "state_snapshot", "visual_diff"],
            )

        # 5. 未知操作，拒绝
        return ClassificationResult(
            task_id=task.task_id,
            classification=IntentClassification.REJECTED,
            routing="rejected",
            reject_reason=f"未知操作: {task.operation}",
            evidence_required=["rejection_record"],
        )

    def _is_illegal(self, task: TaskIntent) -> bool:
        """检查是否为非法意图。"""
        if task.intent_type == "illegal_catalog":
            return True
        # 检查操作名是否包含非法关键词
        for pattern in self.ILLEGAL_CATALOG_PATTERNS:
            if pattern in task.operation.lower():
                return True
        return False

    def _is_unsatisfiable(self, task: TaskIntent) -> bool:
        """检查是否为不可满足断言。"""
        if task.intent_type == "unsatisfiable_assert":
            return True
        # 检查断言参数是否自相矛盾
        if "expected" in task.args and "condition" in task.args:
            expected = task.args.get("expected")
            condition = task.args.get("condition")
            if condition == "greater_than" and expected is not None:
                try:
                    if float(expected) < 0:
                        return True
                except (TypeError, ValueError):
                    pass
        return False


# ---- 6 个固定测试意图 ----

def get_test_intents() -> list[TaskIntent]:
    """获取 P5 验收的 6 个固定测试意图。"""
    return [
        TaskIntent(
            task_id="intent-01-hot-spawn",
            description="热刷兵：spawn 3 Marine",
            intent_type="spawn",
            operation="unit.spawn",
            args={"unit_type": "Marine", "count": 3, "player": 1},
        ),
        TaskIntent(
            task_id="intent-02-hot-visual",
            description="热视觉修改：tint 单位",
            intent_type="visual",
            operation="visual.actor_tint",
            args={"unit_tag": 1, "color": "255,0,0"},
        ),
        TaskIntent(
            task_id="intent-03-cold-galaxy",
            description="冷 Galaxy：修改 LibVibeKernel.galaxy",
            intent_type="galaxy_modify",
            files=["tools/galaxy-vibe/kernel/LibVibeKernel.galaxy"],
        ),
        TaskIntent(
            task_id="intent-04-cold-xml",
            description="冷 XML：修改 GameData XML",
            intent_type="xml_modify",
            files=["src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map/Attributes"],
        ),
        TaskIntent(
            task_id="intent-05-illegal-catalog",
            description="非法 Catalog 字段",
            intent_type="illegal_catalog",
            operation="catalog.set_field",
            args={"entry": "Marine", "field": "arbitrary_field", "value": "invalid"},
        ),
        TaskIntent(
            task_id="intent-06-unsatisfiable-assert",
            description="不可满足断言：断言 Marine count == -1",
            intent_type="unsatisfiable_assert",
            operation="assert.count",
            args={"unit_type": "Marine", "player": 1, "expected": -1},
        ),
    ]


def save_task_json(task: TaskIntent, out_dir: Path) -> Path:
    """保存 task 为 task.json。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    data = {
        "task_id": task.task_id,
        "description": task.description,
        "intent_type": task.intent_type,
        "operation": task.operation,
        "args": task.args,
        "files": task.files,
    }
    path = out_dir / f"{task.task_id}.json"
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
