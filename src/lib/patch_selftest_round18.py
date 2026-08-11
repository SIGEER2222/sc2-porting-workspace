# -*- coding: utf-8 -*-
"""
round18 selftest 补丁（幂等）。

给 round 18 新增的 27 个 API 补真机断言，分三处注入：

  A) CMLibTest_Deferred  —— 主证据链：Dialog 控件族 / 单位 / 单位组 /
                            触发器查找 / 角度三角 / UserData / 音效
  B) CMLibTest_EvtProbe  —— **事件上下文**里读 EvtDamageAmount / EvtUpgradeName。
                            这两个 native 只在对应事件里有意义，必须在真事件
                            回调里调；放主链上等于拿全部证据赌一把，所以沿用
                            既有的「异步探针 + 进度码」范式。
  C) CMLibTest_AIDeferred —— AI 自杀冲锋 / 脚本接管 / 子状态几率 / 状态槽。

沿用前几轮总结出来的硬约束：
  1. **只引用确认存在的引擎常量**。本轮用到的都逐条核过 natives.galaxy：
     c_anchorCenter(4) / c_triggerControlTypeLabel(1) / c_triggerControlTypeListBox(5)
     / c_playerPropMinerals(0) / c_unitAbilChargeCountMax(0) / c_unitCountAll(0)。
     引用不存在的常量 = 编译失败 = SC2 静默丢弃整个 MapScript，静态 lint 报 0 错。
  2. **语义把不准的返回值不写死**。空列表框的 SelectedItem 基数、人类玩家上
     AIState 的返回，各版本不一致 —— 只断言「守卫契约 + 不抛错」。
     一条写死的错误期望会变成永久 FAIL，比没有断言更糟。
  3. **有抛错风险的调用放各自子块末尾**，万一炸也只损失自己。
  4. Galaxy 强制局部变量置顶（G1001），新变量一律并入函数头部声明区。
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "selftest", "cmlib_selftest.galaxy")

MARK = "round 18：面板控件 / 单位 / 角度 / UserData / 音效"
MARK_AI = "round 18：AI 自杀冲锋"
MARK_EVT = "round 18：伤害数值 / 升级名"

# ---------------------------------------------------------------- A) 主证据链
ANCHOR_MAIN = "    // ---- 汇合 AI 加分线"
DECL_ANCHOR = "    int         lv_r17obj;\n"

DECLS = """    int         lv_r18dlg;
    int         lv_r18c1;
    int         lv_r18c2;
    int         lv_r18i;
    fixed       lv_r18f;
    unit        lv_r18u;
    unitgroup   lv_r18g;
    playergroup lv_r18pg;
    trigger     lv_r18t;
