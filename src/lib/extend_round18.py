# -*- coding: utf-8 -*-
"""CMLib round18 扩展：补齐 gap_scan 复扫后剩余的**真实**缺口。

筛选口径（沿用前几轮，去噪后才算真缺口）：
  · 排除 GUI 触发器自动生成的访问器噪声（`*FromId` / `*FromName` / `*LastCreated`
    / `*LoopCurrent`），它们由编辑器生成、不是人写的 API；
  · 排除等价假缺口（库里已用语义等价的 native 覆盖）；
  · 排除**不在 core 默认 include 链**里的 native（如 `Tactical/TacticalAI.galaxy`
    的 `AIFilter` 族）—— 包了会在真机静默编译失败，丢整个 MapScript；
  · 排除自定义地图无效的陷阱 API（`StatEvent*` / `Achievement*`）。

本轮补的（全部逐条对照 core `natives.galaxy` / `AI.galaxy` 核过签名）：
  面板效果 UI  6 个   —— 用户点名领域，`DialogControlCreate`(537) 等
  单位          6 个   —— `UnitHasBehavior`(447) / `UnitAbilityChargeInfo`(267) …
  单位组        1 个   —— `UnitGroupFilterRegion`(357)
  触发器/事件   5 个   —— `TriggerEventParamName`(594) / `EventUpgradeName`(388) …
  几何/角度     3 个   —— `Sin`/`Cos`（SC2 用**度**不是弧度，是真实陷阱）
  AI            4 个   —— `AIState`(421) / `AISetSubStateChance`(370) …
  用户数据      1 个   —— `UserDataGetUserInstance`(325)
  音效          1 个   —— `SoundPlayForPlayer`(1448)，库里只有 AtPoint 变体

幂等：每个文件用 MARK 标记判断是否已打过补丁，复跑输出「无需改动」。
"""
from __future__ import annotations

import re
from pathlib import Path

CM = Path(__file__).resolve().parent / "scripts" / "cmlib"
MARK = "round 18"

# ---------------------------------------------------------------------------
# 每项 = (模块名, header 追加, 实现追加)
# ---------------------------------------------------------------------------

UI_H = """

// ---- round 18：Dialog 控件族（面板效果真实缺口）--------------------------------
// 直接在对话框上建控件。原生 `DialogControlCreate` 在 78 个 mod 文件里 537 次调用，
// 是最常用的面板构造入口，而库里此前只有 InPanel 变体（要求先有一个 panel 容器）。
// dialog 无效（<=0，多半是 DialogCreate 失败或还没建）时返回 0 而不是把无效 id 传下去。
int  CMLib_DlgCtrlCreate(int lp_dialog, int lp_type);
// 带模板版本；模板名传 "" 时自动退化成无模板创建（模板名拼错在真机是静默无样式）。
int  CMLib_DlgCtrlCreateTpl(int lp_dialog, int lp_type, string lp_template);
// 取列表框/下拉框当前选中项（1-based；无效控件返回 0）。
int  CMLib_DlgCtrlSelectedItem(int lp_control, int lp_player);
// 让控件铺满整个对话框（做全屏面板的常用姿势）。players 传 null = 所有玩家。
void CMLib_DlgCtrlFullDialog(int lp_control, playergroup lp_players, bool lp_full);
// 销毁单个控件（无效 id 直接忽略，避免"销毁两次"崩掉）。
void CMLib_DlgCtrlDestroy(int lp_control);
// 高亮指挥面板上某个按钮 face（新手引导/教学关高频）。players 传 null = 所有玩家。
void CMLib_UIFaceHighlight(playergroup lp_players, string lp_face, bool lp_highlight);
"""

