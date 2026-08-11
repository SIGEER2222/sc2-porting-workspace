# -*- coding: utf-8 -*-
"""
round17 selftest 补丁（幂等）。

给 CMLibTest_Deferred 追加 unit / player / bank / panel / ui 五个模块的真机断言。

设计约束（都是踩过坑总结出来的）：
  1. 只引用**确认存在**的引擎常量。`c_unitFlagStructure` 根本不存在（建筑是
     attribute 不是 flag），`c_selectionType*` 也不存在（用字面量 0）。引用一个
     不存在的常量 = 编译失败 = SC2 静默丢弃整个 MapScript，静态 lint 还报 0 错。
  2. 语义把不准的 native（bank 枚举索引基数、objective 可见性时序）只断言
     「调用链不炸 + 守卫契约」，不断言具体返回值 —— 一条写死的错误期望会变成
     永久 FAIL，比没有断言更糟。
  3. 有运行时抛错风险的调用（未知 cooldown link）放各自子块**末尾**，
     万一抛错也只损失自己，不带走整段证据。
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(HERE, "selftest", "cmlib_selftest.galaxy")

MARK = "round 17：unit / player / bank / panel / ui 补齐"
ANCHOR = "    // ---- 汇合 AI 加分线"

DECLS = """    unit        lv_r17u;
    order       lv_r17order;
    int         lv_r17i;
    string      lv_r17s;
    bool        lv_r17b;
    text        lv_r17t;
    fixed       lv_r17f;
    playergroup lv_r17pg;
    int         lv_r17obj;
