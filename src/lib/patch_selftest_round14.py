# -*- coding: utf-8 -*-
"""第 14 轮：消除断言「观测双记」，统一证据口径。

问题（2026-08-09 第 13 轮矩阵实测暴露）
--------------------------------------
矩阵日志报「断言通过 194/188」—— 观测到的 Marauder 比源码里的断言条数多 6。
排查结论：**不是 bug，是竞态导致的证据双记**。

    CMLibTest_Deferred   在 2.0s 触发，但主线含大量 Wait，实际跑到 20s 之后才落盘
    CMLibTest_AIDeferred 在 6.0s 触发，中途就跑完了

两条线都往同一个 gv_cmlibPassed 里计数。旧写法中 AI 线跑完后自己 spawn 了
lv_aiPassed(=6) 个 Marauder，而主线随后按**已经包含这 6 条**的 gv_cmlibPassed
又整体 spawn 了一遍 —— 同样 6 项被记了两次。

为什么必须修（这不是"多几个单位无所谓"）
----------------------------------------
观测数虚高会**吃掉失败**：假如主线哪天真丢了 6 条断言，观测数仍然是
182 + 6(AI 自 spawn) + ... 恰好凑够 188，判定照样 PASS —— 一个标准的假阳性。
证据链的价值在于"少一条就看得出来"，虚高等于把这个能力废掉。

修法
----
让证据只由一个地方产出：**AI 线只负责算，主线负责统一落盘 + 编码**。

1. 新增全局 gv_cmlibAIDone，AI 线跑完置 1；
2. 主线在落盘前自旋等待该标志（带 10s 游戏时间超时，AI 线若挂掉不会死等），
   并把"AI 线确实汇合了"本身作为一条断言 —— 等待失败要能被看见，不能静默；
3. AI 线删掉自己的 spawn 循环与 bank 回写：
   - spawn 交给主线统一做，口径唯一；
   - bank 也只由主线在终点写一次。AI 线那次回写写的是中间态
     (Passed==Total 但都不足额)，留着只会给 bank 判定制造歧义。

改完后 观测 Marauder 数 == 源码断言条数，一一对应。
"""
import os
import re
import sys

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "selftest", "cmlib_selftest.galaxy")
MARKER = "第 14 轮"


def count_asserts(txt: str) -> int:
    t = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
    t = re.sub(r"//[^\n]*", "", t)
    n = len(re.findall(r"\bCMLibTest_Mark(?:Tag)?\s*\(", t))
    n -= len(re.findall(r"\bvoid\s+CMLibTest_Mark(?:Tag)?\s*\(", t))
    return n


