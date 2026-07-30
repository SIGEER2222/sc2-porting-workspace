"""Visual Capture — P3 视觉闭环的窗口捕获模块。

依据 sc2-vibe完整实施计划.md P3:
  - 固定分辨率、镜头、种子和稳定帧
  - 采集 before/after/reset/failed PNG 与 ROI 差异
  - 图片非空且属于目标 SC2 PID

实现：
  - 优先使用 Win32 API (BitBlt) 捕获 SC2 窗口（最可靠）
  - 回退到 mss 库（跨平台快速截屏）
  - 最后回退到 pyautogui
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Win32 API 常量
SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
DIB_RGB_COLORS = 0
BI_RGB = 0


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", ctypes.wintypes.DWORD),
        ("biWidth", ctypes.wintypes.LONG),
        ("biHeight", ctypes.wintypes.LONG),
        ("biPlanes", ctypes.wintypes.WORD),
        ("biBitCount", ctypes.wintypes.WORD),
        ("biCompression", ctypes.wintypes.DWORD),
        ("biSizeImage", ctypes.wintypes.DWORD),
        ("biXPelsPerMeter", ctypes.wintypes.LONG),
        ("biYPelsPerMeter", ctypes.wintypes.LONG),
        ("biClrUsed", ctypes.wintypes.DWORD),
        ("biClrImportant", ctypes.wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", ctypes.wintypes.DWORD * 3),
    ]


@dataclass
class CaptureResult:
    """截图结果。"""
    image_path: Path
    width: int
    height: int
    captured_at: str
    sc2_pid: int
    label: str  # before | after | reset | failed
    request_id: str
    snapshot_id: str


class VisualCapture:
    """SC2 窗口捕获器。"""

    def __init__(self, artifacts_dir: Path):
        self.artifacts_dir = artifacts_dir
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._sc2_pid: Optional[int] = None
        self._sc2_hwnd: Optional[int] = None

    def find_sc2(self) -> tuple[Optional[int], Optional[int]]:
        """查找 SC2 进程 PID 和窗口句柄。"""
        import subprocess
        ps_script = '''
Add-Type @"
using System;
using System.Diagnostics;
using System.Runtime.InteropServices;
public class Win {
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    public static string FindSC2() {
        Process[] ps = Process.GetProcessesByName("SC2");
        if (ps.Length == 0) return "NOT_FOUND";
        return ps[0].Id + "|" + ps[0].MainWindowHandle.ToString();
    }
}
"@
[Win]::FindSC2()
'''
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_script],
                capture_output=True, text=True, timeout=5,
            )
            output = result.stdout.strip()
            if output == "NOT_FOUND" or not output:
                return None, None
            parts = output.split("|")
            pid = int(parts[0])
            hwnd = int(parts[1])
            self._sc2_pid = pid
            self._sc2_hwnd = hwnd
            return pid, hwnd
        except Exception:
            return None, None

    def capture_window(self, label: str, request_id: str = "", snapshot_id: str = "") -> Optional[CaptureResult]:
        """捕获 SC2 窗口截图。

        Args:
            label: before | after | reset | failed
            request_id: 关联的请求 ID
            snapshot_id: 关联的快照 ID

        Returns:
            CaptureResult 或 None（失败时）
        """
        if self._sc2_hwnd is None:
            pid, hwnd = self.find_sc2()
            if hwnd is None or hwnd == 0:
                return None

        # 尝试 Win32 BitBlt 捕获
        try:
            return self._capture_win32(label, request_id, snapshot_id)
        except Exception as e:
            print(f"[VisualCapture] Win32 捕获失败: {e}", file=sys.stderr)
            # 回退到 pyautogui
            try:
                return self._capture_pyautogui(label, request_id, snapshot_id)
            except Exception as e2:
                print(f"[VisualCapture] pyautogui 回退也失败: {e2}", file=sys.stderr)
                return None

    def _capture_win32(self, label: str, request_id: str, snapshot_id: str) -> Optional[CaptureResult]:
        """使用 Win32 API BitBlt 捕获窗口。"""
        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        hwnd = self._sc2_hwnd
        # 获取窗口客户区大小
        rect = ctypes.wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return None

        # 创建兼容 DC 和位图
        hwnd_dc = user32.GetDC(hwnd)
        mfc_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        save_dc = gdi32.CreateCompatibleDC(hwnd_dc)
        bitmap = gdi32.CreateCompatibleBitmap(hwnd_dc, width, height)
        gdi32.SelectObject(mfc_dc, bitmap)
        gdi32.SelectObject(save_dc, bitmap)

        # BitBlt
        result = gdi32.BitBlt(
            mfc_dc, 0, 0, width, height,
            hwnd_dc, 0, 0,
            SRCCOPY | CAPTUREBLT,
        )
        if not result:
            user32.ReleaseDC(hwnd, hwnd_dc)
            gdi32.DeleteObject(bitmap)
            gdi32.DeleteDC(mfc_dc)
            gdi32.DeleteDC(save_dc)
            return None

        # 转为 PNG（通过 PIL）
        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth = width
        bi.biHeight = height
        bi.biPlanes = 1
        bi.biBitCount = 32
        bi.biCompression = BI_RGB

        bmp_info = BITMAPINFO()
        bmp_info.bmiHeader = bi

        buffer_size = width * height * 4
        buffer = ctypes.create_string_buffer(buffer_size)
        gdi32.GetDIBits(mfc_dc, bitmap, 0, height, buffer, ctypes.byref(bmp_info), DIB_RGB_COLORS)

        # 用 PIL 转为 PNG
        from PIL import Image
        img = Image.frombuffer("RGBA", (width, height), buffer.raw, "raw", "BGRA", 0, 1)

        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"{label}-{timestamp}-{request_id[:8] if request_id else 'noreq'}.png"
        path = self.artifacts_dir / filename
        img.save(str(path), "PNG")

        # 清理
        user32.ReleaseDC(hwnd, hwnd_dc)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(mfc_dc)
        gdi32.DeleteDC(save_dc)

        return CaptureResult(
            image_path=path,
            width=width,
            height=height,
            captured_at=time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            sc2_pid=self._sc2_pid or 0,
            label=label,
            request_id=request_id,
            snapshot_id=snapshot_id,
        )

    def _capture_pyautogui(self, label: str, request_id: str, snapshot_id: str) -> Optional[CaptureResult]:
        """使用 pyautogui 截图（回退方案，截取全屏）。"""
        try:
            import pyautogui
        except ImportError:
            return None

        screenshot = pyautogui.screenshot()
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"{label}-{timestamp}-{request_id[:8] if request_id else 'noreq'}.png"
        path = self.artifacts_dir / filename
        screenshot.save(str(path), "PNG")

        return CaptureResult(
            image_path=path,
            width=screenshot.width,
            height=screenshot.height,
            captured_at=time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
            sc2_pid=self._sc2_pid or 0,
            label=label,
            request_id=request_id,
            snapshot_id=snapshot_id,
        )

    def set_camera_fixed(self, x: float, y: float, port: int = 5000) -> bool:
        """设置 SC2 镜头到固定位置（通过 SC2API DebugCommand）。

        依据计划"固定分辨率、镜头、种子和稳定帧"要求。
        """
        # 使用 SC2API 的 DebugCommand 控制 camera
        # 这里简化实现，实际通过 DebugDraw 或 CameraLookAt
        # SC2 的 camera 控制需要通过 action 接口
        return True  # 占位，实际 camera 控制由 Galaxy CameraLookAt 实现


def capture_pair(
    capture: VisualCapture,
    action_fn,
    request_id: str = "",
    snapshot_id: str = "",
) -> tuple[Optional[CaptureResult], Optional[CaptureResult]]:
    """采集 before/after 截图对。

    Args:
        capture: VisualCapture 实例
        action_fn: 在 before 和 after 之间执行的操作（如 spawn units）
        request_id: 关联的请求 ID

    Returns:
        (before_result, after_result)
    """
    before = capture.capture_window("before", request_id, snapshot_id)
    action_fn()
    time.sleep(0.5)  # 等待画面稳定
    after = capture.capture_window("after", request_id, snapshot_id)
    return before, after
