# -*- coding: utf-8 -*-
"""第 9 轮扩展：面板效果(HUD/消息/警报/淡变) + Catalog 全表遍历 + unit/player/math 真缺口。

幂等：每段补丁先查标记，已存在则跳过。
"""
import os, sys, io

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts", "cmlib")

PATCHES = []


def patch(fname, marker, content):
    PATCHES.append((fname, marker, content))


# =============================================================================
# 1) UI —— 面板效果：HUD 消息区 / 警报 / 淡变 / 原生框架显隐
# =============================================================================
patch("cmlib_ui_h.galaxy", "CMLib_MsgAll", """
// ---- HUD 消息区（UIDisplayMessage 族）---------------------------------------
// 原生 UIDisplayMessage 在 1100+ 处被直接调用，每处都要手写 playergroup 与区域常量。
// 这里给出「区域语义化 + 全员/单人快捷」两层封装；players 传 null 时自动视为全员，
// 避免最常见的空 playergroup 静默丢消息。
void CMLib_Msg(playergroup lp_players, int lp_area, text lp_message);
void CMLib_MsgAll(int lp_area, text lp_message);
void CMLib_MsgPlayer(int lp_player, int lp_area, text lp_message);
void CMLib_MsgClear(playergroup lp_players, int lp_area);
void CMLib_MsgClearAll();
// 语义化快捷（区域常量已内置，调用点不必再记 c_messageArea*）
void CMLib_MsgObjective(playergroup lp_players, text lp_message);
void CMLib_MsgDirective(playergroup lp_players, text lp_message);
void CMLib_MsgError(playergroup lp_players, text lp_message);
void CMLib_MsgSubtitle(playergroup lp_players, text lp_message);
void CMLib_MsgWarning(playergroup lp_players, text lp_message);

// ---- 警报（UIAlertPoint / UIAlertUnit）---------------------------------------
// point / unit 为空时原生会抛脚本错误，这里前置守门后静默跳过。
void CMLib_AlertAtPoint(string lp_alert, int lp_player, text lp_message, string lp_icon, point lp_p);
void CMLib_AlertAtUnit(string lp_alert, int lp_player, text lp_message, string lp_icon, unit lp_unit);

// ---- 透明度淡变 / 动画事件 ----------------------------------------------------
// 【语义坑】SC2 的 transparency：0.0 = 完全不透明，1.0 = 完全透明（与直觉相反）。
// CMLib_UIFadeIn/Out 按「视觉直觉」命名：FadeIn = 淡入可见 = 目标 0.0。
void CMLib_UIFade(int lp_control, playergroup lp_players, fixed lp_seconds, fixed lp_targetTransparency);
void CMLib_UIFadeIn(int lp_control, playergroup lp_players, fixed lp_seconds);
void CMLib_UIFadeOut(int lp_control, playergroup lp_players, fixed lp_seconds);
void CMLib_UIAnimEvent(int lp_control, playergroup lp_players, string lp_eventName);

// ---- 原生 HUD 框架显隐（UISetFrameVisible / UISetWorldVisible）-----------------
void CMLib_HudFrame(playergroup lp_players, int lp_frameType, bool lp_visible);
void CMLib_HudFrameAll(int lp_frameType, bool lp_visible);
// 批量：frameSpec 为逗号分隔的框架类型序号，例如 "21,22,6"（小地图/命令面板/资源栏）。
// 返回实际应用的框架数量。
int  CMLib_HudFrameCSV(playergroup lp_players, string lp_frameSpec, bool lp_visible);
// 过场模式：一次性隐藏/恢复核心 HUD（菜单栏、资源、补给、小地图、命令面板、
// 信息面板、控制台、编队栏、闲置工人、部队按钮、任务目标、警报面板）。
void CMLib_HudCinematic(playergroup lp_players, bool lp_cinematicOn);
void CMLib_HudWorldVisible(playergroup lp_players, bool lp_visible);
""")

