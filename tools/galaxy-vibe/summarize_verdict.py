#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Vibe 验收汇总器 — 把状态断言与崩溃闸门合成一个最终 verdict。

读取 P2 的 `assert-results.json`（REPL `--assert-file` 产出）与 ScriptError 复核的
`script-error-verdict.json`（`script_error_check.py` 产出），输出 `vibe-verdict.json`
并给出退出码：

- 跑过断言（assert total>0）时：断言全过 且 无新增 ScriptError → PASS(0)，否则 FAIL(1)；
- 没跑断言（仅想查崩溃闸门）时：以 ScriptError 闸门为准。

退出码：PASS=0 / FAIL=1，可直接接 CI / 冷循环门禁。

证据分类：聚合的是已落盘的 runtime 证据（assert-results / script-error-verdict），本身只做判定。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASSERT = REPO_ROOT / "artifacts" / "galaxy-vibe" / "assert-results.json"
DEFAULT_SE = REPO_ROOT / "artifacts" / "galaxy-vibe" / "script-error-verdict.json"
DEFAULT_VISUAL = REPO_ROOT / "artifacts" / "galaxy-vibe" / "visual-verdict.json"
DEFAULT_OUT = REPO_ROOT / "artifacts" / "galaxy-vibe" / "vibe-verdict.json"


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except Exception as e:  # pragma: no cover
        return None, str(e)


def main():
    ap = argparse.ArgumentParser(description="Vibe 验收汇总（assert + ScriptError -> PASS/FAIL）")
    ap.add_argument("--assert-json", default=str(DEFAULT_ASSERT))
    ap.add_argument("--script-error-json", default=str(DEFAULT_SE))
    ap.add_argument("--visual-json", default=str(DEFAULT_VISUAL),
                    help="P3 视觉 verdict（存在才纳入判定，否则不影响既有逻辑）")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    a = ap.parse_args()

    ad, a_err = _load(Path(a.assert_json))
    if ad is not None:
        assert_pass = bool(ad.get("all_passed", False))
        assert_total = int(ad.get("total", 0))
        assert_passed = int(ad.get("passed", 0))
    else:
        assert_pass, assert_total, assert_passed = False, 0, 0

    sd, s_err = _load(Path(a.script_error_json))
    if sd is not None:
        se_has_new = bool(sd.get("has_new_errors", False))
        se_count = int(sd.get("count", 0))
    else:
        se_has_new, se_count = True, -1  # 读不到视为闸门失败（安全默认）

    if assert_total > 0:
        passed = assert_pass and (not se_has_new)
    else:
        # 没跑断言：仅以 ScriptError 闸门为准
        passed = not se_has_new

    # P3 视觉：仅当 visual-verdict.json 存在时纳入（缺省不硬性要求，避免打断无图场景）
    visual_pass, visual_present, v_err = None, False, None
    vd, v_err = _load(Path(a.visual_json))
    if vd is not None:
        visual_present = True
        visual_pass = bool(vd.get("visual_passed", False))
        passed = passed and visual_pass

    verdict = {
        "passed": passed,
        "assert": {
            "all_passed": assert_pass,
            "total": assert_total,
            "passed": assert_passed,
            "read_error": a_err,
        },
        "script_error": {
            "has_new_errors": se_has_new,
            "count": se_count,
            "read_error": s_err,
        },
        "visual": {
            "present": visual_present,
            "passed": visual_pass,
            "read_error": v_err,
        },
        "generated_at": utcnow(),
    }
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")

    vtag = "" if not visual_present else f", visual={'OK' if visual_pass else 'FAIL'}"
    tag = "PASS" if passed else "FAIL"
    print(
        f"VIBE VERDICT: {tag} (assert {assert_passed}/{assert_total}, "
        f"scripterror new={se_count}{vtag}) -> {out}"
    )
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
