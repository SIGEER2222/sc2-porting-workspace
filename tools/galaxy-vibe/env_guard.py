#!/usr/bin/env python3
"""env_guard.py — 真机探针的环境哨兵：把「环境被抢」和「代码失败」分开。

## 为什么需要它（2026-08-09 血泪）

N2 tier100 抽样跑出 `ok=0/53`，53 项清一色 `INTERNAL_ERROR` + `elapsed_ms≈3080`
（全部撞满 3s 超时）。看上去像是生成的 gen bundle 把 MapScript 整个搞挂了，
于是花了一整轮去查编译闭包 —— 结果 `closure_doctor` 形态 A~J 全 0、
`staged_map_doctor` CLEAN、重打包字节数与原图一致。代码侧根本没问题。

真相靠事后翻 Bank 文件 mtime 才拼出来：

    13:28:04  探针启动，连上 API 实例 PID 26896
    13:28:05  Host 把 request 写进 Banks/<n>/GalaxyVibe.SC2Bank
    13:28:36  Bank 最后一次被写
    13:28:39  另一个 SC2 实例 PID 27348 启动（真人局，命令行是裸地图无 -listen）
    13:28:39+ 我的 API 实例被挤掉，之后 53 次调用全部空转到超时

也就是说：**这份 0/53 的证据是环境噪声，不是判据**。而探针自己毫不知情，
还一本正经把它写进 artifacts 当验收证据 —— 这比没有证据更危险，因为它会
把后续所有根因分析引向错误方向（我已经被引偏一整轮）。

## 判据设计

单看「调用超时」无法区分三种截然不同的失败，必须引入两路正交信号：

  信号 A（进程侧）：基线 SC2 PID 是否还活着 / 是否冒出了新的 SC2 实例
  信号 B（Bank 侧）：Kernel **写方向**的键有没有增长
                     （watchdog_last_seen_poll / kernel_initialized / response/*）
                     注意 request/* 是 Host 自己写的，绝不能拿来判 Kernel 活性 ——
                     那是自己写自己读的假阳性。

组合出四种 verdict：

  ok                        正常
  env_preempted             基线 PID 没了，或冒出新 SC2 实例 ⇒ 环境被抢，结果作废
  kernel_never_registered   实例活着但 Kernel 侧从头到尾零写入
                            ⇒ MapScript 被静默丢弃（Galaxy 铁律的经典表现）
  kernel_lost_midway        Kernel 先有写入后停摆 ⇒ 运行期硬崩 / PollLoop 卡死

前两者结果**不可用于验收**，后两者才是真的代码问题、值得去二分定位。

## 用法

    guard = EnvGuard()
    guard.baseline()
    ...
    v = guard.check()          # 每次调用后调一下，None 表示一切正常
    if v: break                # 非 None ⇒ 环境或 Kernel 出事，立刻停，别再刷垃圾数据
    ...
    guard.verdict(any_ok=...)  # 收尾时给最终裁决

非 Windows 或枚举失败时优雅降级：进程侧信号关闭，只保留 Bank 侧，
`degraded` 标志会如实写进证据，绝不假装自己在守护。
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BANK_NAME = "GalaxyVibe"
BANKS_ROOT = Path.home() / "Documents" / "StarCraft II" / "Banks"

# Kernel 单方向写入的键。request/* 是 Host 写的，故意排除 —— 拿它判活性等于自欺。
KERNEL_INDEX_KEYS = ("watchdog_last_seen_poll", "kernel_initialized", "state_version")
KERNEL_SECTIONS = ("response", "diag")


# --------------------------------------------------------------------- 进程枚举
def list_sc2_pids() -> set[int] | None:
    """枚举 SC2 进程 PID。返回 None 表示本平台不支持（哨兵降级，不是「没有进程」）。

    刻意用 ctypes + Toolhelp32 而不是 psutil / PowerShell：
      - psutil 不一定装（真机跑的是系统 Py3.11，依赖越少越好）
      - 每次调用都起一个 PowerShell 进程的话，53 次调用要多花好几秒，
        而且会跟正在测的 SC2 抢 CPU，属于观测行为干扰被观测对象
    Toolhelp32 快照是微秒级的，可以放心塞进每次调用后的检查点。
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes
        from ctypes import wintypes

        TH32CS_SNAPPROCESS = 0x00000002
        INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

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

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if snap == INVALID_HANDLE_VALUE:
            return None
        try:
            entry = PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
            pids: set[int] = set()
            ok = k32.Process32First(snap, ctypes.byref(entry))
            while ok:
                name = entry.szExeFile.decode("latin-1", "replace")
                if name.lower().startswith("sc2"):
                    pids.add(int(entry.th32ProcessID))
                ok = k32.Process32Next(snap, ctypes.byref(entry))
            return pids
        finally:
            k32.CloseHandle(snap)
    except Exception:
        return None


