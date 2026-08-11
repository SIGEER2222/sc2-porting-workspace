# -*- coding: utf-8 -*-
"""Round20 扩展：补齐「单位 / 建筑 / 面板效果」三大主线上剩余的真实缺口。

对齐任务书原话 ——「分析当前所有 mod 的各个单位、建筑、面板效果的实现，
提取一个通用函数库出来」。前 19 轮把骨架铺满了，本轮专门回头补这三条主线
上仍然露着的洞，外加覆盖率最低的两个真实域（DataTable 66.1% / conversation）。

本轮 57 个 native 全部是 CMLib 从未调用过的（_tmp_dup20 查重），
新增 4 个已用 native 的强化封装不重复计数。

铁律（round19 用一整轮三档全灭换来的）：
  形参类型/个数/常量名一律来自 sigs_round20.py 从 natives.galaxy 的权威抽取，
  绝不凭记忆写。真机上 arity 错 / 常量不存在 = SC2 **静默丢弃整个 MapScript**，
  静态 lint 因 `R3-undeclared` 抑制规则照样报 0 错误。

常量出处已逐个核实：
  c_unitQueueTime* / c_unitQueueProperty* / c_unitProp* / c_unitAttribute* /
  c_unitCount* / c_uiMode* / c_uiCommandAllow* / c_dialogControl* /
  c_soundOffset* / c_orderTarget*        -> natives.galaxy
  c_heightMapAir(0) / c_heightMapGlide(1) / c_heightMapGround(2)
                                         -> Game.galaxy
  （Game.galaxy 在 include 链内已被 round≤19 的 c_playerTypeUser /
     c_allianceIdPassive 真机 418/420 实证过，可安全引用）

注意：`OrderGetFlag` 的 flag 序号引擎**没有导出常量族**（core 全库 grep
`c_orderFlag` 零命中），只能传数据层定义的裸 int，封装里如实注明。

幂等：每块用 MARK 标记，已存在则跳过。
"""
import sys
from pathlib import Path

CM = Path(__file__).resolve().parent / "scripts" / "cmlib"
MARK = "CMLib :: Round20"

BLOCKS = {}

