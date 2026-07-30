#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3 视觉闭环 — 截图采集 + ROI 差异判定。

离线可验部分：ROI 差异算法（给定两图，算 ROI 内平均像素差，按阈值判定 changed）。
真机部分：实时窗口采集（mss 抓游戏窗口），沙箱无头环境无 mss，运行时 guarded skip。

命令：
  --diff <A.png> <B.png> [--roi x,y,w,h] [--threshold N]
        比较两图，输出 {mean_diff, changed, threshold, roi}，退出码 changed?1:0
  --gen-test <DIR>       生成合成测试图（base/same/roi-changed/full-changed）
  --selftest <DIR>       生成测试图 + 断言 diff 行为，退出码 0/1（全过/否则）
  --capture-loop [--adapter file|mss] [--frames N] [--roi x,y,w,h]
                [--threshold N] [--steady K] [--src <dir>] [--out <verdict.json>]
        连续采集并判定"场景稳定"，稳定后写 visual-verdict.json。
        adapter=file：从历史截图目录回放（离线/真机回放）；adapter=mss：真机窗口（沙箱跳过）。

证据分类：diff 算法是确定性图像数学（static 验证）；真机 capture-loop 的判定属 visual 证据，
需 master 桌面跑 mss 采集才成立。本脚本只做判定与生成，不写任何只读源。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_VERDICT = REPO_ROOT / "artifacts" / "galaxy-vibe" / "visual-verdict.json"

try:
    from PIL import Image, ImageChops, ImageStat
    _HAVE_PIL = True
except Exception:  # pragma: no cover - 缺 Pillow 时给出明确提示而非崩溃
    _HAVE_PIL = False


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _require_pil():
    if not _HAVE_PIL:
        sys.stderr.write(
            "ERROR: Pillow 未安装（visual_loop 需要）。\n"
            "安装：python -m venv ... && pip install Pillow\n"
        )
        raise SystemExit(2)


def load_rgb(p: Path) -> Image.Image:
    return Image.open(p).convert("RGB")


def parse_roi(s: str | None):
    if not s:
        return None
    parts = [int(x) for x in s.split(",")]
    if len(parts) != 4:
        raise SystemExit(f"--roi 需 x,y,w,h，收到: {s}")
    return tuple(parts)


def _clamp_roi(roi, w, h):
    x, y, rw, rh = roi
    x = max(0, min(x, w))
    y = max(0, min(y, h))
    rw = max(0, min(rw, w - x))
    rh = max(0, min(rh, h - y))
    return (x, y, rw, rh)


def crop_roi(img: Image.Image, roi):
    if not roi:
        return img
    x, y, rw, rh = _clamp_roi(roi, img.width, img.height)
    if rw <= 0 or rh <= 0:
        return img
    return img.crop((x, y, x + rw, y + rh))


def mean_abs_diff(a: Image.Image, b: Image.Image) -> float:
    """两图（已同尺寸 RGB）的平均绝对像素差，0..255。"""
    if a.size != b.size:
        b = b.resize(a.size)
    diff = ImageChops.difference(a, b)
    means = ImageStat.Stat(diff).mean  # 每通道均值
    return sum(means) / len(means)


def diff_pair(a: Image.Image, b: Image.Image, roi, threshold: float) -> dict:
    da = crop_roi(a, roi)
    db = crop_roi(b, roi)
    md = mean_abs_diff(da, db)
    return {
        "mean_diff": round(md, 4),
        "threshold": threshold,
        "changed": md > threshold,
        "roi": list(roi) if roi else None,
    }


# ---- 采集适配器 ----------------------------------------------------------------

class CaptureAdapter:
    def capture(self) -> Image.Image:  # pragma: no cover - 抽象
        raise NotImplementedError

    def __iter__(self):
        return self

    def __next__(self):  # pragma: no cover - 默认无限采集
        return self.capture()


