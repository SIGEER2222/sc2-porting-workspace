"""Vibe Host 清理模块 — 资源/Bank/日志/进程清理。

依据 sc2-vibe完整实施计划.md P7 验收:
  - 资源/Bank/日志无界增长即失败
  - 残留 SC2/锁即失败

清理范围:
  1. Bank 文件：每次 run 后归档/压缩历史 Bank 副本（保留最近 N 个）
  2. 日志：artifacts/galaxy-vibe/<run_id>/ 下的 *.ndjson / *.log 滚动归档
  3. 临时 lock：host.pid / sc2.pid / kernel.lock 等孤儿锁文件清理
  4. 截图：visual/*.png 超过保留数的旧图归档到 archive/
  5. 孤儿 SC2 进程：检测无 Host 关联的 SC2_x64.exe 进程（仅检测+报告，不主动 kill）

调用方式:
  from cleanup import CleanupManager
  mgr = CleanupManager(base_dir=artifacts_dir, bank_dir=bank_dir, keep_recent=10)
  report = mgr.run()
"""
from __future__ import annotations

import json
import os
import shutil
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class CleanupReport:
    """单次清理的执行报告。"""
    ran_at: str
    archived_banks: list[str] = field(default_factory=list)
    archived_logs: list[str] = field(default_factory=list)
    archived_screenshots: list[str] = field(default_factory=list)
    removed_locks: list[str] = field(default_factory=list)
    orphan_sc2_pids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def total_actions(self) -> int:
        return (
            len(self.archived_banks)
            + len(self.archived_logs)
            + len(self.archived_screenshots)
            + len(self.removed_locks)
        )


