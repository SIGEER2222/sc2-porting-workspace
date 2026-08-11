# -*- coding: utf-8 -*-
"""
round19 selftest 补丁（幂等）。

给 round 19 新增的 65 个 API 补真机断言，分四处注入：

  A) CMLibTest_Deferred   —— 主证据链：ConversationData 守卫族 / 事件挂载族 /
                             相机信息 / 单位造价 / 能力命令 / 文本 / 预载 / 游戏态
  B) CMLibTest_EvtProbe   —— 11 个新事件取参 native 的**非事件上下文**安全探针，
                             沿用 round18 的「进度码」范式，炸了能精确定位是哪一个。
  C) CMLibTest_R19Probe   —— 新增。有抛错风险的「真调用」（可跳过区段 / 作弊开关 /
                             科技树帮助 / 录像停止 / 音乐暂停 / AI 计时 / Ping 全族），
                             同样走进度码，逐步计分，不搞「一炸全灭」。
  D) CMLibTest_R19TimerProbe —— 真·计时器事件上下文里读 CMLib_EvtTimer()，
                             这是本轮唯一一个能在真事件回调里取证的取参 native。

硬约束（前几轮血泪，逐条遵守）：
  1. 只引用**逐条核过 natives.galaxy 的常量**：
     c_keySpace(39) / c_keyA(13) / c_keyModifierStateIgnore(0)/Require(1)/Exclude(2)
     / c_unitCostMinerals(0) / c_cameraValueDistance(4) / c_gameCatalogAbil(0)
     / c_unitBehaviorChangeAny(-1) / c_unitCountAll。
     c_soundtrackCategoryMusic 定义在 GameData/Soundtrack.galaxy（不保证被 include），
     故这里用字面量 1 并注释说明 —— 宁可丑，不可赌。
  2. **color / camerainfo 是值类型，绝不与 null 比较**（round18 血泪）。
  3. 语义把不准的返回值不写死；假 id 的真调用一律不做（会抛运行时错误）。
  4. 有抛错风险的真调用全部隔离进 C) 的进度码探针。
  5. Galaxy 强制局部变量置顶（G1001），新变量并入函数头部声明区。
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "selftest", "cmlib_selftest.galaxy")

MARK = "round 19：数据驱动对白"
MARK_EVT = "round 19：事件取参补齐"

# ----------------------------------------------------------------- 全局声明
GLOBAL_ANCHOR = "int gv_cmlibAIDone;\n"
GLOBALS_ADD = """
// round 19：真·计时器事件取参探针 + 有风险真调用的进度码
trigger gt_CMLibR19Timer;
timer   gv_r19Timer;
int     gv_r19TimerOk;
int     gv_cmlibR19Prog;
"""

# ------------------------------------------------------- D) 计时器事件回调
TIMER_HANDLER = """
// round 19：唯一能在**真事件上下文**里取证的取参 native。
// gv_r19TimerOk：1 = EventTimer() 返回非 null；2 = 且与自己启动的那个计时器同一句柄。
bool CMLibTest_R19TimerProbe (bool testConds, bool runActions) {
    timer lv_t;

    lv_t = CMLib_EvtTimer();
    if (lv_t != null) {
        gv_r19TimerOk = 1;
        if (lv_t == gv_r19Timer) {
            gv_r19TimerOk = 2;
        }
    }
    return true;
}