patch("cmlib_ui.galaxy", "CMLib_MsgAll", """
// -----------------------------------------------------------------------------
// HUD 消息区
// -----------------------------------------------------------------------------

void CMLib_Msg(playergroup lp_players, int lp_area, text lp_message) {
    playergroup lv_pg;

    lv_pg = lp_players;
    if ((lv_pg == null)) {
        // 空组等于「没人看得到」——这是消息不显示最常见的原因，直接兜底为全员。
        lv_pg = PlayerGroupAll();
    }
    UIDisplayMessage(lv_pg, lp_area, lp_message);
}

void CMLib_MsgAll(int lp_area, text lp_message) {
    UIDisplayMessage(PlayerGroupAll(), lp_area, lp_message);
}

void CMLib_MsgPlayer(int lp_player, int lp_area, text lp_message) {
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return;
    }
    UIDisplayMessage(PlayerGroupSingle(lp_player), lp_area, lp_message);
}

void CMLib_MsgClear(playergroup lp_players, int lp_area) {
    playergroup lv_pg;

    lv_pg = lp_players;
    if ((lv_pg == null)) {
        lv_pg = PlayerGroupAll();
    }
    UIClearMessages(lv_pg, lp_area);
}

void CMLib_MsgClearAll() {
    UIClearMessages(PlayerGroupAll(), c_messageAreaAll);
}

void CMLib_MsgObjective(playergroup lp_players, text lp_message) {
    CMLib_Msg(lp_players, c_messageAreaObjective, lp_message);
}

void CMLib_MsgDirective(playergroup lp_players, text lp_message) {
    CMLib_Msg(lp_players, c_messageAreaDirective, lp_message);
}

void CMLib_MsgError(playergroup lp_players, text lp_message) {
    CMLib_Msg(lp_players, c_messageAreaError, lp_message);
}

void CMLib_MsgSubtitle(playergroup lp_players, text lp_message) {
    CMLib_Msg(lp_players, c_messageAreaSubtitle, lp_message);
}

void CMLib_MsgWarning(playergroup lp_players, text lp_message) {
    CMLib_Msg(lp_players, c_messageAreaWarning, lp_message);
}

// -----------------------------------------------------------------------------
// 警报
// -----------------------------------------------------------------------------

void CMLib_AlertAtPoint(string lp_alert, int lp_player, text lp_message, string lp_icon, point lp_p) {
    if ((lp_p == null)) {
        CMLib_LogWarn("CMLib.UI", "AlertAtPoint skipped, null point");
        return;
    }
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return;
    }
    UIAlertPoint(lp_alert, lp_player, lp_message, lp_icon, lp_p);
}

void CMLib_AlertAtUnit(string lp_alert, int lp_player, text lp_message, string lp_icon, unit lp_unit) {
    if ((lp_unit == null)) {
        CMLib_LogWarn("CMLib.UI", "AlertAtUnit skipped, null unit");
        return;
    }
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return;
    }
    UIAlertUnit(lp_alert, lp_player, lp_message, lp_icon, lp_unit);
}

// -----------------------------------------------------------------------------
// 透明度淡变 / 动画事件
// -----------------------------------------------------------------------------

void CMLib_UIFade(int lp_control, playergroup lp_players, fixed lp_seconds, fixed lp_targetTransparency) {
    playergroup lv_pg;
    fixed lv_secs;
    fixed lv_target;

    if ((CMLib_UIValid(lp_control) == false)) {
        return;
    }
    lv_pg = lp_players;
    if ((lv_pg == null)) {
        lv_pg = PlayerGroupAll();
    }
    lv_secs = lp_seconds;
    if ((lv_secs < 0.0)) {
        lv_secs = 0.0;
    }
    // 越界的 transparency 会被引擎当作未定义行为，先钳到 [0,1]。
    lv_target = CMLib_ClampFixed(lp_targetTransparency, 0.0, 1.0);
    DialogControlFadeTransparency(lp_control, lv_pg, lv_secs, lv_target);
}

void CMLib_UIFadeIn(int lp_control, playergroup lp_players, fixed lp_seconds) {
    CMLib_UIFade(lp_control, lp_players, lp_seconds, 0.0);
}

void CMLib_UIFadeOut(int lp_control, playergroup lp_players, fixed lp_seconds) {
    CMLib_UIFade(lp_control, lp_players, lp_seconds, 1.0);
}

void CMLib_UIAnimEvent(int lp_control, playergroup lp_players, string lp_eventName) {
    playergroup lv_pg;

    if ((CMLib_UIValid(lp_control) == false)) {
        return;
    }
    if ((lp_eventName == "")) {
        return;
    }
    lv_pg = lp_players;
    if ((lv_pg == null)) {
        lv_pg = PlayerGroupAll();
    }
    DialogControlSendAnimationEvent(lp_control, lv_pg, lp_eventName);
}

// -----------------------------------------------------------------------------
// 原生 HUD 框架
// -----------------------------------------------------------------------------

void CMLib_HudFrame(playergroup lp_players, int lp_frameType, bool lp_visible) {
    playergroup lv_pg;

    lv_pg = lp_players;
    if ((lv_pg == null)) {
        lv_pg = PlayerGroupAll();
    }
    UISetFrameVisible(lv_pg, lp_frameType, lp_visible);
}

void CMLib_HudFrameAll(int lp_frameType, bool lp_visible) {
    UISetFrameVisible(PlayerGroupAll(), lp_frameType, lp_visible);
}

int CMLib_HudFrameCSV(playergroup lp_players, string lp_frameSpec, bool lp_visible) {
    int lv_count;
    int lv_i;
    int lv_applied;
    string lv_tok;

    if ((lp_frameSpec == "")) {
        return 0;
    }
    lv_count = CMLib_SplitCount(lp_frameSpec, ",");
    lv_i = 0;
    lv_applied = 0;
    while ((lv_i < lv_count)) {
        lv_tok = CMLib_TrimSpaces(CMLib_SplitAt(lp_frameSpec, ",", lv_i));
        if ((lv_tok != "")) {
            CMLib_HudFrame(lp_players, CMLib_ParseInt(lv_tok, -1), lp_visible);
            lv_applied += 1;
        }
        lv_i += 1;
    }
    return lv_applied;
}

void CMLib_HudCinematic(playergroup lp_players, bool lp_cinematicOn) {
    bool lv_show;

    lv_show = (lp_cinematicOn == false);
    CMLib_HudFrame(lp_players, c_syncFrameTypeMenuBar, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeResourcePanel, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeSupply, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeMinimapPanel, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeCommandPanel, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeInfoPanel, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeConsolePanel, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeControlGroupPanel, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeIdleWorkerButton, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeArmyButton, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeObjectivePanel, lv_show);
    CMLib_HudFrame(lp_players, c_syncFrameTypeAlertPanel, lv_show);
}

void CMLib_HudWorldVisible(playergroup lp_players, bool lp_visible) {
    playergroup lv_pg;

    lv_pg = lp_players;
    if ((lv_pg == null)) {
        lv_pg = PlayerGroupAll();
    }
    UISetWorldVisible(lv_pg, lp_visible);
}
""")