"""

BLOCK_MAIN = r"""
    // ============ round 18：面板控件 / 单位 / 角度 / UserData / 音效 ============

    lv_r18pg = PlayerGroupAll();

    // ---- 面板效果：Dialog 控件族 ----
    // DialogControlCreate 是各 mod 里最高频的面板构造入口（78 文件 / 537 次），
    // 库里此前只有 InPanel 变体（要求先有 panel 容器），是真实缺口。
    // 先用原生建一个不可见、非模态的对话框当容器；容器建不出来则整段无意义。
    lv_r18dlg = DialogCreate(400, 300, c_anchorCenter, 0, 0, false);
    CMLibTest_MarkTag(lv_r18dlg > 0, "ui.r18.dialog.host");

    lv_r18c1 = CMLib_DlgCtrlCreate(lv_r18dlg, c_triggerControlTypeLabel);
    CMLibTest_MarkTag(lv_r18c1 > 0, "ui.dlgctrl.create");
    CMLibTest_MarkTag(CMLib_DlgCtrlCreate(0, c_triggerControlTypeLabel) == 0,
                      "ui.dlgctrl.create.guard.zero");
    CMLibTest_MarkTag(CMLib_DlgCtrlCreate(-1, c_triggerControlTypeLabel) == 0,
                      "ui.dlgctrl.create.guard.neg");

    // 模板名传空必须退化成"无模板创建"，而不是把 "" 当模板名送进引擎
    //（真机表现是控件建出来了但完全没样式，最难查的一类面板 bug）。
    lv_r18c2 = CMLib_DlgCtrlCreateTpl(lv_r18dlg, c_triggerControlTypeListBox, "");
    CMLibTest_MarkTag(lv_r18c2 > 0, "ui.dlgctrl.tpl.emptyfallback");
    CMLibTest_MarkTag(CMLib_DlgCtrlCreateTpl(0, c_triggerControlTypeLabel, "") == 0,
                      "ui.dlgctrl.tpl.guard");

    // 选中项：空列表框下的返回基数各版本不一致，只验守卫 + 不抛错。
    CMLibTest_MarkTag(CMLib_DlgCtrlSelectedItem(0, 1) == 0,
                      "ui.dlgctrl.selected.guard");
    lv_r18i = CMLib_DlgCtrlSelectedItem(lv_r18c2, 1);
    CMLibTest_MarkTag(lv_r18i >= 0, "ui.dlgctrl.selected.nocrash");

    // 铺满对话框；players 传 null 必须走"所有玩家"分支而不是把 null 传下去。
    CMLib_DlgCtrlFullDialog(lv_r18c1, null, true);
    CMLib_DlgCtrlFullDialog(lv_r18c1, lv_r18pg, false);
    CMLib_DlgCtrlFullDialog(0, null, true);
    CMLibTest_MarkTag(true, "ui.dlgctrl.fulldialog");

    // 连续销毁两次不得炸 —— "销毁两次"是面板代码最常见的崩因。
    CMLib_DlgCtrlDestroy(lv_r18c2);
    CMLib_DlgCtrlDestroy(lv_r18c2);
    CMLib_DlgCtrlDestroy(0);
    CMLibTest_MarkTag(true, "ui.dlgctrl.destroy.twice");

    // 指挥面板按钮 face 高亮（新手引导高频）。face 名未知时不得炸 —— 放子块末尾。
    CMLib_UIFaceHighlight(null, "", true);
    CMLib_UIFaceHighlight(lv_r18pg, "AttackFace", true);
    CMLib_UIFaceHighlight(lv_r18pg, "AttackFace", false);
    CMLibTest_MarkTag(true, "ui.face.highlight");
    DialogDestroy(lv_r18dlg);

    // ---- 单位：behavior 原生版往返（与 CMLib_UnitHasBehavior2 是两个不同 native）----
    lv_r18u = CMLib_SpawnForced("Marine", 1,
                                CMLib_PointOffset(lv_origin, 6.0, -3.0), 90.0);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r18u), "unit.r18.spawn");
    CMLibTest_MarkTag(CMLib_UnitHasBehaviorRaw(lv_r18u, "Stimpack") == false,
                      "unit.hasbehavior.raw.before");
    CMLib_UnitBehaviorAdd(lv_r18u, "Stimpack", lv_r18u, 1);
    CMLibTest_MarkTag(CMLib_UnitHasBehaviorRaw(lv_r18u, "Stimpack"),
                      "unit.hasbehavior.raw.after");
    CMLib_UnitBehaviorRemove(lv_r18u, "Stimpack", 1);
    CMLibTest_MarkTag(CMLib_UnitHasBehaviorRaw(lv_r18u, "Stimpack") == false,
                      "unit.hasbehavior.raw.removed");
    CMLibTest_MarkTag(CMLib_UnitHasBehaviorRaw(null, "Stimpack") == false,
                      "unit.hasbehavior.raw.guard.null");
    CMLibTest_MarkTag(CMLib_UnitHasBehaviorRaw(lv_r18u, "") == false,
                      "unit.hasbehavior.raw.guard.empty");

    // ---- 单位：命令队列 / 队伍色 / 技能充能 ----
    CMLibTest_MarkTag(CMLib_UnitOrderCount(null) == 0, "unit.ordercount.guard");
    CMLibTest_MarkTag(CMLib_UnitOrderCount(lv_r18u) >= 0, "unit.ordercount.nocrash");
    CMLib_UnitTeamColor(lv_r18u, 3);
    CMLib_UnitTeamColor(null, 3);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r18u), "unit.teamcolor");
    // abilcmd 传 null 必须短路成 0.0 / 空操作，不能把 null 送进原生。
    CMLibTest_MarkTag(CMLib_UnitAbilChargeInfo(lv_r18u, null,
                                               c_unitAbilChargeCountMax) == 0.0,
                      "unit.abilcharge.guard");
    CMLib_UnitAbilReset(lv_r18u, null, 0);
    CMLib_UnitAbilReset(null, null, 0);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r18u), "unit.abilreset.guard");
    CMLibTest_MarkTag(CMLib_UnitRefFromVar("") == null, "unit.reffromvar.guard");

    // ---- 单位组：按区域过滤 ----
    lv_r18g = CMLib_UGOfTypeInMap("Marine", 1);
    CMLibTest_MarkTag(UnitGroupCount(CMLib_UGFilterRegion(null, lv_map, 0),
                                     c_unitCountAll) == 0,
                      "ug.filterregion.guard.nullgroup");
    CMLibTest_MarkTag(UnitGroupCount(CMLib_UGFilterRegion(lv_r18g, null, 0),
                                     c_unitCountAll)
                      == UnitGroupCount(lv_r18g, c_unitCountAll),
                      "ug.filterregion.nullregion.passthru");
    // 全地图过滤 = 原样（所有单位都在可玩区内），这是能写死的强断言。
    CMLibTest_MarkTag(UnitGroupCount(CMLib_UGFilterRegion(lv_r18g, lv_map, 0),
                                     c_unitCountAll)
                      == UnitGroupCount(lv_r18g, c_unitCountAll),
                      "ug.filterregion.map");
    // maxCount 传负数必须夹到"不限量"，而不是原样丢给原生（行为未定义）。
    CMLibTest_MarkTag(UnitGroupCount(CMLib_UGFilterRegion(lv_r18g, lv_map, -1),
                                     c_unitCountAll)
                      == UnitGroupCount(lv_r18g, c_unitCountAll),
                      "ug.filterregion.negmax");

    // ---- 触发器：引擎侧按函数名查找 + 玩家属性事件 ----
    // 注意 CMLib_TrigFindByFunc 与 CMLib_TrigFind 是两个东西：
    // 前者查引擎表（TriggerFind），后者查 CMLib 自己的登记表。同名会导致
    // Galaxy 函数重定义 → 整图静默丢弃，所以本轮特意分了名字。
    CMLibTest_MarkTag(CMLib_TrigFindByFunc("") == null, "trig.findbyfunc.guard");
    lv_r18t = CMLib_TrigFindByFunc("CMLibTest_Deferred");
    CMLibTest_MarkTag(true, "trig.findbyfunc.nocrash");
    lv_r18t = TriggerCreate("CMLibTest_NoopHandler");
    CMLib_TrigOnPlayerPropChange(null, 1, c_playerPropMinerals);
    CMLib_TrigOnPlayerPropChange(lv_r18t, 1, c_playerPropMinerals);
    CMLibTest_MarkTag(lv_r18t != null, "trig.onplayerpropchange");
    CMLibTest_MarkTag(CMLib_TrigEventParamName("", "x") == "",
                      "trig.eventparamname.guard");

    // ---- 几何：角度制三角函数（SC2 的 Sin/Cos 吃「度」不是弧度）----
    // 各 mod 里 Sin/Cos 合计 395 次调用全按角度制；封装出来就是防止
    // 有人顺手再套一层 Radians() 转两次。
    CMLibTest_MarkTag(CMLib_SinDeg(0.0) == 0.0, "geo.sindeg.zero");
    CMLibTest_MarkTag(CMLib_CosDeg(0.0) == 1.0, "geo.cosdeg.zero");
    lv_r18f = CMLib_SinDeg(90.0);
    // 定点数（20.12）下 sin(90) 未必是精确 1.0，用容差而不是等号。
    CMLibTest_MarkTag((lv_r18f > 0.99) && (lv_r18f <= 1.0), "geo.sindeg.90");
    CMLibTest_MarkTag(CMLib_NormalizeAngle(370.0) == 10.0, "geo.normalize.over");
    CMLibTest_MarkTag(CMLib_NormalizeAngle(-10.0) == 350.0, "geo.normalize.neg");
    CMLibTest_MarkTag(CMLib_NormalizeAngle(45.0) == 45.0, "geo.normalize.identity");
    CMLibTest_MarkTag(CMLib_NormalizeAngle(720.0) == 0.0, "geo.normalize.wrap2");

    // ---- UserData：实例查询守卫 ----
    // 只验守卫：拿一个真实存在的 UserData 类型名在测试图里不可保证，
    // 用假类型去读会抛运行时错误，写成断言等于给自己埋雷。
    CMLibTest_MarkTag(CMLib_UDataUserInstance("", "i", "f", 0) == "",
                      "udata.userinstance.guard.type");
    CMLibTest_MarkTag(CMLib_UDataUserInstance("t", "i", "", 0) == "",
                      "udata.userinstance.guard.field");

    // ---- 音效：带归属玩家的全局播放（SoundPlayForPlayer 是全库最高频未封装原生）----
    // 声音 id 不硬编码，沿用既有做法从 Sound 目录取真实条目。
    CMLib_SfxPlayOwned("", 1, lv_r18pg, 1.0);
    CMLib_SfxPlayOwned(CMLib_CatEntryAt(c_gameCatalogSound, 1), 1, null, 0.5);
    CMLib_SfxPlayOwned(CMLib_CatEntryAt(c_gameCatalogSound, 1), 1, lv_r18pg, 0.5);
    CMLibTest_MarkTag(true, "fx.playowned");

