#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""对 test_live_lock.py 做变异检验：把锁打坏，判据必须翻红。

判据 1「校验器自身要有校验器，恒绿等于没有校验器」的落地检查。
只在内存里 monkeypatch，不改磁盘源码。

六个变异体：
  M1 互斥失效  —— _try_create 恒 True（锁根本不拦人）        期望 test_2  FAIL
  M2 过度回收  —— _stale_reason 恒返回原因（活人也抢）        期望 test_4  FAIL
  M3 归属失校  —— release 不比对 token（删别人的锁）          期望 test_8  FAIL
  M4 预防恒绿  —— restart_guard 恒 allowed（谁都能重启）      期望 test_18 FAIL
  M5 预防恒红  —— restart_guard 去掉"自己人"通道              期望 test_19 FAIL
  M6 退出码失效 —— CLI can-restart 恒 return 0                期望 test_25 FAIL
任何一个变异体仍然全绿 = 该判据是摆设。

M4/M5 成对存在是刻意的：只测 M4（恒绿）会漏掉「把所有人都拦住」这种坏法，
那种实现同样"能抓住 M4"，但会让预防层没人敢用，最终被整体绕过 —— 判据的两种
坏死形态必须各有一个变异体盯着。M6 单列是因为 PowerShell launcher 消费的是
**退出码**而不是返回值，参数解析写错时函数层全绿、launcher 层恒绿。

用法：
    python tools/galaxy-vibe/tests/mutation_check_live_lock.py
