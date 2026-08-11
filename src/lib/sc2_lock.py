# -*- coding: utf-8 -*-
"""SC2 真机线跨自动化互斥锁 + 外部干扰探测。

## 为什么需要它（2026-08-09 12:12 实测事故）

本仓库有**多个按小时跑的自动化任务**都要独占 SC2：
  · automation-1786148822926（通用库 CMLib 三档真机矩阵）
  · automation-1786147261455 / ...851662（模块四 Runtime VM 真机探针）

12:12 那一轮 CMLib 三档矩阵**内联档与依赖档同时 FAIL**（`Ghost=0 且 bank 无 Magic`），
看起来像通用库真机回归；实际是模块四的自动化在 12:01 "温和退出→强杀→重起 SC2"、
12:16 又重启一次，SC2 全程处在崩溃/重启循环里。矩阵的 SC2 实例被**外部杀掉**，
地图根本没机会跑，于是被分类器当成"真 FAIL"写进了结论。

**假阴性比失败更贵**：它会让人去改一个根本没坏的库。

## 两道防线

1. `SC2Lock`（本文件）：进程间**建议锁**。所有要独占 SC2 的自动化在动手前
   `acquire()`，拿不到就排队/让路。锁文件带 pid + owner + 心跳，进程死了自动过期，
   不会把后续任务永久锁死。
2. `ApiWatch`（本文件）：**单边**外部干扰探测。即使对方没接锁，也能发现
   "跑到一半我的 API 实例被别人杀了"，把这一档判为**瞬态**而不是真结论。
   这条不依赖任何人配合，是兜底。

## 用法

    from sc2_lock import SC2Lock, ApiWatch

    with SC2Lock("cmlib-matrix", wait_minutes=30) as lk:
        if not lk.acquired:
            ...  # 让路
        w = ApiWatch(); w.start()
        run_probe()
        if w.stop().interfered:
            ...  # 判瞬态，重试
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

try:
    from sc2_proc_guard import list_sc2
except Exception:                                    # pragma: no cover
    def list_sc2():                                  # type: ignore
        return []

# 放 TEMP 而非仓库内：跨自动化共享、不进版本控制、重启即清。
LOCK_PATH = Path(os.environ.get("TEMP", "C:/Windows/Temp")) / "sc2-realmachine.lock"

# 心跳超过这个秒数没更新就认为持锁者已死（自动化任务动辄跑十几分钟，给足冗余）。
STALE_SEC = 300
HEARTBEAT_SEC = 30


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    except Exception:
        return True
    return True


def read_lock() -> dict | None:
    try:
        d = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(d, dict) or "pid" not in d:
        return None
    return d


def lock_is_stale(d: dict) -> bool:
    if not _pid_alive(int(d.get("pid", -1))):
        return True
    return (time.time() - float(d.get("beat", 0))) > STALE_SEC


class SC2Lock:
    """跨进程建议锁。`acquired` 为 False 时调用方应当让路，而不是硬闯。"""

    def __init__(self, owner: str, wait_minutes: int = 0):
        self.owner = owner
        self.wait_minutes = wait_minutes
        self.acquired = False
        self._stop = threading.Event()
        self._beat: threading.Thread | None = None

    # -- 内部 -------------------------------------------------------------
    def _write(self) -> None:
        tmp = LOCK_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "pid": os.getpid(), "owner": self.owner,
            "since": time.time(), "beat": time.time(),
        }), encoding="utf-8")
        os.replace(tmp, LOCK_PATH)          # 原子替换，避免读到半截文件

    def _heartbeat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SEC):
            d = read_lock()
            if not d or int(d.get("pid", -1)) != os.getpid():
                return                      # 锁已被别人接管，不再续期
            try:
                self._write()
            except Exception:
                return

    def _try_take(self) -> bool:
        d = read_lock()
        if d is not None:
            if int(d.get("pid", -1)) == os.getpid():
                self._write()
                return True
            if not lock_is_stale(d):
                return False
            print(f"[sc2lock] 发现陈旧锁 (owner={d.get('owner')} "
                  f"pid={d.get('pid')})，接管", flush=True)
        self._write()
        # 双读确认：并发抢锁时后写者胜出，前者读回发现不是自己就退让
        back = read_lock()
        return bool(back and int(back.get("pid", -1)) == os.getpid())

    # -- 对外 -------------------------------------------------------------
    def acquire(self) -> bool:
        deadline = time.time() + max(0, self.wait_minutes) * 60
        announced = False
        while True:
            if self._try_take():
                self.acquired = True
                self._beat = threading.Thread(target=self._heartbeat, daemon=True)
                self._beat.start()
                return True
            if time.time() >= deadline:
                d = read_lock() or {}
                print(f"[sc2lock] 未取得 SC2 独占锁（持有者 owner={d.get('owner')} "
                      f"pid={d.get('pid')}）", flush=True)
                return False
            if not announced:
                d = read_lock() or {}
                print(f"[sc2lock] SC2 被另一自动化占用 (owner={d.get('owner')})，"
                      f"排队最多 {self.wait_minutes} 分钟", flush=True)
                announced = True
            time.sleep(10)

    def release(self) -> None:
        self._stop.set()
        d = read_lock()
        if d and int(d.get("pid", -1)) == os.getpid():
            try:
                LOCK_PATH.unlink()
            except Exception:
                pass
        self.acquired = False

    def __enter__(self) -> "SC2Lock":
        self.acquire()
        return self

    def __exit__(self, *exc) -> None:
        self.release()


class ApiWatch:
    """单边外部干扰探测：跑测试期间盯着 API 实例是否被外人杀掉/真人局是否插进来。

    判据（任一成立即 `interfered=True`）：
      · 曾经看到过 API 实例（`-listen`），随后**归零**，而我们自己没清场；
      · 期间冒出真人对局（用户开始玩了，后续结论一律不可信）。
    """

    def __init__(self, poll_sec: float = 3.0):
        self.poll_sec = poll_sec
        self.interfered = False
        self.reason = ""
        self._stop = threading.Event()
        self._t: threading.Thread | None = None

    def _loop(self) -> None:
        seen_api: set[int] = set()
        while not self._stop.wait(self.poll_sec):
            try:
                rows = list_sc2()
            except Exception:
                continue
            api = {pid for pid, _n, _c, is_api in rows if is_api}
            human = [pid for pid, _n, _c, is_api in rows if not is_api]
            if human:
                self.interfered = True
                self.reason = f"运行期间出现真人对局 PID={human}"
                return
            if seen_api and not api:
                self.interfered = True
                self.reason = (f"运行期间 API 实例 {sorted(seen_api)} 全部消失"
                               f"（疑似被其它自动化强杀）")
                return
            seen_api |= api

    def start(self) -> "ApiWatch":
        self._stop.clear()
        self.interfered = False
        self.reason = ""
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()
        return self

    def stop(self) -> "ApiWatch":
        self._stop.set()
        if self._t:
            self._t.join(timeout=self.poll_sec * 2)
        return self


def cli() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="SC2 真机线互斥锁查看/清理")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--clear", action="store_true", help="强制清掉锁（仅在确认无人持有时用）")
    a = ap.parse_args()
    d = read_lock()
    if a.clear:
        try:
            LOCK_PATH.unlink()
            print("[sc2lock] 已清除")
        except FileNotFoundError:
            print("[sc2lock] 无锁")
        return 0
    if d is None:
        print(f"[sc2lock] 无锁  ({LOCK_PATH})")
    else:
        age = time.time() - float(d.get("since", 0))
        print(f"[sc2lock] owner={d.get('owner')} pid={d.get('pid')} "
              f"持有 {age:.0f}s  陈旧={lock_is_stale(d)}  ({LOCK_PATH})")
    return 0


if __name__ == "__main__":
    raise SystemExit(cli())
