#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""live_lock.py — SC2 真机资源互斥锁（跨会话 / 跨进程 / 跨仓库）。

## 为什么需要它

SC2 真机线争抢的是**机器全局**的独占资源，而不是仓库内的东西：

* API 端口 ``127.0.0.1:5000`` —— SC2 只开**一个 websocket 槽**，第二个连接进来
  先来的那个会收到 ``Server disconnected`` / ``sc2_api_websocket_closed:257``；
* ``Documents/StarCraft II/Banks/GalaxyVibe.SC2Bank`` —— Bank RPC 的请求/响应通道，
  两个 Host 同时写 = 互相覆盖，表现为随机 timeout；
* SC2 进程本身 —— launcher 忙锁（任意 SC2 在跑即拒启）。

仓库里至少有 10 个真机入口（``tier100_live_probe`` / ``real_machine_vm_live`` /
``route_b_rl_probe`` / ``run_tier100_clean`` / CMLib ``run_matrix_round10`` / RL 的
``train_route_b`` …），历史上它们**全靠人肉纪律**串行。项目判据早已写明
「写进报告的性质，必须有一个进程在守 —— 纪律有半衰期，检查没有」，
这个模块就是那个进程。

## 设计要点

1. **机器全局路径**：锁放系统临时目录，不放仓库 —— 被争抢的资源本来就是机器级的，
   同一台机上不同 checkout / 不同 AI 会话必须看到同一把锁。
2. **原子创建**：``os.open(O_CREAT|O_EXCL)``，不用"先 exists 再 write"（有 TOCTOU 窗口）。
3. **token 归属校验**：释放时回读 token 比对，**只删自己的锁**。
   否则会踩经典 bug —— A 的锁被判定过期由 B 接管，A 事后收尾把 B 的锁删了。
4. **过期回收要保守**：只有「持有者 PID 已死」或「超过硬上限时长」才回收。
   活着的持有者在上限内一律不碰 —— 否则这把锁就退化成「恒绿判据」，等于没锁。
5. **PID 存活检测绝不用 ``os.kill(pid, 0)``**：在 Windows 上 Python 的 ``os.kill``
   对 ``CTRL_C_EVENT``/``CTRL_BREAK_EVENT`` 以外的任何 sig 都走 ``TerminateProcess``
   —— ``os.kill(pid, 0)`` **会把目标进程杀掉**。这里走 ctypes ``OpenProcess`` +
   ``GetExitCodeProcess``。

## 用法

    from live_lock import LiveLock, LiveLockBusy

    try:
        with LiveLock(holder="tier100_live_probe", port=5000):
            ...  # 独占真机
    except LiveLockBusy as exc:
        print(exc.holder_info)   # 谁占着、占了多久
