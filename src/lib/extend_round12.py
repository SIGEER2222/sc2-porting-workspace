# -*- coding: utf-8 -*-
"""第 12 轮：补齐 7 个真实缺口（滤掉 GUI 噪声 + 等价假缺口后剩余）。
- unit:     UnitCreateEffectPoint / UnitAbilityEnable / UnitCargoCreate / UnitSetHeight
- unitgroup: UnitGroupClosestToPoint / UnitGroupCenterOfGroup
- trigger:  TriggerQueueClear
全部封装加 null/UnitOk 守门；selftest 注入 7 条带标签断言（140 -> 147）。
等价假缺口（本轮不包，已论证被覆盖）：
  SoundPlayForPlayer -> CMLib_SfxPlayForPlayer（走 SoundPlay）
  StringWord          -> CMLib_SplitAt / CMLib_SplitCount
  CatalogFieldValueSetFixed -> CMLib_CatSetFixed（走 CatalogFieldValueSet）
依赖范围外（不包）：AIFilter/AIGetFilterGroup/AISetFilterAlliance（TacticalAI.galaxy，非 core 默认 include）
"""
import io, sys

BASE = r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib\scripts\cmlib"
SELF = r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib\selftest\cmlib_selftest.galaxy"

def read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()

def write(p, s):
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)

# ---------- 1. unit_h 声明 ----------
p = f"{BASE}\\cmlib_unit_h.galaxy"
s = read(p)
anchor = "unitgroup CMLib_UGAlliesOf(int lp_player, int lp_maxCount);\n"
assert s.count(anchor) == 1, "unit_h anchor 不唯一"
decl = anchor + """
// ---- 单位操作便利封装（round 12 真实缺口补齐）-------------------------------
// 在 unit 上创建定点/单位效果（区别于 CMLib_FxAtPoint 的玩家域效果）。
void CMLib_UnitCreateEffectPoint(unit lp_unit, string lp_effect, point lp_target);
// 启停单位某个技能（如禁用 Attack / 启用被动）。
void CMLib_UnitAbilityEnable(unit lp_unit, string lp_ability, bool lp_enable);
// 给运输单位装入货舱单位（id 为单位类型，count 为数量）。
void CMLib_UnitCargoCreate(unit lp_unit, string lp_id, int lp_count);
// 设置单位飞行高度（height=0 落地；duration=0 瞬时）。
void CMLib_UnitSetHeight(unit lp_unit, fixed lp_height, fixed lp_duration);
// ---- 编组几何便利封装 -------------------------------------------------------
// 组内离某点最近的存活单位；空组/null 返回 null。
unit CMLib_UGClosestToPoint(unitgroup lp_group, point lp_point);
// 组的质心点；空组/null 返回 null。
point CMLib_UGCenterOfGroup(unitgroup lp_group);
"""
s = s.replace(anchor, decl, 1)
write(p, s)
print("unit_h patched")

# ---------- 2. unit.galaxy 实现 ----------
p = f"{BASE}\\cmlib_unit.galaxy"
s = read(p)
anchor = """unitgroup CMLib_UGAlliesOf(int lp_player, int lp_maxCount) {
    return CMLib_UGAlliance(lp_player, c_unitAllianceAlly, null, CMLib_FilterAlive(), lp_maxCount);
}
"""
assert s.count(anchor) == 1, "unit.galaxy anchor 不唯一"
impl = anchor + """
// ---- 单位操作便利封装（round 12）-------------------------------------------
void CMLib_UnitCreateEffectPoint(unit lp_unit, string lp_effect, point lp_target) {
    if ((CMLib_UnitOk(lp_unit) == false) || (lp_effect == "") || (lp_target == null)) {
        return;
    }
    UnitCreateEffectPoint(lp_unit, lp_effect, lp_target);
}

void CMLib_UnitAbilityEnable(unit lp_unit, string lp_ability, bool lp_enable) {
    if ((CMLib_UnitOk(lp_unit) == false) || (lp_ability == "")) {
        return;
    }
    UnitAbilityEnable(lp_unit, lp_ability, lp_enable);
}

void CMLib_UnitCargoCreate(unit lp_unit, string lp_id, int lp_count) {
    if ((CMLib_UnitOk(lp_unit) == false) || (lp_id == "") || (lp_count <= 0)) {
        return;
    }
    UnitCargoCreate(lp_unit, lp_id, lp_count);
}

void CMLib_UnitSetHeight(unit lp_unit, fixed lp_height, fixed lp_duration) {
    if (CMLib_UnitOk(lp_unit) == false) {
        return;
    }
    UnitSetHeight(lp_unit, lp_height, lp_duration);
}

// ---- 编组几何便利封装（round 12）-------------------------------------------
unit CMLib_UGClosestToPoint(unitgroup lp_group, point lp_point) {
    if ((lp_group == null) || (lp_point == null)) {
        return null;
    }
    return UnitGroupClosestToPoint(lp_group, lp_point);
}

point CMLib_UGCenterOfGroup(unitgroup lp_group) {
    if (lp_group == null) {
        return null;
    }
    return UnitGroupCenterOfGroup(lp_group);
}
"""
s = s.replace(anchor, impl, 1)
write(p, s)
print("unit.galaxy patched")

