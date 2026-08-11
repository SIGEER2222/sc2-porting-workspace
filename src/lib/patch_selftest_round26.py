"""round26 selftest 补丁 —— 为 74 个新封装的原生符号建立可证伪的真机断言。

判据分两类，泾渭分明，绝不混淆：

  · **硬断言**   有读回路径 / 有独立期望值的，一律写成双向或往返判据。
  · **bank 探针** 读不回来、或期望值没有独立证据的，只记录数值不参与判定。

为什么要这么分：round23 对 sound、round25 对 AISetFilterCanAttackEnemy 都吃过
「把没证据的东西硬写成断言」的亏 —— 要么恒绿（同义反复，删掉守门也照过），
要么恒红（断言与被测系统设计冲突，长期卡同一项）。本轮凡是拿不到独立观测的
（Catalog scope 反射族、TimerWindow 的 8 个无 getter setter、Cinematic、
VictoryPanel、AI Stock），一律降级成探针，不假装成断言。

本轮硬断言覆盖的族与判据形态：

    string   16 条  纯函数，与地图环境无关；大小写 / 包含 / 分词 / 替换全双向
    point     9 条  Lerp 夹紧、PointSet 参数方向、PointsInRange 双向、Height 往返
    region    5 条  SetCenter / SetOffset / AttachToUnit 三组往返 + 解绑反向
    order     5 条  Player 往返、Flag 双向、构造器非 null
    catalog   4 条  EntryClass 同类相等 + 缺失条目不等（排除恒定返回）
                    CatalogReference Get/GetAsInt 交叉一致
    timer     3 条  TimerWindow 可见性双向 + 8 个 setter 之后仍可见
    trig      1 条  TimerLastStarted 与刚启动的 timer 同一句柄
    conv      1 条  Select 变体返回值 == TransmissionLastSent()
    ai        2 条  AISetFilterEnergy 守门（min>max 忽略）+ 限制向真实收窄

口径来源（全部查过官方用例 / natives.galaxy，不靠推测）：

  · StringReplace 是 **1-based 闭区间**：官方
    `StringReplace(name, sub, length-subLength+1, length)` 替换末尾 subLength 字符。
  · CatalogReferenceGet 的 reference 串格式 `"<Catalog>,<Entry>,<Field>"`，
    官方用例 `CatalogReferenceGet("Unit,SoACaster,Food", 0)`。
  · CatalogFieldCount / FieldGet / FieldIsArray / FieldType 在全部官方 .galaxy 里
    **零用例**，scope 串格式无独立证据 —— 所以整族降级成探针。
  · SoundLink("", 0) 是引擎认可的「无语音」写法（见 CMLib_TransSubtitle）。

幂等：每段先查锚点，已存在则跳过。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

SELFTEST = Path(__file__).resolve().parent / "selftest" / "cmlib_selftest.galaxy"

BLOCKS: list[tuple[str, str, str, str]] = []

# --- 1) 主线 Deferred 局部变量（Galaxy 铁律：必须置顶） -------------------------
ANCHOR_VARS = "    camerainfo  lv_r27cam;\n"
NEW_VARS = """    camerainfo  lv_r27cam;
    string      lv_r26s;
    point       lv_r26p1;
    point       lv_r26p2;
    point       lv_r26p3;
    region      lv_r26rg;
    order       lv_r26o;
    timer       lv_r26tm;
    abilcmd     lv_r26ac;
    datetime    lv_r26dt;
    text        lv_r26tx;
    int         lv_r26w;
    int         lv_r26n;
    int         lv_r26t;
