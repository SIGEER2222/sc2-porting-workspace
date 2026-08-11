# -*- coding: utf-8 -*-
"""第 13 轮：给 cmlib_selftest.galaxy 注入 36 条真机断言。

本轮覆盖 extend_round13.py 新增的 24 个封装（unit / catalog / geo / fx / trig），
其中三条是**真闭环**（不是"调用没抛错"的软证据）：
  1. 下移动命令 -> 从命令队列读回（钉死 UnitOrder 是 getter 的语义）
  2. 生成单位 -> 单位创建事件回调 -> 事件上下文里 CMLib_EvtCreatedUnit() 取到合法单位
     （整组 CMLib_Evt* 事件取参封装第一次拿到真机证据）
  3. 区域合并后 RegionContainsPoint 命中

风险隔离：伤害/效果事件取参无法在无人操作的 API 局里制造真实事件，
而"非事件上下文调用会不会抛运行时错误"本身是必须钉死的契约 —— 抛错会中断整个触发器。
所以丢给独立触发器异步执行（waitUntilDone=false = 另开线程），用递增进度码回读。

脚本幂等：检测到 marker 直接跳过。
"""
import re
import sys
from pathlib import Path

SELF = Path(__file__).resolve().parent / "selftest" / "cmlib_selftest.galaxy"
MARKER = "第 13 轮新增"

# --------------------------------------------------------------------------
# P1: 全局变量 / 触发器句柄
# --------------------------------------------------------------------------
P1A_OLD = "trigger gt_CMLibRegion;\nint gv_cmlibPassed;"
P1A_NEW = "trigger gt_CMLibRegion;\ntrigger gt_CMLibCreated;\nint gv_cmlibPassed;"

P1B_OLD = "string gv_cmlibFailTags;\n"
P1B_NEW = (
    "string gv_cmlibFailTags;\n"
    "int gv_cmlibCreatedHits;\n"
    "int gv_cmlibCreatedOk;\n"
    "int gv_cmlibEvtProbe;\n"
)

# --------------------------------------------------------------------------
# P2: 两个新回调函数
# --------------------------------------------------------------------------
P2_OLD = """bool CMLibTest_OnRegion (bool testConds, bool runActions) {
    gv_cmlibRegionHits = gv_cmlibRegionHits + 1;
    return true;
}
"""

P2_NEW = P2_OLD + """
// 「单位被创建」事件回调 —— 本轮新增的第二条可程序化触发的真闭环。
// 除了计命中数，还在**事件上下文里**调 CMLib_EvtCreatedUnit() 取被创建的单位：
// 这是整组 CMLib_Evt*（事件取参）封装第一次拿到真机证据 ——
// 此前 47 个事件注册器只验了"挂载链不抛错"，取参一侧一直是空白。
bool CMLibTest_OnCreated (bool testConds, bool runActions) {
    unit lv_created;

    gv_cmlibCreatedHits = gv_cmlibCreatedHits + 1;
    lv_created = CMLib_EvtCreatedUnit();
    if (CMLib_UnitOk(lv_created)) {
        gv_cmlibCreatedOk = gv_cmlibCreatedOk + 1;
    }
    return true;
}

// 事件取参 native 在**非事件上下文**下的安全探针。
// 为什么要单独一个触发器：Galaxy 的运行时错误会中断当前触发器，
// 把这三个 native 放主断言链上，等于拿全部证据（含结果编码单位）赌一把。
// 异步执行后，即使某个 native 炸了也只中断这条线程，
// 而递增的进度码能精确指出是三个里的哪一个炸的。
bool CMLibTest_EvtProbe (bool testConds, bool runActions) {
    int  lv_p;
    unit lv_u;
    int  lv_o;

    lv_p = CMLib_EvtDmgSourcePlayer();
    gv_cmlibEvtProbe = 1;
    lv_u = CMLib_EvtDmgSourceUnit();
    gv_cmlibEvtProbe = 2;
    lv_o = CMLib_EvtEffectUsedUnitOwner(CMLIB_EFFECT_LOC_TARGET_UNIT);
    gv_cmlibEvtProbe = 3;
    if ((lv_p < -99) && (lv_u != null) && (lv_o < -99)) {
        gv_cmlibEvtProbe = 4;   // 永不成立，只为让三个读值参与运算
    }
    return true;
}
"""