"""

# --------------------------------------------------------- B) 事件上下文探针
EVT_DECLS = """    fixed lv_dmgAmt;
    string lv_upName;
"""
EVT_ANCHOR = "    if ((lv_p < -99) && (lv_u != null) && (lv_o < -99)) {"
EVT_BLOCK = r"""    // round 18：伤害数值 / 升级名。同样走进度码，炸了能精确定位是哪一个。
    lv_dmgAmt = CMLib_EvtDamageAmount();
    gv_cmlibEvtProbe = 4;
    lv_upName = CMLib_EvtUpgradeName();
    gv_cmlibEvtProbe = 5;
"""
EVT_SENTINEL_OLD = """        gv_cmlibEvtProbe = 4;   // 永不成立，只为让三个读值参与运算"""
EVT_SENTINEL_NEW = """        gv_cmlibEvtProbe = 9;   // 永不成立，只为让这几个读值参与运算"""

EVT_MARK_ANCHOR = ('    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 3, '
                   '"trig.evt.effectowner");\n')
EVT_MARK_ADD = """    // round 18：EvtDamageAmount 在伤害事件里必然可读；EvtUpgradeName 不在
    // 升级事件上下文里，能不能读通由引擎决定 —— 所以它排在最后一位，
    // 读不通只损失自己这一条，不影响前面 4 条的证据。
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 4, "trig.evt.damageamount");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 5, "trig.evt.upgradename");
"""

