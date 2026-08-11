# -*- coding: utf-8 -*-
"""第 13 轮：补齐 24 个真实缺口（覆盖率复扫 top40 逐一核实后剩余的真货）。

核实方法（每一个都过了三道）：
  1. gap_scan top40 -> 在 CMLib 源码里 grep 确认 0 引用；
  2. 在 core.sc2mod/TriggerLibs/natives.galaxy 里确认存在且抄下权威签名（arity+类型）；
  3. 排除「等价假缺口」与「依赖范围外」。

本轮剔除的假缺口（已被等价覆盖，不重复包）：
  UnitHasBehavior            -> CMLib_UnitHasBehavior（走 UnitBehaviorCount）
  CatalogFieldValueSetFixed  -> CMLib_CatSetFixed（走 CatalogFieldValueSet + FixedToString）
  CatalogFieldValueModifyFixed -> CMLib_CatModifyFixed
  *FromId / *FromName / *LastCreated / *Loop* -> GUI 触发器自动访问器噪声

依赖范围外（仍然不包）：AIFilter / AIGetFilterGroup / AISetFilterAlliance（TacticalAI.galaxy）

注意 CameraShake 有两个形态，不是重复：
  CameraShakeStart(int,int,int,fixed,fixed,fixed,fixed) -> 已有 CMLib_CamShake（参数版）
  CameraShake(int,string,string,fixed,fixed,fixed)      -> 本轮新增 CMLib_CamShakePreset（预设版）
"""
import io

BASE = r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib\scripts\cmlib"
SELF = r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib\selftest\cmlib_selftest.galaxy"


def read(p):
    with io.open(p, encoding="utf-8") as f:
        return f.read()


def write(p, s):
    with io.open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(s)


def append(fname, text, marker):
    """幂等追加：已打过补丁就跳过。"""
    p = f"{BASE}\\{fname}"
    s = read(p)
    if marker in s:
        print(f"  skip (already patched): {fname}")
        return
    if not s.endswith("\n"):
        s += "\n"
    write(p, s + text)
    print(f"  patched: {fname}")


# =============================================================================
# 1. unit —— UnitOrder / UnitOrderHasAbil / UnitClearSelection
#              UnitGroupSelected / UnitGroupFilter
# =============================================================================
append("cmlib_unit_h.galaxy", '''
// ---- round 13：命令队列 / 选择集 / 过滤（真实缺口补齐）----------------------
// 读单位命令队列第 N 条命令（0 基）。越界 / 死单位返回 null。
// 注意 UnitOrder 是**读取**命令而非下达命令，下达见 CMLib_UnitOrderAbility。
order      CMLib_UnitOrderAt(unit lp_unit, int lp_index);
// 单位当前命令队列里是否含某技能（判「正在建造/正在施法」的标准手法）。
bool       CMLib_UnitOrderHasAbil(unit lp_unit, string lp_ability);
// 清空某玩家的当前选择集。非法槽位安全返回。
void       CMLib_SelClear(int lp_player);
// 取某玩家当前选中的单位组。非法槽位返回空组（不返回 null）。
unitgroup  CMLib_UGSelected(int lp_player);
// 按「单位类型 + 过滤规格串」筛选单位组。
// lp_type 传 "" 表示不限类型；lp_filterSpec 传 "" 时回退为「存活」过滤；
// lp_maxCount <= 0 表示不限数量。非法槽位返回空组。
unitgroup  CMLib_UGFilterStr(string lp_type, int lp_player, unitgroup lp_group,
                             string lp_filterSpec, int lp_maxCount);
''', "CMLib_UnitOrderAt")

append("cmlib_unit.galaxy", '''
// =============================================================================
// round 13：命令队列 / 选择集 / 过滤
// =============================================================================
order CMLib_UnitOrderAt(unit lp_unit, int lp_index) {
    if ((CMLib_UnitOk(lp_unit) == false) || (lp_index < 0)) {
        return null;
    }
    return UnitOrder(lp_unit, lp_index);
}

bool CMLib_UnitOrderHasAbil(unit lp_unit, string lp_ability) {
    if ((CMLib_UnitOk(lp_unit) == false) || (lp_ability == "")) {
        return false;
    }
    return UnitOrderHasAbil(lp_unit, lp_ability);
}

void CMLib_SelClear(int lp_player) {
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return;
    }
    UnitClearSelection(lp_player);
}

unitgroup CMLib_UGSelected(int lp_player) {
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return UnitGroupEmpty();
    }
    return UnitGroupSelected(lp_player);
}

unitgroup CMLib_UGFilterStr(string lp_type, int lp_player, unitgroup lp_group,
                            string lp_filterSpec, int lp_maxCount) {
    unitfilter lv_filter;
    int        lv_max;

    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return UnitGroupEmpty();
    }
    lv_max = lp_maxCount;
    if ((lv_max < 0)) {
        lv_max = 0;
    }
    if ((lp_filterSpec == "")) {
        lv_filter = CMLib_FilterAlive();
    }
    else {
        lv_filter = UnitFilterStr(lp_filterSpec);
    }
    return UnitGroupFilter(lp_type, lp_player, lp_group, lv_filter, lv_max);
}
''', "CMLib_UnitOrderAt")

