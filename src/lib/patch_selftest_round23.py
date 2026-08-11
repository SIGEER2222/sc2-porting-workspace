"""为 round23 的 CMLib_StatEvt* 注入真机断言（幂等）。

设计要点：

1. **局部变量必须置顶**（round8 血泪：中段声明 → 整段 MapScript 静默不编译，
   Ghost=0）。新变量插在 Deferred 声明区末尾 `unit lv_r20u;` 之后。

2. **void 函数不能进比较表达式**（round20 血泪）。守门类断言的正确写法是
   「裸调用 + 存活哨兵」：先无条件调一串该被守门早退的 void 入口，
   再断言后续一个可回读的表达式仍然正确 —— 若前面任何一条把线程打断了，
   哨兵那条断言根本不会被执行，Total 就对不上，一样能暴露。

3. StatEvent 的**上报结果客户端不可观测**，所以断言只验证「库自身的守门 /
   记账 / CSV 解析语义」这些**可判定**的部分，绝不去断言"上报成功"。
   这条边界很重要：断言一个观测不到的东西，等于给自己发一张假通行证。
"""
import sys
from pathlib import Path

SELF = Path(__file__).resolve().parent / "selftest" / "cmlib_selftest.galaxy"
MARK = "statevt.begin"

DECL_ANCHOR = "    unit        lv_r20u;\n"
DECL_NEW = """    unit        lv_r20u;
    int         lv_r23ev;
    int         lv_r23ev2;
    int         lv_r23n;
"""

BODY_ANCHOR = "    // ---- 汇合 AI 加分线（第 14 轮：消除观测双记）----"

BODY_NEW = r"""    // ---- Round23：StatEvent 埋点封装 ----------------------------------
    // 范围判定翻案后落库的一组 API。真机探针（probe_statevent.py）已证
    // 可编译 / 可调用 / 不中断 trigger；这里验的是**库自己的语义**：
    // 守门、已发送记账、CSV 解析。上报 Battle.net 与否客户端观测不到，
    // 故意不断言 —— 断言观测不到的东西等于自欺。
    lv_r23ev = CMLib_StatEvtBegin("CMLibR23");
    CMLibTest_MarkTag(lv_r23ev != CMLIB_STATEVT_INVALID, "statevt.begin");
    CMLibTest_MarkTag(CMLib_StatEvtOk(lv_r23ev), "statevt.ok");

    // 空名必须被守门挡下，且不能把无效句柄伪装成有效。
    lv_r23ev2 = CMLib_StatEvtBegin("");
    CMLibTest_MarkTag(lv_r23ev2 == CMLIB_STATEVT_INVALID, "statevt.begin.empty");
    CMLibTest_MarkTag(CMLib_StatEvtOk(CMLIB_STATEVT_INVALID) == false,
                      "statevt.ok.invalid");

    // 刚建过事件，LastCreated 不该是 0。
    CMLibTest_MarkTag(CMLib_StatEvtLast() != CMLIB_STATEVT_INVALID,
                      "statevt.last");

    // CSV：三个键三个值。
    lv_r23n = CMLib_StatEvtStrCSV(lv_r23ev, "a:1,b:2,c:3");
    CMLibTest_MarkTag(lv_r23n == 3, "statevt.strcsv");

    // 按**第一个**冒号切，值里可以再含冒号（"用时:12:30"）。
    lv_r23n = CMLib_StatEvtStrCSV(lv_r23ev, "elapsed:12:30");
    CMLibTest_MarkTag(lv_r23n == 1, "statevt.strcsv.colon");

    // 无冒号项不成键值对，计 0 而不是塞个空值进去。
    lv_r23n = CMLib_StatEvtStrCSV(lv_r23ev, "noColonHere");
    CMLibTest_MarkTag(lv_r23n == 0, "statevt.strcsv.nokey");

    // key 前后空格要被 trim 掉，否则下游按键名对齐会错位。
    lv_r23n = CMLib_StatEvtStrCSV(lv_r23ev, "  spaced  :v");
    CMLibTest_MarkTag(lv_r23n == 1, "statevt.strcsv.trim");

    // int 版：解析失败按 0 计但**不丢键**（少键比多一个 0 难查得多）。
    lv_r23n = CMLib_StatEvtIntCSV(lv_r23ev, "x:10,y:20,bad:zzz");
    CMLibTest_MarkTag(lv_r23n == 3, "statevt.intcsv");

    // 守门批次：这几条都该静默早退。void 不能进比较表达式，
    // 用「裸调用 + 后续哨兵」验证 —— 任一条打断线程，哨兵就不会执行。
    CMLib_StatEvtStr(CMLIB_STATEVT_INVALID, "k", "v");
    CMLib_StatEvtInt(CMLIB_STATEVT_INVALID, "k", 1);
    CMLib_StatEvtFixed(CMLIB_STATEVT_INVALID, "k", 1.5);
    CMLib_StatEvtStr(lv_r23ev, "", "v");
    CMLib_StatEvtInt(lv_r23ev, "", 1);
    CMLib_StatEvtFixed(lv_r23ev, "", 1.5);
    CMLibTest_MarkTag(CMLib_StatEvtOk(lv_r23ev), "statevt.guard.alive");

    // 发送成功，句柄随即作废。
    CMLibTest_MarkTag(CMLib_StatEvtSend(lv_r23ev), "statevt.send");
    // 环形缓冲要拦住二次发送（对已销毁对象操作是真实风险）。
    CMLibTest_MarkTag(CMLib_StatEvtSend(lv_r23ev) == false,
                      "statevt.send.twice");
    CMLibTest_MarkTag(CMLib_StatEvtOk(lv_r23ev) == false, "statevt.ok.sent");
    // 发送后再挂数据必须被拒（不能往已销毁事件里写）。
    lv_r23n = CMLib_StatEvtStrCSV(lv_r23ev, "a:1");
    CMLibTest_MarkTag(lv_r23n == 0, "statevt.csv.after.send");

    // 一步到位的两个便捷入口。
    CMLibTest_MarkTag(CMLib_StatEvtSendCSV("CMLibR23CSV", "mode:test,round:23"),
                      "statevt.sendcsv");
    CMLibTest_MarkTag(CMLib_StatEvtSendInt("CMLibR23Int", "count", 42),
                      "statevt.sendint");
    // 空名走便捷入口同样要失败，不能因为多包一层就绕过守门。
    CMLibTest_MarkTag(CMLib_StatEvtSendCSV("", "k:v") == false,
                      "statevt.sendcsv.empty");

"""


def main() -> int:
    if not SELF.is_file():
        print(f"[r23-selftest] 找不到 {SELF}")
        return 1
    cur = SELF.read_text(encoding="utf-8")
    if MARK in cur:
        print("[r23-selftest] skip（已应用）")
        return 0

    if DECL_ANCHOR not in cur:
        print("[r23-selftest] !! 未找到变量声明锚点")
        return 1
    if BODY_ANCHOR not in cur:
        print("[r23-selftest] !! 未找到断言插入锚点")
        return 1

    cur = cur.replace(DECL_ANCHOR, DECL_NEW, 1)
    cur = cur.replace(BODY_ANCHOR, BODY_NEW + BODY_ANCHOR, 1)
    SELF.write_text(cur, encoding="utf-8")

    n = BODY_NEW.count("CMLibTest_MarkTag(")
    print(f"[r23-selftest] 注入 {n} 条带标签断言 + 4 个局部变量")
    return 0


if __name__ == "__main__":
    sys.exit(main())