"""
BLOCKS.append(("主线变量", "lv_r26p3;", ANCHOR_VARS, NEW_VARS))

# --- 2) 主线硬断言段 -----------------------------------------------------------
ANCHOR_MAIN = "    // ---- 引擎语义探针（诊断用，**不是断言**，不影响通过判定）----\n"

NEW_MAIN = r"""    // =========================================================================
    // round26 —— 74 个新封装原生符号的验收（硬断言部分）
    //
    // 只放"有读回路径 / 有独立期望值"的判据。读不回来的族（Catalog scope 反射、
    // TimerWindow 的无 getter setter、Cinematic、VictoryPanel、AI Stock）
    // 全部在下面的探针段里只记录、不判定 —— 不把"调了没崩"包装成语义断言。
    // =========================================================================

    // ---- string：纯函数，与地图环境完全无关，本轮最硬的一批 ----
    CMLibTest_MarkTag(CMLib_StrCase("aBc", true) == "ABC", "str.case.upper");
    CMLibTest_MarkTag(CMLib_StrCase("aBc", false) == "abc", "str.case.lower");
    // 双向：同一对串，大小写敏感时不等、不敏感时相等。
    // 只写其中一条的话，"恒返回 0"的坏实现能拿满分。
    CMLibTest_MarkTag(CMLib_StrCompare("abc", "abc", c_stringCase) == 0,
                      "str.compare.eq");
    CMLibTest_MarkTag(CMLib_StrCompare("abc", "ABC", c_stringCase) != 0,
                      "str.compare.case.sens");
    CMLibTest_MarkTag(CMLib_StrCompare("abc", "ABC", c_stringNoCase) == 0,
                      "str.compare.case.insens");
    // Contains 三向：命中 / 大小写不匹配落空 / 忽略大小写又命中。
    CMLibTest_MarkTag(CMLib_StrContains("hello world", "world",
                                        c_stringAnywhere, c_stringCase),
                      "str.contains.hit");
    CMLibTest_MarkTag(CMLib_StrContains("hello world", "World",
                                        c_stringAnywhere, c_stringCase) == false,
                      "str.contains.case.miss");
    CMLibTest_MarkTag(CMLib_StrContains("hello world", "World",
                                        c_stringAnywhere, c_stringNoCase),
                      "str.contains.case.insens");
    // location 三档必须真的区分位置，不能退化成"哪档都当 Anywhere"。
    CMLibTest_MarkTag(CMLib_StrContains("hello world", "hello",
                                        c_stringBegin, c_stringCase),
                      "str.contains.begin.hit");
    CMLibTest_MarkTag(CMLib_StrContains("hello world", "world",
                                        c_stringBegin, c_stringCase) == false,
                      "str.contains.begin.miss");
    CMLibTest_MarkTag(CMLib_StrContains("hello world", "world",
                                        c_stringEnd, c_stringCase),
                      "str.contains.end.hit");
    // StringWord 是 1-based —— 这条就是把口径钉死的硬证据。
    // 若实现偷偷改成 0-based，index 1 会拿到 "beta"，立刻红。
    CMLibTest_MarkTag(CMLib_StrWord("alpha beta gamma", 1) == "alpha",
                      "str.word.1based");
    CMLibTest_MarkTag(CMLib_StrWord("alpha beta gamma", 2) == "beta",
                      "str.word.second");
    CMLibTest_MarkTag(CMLib_StrWord("alpha beta gamma", 99) == "",
                      "str.word.oob");
    // maxCount 双向：-1 全替、1 只替第一处。只测全替的话，
    // "永远忽略 maxCount"的实现照样满分。
    CMLibTest_MarkTag(CMLib_StrReplaceWord("a b a", "a", "X",
                                           c_stringReplaceAll, c_stringCase)
                      == "X b X", "str.replaceword.all");
    CMLibTest_MarkTag(CMLib_StrReplaceWord("a b a", "a", "X", 1, c_stringCase)
                      == "X b a", "str.replaceword.limit");
    // StringReplace 是 1-based 闭区间（官方 libCamp 用例 length-subLength+1..length）。
    // 替换第 2~3 个字符 "bc" -> "XY"。
    CMLibTest_MarkTag(CMLib_StrReplaceRange("abcdef", "XY", 2, 3) == "aXYdef",
                      "str.replacerange.1based");

    // ---- point ----
    lv_r26p1 = Point(10.0, 20.0);
    lv_r26p2 = Point(20.0, 20.0);
    // 中点：x 必须落在 15。
    lv_r26p3 = CMLib_PointLerp(lv_r26p1, lv_r26p2, 0.5);
    CMLibTest_MarkTag(lv_r26p3 != null
                      && AbsF(PointGetX(lv_r26p3) - 15.0) < 0.01,
                      "point.lerp.mid");
    // 夹紧双向：>1 收到 dest，<0 收到 source。不夹的话会外推到 30 / 0。
    lv_r26p3 = CMLib_PointLerp(lv_r26p1, lv_r26p2, 2.0);
    CMLibTest_MarkTag(lv_r26p3 != null
                      && AbsF(PointGetX(lv_r26p3) - 20.0) < 0.01,
                      "point.lerp.clamp.hi");
    lv_r26p3 = CMLib_PointLerp(lv_r26p1, lv_r26p2, -1.0);
    CMLibTest_MarkTag(lv_r26p3 != null
                      && AbsF(PointGetX(lv_r26p3) - 10.0) < 0.01,
                      "point.lerp.clamp.lo");
    // PointSet(p1,p2) 把 p2 拷进 p1 —— 参数方向搞反是这族最容易犯的错，
    // 所以同时断言 dst 变了、src 没变。
    lv_r26p3 = Point(1.0, 1.0);
    CMLib_PointCopy(lv_r26p3, lv_r26p2);
    CMLibTest_MarkTag(AbsF(PointGetX(lv_r26p3) - 20.0) < 0.01,
                      "point.copy.dst.updated");
    CMLibTest_MarkTag(AbsF(PointGetX(lv_r26p2) - 20.0) < 0.01,
                      "point.copy.src.untouched");
    // PointsInRange 双向。
    CMLibTest_MarkTag(CMLib_PointsWithin(lv_r26p1, lv_r26p1, 1.0),
                      "points.within.hit");
    CMLibTest_MarkTag(CMLib_PointsWithin(lv_r26p1, lv_r26p2, 1.0) == false,
                      "points.within.miss");
    // 高度往返：设了就得读得回来。
    CMLib_PointSetHeight(lv_r26p1, 7.5);
    CMLibTest_MarkTag(AbsF(PointGetHeight(lv_r26p1) - 7.5) < 0.01,
                      "point.setheight.roundtrip");
    // 不存在的预置点名 -> null（本测试图没有任何预置点）。
    CMLibTest_MarkTag(CMLib_PointByName("__cmlib_no_such_point__") == null,
                      "point.byname.missing.null");

    // ---- region ----
    lv_r26rg = CMLib_RegionCircle(lv_origin, 4.0);
    CMLib_RegionSetCenter(lv_r26rg, Point(33.0, 44.0));
    lv_r26p3 = CMLib_RegionCenter(lv_r26rg);
    CMLibTest_MarkTag(lv_r26p3 != null
                      && AbsF(PointGetX(lv_r26p3) - 33.0) < 0.01,
                      "region.setcenter.roundtrip");
    CMLib_RegionSetOffset(lv_r26rg, Point(3.0, 0.0));
    lv_r26p3 = CMLib_RegionOffset(lv_r26rg);
    CMLibTest_MarkTag(lv_r26p3 != null
                      && AbsF(PointGetX(lv_r26p3) - 3.0) < 0.01,
                      "region.setoffset.roundtrip");
    // 跟随往返 + 解绑反向：只测绑定不测解绑的话，
    // "RegionGetAttachUnit 恒返回最后一个见过的单位"也能骗过去。
    CMLib_RegionAttach(lv_r26rg, lv_marine, Point(0.0, 0.0));
    CMLibTest_MarkTag(CMLib_RegionAttachUnit(lv_r26rg) == lv_marine,
                      "region.attach.roundtrip");
    CMLib_RegionAttach(lv_r26rg, null, Point(0.0, 0.0));
    CMLibTest_MarkTag(CMLib_RegionAttachUnit(lv_r26rg) == null,
                      "region.attach.null.detach");
    CMLibTest_MarkTag(CMLib_RegionByName("__cmlib_no_such_region__") == null,
                      "region.byname.missing.null");

    // ---- order ----
    lv_r26o = CMLib_OrderAt("attack", 0, lv_origin);
    CMLib_OrderSetPlayer(lv_r26o, 5);
    CMLibTest_MarkTag(CMLib_OrderPlayer(lv_r26o) == 5, "order.player.roundtrip");
    // flag 双向。引擎没有为 order flag 导出具名常量，只能传裸 int（0 = queued）。
    CMLib_OrderSetFlag(lv_r26o, 0, true);
    CMLibTest_MarkTag(CMLib_OrderFlag(lv_r26o, 0), "order.flag.set.true");
    CMLib_OrderSetFlag(lv_r26o, 0, false);
    CMLibTest_MarkTag(CMLib_OrderFlag(lv_r26o, 0) == false,
                      "order.flag.set.false");
    // 两个新构造器必须真造得出 order 句柄，不能吞成 null。
    lv_r26ac = AbilityCommand("attack", 0);
    CMLibTest_MarkTag(CMLib_OrderAtRelative(lv_r26ac, lv_origin) != null,
                      "order.atrelative.notnull");
    CMLibTest_MarkTag(CMLib_OrderOnGroup(lv_r26ac, CMLib_UGOf(lv_marine)) != null,
                      "order.ongroup.notnull");

    // ---- catalog：只断言"有独立对照"的两组 ----
    // (1) EntryClass：同为 CUnit 的两个条目必须同类；
    //     不存在的条目必须不同类 —— 后一条排除了"恒返回同一个值"的退化实现。
    lv_r26n = CMLib_CatEntryClass(c_gameCatalogUnit, "Marine");
    CMLibTest_MarkTag(lv_r26n == CMLib_CatEntryClass(c_gameCatalogUnit, "Thor"),
                      "cat.entryclass.same.family");
    CMLibTest_MarkTag(lv_r26n != CMLib_CatEntryClass(c_gameCatalogUnit,
                                                     "__cmlib_no_such_entry__"),
                      "cat.entryclass.missing.differs");
    // (2) CatalogReference：Get 与 GetAsInt 走两条不同的引擎路径，
    //     必须给出一致的数 —— 任一条退化成常量都会立刻不一致。
    lv_r26n = CMLib_CatRefInt("Unit,Marine,LifeMax", c_playerAny);
    lv_r26s = CMLib_CatRefGet("Unit,Marine,LifeMax", c_playerAny);
    CMLibTest_MarkTag(lv_r26n > 0, "cat.ref.int.positive");
    CMLibTest_MarkTag(StringToInt(lv_r26s) == lv_r26n, "cat.ref.get.matches.int");

    // ---- timer / timerwindow ----
    lv_r26tm = CMLib_TimerOnce(60.0);
    // TimerLastStarted 必须就是刚刚那个句柄（CMLib_TimerOnce 内部 TimerStart）。
    CMLibTest_MarkTag(lv_r26tm != null && CMLib_TimerLastStarted() == lv_r26tm,
                      "timer.laststarted.match");
    lv_r26w = CMLib_TimerPanelCreate(lv_r26tm, StringToText("CMLibR26"), false);
    CMLib_TimerPanelShow(lv_r26w, PlayerGroupAll(), true);
    CMLibTest_MarkTag(CMLib_TimerPanelVisible(lv_r26w, 1),
                      "timer.window.visible.true");
    CMLib_TimerPanelShow(lv_r26w, PlayerGroupAll(), false);
    CMLibTest_MarkTag(CMLib_TimerPanelVisible(lv_r26w, 1) == false,
                      "timer.window.visible.false");
    // 8 个无 getter 的 setter 全部打一遍，再回到可见性往返。
    // 这条不是语义断言 —— 它能证伪的是「这串调用会不会把窗口打废 / 打断脚本」，
    // 有 getter 的那天再升级成逐项往返。
    CMLib_TimerPanelBind(lv_r26w, lv_r26tm);
    CMLib_TimerPanelStyle(lv_r26w, 1, true);
    CMLib_TimerPanelMove(lv_r26w, 100, 60);
    CMLib_TimerPanelGap(lv_r26w, 8);
    CMLib_TimerPanelHeight(lv_r26w, 24);
    CMLib_TimerPanelBorder(lv_r26w, true);
    CMLib_TimerPanelProgressBar(lv_r26w, true);
    CMLib_TimerPanelProgressColor(lv_r26w, Color(100.0, 0.0, 0.0), 0);
    CMLib_TimerPanelReset(lv_r26w);
    CMLib_TimerPanelShow(lv_r26w, PlayerGroupAll(), true);
    CMLibTest_MarkTag(CMLib_TimerPanelVisible(lv_r26w, 1),
                      "timer.window.setters.survived");
    CMLib_TimerPanelShow(lv_r26w, PlayerGroupAll(), false);

    // ---- transmission：Select 变体 ----
    // waitUntilDone 必须传 false，否则会把整条主链阻塞住。
    lv_r26t = CMLib_TransSendForPlayerSelect(
                  PlayerGroupAll(), CMLib_TransNone(), CMLIB_TRANS_NO_PORTRAIT,
                  "", "", SoundLink("", 0), StringExternal(""),
                  StringExternal(""), 0.1, CMLIB_TRANS_DUR_SET,
                  false, c_maxPlayers, false);
    CMLibTest_MarkTag(lv_r26t == CMLib_TransLast(),
                      "trans.select.lastsent.match");
    CMLib_TransClear(lv_r26t);

