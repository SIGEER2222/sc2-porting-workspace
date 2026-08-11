"""CMLib :: Round22 —— 单位 / 建筑 / 面板三主线剩余真实缺口补齐。

来源：`gap_scan_round22.json`。过滤掉三类**假缺口**后剩下的真实项：
  1) GUI 生成噪声：`*FromId` / `*FromName` / `*LastCreated`（编辑器产物，库不该封）；
  2) 等价已覆盖：`MinI/MaxI/AbsF` 等已有 `CMLib_MinInt/MaxInt/AbsInt` 手写实现；
  3) **范围外符号**：`AIFilter` 族在 `Tactical/TacticalAI.galaxy`、
     `StatEvent*` 族在 `natives_missing.galaxy`（无人 include）——
     包进去有真机静默编译失败风险，本轮不包，另立探针（见 probe_statevent.py）。

本轮 35 个封装全部取自 `core.sc2mod/base.sc2data/TriggerLibs/natives.galaxy`
（默认 include 范围内，安全），签名逐条比对原文：

    void  UnitControlGroupAddUnit(int inPlayer, int inGroup, unit inUnit);
    int   UnitCargoValue(unit inUnit, int inValue);
    void  UnitStatusBarOverride(unit inUnit, int inGroup);
    void  UnitSetScale(unit inUnit, fixed x, fixed y, fixed z);
    int   UnitXPGetCurrentLevel(unit inUnit, string inVeterancyBehavior);
    void  UISetAlertTypeVisible(playergroup inPlayers, string inAlert, bool inVisible);
    void  UIShowTextCrawl(playergroup, text, text, fixed, soundlink, soundlink);
    void  UIHideTextCrawl(playergroup inPlayers);
    void  UISetGameMenuItemVisible(playergroup inPlayers, int inMenuItemType, bool inVisible);
    void  DialogControlSetObservedType(int control, int observedType);
    int   DialogControlGetRelativeControl(int control, int player);
    void  BoardRowSetGroup(int inBoard, int inRow, int inGroup);
    void  BoardSetGroupCount(int inBoard, int inGroups);
    void  BoardSetPosition(int inBoard, int inX, int inY);
    void  BoardTitleSetAlignment(int inBoard, int inAlign, int inIconPos);
    void  BoardSetName(int inBoard, text inName, color inColor);
    void  BoardMinimizeSetColor(int inBoard, color inColor);
    void  TimerWindowSetColor(int inWindow, int inType, color inColor, fixed transparency);
    void  TimerWindowSetFormat(int inWindow, text inFormat);
    void  TimerWindowSetImageType(int inWindow, int inImage, int inType);
    void  TimerWindowSetTitle(int inWindow, text inTitle);
    actor ActorFrom(string name);
    actor ActorCreate(actorscope as, string actorName, string c1, string c2, string c3);
    actor ActorRegionCreate(actorscope as, string actorName, region r);
    void  ActorRegionSend(actor a, int intersect, string msg, string filters, string terms);
    void  ActorSendTo(actor a, string refName, string msg);
    actorscope ActorScopeFromUnit(unit u);
    bool  CatalogReferenceModify(string reference, int player, string value, int operation);
    bool  CatalogEntryIsDefault(int catalog, string entry);
    int   ObjectiveCreateForPlayers(text, text, int, bool, playergroup);
    playergroup ObjectiveGetPlayerGroup(int inObjective);
    fixed MinF/MaxF(fixed,fixed); fixed AbsF(fixed); fixed ModF(fixed,fixed);

**守门约定**（沿用全库）：null / 空串 / 无效句柄一律早退，绝不把 null 漏给引擎；
`color` 是值类型，**不能与 null 比较、不能返回 null**（round18 血泪）。
"""
import sys
from pathlib import Path

CM = Path(__file__).resolve().parent / "scripts" / "cmlib"
MARK = "CMLib :: Round22"

BLOCKS = {}

