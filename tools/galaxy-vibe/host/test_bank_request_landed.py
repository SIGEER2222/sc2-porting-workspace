#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit test for VIBE-KERNEL-005b fix: ``bank_request_landed`` now checks only the
active (kernel-read) candidate's ``request`` section, NOT every candidate and NOT
pending_request_id match.

Background: Banks dir accumulated 16+ stale digit subdirs from prior sessions. The
old "every candidate must carry the request AND pending_request_id==rid" rule caused
spurious False → needless reasserts (every request, every ~2s after the kernel
clears pending). That spurious reassert loop is the real-machine 16s stall source.

This test builds a temp Banks dir with a root + several stale digit subdirs and
asserts:
  - landed == True when the ACTIVE candidate (max-mtime with index) carries the rid,
    even if stale candidates lack it / have mismatched pending.
  - landed == False only when the ACTIVE candidate lacks the rid (genuine loss),
    even if stale candidates happen to carry it.

No SC2 required. Run: python tools/galaxy-vibe/host/test_bank_request_landed.py
Exit 0 = pass, 1 = fail.
"""
from __future__ import annotations

import os
import sys
import time
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


def _write_bank(path: Path, *, has_index: bool, rid: str | None, pending: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    secs = []
    if has_index:
        keys = ""
        if pending is not None:
            keys = f'    <Key name="pending_request_id"><Value string="{pending}"/></Key>\n'
        secs.append(f'  <Section name="index">\n{keys}  </Section>')
    if rid is not None:
        secs.append(
            f'  <Section name="request">\n'
            f'    <Key name="{rid}"><Value string="args"/></Key>\n'
            f'  </Section>'
        )
    xml = '<?xml version="1.0" encoding="utf-8"?>\n<Bank version="1">\n' + "".join(secs) + "</Bank>\n"
    path.write_text(xml, encoding="utf-8")


def _setup(tmp: Path) -> dict[str, Path]:
    """Build root + 3 stale digit subdirs (older mtime, no index) + 1 active dir.

    Returns the path dict; caller decides which file to (re)write for the case.
    """
    bank = tmp / "Banks"
    root = bank / "GalaxyVibe.SC2Bank"
    # stale dirs: no index (so they can't be 'active'), carry stale pending/rid
    stale1 = bank / "1" / "GalaxyVibe.SC2Bank"
    stale2 = bank / "2" / "GalaxyVibe.SC2Bank"
    # active dir will be created by caller with index + max mtime
    active = bank / "3" / "GalaxyVibe.SC2Bank"
    _write_bank(root, has_index=True, rid="old_rid", pending="old_rid")
    _write_bank(stale1, has_index=False, rid="old_rid", pending="old_rid")
    _write_bank(stale2, has_index=False, rid="old_rid", pending="old_rid")
    # older mtime on stale dirs
    t0 = time.time() - 10
    for p in (root, stale1, stale2):
        try:
            os.utime(str(p), (t0, t0))
        except OSError:
            pass
    return {"root": root, "stale1": stale1, "stale2": stale2, "active": active, "bank": bank}


def main() -> int:
    failures = []
    tmp = Path(__file__).resolve().parent / ".tmp_brl_test"
    try:
        tmp.mkdir(parents=True, exist_ok=True)
        VH.DEFAULT_BANK_DIR = tmp / "Banks"

        rid = "req_abc"

        # Case A: active carries rid (+ has index, newest mtime). Stale dirs lack it.
        paths = _setup(tmp)
        _write_bank(paths["active"], has_index=True, rid=rid, pending=rid)
        at = time.time()
        os.utime(str(paths["active"]), (at, at))
        if not VH.bank_request_landed("GalaxyVibe", rid):
            failures.append("A: active carries rid but landed==False (stale dirs should not matter)")
        # and active candidate is indeed the '3' dir
        active_picked = VH._active_candidate("GalaxyVibe")
        if active_picked != paths["active"]:
            failures.append(f"A: active candidate wrong: {active_picked} != {paths['active']}")

        # Case B: the NEWEST candidate-with-index (the kernel-read active dir) LACKS
        # rid → genuine loss → False, even if an OLDER stale dir carries it+index.
        paths = _setup(tmp)
        _write_bank(paths["active"], has_index=True, rid=None, pending=None)
        at = time.time()
        os.utime(str(paths["active"]), (at, at))
        # older stale dir WITH index+rid: must NOT be picked as active nor mask loss
        _write_bank(paths["stale1"], has_index=True, rid=rid, pending=rid)
        try:
            os.utime(str(paths["stale1"]), (at - 5, at - 5))
        except OSError:
            pass
        if VH.bank_request_landed("GalaxyVibe", rid):
            failures.append("B: newest active lacks rid but landed==True (stale dir must not mask loss)")

        # Case C: no candidate has index → active None → False.
        paths = _setup(tmp)
        for p in (paths["root"], paths["stale1"], paths["stale2"]):
            _write_bank(p, has_index=False, rid=None, pending=None)
        if VH.bank_request_landed("GalaxyVibe", rid):
            failures.append("C: no index anywhere but landed==True")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    if failures:
        print("FAIL:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: bank_request_landed (VIBE-KERNEL-005b) checks only active candidate's "
          "request section; stale dirs neither cause spurious False nor mask genuine loss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