class CleanupManager:
    """统一清理 P7 阶段的资源。"""

    LOCK_FILENAMES = ("host.pid", "sc2.pid", "kernel.lock", "vibe_host.lock")
    LOG_SUFFIXES = (".ndjson", ".log")
    SCREENSHOT_SUFFIXES = (".png",)
    BANK_SUFFIX = ".SC2Bank"

    def __init__(
        self,
        base_dir: Path,
        bank_dir: Optional[Path] = None,
        keep_recent: int = 10,
        archive_subdir: str = "archive",
    ):
        self.base_dir = Path(base_dir)
        self.bank_dir = Path(bank_dir) if bank_dir else self.base_dir / "banks"
        self.keep_recent = keep_recent
        self.archive_dir = self.base_dir / archive_subdir

    def run(self) -> CleanupReport:
        report = CleanupReport(ran_at=self._now())
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        self._cleanup_banks(report)
        self._cleanup_logs(report)
        self._cleanup_screenshots(report)
        self._cleanup_locks(report)
        self._detect_orphan_sc2(report)

        return report

    def save_report(self, report: CleanupReport, path: Optional[Path] = None) -> Path:
        target = path or (self.base_dir / "cleanup-report.json")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    # ---- 子任务 ----

    def _cleanup_banks(self, report: CleanupReport) -> None:
        if not self.bank_dir.exists():
            return
        banks = sorted(
            self.bank_dir.glob(f"*{self.BANK_SUFFIX}"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if len(banks) <= self.keep_recent:
            return
        to_archive = banks[self.keep_recent:]
        ts = time.strftime("%Y%m%d-%H%M%S")
        archive_target = self.archive_dir / f"banks-{ts}"
        archive_target.mkdir(parents=True, exist_ok=True)
        for f in to_archive:
            try:
                shutil.move(str(f), str(archive_target / f.name))
                report.archived_banks.append(str(f))
            except OSError as e:
                report.errors.append(f"bank {f.name}: {e}")

    def _cleanup_logs(self, report: CleanupReport) -> None:
        for run_dir in self.base_dir.glob("run-*"):
            if not run_dir.is_dir():
                continue
            for suffix in self.LOG_SUFFIXES:
                files = sorted(
                    run_dir.glob(f"*{suffix}"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
                if len(files) <= self.keep_recent:
                    continue
                to_archive = files[self.keep_recent:]
                archive_target = self.archive_dir / run_dir.name
                archive_target.mkdir(parents=True, exist_ok=True)
                for f in to_archive:
                    try:
                        shutil.move(str(f), str(archive_target / f.name))
                        report.archived_logs.append(str(f))
                    except OSError as e:
                        report.errors.append(f"log {f.name}: {e}")

    def _cleanup_screenshots(self, report: CleanupReport) -> None:
        visual_dir = self.base_dir / "visual"
        if not visual_dir.exists():
            return
        for suffix in self.SCREENSHOT_SUFFIXES:
            files = sorted(
                visual_dir.glob(f"*{suffix}"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if len(files) <= self.keep_recent:
                continue
            to_archive = files[self.keep_recent:]
            archive_target = self.archive_dir / "visual"
            archive_target.mkdir(parents=True, exist_ok=True)
            for f in to_archive:
                try:
                    shutil.move(str(f), str(archive_target / f.name))
                    report.archived_screenshots.append(str(f))
                except OSError as e:
                    report.errors.append(f"png {f.name}: {e}")

    def _cleanup_locks(self, report: CleanupReport) -> None:
        """清理孤儿 lock 文件（指向不存在 PID 的锁）。"""
        for name in self.LOCK_FILENAMES:
            lock_path = self.base_dir / name
            if not lock_path.exists():
                continue
            try:
                content = lock_path.read_text(encoding="utf-8").strip()
                pid = int(content) if content.isdigit() else None
                if pid is not None and self._pid_alive(pid):
                    # 持有者仍存活，跳过
                    continue
                lock_path.unlink()
                report.removed_locks.append(str(lock_path))
            except (OSError, ValueError) as e:
                report.errors.append(f"lock {name}: {e}")

    def _detect_orphan_sc2(self, report: CleanupReport) -> None:
        """检测无 Host 关联的 SC2_x64.exe 进程（仅报告，不 kill）。"""
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            # 用 toolhelp32 枚举进程，避免依赖 psutil
            TH32CS_SNAPPROCESS = 0x00000002

            class PROCESSENTRY32(ctypes.Structure):
                _fields_ = [
                    ("dwSize", wintypes.DWORD),
                    ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD),
                    ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
                    ("th32ModuleID", wintypes.DWORD),
                    ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD),
                    ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD),
                    ("szExeFile", ctypes.c_char * 260),
                ]

            kernel32 = ctypes.windll.kernel32
            snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
            if snapshot == -1:
                return

            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)

            # 先读取 host.pid（如果存在）作为父进程关联检查
            host_pid = None
            host_pid_file = self.base_dir / "host.pid"
            if host_pid_file.exists():
                try:
                    host_pid = int(host_pid_file.read_text(encoding="utf-8").strip())
                except (OSError, ValueError):
                    pass

            if kernel32.Process32First(snapshot, ctypes.byref(entry)):
                while True:
                    name = entry.szExeFile.decode("utf-8", errors="ignore").lower()
                    if name == "sc2_x64.exe":
                        sc2_pid = entry.th32ProcessID
                        parent_pid = entry.th32ParentProcessID
                        # 若 host_pid 已知且 SC2 的父进程匹配 host_pid → 视为关联
                        if host_pid is None or parent_pid != host_pid:
                            report.orphan_sc2_pids.append(sc2_pid)
                    if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                        break
            kernel32.CloseHandle(snapshot)
        except Exception as e:
            report.errors.append(f"orphan_sc2: {e}")

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        if os.name != "nt":
            return False
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            STILL_ACTIVE = 259
            handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            exit_code = wintypes.DWORD()
            ok = kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code))
            kernel32.CloseHandle(handle)
            return bool(ok) and exit_code.value == STILL_ACTIVE
        except Exception:
            return False

    @staticmethod
    def _now() -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())