# =============================================================================
# 2) Catalog —— 全表遍历（「分析所有单位/建筑」的元能力）
# =============================================================================
patch("cmlib_catalog_h.galaxy", "CMLib_CatEntryAt", """
// ---- 目录全表遍历 -------------------------------------------------------------
// 【索引坑】CatalogEntryGet 的 index 是 **1-based**（暴雪自动生成代码一律
// `i = 1; while (i <= CatalogEntryCount(...))`）。从 0 开始遍历会漏掉第一条并
// 在末尾越界拿到空串。CMLib_CatEntryAt 内部做范围守门，越界一律返回 ""。
int    CMLib_CatCount(int lp_catalog);
string CMLib_CatEntryAt(int lp_catalog, int lp_index);
string CMLib_CatEntryScope(int lp_catalog, string lp_entry);
// 字段是数组时的元素个数（对应 CatalogFieldValueCount）。
int    CMLib_CatFieldCount(int lp_catalog, string lp_entry, string lp_fieldPath, int lp_player);
// 直接取整数，省掉 CatalogFieldValueGet + StringToInt 的往返（对应 CatalogFieldValueGetAsInt）。
int    CMLib_CatGetIntFast(int lp_catalog, string lp_entry, string lp_fieldPath, int lp_player);
// 反查条目下标（1-based），找不到返回 0。
int    CMLib_CatFindIndex(int lp_catalog, string lp_entry);
// 遍历全表，返回第一个「指定字段 == 期望值」的条目 id，找不到返回 ""。
string CMLib_CatFirstWhere(int lp_catalog, string lp_fieldPath, string lp_wantValue, int lp_player);
// 遍历全表，统计「指定字段 == 期望值」的条目数量。
int    CMLib_CatCountWhere(int lp_catalog, string lp_fieldPath, string lp_wantValue, int lp_player);

// ---- 目录链接替换（运行时换单位/换模型的标准手法）-------------------------------
bool   CMLib_CatLinkSwap(int lp_player, int lp_catalog, string lp_idA, string lp_idB);
string CMLib_CatLinkOf(int lp_player, int lp_catalog, string lp_id);
""")

