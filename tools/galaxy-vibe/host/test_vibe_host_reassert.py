#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Isolated unit test for VibeHost bank_poll at-least-once reassert (VIBE_GEN_007).

No SC2 / no real Bank required: bank I/O is mocked. Verifies that a request lost
from the lossy Bank channel is re-sent (same request_id) and eventually yields the
response, instead of silently timing out as INTERNAL_ERROR — which is exactly the
Module 1 Step 4 (runtime_invoke_probe --sample/--census) blocker.

Run:
    python tools/galaxy-vibe/host/test_vibe_host_reassert.py
Exit 0 = all passed, 1 = failure.
"""
from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "galaxy-vibe"))
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))

# vibe.function_registry 可能在本环境不可导入（protobuf 过新等）；reassert 逻辑
# 与 function_registry 无关，注入最小 stub 让 host.vibe_host 可 import。
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


def _ok_response(request_id: str, session_id: str) -> str:
    return json.dumps({
        "kind": "result",
        "session_id": session_id,
        "request_id": request_id,
        "sequence": 1,
        "operation": "function.invoke",
        "error_code": "OK",
        "payload": {"value": 0},
    })


class BankChannel:
    """Mock lossy Bank channel.

    - ``respond_when_reasserts``: 写盘次数达到该值才由"内核"产出 response。
    - ``wipe_after``: 首次写盘后多少秒把请求从盘上抹掉（模拟 ReloadBank 窗口丢失）；
      设 None 表示永不丢失。
    """

    def __init__(self, respond_when_reasserts: int, wipe_after: float | None):
        self.respond_when_reasserts = respond_when_reasserts
        self.wipe_after = wipe_after
        self.response: dict[str, str] = {}
        self.request_present = False
        self.reasserts = 0
        self.session_id = ""
        self._wiped = False
        self._timer: threading.Timer | None = None

    def start(self) -> None:
        if self.wipe_after is not None:
            self._timer = threading.Timer(self.wipe_after, self._wipe)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self) -> None:
        if self._timer is not None:
            self._timer.cancel()

    def _wipe(self) -> None:
        self.request_present = False
        self._wiped = True

    # ---- mocked bank I/O ----
    def read_bank(self, bank_name):
        return {"response": self.response}

    def bank_request_landed(self, bank_name, request_id):
        return self.request_present

    def write_bank_request(self, bank_name, request_id, request):
        self.reasserts += 1
        self.request_present = True
        if self.reasserts >= self.respond_when_reasserts:
            self.response[request_id] = _ok_response(request_id, self.session_id)
        return True


def run_one(respond_when_reasserts: int, wipe_after: float | None, reassert: bool):
    ch = BankChannel(respond_when_reasserts, wipe_after)
    VH.read_bank = ch.read_bank
    VH.bank_request_landed = ch.bank_request_landed
    VH.write_bank_request = ch.write_bank_request

    host = VH.VibeHost()  # 默认 client=None：advance_frames 分支不会触发 step
    host.start_session()
    ch.session_id = host.session_id
    ch.start()
    try:
        resp = host.request(
            "system.ping", {}, timeout=3.0, transport="bank_poll", reassert=reassert,
        )
    finally:
        ch.cancel()
    return resp, ch.reasserts


def main() -> int:
    failures = []

    # 1) 基线：请求从不丢失，首次写盘即被"内核"响应 → OK，且无重发。
    resp, reasserts = run_one(respond_when_reasserts=1, wipe_after=None, reassert=True)
    if not resp.is_ok:
        failures.append(f"baseline: expected OK, got {resp.error_code}")
    if reasserts != 1:
        failures.append(f"baseline: expected exactly 1 write, got {reasserts}")

    # 2) 恢复：首次写盘后被抹掉（丢失窗口），重发后在第二次写盘被响应 → OK，
    #    且 reasserts >= 2（证明重发路径确实触发）。
    resp, reasserts = run_one(respond_when_reasserts=2, wipe_after=0.3, reassert=True)
    if not resp.is_ok:
        failures.append(f"recover: expected OK after reassert, got {resp.error_code}")
    if reasserts < 2:
        failures.append(f"recover: reassert path did not fire (writes={reasserts})")

    # 3) 对照：同样丢失，但关闭 reassert → 永久 INTERNAL_ERROR（这正是 Step 4 旧 bug）。
    resp, reasserts = run_one(respond_when_reasserts=2, wipe_after=0.3, reassert=False)
    if resp.error_code != "INTERNAL_ERROR":
        failures.append(f"control: expected INTERNAL_ERROR without reassert, got {resp.error_code}")
    if reasserts != 1:
        failures.append(f"control: expected only 1 write (no reassert), got {reasserts}")

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: VibeHost bank_poll at-least-once reassert (VIBE_GEN_007) verified "
          "without SC2 (baseline OK / lost-request recovered / disabled-reassert fails)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