"""
BLOCKS.append(("主线硬断言", "str.case.upper", ANCHOR_MAIN, NEW_MAIN + ANCHOR_MAIN))

# --- 3) 主线 bank 探针段（只记录，不判定） --------------------------------------
ANCHOR_DIAG = "    // ---- 结果落盘 ----\n"

NEW_DIAG = r"""    // ---- round26 探针：**没有独立期望值**的族，只记录不判定 ----
    //
    // Catalog scope 反射族（CatalogFieldCount / FieldGet / FieldIsArray /
    // FieldIsScope / FieldType / FieldTypeCategory）在 reference 下全部官方
    // .galaxy 里**零用例**，scope 串到底该写 "CUnit" 还是别的形态没有独立证据。
    // 拿不到证据就不写断言 —— 先把真实返回值取回来，下一轮再决定升不升级。
    CMLib_BankSetInt(lv_bank, "Result", "R26ScopeFieldCnt",
                     CMLib_CatScopeFieldCount("CUnit"));
    CMLib_BankSetString(lv_bank, "Result", "R26ScopeField1",
                        CMLib_CatScopeFieldAt("CUnit", 1));
    CMLib_BankSetString(lv_bank, "Result", "R26ScopeField0",
                        CMLib_CatScopeFieldAt("CUnit", 0));
    CMLib_BankSetInt(lv_bank, "Result", "R26FieldIsArray",
                     CMLibTest_BoolToInt(CMLib_CatFieldIsArray("CUnit",
                                                               "Abilities")));
    CMLib_BankSetInt(lv_bank, "Result", "R26FieldIsScope",
                     CMLibTest_BoolToInt(CMLib_CatFieldIsScope("CUnit",
                                                               "LifeMax")));
    CMLib_BankSetString(lv_bank, "Result", "R26FieldType",
                        CMLib_CatFieldType("CUnit", "LifeMax"));
    CMLib_BankSetInt(lv_bank, "Result", "R26FieldTypeCat",
                     CMLib_CatFieldTypeCat("CUnit", "LifeMax"));
    CMLib_BankSetInt(lv_bank, "Result", "R26EntryClass",
                     CMLib_CatEntryClass(c_gameCatalogUnit, "Marine"));
    CMLib_BankSetString(lv_bank, "Result", "R26EntryParent",
                        CMLib_CatEntryParent(c_gameCatalogUnit, "Marine"));
    CMLib_BankSetInt(lv_bank, "Result", "R26RefCount",
                     CMLib_CatRefCount("Unit,Marine,Abilities", c_playerAny));
    CMLib_BankSetInt(lv_bank, "Result", "R26Flags",
                     CMLib_CatGetFlags(c_gameCatalogUnit, "Marine",
                                       "Attributes", c_playerAny));

    // StringToAbilCmd 的入参格式（"Abil" 还是 "Abil,index"）没有独立证据 ——
    // 官方用例喂的都是 CatalogFieldValueGet 的原始返回值。两种都试，记下哪种成。
    lv_r26s = CMLib_CatEntryAt(c_gameCatalogAbil, 1);
    CMLib_BankSetInt(lv_bank, "Result", "R26AbilCmdPlain",
                     CMLibTest_BoolToInt(
                         CMLib_AbilCmdAbility(CMLib_AbilCmdFromString(lv_r26s))
                         == lv_r26s));
    CMLib_BankSetInt(lv_bank, "Result", "R26AbilCmdComma",
                     CMLibTest_BoolToInt(
                         CMLib_AbilCmdAbility(
                             CMLib_AbilCmdFromString(lv_r26s + ",0"))
                         == lv_r26s));

    // 预置点 / 预置区域按 id 取：本测试图一个都没预置，恒 null 属预期，
    // 但这测的是"测试图有没有预置"而不是"库对不对" —— 所以只记录。
    CMLib_BankSetInt(lv_bank, "Result", "R26PointById1Null",
                     CMLibTest_BoolToInt(CMLib_PointById(1) == null));
    CMLib_BankSetInt(lv_bank, "Result", "R26RegionById1Null",
                     CMLibTest_BoolToInt(CMLib_RegionById(1) == null));
    // 悬崖等级取自地图地形，值随图变，只记不判。
    CMLib_BankSetInt(lv_bank, "Result", "R26CliffLevel",
                     RoundI(CMLib_PointCliffLevel(lv_origin) * 100.0));
    // PointReflect 的 angle 语义（度 / 弧度、绕谁转）没有独立证据，只记坐标。
    lv_r26p3 = CMLib_PointReflect(Point(10.0, 10.0), Point(20.0, 10.0), 90.0);
    CMLib_BankSetInt(lv_bank, "Result", "R26ReflectX",
                     RoundI(PointGetX(lv_r26p3) * 100.0));

    // 以下几族**没有任何读回路径**（引擎只给了 setter）。
    // 全部打一遍，能证伪的只有"会不会打断 MapScript" —— 脚本一旦中断，
    // 后面的落盘和 Thor 都不会发生，suite 层自然会红。所以这里不发断言。
    CMLib_TransSourceBypassLog(CMLib_TransNone(), true);
    CMLib_TransSourcePauseAllowed(CMLib_TransNone(), true);
    CMLib_TransSourceStreaming(CMLib_TransNone(), true);
    CMLib_TransHideAlertPanel(false);
    CMLib_TransSetOption(CMLIB_TRANS_OPT_HIDE_ALERT_PANEL, false);
    CMLib_VPanelCustomStatisticText(StringExternal(""));
    CMLib_VPanelCustomStatisticValue(StringExternal(""));
    CMLib_VPanelCustomStatisticInt(StringExternal(""), 42);
    // Cinematic：只走"关"和"守门早退"两条路径。真开过场会遮 UI，
    // 而本测试局的证据链要靠 raw observation 读单位，不给它添变数。
    CMLib_CineMode(PlayerGroupAll(), false, 0.0);
    CMLib_CineDataRun(-1, PlayerGroupAll(), false);
    CMLib_CineDataStop();
    CMLib_CineOverlay(false, 0.0, "", 0.0, false);
    // 本地化文本三件套：text / datetime 没有廉价的可比较读回路径，
    // 这里只保证调用路径被真机走过一遍。
    lv_r26tx = CMLib_StrAsset("");
    lv_r26tx = CMLib_StrHotkey("");
    lv_r26dt = CMLib_StrToDateTime("2026-08-10 05:00:00");
    // order 的两个无 getter setter 一并走一遍。
    CMLib_OrderSetPassenger(lv_r26o, null);
    CMLib_OrderSetAbilCmd(lv_r26o, lv_r26ac);
    CMLib_BankSetInt(lv_bank, "Result", "R26OrderPlacement",
                     CMLibTest_BoolToInt(
                         CMLib_OrderSetPlacement(lv_r26o, lv_origin,
                                                 lv_marine, "")));
    CMLib_OrderSetTargetItem(lv_r26o, null);
    CMLib_BankSetInt(lv_bank, "Result", "R26OrderTargetItemNull",
                     CMLibTest_BoolToInt(CMLib_OrderTargetItem(lv_r26o) == null));
    lv_r26o = CMLib_OrderOnItem(lv_r26ac, lv_marine);
    CMLib_BankSetInt(lv_bank, "Result", "R26OrderOnItemNull",
                     CMLibTest_BoolToInt(lv_r26o == null));

