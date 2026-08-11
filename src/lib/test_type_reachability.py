# -*- coding: utf-8 -*-
"""
test_type_reachability.py — 门禁的门禁：钉住 check_type_reachability 的可证伪性

## 为什么需要它

`check_type_reachability.py` 存在的理由，是抓「封装收了某种句柄，
但库自己造不出这种句柄」的死接口。可**一个只会报 FAIL 的门禁**和
**一个恒绿的门禁**一样没用 —— 前者会被当成噪音直接忽略，
后者压根不报警。两种都是判据坏死。

所以这里用注入式对照钉住它：

    A 现状          -> 必须 PASS（库当下确实没有死接口）
    B 注入合成缺口   -> 必须 FAIL，且报告点名该类型（证明它不是恒绿）
    C 缺口 + 登记    -> 必须 PASS（证明它不是恒红，收口路径真的通）
    D 登记但理由为空 -> 必须 FAIL（证明 blank 分支不是摆设，
                        不能靠写一行空登记把洞糊过去）
    E 源不完整      -> 必须 fail-closed，不能因为读不到引擎符号就"没发现问题"假绿

## round27 修正：A 档原本写的是「现状必须 FAIL」

那版把**被测仓库当时恰好是坏的**这一事实写进了断言。marker / sound / camerainfo
三个洞一收口，A 立刻恒红 —— 判据坏死的第一形态：断言与被测系统的正常状态
正面冲突。它报的红跟库的好坏没关系，只跟"库有没有恢复到写断言那天的样子"有关。

修法不是把 A 删掉，是把它**倒过来**：现状应该是 PASS（这本来就是我们想要的
性质，且完全可证伪 —— 哪天谁再引进一个死接口它就红）。而"门禁不是恒绿"这条
证明责任转交给 B：不依赖仓库脏不脏，自己注入一个合成的不可达类型。
判据不许依赖被测对象的历史状态，这是第二次栽在同一个坑上（第一次是内核
`gf_CheckSession` 那条 new_session_ping_ok）。

## 用法

    python test_type_reachability.py
退出码: 0 = 全部通过, 1 = 有断言不成立
"""
from __future__ import annotations

import contextlib
import io
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

import check_type_reachability as tr  # noqa: E402

FAKE = "fake_reverse_control_h.galaxy"


def _run() -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = tr.main()
    return rc, buf.getvalue()


# 合成缺口用的句柄类型。
# 挑 `waveinfo` 是因为它是引擎真实存在的句柄类型（能通过 handle_types 的筛选），
# 而 CMLib 至今**一处都没碰过** —— 注入一个"收它做形参"的假函数，
# 就凭空造出一个货真价实的死接口。
# 用真实类型而不是编造的名字，是为了让这条对照走的路径和真实缺口完全一致：
# 编造的名字会在 handle_types 那步就被筛掉，那样测到的根本不是同一条判定链。
# 也不能挑库已经碰过的类型（比如 revealer 已被消费/生产），那样注入不出洞。
SYNTH_TYPE = "waveinfo"


def main() -> int:
    fails: list[str] = []
    orig_external = tr.registered_external
    orig_natives = tr.engine_natives
    orig_public = tr.public_api

    def inject_hole():
        """在真实公开 API 之外追加一个只消费、无人生产的假函数。

        元组口径必须与 public_api() 完全一致：(返回类型, 函数名, [形参类型], 文件名)。
        """
        rows = list(orig_public())
        rows.append(("void", "CMLibTest_SynthConsume",
                     [SYNTH_TYPE], "fake_synthetic_h.galaxy"))
        return rows

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(("  PASS  " if cond else "  FAIL  ") + name +
              (("  -> " + detail) if (detail and not cond) else ""))
        if not cond:
            fails.append(name)

    print("=" * 78)
    print("[test] check_type_reachability 可证伪性五向对照")
    print("=" * 78)

    try:
        # ---- A：现状必须是干净的 --------------------------------------------
        # 这条是对**库**的断言（没有死接口），不是对门禁的。它可证伪：
        # 谁再引进一个"收句柄但库造不出"的封装，它立刻红。
        rc_a, out_a = _run()
        check("A 现状为 PASS（库当下没有死接口）", rc_a == 0, f"rc={rc_a}")

        # ---- B：注入合成缺口必须被抓到 --------------------------------------
        # "门禁不是恒绿"的证明责任在这里，而且不依赖仓库脏不脏。
        tr.public_api = inject_hole
        rc_b, out_b = _run()
        check(f"B 注入 {SYNTH_TYPE} 死接口后为 FAIL（门禁不是恒绿）",
              rc_b == 1, f"rc={rc_b}")
        check("B 报告点名了该类型",
              "不可达句柄类型" in out_b and SYNTH_TYPE in out_b)

        # ---- C：登记之后必须能翻绿 ------------------------------------------
        tr.registered_external = lambda: {SYNTH_TYPE: ("反向对照注入", FAKE)}
        rc_c, _ = _run()
        check("C 补齐登记后为 PASS（门禁不是恒红，收口路径真的通）",
              rc_c == 0, f"rc={rc_c}")

        # ---- D：空理由不许糊弄 ----------------------------------------------
        tr.registered_external = lambda: {SYNTH_TYPE: ("", FAKE)}
        rc_d, out_d = _run()
        check("D 登记但理由为空仍为 FAIL（空登记不能当交代）",
              rc_d == 1 and "理由为空" in out_d, f"rc={rc_d}")

        # ---- E：源不完整必须 fail-closed ------------------------------------
        tr.public_api = orig_public
        tr.registered_external = orig_external
        tr.engine_natives = lambda: orig_natives()[:10]
        rc_e, out_e = _run()
        check("E 引擎符号读不全时 fail-closed（输入残缺不许假绿）",
              rc_e == 1 and "fail-closed" in out_e, f"rc={rc_e}")
    finally:
        tr.public_api = orig_public
        tr.registered_external = orig_external
        tr.engine_natives = orig_natives

    print()
    if fails:
        print(f"[test] FAILED —— {len(fails)} 条断言不成立：" + "; ".join(fails))
        return 1
    print("[test] PASSED —— 门禁在 A~E 五个方向上都行为正确"
          "（现状干净 / 注入能抓 / 登记能收 / 空理由拒绝 / 输入残缺 fail-closed）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