class FileCaptureAdapter(CaptureAdapter):
    """从历史截图目录回放（离线验证 / 真机回放）。"""

    def __init__(self, src: Path, limit: int | None = None):
        files = sorted(src.rglob("*.png")) if src.is_dir() else [src]
        self.frames = [f for f in files if f.suffix.lower() == ".png"]
        if limit:
            self.frames = self.frames[:limit]
        self._i = 0

    def __next__(self):
        if self._i >= len(self.frames):
            raise StopIteration
        img = load_rgb(self.frames[self._i])
        self._i += 1
        return img

    def __len__(self):
        return len(self.frames)


class MssCaptureAdapter(CaptureAdapter):
    """真机游戏窗口采集（mss）。沙箱无 mss，构造即抛错由调用方 guarded 跳过。"""

    def __init__(self, monitor: int = 1):
        try:
            import mss  # type: ignore
        except Exception as e:  # pragma: no cover
            raise RuntimeError("mss 不可用（仅真机桌面环境支持实时采集）") from e
        self._mss = mss.mss()
        self._mon = monitor

    def capture(self) -> Image.Image:
        shot = self._mss.grab(self._mss.monitors[self._mon])
        from PIL import Image as _I
        return _I.frombytes("RGB", shot.size, shot.rgb).convert("RGB")


# ---- 命令实现 ------------------------------------------------------------------

def cmd_diff(a):
    _require_pil()
    roi = parse_roi(a.roi)
    img_a = load_rgb(Path(a.diff[0]))
    img_b = load_rgb(Path(a.diff[1]))
    res = diff_pair(img_a, img_b, roi, a.threshold)
    print(json.dumps(res, indent=2, ensure_ascii=False))
    raise SystemExit(1 if res["changed"] else 0)


def gen_test_images(d: Path) -> dict:
    _require_pil()
    d.mkdir(parents=True, exist_ok=True)
    base = Image.new("RGB", (320, 200), (128, 128, 128))
    # 固定标记块（左上），用于肉眼/对齐参考
    for yy in range(10, 30):
        for xx in range(10, 30):
            base.putpixel((xx, yy), (200, 80, 80))
    # same：完全一致
    same = base.copy()
    # roi-changed：在 ROI(100,80,80,60) 内改一块
    roi_changed = base.copy()
    for yy in range(90, 120):
        for xx in range(110, 150):
            roi_changed.putpixel((xx, yy), (20, 200, 20))
    # full-changed：整体换色
    full_changed = Image.new("RGB", (320, 200), (40, 40, 200))

    paths = {
        "base": d / "base.png",
        "same": d / "same.png",
        "roi": d / "roi_changed.png",
        "full": d / "full_changed.png",
    }
    base.save(paths["base"])
    same.save(paths["same"])
    roi_changed.save(paths["roi"])
    full_changed.save(paths["full"])
    return {k: str(v) for k, v in paths.items()}


def cmd_selftest(a):
    _require_pil()
    d = Path(a.gen_test) if a.gen_test else (Path(a.selftest))
    paths = gen_test_images(d)
    roi = (100, 80, 80, 60)
    cases = []
    # 1) base vs same → 不变
    r1 = diff_pair(load_rgb(Path(paths["base"])), load_rgb(Path(paths["same"])), roi, a.threshold)
    cases.append(("base==same unchanged", (not r1["changed"]) and r1["mean_diff"] < 1.0))
    # 2) base vs roi(ROI 内改动) → 变
    r2 = diff_pair(load_rgb(Path(paths["base"])), load_rgb(Path(paths["roi"])), roi, a.threshold)
    cases.append(("base vs roi-changed (roi) changed", r2["changed"] and r2["mean_diff"] > 0))
    # 3) base vs roi 但 ROI 取左上标记块外(无改动区) → 不变（证明 ROI 局部性）
    r3 = diff_pair(load_rgb(Path(paths["base"])), load_rgb(Path(paths["roi"])), (10, 10, 20, 20), a.threshold)
    cases.append(("roi-changed outside roi unchanged", not r3["changed"]))
    # 4) base vs full → 变（全图）
    r4 = diff_pair(load_rgb(Path(paths["base"])), load_rgb(Path(paths["full"])), None, a.threshold)
    cases.append(("base vs full-changed changed", r4["changed"] and r4["mean_diff"] > 30))

    ok = True
    for name, passed in cases:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(json.dumps({
        "selftest": "pass" if ok else "fail",
        "cases": [c[0] for c in cases if c[1]],
        "failed": [c[0] for c in cases if not c[1]],
    }, indent=2, ensure_ascii=False))
    raise SystemExit(0 if ok else 1)