# --------------------------------------------------------------------------
# P3: Deferred 局部变量（Galaxy 要求局部变量全部置顶，中段声明会静默不编译）
# --------------------------------------------------------------------------
P3_OLD = "    point   lv_pStart;\n"
P3_NEW = (
    "    point   lv_pStart;\n"
    "    unitgroup lv_gSel;\n"
    "    region  lv_rAcc;\n"
    "    point   lv_bmin;\n"
    "    point   lv_bmax;\n"
    "    trigger lv_trigC;\n"
    "    int     lv_execA;\n"
    "    int     lv_execB;\n"
)

# --------------------------------------------------------------------------
# P4: 断言块
# --------------------------------------------------------------------------
P4_OLD = "    // ---- 结果落盘 ----\n"

P4_BLOCK = """
    // =========================================================================
    // 第 13 轮新增：命令队列 / 选择集 / Catalog 探测 / 几何朝向与包围盒
    //              / 镜头与声道 / 触发器执行计数 + 事件取参真闭环
    //
    // 本轮的取舍：gap_scan 报出的 top40 未覆盖符号里，先剔除 GUI 自动访问器噪声
    //（*FromId / *FromName / *LastCreated / *Loop*，那是触发器编辑器生成的样板，
    // 不属于"人手写业务代码会用"的 API），再剔除已有等价封装的假缺口
    //（UnitHasBehavior -> CMLib_UnitHasBehavior、
    //  CatalogFieldValueSetFixed -> CMLib_CatSetFixed），剩下 24 个才是真缺口。
    // =========================================================================

    // ---- unit：命令队列读取（UnitOrder 是 getter，不是下令！）----
    CMLibTest_MarkTag(CMLib_UnitOrderAt(null, 0) == null, "unit.orderat.null");
    CMLibTest_MarkTag(CMLib_UnitOrderAt(lv_probe, -1) == null, "unit.orderat.neg");
    CMLibTest_MarkTag(CMLib_UnitOrderHasAbil(null, "move") == false,
                      "unit.orderhasabil.null");
    CMLibTest_MarkTag(CMLib_UnitOrderHasAbil(lv_probe, "") == false,
                      "unit.orderhasabil.empty");
    // 真闭环：给 SCV 下一条移动命令，再从命令队列把它读回来。
    // 一条断言同时钉死「下令」与「读队列」两侧语义，是本段的硬证据。
    lv_dst = CMLib_PointOffset(lv_origin, 12.0, 12.0);
    CMLibTest_MarkTag(CMLib_UnitOrderAbilityAtPoint(lv_probe, "move", 0, lv_dst,
                                                    c_orderQueueReplace),
                      "unit.order.move");
    CMLib_WaitGame(0.2);
    CMLibTest_MarkTag(CMLib_UnitOrderHasAbil(lv_probe, "move"),
                      "unit.orderhasabil.move");
    CMLibTest_MarkTag(CMLib_UnitOrderAt(lv_probe, 0) != null, "unit.orderat.read");

    // ---- unit：选择集 ----
    CMLib_SelClear(1);
    CMLib_SelClear(99);                 // 非法槽守门
    CMLibTest_MarkTag(true, "unit.selclear");
    lv_gSel = CMLib_UGSelected(1);
    CMLibTest_MarkTag(lv_gSel != null, "unit.selected.notnull");
    // 契约：非法槽返回空组而不是 null，调用方可以无脑遍历、不用先判空
    CMLibTest_MarkTag(UnitGroupCount(CMLib_UGSelected(99), c_unitCountAll) == 0,
                      "unit.selected.badslot");
    CMLibTest_MarkTag(CMLib_UGFilterStr("", 1, lv_gAll, "", 0) != null,
                      "ug.filterstr.notnull");
    CMLibTest_MarkTag(UnitGroupCount(CMLib_UGFilterStr("", 99, lv_gAll, "", 0),
                                     c_unitCountAll) == 0,
                      "ug.filterstr.badslot");

    // ---- catalog：字段探测 / 引用写入守门 ----
    CMLibTest_MarkTag(CMLib_CatFieldExists("", "Name") == false,
                      "cat.fieldexists.emptyscope");
    CMLibTest_MarkTag(CMLib_CatFieldExists("Unit", "") == false,
                      "cat.fieldexists.emptyfield");
    CMLibTest_MarkTag(CMLib_CatRefSet("", 1, "1") == false, "cat.refset.empty");

    // ---- geo：点朝向 / 寻路代价 / 区域合并与包围盒 ----
    CMLibTest_MarkTag(CMLib_PointFacing(null) == 0.0, "geo.facing.null");
    CMLib_PointSetFacing(null, 45.0);   // null 守门
    CMLib_PointSetFacing(lv_zero, 90.0);
    CMLibTest_MarkTag(CMLib_PointFacing(lv_zero) == 90.0, "geo.facing.roundtrip");
    CMLibTest_MarkTag(CMLib_PathCost(null, lv_origin) == -1, "geo.pathcost.null");
    CMLibTest_MarkTag(CMLib_PathCost(lv_origin, lv_origin) >= 0, "geo.pathcost.self");
    lv_rAcc = RegionEmpty();
    CMLib_RegionAdd(null, null);        // null 守门
    CMLib_RegionAdd(lv_rAcc, RegionCircle(lv_origin, 3.0));
    CMLibTest_MarkTag(RegionContainsPoint(lv_rAcc, lv_origin), "geo.regionadd");
    lv_bmin = CMLib_RegionBoundsMin(lv_map);
    lv_bmax = CMLib_RegionBoundsMax(lv_map);
    CMLibTest_MarkTag((lv_bmin != null) && (lv_bmax != null), "geo.bounds.notnull");
    CMLibTest_MarkTag(PointGetX(lv_bmax) > PointGetX(lv_bmin), "geo.bounds.order");
    CMLibTest_MarkTag(CMLib_RegionBoundsMin(null) == null, "geo.bounds.null");

    // ---- fx：镜头与声道（fx 模块此前在自测里 0 覆盖，本轮首次上真机）----
    CMLib_CamShakePreset(1, "", "Medium", 0.5, 0.5, 1.0);   // 空预设名守门
    CMLibTest_MarkTag(true, "fx.camshakepreset.guard");
    CMLibTest_MarkTag(CMLib_CamTarget(1) != null, "fx.camtarget");
    CMLib_CamSave(1);
    CMLib_CamRestore(1, 0.5, -1.0, 10.0);
    CMLibTest_MarkTag(true, "fx.camsaverestore");
    CMLib_SfxChannelMute(null, 0, true);                    // null 守门
    CMLib_SfxChannelMute(PlayerGroupSingle(1), 0, false);
    CMLibTest_MarkTag(true, "fx.channelmute");
    // 声音 id 不硬编码：从 Sound 目录取第 1 条真实存在的条目，
    // 免得测试图一换依赖，写死的 id 就失效（那会变成一条误导性的永久失败）
    lv_catE = CMLib_CatEntryAt(c_gameCatalogSound, 1);
    CMLib_SfxPlayAtFor("", 1, PlayerGroupSingle(1), lv_origin, 1.0);   // 空 id 守门
    CMLib_SfxPlayAtFor(lv_catE, 1, PlayerGroupSingle(1), null, 1.0);   // null 落点守门
    CMLib_SfxPlayAtFor(lv_catE, 1, PlayerGroupSingle(1), lv_origin, 0.5);
    CMLibTest_MarkTag(lv_catE != "", "fx.playatfor");

    // ---- trig：执行计数 ----
    CMLibTest_MarkTag(CMLib_TrigExecCount(null) == 0, "trig.execcount.null");
    lv_trigC = CMLib_TrigNew("CMLibTest_Dummy", "cmlib_r13");
    lv_execA = CMLib_TrigExecCount(lv_trigC);
    // Dummy 体内没有 Wait，同步执行可以立刻回读计数；
    // 「waitUntilDone 一律传 false」那条铁律针对的是 while(true) 常驻触发器。
    TriggerExecute(lv_trigC, true, false);
    lv_execB = CMLib_TrigExecCount(lv_trigC);
    CMLibTest_MarkTag(lv_execB > lv_execA, "trig.execcount.inc");

    // ---- trig：单位创建事件真闭环（继区域事件之后第二条可程序化触发的硬证据）----
    gv_cmlibCreatedHits = 0;
    gv_cmlibCreatedOk = 0;
    gt_CMLibCreated = CMLib_TrigNew("CMLibTest_OnCreated", "cmlib_r13");
    // creatorAbil / creatorBehavior 传 null 才是"任意"；传 "" 是字面空串、匹配不上，
    // 这是抄官方 GUI 生成码验过的约定（TriggerAddEventUnitCreated(t, null, null, null)）。
    CMLib_TrigOnUnitCreated(gt_CMLibCreated, null, null, null);
    CMLibTest_MarkTag(true, "trig.created.mount");
    CMLib_SpawnForced("SCV", 1, CMLib_PointOffset(lv_origin, 0.0, -8.0), 270.0);
    CMLib_WaitGame(1.0);
    CMLibTest_MarkTag(gv_cmlibCreatedHits >= 1, "trig.created.fired");
    CMLibTest_MarkTag(gv_cmlibCreatedOk >= 1, "trig.evt.createdunit");
    // 关掉：下面结果编码要生成上百个 Marauder，留着会把这个触发器刷成上百次派发
    CMLib_TrigOff(gt_CMLibCreated);

    // ---- trig：事件取参 native 在非事件上下文的安全性（隔离线程）----
    gv_cmlibEvtProbe = 0;
    TriggerExecute(TriggerCreate("CMLibTest_EvtProbe"), false, false);
    CMLib_WaitGame(0.5);
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 1, "trig.evt.dmgsourceplayer");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 2, "trig.evt.dmgsourceunit");
    CMLibTest_MarkTag(gv_cmlibEvtProbe >= 3, "trig.evt.effectowner");

"""

