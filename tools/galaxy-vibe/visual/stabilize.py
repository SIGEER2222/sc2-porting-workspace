"""Stabilize — P3 稳定帧检测。

依据计划"固定分辨率、镜头、种子和稳定帧"要求：
  - 连续截图直到帧稳定（差异小于阈值）
  - 避免捕获过渡动画帧
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

from visual.capture import VisualCapture  # noqa: E402
from visual.roi_evaluator import ROIEvaluator  # noqa: E402


class FrameStabilizer:
    """稳定帧检测器：连续截图直到帧稳定。"""

    def __init__(self, capture: VisualCapture, evaluator: ROIEvaluator):
        self.capture = capture
        self.evaluator = evaluator

    def wait_for_stable(
        self,
        max_attempts: int = 10,
        interval: float = 0.3,
        stability_threshold: float = 0.005,
    ) -> Optional[Path]:
        """连续截图直到帧稳定。

        Args:
            max_attempts: 最大尝试次数
            interval: 截图间隔（秒）
            stability_threshold: 稳定阈值（变化像素比例 < 此值视为稳定）

        Returns:
            稳定帧的路径，或 None（失败时）
        """
        prev_path: Optional[Path] = None
        for i in range(max_attempts):
            result = self.capture.capture_window(f"stabilize-{i}")
            if result is None:
                time.sleep(interval)
                continue
            curr_path = result.image_path
            if prev_path is not None:
                diff = self.evaluator.compute_pixel_diff(prev_path, curr_path)
                if diff.changed_pixel_ratio < stability_threshold:
                    return curr_path
            prev_path = curr_path
            time.sleep(interval)
        return prev_path

    def capture_stable_pair(
        self,
        action_fn,
        request_id: str = "",
        snapshot_id: str = "",
    ) -> tuple[Optional[Path], Optional[Path]]:
        """采集稳定的 before/after 截图对。

        1. 等待 before 帧稳定
        2. 执行 action
        3. 等待 after 帧稳定
        """
        before_stable = self.wait_for_stable()
        before_result = self.capture.capture_window("before", request_id, snapshot_id)
        before_path = before_result.image_path if before_result else before_stable

        action_fn()

        time.sleep(0.5)  # 等待动画播放
        after_stable = self.wait_for_stable()
        after_result = self.capture.capture_window("after", request_id, snapshot_id)
        after_path = after_result.image_path if after_result else after_stable

        return before_path, after_path