patch("cmlib_catalog.galaxy", "CMLib_CatEntryAt", """
// -----------------------------------------------------------------------------
// 目录全表遍历
// -----------------------------------------------------------------------------

int CMLib_CatCount(int lp_catalog) {
    return CatalogEntryCount(lp_catalog);
}

string CMLib_CatEntryAt(int lp_catalog, int lp_index) {
    // 1-based：合法区间是 [1, count]。0 与越界都返回空串而不是让调用方拿到脏数据。
    if ((lp_index < 1)) {
        return "";
    }
    if ((lp_index > CatalogEntryCount(lp_catalog))) {
        return "";
    }
    return CatalogEntryGet(lp_catalog, lp_index);
}

string CMLib_CatEntryScope(int lp_catalog, string lp_entry) {
    if ((lp_entry == "")) {
        return "";
    }
    if ((CatalogEntryIsValid(lp_catalog, lp_entry) == false)) {
        return "";
    }
    return CatalogEntryScope(lp_catalog, lp_entry);
}

int CMLib_CatFieldCount(int lp_catalog, string lp_entry, string lp_fieldPath, int lp_player) {
    if ((lp_entry == "")) {
        return 0;
    }
    if ((CatalogEntryIsValid(lp_catalog, lp_entry) == false)) {
        return 0;
    }
    return CatalogFieldValueCount(lp_catalog, lp_entry, lp_fieldPath, lp_player);
}

int CMLib_CatGetIntFast(int lp_catalog, string lp_entry, string lp_fieldPath, int lp_player) {
    if ((lp_entry == "")) {
        return 0;
    }
    if ((CatalogEntryIsValid(lp_catalog, lp_entry) == false)) {
        return 0;
    }
    return CatalogFieldValueGetAsInt(lp_catalog, lp_entry, lp_fieldPath, lp_player);
}

int CMLib_CatFindIndex(int lp_catalog, string lp_entry) {
    int lv_i;
    int lv_n;

    if ((lp_entry == "")) {
        return 0;
    }
    lv_n = CatalogEntryCount(lp_catalog);
    lv_i = 1;
    while ((lv_i <= lv_n)) {
        if ((CatalogEntryGet(lp_catalog, lv_i) == lp_entry)) {
            return lv_i;
        }
        lv_i += 1;
    }
    return 0;
}

string CMLib_CatFirstWhere(int lp_catalog, string lp_fieldPath, string lp_wantValue, int lp_player) {
    int lv_i;
    int lv_n;
    string lv_entry;

    lv_n = CatalogEntryCount(lp_catalog);
    lv_i = 1;
    while ((lv_i <= lv_n)) {
        lv_entry = CatalogEntryGet(lp_catalog, lv_i);
        if ((lv_entry != "")) {
            if ((CatalogFieldValueGet(lp_catalog, lv_entry, lp_fieldPath, lp_player) == lp_wantValue)) {
                return lv_entry;
            }
        }
        lv_i += 1;
    }
    return "";
}

int CMLib_CatCountWhere(int lp_catalog, string lp_fieldPath, string lp_wantValue, int lp_player) {
    int lv_i;
    int lv_n;
    int lv_hits;
    string lv_entry;

    lv_n = CatalogEntryCount(lp_catalog);
    lv_i = 1;
    lv_hits = 0;
    while ((lv_i <= lv_n)) {
        lv_entry = CatalogEntryGet(lp_catalog, lv_i);
        if ((lv_entry != "")) {
            if ((CatalogFieldValueGet(lp_catalog, lv_entry, lp_fieldPath, lp_player) == lp_wantValue)) {
                lv_hits += 1;
            }
        }
        lv_i += 1;
    }
    return lv_hits;
}

// -----------------------------------------------------------------------------
// 目录链接替换
// -----------------------------------------------------------------------------

bool CMLib_CatLinkSwap(int lp_player, int lp_catalog, string lp_idA, string lp_idB) {
    if ((lp_idA == "")) {
        return false;
    }
    if ((lp_idB == "")) {
        return false;
    }
    if ((CatalogEntryIsValid(lp_catalog, lp_idA) == false)) {
        CMLib_LogWarn("CMLib.Catalog", "LinkSwap skipped, unknown source id " + lp_idA);
        return false;
    }
    CatalogLinkReplace(lp_player, lp_catalog, lp_idA, lp_idB);
    return true;
}

string CMLib_CatLinkOf(int lp_player, int lp_catalog, string lp_id) {
    if ((lp_id == "")) {
        return "";
    }
    return CatalogLinkReplacement(lp_player, lp_catalog, lp_id);
}
""")