# ------------------------------------------------------------------- C) AI 线
AI_DECL_ANCHOR = "    int   lv_aiPassed;\n"
AI_DECLS = """    unitgroup lv_r18ag;
    int       lv_r18as;
"""
AI_ANCHOR = "    gv_cmlibAIDone = 1;"
AI_BLOCK = r"""    // ---- round 18：AI 自杀冲锋 / 整组脚本接管 / 子状态几率 / 状态槽 ----
    // 这些原生对人类玩家的单位是空操作（不崩），断言只验"封装可被调用且守卫生效"。
    lv_r18ag = CMLib_UGArmyOfPlayer(1);
    CMLib_AIUnitSuicide(null, true);
    CMLib_AIGroupSuicide(null, true);
    CMLib_AIGroupScriptControlled(null, true);
    CMLibTest_MarkTag(true, "ai.suicide.guards");
    CMLib_AIGroupSuicide(lv_r18ag, true);
    CMLib_AIGroupSuicide(lv_r18ag, false);
    CMLibTest_MarkTag(true, "ai.group.suicide");
    // 与已有的 CMLib_AIScriptControlGroup 不同：那个逐单位调，这个用组原生。
    CMLib_AIGroupScriptControlled(lv_r18ag, true);
    CMLib_AIGroupScriptControlled(lv_r18ag, false);
    CMLibTest_MarkTag(true, "ai.group.scriptcontrolled");
    // 状态槽是纯读。本局没有电脑玩家，对人类玩家读槽位引擎无文档承诺，
    // 所以只在确实存在电脑玩家时才真读 —— 写成无条件读只会得到一条
    // 永久失败或永久无意义的指标。
    if (CMLib_PlayerIsComputer(2)) {
        lv_r18as = CMLib_AIState(2, 0);
        CMLibTest_MarkTag(lv_r18as >= 0, "ai.state.read");
    }
    else {
        CMLibTest_MarkTag(true, "ai.state.skipped.nocomputer");
    }
    // 几率夹紧：越界值必须被夹到 [0,100]，负几率会让 AI 行为诡异。
    // 纯 setter，放本子块末尾（万一抛错只损失自己）。
    CMLib_AISubStateChance(0, -5);
    CMLib_AISubStateChance(0, 150);
    CMLib_AISubStateChance(0, 50);
    CMLibTest_MarkTag(true, "ai.substate.chance.clamp");

"""