UI_IMPL = """

// -----------------------------------------------------------------------------
// round 18：Dialog 控件族
// -----------------------------------------------------------------------------

int CMLib_DlgCtrlCreate(int lp_dialog, int lp_type) {
    if ((lp_dialog <= 0)) {
        return 0;
    }
    return DialogControlCreate(lp_dialog, lp_type);
}

int CMLib_DlgCtrlCreateTpl(int lp_dialog, int lp_type, string lp_template) {
    if ((lp_dialog <= 0)) {
        return 0;
    }
    if ((lp_template == "")) {
        return DialogControlCreate(lp_dialog, lp_type);
    }
    return DialogControlCreateFromTemplate(lp_dialog, lp_type, lp_template);
}

int CMLib_DlgCtrlSelectedItem(int lp_control, int lp_player) {
    if ((lp_control <= 0)) {
        return 0;
    }
    return DialogControlGetSelectedItem(lp_control, lp_player);
}

void CMLib_DlgCtrlFullDialog(int lp_control, playergroup lp_players, bool lp_full) {
    playergroup lv_pg;

    if ((lp_control <= 0)) {
        return;
    }
    lv_pg = lp_players;
    if ((lv_pg == null)) {
        lv_pg = PlayerGroupAll();
    }
    DialogControlSetFullDialog(lp_control, lv_pg, lp_full);
}

void CMLib_DlgCtrlDestroy(int lp_control) {
    if ((lp_control <= 0)) {
        return;
    }
    DialogControlDestroy(lp_control);
}

void CMLib_UIFaceHighlight(playergroup lp_players, string lp_face, bool lp_highlight) {
    playergroup lv_pg;

    if ((lp_face == "")) {
        return;
    }
    lv_pg = lp_players;
    if ((lv_pg == null)) {
        lv_pg = PlayerGroupAll();
    }
    UISetButtonFaceHighlighted(lv_pg, lp_face, lp_highlight);
}
"""

UNIT_H = """

// ---- round 18：单位 / 单位组真实缺口 ------------------------------------------
// `UnitHasBehavior` 与库里已封的 `UnitHasBehavior2` 是**两个不同的原生**：
// 前者是"这个单位身上有没有这个 behavior"，后者是触发器版（各 mod 共 447 次用前者）。
// 两者语义在隐藏/内部 behavior 上有差异，故单独提供，不做别名。
bool CMLib_UnitHasBehaviorRaw(unit lp_unit, string lp_behavior);
// 技能充能信息。lp_type 用 **c_unitAbilCharge\*** 常量族
// （CountMax=0 / CountUse=1 / CountLeft=2 / RegenMax=3 / RegenLeft=4）。
// 注意引擎里**没有** c_chargeInfo* 这种名字，写错常量名 = 编译失败 = 整图静默丢弃。
// 单位或 abilcmd 无效返回 0.0。
fixed CMLib_UnitAbilChargeInfo(unit lp_unit, abilcmd lp_abil, int lp_type);
// 重置技能冷却/充能。lp_location 是**裸 int**（引擎没有对应常量族），
// 与 UnitAbilitySpend 的 inLocation 同一套编号，不确定就传 0。
void CMLib_UnitAbilReset(unit lp_unit, abilcmd lp_abil, int lp_location);
// 改单位队伍颜色索引（做"临时染色标记"最省事的手段，不需要 Actor 消息）。
void CMLib_UnitTeamColor(unit lp_unit, int lp_index);
// 当前命令队列长度。null 单位返回 0，可直接用来判"是不是闲着"。
int  CMLib_UnitOrderCount(unit lp_unit);
// 由变量名取 unitref（做存档/配置驱动的单位引用）。名字为空返回 null。
unitref CMLib_UnitRefFromVar(string lp_varName);

// 取单位组里落在某区域内的子集。g 为 null 返回空组；region 为 null 原样返回 g；
// maxCount <= 0 归一到 c_unitCountAll（= 0，即不限量）；**负数**才是真坑：
// 直接把 -1 丢给原生行为未定义，所以这里统一夹到 0。
unitgroup CMLib_UGFilterRegion(unitgroup lp_group, region lp_region, int lp_maxCount);
"""