# =============================================================================
# 3) Unit / UnitGroup —— 过滤器匹配、暂停、归属、编组下令、同盟取组
# =============================================================================
patch("cmlib_unit_h.galaxy", "CMLib_UGAlliance", """
// ---- 过滤器 / 全局暂停 / 归属 --------------------------------------------------
// UnitFilterMatch 对 null 单位会抛脚本错误，这里前置守门后返回 false。
bool CMLib_UnitMatchFilter(unit lp_unit, int lp_player, unitfilter lp_filter);
// 全局暂停（过场必备）。原生就是全局开关，包一层只为语义清晰 + 统一入口。
void CMLib_UnitsPauseAll(bool lp_pause);
// 单位类型的本地化名（对应 UnitTypeGetName），空类型返回空文本而非报错。
text CMLib_UnitTypeName(string lp_unitType);
// 转移归属；单位无效或玩家槽非法时不动作，返回是否真的改了。
bool CMLib_UnitChangeOwner(unit lp_unit, int lp_player, bool lp_changeColor);

// ---- 编组下令 ------------------------------------------------------------------
// 整组一次性下令（对应 UnitGroupIssueOrder），比逐个 UnitIssueOrder 高效。
bool CMLib_UGIssueOrder(unitgroup lp_group, order lp_order, int lp_queueType);
// 无目标技能（如 Stop / HoldPosition / 变形），返回是否成功下发。
bool CMLib_UGOrderAbility(unitgroup lp_group, string lp_ability, int lp_cmdIndex, int lp_queueType);
// 以单位为目标的技能（如 Attack 某单位）。
bool CMLib_UGOrderAbilityAtUnit(unitgroup lp_group, string lp_ability, int lp_cmdIndex, unit lp_target, int lp_queueType);

// ---- 按同盟关系取编组（UnitGroupAlliance）---------------------------------------
// region 传 null 自动用全地图；maxCount <= 0 自动用 c_unitCountAll（不限量）。
unitgroup CMLib_UGAlliance(int lp_player, int lp_alliance, region lp_region, unitfilter lp_filter, int lp_maxCount);
unitgroup CMLib_UGEnemiesOf(int lp_player, int lp_maxCount);
unitgroup CMLib_UGAlliesOf(int lp_player, int lp_maxCount);
""")