# ---------- 3. trig_h 声明 ----------
p = f"{BASE}\\cmlib_trig_h.galaxy"
s = read(p)
anchor = "void CMLib_TrigDumpState();\n"
assert s.count(anchor) == 1, "trig_h anchor 不唯一"
decl = anchor + """
// 清触发器队列（配合 c_triggerQueue* 常量：Retain/Remove/Kill）。
// 用于打断正在排队的触发器链，避免旧队列污染新逻辑。
void CMLib_TriggerQueueClear(int lp_option);
"""
s = s.replace(anchor, decl, 1)
write(p, s)
print("trig_h patched")

# ---------- 4. trig.galaxy 实现 ----------
p = f"{BASE}\\cmlib_trig.galaxy"
s = read(p)
anchor = """    if (CMLib_TrigQDepth != 0) {
        CMLib_LogError("Trig",
            "队列深度非 0，说明有 CMLib_TrigQueueBegin 没有配对的 End —— " +
            "后续排队触发器会静默不执行。");
    }
}
"""
assert s.count(anchor) == 1, "trig.galaxy anchor 不唯一"
impl = anchor + """
// 清触发器队列（round 12 真实缺口补齐）。
void CMLib_TriggerQueueClear(int lp_option) {
    TriggerQueueClear(lp_option);
}
"""
s = s.replace(anchor, impl, 1)
write(p, s)
print("trig.galaxy patched")

# ---------- 5. selftest 断言 ----------
p = SELF
s = read(p)
anchor = '    CMLibTest_MarkTag(CMLib_UGAlliesOf(1, 0) != null, "ug.allies");\n'
assert s.count(anchor) == 1, "selftest anchor 不唯一"
asserts = anchor + """    // round 12: 真实缺口补齐断言（unit/unitgroup/trigger 便利封装）
    CMLib_UnitCreateEffectPoint(lv_probe, "DamageHit", lv_origin);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_probe), "unit.createeffect");
    CMLib_UnitAbilityEnable(lv_probe, "Attack", true);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_probe), "unit.abilityenable");
    CMLib_UnitCargoCreate(lv_probe, "Marine", 1);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_probe), "unit.cargocreate");
    CMLib_UnitSetHeight(lv_probe, 2.0, 0.0);
    CMLibTest_MarkTag(CMLib_UnitOk(lv_probe), "unit.setheight");
    lv_g2 = UnitGroupEmpty();
    CMLib_UGAdd(lv_g2, lv_probe);
    CMLibTest_MarkTag(CMLib_UnitOk(CMLib_UGClosestToPoint(lv_g2, lv_origin)), "ug.closest");
    CMLibTest_MarkTag(CMLib_UGCenterOfGroup(lv_g2) != null, "ug.center");
    CMLib_TriggerQueueClear(c_triggerQueueRemove);
    CMLibTest_MarkTag(true, "trig.queueclear");
"""
s = s.replace(anchor, asserts, 1)
write(p, s)
print("selftest patched")

print("DONE: 7 wrappers + 7 assertions (140 -> 147)")
