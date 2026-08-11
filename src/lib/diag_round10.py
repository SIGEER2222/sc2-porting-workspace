"""Round-10 临时诊断补丁：把 hud.csv.three / pl.start 两条真机失败的中间值写进 bank。

不新增 CMLibTest_Mark 调用（EXPECTED_ASSERTS 从源码自动推导，加断言会污染基线）。
只在 CMLibTest_AIDeferred 末尾的 bank 落盘前插入 Diag/* 键。

  python diag_round10.py apply    # 打补丁
  python diag_round10.py revert   # 还原
"""
import re
import sys
from pathlib import Path

SELFTEST = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib"
                r"\selftest\cmlib_selftest.galaxy")

MARK_BEGIN = "    // >>> CMLIB_DIAG_ROUND10 >>>\n"
MARK_END = "    // <<< CMLIB_DIAG_ROUND10 <<<\n"

DECL_ANCHOR = "    bank  lv_bank2;\n"
DECL_EXTRA = (
    "    int   lv_dCsvCount;\n"
    "    int   lv_dCsvApplied;\n"
    "    point lv_dStart;\n"
    "    int   lv_dStartNull;\n"
    "    int   lv_dStartX;\n"
)

FLUSH_ANCHOR = '    CMLib_BankFlush(lv_bank2);\n'

DIAG_BODY = (
    MARK_BEGIN +
    '    lv_dCsvCount   = CMLib_SplitCount("21, 22 ,6", ",");\n'
    '    lv_dCsvApplied = CMLib_HudFrameCSV(null, "21, 22 ,6", true);\n'
    '    lv_dStart      = PlayerStartLocation(1);\n'
    '    lv_dStartNull  = 0;\n'
    '    lv_dStartX     = -99999;\n'
    '    if ((lv_dStart == null)) {\n'
    '        lv_dStartNull = 1;\n'
    '    }\n'
    '    else {\n'
    '        lv_dStartX = RoundI(PointGetX(lv_dStart) * 100.0);\n'
    '    }\n'
    '    CMLib_BankSetInt(lv_bank2, "Diag", "CsvCount", lv_dCsvCount);\n'
    '    CMLib_BankSetInt(lv_bank2, "Diag", "CsvApplied", lv_dCsvApplied);\n'
    '    CMLib_BankSetString(lv_bank2, "Diag", "Tok0",\n'
    '                        CMLib_TrimSpaces(CMLib_SplitAt("21, 22 ,6", ",", 0)));\n'
    '    CMLib_BankSetString(lv_bank2, "Diag", "Tok1",\n'
    '                        CMLib_TrimSpaces(CMLib_SplitAt("21, 22 ,6", ",", 1)));\n'
    '    CMLib_BankSetString(lv_bank2, "Diag", "Tok2",\n'
    '                        CMLib_TrimSpaces(CMLib_SplitAt("21, 22 ,6", ",", 2)));\n'
    '    CMLib_BankSetInt(lv_bank2, "Diag", "PStartNull", lv_dStartNull);\n'
    '    CMLib_BankSetInt(lv_bank2, "Diag", "PStartX", lv_dStartX);\n'
    '    CMLib_BankSetInt(lv_bank2, "Diag", "PgAllCount",\n'
    '                     PlayerGroupCount(PlayerGroupAll()));\n'
    + MARK_END
)


def apply_patch(txt: str) -> str:
    if MARK_BEGIN in txt:
        print("[diag] 已存在补丁，跳过")
        return txt
    assert DECL_ANCHOR in txt, "找不到局部变量声明锚点"
    txt = txt.replace(DECL_ANCHOR, DECL_ANCHOR + DECL_EXTRA, 1)
    assert FLUSH_ANCHOR in txt, "找不到 bank flush 锚点"
    txt = txt.replace(FLUSH_ANCHOR, DIAG_BODY + FLUSH_ANCHOR, 1)
    return txt


def revert_patch(txt: str) -> str:
    if MARK_BEGIN not in txt:
        print("[diag] 无补丁可还原")
        return txt
    txt = txt.replace(DECL_EXTRA, "", 1)
    start = txt.index(MARK_BEGIN)
    end = txt.index(MARK_END) + len(MARK_END)
    return txt[:start] + txt[end:]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "apply"
    txt = SELFTEST.read_text(encoding="utf-8")
    out = apply_patch(txt) if mode == "apply" else revert_patch(txt)
    if out != txt:
        SELFTEST.write_text(out, encoding="utf-8")
        print(f"[diag] {mode} 完成 -> {SELFTEST.name}")
    n = len(re.findall(r"\bCMLibTest_Mark(?:Tag)?\s*\(", out)) \
        - len(re.findall(r"\bvoid\s+CMLibTest_Mark(?:Tag)?\s*\(", out))
    print(f"[diag] 当前断言计数 = {n}（应保持不变）")


main()