// round 19：有抛错风险的「真调用」隔离探针。
// 走进度码而不是一个布尔：任何一步炸了，前面已完成的步骤照样计分，
// 且主链能精确报出停在第几步 —— 比「整块失败」的信息量高一个量级。
bool CMLibTest_R19Probe (bool testConds, bool runActions) {
    int   lv_ping;
    point lv_pos;
    playergroup lv_pg;

    lv_pg  = PlayerGroupAll();
    lv_pos = CMLibTest_Origin();

    // 1) 可跳过区段：wait=false，立即返回；onSkip 传 null 走「无回调」路径。
    CMLib_SkippableBegin(null, 0, null, false, false);
    CMLib_SkippableEnd();
    gv_cmlibR19Prog = 1;

    // 2) 可玩区域重设为自身 —— 语义等价 no-op，只验通路。
    CMLib_PlayableMapSet(RegionPlayableMap());
    gv_cmlibR19Prog = 2;

    // 3) 作弊开关：显式关闭，不改变对局状态。
    CMLib_GameCheat(0, false);
    gv_cmlibR19Prog = 3;

    // 4) 科技树帮助文本：display=false（关闭），不污染 UI。
    CMLib_TechTreeUnitHelp(1, "Marine", false);
    gv_cmlibR19Prog = 4;

    // 5) 停止录像：本来就没在录，应为 no-op。
    CMLib_MovieRecStop();
    gv_cmlibR19Prog = 5;

    // 6) 音乐暂停：pause=false（恢复），不改变听感。1 = Music 分类
    //    （c_soundtrackCategoryMusic 在 GameData/Soundtrack.galaxy，不保证 include）。
    CMLib_MusicPause(lv_pg, 1, false, false);
    gv_cmlibR19Prog = 6;

    // 7) AI 计时恢复。
    CMLib_AITimePause(false);
    gv_cmlibR19Prog = 7;

    // 8) Ping 真创建。modelLink 传空 —— 不赌任何具体 ping 模型资源存在。
    //    返回 0 也不算失败：下面 6 个 setter 全部有 `ping <= 0` 守卫，
    //    走守卫路径同样证明「不抛错」，这正是守卫存在的意义。
    lv_ping = PingCreate(lv_pg, "", lv_pos, Color(100.0, 100.0, 100.0), 5.0);
    gv_cmlibR19Prog = 8;

    // 9) Ping 属性全族。
    CMLib_PingShow(lv_ping, false);
    CMLib_PingMove(lv_ping, lv_pos);
    CMLib_PingTint(lv_ping, Color(100.0, 0.0, 0.0));
    CMLib_PingRotate(lv_ping, 90.0);
    CMLib_PingModel(lv_ping, "");
    CMLib_PingLifetime(lv_ping, 1.0);
    gv_cmlibR19Prog = 9;

    // 10) 回收。id 为 0 时不调 —— PingDestroy(0) 无文档承诺。
    if (lv_ping > 0) {
        PingDestroy(lv_ping);
    }
    gv_cmlibR19Prog = 10;

    return true;
}
"""
TIMER_HANDLER_ANCHOR = "bool CMLibTest_EvtProbe (bool testConds, bool runActions) {"

# --------------------------------------------------- B) EvtProbe 进度码扩展
EVT_DECLS = """    string lv_r19dmgEff;
    order  lv_r19order;
    unit   lv_r19tu;
    point  lv_r19tp;
    wave   lv_r19wave;
    int    lv_r19key;
    bool   lv_r19shift;
    string lv_r19btn;
"""
EVT_DECL_ANCHOR = "    string lv_upName;\n"

EVT_ANCHOR = "    if ((lv_p < -99) && (lv_u != null) && (lv_o < -99)) {"
EVT_BLOCK = r"""    // ---- round 19：事件取参补齐（11 个）----
    // 与 round18 同一范式：在**非事件上下文**下逐个读，进度码逐格推进。
    // 这些 native 在无事件时按引擎惯例返回默认值而不抛错 —— 但那是「惯例」，
    // 不是承诺，所以必须用探针取证而不是想当然写进主链。
    lv_r19dmgEff = CMLib_EvtDamageEffect();
    gv_cmlibEvtProbe = 6;
    lv_r19order = CMLib_EvtOrder();
    gv_cmlibEvtProbe = 7;
    lv_r19tu = CMLib_EvtTarget();
    gv_cmlibEvtProbe = 8;
    lv_r19tp = CMLib_EvtTargetPoint();
    gv_cmlibEvtProbe = 9;
    lv_r19wave = CMLib_EvtWave();
    gv_cmlibEvtProbe = 10;
    lv_r19key = CMLib_EvtKey();
    gv_cmlibEvtProbe = 11;
    lv_r19shift = CMLib_EvtKeyShift();
    gv_cmlibEvtProbe = 12;
    lv_r19shift = CMLib_EvtKeyCtrl();
    gv_cmlibEvtProbe = 13;
    lv_r19shift = CMLib_EvtKeyAlt();
    gv_cmlibEvtProbe = 14;
    lv_r19btn = CMLib_EvtButton();
    gv_cmlibEvtProbe = 15;
    if ((lv_r19dmgEff == "@@never@@") && (lv_r19btn == "@@never@@") && (lv_r19key < -99)
        && (lv_r19order != null) && (lv_r19tu != null) && (lv_r19tp != null)
        && (lv_r19wave != null) && lv_r19shift) {
        gv_cmlibEvtProbe = 99;  // 永不成立，只为让这几个读值参与运算
    }