def cmd_capture_loop(a):
    _require_pil()
    roi = parse_roi(a.roi)
    out = Path(a.out)
    if a.adapter == "mss":
        try:
            adapter: CaptureAdapter = MssCaptureAdapter()
        except RuntimeError as e:
            # 沙箱/无 mss：明确跳过，不写 verdict（避免假通过），退出 0 不打断链路
            print(f"[visual] {e}；跳过实时采集（desktop-only）。")
            raise SystemExit(0)
    else:
        if not a.src:
            sys.stderr.write("ERROR: --adapter file 需要 --src <目录>\n")
            raise SystemExit(2)
        adapter = FileCaptureAdapter(Path(a.src), limit=a.frames)

    prev = None
    steady = 0
    diffs = []
    captured = 0
    try:
        for cur in adapter:
            if prev is not None:
                d = mean_abs_diff(crop_roi(prev, roi), crop_roi(cur, roi))
                diffs.append(round(d, 4))
                steady = steady + 1 if d <= a.threshold else 0
            prev = cur
            captured += 1
            if a.adapter != "mss" and a.frames and captured >= a.frames:
                break
    except StopIteration:
        pass

    stable = steady >= a.steady
    verdict = {
        "tool": "visual_loop",
        "adapter": a.adapter,
        "stable": stable,
        "visual_passed": stable,
        "frames_captured": captured,
        "steady_frames": steady,
        "required_steady": a.steady,
        "threshold": a.threshold,
        "roi": list(roi) if roi else None,
        "mean_diffs": diffs,
        "checked_at": utcnow(),
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[visual] stable={stable} steady={steady}/{a.steady} frames={captured} -> {out}")
    # 视觉稳定视为"通过"，否则 1
    raise SystemExit(0 if stable else 1)


def main():
    ap = argparse.ArgumentParser(description="P3 视觉闭环：ROI 差异判定 + 采集适配器")
    ap.add_argument("--diff", nargs=2, metavar=("A", "B"), help="比较两图输出 diff JSON")
    ap.add_argument("--roi", help="ROI x,y,w,h（像素）")
    ap.add_argument("--threshold", type=float, default=8.0, help="mean abs diff 阈值，默认 8.0")
    ap.add_argument("--gen-test", metavar="DIR", help="生成合成测试图")
    ap.add_argument("--selftest", metavar="DIR", help="生成+断言 diff 行为")
    ap.add_argument("--capture-loop", action="store_true", help="连续采集判定场景稳定")
    ap.add_argument("--adapter", choices=["file", "mss"], default="file")
    ap.add_argument("--frames", type=int, default=0, help="file 适配器最多帧数（0=全部）")
    ap.add_argument("--steady", type=int, default=3, help="稳定所需连续稳态帧数")
    ap.add_argument("--src", help="file 适配器截图目录")
    ap.add_argument("--out", default=str(DEFAULT_VERDICT), help="visual-verdict.json 输出")
    a = ap.parse_args()

    if a.diff:
        return cmd_diff(a)
    if a.selftest or a.gen_test:
        return cmd_selftest(a)
    if a.capture_loop:
        return cmd_capture_loop(a)
    ap.print_help()
    raise SystemExit(2)


if __name__ == "__main__":
    main()
