"""Round-10 selftest 补强：给 SplitAt / SplitCount / ParseFixed 补真正的内容级断言。

为什么现在才补 —— 这正是 bug 活过 9 轮的原因：
  · 旧断言只验「令牌**数量**」（SplitCount==3），而 off-by-one 恰好不影响计数；
  · CSV 上层 API 全是纯 UI 写入、无读回，只能断言「调用不抛错」；
  · selftest 里甚至写着「切分正确性由 core 的 SplitAt 单测覆盖」——
    而那个单测根本不存在。注释撒的谎，静态检查器查不出来。
本补丁把「令牌内容」变成硬断言，含多字符分隔符、首段为空、越界、嵌套二级切分。
"""
from pathlib import Path

SELFTEST = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib"
                r"\selftest\cmlib_selftest.galaxy")

ANCHOR = """    // ---- core：字符串 ----
    CMLibTest_Mark(CMLib_StartsWith("CMLib_Test", "CMLib"));
    CMLibTest_Mark(CMLib_ParseInt("42", -1) == 42);
"""

BLOCK = """    // ---- core：字符串 ----
    CMLibTest_Mark(CMLib_StartsWith("CMLib_Test", "CMLib"));
    CMLibTest_Mark(CMLib_ParseInt("42", -1) == 42);

    // ---- core：切分器内容级断言（round-10 真机抓到 off-by-one 后补）----
    // 只验计数是抓不到 bug 的：分隔符被算进令牌、最后一段整个丢失，
    // 计数照样等于 3。必须逐个令牌比内容。
    CMLibTest_MarkTag(CMLib_SplitCount("a,b,c", ",") == 3, "split.count3");
    CMLibTest_MarkTag(CMLib_SplitCount("solo", ",") == 1, "split.count1");
    CMLibTest_MarkTag(StringEqual(CMLib_SplitAt("a,b,c", ",", 0), "a", true),
                      "split.tok0");
    CMLibTest_MarkTag(StringEqual(CMLib_SplitAt("a,b,c", ",", 1), "b", true),
                      "split.tok1");
    // 末段：旧实现在这里返回空串（余串推进多吃了一个字符）
    CMLibTest_MarkTag(StringEqual(CMLib_SplitAt("a,b,c", ",", 2), "c", true),
                      "split.tokLast");
    CMLibTest_MarkTag(StringEqual(CMLib_SplitAt("a,b,c", ",", 3), "", true),
                      "split.oob");
    // 首段为空（",b" 的第 0 段）
    CMLibTest_MarkTag(StringEqual(CMLib_SplitAt(",b", ",", 0), "", true),
                      "split.leadEmpty");
    // 多字符分隔符：验证余串推进用的是 +sepLen 而不是 +sepLen+1
    CMLibTest_MarkTag(StringEqual(CMLib_SplitAt("a::b", "::", 1), "b", true),
                      "split.multiChar");
    // 带空白的真实 CSV 形态（HudFrameCSV / StockArmyBatch 的实际输入长相）
    CMLibTest_MarkTag(
        StringEqual(CMLib_TrimSpaces(CMLib_SplitAt("21, 22 ,6", ",", 1)), "22", true),
        "split.trim");
    // 嵌套二级切分 —— stock/buff 的 "类型:数量" 规格串正是这个用法
    CMLibTest_MarkTag(
        StringEqual(CMLib_SplitAt(CMLib_SplitAt("Marine:5,Marauder:3", ",", 1),
                                  ":", 0), "Marauder", true),
        "split.nested");

    // ---- core：ParseFixed（同一个 off-by-one 让它对任何小数恒返回 fallback）----
    CMLibTest_MarkTag(RoundI(CMLib_ParseFixed("3.5", -1.0) * 100.0) == 350,
                      "parse.fixed");
    CMLibTest_MarkTag(RoundI(CMLib_ParseFixed("7", -1.0) * 100.0) == 700,
                      "parse.fixed.int");
    CMLibTest_MarkTag(RoundI(CMLib_ParseFixed("abc", -1.0) * 100.0) == -100,
                      "parse.fixed.bad");
"""


def main():
    txt = SELFTEST.read_text(encoding="utf-8")
    if "split.tokLast" in txt:
        print("[selftest] round-10 断言已存在，跳过")
    else:
        assert ANCHOR in txt, "找不到 core 字符串段锚点"
        txt = txt.replace(ANCHOR, BLOCK, 1)
        SELFTEST.write_text(txt, encoding="utf-8")
        print("[selftest] 注入 round-10 内容级断言")

    # 顺手修掉那句撒谎的注释
    lie = "因此此处只保证调用链不抛错，切分正确性由 core 的 SplitAt 单测覆盖。"
    truth = ("因此此处只保证调用链不抛错；切分正确性由上面 core 段的 split.* "
             "内容级断言覆盖（round-10 补，此前确实没有）。")
    if lie in txt:
        txt = txt.replace(lie, truth, 1)
        SELFTEST.write_text(txt, encoding="utf-8")
        print("[selftest] 订正误导性注释")

    import re
    n = len(re.findall(r"\bCMLibTest_Mark(?:Tag)?\s*\(", txt)) \
        - len(re.findall(r"\bvoid\s+CMLibTest_Mark(?:Tag)?\s*\(", txt))
    print(f"[selftest] 断言总数 = {n}")


main()