"""

# ------------------------------------------------------------- A) 主证据链
DECL_ANCHOR = "    trigger     lv_r18t;\n"
DECLS = """    playergroup lv_r19pg;
    unitgroup   lv_r19g;
    trigger     lv_r19trig;
    camerainfo  lv_r19cam;
    string      lv_r19s;
    bool        lv_r19b;
    text        lv_r19t;
"""

ANCHOR_MAIN = "    // ---- 汇合 AI 加分线"

BLOCK_MAIN = r"""
    // ============ round 19：数据驱动对白 / 事件族 / 相机 / 造价 / 预载 ============
    // 本轮起点是一次**误判纠正**：前几轮把 conversation 域 9.9% 的覆盖率记成
    // 「GUI 自动生成访问器噪声」，本轮逐条回 natives.galaxy 核对，
    // 证明 ConversationData* 全族是引擎正经 API —— 那是真空白，不是噪声。

    lv_r19pg = PlayerGroupAll();

    // ---- ConversationData：数据驱动对白 ----
    // 测试图里没有 Conversation 数据条目，拿假 id 去 Run 会抛运行时错误。
    // 因此这里只验守卫路径（沿用 round18 UserData 的处置口径）：
    // 空 id / null 玩家组必须原地返回，绝不把空串送进引擎。
    CMLib_ConvDataRun("", lv_r19pg, 0, false);
    CMLib_ConvDataRun("X", null, 0, false);
    CMLib_ConvDataRunAll("");
    CMLibTest_MarkTag(true, "conv.datarun.guards");
    CMLibTest_MarkTag(CMLib_ConvDataCanRun("", false) == false, "conv.canrun.guard");
    CMLibTest_MarkTag(CMLib_ConvDataSound("", true) == "", "conv.sound.guard");
    CMLib_ConvDataLinePlayers("", "l", lv_r19pg);
    CMLib_ConvDataLinePlayers("c", "", lv_r19pg);
    CMLib_ConvDataLinePlayers("c", "l", null);
    CMLib_ConvDataLineReset("", "l");
    CMLib_ConvDataLineReset("c", "");
    CMLibTest_MarkTag(true, "conv.line.guards");
    // camerainfo 是值类型：只能取默认值传进去，绝不与 null 比较。
    lv_r19cam = CameraInfoDefault();
    CMLib_ConvDataCamera("", "c", lv_r19cam, null, false);
    CMLib_ConvDataCamera("cam", "", lv_r19cam, null, false);
    CMLibTest_MarkTag(true, "conv.camera.guards");
    CMLib_ConvDataStateSet("", 5);
    CMLibTest_MarkTag(CMLib_ConvDataStateGet("") == 0, "conv.state.guard");
    lv_r19t = CMLib_ConvDataStateTextOf("", "i");
    CMLibTest_MarkTag(true, "conv.statetext.guard");

    // ---- 事件族补齐：按键 / 按钮 / 升级等级 / 行为分类 ----
    // 只验「挂载链不抛错 + null 守卫」；取参一侧在 EvtProbe 里走进度码。
    lv_r19trig = TriggerCreate("CMLibTest_NoopHandler");
    CMLib_OnKeyPressed(null, 1, c_keySpace, true);
    CMLib_OnKeyPressedMod(null, 1, c_keySpace, true,
                          c_keyModifierStateIgnore, c_keyModifierStateIgnore,
                          c_keyModifierStateIgnore);
    CMLib_OnButtonPressed(null, 1, "b");
    CMLib_OnButtonPressed(lv_r19trig, 1, "");
    CMLib_OnUpgradeLevelChanged(null, 1);
    CMLib_OnBehaviorCategoryChange(null, null, 0, c_unitBehaviorChangeAny);
    CMLibTest_MarkTag(true, "trig.r19.event.guards");
    CMLib_OnKeyPressed(lv_r19trig, 1, c_keySpace, true);
    CMLibTest_MarkTag(true, "trig.onkey.mount");
    CMLib_OnKeyPressedMod(lv_r19trig, 1, c_keyA, true,
                          c_keyModifierStateRequire, c_keyModifierStateExclude,
                          c_keyModifierStateIgnore);
    CMLibTest_MarkTag(true, "trig.onkey.mod.mount");
    CMLib_OnButtonPressed(lv_r19trig, 1, "CMLibR19Button");
    CMLibTest_MarkTag(true, "trig.onbutton.mount");
    CMLib_OnUpgradeLevelChanged(lv_r19trig, 1);
    CMLibTest_MarkTag(true, "trig.onupgradelevel.mount");
    CMLib_OnBehaviorCategoryChange(lv_r19trig, null, 0, c_unitBehaviorChangeAny);
    CMLibTest_MarkTag(true, "trig.onbehaviorcat.mount");
    // 挂完就关：行为分类事件挂在「任意单位」上，本图里会被反复触发。
    // 回调虽是空函数，但让它空转属于给后续断言引入噪声。
    CMLib_TrigOff(lv_r19trig);

    // ---- 真·计时器事件上下文里的取参（1.0s 触发，此刻 2.0s 必已跑过）----
    CMLibTest_MarkTag(gv_r19TimerOk >= 1, "trig.evt.timer.nonnull");
    CMLibTest_MarkTag(gv_r19TimerOk >= 2, "trig.evt.timer.identity");

    // ---- 相机信息：值类型读取 ----
    // CameraInfoDefault() 一定有效，距离必为正 —— 这是本组里少数
    // 能写「真语义断言」而不是「不抛错」的地方。
    CMLibTest_MarkTag(CMLib_CamInfoValue(lv_r19cam, c_cameraValueDistance) > 0.0,
                      "fx.caminfo.distance");
    CMLibTest_MarkTag(CMLib_CamInfoTarget(lv_r19cam) != null, "fx.caminfo.target");
    CMLib_CamBounds(null, lv_map, true);
    CMLib_CamBounds(lv_r19pg, null, true);
    CMLibTest_MarkTag(true, "fx.cambounds.guards");
    CMLib_CamBounds(lv_r19pg, lv_map, true);
    CMLibTest_MarkTag(true, "fx.cambounds.set");
    lv_r19g = CMLib_UGArmyOfPlayer(1);
    CMLib_CamFollowGroup(0, lv_r19g, false, false);
    CMLib_CamFollowGroup(1, null, false, false);
    CMLibTest_MarkTag(true, "fx.camfollow.guards");
    CMLib_CamFollowGroup(1, lv_r19g, false, false);
    CMLibTest_MarkTag(true, "fx.camfollow.set");
    CMLib_CamApplyData(null, "c");
    CMLib_CamApplyData(lv_r19pg, "");
    CMLibTest_MarkTag(true, "fx.camdata.guards");

    // ---- 音乐 / 头像 / 文本浮标：守卫 ----
    CMLib_MusicPause(null, 1, false, false);
    CMLib_MusicDefault(null, 1, "s", 0, 0);
    CMLib_MusicDefault(lv_r19pg, 1, "", 0, 0);
    CMLibTest_MarkTag(true, "fx.music.guards");
    CMLib_PortraitShow(0, lv_r19pg, true, false);
    CMLib_PortraitShow(1, null, true, false);
    CMLibTest_MarkTag(true, "fx.portrait.guards");
    CMLib_TextTagShowFor(0, lv_r19pg, true);
    CMLib_TextTagShowFor(1, null, true);
    CMLibTest_MarkTag(true, "fx.texttag.showfor.guards");
    CMLib_MovieRecStart("");
    CMLibTest_MarkTag(true, "fx.movierec.guard");

    // ---- Ping 属性族：守卫（真创建在 R19Probe 里做）----
    CMLib_PingShow(0, true);
    CMLib_PingShow(-1, true);
    CMLib_PingMove(0, lv_origin);
    CMLib_PingMove(1, null);
    CMLib_PingTint(0, Color(100.0, 100.0, 100.0));
    CMLib_PingRotate(0, 45.0);
    CMLib_PingModel(0, "m");
    CMLib_PingModel(1, "");
    CMLib_PingLifetime(0, 1.0);
    CMLibTest_MarkTag(true, "fx.ping.guards");

    // ---- 预载族：守卫 + CSV 分发 ----
    // 空路径必须原地返回：把 "" 送进 Preload* 是最典型的「静默无效」陷阱。
    CMLib_PreloadModel("", true);
    CMLib_PreloadMovie("", true);
    CMLib_PreloadAsset("", false);
    CMLib_PreloadImage("", true);
    CMLib_PreloadSound("", false);
    CMLibTest_MarkTag(true, "fx.preload.guards");
    CMLibTest_MarkTag(CMLib_PreloadCSV("", "a,b", true) == 0, "fx.preloadcsv.guard.kind");
    CMLibTest_MarkTag(CMLib_PreloadCSV("model", "", true) == 0, "fx.preloadcsv.guard.csv");
    // 未知 kind：分词循环照样跑满 3 轮，只是不落任何引擎调用 —— 这条同时
    // 证明了「循环不炸」和「未知 kind 不误派发」，比单纯守卫断言信息量大。
    CMLibTest_MarkTag(CMLib_PreloadCSV("nope", "a,b,c", true) == 0,
                      "fx.preloadcsv.unknownkind");

    // ---- 单位造价 / 载具卸载组 / 能力命令 ----
    CMLibTest_MarkTag(CMLib_UnitTypeCost("", c_unitCostMinerals) == 0,
                      "unit.typecost.guard");
    CMLibTest_MarkTag(CMLib_UnitTypeCost("Marine", c_unitCostMinerals) > 0,
                      "unit.typecost.marine");
    // 非 cargo 事件上下文下原生返回 null，封装必须退化成空组而不是把 null 漏出去 ——
    // 漏出去的下场是调用方 UnitGroupCount(null) 直接抛错。
    lv_r19g = CMLib_UnitCargoLastGroup();
    CMLibTest_MarkTag(lv_r19g != null, "unit.cargolastgroup.nonnull");
    CMLibTest_MarkTag(UnitGroupCount(lv_r19g, c_unitCountAll) == 0,
                      "unit.cargolastgroup.empty");
    // abilcmd 往返：从 Abil 目录取真实条目，不硬编码任何技能 id。
    lv_r19s = CMLib_CatEntryAt(c_gameCatalogAbil, 1);
    if (lv_r19s != "") {
        CMLibTest_MarkTag(CMLib_AbilCmdAbility(AbilityCommand(lv_r19s, 0)) == lv_r19s,
                          "unit.abilcmd.ability.roundtrip");
    }
    else {
        CMLibTest_MarkTag(true, "unit.abilcmd.skipped.nocatalog");
    }

    // ---- 文本：时间格式化 / 词替换 ----
    // text 的相等比较在各版本行为不一，只验「可调用 + 负值被夹到 0」的通路。
    lv_r19t = CMLib_TimeText(StringToText("mm:ss"), -5);
    lv_r19t = CMLib_TimeText(StringToText("mm:ss"), 65);
    CMLibTest_MarkTag(true, "text.timeformat");
    lv_r19t = CMLib_TextReplace(StringToText("aXbXc"), StringToText("X"),
                                StringToText("-"), 0, false);
    lv_r19t = CMLib_TextReplace(StringToText("aXbXc"), StringToText("X"),
                                StringToText("-"), 1, true);
    CMLibTest_MarkTag(true, "text.replaceword");

    // ---- 游戏态 / 背景 / 可玩区域 / 科技树 守卫 ----
    lv_r19b = CMLib_GameOnline();
    lv_r19b = CMLib_GameTestMap(false);
    CMLibTest_MarkTag(true, "game.state.query");
    CMLib_GameBackground(0, "", 1.0);
    CMLibTest_MarkTag(true, "game.background.guard");
    CMLib_PlayableMapSet(null);
    CMLibTest_MarkTag(true, "geo.playablemapset.guard");
    CMLib_TechTreeUnitHelp(0, "Marine", false);
    CMLib_TechTreeUnitHelp(1, "", false);
    CMLibTest_MarkTag(true, "ai.techtreehelp.guards");
    CMLibTest_MarkTag(CMLib_UDataImagePath("", "i", "f", 0) == "",
                      "udata.imagepath.guard.type");
    CMLibTest_MarkTag(CMLib_UDataImagePath("t", "i", "", 0) == "",
                      "udata.imagepath.guard.field");

    // ---- round 19：有风险真调用的进度码探针 ----
    // 同步执行（探针内没有 Wait），跑完立刻读进度码。
    gv_cmlibR19Prog = 0;
    TriggerExecute(TriggerCreate("CMLibTest_R19Probe"), false, false);
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 1,  "trig.skippable.roundtrip");
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 2,  "geo.playablemapset.self");
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 3,  "game.cheat.allow");
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 4,  "ai.techtreehelp.real");
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 5,  "fx.movierec.stop");
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 6,  "fx.music.pause.real");
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 7,  "ai.timepause");
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 8,  "fx.ping.create");
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 9,  "fx.ping.setters");
    CMLibTest_MarkTag(gv_cmlibR19Prog >= 10, "fx.ping.destroy");

    // ---- round 19：事件取参补齐的进度码（探针在主链更早处已执行）----
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 6,  "trig.evt.damageeffect");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 7,  "trig.evt.order");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 8,  "trig.evt.target");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 9,  "trig.evt.targetpoint");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 10, "trig.evt.wave");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 11, "trig.evt.key");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 12, "trig.evt.key.shift");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 13, "trig.evt.key.ctrl");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 14, "trig.evt.key.alt");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 15, "trig.evt.button");

