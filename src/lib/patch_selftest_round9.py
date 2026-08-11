# -*- coding: utf-8 -*-
"""第 9 轮：为新增 API 追加真机断言（幂等）。

设计原则（沿用前几轮教训）：
  * 能读回的一律做「硬断言」（写进去再读出来），不能读回的才退化为「调用链不抛错」。
  * 全表遍历类断言只跑 c_gameCatalogRace（条目个位数），**绝不**在单位目录上全扫——
    几千次 CatalogFieldValueGet 有撑爆触发器执行预算的风险，一旦触发器被中断，
    后面所有断言连同结果编码单位都不会生成，会被误读成「整库没跑起来」。
  * 任何会改变全局可见状态的调用（HUD 隐藏 / 世界不可见 / 全局暂停）必须成对恢复。
"""
import os, sys, io

SELFTEST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "selftest", "cmlib_selftest.galaxy")

MARKER = "cat.at1"

NEW_LOCALS = """    int     lv_catN;
    string  lv_catE;
    playergroup lv_pg;
    unitgroup lv_gAll;
    fixed   lv_rf;
    int     lv_ri;
    point   lv_pStart;
"""

ASSERTS = """
    // =========================================================================
    // 第 9 轮新增：面板效果(HUD/消息/警报/淡变) + Catalog 全表遍历
    //              + unit/player/math 真缺口
    // =========================================================================

    // ---- catalog：1-based 索引守门（这是本轮封装要解决的核心坑）----
    // CatalogEntryGet 的 index 从 1 开始。下面四条把「0 越界 / 1 有效 / 上界越界 /
    // 反查往返」全部钉死，任何一条挂了都说明索引语义理解错了。
    lv_catN = CMLib_CatCount(c_gameCatalogRace);
    CMLibTest_MarkTag(lv_catN > 0, "cat.count");
    CMLibTest_MarkTag(CMLib_CatEntryAt(c_gameCatalogRace, 0) == "", "cat.at0");
    lv_catE = CMLib_CatEntryAt(c_gameCatalogRace, 1);
    CMLibTest_MarkTag(lv_catE != "", "cat.at1");
    CMLibTest_MarkTag(CMLib_CatEntryAt(c_gameCatalogRace, lv_catN + 1) == "",
                      "cat.over");
    // 反查往返：第 1 条的 id 拿去反查，必须还原成下标 1
    CMLibTest_MarkTag(CMLib_CatFindIndex(c_gameCatalogRace, lv_catE) == 1,
                      "cat.findidx");
    CMLibTest_MarkTag(CMLib_CatFindIndex(c_gameCatalogRace, "__nope__") == 0,
                      "cat.findmiss");

    // ---- catalog：真实数据读回（Marine 的最大生命必须 > 0）----
    CMLibTest_MarkTag(CMLib_CatGetIntFast(c_gameCatalogUnit, "Marine", "LifeMax", 1) > 0,
                      "cat.intfast");
    CMLibTest_MarkTag(CMLib_CatGetIntFast(c_gameCatalogUnit, "", "LifeMax", 1) == 0,
                      "cat.intfast.guard");
    CMLibTest_MarkTag(CMLib_CatFieldCount(c_gameCatalogUnit, "Marine", "WeaponArray", 1) >= 0,
                      "cat.fieldcount");
    CMLibTest_MarkTag(CMLib_CatEntryScope(c_gameCatalogUnit, "") == "", "cat.scope.guard");

    // ---- catalog：全表条件查询（只在 Race 这种小目录上跑）----
    CMLibTest_MarkTag(CMLib_CatCountWhere(c_gameCatalogRace, "Name", "__nope__", 1) == 0,
                      "cat.countwhere");
    CMLibTest_MarkTag(CMLib_CatFirstWhere(c_gameCatalogRace, "Name", "__nope__", 1) == "",
                      "cat.firstwhere");

    // ---- catalog：链接替换守门 ----
    CMLibTest_MarkTag(CMLib_CatLinkSwap(1, c_gameCatalogUnit, "", "Marine") == false,
                      "cat.link.empty");
    CMLibTest_MarkTag(CMLib_CatLinkSwap(1, c_gameCatalogUnit, "__nope__", "Marine") == false,
                      "cat.link.unknown");

    // ---- ui/面板：HUD 框架 CSV 批量（返回实际应用数量，可硬断言）----
    CMLibTest_MarkTag(CMLib_HudFrameCSV(null, "", true) == 0, "hud.csv.empty");
    // "21,22,6" = 小地图 / 命令面板 / 资源栏，三项都恢复为可见
    CMLibTest_MarkTag(CMLib_HudFrameCSV(null, "21, 22 ,6", true) == 3, "hud.csv.three");

    // ---- ui/面板：过场模式必须成对恢复，否则后续观测局 HUD 是隐藏态 ----
    CMLib_HudCinematic(null, true);
    CMLib_HudCinematic(null, false);
    CMLib_HudWorldVisible(null, true);
    CMLibTest_MarkTag(true, "hud.cinematic");

    // ---- ui/面板：消息区（无读回 API，验调用链 + null 玩家组兜底不崩）----
    CMLib_MsgAll(c_messageAreaDebug, StringExternal(""));
    CMLib_Msg(null, c_messageAreaDebug, StringExternal(""));
    CMLib_MsgPlayer(1, c_messageAreaDebug, StringExternal(""));
    CMLib_MsgPlayer(99, c_messageAreaDebug, StringExternal(""));   // 非法槽须被守门
    CMLib_MsgObjective(null, StringExternal(""));
    CMLib_MsgDirective(null, StringExternal(""));
    CMLib_MsgError(null, StringExternal(""));
    CMLib_MsgSubtitle(null, StringExternal(""));
    CMLib_MsgWarning(null, StringExternal(""));
    CMLib_MsgClear(null, c_messageAreaDebug);
    CMLib_MsgClearAll();
    CMLibTest_MarkTag(true, "ui.msg");

    // ---- ui/面板：警报守门（null point / null unit 原生会抛错）----
    CMLib_AlertAtPoint("", 1, StringExternal(""), "", null);
    CMLib_AlertAtUnit("", 1, StringExternal(""), "", null);
    CMLib_AlertAtPoint("", 99, StringExternal(""), "", lv_origin);
    CMLibTest_MarkTag(true, "ui.alert.guard");

    // ---- ui/面板：淡变与动画事件（无效控件必须静默跳过而不是抛错）----
    CMLib_UIFade(c_invalidDialogControlId, null, 1.0, 0.5);
    CMLib_UIFadeIn(c_invalidDialogControlId, null, 1.0);
    CMLib_UIFadeOut(c_invalidDialogControlId, null, -5.0);   // 负时长须被钳为 0
    CMLib_UIAnimEvent(c_invalidDialogControlId, null, "Show");
    CMLib_UIAnimEvent(c_invalidDialogControlId, null, "");
    CMLibTest_MarkTag(true, "ui.fade.guard");

    // ---- unit：过滤器匹配（真单位必须匹配 alive 过滤器，null 必须 false）----
    CMLibTest_MarkTag(CMLib_UnitMatchFilter(null, 1, CMLib_FilterAlive()) == false,
                      "unit.filter.null");
    CMLibTest_MarkTag(CMLib_UnitMatchFilter(lv_probe, 1, CMLib_FilterAlive()) == true,
                      "unit.filter.alive");

    // ---- unit：归属转移守门 ----
    CMLibTest_MarkTag(CMLib_UnitChangeOwner(null, 1, true) == false, "unit.owner.null");
    CMLibTest_MarkTag(CMLib_UnitChangeOwner(lv_probe, 99, true) == false, "unit.owner.slot");
    CMLibTest_MarkTag(CMLib_UnitChangeOwner(lv_probe, 1, true) == true, "unit.owner.ok");

    // ---- unit：类型名 + 全局暂停（只调 false，绝不在自测里真的暂停）----
    CMLib_UnitTypeName("");
    CMLib_UnitTypeName("Marine");
    CMLib_UnitsPauseAll(false);
    CMLibTest_MarkTag(true, "unit.typename");

    // ---- unitgroup：整组下令守门 ----
    CMLibTest_MarkTag(CMLib_UGIssueOrder(null, null, c_orderQueueReplace) == false,
                      "ug.order.null");
    lv_gAll = CMLib_UGAlliance(1, c_unitAllianceAny, null, CMLib_FilterAlive(), 0);
    CMLibTest_MarkTag(lv_gAll != null, "ug.alliance.notnull");
    // 本局我方已经生成了 Ghost/Marine/SCV，同盟查询必须至少捞到 1 个
    CMLibTest_MarkTag(UnitGroupCount(lv_gAll, c_unitCountAll) >= 1, "ug.alliance.hit");
    CMLibTest_MarkTag(CMLib_UGOrderAbility(lv_gAll, "", 0, c_orderQueueReplace) == false,
                      "ug.order.emptyabil");
    CMLibTest_MarkTag(CMLib_UGOrderAbilityAtUnit(lv_gAll, "attack", 0, null,
                                                 c_orderQueueReplace) == false,
                      "ug.order.nulltarget");
    // 非法玩家槽必须返回空组而不是崩
    CMLibTest_MarkTag(UnitGroupCount(CMLib_UGAlliance(99, c_unitAllianceAny, null,
                                                      CMLib_FilterAlive(), 0),
                                     c_unitCountAll) == 0,
                      "ug.alliance.badslot");
    CMLibTest_MarkTag(CMLib_UGEnemiesOf(1, 0) != null, "ug.enemies");
    CMLibTest_MarkTag(CMLib_UGAlliesOf(1, 0) != null, "ug.allies");

    // ---- player：静态属性 + 非法槽兜底 ----
    lv_pStart = CMLib_PlayerStart(1);
    CMLibTest_MarkTag(lv_pStart != null, "pl.start");
    // 非法槽返回 Point(0,0) 而不是 null —— 这是本封装的兜底契约
    CMLibTest_MarkTag(CMLib_PlayerStart(99) != null, "pl.start.badslot");
    CMLibTest_MarkTag(CMLib_PlayerDiff(99) == 0, "pl.diff.badslot");
    CMLibTest_MarkTag(CMLib_PlayerRaceOf(1) != "", "pl.race");
    CMLibTest_MarkTag(CMLib_PlayerRaceOf(99) == "", "pl.race.badslot");
    lv_pg = CMLib_PGCopyOf(null);
    CMLibTest_MarkTag(lv_pg != null, "pl.pgcopy.null");
    CMLibTest_MarkTag(PlayerGroupCount(CMLib_PGCopyOf(PlayerGroupSingle(1))) == 1,
                      "pl.pgcopy.one");
    CMLibTest_MarkTag(CMLib_PGAllianceOf(c_playerGroupAlly, 1) != null, "pl.pgally");
    CMLibTest_MarkTag(PlayerGroupCount(CMLib_PGAllianceOf(c_playerGroupAlly, 99)) == 0,
                      "pl.pgally.badslot");

    // ---- core：随机边界自动交换 + 取模除零兜底 ----
    // RandomFixed(5,1) 这种反序区间在原生里行为未定义；封装后必须落在 [1,5]。
    lv_rf = CMLib_RandF(5.0, 1.0);
    CMLibTest_MarkTag((lv_rf >= 1.0) && (lv_rf <= 5.0), "core.randf.swap");
    lv_ri = CMLib_RandI(10, 1);
    CMLibTest_MarkTag((lv_ri >= 1) && (lv_ri <= 10), "core.randi.swap");
    // ModI(x, 0) 会抛除零错误并中断整个触发器 —— 这是最有价值的一条守门
    CMLibTest_MarkTag(CMLib_ModSafe(7, 0) == 0, "core.mod.zero");
    CMLibTest_MarkTag(CMLib_ModSafe(7, 3) == 1, "core.mod.ok");
"""