"""
from __future__ import annotations

import ctypes
import errno
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

__all__ = [
    "LiveLock",
    "LiveLockBusy",
    "LiveRestartBlocked",
    "api_clients_on_port",
    "assert_restart_allowed",
    "lock_dir",
    "lock_path_for",
    "pid_alive",
    "read_lock",
    "restart_guard",
]

# 硬上限：超过这个时长的锁一律视为遗留（进程可能被 taskkill /F 后 PID 立刻被复用，
# 单靠 PID 存活判不出来）。真机探针最长的一档（CMLib 三档矩阵）约 9 分钟，留 3 倍余量。
DEFAULT_MAX_AGE_SEC = 1800.0
DEFAULT_ACQUIRE_TIMEOUT_SEC = 0.0   # 默认不等待，直接失败（fail-fast，让调用方决定排队）
DEFAULT_POLL_SEC = 2.0

_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 退出码约定（各真机入口统一，便于外层脚本区分「为什么没跑」）：
#   3 = 拿不到锁，别人正占着真机       → 我这一轮压根没开始
#   4 = 我被禁止重启 SC2，因为别人在飞 → 我可以继续跑，但不许动环境
EXIT_LOCK_BUSY = 3
EXIT_RESTART_BLOCKED = 4

# 持锁者把自己的 token 播到环境变量里，子进程（含 PowerShell launcher）继承后
# 可以证明「我就是持有者本人」，从而被 restart_guard 放行。
# 没有这一条，预防层会退化成**恒红判据**：持锁的探针自己要重启 SC2 也被自己挡住。
TOKEN_ENV = "SC2_LIVE_LOCK_TOKEN"


class LiveLockBusy(RuntimeError):
    """锁被他人持有且未过期。``holder_info`` 带着持有者的自述。"""

    def __init__(self, message: str, holder_info: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.holder_info = holder_info or {}


class LiveRestartBlocked(RuntimeError):
    """有活着的真机持有者，禁止重启 / 杀死 SC2。

    与 :class:`LiveLockBusy` 的区别：``Busy`` 是"我进不去"，``Blocked`` 是
    "我进得去，但我不许把别人正在用的环境掀了"。两者退出码不同（3 vs 4），
    因为处置方式完全不同 —— 前者应当排队重试，后者应当**放弃重启继续跑**。
    """

    def __init__(self, message: str, holder_info: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.holder_info = holder_info or {}


def lock_dir() -> Path:
    """锁目录。可用 ``SC2_LIVE_LOCK_DIR`` 覆盖（测试用）。"""
    override = os.environ.get("SC2_LIVE_LOCK_DIR")
    base = Path(override) if override else Path(tempfile.gettempdir()) / "sc2-vibe-locks"
    base.mkdir(parents=True, exist_ok=True)
    return base


def lock_path_for(resource: str) -> Path:
    safe = "".join(ch if (ch.isalnum() or ch in "-_.") else "_" for ch in resource)
    return lock_dir() / f"{safe}.lock.json"


def pid_alive(pid: int) -> bool:
    """进程是否存活。

    Windows 走 ``OpenProcess`` + ``GetExitCodeProcess``；POSIX 走 ``os.kill(pid, 0)``。
    **不要**在 Windows 上用 ``os.kill(pid, 0)`` —— 那是 ``TerminateProcess``，会杀进程。
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        kernel32 = ctypes.windll.kernel32          # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(
            _PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                # 拿不到退出码时保守认为还活着，宁可不回收也别误抢。
                return True
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True     # 存在但无权限 —— 活着
    return True


def sc2_pid_on_port(port: int | None) -> int | None:
    """探测哪个进程在 ``port`` 上 LISTEN（即当前这局 SC2 的身份）。

    用途不是"找 SC2"，而是**给这一轮真机 run 的环境拍一张指纹**：
    如果 run 中途这个 PID 变了，说明 SC2 被别人重启过，本轮观测数据已经不连续。
    探测失败一律返回 ``None``（宁可不判，也不要误判成"环境变了"）。
    """
    if not port:
        return None
    try:
        proc = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                              capture_output=True, text=True, timeout=10,
                              errors="replace")
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    needle = f":{int(port)}"
    for line in proc.stdout.splitlines():
        parts = line.split()
        # 形如: TCP  127.0.0.1:5000  0.0.0.0:0  LISTENING  36916
        if len(parts) < 5 or "LISTEN" not in parts[3].upper():
            continue
        if not parts[1].endswith(needle):
            continue
        try:
            return int(parts[4])
        except ValueError:
            continue
    return None