"""
from __future__ import annotations

import io
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "galaxy-vibe"))
sys.path.insert(0, str(ROOT / "tools" / "galaxy-vibe" / "tests"))

import live_lock  # noqa: E402
import test_live_lock as suite  # noqa: E402

BASELINE_TESTS = (
    "TestAcquireRelease.test_2_second_acquirer_is_blocked",
    "TestStaleReclaim.test_4_live_holder_within_max_age_is_NOT_reclaimed",
    "TestOwnershipSafety.test_8_release_never_deletes_someone_elses_lock",
    "TestRestartGuard.test_18_live_foreign_holder_blocks_restart",
    "TestRestartGuard.test_19_self_holder_by_pid_is_allowed",
    "TestRestartGuard.test_25_cli_can_restart_exit_codes_end_to_end",
    "TestRestartGuard.test_26_foreign_connection_blocks_restart",
)


def run_one(test_id: str) -> bool:
    """跑单条测试，返回是否通过。"""
    loader = unittest.TestLoader()
    tests = loader.loadTestsFromName(test_id, suite)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(tests)
    return result.wasSuccessful()


def main() -> int:
    baseline = {t: run_one(t) for t in BASELINE_TESTS}
    baseline_ok = all(baseline.values())
    print(f"[baseline] {len(BASELINE_TESTS)} 条关键判据未变异时全绿 = {baseline_ok}")
    if not baseline_ok:
        for name, ok in baseline.items():
            if not ok:
                print(f"  BROKEN: {name}")
        print("BASELINE_BROKEN — 变异检验无意义，先修判据本身")
        return 3

    findings: list[tuple[str, str, bool]] = []

    # ---- M1: 互斥失效 ------------------------------------------------------
    orig_try = live_lock.LiveLock._try_create
    live_lock.LiveLock._try_create = lambda self: True          # type: ignore[assignment]
    caught = not run_one("TestAcquireRelease.test_2_second_acquirer_is_blocked")
    live_lock.LiveLock._try_create = orig_try                    # type: ignore[assignment]
    findings.append(("M1 互斥失效(_try_create 恒 True)", "test_2", caught))

    # ---- M2: 过度回收 ------------------------------------------------------
    orig_stale = live_lock._stale_reason
    live_lock._stale_reason = lambda info, max_age, now: "always_stale"  # type: ignore[assignment]
    caught = not run_one(
        "TestStaleReclaim.test_4_live_holder_within_max_age_is_NOT_reclaimed")
    live_lock._stale_reason = orig_stale                         # type: ignore[assignment]
    findings.append(("M2 过度回收(_stale_reason 恒返回原因)", "test_4", caught))

    # ---- M3: 归属失校 ------------------------------------------------------
    orig_release = live_lock.LiveLock.release

    def unsafe_release(self) -> bool:      # 不比对 token，直接删
        if not self.acquired:
            return False
        self.acquired = False
        try:
            self.path.unlink()
        except FileNotFoundError:
            return False
        return True

    live_lock.LiveLock.release = unsafe_release                  # type: ignore[assignment]
    caught = not run_one(
        "TestOwnershipSafety.test_8_release_never_deletes_someone_elses_lock")
    live_lock.LiveLock.release = orig_release                    # type: ignore[assignment]
    findings.append(("M3 归属失校(release 不比对 token)", "test_8", caught))

    # ---- M4: 预防层恒绿 ----------------------------------------------------
    orig_guard = live_lock.restart_guard

    def always_allow(port=5000, resource=None, actor="", max_age=1800.0,
                     force=False):
        return {"resource": resource or "?", "actor": actor, "allowed": True,
                "reason": "no_lock", "holder": None, "message": "mutant"}

    live_lock.restart_guard = always_allow                       # type: ignore[assignment]
    caught = not run_one("TestRestartGuard.test_18_live_foreign_holder_blocks_restart")
    live_lock.restart_guard = orig_guard                         # type: ignore[assignment]
    findings.append(("M4 预防层恒绿(restart_guard 恒 allowed)", "test_18", caught))

    # ---- M5: 预防层恒红 ----------------------------------------------------
    def always_block(port=5000, resource=None, actor="", max_age=1800.0,
                     force=False):
        return {"resource": resource or "?", "actor": actor, "allowed": False,
                "reason": "blocked_by_live_holder", "holder": {"holder": "mutant"},
                "message": "mutant blocks everyone"}

    live_lock.restart_guard = always_block                       # type: ignore[assignment]
    caught = not run_one("TestRestartGuard.test_19_self_holder_by_pid_is_allowed")
    live_lock.restart_guard = orig_guard                         # type: ignore[assignment]
    findings.append(("M5 预防层恒红(restart_guard 恒 blocked)", "test_19", caught))

    # ---- M6: CLI 退出码失效 -------------------------------------------------
    # test_25 起真子进程跑 CLI，内存 monkeypatch 传不过去 —— 必须改磁盘源码，
    # 用「临时写入 + finally 还原」，并校验还原后内容与原始逐字节一致。
    src_path = Path(live_lock.__file__)
    original = src_path.read_text(encoding="utf-8")
    needle = "        return 0 if verdict[\"allowed\"] else EXIT_RESTART_BLOCKED"
    if needle not in original:
        findings.append(("M6 退出码失效(CLI 恒 return 0)", "test_25", False))
        print("  [WARN] M6 锚点未命中，CLI 退出码分支可能已改写 —— 视为逃逸")
    else:
        try:
            src_path.write_text(original.replace(needle, "        return 0"),
                                encoding="utf-8")
            caught = not run_one(
                "TestRestartGuard.test_25_cli_can_restart_exit_codes_end_to_end")
        finally:
            src_path.write_text(original, encoding="utf-8")
        assert src_path.read_text(encoding="utf-8") == original, \
            "源码还原失败 —— 立即人工检查 live_lock.py"
        findings.append(("M6 退出码失效(CLI 恒 return 0)", "test_25", caught))

    # ---- M7: 连接兜底失效 --------------------------------------------------
    # 端口连接兜底（覆盖「没接锁却在飞」的会话）是 M4/M5 之外的第三道防线。
    # 它走的是 _scan_foreign_connections（内部调 api_clients_on_port）。把这个函数
    # 钉成「永远看不到任何人」，模拟 netstat 探测被整体绕过 —— test_26 注入的假连接
    # 会被无视，guard 退化成 no_lock 放行 → test_26 必须 FAIL。
    # （注意：不能只钉 api_clients_on_port，test_26 自己会 monkeypatch 它，
    #  必须钉 restart_guard 真正调用的 _scan_foreign_connections 才生效。）
    orig_scan = live_lock._scan_foreign_connections
    live_lock._scan_foreign_connections = lambda *a, **k: []     # type: ignore[assignment]
    caught = not run_one(
        "TestRestartGuard.test_26_foreign_connection_blocks_restart")
    live_lock._scan_foreign_connections = orig_scan             # type: ignore[assignment]
    findings.append(("M7 连接兜底失效(_scan_foreign_connections 恒空)",
                     "test_26", caught))

    print()
    all_caught = True
    for name, guard, caught in findings:
        mark = "CAUGHT" if caught else "ESCAPED"
        print(f"  [{mark:7s}] {name}  ->  由 {guard} 守住")
        all_caught = all_caught and caught

    print()
    if all_caught:
        print(f"MUTATION_CHECK=PASS  {len(findings)} 个变异体全部被判据抓住，判据非摆设")
        return 0
    print("MUTATION_CHECK=FAIL  有变异体逃逸 —— 对应判据是恒绿摆设，必须重写")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