# ----------------------------------------------------------------- Bank 活性
@dataclass
class KernelLiveness:
    """Kernel **写方向**的聚合信号。故意不含 request 段。"""

    watchdog_max: int = -1
    kernel_initialized: bool = False
    response_keys: int = 0
    diag_keys: int = 0
    banks_seen: int = 0

    def signal_tuple(self) -> tuple:
        return (self.watchdog_max, self.kernel_initialized, self.response_keys, self.diag_keys)

    def is_silent(self) -> bool:
        """Kernel 一个字节都没写过。"""
        return self.signal_tuple() == (-1, False, 0, 0)

    def to_dict(self) -> dict:
        return {
            "watchdog_max": self.watchdog_max,
            "kernel_initialized": self.kernel_initialized,
            "response_keys": self.response_keys,
            "diag_keys": self.diag_keys,
            "banks_seen": self.banks_seen,
        }


def _iter_bank_files() -> list[Path]:
    """Banks root + Banks/<digits>/ 下的同名 bank。

    ARENA-007：Galaxy 端实际读写的是 Banks/<AuthorHash>/，只看 root 会永远读不到
    Kernel 的写入。跳过点开头目录，避免 runtime-lab 的备份自嵌套把旧局数据
    混进来（那会造成「读到上一场的 kernel_initialized」这种假阳性）。
    """
    out: list[Path] = []
    if not BANKS_ROOT.is_dir():
        return out
    root_bank = BANKS_ROOT / f"{BANK_NAME}.SC2Bank"
    if root_bank.is_file():
        out.append(root_bank)
    for sub in BANKS_ROOT.iterdir():
        if not sub.is_dir() or sub.name.startswith("."):
            continue
        cand = sub / f"{BANK_NAME}.SC2Bank"
        if cand.is_file():
            out.append(cand)
    return out


def read_kernel_liveness() -> KernelLiveness:
    live = KernelLiveness()
    for path in _iter_bank_files():
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # SC2 正在 BankSave 持句柄是常态，跳过即可，不要让哨兵自己抛异常
            continue
        live.banks_seen += 1
        index_body = _section_body(text, "index")
        for key in KERNEL_INDEX_KEYS:
            hit = re.search(
                r'<Key name="' + re.escape(key) + r'"\s*>\s*<Value\s+(\w+)="([^"]*)"',
                index_body,
            )
            if not hit:
                continue
            if key == "watchdog_last_seen_poll":
                try:
                    live.watchdog_max = max(live.watchdog_max, int(hit.group(2)))
                except ValueError:
                    pass
            else:
                live.kernel_initialized = True
        live.response_keys += len(re.findall(r"<Key ", _section_body(text, "response")))
        live.diag_keys += len(re.findall(r"<Key ", _section_body(text, "diag")))
    return live


def _section_body(text: str, name: str) -> str:
    hit = re.search(r'<Section name="' + re.escape(name) + r'">(.*?)</Section>', text, re.S)
    return hit.group(1) if hit else ""


