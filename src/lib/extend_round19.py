# -*- coding: utf-8 -*-
"""Round19 扩展：补齐 classify_gaps_round19.py 认定的 61 个真实缺口（共 65 个封装）。

本轮最重要的一条：**推翻前几轮「conversation 域 9.9% 是 GUI 噪声」的判断**。
分类器证明 ConversationData* 全族实打实声明在 core.sc2mod/TriggerLibs/natives.galaxy，
不是 *FromId 那种编辑器自动访问器 —— 它是数据驱动战役对白的正经 API，
是全库覆盖率最低的**真**空白域。

所有形参类型/顺序均来自 sigs_round19.py 从 natives.galaxy 抽取的权威签名，
未凭记忆书写（arity 错 = 真机静默丢整个 MapScript，静态 lint 抓不到）。

幂等：每块用 MARK 标记，已存在则跳过。
"""
import io
import re
import sys
from pathlib import Path

CM = Path(__file__).resolve().parent / "scripts" / "cmlib"
MARK = "CMLib :: Round19"

# ---------------------------------------------------------------------------
# 每项： (文件名, 追加内容)
# ---------------------------------------------------------------------------
BLOCKS = {}

# ============================ conv ==========================================
BLOCKS["cmlib_conv_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— ConversationData 数据驱动对白
//
// 与本模块上半部分的 Conversation*（运行时手搓对话框）不同，ConversationData*
// 走的是**编辑器 Conversation 数据表**：对白行、说话人、镜头、状态变量都在数据层
// 配好，脚本只负责「跑哪一段、给谁看、能不能跳过」。战役类地图几乎全用这一套。
//
// 覆盖率证据：gap_scan 显示 conversation 域仅 9.9%，是全库最低。前几轮误判为
// 「GUI 自动访问器噪声」，classify_gaps_round19.py 证伪 —— 这些全是 natives.galaxy
// 里的正经 native。
//
// 跳过档位直接用引擎常量（均在 natives.galaxy，安全）：
//   c_conversationSkipNone(0) / c_conversationSkipSimple(1) / c_conversationSkipFull(2)
// =============================================================================

// 播放一段对白。convId 为空直接返回，避免引擎在空 id 上报错。
void CMLib_ConvDataRun(string lp_convId, playergroup lp_players, int lp_skipType, bool lp_wait);
// 便捷式：全体玩家 / 允许完整跳过 / 不阻塞当前触发器。
void CMLib_ConvDataRunAll(string lp_convId);
void CMLib_ConvDataStop();
// 当前状态下这段对白还有没有可播的行（避免播出一段空对白）。
bool CMLib_ConvDataCanRun(string lp_convId, bool lp_unpickedOnly);
// 取某行绑定的音效 id；无音效或 id 空时返回 ""。
string CMLib_ConvDataSound(string lp_convLine, bool lp_checkConditions);
// 指定某一行只对特定玩家播放 / 恢复默认。
void CMLib_ConvDataLinePlayers(string lp_convId, string lp_lineId, playergroup lp_players);
void CMLib_ConvDataLineReset(string lp_convId, string lp_lineId);
// 把数据层的镜头索引绑到一个 camerainfo + 回调触发器上。
void CMLib_ConvDataCamera(string lp_camIndex, string lp_charIndex, camerainfo lp_cam,
                          trigger lp_t, bool lp_wait);
// 对白状态变量（数据层的分支条件）。
void CMLib_ConvDataStateSet(string lp_stateIndex, int lp_value);
int  CMLib_ConvDataStateGet(string lp_stateIndex);
text CMLib_ConvDataStateTextOf(string lp_stateIndex, string lp_infoName);
"""

BLOCKS["cmlib_conv.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— ConversationData 实现
// =============================================================================
void CMLib_ConvDataRun(string lp_convId, playergroup lp_players, int lp_skipType, bool lp_wait) {
    if (lp_convId == "") { return; }
    if (lp_players == null) { return; }
    ConversationDataRun(lp_convId, lp_players,
                        CMLib_ClampInt(lp_skipType, c_conversationSkipNone,
                                       c_conversationSkipFull),
                        lp_wait);
}

void CMLib_ConvDataRunAll(string lp_convId) {
    CMLib_ConvDataRun(lp_convId, PlayerGroupAll(), c_conversationSkipFull, false);
}

void CMLib_ConvDataStop() {
    ConversationDataStop();
}

bool CMLib_ConvDataCanRun(string lp_convId, bool lp_unpickedOnly) {
    if (lp_convId == "") { return false; }
    return ConversationDataCanRun(lp_convId, lp_unpickedOnly);
}

string CMLib_ConvDataSound(string lp_convLine, bool lp_checkConditions) {
    string lv_s;
    if (lp_convLine == "") { return ""; }
    lv_s = ConversationDataGetSound(lp_convLine, lp_checkConditions);
    if (lv_s == null) { return ""; }
    return lv_s;
}

void CMLib_ConvDataLinePlayers(string lp_convId, string lp_lineId, playergroup lp_players) {
    if ((lp_convId == "") || (lp_lineId == "") || (lp_players == null)) { return; }
    ConversationDataLineSetPlayers(lp_convId, lp_lineId, lp_players);
}

void CMLib_ConvDataLineReset(string lp_convId, string lp_lineId) {
    if ((lp_convId == "") || (lp_lineId == "")) { return; }
    ConversationDataLineResetPlayers(lp_convId, lp_lineId);
}

void CMLib_ConvDataCamera(string lp_camIndex, string lp_charIndex, camerainfo lp_cam,
                          trigger lp_t, bool lp_wait) {
    if ((lp_camIndex == "") || (lp_charIndex == "")) { return; }
    ConversationDataRegisterCamera(lp_camIndex, lp_charIndex, lp_cam, lp_t, lp_wait);
}

void CMLib_ConvDataStateSet(string lp_stateIndex, int lp_value) {
    if (lp_stateIndex == "") { return; }
    ConversationDataStateSetValue(lp_stateIndex, lp_value);
}

int CMLib_ConvDataStateGet(string lp_stateIndex) {
    if (lp_stateIndex == "") { return 0; }
    return ConversationDataStateGetValue(lp_stateIndex);
}

text CMLib_ConvDataStateTextOf(string lp_stateIndex, string lp_infoName) {
    if ((lp_stateIndex == "") || (lp_infoName == "")) { return StringToText(""); }
    return ConversationDataStateText(lp_stateIndex, lp_infoName);
}
"""

# ============================ trig ==========================================
BLOCKS["cmlib_trig_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 事件族补齐（按键 / 界面按钮 / 升级 / 行为分类）+ 可跳过段
//
// 本模块此前已有 41 个事件注册器，但缺了「玩家输入」这一整类 —— 而热键与
// 界面按钮正是自定义面板效果最常见的驱动源（gap_scan：KeyPressed 246 次 /
// ButtonPressed 124 次 / UpgradeLevelChanged 138 次）。
//
// 修饰键约定（引擎常量，natives.galaxy）：
//   c_keyModifierStateIgnore(0) 不关心 / Require(1) 必须按下 / Exclude(2) 必须没按
// =============================================================================

// 按键事件。三个修饰键一律 Ignore —— 90% 的用法都是「不管有没有按 Shift」。
void CMLib_OnKeyPressed(trigger lp_t, int lp_player, int lp_key, bool lp_down);
// 完整式：显式指定 shift / ctrl / alt 的 c_keyModifierState*。
void CMLib_OnKeyPressedMod(trigger lp_t, int lp_player, int lp_key, bool lp_down,
                           int lp_shift, int lp_ctrl, int lp_alt);
// 自定义界面按钮（UI 框架里的 button id）。
void CMLib_OnButtonPressed(trigger lp_t, int lp_player, string lp_button);
void CMLib_OnUpgradeLevelChanged(trigger lp_t, int lp_player);
// 按 Behavior **分类**（c_behaviorCategory*）而非具体 buff 监听增删，
// 做「被控制/被隐身」这类通用反应时比逐个 buff 挂事件省事得多。
void CMLib_OnBehaviorCategoryChange(trigger lp_t, unitref lp_u, int lp_category,
                                    int lp_changeType);

// ---- 事件取参（只能在对应事件的响应体内调用，否则返回值无意义） ----
string CMLib_EvtDamageEffect();
order  CMLib_EvtOrder();
unit   CMLib_EvtTarget();
point  CMLib_EvtTargetPoint();
timer  CMLib_EvtTimer();
wave   CMLib_EvtWave();
int    CMLib_EvtKey();
bool   CMLib_EvtKeyShift();
bool   CMLib_EvtKeyCtrl();
bool   CMLib_EvtKeyAlt();
string CMLib_EvtButton();

// ---- 可跳过段（过场动画标配） ----
// 在 Begin/End 之间的 Wait 会在足够多玩家按下跳过键时被打断，转而执行 onSkip。
// requiredCount <= 0 时自动取「允许跳过的玩家全数」。
void CMLib_SkippableBegin(playergroup lp_allowed, int lp_requiredCount, trigger lp_onSkip,
                          bool lp_testConds, bool lp_wait);
void CMLib_SkippableEnd();
"""

BLOCKS["cmlib_trig.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 事件族补齐 实现
// =============================================================================
void CMLib_OnKeyPressed(trigger lp_t, int lp_player, int lp_key, bool lp_down) {
    CMLib_OnKeyPressedMod(lp_t, lp_player, lp_key, lp_down,
                          c_keyModifierStateIgnore, c_keyModifierStateIgnore,
                          c_keyModifierStateIgnore);
}

void CMLib_OnKeyPressedMod(trigger lp_t, int lp_player, int lp_key, bool lp_down,
                           int lp_shift, int lp_ctrl, int lp_alt) {
    if (lp_t == null) { return; }
    TriggerAddEventKeyPressed(lp_t, lp_player, lp_key, lp_down,
                              lp_shift, lp_ctrl, lp_alt);
}

void CMLib_OnButtonPressed(trigger lp_t, int lp_player, string lp_button) {
    if ((lp_t == null) || (lp_button == "")) { return; }
    TriggerAddEventButtonPressed(lp_t, lp_player, lp_button);
}

void CMLib_OnUpgradeLevelChanged(trigger lp_t, int lp_player) {
    if (lp_t == null) { return; }
    TriggerAddEventUpgradeLevelChanged(lp_t, lp_player);
}

void CMLib_OnBehaviorCategoryChange(trigger lp_t, unitref lp_u, int lp_category,
                                    int lp_changeType) {
    if (lp_t == null) { return; }
    TriggerAddEventUnitBehaviorChangeFromCategory(lp_t, lp_u, lp_category, lp_changeType);
}

string CMLib_EvtDamageEffect() { return EventUnitDamageEffect(); }
order  CMLib_EvtOrder()        { return EventUnitOrder(); }
unit   CMLib_EvtTarget()       { return EventUnitTarget(); }
point  CMLib_EvtTargetPoint()  { return EventUnitTargetPoint(); }
timer  CMLib_EvtTimer()        { return EventTimer(); }
wave   CMLib_EvtWave()         { return EventPlayerWave(); }
int    CMLib_EvtKey()          { return EventKeyPressed(); }
bool   CMLib_EvtKeyShift()     { return EventKeyShift(); }
bool   CMLib_EvtKeyCtrl()      { return EventKeyControl(); }
bool   CMLib_EvtKeyAlt()       { return EventKeyAlt(); }
string CMLib_EvtButton()       { return EventButtonPressed(); }

void CMLib_SkippableBegin(playergroup lp_allowed, int lp_requiredCount, trigger lp_onSkip,
                          bool lp_testConds, bool lp_wait) {
    playergroup lv_pg;
    int lv_need;
    lv_pg = lp_allowed;
    if (lv_pg == null) { lv_pg = PlayerGroupAll(); }
    lv_need = lp_requiredCount;
    if (lv_need <= 0) { lv_need = PlayerGroupCount(lv_pg); }
    if (lv_need <= 0) { lv_need = 1; }
    TriggerSkippableBegin(lv_pg, lv_need, lp_onSkip, lp_testConds, lp_wait);
}

void CMLib_SkippableEnd() {
    TriggerSkippableEnd();
}
"""

# ============================ fx ============================================
BLOCKS["cmlib_fx_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— Ping 属性 / 镜头信息 / 音乐 / 头像 / 录像 / 资源预载
// =============================================================================

// ---- Ping：本模块此前只有创建与销毁，缺全部属性设置 ----
void CMLib_PingShow(int lp_ping, bool lp_visible);
void CMLib_PingMove(int lp_ping, point lp_pos);
void CMLib_PingTint(int lp_ping, color lp_color);
void CMLib_PingRotate(int lp_ping, fixed lp_rotation);
void CMLib_PingModel(int lp_ping, string lp_modelLink);
void CMLib_PingLifetime(int lp_ping, fixed lp_duration);

// ---- 镜头信息读取 / 边界 / 跟随 ----
// type 取 c_cameraValue*（Distance / Pitch / FieldOfView ...）。
fixed CMLib_CamInfoValue(camerainfo lp_cam, int lp_type);
point CMLib_CamInfoTarget(camerainfo lp_cam);
void  CMLib_CamBounds(playergroup lp_players, region lp_bounds, bool lp_includeMinimap);
void  CMLib_CamFollowGroup(int lp_player, unitgroup lp_group, bool lp_follow, bool lp_isOffset);
void  CMLib_CamApplyData(playergroup lp_players, string lp_cameraId);

// ---- 音乐 / 环境音轨（category 取 c_soundtrackCategory*） ----
void CMLib_MusicPause(playergroup lp_players, int lp_category, bool lp_pause, bool lp_fade);
void CMLib_MusicDefault(playergroup lp_players, int lp_category, string lp_soundtrack,
                        int lp_cue, int lp_index);

// ---- 头像 / 录像 ----
void CMLib_PortraitShow(int lp_portrait, playergroup lp_players, bool lp_visible,
                        bool lp_force);
void CMLib_MovieRecStart(string lp_name);
void CMLib_MovieRecStop();

// ---- 飘字标签可见性（创建/销毁本模块已有） ----
void CMLib_TextTagShowFor(int lp_tag, playergroup lp_players, bool lp_show);

// ---- 资源预载：切场景前预热，避免第一次出现时卡顿 ----
// queue=true 走后台队列（不阻塞），false 立即同步加载。
void CMLib_PreloadModel(string lp_path, bool lp_queue);
void CMLib_PreloadMovie(string lp_path, bool lp_queue);
void CMLib_PreloadAsset(string lp_key, bool lp_queue);
void CMLib_PreloadImage(string lp_path, bool lp_queue);
void CMLib_PreloadSound(string lp_path, bool lp_queue);
// 批量：kind 取 "model"/"movie"/"asset"/"image"/"sound"，csv 为逗号分隔路径表。
// 返回实际发起预载的条数。
int  CMLib_PreloadCSV(string lp_kind, string lp_csv, bool lp_queue);
"""

BLOCKS["cmlib_fx.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 实现
// =============================================================================
void CMLib_PingShow(int lp_ping, bool lp_visible) {
    if (lp_ping <= 0) { return; }
    PingSetVisible(lp_ping, lp_visible);
}

void CMLib_PingMove(int lp_ping, point lp_pos) {
    if ((lp_ping <= 0) || (lp_pos == null)) { return; }
    PingSetPosition(lp_ping, lp_pos);
}

void CMLib_PingTint(int lp_ping, color lp_color) {
    // 注意：color 是值类型，不能与 null 比较（round18 血泪）。
    if (lp_ping <= 0) { return; }
    PingSetColor(lp_ping, lp_color);
}

void CMLib_PingRotate(int lp_ping, fixed lp_rotation) {
    if (lp_ping <= 0) { return; }
    PingSetRotation(lp_ping, lp_rotation);
}

void CMLib_PingModel(int lp_ping, string lp_modelLink) {
    if ((lp_ping <= 0) || (lp_modelLink == "")) { return; }
    PingSetModel(lp_ping, lp_modelLink);
}

void CMLib_PingLifetime(int lp_ping, fixed lp_duration) {
    if (lp_ping <= 0) { return; }
    PingSetDuration(lp_ping, lp_duration);
}

fixed CMLib_CamInfoValue(camerainfo lp_cam, int lp_type) {
    return CameraInfoGetValue(lp_cam, lp_type);
}

point CMLib_CamInfoTarget(camerainfo lp_cam) {
    return CameraInfoGetTarget(lp_cam);
}

void CMLib_CamBounds(playergroup lp_players, region lp_bounds, bool lp_includeMinimap) {
    if ((lp_players == null) || (lp_bounds == null)) { return; }
    CameraSetBounds(lp_players, lp_bounds, lp_includeMinimap);
}

void CMLib_CamFollowGroup(int lp_player, unitgroup lp_group, bool lp_follow, bool lp_isOffset) {
    if (CMLib_IsValidPlayerSlot(lp_player) == false) { return; }
    if (lp_group == null) { return; }
    CameraFollowUnitGroup(lp_player, lp_group, lp_follow, lp_isOffset);
}

void CMLib_CamApplyData(playergroup lp_players, string lp_cameraId) {
    if ((lp_players == null) || (lp_cameraId == "")) { return; }
    CameraSetData(lp_players, lp_cameraId);
}

void CMLib_MusicPause(playergroup lp_players, int lp_category, bool lp_pause, bool lp_fade) {
    if (lp_players == null) { return; }
    SoundtrackPause(lp_players, lp_category, lp_pause, lp_fade);
}

void CMLib_MusicDefault(playergroup lp_players, int lp_category, string lp_soundtrack,
                        int lp_cue, int lp_index) {
    if ((lp_players == null) || (lp_soundtrack == "")) { return; }
    SoundtrackDefault(lp_players, lp_category, lp_soundtrack, lp_cue, lp_index);
}

void CMLib_PortraitShow(int lp_portrait, playergroup lp_players, bool lp_visible,
                        bool lp_force) {
    if ((lp_portrait <= 0) || (lp_players == null)) { return; }
    PortraitSetVisible(lp_portrait, lp_players, lp_visible, lp_force);
}

void CMLib_MovieRecStart(string lp_name) {
    if (lp_name == "") { return; }
    MovieStartRecording(lp_name);
}

void CMLib_MovieRecStop() {
    MovieStopRecording();
}

void CMLib_TextTagShowFor(int lp_tag, playergroup lp_players, bool lp_show) {
    if ((lp_tag <= 0) || (lp_players == null)) { return; }
    TextTagShow(lp_tag, lp_players, lp_show);
}

void CMLib_PreloadModel(string lp_path, bool lp_queue) {
    if (lp_path == "") { return; }
    PreloadModel(lp_path, lp_queue);
}

void CMLib_PreloadMovie(string lp_path, bool lp_queue) {
    if (lp_path == "") { return; }
    PreloadMovie(lp_path, lp_queue);
}

void CMLib_PreloadAsset(string lp_key, bool lp_queue) {
    if (lp_key == "") { return; }
    PreloadAsset(lp_key, lp_queue);
}

void CMLib_PreloadImage(string lp_path, bool lp_queue) {
    if (lp_path == "") { return; }
    PreloadImage(lp_path, lp_queue);
}

void CMLib_PreloadSound(string lp_path, bool lp_queue) {
    if (lp_path == "") { return; }
    PreloadSound(lp_path, lp_queue);
}

int CMLib_PreloadCSV(string lp_kind, string lp_csv, bool lp_queue) {
    int lv_n;
    int lv_i;
    int lv_done;
    string lv_item;
    lv_done = 0;
    if ((lp_kind == "") || (lp_csv == "")) { return 0; }
    lv_n = CMLib_SplitCount(lp_csv, ",");
    lv_i = 0;
    while (lv_i < lv_n) {
        lv_item = CMLib_SplitAt(lp_csv, ",", lv_i);
        if (lv_item != "") {
            if (lp_kind == "model")      { PreloadModel(lv_item, lp_queue); lv_done += 1; }
            else if (lp_kind == "movie") { PreloadMovie(lv_item, lp_queue); lv_done += 1; }
            else if (lp_kind == "asset") { PreloadAsset(lv_item, lp_queue); lv_done += 1; }
            else if (lp_kind == "image") { PreloadImage(lv_item, lp_queue); lv_done += 1; }
            else if (lp_kind == "sound") { PreloadSound(lv_item, lp_queue); lv_done += 1; }
        }
        lv_i += 1;
    }
    return lv_done;
}
"""

# ============================ text ==========================================
BLOCKS["cmlib_text_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 时间格式化 / 文本替换
// =============================================================================
// 秒数按 format 模板渲染（如 "mm:ss"）。负秒钳到 0，避免出现 "-01:-30"。
text CMLib_TimeText(text lp_format, int lp_seconds);
// 词替换。maxCount <= 0 表示全部替换。
text CMLib_TextReplace(text lp_src, text lp_word, text lp_replace, int lp_maxCount,
                       bool lp_caseSensitive);
"""

BLOCKS["cmlib_text.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 实现
// =============================================================================
text CMLib_TimeText(text lp_format, int lp_seconds) {
    int lv_s;
    lv_s = lp_seconds;
    if (lv_s < 0) { lv_s = 0; }
    return TextTimeFormat(lp_format, lv_s);
}

text CMLib_TextReplace(text lp_src, text lp_word, text lp_replace, int lp_maxCount,
                       bool lp_caseSensitive) {
    int lv_max;
    lv_max = lp_maxCount;
    if (lv_max <= 0) { lv_max = c_maxInt; }
    return TextReplaceWord(lp_src, lp_word, lp_replace, lv_max, lp_caseSensitive);
}
"""

# ============================ unit ==========================================
BLOCKS["cmlib_unit_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 单位造价 / 运输舱产出 / 技能命令解包
// =============================================================================
// costType 取 c_unitCostMinerals / Vespene / Terrazine / SumMineralsVespene 等。
int CMLib_UnitTypeCost(string lp_unitType, int lp_costType);
// 上一次 UnitCargoCreate 产出的整组单位（一次造多个时只能靠它拿全）。
unitgroup CMLib_UnitCargoLastGroup();
// 从 abilcmd 里取出技能 id 字符串（做技能事件分发时的标准姿势）。
string CMLib_AbilCmdAbility(abilcmd lp_cmd);
"""

BLOCKS["cmlib_unit.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 实现
// =============================================================================
int CMLib_UnitTypeCost(string lp_unitType, int lp_costType) {
    if (lp_unitType == "") { return 0; }
    return UnitTypeGetCost(lp_unitType, lp_costType);
}

unitgroup CMLib_UnitCargoLastGroup() {
    unitgroup lv_g;
    lv_g = UnitCargoLastCreatedGroup();
    if (lv_g == null) { return UnitGroupEmpty(); }
    return lv_g;
}

string CMLib_AbilCmdAbility(abilcmd lp_cmd) {
    string lv_s;
    lv_s = AbilityCommandGetAbility(lp_cmd);
    if (lv_s == null) { return ""; }
    return lv_s;
}
"""

# ============================ game ==========================================
BLOCKS["cmlib_game_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 场景背景 / 作弊开关 / 环境判定
// =============================================================================
// type 取 c_backgroundFixed(贴镜头，永远不动) / c_backgroundTerrain(贴地形，随镜头滚)。
void CMLib_GameBackground(int lp_type, string lp_model, fixed lp_animSpeed);
// cheat 取 c_gameCheat*，通常用于测试图开 God/FastBuild。
void CMLib_GameCheat(int lp_cheat, bool lp_allow);
bool CMLib_GameOnline();
// inAuto=true 时把「编辑器一键测试」也算作测试图。
bool CMLib_GameTestMap(bool lp_auto);
"""

BLOCKS["cmlib_game.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 实现
// =============================================================================
void CMLib_GameBackground(int lp_type, string lp_model, fixed lp_animSpeed) {
    if (lp_model == "") { return; }
    GameSetBackground(CMLib_ClampInt(lp_type, c_backgroundFixed, c_backgroundTerrain),
                      lp_model, lp_animSpeed);
}

void CMLib_GameCheat(int lp_cheat, bool lp_allow) {
    GameCheatAllow(lp_cheat, lp_allow);
}

bool CMLib_GameOnline() {
    return GameIsOnline();
}

bool CMLib_GameTestMap(bool lp_auto) {
    return GameIsTestMap(lp_auto);
}
"""

# ============================ geo ===========================================
BLOCKS["cmlib_geo_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 可玩区域设置
// =============================================================================
// 收缩/扩张可玩地图范围（迷雾、镜头边界、单位出生合法性都跟着它走）。
void CMLib_PlayableMapSet(region lp_r);
"""

BLOCKS["cmlib_geo.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 实现
// =============================================================================
void CMLib_PlayableMapSet(region lp_r) {
    if (lp_r == null) { return; }
    RegionPlayableMapSet(lp_r);
}
"""

# ============================ ai ============================================
BLOCKS["cmlib_ai_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— AI 计时暂停 / 科技树提示
// =============================================================================
// 暂停/恢复 AI 内部计时（过场动画期间冻结 AI 节奏的标准做法）。
void CMLib_AITimePause(bool lp_pause);
// 在科技树面板上显示/隐藏某单位（做渐进解锁时用）。
void CMLib_TechTreeUnitHelp(int lp_player, string lp_unitType, bool lp_display);
"""

BLOCKS["cmlib_ai.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 实现
// =============================================================================
void CMLib_AITimePause(bool lp_pause) {
    AITimePause(lp_pause);
}

void CMLib_TechTreeUnitHelp(int lp_player, string lp_unitType, bool lp_display) {
    if (CMLib_IsValidPlayerSlot(lp_player) == false) { return; }
    if (lp_unitType == "") { return; }
    TechTreeUnitHelp(lp_player, lp_unitType, lp_display);
}
"""

# ============================ udata =========================================
BLOCKS["cmlib_udata_h.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— User Data 图片路径
// =============================================================================
// 从自定义 User Data 表里取图片资源路径；任一参数为空返回 ""。
string CMLib_UDataImagePath(string lp_type, string lp_instance, string lp_field,
                            int lp_index);
"""

BLOCKS["cmlib_udata.galaxy"] = r"""
// =============================================================================
// CMLib :: Round19 —— 实现
// =============================================================================
string CMLib_UDataImagePath(string lp_type, string lp_instance, string lp_field,
                            int lp_index) {
    string lv_s;
    if ((lp_type == "") || (lp_instance == "") || (lp_field == "")) { return ""; }
    lv_s = UserDataGetImagePath(lp_type, lp_instance, lp_field, lp_index);
    if (lv_s == null) { return ""; }
    return lv_s;
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