# =============================================================================
# 2. catalog —— CatalogFieldExists / CatalogReferenceSet
# =============================================================================
append("cmlib_catalog_h.galaxy", '''
// ---- round 13：字段存在性 / 引用写入（真实缺口补齐）-------------------------
// 某 Catalog 作用域下字段路径是否存在。读字段前先探，避免拿到空串当默认值。
bool CMLib_CatFieldExists(string lp_scope, string lp_field);
// 按「引用路径」写值（CatalogReferenceSet），用于改数据层引用而非字面值。
// 引用串非法 / 空返回 false。
bool CMLib_CatRefSet(string lp_reference, int lp_player, string lp_value);
''', "CMLib_CatFieldExists")

append("cmlib_catalog.galaxy", '''
// =============================================================================
// round 13：字段存在性 / 引用写入
// =============================================================================
bool CMLib_CatFieldExists(string lp_scope, string lp_field) {
    if ((lp_scope == "") || (lp_field == "")) {
        return false;
    }
    return CatalogFieldExists(lp_scope, lp_field);
}

bool CMLib_CatRefSet(string lp_reference, int lp_player, string lp_value) {
    if ((lp_reference == "")) {
        return false;
    }
    return CatalogReferenceSet(lp_reference, lp_player, lp_value);
}
''', "CMLib_CatFieldExists")

# =============================================================================
# 3. geo —— PointGetFacing / PointSetFacing / PointPathingCost
#            RegionAddRegion / RegionGetBoundsMin / RegionGetBoundsMax
# =============================================================================
append("cmlib_geo_h.galaxy", '''
// ---- round 13：点朝向 / 寻路代价 / 区域合并与包围盒（真实缺口补齐）---------
// 点自带的朝向（度）。null 返回 0.0。
fixed CMLib_PointFacing(point lp_p);
// 设置点自带朝向（度）。生成单位时用它统一朝向，避免每处手传 facing。
void  CMLib_PointSetFacing(point lp_p, fixed lp_facing);
// 两点间寻路代价（不可达 / null 返回 -1）。用于生成点可达性预检。
int   CMLib_PathCost(point lp_a, point lp_b);
// 把 lp_add 并入 lp_target（原地修改 lp_target）。任一为 null 安全返回。
void  CMLib_RegionAdd(region lp_target, region lp_add);
// 区域包围盒左下 / 右上角点。null 返回 null。
point CMLib_RegionBoundsMin(region lp_r);
point CMLib_RegionBoundsMax(region lp_r);
''', "CMLib_PointFacing")

append("cmlib_geo.galaxy", '''
// =============================================================================
// round 13：点朝向 / 寻路代价 / 区域合并与包围盒
// =============================================================================
fixed CMLib_PointFacing(point lp_p) {
    if ((lp_p == null)) {
        return 0.0;
    }
    return PointGetFacing(lp_p);
}

void CMLib_PointSetFacing(point lp_p, fixed lp_facing) {
    if ((lp_p == null)) {
        return;
    }
    PointSetFacing(lp_p, lp_facing);
}

int CMLib_PathCost(point lp_a, point lp_b) {
    if ((lp_a == null) || (lp_b == null)) {
        return -1;
    }
    return PointPathingCost(lp_a, lp_b);
}

void CMLib_RegionAdd(region lp_target, region lp_add) {
    if ((lp_target == null) || (lp_add == null)) {
        return;
    }
    RegionAddRegion(lp_target, lp_add);
}

point CMLib_RegionBoundsMin(region lp_r) {
    if ((lp_r == null)) {
        return null;
    }
    return RegionGetBoundsMin(lp_r);
}

point CMLib_RegionBoundsMax(region lp_r) {
    if ((lp_r == null)) {
        return null;
    }
    return RegionGetBoundsMax(lp_r);
}
''', "CMLib_PointFacing")

