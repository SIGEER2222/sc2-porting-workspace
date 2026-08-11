#!/usr/bin/env python3
"""test_env_guard.py — 环境哨兵的阳性/阴性对照。

哨兵这类东西最怕「看着在跑其实什么都没检测到」——正则少个空格就永远返回
「一切正常」，而且不会报错，只会静默放行。所以每条判据都必须有阳性对照
（能触发）+ 阴性对照（不误报）。

尤其针对已经踩过的坑：
  - Kernel 活性绝不能把 request/* 算进去（那是 Host 自己写的，自欺）
  - SC2 的 Bank XML 里 `<Key>` 和 `<Value>` 之间隔着换行 + 缩进，
    正则必须容忍任意空白
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import env_guard  # noqa: E402


BANK_KERNEL_ALIVE = """<?xml version="1.0" encoding="utf-8"?>
<Bank version="1">
    <Section name="index">
        <Key name="watchdog_last_seen_poll">
            <Value int="421"/>
        </Key>
    </Section>
</Bank>
"""

# 探针 13:28 那局的真实形态：Host 写满 request，Kernel 一个字节没回
BANK_HOST_ONLY = """<?xml version="1.0" encoding="utf-8"?>
<Bank version="1">
  <Section name="index">
    <Key name="pending_request_id">
      <Value string="f1bf562a56cd" />
    </Key>
  </Section>
  <Section name="request">
    <Key name="95378081ae6c">
      <Value string="{}" />
    </Key>
    <Key name="cacb6870f50e">
      <Value string="{}" />
    </Key>
  </Section>
  <Section name="response">
  </Section>
</Bank>
"""

BANK_WITH_RESPONSE = """<?xml version="1.0" encoding="utf-8"?>
<Bank version="1">
  <Section name="index">
    <Key name="kernel_initialized">
      <Value string="1" />
    </Key>
  </Section>
  <Section name="response">
    <Key name="f1bf562a56cd">
      <Value string="{&quot;ok&quot;:true}" />
    </Key>
  </Section>
</Bank>
"""


def _stage(tmp_path: Path, banks: dict[str, str]) -> None:
    """把假 bank 铺到临时 Banks 目录并让 env_guard 指过去。"""
    root = tmp_path / "Banks"
    root.mkdir(parents=True, exist_ok=True)
    for rel, content in banks.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    env_guard.BANKS_ROOT = root


def test_watchdog_parsed_across_newline(tmp_path):
    """阳性对照：Kernel 写了 watchdog ⇒ 必须判定为「活着」。

    这条就是防「正则少匹配一个换行导致哨兵永远说 silent」的。
    """
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_KERNEL_ALIVE})
    live = env_guard.read_kernel_liveness()
    assert live.watchdog_max == 421
    assert live.is_silent() is False


def test_host_only_bank_is_silent(tmp_path):
    """阴性对照：只有 Host 写的 request，Kernel 侧必须判定为 silent。

    这是 2026-08-09 N2 tier100 那局的真实形态。若把 request 计入活性，
    哨兵会得出「Kernel 活着」的错误结论，从而把根因推向 gen 路由，
    而真相是 MapScript 压根没跑起来 / 实例被挤掉。
    """
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_HOST_ONLY})
    live = env_guard.read_kernel_liveness()
    assert live.response_keys == 0
    assert live.watchdog_max == -1
    assert live.kernel_initialized is False
    assert live.is_silent() is True


def test_response_counts_as_alive(tmp_path):
    _stage(tmp_path, {"GalaxyVibe.SC2Bank": BANK_WITH_RESPONSE})
    live = env_guard.read_kernel_liveness()
    assert live.kernel_initialized is True
    assert live.response_keys == 1
    assert live.is_silent() is False


def test_dot_dirs_skipped(tmp_path):
    """runtime-lab 的备份目录（点开头）必须跳过，否则旧局数据会造成假阳性。"""
    _stage(tmp_path, {
        ".runtime-lab-backup-1786211919/GalaxyVibe.SC2Bank": BANK_KERNEL_ALIVE,
        "14/GalaxyVibe.SC2Bank": BANK_HOST_ONLY,
    })
    live = env_guard.read_kernel_liveness()
    assert live.is_silent() is True, "备份目录里的旧 bank 不得计入本局活性"


def test_guard_trips_on_baseline_pid_exit(tmp_path, monkeypatch):
    """阳性对照：基线 PID 消失 ⇒ env_preempted（13:28:39 真人局挤掉 API 实例那次）。"""
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_HOST_ONLY})
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard()
    guard.baseline()
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {27348})
    got = guard.check()
    assert got is not None
    assert got["verdict"] == "env_preempted"
    # 基线 PID 消失优先于「新实例出现」上报，因为前者才是结果作废的直接原因
    assert got["reason"] == "baseline_sc2_exited"
    assert got["gone_pids"] == [26896]


def test_guard_trips_on_foreign_instance(tmp_path, monkeypatch):
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_HOST_ONLY})
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard()
    guard.baseline()
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896, 27348})
    got = guard.check()
    assert got is not None
    assert got["verdict"] == "env_preempted"
    assert got["reason"] == "foreign_sc2_appeared"


def test_guard_grace_period_prevents_false_kill(tmp_path, monkeypatch):
    """阴性对照：开局 30s 宽限期内 Kernel 静默属正常（地图还在加载），不得误杀。"""
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_HOST_ONLY})
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard()
    guard.baseline()
    assert guard.check() is None, "宽限期内静默不应触发"


def test_guard_reports_kernel_never_registered_after_grace(tmp_path, monkeypatch):
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_HOST_ONLY})
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard(kernel_silence_grace_s=0.0)
    guard.baseline()
    got = guard.check()
    assert got is not None
    assert got["verdict"] == "kernel_never_registered"


def test_guard_reports_lost_midway(tmp_path, monkeypatch):
    """Kernel 先有写入、之后信号冻结 ⇒ kernel_lost_midway（区别于从未注册）。"""
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_KERNEL_ALIVE})
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard(kernel_silence_grace_s=0.0)
    guard.baseline()
    got = guard.check()
    assert got is not None
    assert got["verdict"] == "kernel_lost_midway"


def test_verdict_ok_when_any_call_succeeded(tmp_path, monkeypatch):
    """哪怕 Kernel 侧 bank 读不出信号，只要真有调用成功过就不许判死。"""
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_HOST_ONLY})
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard()
    guard.baseline()
    v = guard.verdict(any_ok=True)
    assert v["verdict"] == "ok"
    assert v["usable_for_acceptance"] is True


def test_verdict_flags_unusable_when_silent(tmp_path, monkeypatch):
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_HOST_ONLY})
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard()
    guard.baseline()
    v = guard.verdict(any_ok=False)
    assert v["verdict"] == "kernel_never_registered"
    assert v["usable_for_acceptance"] is False


def test_degraded_when_process_enum_unavailable(tmp_path, monkeypatch):
    """非 Windows / 枚举失败时必须如实标 degraded，不许假装自己在守护。"""
    _stage(tmp_path, {"14/GalaxyVibe.SC2Bank": BANK_HOST_ONLY})
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: None)
    guard = env_guard.EnvGuard()
    meta = guard.baseline()
    assert meta["degraded"] is True
    assert meta["baseline_pids"] is None