"""

# --------------------------------------------- 计时器探针的挂载（SelfTest 内）
SELFTEST_ANCHOR = """    gt_CMLibDeferred = TriggerCreate("CMLibTest_Deferred");"""
SELFTEST_ADD = """    // round 19：1.0s 后触发的计时器事件 —— 主链 2.0s 才跑，读得到结果。
    // 这是本轮唯一在**真事件上下文**里取证的取参 native，比非上下文探针强得多。
    gv_r19TimerOk = 0;
    gv_r19Timer = TimerCreate();
    gt_CMLibR19Timer = TriggerCreate("CMLibTest_R19TimerProbe");
    TriggerAddEventTimer(gt_CMLibR19Timer, gv_r19Timer);
    TimerStart(gv_r19Timer, 1.0, false, c_timeGame);

"""


def main():
    with io.open(TARGET, "r", encoding="utf-8") as fh:
        src = fh.read()

    if MARK in src:
        print("[SKIP] round19 断言已存在，幂等返回")
        return 0

    checks = (
        ("全局锚点", GLOBAL_ANCHOR),
        ("计时器回调锚点", TIMER_HANDLER_ANCHOR),
        ("EvtProbe 声明锚点", EVT_DECL_ANCHOR),
        ("EvtProbe 注入锚点", EVT_ANCHOR),
        ("主链声明锚点", DECL_ANCHOR),
        ("主链锚点", ANCHOR_MAIN),
        ("SelfTest 锚点", SELFTEST_ANCHOR),
    )
    for name, anchor in checks:
        if anchor not in src:
            print("[ERR] 找不到%s：%r" % (name, anchor[:50]))
            return 1

    src = src.replace(GLOBAL_ANCHOR, GLOBAL_ANCHOR + GLOBALS_ADD, 1)
    src = src.replace(TIMER_HANDLER_ANCHOR,
                      TIMER_HANDLER.lstrip("\n") + "\n" + TIMER_HANDLER_ANCHOR, 1)
    src = src.replace(EVT_DECL_ANCHOR, EVT_DECL_ANCHOR + EVT_DECLS, 1)
    src = src.replace(EVT_ANCHOR, EVT_BLOCK + EVT_ANCHOR, 1)
    src = src.replace(DECL_ANCHOR, DECL_ANCHOR + DECLS, 1)
    src = src.replace(ANCHOR_MAIN, BLOCK_MAIN + ANCHOR_MAIN, 1)
    src = src.replace(SELFTEST_ANCHOR, SELFTEST_ADD + SELFTEST_ANCHOR, 1)

    with io.open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(src)

    n = len(re.findall(r"CMLibTest_Mark(?:Tag)?\s*\(", src))
    print("[OK] round19 断言已注入；文件内 Mark 调用点总数 = %d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
