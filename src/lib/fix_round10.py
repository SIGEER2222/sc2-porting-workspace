"""Round-10 修复：StringFind 索引约定统一 + PlayerStartLocation null 兜底。

真机诊断证据（2026-08-08，test_cmlib.SC2Map 内联档）：
    Diag/CsvCount   = 3       -> SplitCount 计数碰巧对
    Diag/CsvApplied = 2       -> HudFrameCSV 少应用一项
    Diag/Tok0       = "21,"   -> 令牌把分隔符也带出来了
    Diag/Tok1       = "22 ,"  -> 同上
    Diag/Tok2       = (空)    -> 最后一个令牌整个丢失
    Diag/PStartNull = 1       -> PlayerStartLocation(1) 真的返回 null

根因：**SC2 的 `StringFind` 返回 1-based 下标，未找到才返回 -1**
（与 `StringSub` 的 1-based 闭区间约定一致）。`cmlib_core` 的 SplitAt /
SplitCount / ParseFixed 却按 0-based 写，全部 off-by-one。
讽刺的是 `cmlib_board` 的冒号切分写的是正确的 1-based —— 同一个库里两套约定
打架，静态检查器只看 arity 不看语义，所以一直没暴。

影响面（全部走 SplitAt/SplitCount 的 CSV API）：
    cmlib_stock  StockArmyBatch / StockTechBatch
    cmlib_buff   BuffAddCSV
    cmlib_board  BoardHeaders / BoardRow / BoardRowInt / VPanelStatBatch
    cmlib_ui     HudFrameCSV
    cmlib_core   ParseFixed（任何含小数点的串都恒返回 fallback）

修复策略：以引擎实测的 1-based 为唯一约定，改 core 三处；PlayerStart 补 null 兜底
（契约本就是「永不返回 null」，非法槽分支已经返回 Point(0,0)，有效槽却漏了守门）。
"""
import sys
from pathlib import Path

LIB = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib")
CORE = LIB / "scripts" / "cmlib" / "cmlib_core.galaxy"
PLAYER = LIB / "scripts" / "cmlib" / "cmlib_player.galaxy"

# ---------------------------------------------------------------- SplitCount
OLD_SPLITCOUNT = """    lv_count = 1;
    lv_rest = lp_s;
    lv_pos = StringFind(lv_rest, lp_sep, true);
    while ((lv_pos >= 0)) {
        lv_count += 1;
        lv_rest = StringSub(lv_rest, lv_pos + lv_sepLen + 1, StringLength(lv_rest));
        lv_pos = StringFind(lv_rest, lp_sep, true);
    }
    return lv_count;"""

NEW_SPLITCOUNT = """    // StringFind 是 1-based（未找到 = -1）。分隔符占 [lv_pos, lv_pos+sepLen-1]，
    // 所以余串从 lv_pos + sepLen 开始，不是 +sepLen+1。
    lv_count = 1;
    lv_rest = lp_s;
    lv_pos = StringFind(lv_rest, lp_sep, true);
    while ((lv_pos > 0)) {
        lv_count += 1;
        lv_rest = StringSub(lv_rest, lv_pos + lv_sepLen, StringLength(lv_rest));
        lv_pos = StringFind(lv_rest, lp_sep, true);
    }
    return lv_count;"""

# ------------------------------------------------------------------ SplitAt
OLD_SPLITAT = """    lv_current = 0;
    lv_rest = lp_s;
    while (true) {
        lv_pos = StringFind(lv_rest, lp_sep, true);
        if ((lv_pos < 0)) {
            if ((lv_current == lp_index)) {
                return lv_rest;
            }
            return "";
        }
        if ((lv_current == lp_index)) {
            if ((lv_pos == 0)) {
                return "";
            }
            return StringSub(lv_rest, 1, lv_pos);
        }
        lv_rest = StringSub(lv_rest, lv_pos + lv_sepLen + 1, StringLength(lv_rest));
        lv_current += 1;
    }
    return "";"""

