# -*- coding: utf-8 -*-
"""控制台编码自卫检查 —— round24。

**要解决的问题（round24 现场抓获）**

Windows 控制台默认 GBK(gb2312)。工具脚本里只要出现一个 GBK 编不出的字符
（实测：`verify_natives.py` 成功路径打印的 `'\u2713'`，也就是 ✓），`print`
就抛 `UnicodeEncodeError`，脚本以 rc=1 退出。gate.py 看到 rc=1，判

    [gate] FAILED —— 未通过的关卡: verify_natives

——但 verify_natives 的核对**根本就通过了**，崩的是最后那句"恭喜"。
同一份代码，`PYTHONIOENCODING=utf-8` 下 ALL PASSED、裸 GBK 控制台下 FAILED。

这是一次**假 FAIL**。它比假 PASS 温和，但性质同样恶劣：一个结论取决于
调用者当时有没有设环境变量的门禁，等于没有门禁。round22 的血泪是
"别让次级判据插到 sentinel 前面"，这次是同一个母题的另一面 ——
**判定不能依赖与被测对象无关的环境细节**。

**本检查做两件事**

1. 常驻入口脚本若含 GBK 编不出的字符，必须带编码自卫片段
   （`sys.stdout.reconfigure(errors="replace")`）。
   一次性 patch/extend 脚本不在范围内：它们跑完即弃，不进门禁链。
2. `gate.py` 调子进程时必须显式传 `PYTHONIOENCODING=utf-8`。
   因为 gate.py 用 `encoding="utf-8"` 解码子进程输出，子进程却按 GBK
   编码 —— 编解码口径不一致，中文会被 `errors="replace"` 悄悄糊成乱码，
   属于"没报错但证据已经脏了"的那类问题。

**反向对照**：`test_detector_actually_detects` 用合成样本验证探测逻辑
本身有效。没有它，只要 `_gbk_unsafe_chars` 写错一个字，本检查就会
恒绿 —— 那正是"校验器自身要有校验器"要防的东西。

用法：
    python test_console_encoding.py
"""
from __future__ import annotations

import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent

# 常驻入口 = 会被 gate.py / 真机矩阵 / 自动化反复调用的脚本。
# 判据是"是否进门禁或验证链"，不是"是否重要"。
RECURRING = [
    "gate.py",
    "check_cmlib.py",
    "check_g1001.py",
    "verify_natives.py",
    "expected_asserts.py",
    "matrix_daemon.py",
    "run_matrix_round10.py",
    "build_testmap.py",
    "build_typecheck_unit.py",
    "gen_api_index.py",
    "test_verdict_order.py",
    "sc2_proc_guard.py",
    "test_console_encoding.py",  # 自己也算，别搞双标
]

GUARD_SIGNATURE = 'reconfigure(errors="replace")'


def _gbk_unsafe_chars(text: str) -> set[str]:
    """返回 text 里 GBK 编不出的字符集合（ASCII 直接跳过，省时间）。"""
    out: set[str] = set()
    for ch in text:
        if ord(ch) < 128:
            continue
        try:
            ch.encode("gbk")
        except UnicodeEncodeError:
            out.add(ch)
    return out


def test_detector_actually_detects() -> list[str]:
    """反向对照：探测器必须能抓到已知的坏字符，也必须放过纯中文。

    没有这一步，_gbk_unsafe_chars 一旦写坏（比如 except 写成 Exception 且
    吞掉），全表恒绿，本文件就成了摆设。
    """
    errs: list[str] = []
    hit = _gbk_unsafe_chars("成功 \u2713 完成")
    if hit != {"\u2713"}:
        errs.append(f"反向对照失败：'\\u2713' 应被判为 GBK 不安全，实得 {hit!r}")
    if _gbk_unsafe_chars("纯中文一律安全，逗号句号都在 GBK 里"):
        errs.append("反向对照失败：纯中文被误判为 GBK 不安全")
    if _gbk_unsafe_chars("plain ascii only"):
        errs.append("反向对照失败：纯 ASCII 被误判为 GBK 不安全")
    return errs


def test_recurring_scripts_guarded() -> list[str]:
    errs: list[str] = []
    for name in RECURRING:
        p = HERE / name
        if not p.exists():
            errs.append(f"{name}: 清单里有但文件不存在（清单漂移，先修清单）")
            continue
        text = p.read_text(encoding="utf-8")
        bad = _gbk_unsafe_chars(text)
        if not bad:
            continue
        if GUARD_SIGNATURE not in text:
            errs.append(
                f"{name}: 含 GBK 编不出的字符 {''.join(sorted(bad))!r} "
                f"却没有编码自卫片段 -> 在 GBK 控制台会 UnicodeEncodeError 崩溃，"
                f"造成假 FAIL。请在 import 段后加 "
                f'sys.stdout/stderr.reconfigure(errors="replace")'
            )
    return errs


def test_gate_forces_child_utf8() -> list[str]:
    """gate.py 必须给子进程显式指定 PYTHONIOENCODING=utf-8。"""
    errs: list[str] = []
    text = (HERE / "gate.py").read_text(encoding="utf-8")
    if '"PYTHONIOENCODING": "utf-8"' not in text:
        errs.append(
            'gate.py: 未给子进程设置 PYTHONIOENCODING=utf-8。'
            '它用 encoding="utf-8" 解码子进程输出，子进程若按 GBK 编码，'
            "中文会被静默糊成乱码，且子进程可能因打印崩溃被误判为关卡失败。"
        )
    if "env=_CHILD_ENV" not in text:
        errs.append("gate.py: subprocess.run 未把 _CHILD_ENV 传下去（定义了没用等于没定义）")
    return errs


def main() -> int:
    all_errs: list[str] = []
    for fn in (test_detector_actually_detects,
               test_recurring_scripts_guarded,
               test_gate_forces_child_utf8):
        errs = fn()
        status = "FAIL" if errs else "ok"
        print(f"[enc] {fn.__name__:38s} {status}")
        all_errs.extend(errs)

    print()
    if all_errs:
        for e in all_errs:
            print(f"[enc] ERROR {e}")
        print(f"\n[enc] FAILED —— {len(all_errs)} 个问题")
        return 1
    print(f"[enc] PASSED —— {len(RECURRING)} 个常驻入口的控制台编码自卫齐备")
    return 0


if __name__ == "__main__":
    sys.exit(main())