patch("cmlib_unit.galaxy", "CMLib_UGAlliance", """
// -----------------------------------------------------------------------------
// 过滤器 / 全局暂停 / 归属
// -----------------------------------------------------------------------------

bool CMLib_UnitMatchFilter(unit lp_unit, int lp_player, unitfilter lp_filter) {
    if ((lp_unit == null)) {
        return false;
    }
    return UnitFilterMatch(lp_unit, lp_player, lp_filter);
}

void CMLib_UnitsPauseAll(bool lp_pause) {
    UnitPauseAll(lp_pause);
}

text CMLib_UnitTypeName(string lp_unitType) {
    if ((lp_unitType == "")) {
        return StringExternal("");
    }
    return UnitTypeGetName(lp_unitType);
}

bool CMLib_UnitChangeOwner(unit lp_unit, int lp_player, bool lp_changeColor) {
    if ((CMLib_UnitOk(lp_unit) == false)) {
        return false;
    }
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return false;
    }
    UnitSetOwner(lp_unit, lp_player, lp_changeColor);
    return true;
}

// -----------------------------------------------------------------------------
// 编组下令
// -----------------------------------------------------------------------------

bool CMLib_UGIssueOrder(unitgroup lp_group, order lp_order, int lp_queueType) {
    if ((lp_group == null)) {
        return false;
    }
    if ((lp_order == null)) {
        return false;
    }
    if ((UnitGroupCount(lp_group, c_unitCountAll) < 1)) {
        return false;
    }
    return UnitGroupIssueOrder(lp_group, lp_order, lp_queueType);
}

bool CMLib_UGOrderAbility(unitgroup lp_group, string lp_ability, int lp_cmdIndex, int lp_queueType) {
    if ((lp_ability == "")) {
        return false;
    }
    return CMLib_UGIssueOrder(lp_group, Order(AbilityCommand(lp_ability, lp_cmdIndex)), lp_queueType);
}

bool CMLib_UGOrderAbilityAtUnit(unitgroup lp_group, string lp_ability, int lp_cmdIndex, unit lp_target, int lp_queueType) {
    if ((lp_ability == "")) {
        return false;
    }
    if ((lp_target == null)) {
        return false;
    }
    return CMLib_UGIssueOrder(lp_group, OrderTargetingUnit(AbilityCommand(lp_ability, lp_cmdIndex), lp_target), lp_queueType);
}

// -----------------------------------------------------------------------------
// 按同盟关系取编组
// -----------------------------------------------------------------------------

unitgroup CMLib_UGAlliance(int lp_player, int lp_alliance, region lp_region, unitfilter lp_filter, int lp_maxCount) {
    region lv_region;
    int lv_max;

    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return UnitGroupEmpty();
    }
    lv_region = lp_region;
    if ((lv_region == null)) {
        lv_region = RegionEntireMap();
    }
    lv_max = lp_maxCount;
    if ((lv_max <= 0)) {
        lv_max = c_unitCountAll;
    }
    return UnitGroupAlliance(lp_player, lp_alliance, lv_region, lp_filter, lv_max);
}

unitgroup CMLib_UGEnemiesOf(int lp_player, int lp_maxCount) {
    return CMLib_UGAlliance(lp_player, c_unitAllianceEnemy, null, CMLib_FilterAlive(), lp_maxCount);
}

unitgroup CMLib_UGAlliesOf(int lp_player, int lp_maxCount) {
    return CMLib_UGAlliance(lp_player, c_unitAllianceAlly, null, CMLib_FilterAlive(), lp_maxCount);
}
""")

