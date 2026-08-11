#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""VIBE-KERNEL-006 契约测试：HANDLER_ABORTED 是 provisional 占位符，不是终态裁决。

背景（真机取证 artifacts/galaxy-vibe/p0-transport-k006-forensic-rep2/rep3）：
内核 ``KERNEL001_PESSIMISTIC``（LibVibeKernel.galaxy:1483-1485）在 handler 运行
**之前**就写 ``response/<rid> = HANDLER_ABORTED``，而 ``gf_WriteBankKey`` 内部
（:194-195）是 ``BankValueSetFromString`` + **立即 BankSave**。Host 每 50ms 轮询
且旧代码把任何非空 response 当终态，于是会抢读到这个占位符。取证结果：7/7 个
HANDLER_ABORTED 都在 37~54ms 内被真 ``OK`` 覆盖，**零个是真 abort**。
``HANDLER_ABORTED`` 在内核里只有这一个代码产生点，因此 Host 侧即可完整修复。

本测试锁定的契约（含防恒绿 / 防恒红 / 反向对照）：
  1. 占位符随后被真响应覆盖 → ``_poll_response`` 返回**真响应**（修复生效）
  2. 占位符始终不变 → 观测窗口耗尽后返回 **HANDLER_ABORTED**（不是 INTERNAL_ERROR）
     —— 防恒绿关键：真 abort 依旧计为 non-ok，判据强度分毫未放宽
  3. 盘上自始至终无 response → 仍返回 INTERNAL_ERROR（host 侧超时语义不变）
  4. ``abort_is_terminal=True``（legacy 反向对照）→ 立刻返回 HANDLER_ABORTED
     —— 证明 case 1 的差异确实来自本修复而非环境
  5. 观察-only 取证器 ``_observe_aborted_supersede`` 本身能报真也能报假

Run:
    python tools/galaxy-vibe/host/test_provisional_abort_probe.py
Exit 0 = all passed, 1 = failure.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "galaxy-vibe"))
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))

try:
    import vibe.function_registry  # noqa: F401
except Exception:  # noqa: BLE001
    import types
    m = types.ModuleType("vibe.function_registry")
    m.FunctionRegistryError = Exception
    m.normalize_request_args = lambda args: ("", {})
    m.wire_function_args = lambda fid, args: {}
    sys.modules["vibe.function_registry"] = m

import host.vibe_host as VH  # noqa: E402

RID = "rid_provisional_001"


def _abort_placeholder() -> str:
    """内核 KERNEL001_PESSIMISTIC 写的悲观占位符（handler 运行前）。"""
    return json.dumps({
        "kind": "error", "session_id": "sess", "request_id": RID, "sequence": 1,
        "operation": "system.ping", "error_code": "HANDLER_ABORTED",
        "payload": {"reason": "handler_did_not_complete"},
    })


def _real_ok() -> str:
    """handler 真正完成后写回的响应。"""
    return json.dumps({
        "kind": "result", "session_id": "sess", "request_id": RID, "sequence": 1,
        "operation": "system.ping", "error_code": "OK", "payload": {"pong": True},
    })


def _make_host() -> "VH.VibeHost":
    host = VH.VibeHost.__new__(VH.VibeHost)          # 绕过 __init__ 的 SC2/目录副作用
    host.bank_name = "GalaxyVibe"
    host.session_id = "sess"
    host.sequence = 1
    host.client = None
    host.realtime = True
    host.poll_step_count = 1
    host.aborted_grace_probe = 0.0
    host.abort_is_terminal = False
    host.provisional_diags = []
    host.reassert_diags = []
    return host


def _install_bank(seq: list[str]) -> None:
    """read_bank 打桩：按序返回 response/<RID>；最后一项会被重复返回。

    传入 ``[]`` 表示盘上始终没有该 rid 的 response。
    """
    state = {"i": 0}

    def fake_read_bank(_name: str) -> dict:
        if not seq:
            return {"response": {}}
        i = min(state["i"], len(seq) - 1)
        state["i"] += 1
        return {"response": {RID: seq[i]}}

    VH.read_bank = fake_read_bank  # type: ignore[assignment]