"""

BLOCK = r"""
    // ================= round 17：unit / player / bank / panel / ui 补齐 =================

    // ---- unit：句柄与标识 ----
    lv_r17u = CMLib_SpawnForced("Marine", 1,
                                CMLib_PointOffset(lv_origin, 3.0, -3.0), 90.0);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r17u), "unit.r17.spawn");
    CMLibTest_MarkTag(CMLib_UnitTag(lv_r17u) != 0, "unit.tag");
    CMLibTest_MarkTag(CMLib_UnitTag(null) == 0, "unit.tag.guard");
    // UnitFromId 取的是**编辑器预放置**单位 id，不是 UnitGetTag 的运行时 tag
    // （官方图里全是 UnitFromId(9) / UnitFromId(3245) 这种小整数）。
    // 所以这里只验守卫契约，不写一个必然失败的往返断言。
    CMLibTest_MarkTag(CMLib_UnitById(0) == null, "unit.byid.guard");
    CMLibTest_MarkTag(CMLib_UnitById(-1) == null, "unit.byid.guard.neg");

    // ---- unit：朝向（三种入口 + null 守卫都不得炸）----
    CMLib_UnitFace(lv_r17u, 180.0, 0.0);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r17u), "unit.face");
    CMLib_UnitFaceUnit(lv_r17u, lv_u, 0.0);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r17u), "unit.face.unit");
    CMLib_UnitFacePoint(lv_r17u, lv_origin, 0.0);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r17u), "unit.face.point");
    CMLib_UnitFace(null, 90.0, -1.0);          // null + 负时长双守卫
    CMLib_UnitFaceUnit(lv_r17u, null, 0.0);
    CMLib_UnitFacePoint(null, lv_origin, 0.0);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r17u), "unit.face.guard");

    // ---- unit：选中 / 信息文本 ----
    CMLib_UnitSelectFor(lv_r17u, 1, true);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r17u), "unit.select");
    CMLib_UnitSelectOnly(lv_r17u, 1);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r17u), "unit.select.only");
    CMLib_UnitSelectFor(lv_r17u, 99, true);    // 非法槽位：走 LogWarn 分支不崩
    CMLib_UnitSelectOnly(null, 1);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r17u), "unit.select.guard");
    CMLib_UnitInfoText(lv_r17u, StringToText("CMLib"),
                       StringToText(""), StringToText(""));
    CMLib_UnitInfoText(null, StringToText(""), StringToText(""), StringToText(""));
    CMLibTest_MarkTag(CMLib_UnitOk(lv_r17u), "unit.infotext");

    // ---- unit：类型元数据 ----
    // 「建筑」在引擎里是 attribute（c_unitAttributeStructure=7）不是 flag ——
    // 这两条就是那次「c_unitFlagStructure 不存在」踩坑的回归护栏。
    CMLibTest_MarkTag(CMLib_UnitTypeIsStructure("SupplyDepot") == true,
                      "unit.type.structure");
    CMLibTest_MarkTag(CMLib_UnitTypeIsStructure("Marine") == false,
                      "unit.type.structure.neg");
    CMLibTest_MarkTag(CMLib_UnitTypeIsStructure("") == false,
                      "unit.type.structure.guard");
    CMLibTest_MarkTag(CMLib_UnitTypeIsWorker("SCV") == true, "unit.type.worker");
    CMLibTest_MarkTag(CMLib_UnitTypeIsWorker("Marine") == false,
                      "unit.type.worker.neg");
    CMLibTest_MarkTag(CMLib_UnitTypeProp("Marine", c_unitPropLifeMax) > 0.0,
                      "unit.type.prop");
    CMLibTest_MarkTag(CMLib_UnitTypeProp("", c_unitPropLifeMax) == 0.0,
                      "unit.type.prop.guard");
    CMLibTest_MarkTag(CMLib_UnitTypeFlag("SCV", c_unitFlagWorker) == true,
                      "unit.type.flag");
    CMLibTest_MarkTag(CMLib_UnitTypeFlag("", c_unitFlagWorker) == false,
                      "unit.type.flag.guard");

    // ---- unit：计数（Ghost 是编译成功 sentinel，此刻必在场）----
    CMLibTest_MarkTag(CMLib_UnitCountOf("Ghost", 1, null, "", 0) >= 1,
                      "unit.count.of");
    CMLibTest_MarkTag(CMLib_UnitCountOf("Ghost", 1, RegionEntireMap(), "", 0) >= 1,
                      "unit.count.of.region");
    CMLibTest_MarkTag(CMLib_UnitCountOf("Ghost", 99, null, "", 0) == 0,
                      "unit.count.guard");
    CMLibTest_MarkTag(CMLib_UnitCountAllianceOf(1, c_unitAllianceAny, null, "", 0) >= 1,
                      "unit.count.alliance");
    CMLibTest_MarkTag(CMLib_UnitCountAllianceOf(99, c_unitAllianceAny, null, "", 0) == 0,
                      "unit.count.alliance.guard");

    // ---- unit：order 结构读写 ----
    lv_r17order = CMLib_OrderAt("attack", 0, lv_origin);
    CMLibTest_MarkTag(lv_r17order != null, "unit.order.at");
    CMLibTest_MarkTag(CMLib_OrderTargetPoint(lv_r17order) != null,
                      "unit.order.target.point");
    CMLibTest_MarkTag(StringLength(AbilityCommandGetAbility(
                          CMLib_OrderAbilCmd(lv_r17order))) > 0,
                      "unit.order.abilcmd");
    lv_r17order = CMLib_OrderOn("attack", 0, lv_r17u);
    CMLibTest_MarkTag(CMLib_OrderTargetUnit(lv_r17order) == lv_r17u,
                      "unit.order.on");
    CMLib_OrderSetTargetPoint(lv_r17order, lv_origin);
    CMLibTest_MarkTag(CMLib_OrderTargetPoint(lv_r17order) != null,
                      "unit.order.settarget.point");
    CMLib_OrderSetTargetUnit(lv_r17order, lv_r17u);
    CMLibTest_MarkTag(CMLib_OrderTargetUnit(lv_r17order) == lv_r17u,
                      "unit.order.settarget.unit");
    CMLibTest_MarkTag(CMLib_OrderAutoCast("attack", 0, true) != null,
                      "unit.order.autocast");
    // 守卫：空技能 / null order 一律安全回退，绝不进 native
    CMLibTest_MarkTag(CMLib_OrderAt("", 0, lv_origin) == null, "unit.order.guard");
    CMLibTest_MarkTag(CMLib_OrderOn("attack", 0, null) == null,
                      "unit.order.on.guard");
    CMLibTest_MarkTag(CMLib_OrderAutoCast("", 0, true) == null,
                      "unit.order.autocast.guard");
    CMLibTest_MarkTag(CMLib_OrderTargetUnit(null) == null, "unit.order.null.unit");
    CMLibTest_MarkTag(CMLib_OrderTargetPoint(null) == null, "unit.order.null.point");
    CMLib_OrderSetTargetPoint(null, lv_origin);
    CMLib_OrderSetTargetUnit(null, lv_r17u);
    CMLibTest_MarkTag(true, "unit.order.null.set");

    // ---- player：标识 ----
    lv_r17t = CMLib_PlayerNameOf(1);
    CMLibTest_MarkTag(true, "player.name");
    lv_r17s = CMLib_PlayerHandleOf(1);
    CMLibTest_MarkTag(StringLength(lv_r17s) >= 0, "player.handle");
    CMLibTest_MarkTag(StringEqual(CMLib_PlayerHandleOf(99), "", true),
                      "player.handle.guard");
    CMLibTest_MarkTag(CMLib_PlayerTypeOf(1) == c_playerTypeUser, "player.type");
    CMLibTest_MarkTag(CMLib_PlayerTypeOf(99) == c_playerTypeNone,
                      "player.type.guard");
    CMLibTest_MarkTag(CMLib_PlayerStatusOf(1) == c_playerStatusActive,
                      "player.status");
    CMLibTest_MarkTag(CMLib_PlayerStatusOf(99) == c_playerStatusUnused,
                      "player.status.guard");
    CMLibTest_MarkTag(CMLib_PlayerPropInt(1, c_playerPropMinerals) >= 0,
                      "player.prop");
    CMLibTest_MarkTag(CMLib_PlayerPropInt(99, c_playerPropMinerals) == 0,
                      "player.prop.guard");

    // ---- player：颜色（读回往返，不改变实际外观）----
    lv_r17i = CMLib_PlayerColor(1);
    CMLibTest_MarkTag(lv_r17i >= 0, "player.color");
    CMLib_PlayerSetColor(1, lv_r17i, false);
    CMLibTest_MarkTag(CMLib_PlayerColor(1) == lv_r17i, "player.color.set");
    CMLib_PlayerSetColor(1, -1, false);        // 负索引：守卫必须挡住
    CMLib_PlayerSetColor(99, 0, false);        // 非法槽位：守卫必须挡住
    CMLibTest_MarkTag(CMLib_PlayerColor(1) == lv_r17i, "player.color.guard");

    // ---- player：playergroup 增删查 ----
    lv_r17pg = PlayerGroupEmpty();
    CMLib_PGAdd(lv_r17pg, 1);
    CMLibTest_MarkTag(CMLib_PGHas(lv_r17pg, 1) == true, "player.pg.add");
    CMLibTest_MarkTag(CMLib_PGCount(lv_r17pg) == 1, "player.pg.count");
    CMLibTest_MarkTag(CMLib_PGAt(lv_r17pg, 1) == 1, "player.pg.at");
    CMLibTest_MarkTag(CMLib_PGAt(lv_r17pg, 0) == 0, "player.pg.at.guard.low");
    CMLibTest_MarkTag(CMLib_PGAt(lv_r17pg, 99) == 0, "player.pg.at.guard.high");
    CMLibTest_MarkTag(CMLib_PGAt(null, 1) == 0, "player.pg.at.guard.null");
    CMLib_PGRemove(lv_r17pg, 1);
    CMLibTest_MarkTag(CMLib_PGHas(lv_r17pg, 1) == false, "player.pg.remove");
    CMLib_PGAdd(lv_r17pg, 1);
    CMLib_PGAdd(lv_r17pg, 99);                 // 非法槽位不得入组
    CMLib_PGClear(lv_r17pg);
    CMLibTest_MarkTag(CMLib_PGCount(lv_r17pg) == 0, "player.pg.clear");
    CMLib_PGAdd(null, 1);
    CMLib_PGRemove(null, 1);
    CMLib_PGClear(null);
    CMLibTest_MarkTag(true, "player.pg.null.guard");

    // ---- player：天赋 / 冷却 / 施法（都只验守卫与可调用性）----
    CMLibTest_MarkTag(CMLib_PlayerTalent(1, "") == false, "player.talent.guard");
    CMLibTest_MarkTag(CMLib_PlayerTalent(99, "CMLibNone") == false,
                      "player.talent.guard.slot");
    CMLib_PlayerEffectAt(1, "", lv_origin);
    CMLib_PlayerEffectOn(1, "", lv_r17u);
    CMLib_PlayerEffectOn(1, "CMLibNone", null);
    CMLibTest_MarkTag(true, "player.effect.guard");
    // 冷却读取放本段末尾：未知 cooldown link 的引擎行为不是 100% 确定，
    // 万一抛运行时错误也只损失这两条，不带走上面整段 player 证据。
    CMLibTest_MarkTag(CMLib_PlayerCooldown(1, "") == 0.0, "player.cooldown.guard");
    lv_r17f = CMLib_PlayerCooldown(1, "CMLibNoSuchCooldown");
    CMLibTest_MarkTag(lv_r17f >= 0.0, "player.cooldown");
    CMLibTest_MarkTag(CMLib_PlayerCooldownReady(1, "CMLibNoSuchCooldown") == true,
                      "player.cooldown.ready");

    // ---- bank：底层查询（lv_bank 早已写过 Result 段）----
    CMLibTest_MarkTag(StringEqual(CMLib_BankNameOf(lv_bank),
                                  "CMLibRuntimeTest", true), "bank.name");
    CMLibTest_MarkTag(StringEqual(CMLib_BankNameOf(null), "", true),
                      "bank.name.guard");
    CMLibTest_MarkTag(CMLib_BankPlayerOf(lv_bank) == 1, "bank.player");
    CMLibTest_MarkTag(CMLib_BankPlayerOf(null) == 0, "bank.player.guard");
    CMLibTest_MarkTag(CMLib_BankExists("CMLibRuntimeTest", 1) == true, "bank.exists");
    CMLibTest_MarkTag(CMLib_BankExists("", 1) == false, "bank.exists.guard");
    CMLibTest_MarkTag(CMLib_BankExists("CMLibRuntimeTest", 99) == false,
                      "bank.exists.guard.slot");
    CMLibTest_MarkTag(CMLib_BankSectionExists(lv_bank, "Result") == true,
                      "bank.section.exists");
    CMLibTest_MarkTag(CMLib_BankSectionExists(lv_bank, "CMLibNoSuchSection") == false,
                      "bank.section.exists.neg");
    CMLibTest_MarkTag(CMLib_BankSectionCount(lv_bank) >= 1, "bank.section.count");
    CMLibTest_MarkTag(CMLib_BankSectionCount(null) == 0, "bank.section.count.guard");
    // 枚举索引基数（0 还是 1）引擎未文档化 —— 只钉守卫契约，不钉具体名字。
    CMLibTest_MarkTag(StringEqual(CMLib_BankSectionName(lv_bank, -1), "", true),
                      "bank.section.name.guard.low");
    CMLibTest_MarkTag(StringEqual(CMLib_BankSectionName(lv_bank, 9999), "", true),
                      "bank.section.name.guard.high");
    lv_r17s = CMLib_BankSectionName(lv_bank, 0);
    CMLibTest_MarkTag(true, "bank.section.name");
    CMLibTest_MarkTag(CMLib_BankKeyCount(lv_bank, "Result") >= 1, "bank.key.count");
    CMLibTest_MarkTag(CMLib_BankKeyCount(lv_bank, "CMLibNoSuchSection") == 0,
                      "bank.key.count.guard");
    CMLibTest_MarkTag(StringEqual(
                          CMLib_BankKeyName(lv_bank, "CMLibNoSuchSection", 0), "", true),
                      "bank.key.name.guard");
    lv_r17s = CMLib_BankKeyName(lv_bank, "Result", 0);
    CMLibTest_MarkTag(true, "bank.key.name");
    CMLib_BankOption(lv_bank, c_bankOptionSignature, false);
    CMLibTest_MarkTag(CMLib_BankOptionOn(lv_bank, c_bankOptionSignature) == false,
                      "bank.option");
    CMLibTest_MarkTag(CMLib_BankOptionOn(null, c_bankOptionSignature) == false,
                      "bank.option.guard");
    lv_r17b = CMLib_BankVerified(lv_bank);
    CMLibTest_MarkTag(CMLib_BankVerified(null) == false, "bank.verified.guard");
    CMLibTest_MarkTag(CMLib_BankLast() != null, "bank.last");
    CMLib_BankRemove(null);                    // 只验 null 守卫；绝不删真 bank
    CMLibTest_MarkTag(true, "bank.remove.guard");
    // CMLib_BankWait 刻意不做真机断言：它是阻塞语义，一旦引擎不返回
    // 会把整个测试挂死成超时，代价远大于收益。

    // ---- panel：任务目标补齐 ----
    lv_r17obj = CMLib_ObjCreate(StringToText("CMLib R17"),
                                StringToText("round17"), false);
    CMLibTest_MarkTag(lv_r17obj >= 0, "panel.obj.create");
    CMLibTest_MarkTag(CMLib_ObjLast() == lv_r17obj, "panel.obj.last");
    CMLib_ObjSetPriority(lv_r17obj, 5);
    CMLibTest_MarkTag(CMLib_ObjPriority(lv_r17obj) == 5, "panel.obj.priority");
    CMLib_ObjSetPrimary(lv_r17obj, true);
    CMLibTest_MarkTag(CMLib_ObjIsPrimary(lv_r17obj) == true, "panel.obj.primary");
    CMLib_ObjSetPrimary(lv_r17obj, false);
    CMLibTest_MarkTag(CMLib_ObjIsPrimary(lv_r17obj) == false, "panel.obj.primary.off");
    CMLib_ObjSetPlayers(lv_r17obj, CMLib_PGSingle(1));
    lv_r17b = CMLib_ObjVisibleFor(lv_r17obj, 1);
    CMLibTest_MarkTag(true, "panel.obj.visible");
    CMLibTest_MarkTag(CMLib_ObjVisibleFor(0, 1) == false, "panel.obj.visible.guard");
    CMLib_ObjSetDesc(lv_r17obj, StringToText("cmlib-desc"));
    lv_r17t = CMLib_ObjDesc(lv_r17obj);
    lv_r17t = CMLib_ObjName(lv_r17obj);
    CMLibTest_MarkTag(true, "panel.obj.text");
    CMLib_ObjMoveFirst(lv_r17obj);
    CMLib_ObjMoveLast(lv_r17obj);
    CMLibTest_MarkTag(CMLib_ObjPriority(lv_r17obj) == 5, "panel.obj.move");
    CMLib_ObjMoveAfter(lv_r17obj, lv_r17obj);  // anchor == self：守门必须挡住
    CMLib_ObjMoveBefore(lv_r17obj, lv_r17obj);
    CMLibTest_MarkTag(CMLib_ObjPriority(lv_r17obj) == 5, "panel.obj.move.self.guard");
    CMLib_ObjSetPriority(0, 3);                // 无效句柄一律不进 native
    CMLib_ObjSetPrimary(0, true);
    CMLib_ObjSetDesc(0, StringToText("x"));
    CMLib_ObjMoveFirst(0);
    CMLibTest_MarkTag(CMLib_ObjPriority(0) == 0, "panel.obj.guard");
    CMLib_ObjDestroy(lv_r17obj);
    CMLibTest_MarkTag(true, "panel.obj.destroy");
    CMLib_ObjDestroyAll(CMLib_PGSingle(1));
    CMLibTest_MarkTag(true, "panel.obj.destroyall");

    // ---- ui：界面模式 / 按钮高亮 / 光标 / 选择方式 ----
    lv_r17pg = CMLib_PGSingle(1);
    CMLib_UIMode(lv_r17pg, c_uiModeConsole);
    CMLibTest_MarkTag(true, "ui.mode");
    CMLib_UIModeLetterbox(lv_r17pg, 0.0);
    CMLibTest_MarkTag(true, "ui.mode.letterbox");
    CMLib_UIModeFullscreen(lv_r17pg, 0.0);
    CMLibTest_MarkTag(true, "ui.mode.fullscreen");
    CMLib_UIModeConsole(lv_r17pg, 0.0);        // 还原正常界面，别把测试图搞黑屏
    CMLibTest_MarkTag(true, "ui.mode.console");
    CMLib_UISetMode(lv_r17pg, 999, -5.0);      // 越界 mode + 负时长：双钳制
    CMLib_UISetMode(lv_r17pg, -3, 0.0);
    CMLib_UIModeConsole(lv_r17pg, 0.0);
    CMLibTest_MarkTag(true, "ui.mode.guard");
    CMLib_UIButtonHighlight(lv_r17pg, "attack", 0, true);
    CMLib_UIButtonHighlight(lv_r17pg, "attack", 0, false);
    CMLib_UIButtonHighlight(lv_r17pg, "", 0, true);   // 空技能：守卫
    CMLibTest_MarkTag(true, "ui.button.highlight");
    CMLib_UICursor(lv_r17pg, true);
    CMLibTest_MarkTag(true, "ui.cursor");
    // 引擎没有 c_selectionType* 常量族，只有裸 int —— 用 0 并注明。
    CMLib_UISelectionType(lv_r17pg, 0, true);
    CMLibTest_MarkTag(true, "ui.selection.type");