# =============================================================================
# 4) Player —— 出生点 / 难度 / 种族 / 组拷贝
# =============================================================================
patch("cmlib_player_h.galaxy", "CMLib_PlayerStart", """
// ---- 玩家静态属性 --------------------------------------------------------------
// 出生点：非法槽位返回 (0,0) 而不是 null，调用方无需再判空（原生对非法槽会抛错）。
point  CMLib_PlayerStart(int lp_player);
// 难度等级（对应 PlayerDifficulty），非法槽返回 0。
int    CMLib_PlayerDiff(int lp_player);
// 种族字符串（"Terr"/"Zerg"/"Prot"），非法槽返回 ""。
string CMLib_PlayerRaceOf(int lp_player);
// 玩家组安全拷贝：null 输入返回空组而不是 null，避免下游连锁判空。
playergroup CMLib_PGCopyOf(playergroup lp_group);
// 按同盟类型取玩家组（c_playerGroupAlly / c_playerGroupEnemy）。
playergroup CMLib_PGAllianceOf(int lp_type, int lp_player);
""")

patch("cmlib_player.galaxy", "CMLib_PlayerStart", """
// -----------------------------------------------------------------------------
// 玩家静态属性
// -----------------------------------------------------------------------------

point CMLib_PlayerStart(int lp_player) {
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return Point(0.0, 0.0);
    }
    return PlayerStartLocation(lp_player);
}

int CMLib_PlayerDiff(int lp_player) {
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return 0;
    }
    return PlayerDifficulty(lp_player);
}

string CMLib_PlayerRaceOf(int lp_player) {
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return "";
    }
    return PlayerRace(lp_player);
}

playergroup CMLib_PGCopyOf(playergroup lp_group) {
    if ((lp_group == null)) {
        return PlayerGroupEmpty();
    }
    return PlayerGroupCopy(lp_group);
}

playergroup CMLib_PGAllianceOf(int lp_type, int lp_player) {
    if ((CMLib_IsValidPlayerSlot(lp_player) == false)) {
        return PlayerGroupEmpty();
    }
    return PlayerGroupAlliance(lp_type, lp_player);
}
""")

# =============================================================================
# 5) Core —— 随机数与取模的安全封装
# =============================================================================
patch("cmlib_core_h.galaxy", "CMLib_RandF", """
// ---- 随机数 / 取模安全封装 -----------------------------------------------------
// 【真坑】RandomInt/RandomFixed 在 min > max 时行为未定义；ModI 在 m == 0 时
// 触发除零运行时错误并中断当前触发器。以下封装自动交换边界 / 兜底返回。
fixed CMLib_RandF(fixed lp_min, fixed lp_max);
int   CMLib_RandI(int lp_min, int lp_max);
int   CMLib_ModSafe(int lp_x, int lp_m);
""")

patch("cmlib_core.galaxy", "CMLib_RandF", """
// -----------------------------------------------------------------------------
// 随机数 / 取模安全封装
// -----------------------------------------------------------------------------

fixed CMLib_RandF(fixed lp_min, fixed lp_max) {
    if ((lp_min > lp_max)) {
        return RandomFixed(lp_max, lp_min);
    }
    return RandomFixed(lp_min, lp_max);
}

int CMLib_RandI(int lp_min, int lp_max) {
    if ((lp_min > lp_max)) {
        return RandomInt(lp_max, lp_min);
    }
    return RandomInt(lp_min, lp_max);
}

int CMLib_ModSafe(int lp_x, int lp_m) {
    // m == 0 会让引擎抛除零错误并中止整个触发器，这里兜底为 0。
    if ((lp_m == 0)) {
        return 0;
    }
    return ModI(lp_x, lp_m);
}
""")


def main():
    applied = 0
    skipped = 0
    for fname, marker, content in PATCHES:
        path = os.path.join(BASE, fname)
        if not os.path.isfile(path):
            print("MISSING " + fname)
            return 1
        with io.open(path, encoding="utf-8") as fh:
            txt = fh.read()
        if marker in txt:
            print("SKIP    " + fname + "  (已含 " + marker + ")")
            skipped += 1
            continue
        if not txt.endswith("\n"):
            txt += "\n"
        txt += content
        with io.open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(txt)
        print("PATCHED " + fname + "  (+" + str(len(content.splitlines())) + " 行)")
        applied += 1
    print("---- 应用 " + str(applied) + " 处, 跳过 " + str(skipped) + " 处 ----")
    return 0


if __name__ == "__main__":
    sys.exit(main())