UNIT_IMPL = """

// -----------------------------------------------------------------------------
// round 18：单位 / 单位组真实缺口
// -----------------------------------------------------------------------------

bool CMLib_UnitHasBehaviorRaw(unit lp_unit, string lp_behavior) {
    if ((CMLib_UnitOk(lp_unit) == false)) {
        return false;
    }
    if ((lp_behavior == "")) {
        return false;
    }
    return UnitHasBehavior(lp_unit, lp_behavior);
}

fixed CMLib_UnitAbilChargeInfo(unit lp_unit, abilcmd lp_abil, int lp_type) {
    if ((CMLib_UnitOk(lp_unit) == false)) {
        return 0.0;
    }
    if ((lp_abil == null)) {
        return 0.0;
    }
    return UnitAbilityChargeInfo(lp_unit, lp_abil, lp_type);
}

void CMLib_UnitAbilReset(unit lp_unit, abilcmd lp_abil, int lp_location) {
    if ((CMLib_UnitOk(lp_unit) == false)) {
        return;
    }
    if ((lp_abil == null)) {
        return;
    }
    UnitAbilityReset(lp_unit, lp_abil, lp_location);
}

void CMLib_UnitTeamColor(unit lp_unit, int lp_index) {
    if ((CMLib_UnitOk(lp_unit) == false)) {
        return;
    }
    UnitSetTeamColorIndex(lp_unit, lp_index);
}

int CMLib_UnitOrderCount(unit lp_unit) {
    if ((CMLib_UnitOk(lp_unit) == false)) {
        return 0;
    }
    return UnitOrderCount(lp_unit);
}

unitref CMLib_UnitRefFromVar(string lp_varName) {
    if ((lp_varName == "")) {
        return null;
    }
    return UnitRefFromVariable(lp_varName);
}

unitgroup CMLib_UGFilterRegion(unitgroup lp_group, region lp_region, int lp_maxCount) {
    int lv_max;

    if ((lp_group == null)) {
        return UnitGroupEmpty();
    }
    if ((lp_region == null)) {
        return lp_group;
    }
    lv_max = lp_maxCount;
    if ((lv_max <= 0)) {
        lv_max = c_unitCountAll;
    }
    return UnitGroupFilterRegion(lp_group, lp_region, lv_max);
}
"""

TRIG_H = """

// ---- round 18：触发器查找 + 事件取参补齐（真实缺口）----------------------------
// 按 Galaxy 函数名找「引擎侧」触发器（GUI 触发器互相调用时的通用入口）。
// 注意与前面的 CMLib_TrigFind 区分：那个查 CMLib 自己的登记表，这个查引擎表。
trigger CMLib_TrigFindByFunc(string lp_funcName);
// 注册「玩家属性变化」事件（矿/气/人口/科技点等，见 c_playerProp* 常量）。
void CMLib_TrigOnPlayerPropChange(trigger lp_t, int lp_player, int lp_prop);
// 「升级完成」事件：取升级 id。
string CMLib_EvtUpgradeName();
// 「单位受伤」事件：取本次伤害数值（fixed）。
fixed  CMLib_EvtDamageAmount();
// 自定义脚本事件的参数名解析（`TriggerSendEvent` 那一套的配套函数）。
// 任一入参为空返回 ""，避免把空名字送进事件表。
string CMLib_TrigEventParamName(string lp_eventName, string lp_paramName);
"""

TRIG_IMPL = """

// -----------------------------------------------------------------------------
// round 18：触发器查找 + 事件取参补齐
// -----------------------------------------------------------------------------

trigger CMLib_TrigFindByFunc(string lp_funcName) {
    if ((lp_funcName == "")) {
        return null;
    }
    return TriggerFind(lp_funcName);
}

void CMLib_TrigOnPlayerPropChange(trigger lp_t, int lp_player, int lp_prop) {
    if ((lp_t == null)) {
        return;
    }
    TriggerAddEventPlayerPropChange(lp_t, lp_player, lp_prop);
}

string CMLib_EvtUpgradeName() {
    return EventUpgradeName();
}

fixed CMLib_EvtDamageAmount() {
    return EventUnitDamageAmount();
}

string CMLib_TrigEventParamName(string lp_eventName, string lp_paramName) {
    if ((lp_eventName == "")) {
        return "";
    }
    if ((lp_paramName == "")) {
        return "";
    }
    return TriggerEventParamName(lp_eventName, lp_paramName);
}
"""

GEO_H = """

// ---- round 18：角度三角函数（SC2 用「度」不是弧度，是真实陷阱）------------------
// 各 mod 里 Sin/Cos 合计 395 次调用，全部按角度制。用这两个包装避免有人
// 顺手套 Radians/Degrees 转换转两次。
fixed CMLib_SinDeg(fixed lp_degrees);
fixed CMLib_CosDeg(fixed lp_degrees);
// 把任意角度规整到 [0, 360)。做朝向插值/转向判定前必须先规整，否则
// 359 度和 1 度会被当成"差 358 度"。
fixed CMLib_NormalizeAngle(fixed lp_degrees);
"""