"""


def main():
    if not os.path.exists(TARGET):
        print("[ERR] 找不到 %s" % TARGET)
        return 1

    with io.open(TARGET, "r", encoding="utf-8") as fh:
        src = fh.read()

    if MARK in src:
        print("[SKIP] round17 断言已存在，幂等返回")
        return 0

    if ANCHOR not in src:
        print("[ERR] 找不到插入锚点：%s" % ANCHOR)
        return 1

    # 1) 补局部变量声明（Galaxy 强制局部变量置顶，中途声明 = 编译失败 = 整图静默丢弃）
    decl_anchor = "    int     lv_dummyPlayer;\n"
    if decl_anchor not in src:
        print("[ERR] 找不到声明锚点 lv_dummyPlayer")
        return 1
    if "lv_r17u;" not in src:
        src = src.replace(decl_anchor, decl_anchor + DECLS, 1)

    # 2) 在「汇合 AI 加分线」之前插入断言块
    src = src.replace(ANCHOR, BLOCK + ANCHOR, 1)

    with io.open(TARGET, "w", encoding="utf-8") as fh:
        fh.write(src)

    n = len(re.findall(r"CMLibTest_Mark(?:Tag)?\s*\(", src))
    print("[OK] round17 断言已注入；文件内 Mark 调用点总数 = %d" % n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