def api_clients_on_port(port: int | None,
                        ignore_pids: set[int] | None = None
                        ) -> list[dict[str, Any]]:
    """谁正连着 ``port`` 上的 SC2 API？（不依赖对方是否取过锁）

    锁只能挡住「接入了 LiveLock 的入口」。可现实里一堆真机入口
    （``run_live_rl.py`` 的 stage6、历史 3v6 训练……）**根本没接锁**，
    它们对锁体系是隐形的 —— 锁目录空空，但 SC2 上真有一个 ws 客户端在飞。
    这种情形光看锁会错误地放行重启，把别人的 run 打断。

    这个函数直接问操作系统：``netstat`` 里有没有 ESTABLISHED 连到 ``port``
    的**他人**进程（排除自己、排除已死的）。有 = 有人在用，不许重启。
    取向是**宁可误报**（漏报会毁数据）：``netstat`` 探不到一律返回空（不判），
    但探到了就当作铁证（哪怕对方其实只是个残留连接，重启也会动它的环境）。

    返回每行 ``{"pid": int, "local": str, "remote": str}``。
    """
    if not port:
        return []
    ignore = set(ignore_pids or set())
    ignore.add(os.getpid())
    try:
        proc = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                              capture_output=True, text=True, timeout=10,
                              errors="replace")
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []
    needle = f":{int(port)}"
    found: dict[int, dict[str, Any]] = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        # 形如: TCP  127.0.0.1:51832  127.0.0.1:5974  ESTABLISHED  4128
        if len(parts) < 5 or "ESTABLISHED" not in parts[3].upper():
            continue
        if not parts[2].endswith(needle):
            continue
        try:
            pid = int(parts[4])
        except ValueError:
            continue
        if pid in ignore or pid <= 0:
            continue
        if not pid_alive(pid):
            continue
        found[pid] = {"pid": pid, "local": parts[1], "remote": parts[2]}
    return list(found.values())


def _candidate_sc2_ports(resource: str, port: int | None) -> set[int]:
    """怕漏掉「别人在别的端口飞」这种跨端口重启杀伤而生成的候选端口集。

    重启 SC2 是**全局**动作 —— 杀掉 SC2 进程会连带着把 :5974 上的 live RL
    一起掀了，哪怕我这一轮只想用 :5000。所以除显式请求的端口外，还要把
    「锁目录里登记过的端口」和「历史上出过事的两个端口 5000/5974」一起扫。

    ``SC2_LIVE_LOCK_SCAN_PORTS`` 环境变量可**覆盖**整套启发式（逗号分隔整数）。
    主要用于测试隔离（让单测不依赖真机上是否有并行会话），也允许生产上把扫描
    收窄到已知端口集。设了就是唯一权威，不再叠加默认 5000/5974。
    """
    override = os.environ.get("SC2_LIVE_LOCK_SCAN_PORTS")
    if override is not None:
        ports: set[int] = set()
        for tok in override.split(","):
            tok = tok.strip()
            if not tok:
                continue
            try:
                ports.add(int(tok))
            except ValueError:
                continue
        if port:
            ports.add(int(port))
        return ports
    ports = {5000, 5974}
    if port:
        ports.add(int(port))
    try:
        for p in lock_dir().glob("*.lock.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            pv = data.get("port")
            if isinstance(pv, int) and pv > 0:
                ports.add(pv)
    except OSError:
        pass
    return ports


def _scan_foreign_connections(port: int | None,
                              resource: str = "") -> list[dict[str, Any]]:
    """跨候选端口扫描他人 ESTABLISHED 连接（``restart_guard`` 的兜底防误杀层）。

    用模块级名字调用 :func:`api_clients_on_port`，以便测试用 monkeypatch 替换。
    """
    ports = _candidate_sc2_ports(resource, port)
    seen: dict[int, dict[str, Any]] = {}
    for p in ports:
        for c in api_clients_on_port(p, ignore_pids={os.getpid()}):
            seen[c["pid"]] = c
    return list(seen.values())


def read_lock(resource: str) -> dict[str, Any] | None:
    """读当前锁内容；文件不存在或内容损坏都返回 ``None``（损坏视为可回收）。"""
    path = lock_path_for(resource)
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"_corrupt": True, "pid": -1, "acquired_at": 0.0}
    return data if isinstance(data, dict) else {"_corrupt": True, "pid": -1,
                                                "acquired_at": 0.0}