GEO_IMPL = """

// -----------------------------------------------------------------------------
// round 18：角度三角函数
// -----------------------------------------------------------------------------

fixed CMLib_SinDeg(fixed lp_degrees) {
    return Sin(lp_degrees);
}

fixed CMLib_CosDeg(fixed lp_degrees) {
    return Cos(lp_degrees);
}

fixed CMLib_NormalizeAngle(fixed lp_degrees) {
    fixed lv_a;
    int lv_guard;

    lv_a = lp_degrees;
    lv_guard = 0;
    while ((lv_a < 0.0) && (lv_guard < 64)) {
        lv_a = lv_a + 360.0;
        lv_guard = lv_guard + 1;
    }
    lv_guard = 0;
    while ((lv_a >= 360.0) && (lv_guard < 64)) {
        lv_a = lv_a - 360.0;
        lv_guard = lv_guard + 1;
    }
    return lv_a;
}
"""

AI_H = """

// ---- round 18：AI 状态 / 自杀冲锋 / 子状态几率（真实缺口）-----------------------
// 读 AI 状态槽。index 是**裸 int**：AI.galaxy 里并没有 c_ASState* 常量族，
// 各战役脚本自己用字面量索引，不确定就传 0。
int  CMLib_AIState(int lp_player, int lp_index);
// 单位「自杀式冲锋」开关：开了之后 AI 不再考虑撤退保命。
void CMLib_AIUnitSuicide(unit lp_unit, bool lp_enable);
// 整组自杀式冲锋（比逐个单位设省一个循环）。
void CMLib_AIGroupSuicide(unitgroup lp_group, bool lp_enable);
// 整组「交给脚本控制」——注意与已有的 CMLib_AIScriptControlGroup 不同：
// 后者逐单位调 `AISetUnitScriptControlled`，本函数直接用组原生，开销更低。
void CMLib_AIGroupScriptControlled(unitgroup lp_group, bool lp_enable);
// 设置某子状态被选中的几率（0..100，越界自动夹紧，负数会让 AI 行为诡异）。
void CMLib_AISubStateChance(int lp_subState, int lp_chance);
"""

AI_IMPL = """

// -----------------------------------------------------------------------------
// round 18：AI 状态 / 自杀冲锋 / 子状态几率
// -----------------------------------------------------------------------------

int CMLib_AIState(int lp_player, int lp_index) {
    return AIState(lp_player, lp_index);
}

void CMLib_AIUnitSuicide(unit lp_unit, bool lp_enable) {
    if ((CMLib_UnitOk(lp_unit) == false)) {
        return;
    }
    AISetUnitSuicide(lp_unit, lp_enable);
}

void CMLib_AIGroupSuicide(unitgroup lp_group, bool lp_enable) {
    if ((lp_group == null)) {
        return;
    }
    AISetGroupSuicide(lp_group, lp_enable);
}

void CMLib_AIGroupScriptControlled(unitgroup lp_group, bool lp_enable) {
    if ((lp_group == null)) {
        return;
    }
    AISetGroupScriptControlled(lp_group, lp_enable);
}

void CMLib_AISubStateChance(int lp_subState, int lp_chance) {
    int lv_c;

    lv_c = lp_chance;
    if ((lv_c < 0)) {
        lv_c = 0;
    }
    if ((lv_c > 100)) {
        lv_c = 100;
    }
    AISetSubStateChance(lp_subState, lv_c);
}
"""

UDATA_H = """

// ---- round 18：用户数据实例查询（真实缺口）-------------------------------------
// 按「类型 + 实例 + 字段 + 下标」读一条 UserData 实例引用（返回实例 id 字符串）。
// 各 mod 325 次调用；任一必填入参为空返回 ""。
string CMLib_UDataUserInstance(string lp_type, string lp_instance,
                               string lp_field, int lp_index);
"""

UDATA_IMPL = """

// -----------------------------------------------------------------------------
// round 18：用户数据实例查询
// -----------------------------------------------------------------------------

string CMLib_UDataUserInstance(string lp_type, string lp_instance,
                               string lp_field, int lp_index) {
    int lv_i;

    if ((lp_type == "")) {
        return "";
    }
    if ((lp_field == "")) {
        return "";
    }
    lv_i = lp_index;
    if ((lv_i < 0)) {
        lv_i = 0;
    }
    return UserDataGetUserInstance(lp_type, lp_instance, lp_field, lv_i);
}
"""