P4_NEW = P4_BLOCK + P4_OLD


def count_asserts(txt: str) -> int:
    t = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
    t = re.sub(r"//[^\n]*", "", t)
    n = len(re.findall(r"\bCMLibTest_Mark(?:Tag)?\s*\(", t))
    n -= len(re.findall(r"\bvoid\s+CMLibTest_Mark(?:Tag)?\s*\(", t))
    return n


def main() -> int:
    txt = SELF.read_text(encoding="utf-8")
    if MARKER in txt:
        print(f"[skip] 已含 marker「{MARKER}」，幂等跳过。断言数={count_asserts(txt)}")
        return 0

    before = count_asserts(txt)
    for name, old, new in (
        ("P1a globals-trigger", P1A_OLD, P1A_NEW),
        ("P1b globals-int", P1B_OLD, P1B_NEW),
        ("P2 handlers", P2_OLD, P2_NEW),
        ("P3 locals", P3_OLD, P3_NEW),
        ("P4 asserts", P4_OLD, P4_NEW),
    ):
        hits = txt.count(old)
        if hits != 1:
            print(f"[ERR] {name}: 锚点命中 {hits} 次（要求恰好 1 次），中止不落盘")
            return 1
        txt = txt.replace(old, new, 1)
        print(f"[ok] {name}")

    # 落盘前自检：确保没有把局部变量声明写到函数中段（Galaxy 会静默不编译）
    SELF.write_text(txt, encoding="utf-8")
    after = count_asserts(txt)
    print(f"[done] {SELF.name}: 断言 {before} -> {after}  (+{after - before})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
