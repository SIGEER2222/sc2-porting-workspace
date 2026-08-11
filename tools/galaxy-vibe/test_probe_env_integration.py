#!/usr/bin/env python3
"""test_probe_env_integration.py — runtime_invoke_probe 与环境哨兵的集成对照。

真机档期长期被真人局占着，`run_live` 的哨兵集成没法靠真跑来验证。但这段逻辑
恰恰是「防止把环境噪声写进验收证据」的最后一道闸，不能只靠肉眼读代码就信。
所以用假 host 在离线把三条路径都走一遍：

  1. 全成功        ⇒ 不中止、env=ok、usable=True
  2. 中途被抢      ⇒ 立刻中止、剩余不执行、usable=False、退出码语义=2
  3. 全失败但环境好 ⇒ 不误报 env_preempted，如实归为代码问题（退出码语义=1）

第 3 条尤其重要：哨兵宁可漏报也不能乱报 —— 一旦它把真故障说成「环境问题」，
就会掩盖真正需要修的 bug，比没有哨兵更糟。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(REPO / "src" / "projects" / "cmre-porting" / "stages" / "26-full-function-invoke"))

import env_guard  # noqa: E402
import runtime_invoke_probe as probe  # noqa: E402


BANK_HOST_ONLY = """<?xml version="1.0" encoding="utf-8"?>
<Bank version="1">
  <Section name="index">
    <Key name="pending_request_id"><Value string="abc" /></Key>
  </Section>
  <Section name="response"></Section>
</Bank>
"""

BANK_KERNEL_ALIVE = """<?xml version="1.0" encoding="utf-8"?>
<Bank version="1">
    <Section name="index">
        <Key name="watchdog_last_seen_poll">
            <Value int="421"/>
        </Key>
    </Section>
</Bank>
"""


class FakeResponse:
    def __init__(self, ok: bool, code: str = "INTERNAL_ERROR", payload=None):
        self.is_ok = ok
        self.error_code = None if ok else code
        self.payload = payload or {}


class FakeHost:
    """按预设脚本回应的假 host；记录实际被调用了几次，用来证明「中止」真的中止了。"""

    def __init__(self, script: list[bool]):
        self.script = list(script)
        self.calls = 0

    def invoke_function(self, function_id, args, timeout=3.0):
        self.calls += 1
        ok = self.script.pop(0) if self.script else False
        return FakeResponse(ok, payload={"v": function_id} if ok else None)

    def close(self):
        pass


def _entries(n: int) -> list[dict]:
    return [{"function_id": f"gen.{i}", "galaxy_name": f"Fn{i}", "args": {}} for i in range(n)]


def _stage_banks(tmp_path: Path, content: str) -> None:
    root = tmp_path / "Banks"
    (root / "14").mkdir(parents=True, exist_ok=True)
    (root / "14" / "GalaxyVibe.SC2Bank").write_text(content, encoding="utf-8")
    env_guard.BANKS_ROOT = root


def test_all_success_keeps_running(tmp_path, monkeypatch):
    _stage_banks(tmp_path, BANK_KERNEL_ALIVE)
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard()
    guard.baseline()
    host = FakeHost([True] * 5)

    out = probe.run_live(_entries(5), timeout=1.0, host=host, guard=guard)

    assert host.calls == 5
    assert out["summary"]["ok"] == 5
    assert out["env"]["verdict"] == "ok"
    assert out["env"]["usable_for_acceptance"] is True


def test_preemption_aborts_immediately(tmp_path, monkeypatch):
    """跑到第 2 项时真人局启动 ⇒ 必须当场停，不许把剩下 51 项对着空气发完。"""
    _stage_banks(tmp_path, BANK_HOST_ONLY)
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard()
    guard.baseline()
    # 第 1 项成功，随后实例被挤掉
    host = FakeHost([True] + [False] * 52)
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {27348})

    out = probe.run_live(_entries(53), timeout=1.0, host=host, guard=guard)

    assert host.calls == 2, "第 2 项失败后应立即触发哨兵并中止"
    assert out["env"]["verdict"] == "env_preempted"
    assert out["env"]["aborted_after"] == 2
    assert out["env"]["planned"] == 53
    assert out["env"]["usable_for_acceptance"] is False


def test_real_failure_not_blamed_on_env(tmp_path, monkeypatch):
    """环境完好但调用全失败 ⇒ 不得甩锅给环境（Kernel 有活性信号，属真代码问题）。"""
    _stage_banks(tmp_path, BANK_KERNEL_ALIVE)
    monkeypatch.setattr(env_guard, "list_sc2_pids", lambda: {26896})
    guard = env_guard.EnvGuard(kernel_silence_grace_s=9999.0)
    guard.baseline()
    host = FakeHost([False] * 4)

    out = probe.run_live(_entries(4), timeout=1.0, host=host, guard=guard)

    assert host.calls == 4, "环境没问题就该把这批跑完，好拿到完整的失败面貌"
    assert out["summary"]["ok"] == 0
    assert out["env"]["verdict"] == "ok"
    assert out["env"]["usable_for_acceptance"] is True


def test_report_exit_codes(tmp_path, capsys):
    """退出码语义：0=全过、1=真失败、2=环境作废。上层调度靠它决定重排还是查代码。"""
    p = tmp_path / "e.json"
    assert probe._report("x", p, {
        "summary": {"total": 3, "ok": 3}, "env": {"verdict": "ok", "usable_for_acceptance": True},
    }) == 0
    assert probe._report("x", p, {
        "summary": {"total": 3, "ok": 0}, "env": {"verdict": "ok", "usable_for_acceptance": True},
    }) == 1
    assert probe._report("x", p, {
        "summary": {"total": 3, "ok": 0},
        "env": {"verdict": "env_preempted", "usable_for_acceptance": False,
                "reason": "baseline_sc2_exited", "hint": "h", "aborted_after": 2, "planned": 53},
    }) == 2
    text = capsys.readouterr().out
    assert "不可用于验收" in text