# ---------------------------------------------------------------- unit -------
BLOCKS["cmlib_unit_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 单位主线：编队 / 载具容量 / 状态条 / 缩放 / 老兵等级
// -----------------------------------------------------------------------------
// 把单位塞进某玩家的控制编队（1~10）。编队号越界直接忽略，不让引擎吃脏值。
void  CMLib_UnitCtrlGroupAdd(unit lp_unit, int lp_player, int lp_group);
// c_unitCargoUnitCount / SpaceTotal / SpaceUsed / SpaceFree / SizeAsCargo /
// SizeMax / Position —— 无效单位或越界类型返回 0。
int   CMLib_UnitCargoValue(unit lp_unit, int lp_valueType);
// 状态条分组覆盖（多单位共享一条血条时用）。
void  CMLib_UnitStatusBar(unit lp_unit, int lp_group);
// 三轴缩放。注意这是**表现层**缩放，不改碰撞体积与数据层数值。
void  CMLib_UnitSetScale(unit lp_unit, fixed lp_x, fixed lp_y, fixed lp_z);
// 等比缩放便捷式：scale <= 0 视为非法直接忽略（0 会让模型塌成一个点）。
void  CMLib_UnitSetScaleUniform(unit lp_unit, fixed lp_scale);
// 老兵行为当前等级；单位无效 / 行为名为空返回 0。
int   CMLib_UnitVeterancyLevel(unit lp_unit, string lp_veterancyBehavior);
"""

BLOCKS["cmlib_unit.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 单位主线补齐
// -----------------------------------------------------------------------------

void CMLib_UnitCtrlGroupAdd(unit lp_unit, int lp_player, int lp_group) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    // 控制编队号是 1~10；越界值引擎行为无文档承诺，直接拒绝。
    if (lp_group < 1) { return; }
    if (lp_group > 10) { return; }
    UnitControlGroupAddUnit(lp_player, lp_group, lp_unit);
}

int CMLib_UnitCargoValue(unit lp_unit, int lp_valueType) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0; }
    if (lp_valueType < c_unitCargoUnitCount) { return 0; }
    if (lp_valueType > c_unitCargoPosition) { return 0; }
    return UnitCargoValue(lp_unit, lp_valueType);
}

void CMLib_UnitStatusBar(unit lp_unit, int lp_group) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    UnitStatusBarOverride(lp_unit, lp_group);
}

void CMLib_UnitSetScale(unit lp_unit, fixed lp_x, fixed lp_y, fixed lp_z) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    UnitSetScale(lp_unit, lp_x, lp_y, lp_z);
}

void CMLib_UnitSetScaleUniform(unit lp_unit, fixed lp_scale) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    // 0 或负缩放会让模型塌陷/翻面，属调用方笔误，拦掉而不是传给引擎。
    if (lp_scale <= 0.0) { return; }
    UnitSetScale(lp_unit, lp_scale, lp_scale, lp_scale);
}

int CMLib_UnitVeterancyLevel(unit lp_unit, string lp_veterancyBehavior) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0; }
    if (lp_veterancyBehavior == "") { return 0; }
    return UnitXPGetCurrentLevel(lp_unit, lp_veterancyBehavior);
}
"""

# ------------------------------------------------------------------ ui -------
BLOCKS["cmlib_ui_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 面板主线：警报开关 / 文字滚屏 / 游戏菜单项 / 控件观察
// -----------------------------------------------------------------------------
// 单类警报的显示开关（如屏蔽"你的部队受到攻击"）。
void CMLib_UIAlertTypeVisible(playergroup lp_players, string lp_alert, bool lp_visible);
// 片头式文字滚屏。soundlink 允许传 null（无音效）。
void CMLib_UITextCrawlShow(playergroup lp_players, text lp_title, text lp_text,
                           fixed lp_maxTime, soundlink lp_birth, soundlink lp_type);
void CMLib_UITextCrawlHide(playergroup lp_players);
// c_gameMenuDialog* 菜单项显隐（如屏蔽"放弃"按钮）。
void CMLib_UIGameMenuItemVisible(playergroup lp_players, int lp_menuItemType, bool lp_visible);
// 让控件观察某类对象（c_observedType* 由数据层定义，传裸 int）。
void CMLib_DCObservedType(int lp_control, int lp_observedType);
// 取控件在某玩家视角下的相对控件；控件无效返回 c_invalidDialogControlId。
int  CMLib_DCRelative(int lp_control, int lp_player);
"""

BLOCKS["cmlib_ui.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 面板主线补齐
// -----------------------------------------------------------------------------

void CMLib_UIAlertTypeVisible(playergroup lp_players, string lp_alert, bool lp_visible) {
    if (lp_players == null) { return; }
    if (lp_alert == "") { return; }
    UISetAlertTypeVisible(lp_players, lp_alert, lp_visible);
}

void CMLib_UITextCrawlShow(playergroup lp_players, text lp_title, text lp_text,
                           fixed lp_maxTime, soundlink lp_birth, soundlink lp_type) {
    if (lp_players == null) { return; }
    // 负时长会让滚屏永不结束（引擎按无限处理），夹到 0。
    if (lp_maxTime < 0.0) { lp_maxTime = 0.0; }
    UIShowTextCrawl(lp_players, lp_title, lp_text, lp_maxTime, lp_birth, lp_type);
}

void CMLib_UITextCrawlHide(playergroup lp_players) {
    if (lp_players == null) { return; }
    UIHideTextCrawl(lp_players);
}

void CMLib_UIGameMenuItemVisible(playergroup lp_players, int lp_menuItemType, bool lp_visible) {
    if (lp_players == null) { return; }
    UISetGameMenuItemVisible(lp_players, lp_menuItemType, lp_visible);
}

void CMLib_DCObservedType(int lp_control, int lp_observedType) {
    if (lp_control == c_invalidDialogControlId) { return; }
    DialogControlSetObservedType(lp_control, lp_observedType);
}

int CMLib_DCRelative(int lp_control, int lp_player) {
    if (lp_control == c_invalidDialogControlId) { return c_invalidDialogControlId; }
    return DialogControlGetRelativeControl(lp_control, lp_player);
}
"""

# --------------------------------------------------------------- board -------
BLOCKS["cmlib_board_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 计分板：行分组 / 分组数 / 位置 / 标题对齐 / 名称 / 最小化色
// -----------------------------------------------------------------------------
void CMLib_BoardRowGroup(int lp_board, int lp_row, int lp_group);
void CMLib_BoardGroupCount(int lp_board, int lp_groups);
void CMLib_BoardPosition(int lp_board, int lp_x, int lp_y);
void CMLib_BoardTitleAlign(int lp_board, int lp_align, int lp_iconPos);
// 注意：color 是**值类型**，不能传 null、也不能与 null 比较（round18 教训）。
void CMLib_BoardName(int lp_board, text lp_name, color lp_color);
void CMLib_BoardMinimizeColor(int lp_board, color lp_color);
"""

BLOCKS["cmlib_board.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 计分板补齐
// -----------------------------------------------------------------------------

void CMLib_BoardRowGroup(int lp_board, int lp_row, int lp_group) {
    if (!CMLib_BoardValid(lp_board)) { return; }
    if (lp_row < 1) { return; }
    BoardRowSetGroup(lp_board, lp_row, lp_group);
}

void CMLib_BoardGroupCount(int lp_board, int lp_groups) {
    if (!CMLib_BoardValid(lp_board)) { return; }
    if (lp_groups < 0) { return; }
    BoardSetGroupCount(lp_board, lp_groups);
}

void CMLib_BoardPosition(int lp_board, int lp_x, int lp_y) {
    if (!CMLib_BoardValid(lp_board)) { return; }
    BoardSetPosition(lp_board, lp_x, lp_y);
}

void CMLib_BoardTitleAlign(int lp_board, int lp_align, int lp_iconPos) {
    if (!CMLib_BoardValid(lp_board)) { return; }
    BoardTitleSetAlignment(lp_board, lp_align, lp_iconPos);
}

void CMLib_BoardName(int lp_board, text lp_name, color lp_color) {
    if (!CMLib_BoardValid(lp_board)) { return; }
    BoardSetName(lp_board, lp_name, lp_color);
}

void CMLib_BoardMinimizeColor(int lp_board, color lp_color) {
    if (!CMLib_BoardValid(lp_board)) { return; }
    BoardMinimizeSetColor(lp_board, lp_color);
}
"""

# --------------------------------------------------------------- panel -------
BLOCKS["cmlib_panel_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 计时器窗口外观 + 任务目标（按玩家组）
// -----------------------------------------------------------------------------
void CMLib_TWColor(int lp_window, int lp_type, color lp_color, fixed lp_transparency);
void CMLib_TWFormat(int lp_window, text lp_format);
void CMLib_TWImageType(int lp_window, int lp_image, int lp_type);
void CMLib_TWTitle(int lp_window, text lp_title);
// 只对指定玩家组可见的任务目标；state 取 c_objectiveState*，越界夹到 Active。
int  CMLib_ObjCreateForPlayers(text lp_name, text lp_desc, int lp_state,
                               bool lp_primary, playergroup lp_players);
// 目标的可见玩家组；目标无效返回空组（绝不返回 null）。
playergroup CMLib_ObjPlayers(int lp_objective);
"""

BLOCKS["cmlib_panel.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 计时器窗口外观 + 任务目标补齐
// -----------------------------------------------------------------------------

void CMLib_TWColor(int lp_window, int lp_type, color lp_color, fixed lp_transparency) {
    if (lp_window == 0) { return; }
    // 透明度语义是 0=不透明、100=全透明，越界夹紧而不是传脏值。
    if (lp_transparency < 0.0) { lp_transparency = 0.0; }
    if (lp_transparency > 100.0) { lp_transparency = 100.0; }
    TimerWindowSetColor(lp_window, lp_type, lp_color, lp_transparency);
}

void CMLib_TWFormat(int lp_window, text lp_format) {
    if (lp_window == 0) { return; }
    TimerWindowSetFormat(lp_window, lp_format);
}

void CMLib_TWImageType(int lp_window, int lp_image, int lp_type) {
    if (lp_window == 0) { return; }
    TimerWindowSetImageType(lp_window, lp_image, lp_type);
}

void CMLib_TWTitle(int lp_window, text lp_title) {
    if (lp_window == 0) { return; }
    TimerWindowSetTitle(lp_window, lp_title);
}

int CMLib_ObjCreateForPlayers(text lp_name, text lp_desc, int lp_state,
                              bool lp_primary, playergroup lp_players) {
    if (lp_players == null) { return c_invalidObjectiveId; }
    if (lp_state < c_objectiveStateHidden) { lp_state = c_objectiveStateActive; }
    if (lp_state > c_objectiveStateFailed) { lp_state = c_objectiveStateActive; }
    return ObjectiveCreateForPlayers(lp_name, lp_desc, lp_state, lp_primary, lp_players);
}

playergroup CMLib_ObjPlayers(int lp_objective) {
    playergroup lv_pg;

    if (lp_objective == c_invalidObjectiveId) { return PlayerGroupEmpty(); }
    lv_pg = ObjectiveGetPlayerGroup(lp_objective);
    // 引擎在目标已销毁时可能返回 null；调用方随后 PlayerGroupCount(null) 会抛错。
    if (lv_pg == null) { return PlayerGroupEmpty(); }
    return lv_pg;
}
"""

# ------------------------------------------------------------------ fx -------
BLOCKS["cmlib_fx_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— Actor 层（单位视觉效果的直接操纵面）
// -----------------------------------------------------------------------------
// 按名字取全局 actor；名字为空返回 null。
actor CMLib_ActorFrom(string lp_name);
// 从单位取 actorscope —— 单位视觉操作的入口。单位无效返回 null。
actorscope CMLib_ActorScopeOfUnit(unit lp_unit);
// 在指定 scope 内创建 actor。scope/名字任一无效返回 null。
actor CMLib_ActorCreate(actorscope lp_scope, string lp_actorName,
                        string lp_c1, string lp_c2, string lp_c3);
// 区域 actor（区域进出触发视觉/音效的载体）。
actor CMLib_ActorRegionCreate(actorscope lp_scope, string lp_actorName, region lp_region);
void  CMLib_ActorRegionSend(actor lp_actor, int lp_intersect, string lp_msg,
                            string lp_filters, string lp_terms);
// 给 actor 的引用目标发消息（如 "::Main" + "SetTintColor ..."）。
void  CMLib_ActorSendTo(actor lp_actor, string lp_refName, string lp_msg);
"""

BLOCKS["cmlib_fx.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— Actor 层补齐
// -----------------------------------------------------------------------------

actor CMLib_ActorFrom(string lp_name) {
    if (lp_name == "") { return null; }
    return ActorFrom(lp_name);
}

actorscope CMLib_ActorScopeOfUnit(unit lp_unit) {
    if (CMLib_UnitOk(lp_unit) == false) { return null; }
    return ActorScopeFromUnit(lp_unit);
}

actor CMLib_ActorCreate(actorscope lp_scope, string lp_actorName,
                        string lp_c1, string lp_c2, string lp_c3) {
    if (lp_scope == null) { return null; }
    if (lp_actorName == "") { return null; }
    return ActorCreate(lp_scope, lp_actorName, lp_c1, lp_c2, lp_c3);
}

actor CMLib_ActorRegionCreate(actorscope lp_scope, string lp_actorName, region lp_region) {
    if (lp_scope == null) { return null; }
    if (lp_actorName == "") { return null; }
    if (lp_region == null) { return null; }
    return ActorRegionCreate(lp_scope, lp_actorName, lp_region);
}

void CMLib_ActorRegionSend(actor lp_actor, int lp_intersect, string lp_msg,
                           string lp_filters, string lp_terms) {
    if (lp_actor == null) { return; }
    if (lp_msg == "") { return; }
    ActorRegionSend(lp_actor, lp_intersect, lp_msg, lp_filters, lp_terms);
}

void CMLib_ActorSendTo(actor lp_actor, string lp_refName, string lp_msg) {
    if (lp_actor == null) { return; }
    if (lp_msg == "") { return; }
    ActorSendTo(lp_actor, lp_refName, lp_msg);
}
"""

# ------------------------------------------------------------- catalog -------
BLOCKS["cmlib_catalog_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— Catalog 引用改写 / 默认值判定
// -----------------------------------------------------------------------------
// 按 "Catalog,Entry,Field" 三段引用串改写；operation 取 c_upgradeOperation*。
bool CMLib_CatRefModify(string lp_reference, int lp_player, string lp_value, int lp_operation);
// 该条目是否为数据层默认（未被任何 upgrade/override 改过）。
bool CMLib_CatEntryIsDefault(int lp_catalog, string lp_entry);
"""

BLOCKS["cmlib_catalog.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— Catalog 引用改写 / 默认值判定
// -----------------------------------------------------------------------------

bool CMLib_CatRefModify(string lp_reference, int lp_player, string lp_value, int lp_operation) {
    if (lp_reference == "") { return false; }
    return CatalogReferenceModify(lp_reference, lp_player, lp_value, lp_operation);
}

bool CMLib_CatEntryIsDefault(int lp_catalog, string lp_entry) {
    if (lp_entry == "") { return false; }
    return CatalogEntryIsDefault(lp_catalog, lp_entry);
}
"""

# ---------------------------------------------------------------- core -------
BLOCKS["cmlib_core_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 定点数(fixed) 数学补齐
// 说明：整型侧 CMLib_MinInt/MaxInt/AbsInt 早已存在；fixed 侧一直是空白，
//       而 Galaxy 里绝大多数坐标/时间/伤害运算都是 fixed。
// -----------------------------------------------------------------------------
fixed CMLib_MinFixed(fixed lp_a, fixed lp_b);
fixed CMLib_MaxFixed(fixed lp_a, fixed lp_b);
fixed CMLib_AbsFixed(fixed lp_value);
// 取模：m == 0 时返回 0（引擎除零会抛运行时错误、中断整条触发器线程）。
fixed CMLib_ModFixed(fixed lp_x, fixed lp_m);
"""

BLOCKS["cmlib_core.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round22 —— 定点数(fixed) 数学补齐
// -----------------------------------------------------------------------------

fixed CMLib_MinFixed(fixed lp_a, fixed lp_b) {
    return MinF(lp_a, lp_b);
}

fixed CMLib_MaxFixed(fixed lp_a, fixed lp_b) {
    return MaxF(lp_a, lp_b);
}

fixed CMLib_AbsFixed(fixed lp_value) {
    return AbsF(lp_value);
}

fixed CMLib_ModFixed(fixed lp_x, fixed lp_m) {
    // 除零在 Galaxy 是运行时错误，会中断当前触发器线程 —— 守门比"信任调用方"划算。
    if (lp_m == 0.0) { return 0.0; }
    return ModF(lp_x, lp_m);
}
"""


def main() -> int:
    if not CM.is_dir():
        print(f"[round22] 找不到库目录: {CM}")
        return 1
    changed = skipped = 0
    for fname, block in BLOCKS.items():
        path = CM / fname
        if not path.is_file():
            print(f"[round22] !! 缺文件 {fname}")
            return 1
        cur = path.read_text(encoding="utf-8")
        if MARK in cur:
            print(f"[round22] skip (已应用) {fname}")
            skipped += 1
            continue
        path.write_text(cur.rstrip("\n") + "\n" + block, encoding="utf-8")
        print(f"[round22] patched {fname}  (+{len(block.splitlines())} 行)")
        changed += 1
    print(f"[round22] 完成：{changed} 个文件更新，{skipped} 个已是最新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