ANCHOR = "    // ---- 结果落盘 ----"
LOCAL_ANCHOR = "    unit    lv_probe;\n"


def main():
    with io.open(SELFTEST, encoding="utf-8") as fh:
        txt = fh.read()

    if MARKER in txt:
        print("SKIP — selftest 已包含第 9 轮断言")
        return 0

    if LOCAL_ANCHOR not in txt:
        print("ERROR — 找不到局部变量锚点")
        return 1
    if ANCHOR not in txt:
        print("ERROR — 找不到结果落盘锚点")
        return 1

    # Galaxy 硬约束：局部变量必须全部声明在函数体最顶部，中段声明会导致
    # 整个 MapScript 静默不编译（第 8 轮真机踩过，Ghost=0）。
    txt = txt.replace(LOCAL_ANCHOR, LOCAL_ANCHOR + NEW_LOCALS, 1)
    txt = txt.replace(ANCHOR, ASSERTS + "\n" + ANCHOR, 1)

    with io.open(SELFTEST, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(txt)

    n = txt.count("CMLibTest_Mark(") + txt.count("CMLibTest_MarkTag(")
    n -= txt.count("void CMLibTest_Mark(") + txt.count("void CMLibTest_MarkTag(")
    print("PATCHED selftest — 断言总数现为 " + str(n))
    return 0


if __name__ == "__main__":
    sys.exit(main())