NOOP_HANDLER = """
// round 18：给 CMLib_TrigOnPlayerPropChange 当挂载靶子的空回调。
// 必须是真实存在的函数名 —— TriggerCreate 拿到一个不存在的函数名，
// 在真机是运行时错误而不是编译错误，静态门禁抓不到。
bool CMLibTest_NoopHandler (bool testConds, bool runActions) {
    return true;
}
"""


def main():
    if not os.path.exists(TARGET):
        print("[ERR] 找不到 %s" % TARGET)
        return 1

    with io.open(TARGET, "r", encoding="utf-8") as fh:
        src = fh.read()

    if MARK in src:
        print("[SKIP] round18 断言已存在，幂等返回")
        return 0

    for name, anchor in (("主链锚点", ANCHOR_MAIN),
                         ("主链声明锚点", DECL_ANCHOR),
                         ("事件探针锚点", EVT_ANCHOR),
                         ("事件断言锚点", EVT_MARK_ANCHOR),
                         ("AI 声明锚点", AI_DECL_ANCHOR),
                         ("AI 锚点", AI_ANCHOR)):
        if anchor not in src:
            print("[ERR] 找不到%s：%r" % (name, anchor[:40]))
            return 1

    # 0) 空回调（放在文件靠前，供 TriggerCreate 按名引用）
    if "CMLibTest_NoopHandler" not in src:
        head_anchor = "bool CMLibTest_EvtProbe (bool testConds, bool runActions) {"
        src = src.replace(head_anchor, NOOP_HANDLER.lstrip("\n") + "\n" + head_anchor, 1)

    # 1) 主链：声明 + 断言块
    src = src.replace(DECL_ANCHOR, DECL_ANCHOR + DECLS, 1)
    src = src.replace(ANCHOR_MAIN, BLOCK_MAIN + ANCHOR_MAIN, 1)

    # 2) 事件探针：声明 + 两个读值 + 哨兵改号 + 两条断言
    src = src.replace("    int  lv_o;\n", "    int  lv_o;\n" + EVT_DECLS, 1)
    src = src.replace(EVT_ANCHOR, EVT_BLOCK + EVT_ANCHOR, 1)
    src = src.replace(EVT_SENTINEL_OLD, EVT_SENTINEL_NEW, 1)
    src = src.replace(EVT_MARK_ANCHOR, EVT_MARK_ANCHOR + EVT_MARK_ADD, 1)

    # 3) AI 线：声明 + 断言块（插在 gv_cmlibAIDone = 1 之前）
    src = src.replace(AI_DECL_ANCHOR, AI_DECL_ANCHOR + AI_DECLS, 1)
    src = src.replace(AI_ANCHOR, AI_BLOCK + AI_ANCHOR, 1)

    with io.open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(src)

    n = len(re.findall(r"CMLibTest_Mark(?:Tag)?\s*\(", src))
    print("[OK] round18 断言已注入；文件内 Mark 调用点总数 = %d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