def _stale_reason(info: dict[str, Any], max_age: float,
                  now: float) -> str | None:
    """锁是否可回收；可回收返回原因字符串，否则返回 ``None``。

    判定顺序很重要：先看内容是否可信（损坏 → 回收），再看持有者是否还活着，
    最后才看时长。把「时长」放最后是刻意的 —— 一个还活着、正在跑长任务的持有者
    不该仅因为跑得久就被抢走。
    """
    if info.get("_corrupt"):
        return "corrupt_lock_file"
    pid = int(info.get("pid", -1) or -1)
    if not pid_alive(pid):
        return f"holder_pid_{pid}_not_alive"
    age = now - float(info.get("acquired_at", 0.0) or 0.0)
    if age > max_age:
        return f"exceeded_max_age_{max_age:.0f}s_age_{age:.0f}s"
    return None


class LiveLock:
    """SC2 真机独占锁。既可当上下文管理器，也可手动 ``acquire`` / ``release``。"""

    def __init__(self, holder: str, port: int | None = 5000,
                 resource: str | None = None,
                 timeout: float = DEFAULT_ACQUIRE_TIMEOUT_SEC,
                 poll: float = DEFAULT_POLL_SEC,
                 max_age: float = DEFAULT_MAX_AGE_SEC,
                 note: str = "") -> None:
        self.holder = holder
        self.port = port
        self.resource = resource or (f"sc2-port-{port}" if port else "sc2-live")
        self.timeout = float(timeout)
        self.poll = max(0.05, float(poll))
        self.max_age = float(max_age)
        self.note = note
        self.token = uuid.uuid4().hex
        self.path = lock_path_for(self.resource)
        self.acquired = False
        self.reclaimed: str | None = None
        self.sc2_pid_at_acquire: int | None = None

    # ------------------------------------------------------------------ 内部
    def _payload(self) -> dict[str, Any]:
        return {
            "schemaVersion": 2,
            "resource": self.resource,
            "holder": self.holder,
            "token": self.token,
            "pid": os.getpid(),
            "host": socket.gethostname(),
            "port": self.port,
            "cwd": os.getcwd(),
            "argv": sys.argv[:8],
            "note": self.note,
            "sc2_pid": self.sc2_pid_at_acquire,
            "acquired_at": time.time(),
            "acquired_at_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

    # -------------------------------------------------------- 环境指纹校验
    def env_drift(self) -> dict[str, Any] | None:
        """SC2 进程是否在本轮 run 期间被换掉了？没漂移返回 ``None``。

        这是 §"锁管不到重启"的补丁：锁能挡住并发**访问**，挡不住别人
        并发地把 SC2 **重启**掉。至少要让被打断的一方**明确知道自己被打断了**，
        而不是安静地产出一份半截报告。

        保守原则：只有"取锁时探到过 PID"且"现在探到的 PID 不同"才判漂移。
        任一侧探测失败（None）都不判 —— 宁可漏报，不可误报。
        """
        before = self.sc2_pid_at_acquire
        if before is None:
            return None
        now = sc2_pid_on_port(self.port)
        if now is None:
            # 端口上已经没人 LISTEN：SC2 没了，这是最硬的漂移信号。
            if not pid_alive(before):
                return {"kind": "sc2_gone", "sc2_pid_at_acquire": before,
                        "sc2_pid_now": None}
            return None
        if now != before:
            return {"kind": "sc2_restarted", "sc2_pid_at_acquire": before,
                    "sc2_pid_now": now}
        return None

    def _try_create(self) -> bool:
        """原子建锁。已存在返回 ``False``，不抛。"""
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
        except OSError as exc:
            if exc.errno == errno.EEXIST:
                return False
            raise
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(self._payload(), handle, ensure_ascii=False, indent=2)
        return True

    # ------------------------------------------------------------------ 对外
    def acquire(self) -> "LiveLock":
        deadline = time.time() + self.timeout
        # 建锁前先拍环境指纹，写进锁内容里，供 env_drift() 事后比对。
        self.sc2_pid_at_acquire = sc2_pid_on_port(self.port)
        while True:
            if self._try_create():
                self.acquired = True
                # 把 token 播给子进程：持锁者自己（及其拉起的 launcher）重启 SC2 是合法的。
                os.environ[TOKEN_ENV] = self.token
                return self

            info = read_lock(self.resource) or {}
            reason = _stale_reason(info, self.max_age, time.time())
            if reason is not None:
                # 回收：删掉遗留锁再抢。删除与重建之间有窗口，抢不到就正常走等待分支。
                try:
                    self.path.unlink()
                except FileNotFoundError:
                    pass
                if self._try_create():
                    self.acquired = True
                    self.reclaimed = reason
                    os.environ[TOKEN_ENV] = self.token
                    return self
                continue

            if time.time() >= deadline:
                held = time.time() - float(info.get("acquired_at", 0.0) or 0.0)
                raise LiveLockBusy(
                    f"SC2 真机资源 {self.resource} 被 "
                    f"{info.get('holder', '?')}(pid={info.get('pid', '?')}) 持有 "
                    f"{held:.0f}s；本次 holder={self.holder}。"
                    f"等待请加 --lock-timeout，强制请先确认对方确实已死。",
                    holder_info=info)
            time.sleep(self.poll)

    def release(self) -> bool:
        """释放。**只删自己的锁**（token 比对），返回是否真的删掉了。"""
        if not self.acquired:
            return False
        self.acquired = False
        if os.environ.get(TOKEN_ENV) == self.token:
            os.environ.pop(TOKEN_ENV, None)
        info = read_lock(self.resource)
        if not info or info.get("token") != self.token:
            # 我们的锁已经被别人回收并重建 —— 绝不能删，那是别人的锁。
            return False
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        return True

    def __enter__(self) -> "LiveLock":
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()


def restart_guard(port: int | None = 5000, resource: str | None = None,
                  actor: str = "", max_age: float = DEFAULT_MAX_AGE_SEC,
                  force: bool = False) -> dict[str, Any]:
    """**预防层**：现在可以重启 / 杀掉 SC2 吗？

    ## 为什么需要它（而不是只有 LiveLock）

    锁解决的是「两个会话同时**用**真机」。它解决不了「A 拿着锁在跑，B 拿不到锁，
    B 转头把 SC2 重启了」—— B 全程守规矩没碰锁，却照样把 A 的 run 打断。
    2026-08-10 03:xx 的 3v6 训练就是这么断的（PID 36916→33828），当时只补了
    **检测层** :meth:`LiveLock.env_drift`（让被打断的一方知道自己被打断了），
    预防层一直缺着。这个函数就是预防层。

    ## 判定顺序（刻意如此）

    1. ``force`` → 放行，但**仍然把持有者报出来**（强制不等于假装没人）；
    2. 无锁 → 放行；
    3. **我就是持有者**（PID 相同，或环境变量 token 相同）→ 放行。
       这一条是防**恒红**的：持锁者重启自己的 SC2 完全合法，
       挡住它等于让整个预防层没法用，最后被人整体绕过；
    4. 持有者已死 / 已超期 → 放行（复用 ``_stale_reason``，与取锁同一套口径，
       避免出现「锁能被回收，但重启被拒」这种自相矛盾的状态）；
    5. 其余 → **拒绝**。

    ## 端口连接兜底（覆盖「自愿登记制」漏洞 + 跨端口杀伤）

    锁只认「接入了 LiveLock 的入口」。但现实里一堆真机入口
    （``run_live_rl.py`` 的 stage6、历史 3v6 训练……）**根本没接锁**，
    它们对锁体系是隐形的 —— 锁目录空空，但 SC2 上真有一个 ws 客户端在飞。
    于是无论第 2 步（无锁）还是第 5 步（有他人活锁），都额外调
    :func:`api_clients_on_port` 直接问端口：任何候选端口（含请求的端口、
    历史上出过事的 5000/5974、锁目录登记过的端口）上只要有**他人** ESTABLISHED
    连接，就拒绝重启。取向是**宁可误报**（漏报会毁掉别人的训练数据）。

    返回 ``{"allowed": bool, "reason": str, "holder": {...}|None, "message": str}``。
    """
    res = resource or (f"sc2-port-{port}" if port else "sc2-live")
    info = read_lock(res)
    holder = None
    if info:
        holder = {k: info.get(k) for k in
                  ("holder", "pid", "port", "note", "cwd", "acquired_at_iso")}
        holder["age_sec"] = round(
            time.time() - float(info.get("acquired_at", 0.0) or 0.0), 1)

    def _verdict(allowed: bool, reason: str, message: str = "") -> dict[str, Any]:
        return {"resource": res, "actor": actor, "allowed": allowed,
                "reason": reason, "holder": holder,
                "message": message or reason}

    if force:
        return _verdict(True, "forced",
                        "强制放行（--force）；如有持有者见 holder 字段")
    if not info:
        # 无人持锁，但别人可能根本没接锁却在飞（自愿登记制的覆盖漏洞）。
        # 直接问端口：任何候选端口上有他人 ESTABLISHED 连接都不许重启。
        # 含跨端口杀伤（我这一轮只用 :5000，但 :5974 上有别人在飞）。
        blockers = _scan_foreign_connections(port, res)
        if blockers:
            return _verdict(
                False, "blocked_by_active_connection",
                f"禁止重启 SC2：端口探测到 {len(blockers)} 个他人活动连接"
                f"（如 pid={blockers[0].get('pid')}）。重启会打断对方正在采集的"
                f"观测数据（历史事故：3v6 训练被中途重启）。"
                f"确认对方确实已死再加 --force。")
        return _verdict(True, "no_lock", "无人持有真机锁且无活动连接，可以重启")

    if int(info.get("pid", -1) or -1) == os.getpid():
        return _verdict(True, "self_is_holder", "我自己就是持有者，可以重启")
    env_token = os.environ.get(TOKEN_ENV)
    if env_token and env_token == info.get("token"):
        return _verdict(True, "self_is_holder_via_env",
                        "持有者 token 经环境变量继承，可以重启")

    stale = _stale_reason(info, max_age, time.time())
    if stale is not None:
        return _verdict(True, f"holder_stale:{stale}",
                        f"持有者锁已可回收（{stale}），可以重启")

    # 双保险：活着的他人持锁。再扫端口，覆盖「锁是别人留的、但还有第三个
    # 会话在飞」以及「别人在别的端口（如 5974）飞、我这一轮只想用 5000」的跨端口杀伤。
    blockers = _scan_foreign_connections(port, res)
    if blockers:
        return _verdict(
            False, "blocked_by_active_connection",
            f"禁止重启 SC2：真机资源 {res} 正被 "
            f"{info.get('holder', '?')}(pid={info.get('pid', '?')}) 持有，"
            f"且端口另有 {len(blockers)} 个活动连接"
            f"（如 pid={blockers[0].get('pid')}）。"
            f"重启会连带着掀掉这些会话（历史事故：3v6 训练被中途重启）。"
            f"确认对方确实已死再加 --force。")

    age = holder["age_sec"] if holder else 0.0
    return _verdict(
        False, "blocked_by_live_holder",
        f"禁止重启 SC2：真机资源 {res} 正被 "
        f"{info.get('holder', '?')}(pid={info.get('pid', '?')}) 持有 {age:.0f}s。"
        f"本次 actor={actor or '?'}。重启会打断对方正在采集的观测数据"
        f"（历史事故：3v6 训练被中途重启，产出半截报告）。"
        f"确认对方确实已死再加 --force。")


def assert_restart_allowed(port: int | None = 5000, resource: str | None = None,
                           actor: str = "", max_age: float = DEFAULT_MAX_AGE_SEC,
                           force: bool = False) -> dict[str, Any]:
    """:func:`restart_guard` 的抛异常版本。被拒时抛 :class:`LiveRestartBlocked`。"""
    verdict = restart_guard(port=port, resource=resource, actor=actor,
                            max_age=max_age, force=force)
    if not verdict["allowed"]:
        raise LiveRestartBlocked(verdict["message"], holder_info=verdict["holder"])
    return verdict


def add_lock_args(ap: Any) -> Any:
    """给 argparse 解析器挂上标准锁参数（各真机入口统一口径，避免每处手抄）。"""
    ap.add_argument("--lock-timeout", type=float, default=0.0,
                    help="真机资源互斥锁等待上限秒（0=拿不到立刻退出，不排队）")
    ap.add_argument("--no-lock", action="store_true",
                    help="跳过真机互斥锁（仅用于明确知道自己独占时；默认加锁）")
    return ap


def acquire_from_args(args: Any, holder: str, note: str = "",
                      port: int | None = None) -> "LiveLock | None":
    """按 ``add_lock_args`` 注入的参数取锁。

    返回 ``None`` 表示用户显式 ``--no-lock``。拿不到锁时抛 ``LiveLockBusy``，
    由调用方决定怎么把它变成退出码（约定 exit=3）。
    """
    if getattr(args, "no_lock", False):
        return None
    lock = LiveLock(holder=holder,
                    port=int(port if port is not None else getattr(args, "port", 5000)),
                    timeout=float(getattr(args, "lock_timeout", 0.0) or 0.0),
                    note=note).acquire()
    if lock.reclaimed:
        print(f"[live-lock] 回收遗留锁：{lock.reclaimed}", file=sys.stderr)
    return lock


def main(argv: list[str] | None = None) -> int:
    """CLI：查看 / 清理锁 / 询问能否重启。

    ``python live_lock.py status|clear|can-restart [resource] [--force] [--actor X]``

    ``can-restart`` 是给 **PowerShell launcher** 用的预防层入口（那边没法 import
    Python 模块）：退出码 0=允许、4=禁止，stdout 是 JSON 裁决。
    """
    args = list(argv if argv is not None else sys.argv[1:])
    force = "--force" in args
    actor = ""
    if "--actor" in args:
        idx = args.index("--actor")
        if idx + 1 < len(args):
            actor = args[idx + 1]
            del args[idx:idx + 2]
    args = [a for a in args if a != "--force"]
    cmd = args[0] if args else "status"
    resource = args[1] if len(args) > 1 else "sc2-port-5000"
    if cmd == "can-restart":
        verdict = restart_guard(port=None, resource=resource, actor=actor,
                                force=force)
        print(json.dumps(verdict, ensure_ascii=False, indent=2))
        return 0 if verdict["allowed"] else EXIT_RESTART_BLOCKED
    if cmd == "status":
        info = read_lock(resource)
        if not info:
            print(json.dumps({"resource": resource, "locked": False,
                              "path": str(lock_path_for(resource))},
                             ensure_ascii=False, indent=2))
            return 0
        info = dict(info)
        info["locked"] = True
        info["holder_alive"] = pid_alive(int(info.get("pid", -1) or -1))
        info["age_sec"] = round(time.time()
                                - float(info.get("acquired_at", 0.0) or 0.0), 1)
        info["stale_reason"] = _stale_reason(info, DEFAULT_MAX_AGE_SEC, time.time())
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return 0
    if cmd == "clear":
        path = lock_path_for(resource)
        existed = path.exists()
        if existed:
            path.unlink()
        print(json.dumps({"resource": resource, "cleared": existed},
                         ensure_ascii=False, indent=2))
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