# ============================ unit ==========================================
BLOCKS["cmlib_unit_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 单位 / 建筑主线补完
//
// 这一段回答的是「一个单位或建筑，在运行时到底能被问出什么、能被改什么」：
//   选中闪烁 / 载具舱 / Buff 时长与来源 / 整数属性 / 技能可见性 /
//   建筑落点求解 / 模型挂点 / 生产队列 / 单位名 / 武器与 DPS /
//   采集状态 / 编组选中 / 闲置单位 / 命令(order)目标查询
// =============================================================================

// ---- 视觉与选择 --------------------------------------------------------------
// 让单位的选择圈闪烁 lp_period 秒（0 表示停止）。教学关引导视线常用。
void CMLib_UnitFlash(unit lp_unit, fixed lp_period);
// 批量选中/取消选中。注意这是**改玩家选择框**，不是加编组。
void CMLib_UGSelect(unitgroup lp_group, int lp_player, bool lp_select);
// 该玩家当前闲置的单位；workerOnly=true 时只要闲置农民（经营类地图刚需）。
unitgroup CMLib_UGIdle(int lp_player, bool lp_workerOnly);
int CMLib_UGIdleCount(int lp_player, bool lp_workerOnly);

// ---- 载具舱 ------------------------------------------------------------------
// 车/船/虫道里装的单位；单位无效或空舱一律返回空组（绝不返回 null）。
unitgroup CMLib_UnitCargo(unit lp_unit);
int CMLib_UnitCargoCount(unit lp_unit);

// ---- Buff 时长与来源 ----------------------------------------------------------
// 强行改写身上某个 Behavior 的剩余时长（做「延长/缩短增益」最直接的一招）。
void CMLib_UnitBuffDuration(unit lp_unit, string lp_behavior, fixed lp_duration);
// 取该 Behavior 的关联单位（施法者 / 来源 / 目标，由 lp_location 决定）。
unit CMLib_UnitBuffEffectUnit(unit lp_unit, string lp_behavior, int lp_location,
                              int lp_index);

// ---- 属性 --------------------------------------------------------------------
// 整数通道读属性（c_unitProp*）；current=false 读的是基础值而非当前值。
int   CMLib_UnitPropInt(unit lp_unit, int lp_prop, bool lp_current);

// ---- 技能 --------------------------------------------------------------------
// 只控制命令面板上「看不看得见」，不等于禁用（禁用请用 AbilEnable 那一族）。
void CMLib_UnitAbilShow(unit lp_unit, string lp_abil, bool lp_show);
bool CMLib_UnitAbilExists(unit lp_unit, string lp_abil);

// ---- 建筑放置 ----------------------------------------------------------------
// 在 lp_source 附近 lp_range 内求一个能放下该建筑的合法落点。
// 求不到返回 null —— 调用方必须判空，别直接喂给 UnitCreate。
point CMLib_UnitTypePlaceNear(string lp_unitType, int lp_player, point lp_source,
                              fixed lp_range);

// ---- 模型挂点 ----------------------------------------------------------------
// 取模型挂点的世界坐标（"Ref_Weapon"/"Ref_Center" 等）；失败返回 null。
point CMLib_UnitAttachPoint(unit lp_unit, string lp_attachment);

// ---- 生产队列 ----------------------------------------------------------------
// 队列容量属性（c_unitQueueProperty*）。
int  CMLib_UnitQueueProp(unit lp_unit, int lp_prop);
int  CMLib_UnitQueueUsed(unit lp_unit);
int  CMLib_UnitQueueFree(unit lp_unit);
bool CMLib_UnitIsProducing(unit lp_unit);
// 指定队列槽里的条目数 / 第 N 条的 id / 第 N 条是不是某类型。
int    CMLib_UnitQueueItemCount(unit lp_unit, int lp_slot);
string CMLib_UnitQueueItemAt(unit lp_unit, int lp_item, int lp_slot);
bool   CMLib_UnitQueueItemIs(unit lp_unit, int lp_item, int lp_type);
// 第 N 条还差几秒 / 完成度 0.0~1.0（进度条直接用这个）。
fixed CMLib_UnitQueueEta(unit lp_unit, int lp_item);
fixed CMLib_UnitQueueProgress(unit lp_unit, int lp_item);

// ---- 名称 --------------------------------------------------------------------
// 本地化后的单位显示名；无效单位返回空 text 而不是 null。
// 单位**实例**的显示名 —— 英雄改过名、剧情单位挂过自定义名的，读到的是那个。
// 和 text 模块的 CMLib_UnitName 区别很大：后者走 UnitGetType 拿的是**类型名**，
// 同一批小兵读出来全一样。要显示"这一个"就用 CustomName。
text CMLib_UnitCustomName(unit lp_unit);

// ---- 武器 --------------------------------------------------------------------
int   CMLib_UnitWeaponCount(unit lp_unit);
fixed CMLib_UnitWeaponPeriod(unit lp_unit, int lp_index);
fixed CMLib_UnitWeaponDamage(unit lp_unit, int lp_index, int lp_attribute,
                             bool lp_maximum);
// 单武器 DPS = 伤害 / 攻击间隔；间隔<=0 时返回 0 而不是除零。
fixed CMLib_UnitWeaponDps(unit lp_unit, int lp_index);
// 全武器 DPS 求和（对空对地都算，做战力评估用）。
fixed CMLib_UnitDpsTotal(unit lp_unit);

// ---- 采集 --------------------------------------------------------------------
bool CMLib_UnitIsHarvesting(unit lp_unit, int lp_resource);

// ---- 命令(order) 目标查询 -----------------------------------------------------
// flag 序号由数据层定义，引擎没有导出 c_orderFlag* 常量族，只能传裸 int。
bool  CMLib_OrderFlag(order lp_order, int lp_flag);
// 不管目标是点还是单位，一律给出世界坐标；没有目标返回 null。
point CMLib_OrderTargetPos(order lp_order);
// c_orderTargetNone / Point / Unit / Item
int   CMLib_OrderTargetType(order lp_order);
bool  CMLib_OrderHasTarget(order lp_order);
"""

BLOCKS["cmlib_unit.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 单位 / 建筑主线补完（实现）
// =============================================================================

void CMLib_UnitFlash(unit lp_unit, fixed lp_period) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    if (lp_period < 0.0) { return; }
    UnitFlashSelection(lp_unit, lp_period);
}

void CMLib_UGSelect(unitgroup lp_group, int lp_player, bool lp_select) {
    if (lp_group == null) { return; }
    if (CMLib_IsValidPlayerSlot(lp_player) == false) { return; }
    UnitGroupSelect(lp_group, lp_player, lp_select);
}

unitgroup CMLib_UGIdle(int lp_player, bool lp_workerOnly) {
    unitgroup lv_g;

    if (CMLib_IsValidPlayerSlot(lp_player) == false) { return UnitGroupEmpty(); }
    lv_g = UnitGroupIdle(lp_player, lp_workerOnly);
    if (lv_g == null) { return UnitGroupEmpty(); }
    return lv_g;
}

int CMLib_UGIdleCount(int lp_player, bool lp_workerOnly) {
    return UnitGroupCount(CMLib_UGIdle(lp_player, lp_workerOnly), c_unitCountAll);
}

unitgroup CMLib_UnitCargo(unit lp_unit) {
    unitgroup lv_g;

    if (CMLib_UnitOk(lp_unit) == false) { return UnitGroupEmpty(); }
    lv_g = UnitCargoGroup(lp_unit);
    if (lv_g == null) { return UnitGroupEmpty(); }
    return lv_g;
}

int CMLib_UnitCargoCount(unit lp_unit) {
    return UnitGroupCount(CMLib_UnitCargo(lp_unit), c_unitCountAll);
}

void CMLib_UnitBuffDuration(unit lp_unit, string lp_behavior, fixed lp_duration) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    if (lp_behavior == "") { return; }
    if (lp_duration < 0.0) { return; }
    UnitBehaviorSetDuration(lp_unit, lp_behavior, lp_duration);
}

unit CMLib_UnitBuffEffectUnit(unit lp_unit, string lp_behavior, int lp_location,
                              int lp_index) {
    if (CMLib_UnitOk(lp_unit) == false) { return null; }
    if (lp_behavior == "") { return null; }
    if (lp_index < 0) { return null; }
    return UnitBehaviorEffectUnit(lp_unit, lp_behavior, lp_location, lp_index);
}

int CMLib_UnitPropInt(unit lp_unit, int lp_prop, bool lp_current) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0; }
    return UnitGetPropertyInt(lp_unit, lp_prop, lp_current);
}


void CMLib_UnitAbilShow(unit lp_unit, string lp_abil, bool lp_show) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    if (lp_abil == "") { return; }
    UnitAbilityShow(lp_unit, lp_abil, lp_show);
}

bool CMLib_UnitAbilExists(unit lp_unit, string lp_abil) {
    if (CMLib_UnitOk(lp_unit) == false) { return false; }
    if (lp_abil == "") { return false; }
    return UnitAbilityExists(lp_unit, lp_abil);
}

point CMLib_UnitTypePlaceNear(string lp_unitType, int lp_player, point lp_source,
                              fixed lp_range) {
    if (lp_unitType == "") { return null; }
    if (lp_source == null) { return null; }
    if (CMLib_IsValidPlayerSlot(lp_player) == false) { return null; }
    if (lp_range < 0.0) { return null; }
    return UnitTypePlacementFromPoint(lp_unitType, lp_player, lp_source, lp_range);
}

point CMLib_UnitAttachPoint(unit lp_unit, string lp_attachment) {
    if (CMLib_UnitOk(lp_unit) == false) { return null; }
    if (lp_attachment == "") { return null; }
    return UnitGetAttachmentPoint(lp_unit, lp_attachment);
}

int CMLib_UnitQueueProp(unit lp_unit, int lp_prop) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0; }
    return UnitQueueGetProperty(lp_unit,
                                CMLib_ClampInt(lp_prop, c_unitQueuePropertyAvailable,
                                               c_unitQueuePropertyCount));
}

int CMLib_UnitQueueUsed(unit lp_unit) {
    return CMLib_UnitQueueProp(lp_unit, c_unitQueuePropertyUsed);
}

int CMLib_UnitQueueFree(unit lp_unit) {
    return CMLib_UnitQueueProp(lp_unit, c_unitQueuePropertyAvailable);
}

bool CMLib_UnitIsProducing(unit lp_unit) {
    return (CMLib_UnitQueueUsed(lp_unit) > 0);
}

int CMLib_UnitQueueItemCount(unit lp_unit, int lp_slot) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0; }
    if (lp_slot < 0) { return 0; }
    return UnitQueueItemCount(lp_unit, lp_slot);
}

string CMLib_UnitQueueItemAt(unit lp_unit, int lp_item, int lp_slot) {
    string lv_s;

    if (CMLib_UnitOk(lp_unit) == false) { return ""; }
    if ((lp_item < 0) || (lp_slot < 0)) { return ""; }
    lv_s = UnitQueueItemGet(lp_unit, lp_item, lp_slot);
    if (lv_s == null) { return ""; }
    return lv_s;
}

bool CMLib_UnitQueueItemIs(unit lp_unit, int lp_item, int lp_type) {
    if (CMLib_UnitOk(lp_unit) == false) { return false; }
    if (lp_item < 0) { return false; }
    return UnitQueueItemTypeCheck(lp_unit, lp_item, lp_type);
}

fixed CMLib_UnitQueueEta(unit lp_unit, int lp_item) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0.0; }
    if (lp_item < 0) { return 0.0; }
    return UnitQueueItemTime(lp_unit, c_unitQueueTimeRemaining, lp_item);
}

fixed CMLib_UnitQueueProgress(unit lp_unit, int lp_item) {
    fixed lv_total;
    fixed lv_elapsed;

    if (CMLib_UnitOk(lp_unit) == false) { return 0.0; }
    if (lp_item < 0) { return 0.0; }
    lv_total = UnitQueueItemTime(lp_unit, c_unitQueueTimeTotal, lp_item);
    if (lv_total <= 0.0) { return 0.0; }
    lv_elapsed = UnitQueueItemTime(lp_unit, c_unitQueueTimeElapsed, lp_item);
    return CMLib_ClampFixed((lv_elapsed / lv_total), 0.0, 1.0);
}

text CMLib_UnitCustomName(unit lp_unit) {
    if (CMLib_UnitOk(lp_unit) == false) { return StringToText(""); }
    return UnitGetName(lp_unit);
}

int CMLib_UnitWeaponCount(unit lp_unit) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0; }
    return UnitWeaponCount(lp_unit);
}

fixed CMLib_UnitWeaponPeriod(unit lp_unit, int lp_index) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0.0; }
    if (lp_index < 1) { return 0.0; }
    if (lp_index > UnitWeaponCount(lp_unit)) { return 0.0; }
    return UnitWeaponPeriod(lp_unit, lp_index);
}

fixed CMLib_UnitWeaponDamage(unit lp_unit, int lp_index, int lp_attribute,
                             bool lp_maximum) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0.0; }
    if (lp_index < 1) { return 0.0; }
    if (lp_index > UnitWeaponCount(lp_unit)) { return 0.0; }
    return UnitWeaponDamage(lp_unit, lp_index, lp_attribute, lp_maximum);
}

fixed CMLib_UnitWeaponDps(unit lp_unit, int lp_index) {
    fixed lv_period;
    fixed lv_damage;

    lv_period = CMLib_UnitWeaponPeriod(lp_unit, lp_index);
    if (lv_period <= 0.0) { return 0.0; }
    lv_damage = CMLib_UnitWeaponDamage(lp_unit, lp_index, c_unitAttributeNone, false);
    return (lv_damage / lv_period);
}

fixed CMLib_UnitDpsTotal(unit lp_unit) {
    fixed lv_sum;
    int   lv_i;
    int   lv_n;

    lv_sum = 0.0;
    if (CMLib_UnitOk(lp_unit) == false) { return 0.0; }
    lv_n = UnitWeaponCount(lp_unit);
    lv_i = 1;
    while (lv_i <= lv_n) {
        lv_sum = (lv_sum + CMLib_UnitWeaponDps(lp_unit, lv_i));
        lv_i = (lv_i + 1);
    }
    return lv_sum;
}

bool CMLib_UnitIsHarvesting(unit lp_unit, int lp_resource) {
    if (CMLib_UnitOk(lp_unit) == false) { return false; }
    return UnitIsHarvesting(lp_unit, lp_resource);
}

bool CMLib_OrderFlag(order lp_order, int lp_flag) {
    if (lp_order == null) { return false; }
    if (lp_flag < 0) { return false; }
    return OrderGetFlag(lp_order, lp_flag);
}

int CMLib_OrderTargetType(order lp_order) {
    if (lp_order == null) { return c_orderTargetNone; }
    return OrderGetTargetType(lp_order);
}

point CMLib_OrderTargetPos(order lp_order) {
    if (lp_order == null) { return null; }
    if (OrderGetTargetType(lp_order) == c_orderTargetNone) { return null; }
    return OrderGetTargetPosition(lp_order);
}

bool CMLib_OrderHasTarget(order lp_order) {
    return (CMLib_OrderTargetType(lp_order) != c_orderTargetNone);
}
"""

# ============================ board (胜利/结算面板) ==========================
BLOCKS["cmlib_board_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 结算面板成就
// 任务通关后在结算页列出解锁的成就；空串直接跳过，避免面板出现空行。
// =============================================================================
void CMLib_VPanelAchievement(string lp_achievement);
// CSV 批量，形如 "Ach_NoLosses,Ach_SpeedRun"。
void CMLib_VPanelAchievementBatch(string lp_csv);
"""

BLOCKS["cmlib_board.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 结算面板成就（实现）
// =============================================================================
void CMLib_VPanelAchievement(string lp_achievement) {
    if (lp_achievement == "") { return; }
    VictoryPanelAddAchievement(lp_achievement);
}

void CMLib_VPanelAchievementBatch(string lp_csv) {
    int    lv_n;
    int    lv_i;
    string lv_one;

    if (lp_csv == "") { return; }
    lv_n = CMLib_SplitCount(lp_csv, ",");
    lv_i = 0;
    while (lv_i < lv_n) {
        lv_one = CMLib_TrimSpaces(CMLib_SplitAt(lp_csv, ",", lv_i));
        if (lv_one != "") {
            VictoryPanelAddAchievement(lv_one);
        }
        lv_i = (lv_i + 1);
    }
}
"""

# ============================ ui (面板效果) =================================
BLOCKS["cmlib_ui_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 面板效果补完
//
// 覆盖三件事：
//   1. Dialog 控件的**反查**（可见性 / 属于哪个对话框 / 挂靠单位状态框架）
//   2. 命令面板开关（c_uiCommandAllow*，做教学关锁操作的正规姿势）
//   3. 目标选择模式（UISetTargetingOrder，自定义技能施法圈）与警报清理
// =============================================================================

// ---- Dialog 控件反查 ----------------------------------------------------------
// 控件 id 非法（<=c_invalidDialogControlId）一律 false / 0，不去问引擎。
bool CMLib_DlgCtrlVisible(int lp_control, int lp_player);
int  CMLib_DlgCtrlDialog(int lp_control);
// 把 XML 里定义的单位状态框架挂成脚本可控的控件；失败返回 c_invalidDialogControlId。
int  CMLib_DlgHookupUnitStatus(int lp_type, string lp_template, unit lp_unit);

// ---- 命令面板开关 -------------------------------------------------------------
// option 取 c_uiCommandAllowButtons / Hotkeys / SmartClick / Modifiers /
//            InfoPanel / Minimap / Pings / ModifiersSmartCtrlAttack /
//            InventoryTargeting
void CMLib_UICommandAllow(playergroup lp_players, int lp_option, bool lp_allow);
// 一次性开关全部 9 项（教学关「先锁死再逐项放开」的常用起手式）。
void CMLib_UICommandAllowAll(playergroup lp_players, bool lp_allow);

// ---- 目标选择模式 / 警报 -------------------------------------------------------
// 强制玩家进入某个命令的目标选择态；sticky=true 时施放后不退出（连点施法）。
void CMLib_UITargetOrder(playergroup lp_players, unitgroup lp_units, order lp_order,
                         bool lp_sticky);
void CMLib_UIAlertClear(int lp_player);
void CMLib_UIAlertClearAll();
"""

BLOCKS["cmlib_ui.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 面板效果补完（实现）
// =============================================================================

bool CMLib_DlgCtrlVisible(int lp_control, int lp_player) {
    if (lp_control <= c_invalidDialogControlId) { return false; }
    if (CMLib_IsValidPlayerSlot(lp_player) == false) { return false; }
    return DialogControlIsVisible(lp_control, lp_player);
}

int CMLib_DlgCtrlDialog(int lp_control) {
    if (lp_control <= c_invalidDialogControlId) { return c_invalidDialogControlId; }
    return DialogControlGetDialog(lp_control);
}

int CMLib_DlgHookupUnitStatus(int lp_type, string lp_template, unit lp_unit) {
    if (lp_template == "") { return c_invalidDialogControlId; }
    if (CMLib_UnitOk(lp_unit) == false) { return c_invalidDialogControlId; }
    return DialogControlHookupUnitStatus(lp_type, lp_template, lp_unit);
}

void CMLib_UICommandAllow(playergroup lp_players, int lp_option, bool lp_allow) {
    if (lp_players == null) { return; }
    UISetCommandAllowed(lp_players,
                        CMLib_ClampInt(lp_option, c_uiCommandAllowButtons,
                                       c_uiCommandAllowInventoryTargeting),
                        lp_allow);
}

void CMLib_UICommandAllowAll(playergroup lp_players, bool lp_allow) {
    int lv_i;

    if (lp_players == null) { return; }
    lv_i = c_uiCommandAllowButtons;
    while (lv_i <= c_uiCommandAllowInventoryTargeting) {
        UISetCommandAllowed(lp_players, lv_i, lp_allow);
        lv_i = (lv_i + 1);
    }
}

void CMLib_UITargetOrder(playergroup lp_players, unitgroup lp_units, order lp_order,
                         bool lp_sticky) {
    if (lp_players == null) { return; }
    if (lp_units == null) { return; }
    if (lp_order == null) { return; }
    UISetTargetingOrder(lp_players, lp_units, lp_order, lp_sticky);
}

void CMLib_UIAlertClear(int lp_player) {
    if (CMLib_IsValidPlayerSlot(lp_player) == false) { return; }
    UIAlertClear(lp_player);
}

void CMLib_UIAlertClearAll() {
    int lv_i;

    lv_i = CMLIB_PLAYER_MIN;
    while (lv_i <= CMLIB_PLAYER_MAX) {
        UIAlertClear(lv_i);
        lv_i = (lv_i + 1);
    }
}
"""

# ============================ core (DataTable 作用域族 + 数学) ==============
BLOCKS["cmlib_core_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— DataTable 作用域族（DT*）与补充数学
//
// 与本模块上半部分的 CMLib_Store* / CMLib_Load* 的分工：
//   · Store/Load   —— 固定 global=true 的「全局便签」，bool 走 int 存储，
//                     方便直接倒进 Bank；日常存个状态用它就够。
//   · DT*          —— 显式带 lp_global 的完整通道，覆盖引擎全部强类型
//                     （bool / unitgroup / timer / objective / region），
//                     还能枚举、按前缀清理。写系统级模块用这一套。
// local 表（global=false）的生命周期跟着**当前线程**走，跨触发器读不到，
// 这一点引擎不会报错，只会让你读到默认值 —— 用之前先想清楚作用域。
//
// gap_scan 显示 data 域覆盖率 66.1%，是排除 GUI 噪声后的真实最低域。
// =============================================================================

// ---- 通用 --------------------------------------------------------------------
bool   CMLib_DTHas(bool lp_global, string lp_key);
void   CMLib_DTRemove(bool lp_global, string lp_key);
void   CMLib_DTClear(bool lp_global);
int    CMLib_DTCount(bool lp_global);
// 按序号取键名（配合 DTCount 遍历整张表）；越界返回 ""。
string CMLib_DTNameAt(bool lp_global, int lp_index);
// 删除所有以 lp_prefix 开头的键，返回删掉的条数。
// 倒序遍历删除 —— 正序删会让后面的 index 整体前移，漏掉一半（老坑）。
int    CMLib_DTClearPrefix(bool lp_global, string lp_prefix);

// ---- 强类型存取（不存在时返回 fallback / 空值，绝不抛给引擎） -----------------
void       CMLib_DTSetBool(bool lp_global, string lp_key, bool lp_value);
bool       CMLib_DTGetBool(bool lp_global, string lp_key, bool lp_fallback);
void       CMLib_DTSetUG(bool lp_global, string lp_key, unitgroup lp_value);
unitgroup  CMLib_DTGetUG(bool lp_global, string lp_key);
void       CMLib_DTSetTimer(bool lp_global, string lp_key, timer lp_value);
timer      CMLib_DTGetTimer(bool lp_global, string lp_key);
void       CMLib_DTSetObjective(bool lp_global, string lp_key, int lp_value);
int        CMLib_DTGetObjective(bool lp_global, string lp_key);
void       CMLib_DTSetRegion(bool lp_global, string lp_key, region lp_value);
region     CMLib_DTGetRegion(bool lp_global, string lp_key);

// ---- 补充数学 / 计时器 ---------------------------------------------------------
// 四舍五入到 int（引擎的 FixedToInt 是截断，两者别混用）。
int   CMLib_RoundI(fixed lp_x);
fixed CMLib_TimerDuration(timer lp_timer);
bool  CMLib_TimerPaused(timer lp_timer);
// 计时器完成度 0.0~1.0，给进度条用；时长<=0 返回 0。
fixed CMLib_TimerProgress(timer lp_timer);
"""

BLOCKS["cmlib_core.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— DataTable 作用域族（实现）
// =============================================================================

bool CMLib_DTHas(bool lp_global, string lp_key) {
    if (lp_key == "") { return false; }
    return DataTableValueExists(lp_global, lp_key);
}

void CMLib_DTRemove(bool lp_global, string lp_key) {
    if (lp_key == "") { return; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return; }
    DataTableValueRemove(lp_global, lp_key);
}

void CMLib_DTClear(bool lp_global) {
    DataTableClear(lp_global);
}

int CMLib_DTCount(bool lp_global) {
    return DataTableValueCount(lp_global);
}

string CMLib_DTNameAt(bool lp_global, int lp_index) {
    string lv_s;

    if (lp_index < 1) { return ""; }
    if (lp_index > DataTableValueCount(lp_global)) { return ""; }
    lv_s = DataTableValueName(lp_global, lp_index);
    if (lv_s == null) { return ""; }
    return lv_s;
}

int CMLib_DTClearPrefix(bool lp_global, string lp_prefix) {
    int    lv_i;
    int    lv_len;
    int    lv_removed;
    string lv_name;

    lv_removed = 0;
    if (lp_prefix == "") { return 0; }
    lv_len = StringLength(lp_prefix);
    lv_i = DataTableValueCount(lp_global);
    while (lv_i >= 1) {
        lv_name = DataTableValueName(lp_global, lv_i);
        if (lv_name != null) {
            if (StringLength(lv_name) >= lv_len) {
                if (StringSub(lv_name, 1, lv_len) == lp_prefix) {
                    DataTableValueRemove(lp_global, lv_name);
                    lv_removed = (lv_removed + 1);
                }
            }
        }
        lv_i = (lv_i - 1);
    }
    return lv_removed;
}

// ---- 强类型存取 ---------------------------------------------------------------
void CMLib_DTSetBool(bool lp_global, string lp_key, bool lp_value) {
    if (lp_key == "") { return; }
    DataTableSetBool(lp_global, lp_key, lp_value);
}

bool CMLib_DTGetBool(bool lp_global, string lp_key, bool lp_fallback) {
    if (lp_key == "") { return lp_fallback; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return lp_fallback; }
    return DataTableGetBool(lp_global, lp_key);
}

void CMLib_DTSetUG(bool lp_global, string lp_key, unitgroup lp_value) {
    if (lp_key == "") { return; }
    DataTableSetUnitGroup(lp_global, lp_key, lp_value);
}

unitgroup CMLib_DTGetUG(bool lp_global, string lp_key) {
    if (lp_key == "") { return UnitGroupEmpty(); }
    if (DataTableValueExists(lp_global, lp_key) == false) { return UnitGroupEmpty(); }
    return DataTableGetUnitGroup(lp_global, lp_key);
}

void CMLib_DTSetTimer(bool lp_global, string lp_key, timer lp_value) {
    if (lp_key == "") { return; }
    DataTableSetTimer(lp_global, lp_key, lp_value);
}

timer CMLib_DTGetTimer(bool lp_global, string lp_key) {
    if (lp_key == "") { return null; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return null; }
    return DataTableGetTimer(lp_global, lp_key);
}

void CMLib_DTSetObjective(bool lp_global, string lp_key, int lp_value) {
    if (lp_key == "") { return; }
    DataTableSetObjective(lp_global, lp_key, lp_value);
}

int CMLib_DTGetObjective(bool lp_global, string lp_key) {
    if (lp_key == "") { return 0; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return 0; }
    return DataTableGetObjective(lp_global, lp_key);
}

void CMLib_DTSetRegion(bool lp_global, string lp_key, region lp_value) {
    if (lp_key == "") { return; }
    DataTableSetRegion(lp_global, lp_key, lp_value);
}

region CMLib_DTGetRegion(bool lp_global, string lp_key) {
    if (lp_key == "") { return null; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return null; }
    return DataTableGetRegion(lp_global, lp_key);
}

// ---- 补充数学 / 计时器 ---------------------------------------------------------
int CMLib_RoundI(fixed lp_x) {
    return RoundI(lp_x);
}

fixed CMLib_TimerDuration(timer lp_timer) {
    if (lp_timer == null) { return 0.0; }
    return TimerGetDuration(lp_timer);
}

bool CMLib_TimerPaused(timer lp_timer) {
    if (lp_timer == null) { return false; }
    return TimerIsPaused(lp_timer);
}

fixed CMLib_TimerProgress(timer lp_timer) {
    fixed lv_total;
    fixed lv_elapsed;

    if (lp_timer == null) { return 0.0; }
    lv_total = TimerGetDuration(lp_timer);
    if (lv_total <= 0.0) { return 0.0; }
    lv_elapsed = TimerGetElapsed(lp_timer);
    return CMLib_ClampFixed((lv_elapsed / lv_total), 0.0, 1.0);
}
"""

BLOCKS["cmlib_conv_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 数据驱动对话（ConversationData）补齐
//
// conv 域此前只封了 Run / Stop / State 读写，缺「预载 / 存档 / 重置」这三块，
// 而它们恰恰是战役型 mod 最容易踩坑的地方：
//   · 不预载 —— 首句语音有明显吞字（引擎现读现解码）。
//   · 不存档 —— 玩家读档后分支状态回到初始，选过的选项重新出现。
// =============================================================================

// 预载某段对话的全部语音行；进关卡前调一次，别放在对话触发的同一帧。
void   CMLib_ConvDataPreload(string lp_convId);
// 批量预载，lp_csv 形如 "Conv01,Conv02,Conv03"，返回成功提交的条数。
int    CMLib_ConvDataPreloadBatch(string lp_csv);
// 读状态索引上的 fixed 型信息字段（ConvDataStateGet 只能读 int）。
fixed  CMLib_ConvDataStateFixed(string lp_stateIndex, string lp_infoName);
// 当前正在播的那一行对应的 sound id；没有则 ""。
string CMLib_ConvDataActiveSound();
// 对话节点状态（哪些行/选项播过）存进 bank 的指定 section。
void   CMLib_ConvDataSaveNodes(string lp_convId, bank lp_bank, string lp_section);
void   CMLib_ConvDataLoadNodes(string lp_convId, bank lp_bank, string lp_section);
// 把某个 state id 下的全部状态值重置回数据层默认（重开一章时用）。
void   CMLib_ConvDataResetStates(string lp_stateId);
"""

BLOCKS["cmlib_conv.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 数据驱动对话补齐（实现）
// =============================================================================

void CMLib_ConvDataPreload(string lp_convId) {
    if (lp_convId == "") { return; }
    ConversationDataPreloadLines(lp_convId);
}

int CMLib_ConvDataPreloadBatch(string lp_csv) {
    int    lv_count;
    int    lv_i;
    int    lv_done;
    string lv_id;

    lv_done = 0;
    if (lp_csv == "") { return 0; }
    lv_count = CMLib_SplitCount(lp_csv, ",");
    lv_i = 1;
    while (lv_i <= lv_count) {
        lv_id = CMLib_TrimSpaces(CMLib_SplitAt(lp_csv, ",", lv_i));
        if (lv_id != "") {
            ConversationDataPreloadLines(lv_id);
            lv_done = (lv_done + 1);
        }
        lv_i = (lv_i + 1);
    }
    return lv_done;
}

fixed CMLib_ConvDataStateFixed(string lp_stateIndex, string lp_infoName) {
    if (lp_stateIndex == "") { return 0.0; }
    if (lp_infoName == "") { return 0.0; }
    return ConversationDataStateFixedValue(lp_stateIndex, lp_infoName);
}

string CMLib_ConvDataActiveSound() {
    string lv_id;

    lv_id = ConversationDataActiveSound();
    if (lv_id == null) { return ""; }
    return lv_id;
}

void CMLib_ConvDataSaveNodes(string lp_convId, bank lp_bank, string lp_section) {
    if (lp_convId == "") { return; }
    if (lp_bank == null) { return; }
    if (lp_section == "") { return; }
    ConversationDataSaveNodeState(lp_convId, lp_bank, lp_section);
}

void CMLib_ConvDataLoadNodes(string lp_convId, bank lp_bank, string lp_section) {
    if (lp_convId == "") { return; }
    if (lp_bank == null) { return; }
    if (lp_section == "") { return; }
    ConversationDataLoadNodeState(lp_convId, lp_bank, lp_section);
}

void CMLib_ConvDataResetStates(string lp_stateId) {
    if (lp_stateId == "") { return; }
    ConversationDataResetStateValues(lp_stateId);
}
"""

BLOCKS["cmlib_geo_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 地形高度图采样
//
// CMLib_PointHeight 读的是 point 自带的高度分量（点被创建时钉住的值），
// 而 CMLib_TerrainHeight 是**实时**去采样地形高度图 —— 悬崖、可破坏地形、
// 剧情中被抬升/下沉的地块，只有后者能读到当前真实值。
//
// lp_layer 传引擎的 c_heightMap<*>（Air / Glide / Ground）。
// 本库刻意不复制这三个常量的数值：它们不在 core 的 natives.galaxy 里声明，
// 抄一份进来就是在赌数值不变 —— round19 已经用一次三档全灭买过这个教训。
// 调用方直接写 c_heightMapGround 即可，编译期由引擎解析。
// =============================================================================

fixed CMLib_TerrainHeight(int lp_layer, point lp_p);
// 两点在同一高度图层上的高度差（b - a）；用来判断"上坡还是下坡"。
fixed CMLib_TerrainHeightDelta(int lp_layer, point lp_a, point lp_b);
// 两点是否算同一层平地（高度差在 lp_tolerance 内）。悬崖判定的常用写法。
bool  CMLib_TerrainSameLevel(int lp_layer, point lp_a, point lp_b, fixed lp_tolerance);
"""

BLOCKS["cmlib_geo.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— 地形高度图采样（实现）
// =============================================================================

fixed CMLib_TerrainHeight(int lp_layer, point lp_p) {
    if (lp_p == null) { return 0.0; }
    return WorldHeight(lp_layer, lp_p);
}

fixed CMLib_TerrainHeightDelta(int lp_layer, point lp_a, point lp_b) {
    if (lp_a == null) { return 0.0; }
    if (lp_b == null) { return 0.0; }
    return (WorldHeight(lp_layer, lp_b) - WorldHeight(lp_layer, lp_a));
}

bool CMLib_TerrainSameLevel(int lp_layer, point lp_a, point lp_b, fixed lp_tolerance) {
    fixed lv_delta;

    if (lp_a == null) { return false; }
    if (lp_b == null) { return false; }
    lv_delta = (WorldHeight(lp_layer, lp_b) - WorldHeight(lp_layer, lp_a));
    if (lv_delta < 0.0) { lv_delta = -lv_delta; }
    return (lv_delta <= lp_tolerance);
}
"""

BLOCKS["cmlib_udata_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— UserData 补齐：升级引用与整型重置
// =============================================================================

// 把某个 UserData 类型下**所有实例**的字段重置回数据层默认值。
// 注意作用域是整个 type，不是单个 instance —— 换关卡/重开局时用，
// 局内想清单个实例请逐字段 CMLib_UDataSet*。
void   CMLib_UDataResetType(string lp_type);
// 读 upgrade 型字段（返回 upgrade 的 link id 字符串），越界/不存在返回 ""。
string CMLib_UDataUpgrade(string lp_type, string lp_instance, string lp_field, int lp_index);
// 便捷版：取第 0 个索引。
string CMLib_UDataUpgrade0(string lp_type, string lp_instance, string lp_field);
"""

BLOCKS["cmlib_udata.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— UserData 补齐（实现）
// =============================================================================

void CMLib_UDataResetType(string lp_type) {
    if (lp_type == "") { return; }
    UserDataResetType(lp_type);
}

string CMLib_UDataUpgrade(string lp_type, string lp_instance, string lp_field, int lp_index) {
    string lv_val;

    if (lp_type == "") { return ""; }
    if (lp_instance == "") { return ""; }
    if (lp_field == "") { return ""; }
    if (lp_index < 0) { return ""; }
    lv_val = UserDataGetUpgrade(lp_type, lp_instance, lp_field, lp_index);
    if (lv_val == null) { return ""; }
    return lv_val;
}

string CMLib_UDataUpgrade0(string lp_type, string lp_instance, string lp_field) {
    return CMLib_UDataUpgrade(lp_type, lp_instance, lp_field, 0);
}
"""

BLOCKS["cmlib_fx_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— Cutscene 播放控制与声音同步等待
//
// ⚠️ CMLib_SfxWait* 内部是 SoundWait，属于**阻塞式等待**：
//    只能在允许 Wait 的线程里调（普通触发器 / TriggerExecute 出去的分支），
//    放进条件判断、Actor 事件回调或 InitMap 主线里会把整条线程钉死。
//    需要非阻塞的按时长排程，请改用 CMLib_SfxLength + Timer。
// =============================================================================

// 播放 Cutscene Editor 制作的场景（句柄由 CutsceneCreate 系列返回，<=0 视为无效）。
void CMLib_CutscenePlay(int lp_cutscene);
// 跳到场景内的命名书签，成功返回 true（句柄有效且书签名非空）。
bool CMLib_CutsceneBookmark(int lp_cutscene, string lp_bookmark);
// 等到声音播放到「距开头 lp_offset 秒」处。
void CMLib_SfxWaitFrom(sound lp_sound, fixed lp_offset);
// 等到声音播放到「距结尾 lp_offset 秒」处；lp_offset=0 即等到整段放完。
void CMLib_SfxWaitEnd(sound lp_sound, fixed lp_offset);
"""

BLOCKS["cmlib_fx.galaxy"] = r"""
// =============================================================================
// CMLib :: Round20 —— Cutscene 与声音同步等待（实现）
// =============================================================================

void CMLib_CutscenePlay(int lp_cutscene) {
    if (lp_cutscene <= 0) { return; }
    CutscenePlay(lp_cutscene);
}

bool CMLib_CutsceneBookmark(int lp_cutscene, string lp_bookmark) {
    if (lp_cutscene <= 0) { return false; }
    if (lp_bookmark == "") { return false; }
    CutsceneGoToBookmark(lp_cutscene, lp_bookmark);
    return true;
}

void CMLib_SfxWaitFrom(sound lp_sound, fixed lp_offset) {
    fixed lv_offset;

    if (lp_sound == null) { return; }
    lv_offset = lp_offset;
    if (lv_offset < 0.0) { lv_offset = 0.0; }
    SoundWait(lp_sound, lv_offset, c_soundOffsetStart);
}

void CMLib_SfxWaitEnd(sound lp_sound, fixed lp_offset) {
    fixed lv_offset;

    if (lp_sound == null) { return; }
    lv_offset = lp_offset;
    if (lv_offset < 0.0) { lv_offset = 0.0; }
    SoundWait(lp_sound, lv_offset, c_soundOffsetEnd);
}
"""


def main():
    changed, skipped = [], []
    for fname, block in BLOCKS.items():
        p = CM / fname
        if not p.is_file():
            print("!! 缺文件：%s" % fname)
            return 1
        txt = p.read_text(encoding="utf-8", errors="replace")
        if MARK in txt:
            skipped.append(fname)
            continue
        if not txt.endswith("\n"):
            txt += "\n"
        p.write_text(txt + block, encoding="utf-8")
        changed.append(fname)
    print("已追加：%d 个文件" % len(changed))
    for f in changed:
        print("   +", f)
    if skipped:
        print("已存在跳过：%s" % ", ".join(skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