# ---------------------------------------------------------------- 锚点定义
# (说明, 原文, 新文)
EDITS = [
    (
        "P1 全局标志位",
        "int gv_cmlibEvtProbe;",
        "int gv_cmlibEvtProbe;\n"
        "// 第 14 轮：AI 加分线完成标志。主线靠它汇合后再统一落盘 + 编码，\n"
        "// 避免两条线各自 spawn 证据单位造成重复计数。\n"
        "int gv_cmlibAIDone;",
    ),
    (
        "P2 主线局部变量（必须置顶，中段声明会静默不编译）",
        "    int     lv_execB;\n",
        "    int     lv_execB;\n"
        "    int     lv_aiWait;\n",
    ),
    (
        "P3 主线：落盘前汇合 AI 线",
        "    // ---- 结果落盘 ----\n",
        "    // ---- 汇合 AI 加分线（第 14 轮：消除观测双记）----\n"
        "    // AI 线 6.0s 触发、主线跑到这里已远超 6s，正常情况下这个 while\n"
        "    // 一次都不会转。留着是为了不依赖「谁先跑完」这种时序巧合 ——\n"
        "    // 一旦将来主线变快，没有它就会退化成「漏记 AI 那 6 条」。\n"
        "    // 40 * 0.25 = 10s 游戏时间上限：AI 线若中途抛错，主线不会死等，\n"
        "    // 而是带着一条失败断言继续走完，让问题暴露成 FAIL 而不是卡死。\n"
        "    lv_aiWait = 0;\n"
        "    while (((gv_cmlibAIDone == 0) && (lv_aiWait < 40))) {\n"
        "        CMLib_WaitGame(0.25);\n"
        "        lv_aiWait = lv_aiWait + 1;\n"
        "    }\n"
        "    CMLibTest_MarkTag(gv_cmlibAIDone == 1, \"selftest.ailine.joined\");\n"
        "\n"
        "    // ---- 结果落盘 ----\n",
    ),
    (
        "P4 AI 线：删除自 spawn 循环与中间态 bank 回写，改为置完成标志",
        "    lv_k = 0;\n"
        "    while (lv_k < lv_aiPassed) {\n"
        "        CMLib_SpawnForced(\"Marauder\", 1, CMLib_PointOffset(lv_origin, 4.0, 0.0), 270.0);\n"
        "        lv_k += 1;\n"
        "    }\n"
        "\n"
        "    // 回写 bank，使 Total/Passed 反映含 AI 加分项的完整计数（主线在 AIDeferred\n"
        "    // 之前已落盘一次 74/74，这里补齐到 80/80，避免 bank 与观测单位数不一致）。\n"
        "    lv_bank2 = CMLib_BankOpen(\"CMLibRuntimeTest\", 1);\n"
        "    CMLib_BankSetInt(lv_bank2, \"Result\", \"Passed\", gv_cmlibPassed);\n"
        "    CMLib_BankSetInt(lv_bank2, \"Result\", \"Total\", gv_cmlibTotal);\n"
        "    CMLib_BankSetString(lv_bank2, \"Result\", \"FailTags\", gv_cmlibFailTags);\n"
        "    CMLib_BankFlush(lv_bank2);\n"
        "\n",
        "    // 第 14 轮：这里原本有一个「自己 spawn lv_aiPassed 个 Marauder」的循环\n"
        "    // 和一次 bank 回写，两者都已移除 ——\n"
        "    //   spawn：主线会按最终的 gv_cmlibPassed 统一编码，AI 再 spawn 就是重复计数；\n"
        "    //   bank ：这里写的是主线尚未跑完的中间态，Passed==Total 却不足额，\n"
        "    //          会给「以 bank 为权威」的判定制造一个看似合格的假象。\n"
        "    // AI 线现在只做一件事：算完，然后举手。\n"
        "    gv_cmlibAIDone = 1;\n"
        "\n",
    ),
    (
        "P5 AI 线：清理不再使用的局部变量",
        "    point lv_origin;\n"
        "    int   lv_aiPassed;\n"
        "    int   lv_k;\n"
        "    bank  lv_bank2;\n",
        "    point lv_origin;\n"
        "    int   lv_aiPassed;\n",
    ),
]


def main() -> int:
    txt = open(SRC, encoding="utf-8").read()
    before = count_asserts(txt)

    if MARKER in txt:
        print(f"[patch14] 已打过补丁（检测到标记「{MARKER}」），跳过。断言数 = {before}")
        return 0

    # 落盘前自检：每个锚点必须恰好命中 1 次，否则宁可不改
    for name, old, _new in EDITS:
        hits = txt.count(old)
        if hits != 1:
            print(f"[patch14] 锚点异常：{name} 命中 {hits} 次（期望 1），中止。")
            return 2

    for name, old, new in EDITS:
        txt = txt.replace(old, new, 1)
        print(f"[patch14] OK  {name}")

    # 残留检查：被删掉的变量不能还有人用
    for dead in ("lv_k", "lv_bank2"):
        if re.search(r"\b" + dead + r"\b", txt):
            print(f"[patch14] 残留引用：{dead} 仍被使用，中止（避免编译期未声明变量）。")
            return 3

    open(SRC, "w", encoding="utf-8", newline="\n").write(txt)
    after = count_asserts(txt)
    print(f"[patch14] 写入完成：{SRC}")
    print(f"[patch14] 断言 {before} -> {after} (+{after - before})")
    print("[patch14] 预期真机观测 Marauder 数 == %d（不再有 +6 虚高）" % after)
    return 0


if __name__ == "__main__":
    sys.exit(main())