NEW_SPLITAT = """    // StringFind 是 1-based（未找到 = -1），StringSub 是 1-based 闭区间。
    // 分隔符出现在 lv_pos，则本段令牌是 [1, lv_pos-1]，余串从 lv_pos+sepLen 起。
    lv_current = 0;
    lv_rest = lp_s;
    while (true) {
        lv_pos = StringFind(lv_rest, lp_sep, true);
        if ((lv_pos <= 0)) {
            if ((lv_current == lp_index)) {
                return lv_rest;
            }
            return "";
        }
        if ((lv_current == lp_index)) {
            if ((lv_pos == 1)) {
                return "";
            }
            return StringSub(lv_rest, 1, lv_pos - 1);
        }
        lv_rest = StringSub(lv_rest, lv_pos + lv_sepLen, StringLength(lv_rest));
        lv_current += 1;
    }
    return "";"""

# --------------------------------------------------------------- ParseFixed
OLD_PARSEFIXED = """    lv_dot = StringFind(lv_trimmed, ".", true);
    if ((lv_dot < 0)) {"""
NEW_PARSEFIXED = """    lv_dot = StringFind(lv_trimmed, ".", true);
    if ((lv_dot <= 0)) {"""

OLD_PARTS = """    lv_intPart = StringSub(lv_trimmed, 1, lv_dot);
    lv_fracPart = StringSub(lv_trimmed, lv_dot + 2, StringLength(lv_trimmed));"""
NEW_PARTS = """    // 1-based：小数点在 lv_dot，整数部分是 [1, lv_dot-1]，小数部分从 lv_dot+1 起。
    // 旧代码按 0-based 写成 (1, lv_dot) / (lv_dot+2, ...)，导致整数部分把小数点
    // 也带进去 -> ParseInt 判非数字 -> 任何 "3.14" 都恒返回 fallback。
    if ((lv_dot <= 1)) {
        lv_intPart = "";
    }
    else {
        lv_intPart = StringSub(lv_trimmed, 1, lv_dot - 1);
    }
    lv_fracPart = StringSub(lv_trimmed, lv_dot + 1, StringLength(lv_trimmed));"""

# -------------------------------------------------------------- PlayerStart
OLD_PSTART = """point CMLib_PlayerStart(int lp_player) {
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return Point(0.0, 0.0);
    }
    return PlayerStartLocation(lp_player);
}"""

NEW_PSTART = """point CMLib_PlayerStart(int lp_player) {
    point lv_p;

    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return Point(0.0, 0.0);
    }
    // 真机实测：没有为该槽位摆开始点的地图（含 API create_game 起的测试图），
    // PlayerStartLocation 会返回 null。本封装的契约是「永不返回 null」，
    // 否则调用方一个 PointGetX 就把整条触发器打断。
    lv_p = PlayerStartLocation(lp_player);
    if ((lv_p == null)) {
        return Point(0.0, 0.0);
    }
    return lv_p;
}"""


def sub(path: Path, pairs):
    txt = path.read_text(encoding="utf-8")
    changed = 0
    for old, new in pairs:
        if new in txt and old not in txt:
            print(f"[fix] {path.name}: 已是修复态，跳过一处")
            continue
        if old not in txt:
            print(f"[fix] !! {path.name}: 找不到锚点\n---\n{old[:120]}\n---")
            sys.exit(1)
        txt = txt.replace(old, new, 1)
        changed += 1
    if changed:
        path.write_text(txt, encoding="utf-8")
    print(f"[fix] {path.name}: 应用 {changed} 处")


sub(CORE, [(OLD_SPLITCOUNT, NEW_SPLITCOUNT),
           (OLD_SPLITAT, NEW_SPLITAT),
           (OLD_PARSEFIXED, NEW_PARSEFIXED),
           (OLD_PARTS, NEW_PARTS)])
sub(PLAYER, [(OLD_PSTART, NEW_PSTART)])
print("[fix] round-10 修复完成")
