#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_live_lock.py — 真机互斥锁的判据测试。

按项目判据写：**每条正向断言都配一条反向对照**，并且专门测「判据自身会不会坏死」——
- 恒绿形态：锁根本拦不住第二个人（第 2 组）；
- 恒红形态：锁过度回收，把活着的持有者抢掉（第 4 组）。
两边都钉住，这把锁才算真的在守。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import live_lock as live_lock_mod  # noqa: E402
from live_lock import (  # noqa: E402
    LiveLock,
    LiveLockBusy,
    lock_path_for,
    pid_alive,
    read_lock,
)

# 保留一份未被 monkeypatch 的真实探测函数引用，供 test_16 用。
_real_sc2_pid_on_port = live_lock_mod.sc2_pid_on_port

RESOURCE = "pytest-sc2-live"


class LiveLockTestBase(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self._prev = os.environ.get("SC2_LIVE_LOCK_DIR")
        os.environ["SC2_LIVE_LOCK_DIR"] = self._tmp.name
        # acquire() 会把 token 播进环境（restart_guard 的"自己人"通道）。
        # 不清理会造成**跨用例污染**：上一个用例遗留的 token 可能让
        # 下一个用例的"他人活锁必须被拒"莫名放行 —— 判据被自己的副作用弄成恒绿。
        self._prev_token = os.environ.pop(live_lock_mod.TOKEN_ENV, None)

    def tearDown(self) -> None:
        if self._prev is None:
            os.environ.pop("SC2_LIVE_LOCK_DIR", None)
        else:
            os.environ["SC2_LIVE_LOCK_DIR"] = self._prev
        os.environ.pop(live_lock_mod.TOKEN_ENV, None)
        if self._prev_token is not None:
            os.environ[live_lock_mod.TOKEN_ENV] = self._prev_token
        self._tmp.cleanup()


class TestAcquireRelease(LiveLockTestBase):
    def test_1_roundtrip_creates_and_removes_lock(self) -> None:
        lock = LiveLock(holder="probe-a", resource=RESOURCE)
        path = lock_path_for(RESOURCE)
        self.assertFalse(path.exists(), "起始必须无锁")
        with lock:
            self.assertTrue(path.exists(), "持锁期间锁文件必须在")
            info = read_lock(RESOURCE)
            self.assertIsNotNone(info)
            assert info is not None
            self.assertEqual(info["holder"], "probe-a")
            self.assertEqual(info["pid"], os.getpid())
            self.assertEqual(info["token"], lock.token)
        self.assertFalse(path.exists(), "退出上下文后锁必须清掉")

    def test_2_second_acquirer_is_blocked(self) -> None:
        """核心判据：第二个人必须抢不到。

        这条要是过不了，这把锁就是「恒绿判据」——看着有、实际不拦人。
        """
        first = LiveLock(holder="probe-a", resource=RESOURCE).acquire()
        try:
            second = LiveLock(holder="probe-b", resource=RESOURCE, timeout=0.0)
            with self.assertRaises(LiveLockBusy) as ctx:
                second.acquire()
            self.assertEqual(ctx.exception.holder_info.get("holder"), "probe-a")
            self.assertIn("probe-a", str(ctx.exception))
            self.assertFalse(second.acquired)
        finally:
            first.release()

        # 反向对照：前者释放之后，同一个 second 必须能拿到 —— 证明上面的失败
        # 是「被占用」造成的，而不是 second 本身坏了（否则等于用崩溃冒充判据）。
        second_again = LiveLock(holder="probe-b", resource=RESOURCE, timeout=0.0)
        second_again.acquire()
        self.assertTrue(second_again.acquired)
        second_again.release()

    def test_3_blocking_acquire_times_out_without_hanging(self) -> None:
        held = LiveLock(holder="long-runner", resource=RESOURCE).acquire()
        try:
            waiter = LiveLock(holder="waiter", resource=RESOURCE,
                              timeout=0.6, poll=0.1)
            started = time.time()
            with self.assertRaises(LiveLockBusy):
                waiter.acquire()
            elapsed = time.time() - started
            self.assertGreaterEqual(elapsed, 0.5, "必须真的等够 timeout")
            self.assertLess(elapsed, 8.0, "不能挂死")
        finally:
            held.release()


class TestStaleReclaim(LiveLockTestBase):
    def _write_raw_lock(self, **overrides: object) -> Path:
        path = lock_path_for(RESOURCE)
        payload = {
            "schemaVersion": 1, "resource": RESOURCE, "holder": "ghost",
            "token": "deadbeef", "pid": 999_999_999, "port": 5000,
            "acquired_at": time.time(),
        }
        payload.update(overrides)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_4_live_holder_within_max_age_is_NOT_reclaimed(self) -> None:
        """反向对照（防「恒红/过度回收」）：持有者还活着且没超时，绝不能抢。

        回收逻辑最容易写飘 —— 一旦活人也被抢，这把锁就从「守卫」变成「制造并发」。
        """
        self._write_raw_lock(pid=os.getpid(), holder="alive-holder",
                             acquired_at=time.time())
        challenger = LiveLock(holder="challenger", resource=RESOURCE,
                              timeout=0.0, max_age=3600.0)
        with self.assertRaises(LiveLockBusy):
            challenger.acquire()
        self.assertIsNone(challenger.reclaimed)
        info = read_lock(RESOURCE)
        assert info is not None
        self.assertEqual(info["holder"], "alive-holder", "活着的持有者必须原样保留")

    def test_5_dead_holder_is_reclaimed(self) -> None:
        self._write_raw_lock(pid=999_999_999, holder="ghost")
        taker = LiveLock(holder="taker", resource=RESOURCE, timeout=0.0)
        taker.acquire()
        try:
            self.assertTrue(taker.acquired)
            self.assertIsNotNone(taker.reclaimed)
            assert taker.reclaimed is not None
            self.assertIn("not_alive", taker.reclaimed)
        finally:
            taker.release()

    def test_6_exceeded_max_age_is_reclaimed_even_if_alive(self) -> None:
        self._write_raw_lock(pid=os.getpid(), holder="zombie-longrunner",
                             acquired_at=time.time() - 10_000)
        taker = LiveLock(holder="taker", resource=RESOURCE, timeout=0.0,
                         max_age=60.0)
        taker.acquire()
        try:
            self.assertIsNotNone(taker.reclaimed)
            assert taker.reclaimed is not None
            self.assertIn("exceeded_max_age", taker.reclaimed)
        finally:
            taker.release()

    def test_7_corrupt_lock_file_is_reclaimed(self) -> None:
        lock_path_for(RESOURCE).write_text("{not json at all", encoding="utf-8")
        taker = LiveLock(holder="taker", resource=RESOURCE, timeout=0.0)
        taker.acquire()
        try:
            self.assertEqual(taker.reclaimed, "corrupt_lock_file")
        finally:
            taker.release()


class TestOwnershipSafety(LiveLockTestBase):
    def test_8_release_never_deletes_someone_elses_lock(self) -> None:
        """经典 bug 防线：A 的锁被判定过期由 B 接管后，A 收尾不能删掉 B 的锁。"""
        victim = LiveLock(holder="victim", resource=RESOURCE).acquire()
        self.assertTrue(victim.acquired)

        # 模拟「victim 被判定死亡、B 回收重建」。
        lock_path_for(RESOURCE).unlink()
        usurper = LiveLock(holder="usurper", resource=RESOURCE).acquire()
        self.assertTrue(usurper.acquired)

        removed = victim.release()           # A 事后收尾
        self.assertFalse(removed, "token 不匹配时 release 必须返回 False")
        info = read_lock(RESOURCE)
        assert info is not None
        self.assertEqual(info["holder"], "usurper", "B 的锁必须完好无损")
        self.assertEqual(info["token"], usurper.token)
        usurper.release()

    def test_9_release_without_acquire_is_noop(self) -> None:
        other = LiveLock(holder="holder", resource=RESOURCE).acquire()
        try:
            never = LiveLock(holder="never-acquired", resource=RESOURCE)
            self.assertFalse(never.release())
            self.assertTrue(lock_path_for(RESOURCE).exists())
        finally:
            other.release()


class TestPidAlive(unittest.TestCase):
    def test_10_pid_alive_does_not_kill_the_process(self) -> None:
        """Windows 上 ``os.kill(pid, 0)`` 是 TerminateProcess —— 会把进程杀掉。

        这条测试就是钉死「探活不能有副作用」：连查 5 次之后目标必须还活着。
        """
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(6)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            for _ in range(5):
                self.assertTrue(pid_alive(child.pid), "存活进程必须判为活")
            self.assertIsNone(child.poll(), "探活之后子进程必须还活着（无副作用）")
        finally:
            child.kill()
            child.wait(timeout=10)

        # 反向对照：进程死了之后必须判为死，否则上面的 True 只是恒真。
        deadline = time.time() + 10
        while time.time() < deadline and pid_alive(child.pid):
            time.sleep(0.1)
        self.assertFalse(pid_alive(child.pid), "已退出的进程必须判为死")

    def test_11_impossible_pid_is_not_alive(self) -> None:
        self.assertFalse(pid_alive(999_999_999))
        self.assertFalse(pid_alive(-1))
        self.assertFalse(pid_alive(0))


class TestEnvDrift(LiveLockTestBase):
    """SC2 被别人重启时，持锁者必须**知道自己被打断了**。

    锁能挡住并发访问，挡不住并发的环境重置。这组测试钉住的是：
    漂移要能被发现（否则静默产出半截数据），且**没漂移时绝不能误报**
    （否则就成了恒红判据，每次 run 都说环境变了 = 等于没判据）。
    """

    def test_12_no_drift_when_pid_unchanged(self) -> None:
        """反向对照（防恒红）：PID 没变必须返回 None。"""
        lock = LiveLock(holder="probe-drift", resource=RESOURCE, port=59998)
        with lock:
            lock.sc2_pid_at_acquire = 12345
            live_lock_mod.sc2_pid_on_port = lambda _port: 12345
            self.assertIsNone(lock.env_drift(), "PID 未变时不得报漂移")

    def test_13_drift_detected_when_pid_changed(self) -> None:
        lock = LiveLock(holder="probe-drift", resource=RESOURCE, port=59998)
        with lock:
            lock.sc2_pid_at_acquire = 12345
            live_lock_mod.sc2_pid_on_port = lambda _port: 67890
            drift = lock.env_drift()
            self.assertIsNotNone(drift, "PID 变了必须报漂移")
            assert drift is not None
            self.assertEqual(drift["kind"], "sc2_restarted")
            self.assertEqual(drift["sc2_pid_at_acquire"], 12345)
            self.assertEqual(drift["sc2_pid_now"], 67890)

    def test_14_no_drift_when_baseline_unknown(self) -> None:
        """取锁时没探到 PID（探测失败/端口没人）→ 无基线，一律不判漂移。

        宁可漏报也不可误报：一个假的"环境变了"会让所有 run 的结论都不可信。
        """
        lock = LiveLock(holder="probe-drift", resource=RESOURCE, port=59998)
        with lock:
            lock.sc2_pid_at_acquire = None
            live_lock_mod.sc2_pid_on_port = lambda _port: 67890
            self.assertIsNone(lock.env_drift(), "无基线时不得报漂移")

    def test_15_sc2_gone_is_drift_only_if_holder_dead(self) -> None:
        """端口没人 LISTEN 了：只有当原 SC2 进程确实已死才算漂移。"""
        lock = LiveLock(holder="probe-drift", resource=RESOURCE, port=59998)
        with lock:
            lock.sc2_pid_at_acquire = 999_999_999      # 必然不存在的 pid
            live_lock_mod.sc2_pid_on_port = lambda _port: None
            drift = lock.env_drift()
            self.assertIsNotNone(drift)
            assert drift is not None
            self.assertEqual(drift["kind"], "sc2_gone")

            # 反向对照：原进程还活着（用自己的 pid）→ 只是探测不到，不算漂移
            lock.sc2_pid_at_acquire = os.getpid()
            self.assertIsNone(lock.env_drift(),
                              "原进程还活着时端口探不到不算漂移")

    def test_16_real_port_probe_returns_none_for_dead_port(self) -> None:
        """真实探测（不 monkeypatch）：没人监听的端口必须返回 None，且不抛。"""
        self.assertIsNone(_real_sc2_pid_on_port(59997))

    def setUp(self) -> None:
        super().setUp()
        self._orig_probe = live_lock_mod.sc2_pid_on_port

    def tearDown(self) -> None:
        live_lock_mod.sc2_pid_on_port = self._orig_probe
        super().tearDown()


class TestRestartGuard(LiveLockTestBase):
    """**预防层**判据：谁可以重启 SC2。

    背景：锁只挡住「同时访问」。2026-08-10 03:xx 一次 3v6 训练跑到一半被另一个
    会话重启 SC2 打断（PID 36916→33828），产出半截报告 —— 那个会话**全程守规矩**，
    它只是拿不到锁就转头重启了环境。检测层（env_drift）事后能发现，预防层才能拦住。

    这组测试同时钉死判据的两种坏死形态：
    - **恒绿**（test_18/25）：他人正在飞时必须真的拒绝，否则这层等于没写；
    - **恒红**（test_19/20）：持有者自己重启必须放行，否则没人用得了，最终被绕过。

    隔离策略：用 ``SC2_LIVE_LOCK_SCAN_PORTS`` 把端口扫描收窄到确定性端口
    （待测机上有并行会话在 :5974 飞时，单测也不会被它的真实连接误伤）；
    同时把 :func:`api_clients_on_port` 默认钉成「无人连接」，需要假连接时由
    具体用例自行覆盖（test_26）。这样单测完全不需要真机干净。
    """

    _SCAN_PORT = 59999

    def setUp(self) -> None:
        super().setUp()
        self._prev_scan = os.environ.get("SC2_LIVE_LOCK_SCAN_PORTS")
        os.environ["SC2_LIVE_LOCK_SCAN_PORTS"] = str(self._SCAN_PORT)
        self._real_api_clients = live_lock_mod.api_clients_on_port
        live_lock_mod.api_clients_on_port = lambda *a, **k: []  # type: ignore[assignment]

    def tearDown(self) -> None:
        live_lock_mod.api_clients_on_port = self._real_api_clients  # type: ignore[assignment]
        if self._prev_scan is None:
            os.environ.pop("SC2_LIVE_LOCK_SCAN_PORTS", None)
        else:
            os.environ["SC2_LIVE_LOCK_SCAN_PORTS"] = self._prev_scan
        super().tearDown()

    def _write_raw_lock(self, **overrides: object) -> None:
        payload = {
            "schemaVersion": 2, "resource": RESOURCE, "holder": "ghost",
            "token": "deadbeef", "pid": 999_999_999, "port": 5000,
            "acquired_at": time.time(),
        }
        payload.update(overrides)
        lock_path_for(RESOURCE).write_text(json.dumps(payload), encoding="utf-8")

    def _spawn_live_foreign(self) -> int:
        """起一个真实存活、且 PID 不等于自己的进程，充当"别人正在飞"。"""
        proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(proc.kill)
        self.assertNotEqual(proc.pid, os.getpid())
        return proc.pid

    # ------------------------------------------------------------ 放行侧
    def test_17_no_lock_allows_restart(self) -> None:
        verdict = live_lock_mod.restart_guard(resource=RESOURCE, actor="t17")
        self.assertTrue(verdict["allowed"])
        self.assertEqual(verdict["reason"], "no_lock")
        self.assertIsNone(verdict["holder"])

    def test_19_self_holder_by_pid_is_allowed(self) -> None:
        """防恒红：持锁者本人重启自己的 SC2 必须放行。"""
        self._write_raw_lock(pid=os.getpid(), holder="me")
        verdict = live_lock_mod.restart_guard(resource=RESOURCE, actor="t19")
        self.assertTrue(verdict["allowed"], "持有者自己被自己挡住 = 预防层恒红")
        self.assertEqual(verdict["reason"], "self_is_holder")

    def test_20_self_holder_via_env_token_is_allowed(self) -> None:
        """防恒红（跨进程）：子进程靠继承的 token 证明"我就是持有者"。"""
        foreign = self._spawn_live_foreign()
        self._write_raw_lock(pid=foreign, holder="parent-probe", token="tok-abc")
        # 没 token 时必须拒（先证明这个用例不是同义反复）
        self.assertFalse(
            live_lock_mod.restart_guard(resource=RESOURCE)["allowed"],
            "没有 token 就应当被拒，否则下面的放行不能归因于 token")
        os.environ[live_lock_mod.TOKEN_ENV] = "tok-abc"
        verdict = live_lock_mod.restart_guard(resource=RESOURCE, actor="t20")
        self.assertTrue(verdict["allowed"])
        self.assertEqual(verdict["reason"], "self_is_holder_via_env")

    def test_21_dead_holder_allows_restart(self) -> None:
        self._write_raw_lock(pid=999_999_999, holder="ghost")
        verdict = live_lock_mod.restart_guard(resource=RESOURCE, actor="t21")
        self.assertTrue(verdict["allowed"])
        self.assertIn("not_alive", verdict["reason"])

    def test_22_expired_holder_allows_restart(self) -> None:
        """与取锁回收同口径：能被回收的锁，就不该再挡重启（否则自相矛盾）。"""
        foreign = self._spawn_live_foreign()
        self._write_raw_lock(pid=foreign, holder="zombie",
                             acquired_at=time.time() - 10_000)
        verdict = live_lock_mod.restart_guard(resource=RESOURCE, actor="t22",
                                              max_age=60.0)
        self.assertTrue(verdict["allowed"])
        self.assertIn("exceeded_max_age", verdict["reason"])

    def test_23_force_allows_but_still_reports_holder(self) -> None:
        """强制 ≠ 假装没人：holder 必须照常出现在裁决里，留下痕迹。"""
        foreign = self._spawn_live_foreign()
        self._write_raw_lock(pid=foreign, holder="busy-trainer")
        verdict = live_lock_mod.restart_guard(resource=RESOURCE, actor="t23",
                                              force=True)
        self.assertTrue(verdict["allowed"])
        self.assertEqual(verdict["reason"], "forced")
        self.assertIsNotNone(verdict["holder"])
        assert verdict["holder"] is not None
        self.assertEqual(verdict["holder"]["holder"], "busy-trainer")

    # ------------------------------------------------------------ 拒绝侧
    def test_18_live_foreign_holder_blocks_restart(self) -> None:
        """核心正向判据（防恒绿）：别人正在飞，必须拒绝重启。"""
        foreign = self._spawn_live_foreign()
        self._write_raw_lock(pid=foreign, holder="train_route_b",
                             note="3v6 hard run")
        verdict = live_lock_mod.restart_guard(resource=RESOURCE, actor="t18")
        self.assertFalse(verdict["allowed"], "活着的持有者没挡住 = 预防层恒绿")
        self.assertEqual(verdict["reason"], "blocked_by_live_holder")
        assert verdict["holder"] is not None
        self.assertEqual(verdict["holder"]["holder"], "train_route_b")
        self.assertIn("train_route_b", verdict["message"])

    def test_24_assert_restart_allowed_raises_with_holder(self) -> None:
        foreign = self._spawn_live_foreign()
        self._write_raw_lock(pid=foreign, holder="tier100_live_probe")
        with self.assertRaises(live_lock_mod.LiveRestartBlocked) as ctx:
            live_lock_mod.assert_restart_allowed(resource=RESOURCE, actor="t24")
        self.assertEqual(ctx.exception.holder_info.get("holder"),
                         "tier100_live_probe")
        # 反向对照：同一调用在无锁时不抛
        lock_path_for(RESOURCE).unlink()
        live_lock_mod.assert_restart_allowed(resource=RESOURCE, actor="t24")

    def test_26_foreign_connection_blocks_restart(self) -> None:
        """核心正向判据（防恒绿，覆盖「自愿登记制」漏洞）：

        无人持锁（对锁体系隐形），但 ``port`` 上有他人 ESTABLISHED 连接
        （真实 netstat 会探到、run_live_rl 之类没接锁的入口在飞）→ 必须拒绝重启。
        这正是对 3v6 事故「A 没接锁、B 拿到空锁目录就重启」的补丁。

        用 monkeypatch 把 ``api_clients_on_port`` 换成「返回一条假连接」，
        断言 guard 拒绝；同时断言「返回空列表」时放行（排掉同义反复）。
        """
        from live_lock import api_clients_on_port as _real

        fake_conn = [{"pid": 99999, "local": "127.0.0.1:5000",
                      "remote": "127.0.0.1:51832"}]
        live_lock_mod.api_clients_on_port = lambda *a, **k: fake_conn  # type: ignore[assignment]
        try:
            verdict = live_lock_mod.restart_guard(resource=RESOURCE, actor="t26")
            self.assertFalse(verdict["allowed"],
                             "无锁但端口有他人连接仍被放行 = 预防层恒绿")
            self.assertEqual(verdict["reason"], "blocked_by_active_connection")
            self.assertIn("99999", verdict["message"])

            # 反向对照：同样的无锁状态，但端口空空如也 → 放行。
            live_lock_mod.api_clients_on_port = lambda *a, **k: []  # type: ignore[assignment]
            verdict_empty = live_lock_mod.restart_guard(resource=RESOURCE, actor="t26")
            self.assertTrue(verdict_empty["allowed"], "端口无连接时不应被拒")
            self.assertEqual(verdict_empty["reason"], "no_lock")
        finally:
            live_lock_mod.api_clients_on_port = _real  # type: ignore[assignment]

    def test_25_cli_can_restart_exit_codes_end_to_end(self) -> None:
        """端到端反向对照：真子进程跑 CLI，两种结局退出码必须不同。

        只测函数不测 CLI 是不够的 —— PowerShell launcher 消费的是**退出码**，
        参数解析写错会让 launcher 永远拿到 0（恒绿）而毫无察觉。
        """
        cli = Path(live_lock_mod.__file__)
        env = dict(os.environ)
        env["SC2_LIVE_LOCK_DIR"] = self._tmp.name
        env.pop(live_lock_mod.TOKEN_ENV, None)
        env["PYTHONIOENCODING"] = "utf-8"

        def run(*extra: str) -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(cli), "can-restart", RESOURCE, *extra],
                capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)

        # 情形 A：无锁 → 0
        allowed = run("--actor", "cli-a")
        self.assertEqual(allowed.returncode, 0, allowed.stdout + allowed.stderr)
        self.assertTrue(json.loads(allowed.stdout)["allowed"])

        # 情形 B：他人活锁 → EXIT_RESTART_BLOCKED
        foreign = self._spawn_live_foreign()
        self._write_raw_lock(pid=foreign, holder="cmlib_matrix")
        blocked = run("--actor", "cli-b")
        self.assertEqual(blocked.returncode, live_lock_mod.EXIT_RESTART_BLOCKED,
                         blocked.stdout + blocked.stderr)
        self.assertFalse(json.loads(blocked.stdout)["allowed"])

        # 情形 C：同一状态 + --force → 0（证明 B 的拒绝来自 guard，不是别的错误）
        forced = run("--actor", "cli-c", "--force")
        self.assertEqual(forced.returncode, 0, forced.stdout + forced.stderr)
        self.assertEqual(json.loads(forced.stdout)["reason"], "forced")


if __name__ == "__main__":
    unittest.main()