# --------------------------------------------------------------------- 哨兵
@dataclass
class EnvGuard:
    kernel_silence_grace_s: float = 30.0
    """Kernel 侧允许静默多久才判定异常。

    地图加载 + InitMap + PollLoop 首轮 BankSave 是要时间的，开局立刻判死会误杀。
    30s 是从实测 CreateGame→首个 watchdog 落盘的耗时留足余量取的。
    """

    baseline_pids: set[int] | None = None
    baseline_live: KernelLiveness = field(default_factory=KernelLiveness)
    started_at: float = 0.0
    degraded: bool = False
    tripped: dict | None = None

    def baseline(self) -> dict:
        self.baseline_pids = list_sc2_pids()
        self.degraded = self.baseline_pids is None
        self.baseline_live = read_kernel_liveness()
        self.started_at = time.time()
        self.tripped = None
        return {
            "baseline_pids": sorted(self.baseline_pids) if self.baseline_pids else None,
            "baseline_kernel": self.baseline_live.to_dict(),
            "degraded": self.degraded,
        }

    def check(self) -> dict | None:
        """返回非 None 表示环境/Kernel 出事，调用方应立即停止，别再刷无意义数据。"""
        if self.tripped is not None:
            return self.tripped

        # ---- 信号 A：进程侧
        if self.baseline_pids is not None:
            now_pids = list_sc2_pids()
            if now_pids is not None:
                gone = self.baseline_pids - now_pids
                added = now_pids - self.baseline_pids
                if gone:
                    return self._trip("env_preempted", {
                        "reason": "baseline_sc2_exited",
                        "gone_pids": sorted(gone),
                        "current_pids": sorted(now_pids),
                        "hint": "连接的 SC2 实例已退出（被挤掉或崩溃），本轮结果不可用于验收",
                    })
                if added:
                    return self._trip("env_preempted", {
                        "reason": "foreign_sc2_appeared",
                        "new_pids": sorted(added),
                        "current_pids": sorted(now_pids),
                        "hint": "运行期间出现新的 SC2 实例（多半是真人局），本轮结果不可用于验收",
                    })

        # ---- 信号 B：Bank 侧
        live = read_kernel_liveness()
        elapsed = time.time() - self.started_at
        if elapsed >= self.kernel_silence_grace_s:
            if live.is_silent():
                return self._trip("kernel_never_registered", {
                    "reason": "kernel_wrote_nothing",
                    "elapsed_s": round(elapsed, 1),
                    "kernel": live.to_dict(),
                    "hint": "Kernel 侧零写入 ⇒ MapScript 很可能被静默丢弃，"
                            "下一步做 shard 二分定位，别再重复整包重跑",
                })
            if (not self.baseline_live.is_silent()
                    and live.signal_tuple() == self.baseline_live.signal_tuple()):
                return self._trip("kernel_lost_midway", {
                    "reason": "kernel_signal_frozen",
                    "elapsed_s": round(elapsed, 1),
                    "kernel": live.to_dict(),
                    "hint": "Kernel 曾有写入但已停摆 ⇒ 运行期硬崩或 PollLoop 卡死",
                })
        return None

    def _trip(self, verdict: str, detail: dict) -> dict:
        self.tripped = {"verdict": verdict, **detail}
        return self.tripped

    def verdict(self, any_ok: bool) -> dict:
        """收尾裁决。any_ok=True（哪怕只成功过一次）时不再报 kernel_never_registered。"""
        if self.tripped is not None:
            return {**self.tripped, "usable_for_acceptance": False}
        live = read_kernel_liveness()
        if not any_ok and live.is_silent():
            return {
                "verdict": "kernel_never_registered",
                "reason": "kernel_wrote_nothing_at_exit",
                "kernel": live.to_dict(),
                "usable_for_acceptance": False,
            }
        return {
            "verdict": "ok",
            "kernel": live.to_dict(),
            "degraded": self.degraded,
            "usable_for_acceptance": True,
        }


def main() -> int:
    """CLI：直接打印当前环境快照，用于开跑前人工确认档期是否干净。"""
    pids = list_sc2_pids()
    live = read_kernel_liveness()
    print(f"sc2_pids      : {sorted(pids) if pids is not None else 'UNSUPPORTED(degraded)'}")
    print(f"banks_seen    : {live.banks_seen}")
    print(f"kernel_signal : {live.to_dict()}")
    print(f"kernel_silent : {live.is_silent()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