# =============================================================================
# 4. fx —— CameraShake(预设版) / CameraGetTarget / CameraSave / CameraRestore
#           SoundChannelMute / SoundPlayAtPointForPlayer
# =============================================================================
append("cmlib_fx_h.galaxy", '''
// ---- round 13：镜头预设抖动 / 存档恢复 / 声道与带主控声音（真实缺口）------
// 预设版镜头抖动：amplitude / frequency 传 Camera 数据表里的**预设名**（字符串），
// 与参数版 CMLib_CamShake（走 CameraShakeStart，数值参数）互补，不是重复。
// 任一预设名为空则安全返回。
void  CMLib_CamShakePreset(int lp_player, string lp_amplitude, string lp_frequency,
                           fixed lp_blendIn, fixed lp_blendOut, fixed lp_duration);
// 玩家镜头当前注视点。
point CMLib_CamTarget(int lp_player);
// 保存 / 恢复玩家镜头（过场进出的标准配对）。
void  CMLib_CamSave(int lp_player);
void  CMLib_CamRestore(int lp_player, fixed lp_duration, fixed lp_velocity,
                       fixed lp_decelerate);
// 静音 / 取消静音某个声道（channel 为引擎声道序号，core 未导出常量故用裸 int）。
void  CMLib_SfxChannelMute(playergroup lp_players, int lp_channel, bool lp_mute);
// 带「主控玩家」的定点播放：区别于 CMLib_SfxPlayAt（走 SoundPlayAtPoint、无归属），
// 归属玩家会参与音量 / 静音规则判定。
void  CMLib_SfxPlayAtFor(string lp_soundId, int lp_owner, playergroup lp_players,
                         point lp_at, fixed lp_volume);
''', "CMLib_CamShakePreset")

append("cmlib_fx.galaxy", '''
// =============================================================================
// round 13：镜头预设抖动 / 存档恢复 / 声道与带主控声音
// =============================================================================
void CMLib_CamShakePreset(int lp_player, string lp_amplitude, string lp_frequency,
                          fixed lp_blendIn, fixed lp_blendOut, fixed lp_duration) {
    if ((lp_amplitude == "") || (lp_frequency == "")) {
        return;
    }
    CameraShake(lp_player, lp_amplitude, lp_frequency, lp_blendIn, lp_blendOut,
                lp_duration);
}

point CMLib_CamTarget(int lp_player) {
    return CameraGetTarget(lp_player);
}

void CMLib_CamSave(int lp_player) {
    CameraSave(lp_player);
}

void CMLib_CamRestore(int lp_player, fixed lp_duration, fixed lp_velocity,
                      fixed lp_decelerate) {
    CameraRestore(lp_player, lp_duration, lp_velocity, lp_decelerate);
}

void CMLib_SfxChannelMute(playergroup lp_players, int lp_channel, bool lp_mute) {
    if ((lp_players == null)) {
        return;
    }
    SoundChannelMute(lp_players, lp_channel, lp_mute);
}

void CMLib_SfxPlayAtFor(string lp_soundId, int lp_owner, playergroup lp_players,
                        point lp_at, fixed lp_volume) {
    if ((lp_soundId == "") || (lp_at == null)) {
        return;
    }
    SoundPlayAtPointForPlayer(CMLib_SfxLink(lp_soundId, -1), lp_owner, lp_players,
                              lp_at, 0.0, CMLib_FxVol(lp_volume), CMLIB_FX_NO_OFFSET);
}
''', "CMLib_CamShakePreset")

# =============================================================================
# 5. trig —— TriggerGetExecCount + 4 个事件取参
# =============================================================================
append("cmlib_trig_h.galaxy", '''
// ---- round 13：触发器执行计数 + 事件取参补齐（真实缺口）--------------------
// 触发器累计执行次数。null 返回 0。用于「只跑一次」与死循环自检。
int  CMLib_TrigExecCount(trigger lp_t);
// 「单位被创建」事件：取被创建的单位。
unit CMLib_EvtCreatedUnit();
// 「单位受伤」事件：取伤害来源玩家 / 来源单位。
int  CMLib_EvtDmgSourcePlayer();
unit CMLib_EvtDmgSourceUnit();
// 「效果被使用」事件：取指定位置单位的归属玩家（位置用 CMLIB_EFFECT_LOC_* 常量）。
int  CMLib_EvtEffectUsedUnitOwner(int lp_location);
''', "CMLib_TrigExecCount")

append("cmlib_trig.galaxy", '''
// =============================================================================
// round 13：触发器执行计数 + 事件取参补齐
// =============================================================================
int CMLib_TrigExecCount(trigger lp_t) {
    if ((lp_t == null)) {
        return 0;
    }
    return TriggerGetExecCount(lp_t);
}

unit CMLib_EvtCreatedUnit() {
    return EventUnitCreatedUnit();
}

int CMLib_EvtDmgSourcePlayer() {
    return EventUnitDamageSourcePlayer();
}

unit CMLib_EvtDmgSourceUnit() {
    return EventUnitDamageSourceUnit();
}

int CMLib_EvtEffectUsedUnitOwner(int lp_location) {
    return EventPlayerEffectUsedUnitOwner(lp_location);
}
''', "CMLib_TrigExecCount")

print("库扩展完成：24 个封装（5 个模块对，18 模块 / 37 文件不变）")
