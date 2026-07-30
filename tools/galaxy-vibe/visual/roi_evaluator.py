"""ROI Evaluator — P3 视觉闭环的 ROI 差异评估器。

依据 sc2-vibe完整实施计划.md P3 验收：
  - 两次同状态截图建立噪声包络
  - spawn/tint 的 ROI 差异大于 max(3x噪声p99, 1%)
  - reset 回到噪声包络内
  - 截图中的单位数与快照一致
"""
from __future__ import annotations

import json
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


@dataclass
class DiffResult:
    """差异计算结果。"""
    mean_diff: float
    max_diff: float
    p99_diff: float
    changed_pixel_ratio: float
    is_significant: bool
    threshold: float
    detail: str = ""


@dataclass
class NoiseEnvelope:
    """噪声包络（同状态两次截图的差异基线）。"""
    mean_diff: float
    p99_diff: float
    max_diff: float
    threshold: float  # max(3x p99, 1%)


class ROIEvaluator:
    """ROI 差异评估器。"""

    def __init__(self, artifacts_dir: Path):
        self.artifacts_dir = artifacts_dir
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self.noise_envelope: Optional[NoiseEnvelope] = None

    def compute_pixel_diff(self, img1_path: Path, img2_path: Path) -> DiffResult:
        """计算两张图片的像素差异。"""
        if not HAS_PIL:
            return DiffResult(0, 0, 0, 0, False, 0, "PIL 未安装")

        img1 = Image.open(str(img1_path)).convert("RGB")
        img2 = Image.open(str(img2_path)).convert("RGB")

        # 统一尺寸（取较小）
        w = min(img1.width, img2.width)
        h = min(img1.height, img2.height)
        if img1.size != (w, h):
            img1 = img1.crop((0, 0, w, h))
        if img2.size != (w, h):
            img2 = img2.crop((0, 0, w, h))

        pixels1 = list(img1.getdata())
        pixels2 = list(img2.getdata())

        diffs = []
        changed = 0
        threshold_per_pixel = 10  # 单像素差异阈值

        for p1, p2 in zip(pixels1, pixels2):
            r_diff = abs(p1[0] - p2[0])
            g_diff = abs(p1[1] - p2[1])
            b_diff = abs(p1[2] - p2[2])
            pixel_diff = (r_diff + g_diff + b_diff) / 3
            diffs.append(pixel_diff)
            if pixel_diff > threshold_per_pixel:
                changed += 1

        total_pixels = len(diffs)
        mean_diff = sum(diffs) / total_pixels if total_pixels > 0 else 0
        max_diff = max(diffs) if diffs else 0
        # p99
        sorted_diffs = sorted(diffs)
        p99_idx = int(len(sorted_diffs) * 0.99)
        p99_diff = sorted_diffs[p99_idx] if sorted_diffs else 0
        changed_ratio = changed / total_pixels if total_pixels > 0 else 0

        # 显著性判定：与噪声包络比较
        if self.noise_envelope:
            threshold = self.noise_envelope.threshold
        else:
            threshold = 0.01  # 默认 1%

        is_significant = changed_ratio > threshold

        return DiffResult(
            mean_diff=round(mean_diff, 4),
            max_diff=round(max_diff, 4),
            p99_diff=round(p99_diff, 4),
            changed_pixel_ratio=round(changed_ratio, 6),
            is_significant=is_significant,
            threshold=threshold,
            detail=f"changed={changed}/{total_pixels}",
        )

    def establish_noise_envelope(self, img1_path: Path, img2_path: Path) -> NoiseEnvelope:
        """建立噪声包络（同状态两次截图）。

        依据计划："两次同状态截图建立噪声包络"
        阈值 = max(3x p99, 1%)
        """
        diff = self.compute_pixel_diff(img1_path, img2_path)
        threshold = max(3 * diff.p99_diff / 255.0, 0.01)  # 归一化到 0-1
        self.noise_envelope = NoiseEnvelope(
            mean_diff=diff.mean_diff,
            p99_diff=diff.p99_diff,
            max_diff=diff.max_diff,
            threshold=threshold,
        )
        return self.noise_envelope

    def generate_diff_image(self, img1_path: Path, img2_path: Path, out_path: Path) -> bool:
        """生成差异图（红色高亮变化区域）。"""
        if not HAS_PIL:
            return False
        img1 = Image.open(str(img1_path)).convert("RGB")
        img2 = Image.open(str(img2_path)).convert("RGB")
        w = min(img1.width, img2.width)
        h = min(img1.height, img2.height)
        if img1.size != (w, h):
            img1 = img1.crop((0, 0, w, h))
        if img2.size != (w, h):
            img2 = img2.crop((0, 0, w, h))

        diff_img = Image.new("RGB", (w, h))
        pixels1 = img1.getdata()
        pixels2 = img2.getdata()
        diff_pixels = []
        for p1, p2 in zip(pixels1, pixels2):
            r_diff = abs(p1[0] - p2[0])
            g_diff = abs(p1[1] - p2[1])
            b_diff = abs(p1[2] - p2[2])
            avg_diff = (r_diff + g_diff + b_diff) / 3
            if avg_diff > 10:
                # 红色高亮
                diff_pixels.append((255, int(255 - avg_diff), int(255 - avg_diff)))
            else:
                diff_pixels.append((int(p1[0] * 0.3), int(p1[1] * 0.3), int(p1[2] * 0.3)))
        diff_img.putdata(diff_pixels)
        diff_img.save(str(out_path), "PNG")
        return True

    def evaluate_change(
        self,
        before_path: Path,
        after_path: Path,
        label: str = "change",
        request_id: str = "",
    ) -> dict:
        """评估 before/after 截图的变化。

        依据计划："spawn/tint 的 ROI 差异大于 max(3x噪声p99, 1%)"
        """
        diff = self.compute_pixel_diff(before_path, after_path)

        # 生成差异图
        diff_filename = f"diff-{label}-{request_id[:8] if request_id else 'noreq'}.png"
        diff_path = self.artifacts_dir / diff_filename
        self.generate_diff_image(before_path, after_path, diff_path)

        result = {
            "label": label,
            "request_id": request_id,
            "before_image": str(before_path),
            "after_image": str(after_path),
            "diff_image": str(diff_path),
            "mean_diff": diff.mean_diff,
            "max_diff": diff.max_diff,
            "p99_diff": diff.p99_diff,
            "changed_pixel_ratio": diff.changed_pixel_ratio,
            "threshold": diff.threshold,
            "is_significant": diff.is_significant,
            "noise_envelope": {
                "mean": self.noise_envelope.mean_diff if self.noise_envelope else 0,
                "p99": self.noise_envelope.p99_diff if self.noise_envelope else 0,
                "threshold": self.noise_envelope.threshold if self.noise_envelope else 0.01,
            } if self.noise_envelope else None,
            "verdict": "passed" if diff.is_significant else "failed",
        }
        return result

    def evaluate_reset(
        self,
        baseline_path: Path,
        after_reset_path: Path,
        request_id: str = "",
    ) -> dict:
        """评估 reset 后是否回到噪声包络内。

        依据计划："reset 回到噪声包络内"
        """
        diff = self.compute_pixel_diff(baseline_path, after_reset_path)

        result = {
            "label": "reset",
            "request_id": request_id,
            "baseline_image": str(baseline_path),
            "after_reset_image": str(after_reset_path),
            "mean_diff": diff.mean_diff,
            "changed_pixel_ratio": diff.changed_pixel_ratio,
            "threshold": diff.threshold,
            "within_noise_envelope": not diff.is_significant,
            "verdict": "passed" if not diff.is_significant else "failed",
        }
        return result


def generate_manifest(
    capture_results: list,
    diff_results: list[dict],
    artifacts_dir: Path,
) -> Path:
    """生成截图 manifest。"""
    manifest = {
        "timestamp": __import__("time").strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        "captures": [
            {
                "label": r.label,
                "image_path": str(r.image_path),
                "width": r.width,
                "height": r.height,
                "sc2_pid": r.sc2_pid,
                "request_id": r.request_id,
                "snapshot_id": r.snapshot_id,
                "captured_at": r.captured_at,
            }
            for r in capture_results
        ],
        "diffs": diff_results,
    }
    manifest_path = artifacts_dir / "visual-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    return manifest_path