def case_1_provisional_superseded_returns_real() -> bool:
    host = _make_host()
    _install_bank([_abort_placeholder(), _abort_placeholder(), _real_ok()])
    resp = host._poll_response(RID, timeout=3.0)
    d = host.provisional_diags
    ok = (resp.error_code == "OK" and len(d) == 1 and d[0]["superseded"] is True)
    print(f"  case1 provisional_superseded_returns_real: {'PASS' if ok else 'FAIL'} -> "
          f"returned={resp.error_code}, diags={d}")
    return ok


def case_2_real_abort_stays_red() -> bool:
    """防恒绿：占位符永不被覆盖 = 真 abort，必须仍返回 HANDLER_ABORTED。"""
    host = _make_host()
    _install_bank([_abort_placeholder()])
    resp = host._poll_response(RID, timeout=0.5)
    d = host.provisional_diags
    ok = (
        resp.error_code == "HANDLER_ABORTED"
        and len(d) == 1 and d[0]["superseded"] is False
    )
    print(f"  case2 real_abort_stays_red: {'PASS' if ok else 'FAIL'} -> "
          f"returned={resp.error_code}, diags={d}")
    return ok


def case_3_no_response_still_internal_error() -> bool:
    """盘上无任何 response → 仍是 host 侧超时 INTERNAL_ERROR（语义未被污染）。"""
    host = _make_host()
    _install_bank([])
    resp = host._poll_response(RID, timeout=0.4)
    ok = resp.error_code == "INTERNAL_ERROR" and host.provisional_diags == []
    print(f"  case3 no_response_still_internal_error: {'PASS' if ok else 'FAIL'} -> "
          f"returned={resp.error_code}")
    return ok


def case_4_legacy_negative_control() -> bool:
    """反向对照：legacy 模式下同一输入必须回到旧行为（立刻 HANDLER_ABORTED）。

    与 case 1 的唯一差异就是 abort_is_terminal —— 若两者结果相同，说明修复根本没生效。
    """
    host = _make_host()
    host.abort_is_terminal = True
    _install_bank([_abort_placeholder(), _abort_placeholder(), _real_ok()])
    resp = host._poll_response(RID, timeout=3.0)
    ok = resp.error_code == "HANDLER_ABORTED"
    print(f"  case4 legacy_negative_control: {'PASS' if ok else 'FAIL'} -> "
          f"returned={resp.error_code} (case1 同输入应为 OK)")
    return ok


def case_5_observer_reports_both_ways() -> bool:
    """观察-only 取证器自身既能报真（被覆盖）也能报假（未被覆盖）。"""
    h1 = _make_host()
    h1.aborted_grace_probe = 1.0
    _install_bank([_abort_placeholder(), _abort_placeholder(), _real_ok()])
    h1._observe_aborted_supersede(RID, _abort_placeholder())

    h2 = _make_host()
    h2.aborted_grace_probe = 0.3
    _install_bank([_abort_placeholder()])
    h2._observe_aborted_supersede(RID, _abort_placeholder())

    ok = (
        h1.provisional_diags[0]["superseded"] is True
        and h1.provisional_diags[0]["final_error_code"] == "OK"
        and h2.provisional_diags[0]["superseded"] is False
    )
    print(f"  case5 observer_reports_both_ways: {'PASS' if ok else 'FAIL'} -> "
          f"positive={h1.provisional_diags}, negative={h2.provisional_diags}")
    return ok


def main() -> int:
    print("VIBE-KERNEL-006 provisional HANDLER_ABORTED contract test")
    results = [
        case_1_provisional_superseded_returns_real(),
        case_2_real_abort_stays_red(),
        case_3_no_response_still_internal_error(),
        case_4_legacy_negative_control(),
        case_5_observer_reports_both_ways(),
    ]
    passed = sum(1 for r in results if r)
    print(f"{passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