"""
BLOCKS.append(("主线探针", "R26ScopeFieldCnt", ANCHOR_DIAG, NEW_DIAG + ANCHOR_DIAG))

# --- 4) AI 链局部变量 ----------------------------------------------------------
ANCHOR_AIVARS = "    int       lv_r27an1;\n"
NEW_AIVARS = """    int       lv_r27an1;
    aifilter  lv_r26af;
    int       lv_r26an;
"""
BLOCKS.append(("AI 变量", "lv_r26af;", ANCHOR_AIVARS, NEW_AIVARS))

# --- 5) AI 链断言 --------------------------------------------------------------
ANCHOR_AI = "    gv_cmlibAIDone = 1;\n"

NEW_AI = r"""    // ---- round26：AISetFilterEnergy 双向判据 -------------------------------
    // 只写守门（min>max 必须忽略）是不够的 —— 一个"永远不把条件传给引擎"的
    // 坏实现照样满分。所以配一条限制向：能量下限拉到没有任何单位够得着，
    // 结果必须真的收窄。两条一起才排除掉"恒等于全集"的退化。
    lv_r24all = UnitGroup(null, c_playerAny, RegionEntireMap(),
                          UnitFilterStr(""), c_noMaxCount);
    lv_r26af = CMLib_AIFilterNew(1);
    CMLib_AIFilterAlliance(lv_r26af, c_playerGroupAny);
    lv_r26an = CMLib_AIFilterApplyCount(lv_r26af, lv_r24all);
    CMLib_AIFilterEnergy(lv_r26af, 100.0, 0.0);
    CMLibTest_MarkTag(CMLib_AIFilterApplyCount(lv_r26af, lv_r24all) == lv_r26an,
                      "ai.filter.energy.badrange.ignored");
    lv_r26af = CMLib_AIFilterNew(1);
    CMLib_AIFilterAlliance(lv_r26af, c_playerGroupAny);
    CMLib_AIFilterEnergy(lv_r26af, 5000.0, 100000.0);
    CMLibTest_MarkTag(lv_r26an > 0
                      && CMLib_AIFilterApplyCount(lv_r26af, lv_r24all) < lv_r26an,
                      "ai.filter.energy.restrictive");

    // AI Stock 三件套没有读回路径（AITechCount 走的是另一套账），
    // 且本测试局玩家 1 是人类、没有 AI 调度器 —— 观测不到就不断言，
    // 只保证调用路径在真机上被走过（崩了会连带整条 AI 链失联）。
    CMLib_StockAlias(1, 1, "Marine", "Marine");
    CMLib_StockFree(1, 1, "Marine", "");
    CMLib_StockTechUncap(1, 0, 0);

"""
BLOCKS.append(("AI 断言", "ai.filter.energy.badrange.ignored",
               ANCHOR_AI, NEW_AI + ANCHOR_AI))


def main() -> int:
    if not SELFTEST.is_file():
        print("[FAIL] 找不到 selftest: %s" % SELFTEST)
        return 2

    txt = SELFTEST.read_text(encoding="utf-8")
    orig = txt
    done: list[str] = []
    skipped: list[str] = []

    for label, guard, anchor, block in BLOCKS:
        if guard in txt:
            skipped.append(label)
            continue
        if anchor not in txt:
            print("  FAIL 找不到锚点（%s）: %r" % (label, anchor))
            return 1
        if txt.count(anchor) != 1:
            print("  FAIL 锚点不唯一（%s，出现 %d 次）"
                  % (label, txt.count(anchor)))
            return 1
        txt = txt.replace(anchor, block, 1)
        done.append(label)

    if txt != orig:
        SELFTEST.write_text(txt, encoding="utf-8")

    for d in done:
        print("  +    %s" % d)
    for s in skipped:
        print("  skip %s（已存在）" % s)
    print("\n[patch_selftest_round26] 新增 %d 段，跳过 %d 段" % (len(done), len(skipped)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