FX_H = """

// ---- round 18：带归属玩家的全局音效（真实缺口）---------------------------------
// `SoundPlayForPlayer` 在各 mod 里 1448 次调用（全库最高频未封装原生），
// 库里此前只有 AtPoint / OnUnit 的 ForPlayer 变体。owner 决定这条音效算谁的
// （影响音量分组与"只有自己听得到"的判定），players 传 null = 所有玩家。
void CMLib_SfxPlayOwned(string lp_soundId, int lp_owner,
                        playergroup lp_players, fixed lp_volume);
"""

FX_IMPL = """

// -----------------------------------------------------------------------------
// round 18：带归属玩家的全局音效
// -----------------------------------------------------------------------------

void CMLib_SfxPlayOwned(string lp_soundId, int lp_owner,
                        playergroup lp_players, fixed lp_volume) {
    playergroup lv_pg;

    if ((lp_soundId == "")) {
        return;
    }
    lv_pg = lp_players;
    if ((lv_pg == null)) {
        lv_pg = PlayerGroupAll();
    }
    SoundPlayForPlayer(CMLib_SfxLink(lp_soundId, -1), lp_owner, lv_pg,
                       CMLib_FxVol(lp_volume), CMLIB_FX_NO_OFFSET);
}
"""

PATCHES = [
    ("cmlib_ui", UI_H, UI_IMPL),
    ("cmlib_unit", UNIT_H, UNIT_IMPL),
    ("cmlib_trig", TRIG_H, TRIG_IMPL),
    ("cmlib_geo", GEO_H, GEO_IMPL),
    ("cmlib_ai", AI_H, AI_IMPL),
    ("cmlib_udata", UDATA_H, UDATA_IMPL),
    ("cmlib_fx", FX_H, FX_IMPL),
]


def apply_one(stem: str, h_text: str, impl_text: str) -> tuple[int, int]:
    h = CM / f"{stem}_h.galaxy"
    c = CM / f"{stem}.galaxy"
    done = 0
    skipped = 0
    for path, add in ((h, h_text), (c, impl_text)):
        txt = path.read_text(encoding="utf-8")
        if MARK in txt:
            skipped += 1
            continue
        path.write_text(txt.rstrip("\n") + "\n" + add, encoding="utf-8")
        done += 1
    return done, skipped


_NAME_RE = re.compile(
    r"^\s*(?:[A-Za-z_]\w*)\s+(CMLib_\w+)\s*\(", re.M)


def preflight_collisions() -> list[str]:
    """落盘前先查重名。

    血泪来源：round 18 首跑给 cmlib_trig 追加了一个 `CMLib_TrigFind`，
    而同文件 121 行早就有一个同名（查 CMLib 登记表的）实现。
    Galaxy 函数重定义 ⇒ SC2 **静默丢弃整个 MapScript**（Ghost=0，零报错）。
    幂等标记只认「本文件是否已打过 round 18」，认不出跨轮次的重名，
    所以必须单独做一遍全库名字碰撞检查。
    """
    existing: dict[str, str] = {}
    for f in sorted(CM.glob("*.galaxy")):
        for m in _NAME_RE.finditer(f.read_text(encoding="utf-8")):
            existing.setdefault(m.group(1), f.name)

    hits: list[str] = []
    for stem, h_text, impl_text in PATCHES:
        already = MARK in (CM / f"{stem}_h.galaxy").read_text(encoding="utf-8")
        if already:
            continue  # 本模块已打过，跳过（否则会把自己刚写的当碰撞）
        for name in {m.group(1) for m in _NAME_RE.finditer(h_text + impl_text)}:
            if name in existing:
                hits.append(f"{name}（已存在于 {existing[name]}，本轮想加进 {stem}）")
    return sorted(hits)


def main() -> int:
    hits = preflight_collisions()
    if hits:
        print("ABORT — 与既有函数重名，Galaxy 重定义会让 SC2 静默丢整图：")
        for h in hits:
            print(f"  ! {h}")
        return 1

    total_done = 0
    total_skip = 0
    for stem, h_text, impl_text in PATCHES:
        d, s = apply_one(stem, h_text, impl_text)
        total_done += d
        total_skip += s
        print(f"  {stem:<14} 写入 {d} / 已存在 {s}")
    print("-" * 60)
    if total_done == 0:
        print("round18 补丁已全部存在，无需改动")
    else:
        print(f"round18: 写入 {total_done} 个文件，跳过 {total_skip} 个（幂等）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
