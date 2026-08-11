# CMLib — 完整 API 索引（自动生成，勿手改）

> 由 `gen_api_index.py` 从各模块 `_h.galaxy` 声明生成，**单一来源、不会与实现漂移**。
> 每轮扩库后重跑：`python gen_api_index.py`。
>
> 这里保证**一个函数都不漏**；至于「为什么这么设计、踩过什么坑」，看 [`README.md`](README.md) §2 精选速查。

| 生成时间 | 模块数 | 函数总数 |
|---|---|---|
| 2026-08-10 07:20 | 21 | 1417 |

---

## 目录

- [`cmlib_core`](#cmlib_core) — 数值 / 字符串 / 键名 / 日志 / DataTable 存储（100）
- [`cmlib_ui`](#cmlib_ui) — Dialog 控件挂钩 / 创建 / 属性 / 列表 / 事件 / HUD（79）
- [`cmlib_unit`](#cmlib_unit) — unitfilter / 单位查询 / 生成 / 行为·武器 / 命令 / 清理（172）
- [`cmlib_catalog`](#cmlib_catalog) — Catalog 运行时读写（单位/武器/效果/行为/技能/按钮）（70）
- [`cmlib_player`](#cmlib_player) — 玩家判定 / 遍历 / PlayerGroup / 资源 / 联盟 / 科技（57）
- [`cmlib_ai`](#cmlib_ai) — AI 波次编排 / 难度 / 脚本控制（75）
- [`cmlib_fx`](#cmlib_fx) — 音效 / 音乐 / 镜头 / 淡入淡出 / Ping / 飘字 / Actor（90）
- [`cmlib_panel`](#cmlib_panel) — Dialog 容器 / 计时器窗口 / 任务目标（64）
- [`cmlib_bank`](#cmlib_bank) — Bank 存档（fallback / 脏标记批量落盘 / 版本 / 枚举）（39）
- [`cmlib_geo`](#cmlib_geo) — 几何 / 寻路 / 单位自定义值 / 行为查询（55）
- [`cmlib_text`](#cmlib_text) — 本地化文本 / 数值格式化 / 颜色文本 / 单位名（18）
- [`cmlib_trig`](#cmlib_trig) — 触发器编排 / 事件挂载 / 等待与计时 / 事件取参（146）
- [`cmlib_game`](#cmlib_game) — 游戏状态 / 胜负 / 视野迷雾 / 揭示器 / 蔓延 / 时间（49）
- [`cmlib_conv`](#cmlib_conv) — 过场对白（Transmission / Conversation）（59）
- [`cmlib_udata`](#cmlib_udata) — 数据编辑器 User Data 表读写（31）
- [`cmlib_stock`](#cmlib_stock) — 电脑 AI 库存 / 科技树 / AI 用户变量（43）
- [`cmlib_board`](#cmlib_board) — 排行榜面板（Board）/ 任务结算面板（VictoryPanel）（68）
- [`cmlib_buff`](#cmlib_buff) — Behavior 增益减益 / 单位状态开关 / 玩家状态开关（51）
- [`cmlib_path`](#cmlib_path) — 地形寻路查询 / 路线（Route）可视化编排（54）
- [`cmlib_env`](#cmlib_env) — 装饰物 Doodad / 地形贴图 / 水面 / 战争迷雾外观（29）
- [`cmlib_stat`](#cmlib_stat) — 成就 / 分数 / 难度名 / 效果历史 / 战役模式 / 时间戳（68）


## cmlib_core

> 数值 / 字符串 / 键名 / 日志 / DataTable 存储

| 返回 | 函数 | 参数 |
|---|---|---|
| `int` | **`CMLib_ClampInt`** | `int, int, int` |
| `fixed` | **`CMLib_ClampFixed`** | `fixed, fixed, fixed` |
| `int` | **`CMLib_MinInt`** | `int, int` |
| `int` | **`CMLib_MaxInt`** | `int, int` |
| `int` | **`CMLib_AbsInt`** | `int` |
| `int` | **`CMLib_DivInt`** | `int, int, int` |
| `fixed` | **`CMLib_DivFixed`** | `fixed, fixed, fixed` |
| `int` | **`CMLib_ScalePercentInt`** | `int, int` |
| `fixed` | **`CMLib_ScalePercentFixed`** | `fixed, int` |
| `fixed` | **`CMLib_Lerp`** | `fixed, fixed, fixed` |
| `bool` | **`CMLib_IsValidPlayerSlot`** | `int` |
| `bool` | **`CMLib_IsActivePlayer`** | `int` |
| `bool` | **`CMLib_StrIsEmpty`** | `string` |
| `bool` | **`CMLib_StrNotEmpty`** | `string` |
| `string` | **`CMLib_CharAt`** | `string, int` |
| `bool` | **`CMLib_StartsWith`** | `string, string` |
| `bool` | **`CMLib_EndsWith`** | `string, string` |
| `bool` | **`CMLib_Contains`** | `string, string` |
| `string` | **`CMLib_TrimSpaces`** | `string` |
| `string` | **`CMLib_SplitAt`** | `string, string, int` |
| `int` | **`CMLib_SplitCount`** | `string, string` |
| `int` | **`CMLib_ParseInt`** | `string, int` |
| `fixed` | **`CMLib_ParseFixed`** | `string, fixed` |
| `string` | **`CMLib_BoolToString`** | `bool` |
| `bool` | **`CMLib_ParseBool`** | `string, bool` |
| `string` | **`CMLib_Key1`** | `string` |
| `string` | **`CMLib_Key2`** | `string, string` |
| `string` | **`CMLib_Key3`** | `string, string, string` |
| `string` | **`CMLib_KeyPlayer`** | `string, int` |
| `string` | **`CMLib_KeyIndexed`** | `string, int` |
| `bool` | **`CMLib_StoreHas`** | `string` |
| `void` | **`CMLib_StoreInt`** | `string, int` |
| `int` | **`CMLib_LoadInt`** | `string, int` |
| `void` | **`CMLib_StoreFixed`** | `string, fixed` |
| `fixed` | **`CMLib_LoadFixed`** | `string, fixed` |
| `void` | **`CMLib_StoreString`** | `string, string` |
| `string` | **`CMLib_LoadString`** | `string, string` |
| `void` | **`CMLib_StoreBool`** | `string, bool` |
| `bool` | **`CMLib_LoadBool`** | `string, bool` |
| `void` | **`CMLib_StoreUnit`** | `string, unit` |
| `unit` | **`CMLib_LoadUnit`** | `string` |
| `int` | **`CMLib_StoreBump`** | `string, int` |
| `void` | **`CMLib_LogSetLevel`** | `int` |
| `int` | **`CMLib_LogGetLevel`** | `—` |
| `void` | **`CMLib_LogError`** | `string, string` |
| `void` | **`CMLib_LogWarn`** | `string, string` |
| `void` | **`CMLib_LogInfo`** | `string, string` |
| `void` | **`CMLib_LogDebug`** | `string, string` |
| `fixed` | **`CMLib_RandF`** | `fixed, fixed` |
| `int` | **`CMLib_RandI`** | `int, int` |
| `int` | **`CMLib_ModSafe`** | `int, int` |
| `bool` | **`CMLib_DTHas`** | `bool, string` |
| `void` | **`CMLib_DTRemove`** | `bool, string` |
| `void` | **`CMLib_DTClear`** | `bool` |
| `int` | **`CMLib_DTCount`** | `bool` |
| `string` | **`CMLib_DTNameAt`** | `bool, int` |
| `int` | **`CMLib_DTClearPrefix`** | `bool, string` |
| `void` | **`CMLib_DTSetBool`** | `bool, string, bool` |
| `bool` | **`CMLib_DTGetBool`** | `bool, string, bool` |
| `void` | **`CMLib_DTSetUG`** | `bool, string, unitgroup` |
| `unitgroup` | **`CMLib_DTGetUG`** | `bool, string` |
| `void` | **`CMLib_DTSetTimer`** | `bool, string, timer` |
| `timer` | **`CMLib_DTGetTimer`** | `bool, string` |
| `void` | **`CMLib_DTSetObjective`** | `bool, string, int` |
| `int` | **`CMLib_DTGetObjective`** | `bool, string` |
| `void` | **`CMLib_DTSetRegion`** | `bool, string, region` |
| `region` | **`CMLib_DTGetRegion`** | `bool, string` |
| `int` | **`CMLib_RoundI`** | `fixed` |
| `fixed` | **`CMLib_TimerDuration`** | `timer` |
| `bool` | **`CMLib_TimerPaused`** | `timer` |
| `fixed` | **`CMLib_TimerProgress`** | `timer` |
| `void` | **`CMLib_DTSetInt`** | `bool, string, int` |
| `int` | **`CMLib_DTGetInt`** | `bool, string, int` |
| `void` | **`CMLib_DTSetFixed`** | `bool, string, fixed` |
| `fixed` | **`CMLib_DTGetFixed`** | `bool, string, fixed` |
| `void` | **`CMLib_DTSetString`** | `bool, string, string` |
| `string` | **`CMLib_DTGetString`** | `bool, string, string` |
| `void` | **`CMLib_DTSetUnit`** | `bool, string, unit` |
| `unit` | **`CMLib_DTGetUnit`** | `bool, string` |
| `void` | **`CMLib_DTSetPoint`** | `bool, string, point` |
| `point` | **`CMLib_DTGetPoint`** | `bool, string` |
| `fixed` | **`CMLib_MinFixed`** | `fixed, fixed` |
| `fixed` | **`CMLib_MaxFixed`** | `fixed, fixed` |
| `fixed` | **`CMLib_AbsFixed`** | `fixed` |
| `fixed` | **`CMLib_ModFixed`** | `fixed, fixed` |
| `void` | **`CMLib_DTSetSound`** | `bool, string, sound` |
| `sound` | **`CMLib_DTGetSound`** | `bool, string` |
| `void` | **`CMLib_DTSetCameraInfo`** | `bool, string, camerainfo` |
| `camerainfo` | **`CMLib_DTGetCameraInfo`** | `bool, string` |
| `void` | **`CMLib_DTSetMarker`** | `bool, string, marker` |
| `marker` | **`CMLib_DTGetMarker`** | `bool, string` |
| `string` | **`CMLib_StrCase`** | `string, bool` |
| `int` | **`CMLib_StrCompare`** | `string, string, bool` |
| `bool` | **`CMLib_StrContains`** | `string, string, int, bool` |
| `text` | **`CMLib_StrAsset`** | `string` |
| `text` | **`CMLib_StrHotkey`** | `string` |
| `string` | **`CMLib_StrReplaceRange`** | `string, string, int, int` |
| `string` | **`CMLib_StrReplaceWord`** | `string, string, string, int, bool` |
| `string` | **`CMLib_StrWord`** | `string, int` |
| `datetime` | **`CMLib_StrToDateTime`** | `string` |

## cmlib_ui

> Dialog 控件挂钩 / 创建 / 属性 / 列表 / 事件 / HUD

| 返回 | 函数 | 参数 |
|---|---|---|
| `bool` | **`CMLib_UIValid`** | `int` |
| `int` | **`CMLib_UIHookup`** | `int, int, string` |
| `int` | **`CMLib_UIHookupIndexed`** | `int, int, string, int` |
| `int` | **`CMLib_UIHookupStandard`** | `int, string` |
| `int` | **`CMLib_UIHookupPanel`** | `int, string` |
| `int` | **`CMLib_UIHookupButton`** | `int, string` |
| `int` | **`CMLib_UIHookupLabel`** | `int, string` |
| `int` | **`CMLib_UIHookupImage`** | `int, string` |
| `int` | **`CMLib_UICreateInPanel`** | `int, int` |
| `int` | **`CMLib_UICreateFromTemplate`** | `int, int, string` |
| `void` | **`CMLib_UISetText`** | `int, playergroup, text` |
| `void` | **`CMLib_UISetTooltip`** | `int, playergroup, text` |
| `void` | **`CMLib_UISetImage`** | `int, playergroup, string` |
| `void` | **`CMLib_UISetColor`** | `int, playergroup, color` |
| `void` | **`CMLib_UISetToggled`** | `int, playergroup, bool` |
| `void` | **`CMLib_UISetVisible`** | `int, playergroup, bool` |
| `void` | **`CMLib_UISetEnabled`** | `int, playergroup, bool` |
| `void` | **`CMLib_UISetSize`** | `int, playergroup, int, int` |
| `void` | **`CMLib_UISetPosition`** | `int, playergroup, int, int, int` |
| `void` | **`CMLib_UISetPositionRelative`** | `int, playergroup, int, int, int, int, int` |
| `void` | **`CMLib_UISetAnimationState`** | `int, playergroup, string, string` |
| `void` | **`CMLib_UISetRenderPriority`** | `int, playergroup, int` |
| `int` | **`CMLib_UICreatePlaced`** | `int, int, playergroup, int, int, int, int, int` |
| `void` | **`CMLib_UISetActive`** | `int, playergroup, bool` |
| `void` | **`CMLib_UISetVisibleRange`** | `arrayref<CMLib_UIControlArray>, int, playergroup, bool` |
| `void` | **`CMLib_UIListClear`** | `int, playergroup` |
| `void` | **`CMLib_UIListAddItem`** | `int, playergroup, text` |
| `void` | **`CMLib_UIListSelect`** | `int, playergroup, int` |
| `bool` | **`CMLib_UIOnClick`** | `trigger, int` |
| `int` | **`CMLib_UIOnClickRange`** | `trigger, arrayref<CMLib_UIControlArray>, int` |
| `void` | **`CMLib_Msg`** | `playergroup, int, text` |
| `void` | **`CMLib_MsgAll`** | `int, text` |
| `void` | **`CMLib_MsgPlayer`** | `int, int, text` |
| `void` | **`CMLib_MsgClear`** | `playergroup, int` |
| `void` | **`CMLib_MsgClearAll`** | `—` |
| `void` | **`CMLib_MsgObjective`** | `playergroup, text` |
| `void` | **`CMLib_MsgDirective`** | `playergroup, text` |
| `void` | **`CMLib_MsgError`** | `playergroup, text` |
| `void` | **`CMLib_MsgSubtitle`** | `playergroup, text` |
| `void` | **`CMLib_MsgWarning`** | `playergroup, text` |
| `void` | **`CMLib_AlertAtPoint`** | `string, int, text, string, point` |
| `void` | **`CMLib_AlertAtUnit`** | `string, int, text, string, unit` |
| `void` | **`CMLib_UIFade`** | `int, playergroup, fixed, fixed` |
| `void` | **`CMLib_UIFadeIn`** | `int, playergroup, fixed` |
| `void` | **`CMLib_UIFadeOut`** | `int, playergroup, fixed` |
| `void` | **`CMLib_UIAnimEvent`** | `int, playergroup, string` |
| `void` | **`CMLib_HudFrame`** | `playergroup, int, bool` |
| `void` | **`CMLib_HudFrameAll`** | `int, bool` |
| `int` | **`CMLib_HudFrameCSV`** | `playergroup, string, bool` |
| `void` | **`CMLib_HudCinematic`** | `playergroup, bool` |
| `void` | **`CMLib_HudWorldVisible`** | `playergroup, bool` |
| `void` | **`CMLib_UISetMode`** | `playergroup, int, fixed` |
| `void` | **`CMLib_UIMode`** | `playergroup, int` |
| `void` | **`CMLib_UIModeConsole`** | `playergroup, fixed` |
| `void` | **`CMLib_UIModeLetterbox`** | `playergroup, fixed` |
| `void` | **`CMLib_UIModeFullscreen`** | `playergroup, fixed` |
| `void` | **`CMLib_UIButtonHighlight`** | `playergroup, string, int, bool` |
| `void` | **`CMLib_UICursor`** | `playergroup, bool` |
| `void` | **`CMLib_UISelectionType`** | `playergroup, int, bool` |
| `int` | **`CMLib_DlgCtrlCreate`** | `int, int` |
| `int` | **`CMLib_DlgCtrlCreateTpl`** | `int, int, string` |
| `int` | **`CMLib_DlgCtrlSelectedItem`** | `int, int` |
| `void` | **`CMLib_DlgCtrlFullDialog`** | `int, playergroup, bool` |
| `void` | **`CMLib_DlgCtrlDestroy`** | `int` |
| `void` | **`CMLib_UIFaceHighlight`** | `playergroup, string, bool` |
| `bool` | **`CMLib_DlgCtrlVisible`** | `int, int` |
| `int` | **`CMLib_DlgCtrlDialog`** | `int` |
| `int` | **`CMLib_DlgHookupUnitStatus`** | `int, string, unit` |
| `void` | **`CMLib_UICommandAllow`** | `playergroup, int, bool` |
| `void` | **`CMLib_UICommandAllowAll`** | `playergroup, bool` |
| `void` | **`CMLib_UITargetOrder`** | `playergroup, unitgroup, order, bool` |
| `void` | **`CMLib_UIAlertClear`** | `int` |
| `void` | **`CMLib_UIAlertClearAll`** | `—` |
| `void` | **`CMLib_UIAlertTypeVisible`** | `playergroup, string, bool` |
| `void` | **`CMLib_UITextCrawlShow`** | `playergroup, text, text, fixed, soundlink, soundlink` |
| `void` | **`CMLib_UITextCrawlHide`** | `playergroup` |
| `void` | **`CMLib_UIGameMenuItemVisible`** | `playergroup, int, bool` |
| `void` | **`CMLib_DCObservedType`** | `int, int` |
| `int` | **`CMLib_DCRelative`** | `int, int` |

## cmlib_unit

> unitfilter / 单位查询 / 生成 / 行为·武器 / 命令 / 清理

| 返回 | 函数 | 参数 |
|---|---|---|
| `unitfilter` | **`CMLib_FilterAlive`** | `—` |
| `unitfilter` | **`CMLib_FilterAliveVisible`** | `—` |
| `unitfilter` | **`CMLib_FilterAliveVisibleTargetable`** | `—` |
| `unitfilter` | **`CMLib_FilterStructure`** | `—` |
| `unitfilter` | **`CMLib_FilterNonStructure`** | `—` |
| `bool` | **`CMLib_UnitOk`** | `unit` |
| `bool` | **`CMLib_UnitIsStructure`** | `unit` |
| `bool` | **`CMLib_UnitIsType`** | `unit, string` |
| `bool` | **`CMLib_UnitOwnedBy`** | `unit, int` |
| `void` | **`CMLib_UnitVisitor_Proto`** | `unit, int` |
| `int` | **`CMLib_UGForEach`** | `unitgroup, CMLib_UnitVisitor, int` |
| `int` | **`CMLib_UGForEachAlive`** | `unitgroup, CMLib_UnitVisitor, int` |
| `int` | **`CMLib_UGSize`** | `unitgroup` |
| `int` | **`CMLib_UGSizeAlive`** | `unitgroup` |
| `bool` | **`CMLib_UGIsEmpty`** | `unitgroup` |
| `unit` | **`CMLib_UGAt`** | `unitgroup, int` |
| `unit` | **`CMLib_UGFirstAlive`** | `unitgroup` |
| `unitgroup` | **`CMLib_UGOfTypeInMap`** | `string, int` |
| `unitgroup` | **`CMLib_UGOfTypeInRegion`** | `string, int, region` |
| `unitgroup` | **`CMLib_UGOfTypeNearPoint`** | `string, int, point, fixed` |
| `unitgroup` | **`CMLib_UGStructuresOfPlayer`** | `int` |
| `unitgroup` | **`CMLib_UGArmyOfPlayer`** | `int` |
| `void` | **`CMLib_UGAdd`** | `unitgroup, unit` |
| `void` | **`CMLib_UGAddGroup`** | `unitgroup, unitgroup` |
| `void` | **`CMLib_UGRemove`** | `unitgroup, unit` |
| `void` | **`CMLib_UGClear`** | `unitgroup` |
| `unitgroup` | **`CMLib_UGCopy`** | `unitgroup` |
| `unit` | **`CMLib_UGUnit`** | `unitgroup, int` |
| `unit` | **`CMLib_UGRandomUnit`** | `unitgroup, int` |
| `bool` | **`CMLib_UGHasUnit`** | `unitgroup, unit` |
| `unit` | **`CMLib_Spawn`** | `string, int, point, fixed` |
| `unit` | **`CMLib_SpawnForced`** | `string, int, point, fixed` |
| `unitgroup` | **`CMLib_SpawnMany`** | `int, string, int, point, fixed` |
| `unitgroup` | **`CMLib_SpawnRing`** | `int, string, int, point, fixed` |
| `unit` | **`CMLib_RespawnInPlace`** | `unit, string, int` |
| `fixed` | **`CMLib_UnitLifePercent`** | `unit` |
| `fixed` | **`CMLib_UnitShieldPercent`** | `unit` |
| `void` | **`CMLib_UnitSetLifePercent`** | `unit, fixed` |
| `void` | **`CMLib_UnitCopyVitalsPercent`** | `unit, unit` |
| `void` | **`CMLib_UnitSetState`** | `unit, int, bool` |
| `void` | **`CMLib_UnitSetPosition`** | `unit, point, bool` |
| `bool` | **`CMLib_UnitEnsureBehavior`** | `unit, string, int, int` |
| `bool` | **`CMLib_UnitRemoveBehavior`** | `unit, string, int, int` |
| `bool` | **`CMLib_UnitToggleBehavior`** | `unit, string, int, bool` |
| `bool` | **`CMLib_UnitEnsureWeapon`** | `unit, string, string` |
| `bool` | **`CMLib_UnitRemoveWeapon`** | `unit, string` |
| `int` | **`CMLib_UGEnsureBehavior`** | `unitgroup, string, int, int` |
| `int` | **`CMLib_UGRemoveBehavior`** | `unitgroup, string, int, int` |
| `void` | **`CMLib_UnitBehaviorAdd`** | `unit, string, unit, int` |
| `void` | **`CMLib_UnitBehaviorRemove`** | `unit, string, int` |
| `bool` | **`CMLib_UnitOrderAbility`** | `unit, string, int, int` |
| `bool` | **`CMLib_UnitOrderAbilityAtPoint`** | `unit, string, int, point, int` |
| `int` | **`CMLib_UGOrderAbilityAtPoint`** | `unitgroup, string, int, point, int` |
| `int` | **`CMLib_UGRemoveAll`** | `unitgroup` |
| `int` | **`CMLib_UGKillAll`** | `unitgroup` |
| `bool` | **`CMLib_UnitMatchFilter`** | `unit, int, unitfilter` |
| `void` | **`CMLib_UnitsPauseAll`** | `bool` |
| `text` | **`CMLib_UnitTypeName`** | `string` |
| `bool` | **`CMLib_UnitChangeOwner`** | `unit, int, bool` |
| `bool` | **`CMLib_UGIssueOrder`** | `unitgroup, order, int` |
| `bool` | **`CMLib_UGOrderAbility`** | `unitgroup, string, int, int` |
| `bool` | **`CMLib_UGOrderAbilityAtUnit`** | `unitgroup, string, int, unit, int` |
| `unitgroup` | **`CMLib_UGAlliance`** | `int, int, region, unitfilter, int` |
| `unitgroup` | **`CMLib_UGEnemiesOf`** | `int, int` |
| `unitgroup` | **`CMLib_UGAlliesOf`** | `int, int` |
| `void` | **`CMLib_UnitCreateEffectPoint`** | `unit, string, point` |
| `void` | **`CMLib_UnitAbilityEnable`** | `unit, string, bool` |
| `void` | **`CMLib_UnitCargoCreate`** | `unit, string, int` |
| `void` | **`CMLib_UnitSetHeight`** | `unit, fixed, fixed` |
| `void` | **`CMLib_UnitRemove`** | `unit` |
| `unit` | **`CMLib_UGClosestToPoint`** | `unitgroup, point` |
| `point` | **`CMLib_UGCenterOfGroup`** | `unitgroup` |
| `order` | **`CMLib_UnitOrderAt`** | `unit, int` |
| `bool` | **`CMLib_UnitOrderHasAbil`** | `unit, string` |
| `void` | **`CMLib_SelClear`** | `int` |
| `unitgroup` | **`CMLib_UGSelected`** | `int` |
| `unitgroup` | **`CMLib_UGFilterStr`** | `string, int, unitgroup, string, int` |
| `unit` | **`CMLib_UnitById`** | `int` |
| `int` | **`CMLib_UnitTag`** | `unit` |
| `void` | **`CMLib_UnitFace`** | `unit, fixed, fixed` |
| `void` | **`CMLib_UnitFaceUnit`** | `unit, unit, fixed` |
| `void` | **`CMLib_UnitFacePoint`** | `unit, point, fixed` |
| `void` | **`CMLib_UnitSelectFor`** | `unit, int, bool` |
| `void` | **`CMLib_UnitSelectOnly`** | `unit, int` |
| `void` | **`CMLib_UnitInfoText`** | `unit, text, text, text` |
| `bool` | **`CMLib_UnitTypeFlag`** | `string, int` |
| `fixed` | **`CMLib_UnitTypeProp`** | `string, int` |
| `bool` | **`CMLib_UnitTypeIsStructure`** | `string` |
| `bool` | **`CMLib_UnitTypeIsWorker`** | `string` |
| `int` | **`CMLib_UnitCountOf`** | `string, int, region, string, int` |
| `int` | **`CMLib_UnitCountAllianceOf`** | `int, int, region, string, int` |
| `abilcmd` | **`CMLib_OrderAbilCmd`** | `order` |
| `unit` | **`CMLib_OrderTargetUnit`** | `order` |
| `point` | **`CMLib_OrderTargetPoint`** | `order` |
| `void` | **`CMLib_OrderSetTargetUnit`** | `order, unit` |
| `void` | **`CMLib_OrderSetTargetPoint`** | `order, point` |
| `order` | **`CMLib_OrderAt`** | `string, int, point` |
| `order` | **`CMLib_OrderOn`** | `string, int, unit` |
| `order` | **`CMLib_OrderAutoCast`** | `string, int, bool` |
| `bool` | **`CMLib_UnitHasBehaviorRaw`** | `unit, string` |
| `fixed` | **`CMLib_UnitAbilChargeInfo`** | `unit, abilcmd, int` |
| `void` | **`CMLib_UnitAbilReset`** | `unit, abilcmd, int` |
| `void` | **`CMLib_UnitTeamColor`** | `unit, int` |
| `int` | **`CMLib_UnitOrderCount`** | `unit` |
| `unitref` | **`CMLib_UnitRefFromVar`** | `string` |
| `unitgroup` | **`CMLib_UGFilterRegion`** | `unitgroup, region, int` |
| `int` | **`CMLib_UnitTypeCost`** | `string, int` |
| `unitgroup` | **`CMLib_UnitCargoLastGroup`** | `—` |
| `string` | **`CMLib_AbilCmdAbility`** | `abilcmd` |
| `void` | **`CMLib_UnitFlash`** | `unit, fixed` |
| `void` | **`CMLib_UGSelect`** | `unitgroup, int, bool` |
| `unitgroup` | **`CMLib_UGIdle`** | `int, bool` |
| `int` | **`CMLib_UGIdleCount`** | `int, bool` |
| `unitgroup` | **`CMLib_UnitCargo`** | `unit` |
| `int` | **`CMLib_UnitCargoCount`** | `unit` |
| `void` | **`CMLib_UnitBuffDuration`** | `unit, string, fixed` |
| `unit` | **`CMLib_UnitBuffEffectUnit`** | `unit, string, int, int` |
| `int` | **`CMLib_UnitPropInt`** | `unit, int, bool` |
| `void` | **`CMLib_UnitAbilShow`** | `unit, string, bool` |
| `bool` | **`CMLib_UnitAbilExists`** | `unit, string` |
| `point` | **`CMLib_UnitTypePlaceNear`** | `string, int, point, fixed` |
| `point` | **`CMLib_UnitAttachPoint`** | `unit, string` |
| `int` | **`CMLib_UnitQueueProp`** | `unit, int` |
| `int` | **`CMLib_UnitQueueUsed`** | `unit` |
| `int` | **`CMLib_UnitQueueFree`** | `unit` |
| `bool` | **`CMLib_UnitIsProducing`** | `unit` |
| `int` | **`CMLib_UnitQueueItemCount`** | `unit, int` |
| `string` | **`CMLib_UnitQueueItemAt`** | `unit, int, int` |
| `bool` | **`CMLib_UnitQueueItemIs`** | `unit, int, int` |
| `fixed` | **`CMLib_UnitQueueEta`** | `unit, int` |
| `fixed` | **`CMLib_UnitQueueProgress`** | `unit, int` |
| `text` | **`CMLib_UnitCustomName`** | `unit` |
| `int` | **`CMLib_UnitWeaponCount`** | `unit` |
| `fixed` | **`CMLib_UnitWeaponPeriod`** | `unit, int` |
| `fixed` | **`CMLib_UnitWeaponDamage`** | `unit, int, int, bool` |
| `fixed` | **`CMLib_UnitWeaponDps`** | `unit, int` |
| `fixed` | **`CMLib_UnitDpsTotal`** | `unit` |
| `bool` | **`CMLib_UnitIsHarvesting`** | `unit, int` |
| `bool` | **`CMLib_OrderFlag`** | `order, int` |
| `point` | **`CMLib_OrderTargetPos`** | `order` |
| `int` | **`CMLib_OrderTargetType`** | `order` |
| `bool` | **`CMLib_OrderHasTarget`** | `order` |
| `unitgroup` | **`CMLib_UGOf`** | `unit` |
| `void` | **`CMLib_UnitCtrlGroupAdd`** | `unit, int, int` |
| `int` | **`CMLib_UnitCargoValue`** | `unit, int` |
| `void` | **`CMLib_UnitStatusBarGroup`** | `unit, int` |
| `void` | **`CMLib_UnitSetScale`** | `unit, fixed, fixed, fixed` |
| `void` | **`CMLib_UnitSetScaleUniform`** | `unit, fixed` |
| `int` | **`CMLib_UnitVeterancyLevel`** | `unit, string` |
| `marker` | **`CMLib_Marker`** | `string` |
| `marker` | **`CMLib_MarkerForPlayer`** | `string, int` |
| `marker` | **`CMLib_MarkerForUnit`** | `string, unit` |
| `marker` | **`CMLib_UnitMarkerAt`** | `unit, int` |
| `void` | **`CMLib_UnitMarkerAdd`** | `unit, marker` |
| `int` | **`CMLib_UnitMarkerCount`** | `unit, marker` |
| `void` | **`CMLib_UnitMarkerRemove`** | `unit, marker` |
| `int` | **`CMLib_MarkerCastPlayer`** | `marker` |
| `unit` | **`CMLib_MarkerCastUnit`** | `marker` |
| `void` | **`CMLib_MarkerMatchFlag`** | `marker, int, bool` |
| `bool` | **`CMLib_MarkerHasMatchFlag`** | `marker, int` |
| `int` | **`CMLib_OrderPlayer`** | `order` |
| `void` | **`CMLib_OrderSetPlayer`** | `order, int` |
| `unit` | **`CMLib_OrderTargetItem`** | `order` |
| `void` | **`CMLib_OrderSetTargetItem`** | `order, unit` |
| `void` | **`CMLib_OrderSetAbilCmd`** | `order, abilcmd` |
| `void` | **`CMLib_OrderSetFlag`** | `order, int, bool` |
| `void` | **`CMLib_OrderSetPassenger`** | `order, unit` |
| `bool` | **`CMLib_OrderSetPlacement`** | `order, point, unit, string` |
| `order` | **`CMLib_OrderOnItem`** | `abilcmd, unit` |
| `order` | **`CMLib_OrderAtRelative`** | `abilcmd, point` |
| `order` | **`CMLib_OrderOnGroup`** | `abilcmd, unitgroup` |
| `abilcmd` | **`CMLib_AbilCmdFromString`** | `string` |

## cmlib_catalog

> Catalog 运行时读写（单位/武器/效果/行为/技能/按钮）

| 返回 | 函数 | 参数 |
|---|---|---|
| `string` | **`CMLib_CatPathIndex`** | `string, int` |
| `string` | **`CMLib_CatPathIndexSub`** | `string, int, string` |
| `string` | **`CMLib_CatPathSub`** | `string, string` |
| `bool` | **`CMLib_CatEntryExists`** | `int, string` |
| `string` | **`CMLib_CatGetString`** | `int, string, string, int, string` |
| `int` | **`CMLib_CatGetInt`** | `int, string, string, int, int` |
| `fixed` | **`CMLib_CatGetFixed`** | `int, string, string, int, fixed` |
| `int` | **`CMLib_CatArrayCount`** | `int, string, string, int` |
| `bool` | **`CMLib_CatSetString`** | `int, string, string, int, string` |
| `bool` | **`CMLib_CatSetInt`** | `int, string, string, int, int` |
| `bool` | **`CMLib_CatSetFixed`** | `int, string, string, int, fixed` |
| `bool` | **`CMLib_CatModifyInt`** | `int, string, string, int, int, int` |
| `bool` | **`CMLib_CatModifyFixed`** | `int, string, string, int, fixed, int` |
| `bool` | **`CMLib_CatScalePercent`** | `int, string, string, int, int` |
| `fixed` | **`CMLib_UnitDataGetLifeMax`** | `string, int` |
| `fixed` | **`CMLib_UnitDataGetShieldMax`** | `string, int` |
| `fixed` | **`CMLib_UnitDataGetSpeed`** | `string, int` |
| `int` | **`CMLib_UnitDataGetArmor`** | `string, int` |
| `int` | **`CMLib_UnitDataGetSupply`** | `string, int` |
| `bool` | **`CMLib_UnitDataSetLifeMax`** | `string, int, fixed` |
| `bool` | **`CMLib_UnitDataSetShieldMax`** | `string, int, fixed` |
| `bool` | **`CMLib_UnitDataSetSpeed`** | `string, int, fixed` |
| `bool` | **`CMLib_UnitDataAddArmor`** | `string, int, int` |
| `bool` | **`CMLib_UnitDataSetCost`** | `string, int, int, int` |
| `bool` | **`CMLib_UnitDataSetFood`** | `string, int, fixed` |
| `bool` | **`CMLib_UnitDataBoostPercent`** | `string, int, int` |
| `fixed` | **`CMLib_WeaponDataGetRange`** | `string, int` |
| `fixed` | **`CMLib_WeaponDataGetPeriod`** | `string, int` |
| `bool` | **`CMLib_WeaponDataAddRange`** | `string, int, fixed` |
| `bool` | **`CMLib_WeaponDataSpeedUpPercent`** | `string, int, int` |
| `fixed` | **`CMLib_EffectDataGetAmount`** | `string, int` |
| `bool` | **`CMLib_EffectDataSetAmount`** | `string, int, fixed` |
| `bool` | **`CMLib_EffectDataAddAmount`** | `string, int, fixed` |
| `bool` | **`CMLib_EffectDataScalePercent`** | `string, int, int` |
| `fixed` | **`CMLib_BehaviorDataGetDuration`** | `string, int` |
| `bool` | **`CMLib_BehaviorDataSetDuration`** | `string, int, fixed` |
| `bool` | **`CMLib_BehaviorDataSetModFixed`** | `string, int, string, fixed` |
| `bool` | **`CMLib_AbilDataSetCooldown`** | `string, int, int, fixed` |
| `fixed` | **`CMLib_AbilDataGetCooldown`** | `string, int, int` |
| `bool` | **`CMLib_AbilDataSetEnergyCost`** | `string, int, int, fixed` |
| `bool` | **`CMLib_AbilDataSetTrainTime`** | `string, int, string, fixed` |
| `fixed` | **`CMLib_AbilDataGetTrainTime`** | `string, int, string` |
| `bool` | **`CMLib_ButtonDataSetIcon`** | `string, int, string` |
| `string` | **`CMLib_ButtonDataGetIcon`** | `string, int` |
| `int` | **`CMLib_CatCount`** | `int` |
| `string` | **`CMLib_CatEntryAt`** | `int, int` |
| `string` | **`CMLib_CatEntryScope`** | `int, string` |
| `int` | **`CMLib_CatFieldCount`** | `int, string, string, int` |
| `int` | **`CMLib_CatGetIntFast`** | `int, string, string, int` |
| `int` | **`CMLib_CatFindIndex`** | `int, string` |
| `string` | **`CMLib_CatFirstWhere`** | `int, string, string, int` |
| `int` | **`CMLib_CatCountWhere`** | `int, string, string, int` |
| `bool` | **`CMLib_CatLinkSwap`** | `int, int, string, string` |
| `string` | **`CMLib_CatLinkOf`** | `int, int, string` |
| `bool` | **`CMLib_CatFieldExists`** | `string, string` |
| `bool` | **`CMLib_CatRefSet`** | `string, int, string` |
| `bool` | **`CMLib_CatRefModify`** | `string, int, string, int` |
| `bool` | **`CMLib_CatEntryIsDefault`** | `int, string` |
| `int` | **`CMLib_CatEntryClass`** | `int, string` |
| `string` | **`CMLib_CatEntryParent`** | `int, string` |
| `int` | **`CMLib_CatScopeFieldCount`** | `string` |
| `string` | **`CMLib_CatScopeFieldAt`** | `string, int` |
| `bool` | **`CMLib_CatFieldIsArray`** | `string, string` |
| `bool` | **`CMLib_CatFieldIsScope`** | `string, string` |
| `string` | **`CMLib_CatFieldType`** | `string, string` |
| `int` | **`CMLib_CatFieldTypeCat`** | `string, string` |
| `int` | **`CMLib_CatGetFlags`** | `int, string, string, int` |
| `int` | **`CMLib_CatRefCount`** | `string, int` |
| `string` | **`CMLib_CatRefGet`** | `string, int` |
| `int` | **`CMLib_CatRefInt`** | `string, int` |

## cmlib_player

> 玩家判定 / 遍历 / PlayerGroup / 资源 / 联盟 / 科技

| 返回 | 函数 | 参数 |
|---|---|---|
| `void` | **`CMLib_PlayerVisitor_Proto`** | `int, int` |
| `bool` | **`CMLib_PlayerActive`** | `int` |
| `bool` | **`CMLib_PlayerIsHuman`** | `int` |
| `bool` | **`CMLib_PlayerIsComputer`** | `int` |
| `bool` | **`CMLib_PlayerIsEnvironment`** | `int` |
| `int` | **`CMLib_ForEachActivePlayer`** | `CMLib_PlayerVisitor, int` |
| `int` | **`CMLib_ForEachHumanPlayer`** | `CMLib_PlayerVisitor, int` |
| `int` | **`CMLib_ForEachInGroup`** | `playergroup, CMLib_PlayerVisitor, int` |
| `playergroup` | **`CMLib_PGActive`** | `—` |
| `playergroup` | **`CMLib_PGHumans`** | `—` |
| `playergroup` | **`CMLib_PGComputers`** | `—` |
| `playergroup` | **`CMLib_PGSingle`** | `int` |
| `playergroup` | **`CMLib_PGPair`** | `int, int` |
| `playergroup` | **`CMLib_PGAlliesOf`** | `int` |
| `playergroup` | **`CMLib_PGEnemiesOf`** | `int` |
| `int` | **`CMLib_PGCount`** | `playergroup` |
| `bool` | **`CMLib_PGHas`** | `playergroup, int` |
| `int` | **`CMLib_ResGet`** | `int, int` |
| `int` | **`CMLib_ResGetMinerals`** | `int` |
| `int` | **`CMLib_ResGetVespene`** | `int` |
| `int` | **`CMLib_ResAdd`** | `int, int, int` |
| `int` | **`CMLib_ResAddMinerals`** | `int, int` |
| `int` | **`CMLib_ResAddVespene`** | `int, int` |
| `void` | **`CMLib_ResSet`** | `int, int, int` |
| `bool` | **`CMLib_ResTrySpend`** | `int, int, int` |
| `void` | **`CMLib_ResGrantGroup`** | `playergroup, int, int` |
| `int` | **`CMLib_SupplyFree`** | `int` |
| `void` | **`CMLib_AllySetMutual`** | `int, int, int, bool` |
| `void` | **`CMLib_AllyMakeFullAllies`** | `int, int` |
| `void` | **`CMLib_AllyMakeEnemies`** | `int, int` |
| `void` | **`CMLib_AllyGiveVision`** | `int, int, bool` |
| `bool` | **`CMLib_AllyIsAlly`** | `int, int` |
| `int` | **`CMLib_UpgradeLevel`** | `int, string` |
| `bool` | **`CMLib_UpgradeHas`** | `int, string` |
| `int` | **`CMLib_UpgradeEnsureLevel`** | `int, string, int` |
| `int` | **`CMLib_UpgradeGrantGroup`** | `playergroup, string, int` |
| `point` | **`CMLib_PlayerStart`** | `int` |
| `int` | **`CMLib_PlayerDiff`** | `int` |
| `string` | **`CMLib_PlayerRaceOf`** | `int` |
| `playergroup` | **`CMLib_PGCopyOf`** | `playergroup` |
| `playergroup` | **`CMLib_PGAllianceOf`** | `int, int` |
| `text` | **`CMLib_PlayerNameOf`** | `int` |
| `string` | **`CMLib_PlayerHandleOf`** | `int` |
| `int` | **`CMLib_PlayerTypeOf`** | `int` |
| `int` | **`CMLib_PlayerStatusOf`** | `int` |
| `int` | **`CMLib_PlayerPropInt`** | `int, int` |
| `int` | **`CMLib_PlayerColor`** | `int` |
| `void` | **`CMLib_PlayerSetColor`** | `int, int, bool` |
| `bool` | **`CMLib_PlayerTalent`** | `int, string` |
| `fixed` | **`CMLib_PlayerCooldown`** | `int, string` |
| `bool` | **`CMLib_PlayerCooldownReady`** | `int, string` |
| `void` | **`CMLib_PGAdd`** | `playergroup, int` |
| `void` | **`CMLib_PGRemove`** | `playergroup, int` |
| `void` | **`CMLib_PGClear`** | `playergroup` |
| `int` | **`CMLib_PGAt`** | `playergroup, int` |
| `void` | **`CMLib_PlayerEffectAt`** | `int, string, point` |
| `void` | **`CMLib_PlayerEffectOn`** | `int, string, unit` |

## cmlib_ai

> AI 波次编排 / 难度 / 脚本控制

| 返回 | 函数 | 参数 |
|---|---|---|
| `void` | **`CMLib_AIWaveBegin`** | `int, point` |
| `bool` | **`CMLib_AIWaveIsBuilding`** | `—` |
| `int` | **`CMLib_AIWaveEntryCount`** | `—` |
| `void` | **`CMLib_AIWaveAdd`** | `int, string` |
| `void` | **`CMLib_AIWaveAdd4`** | `int, int, int, int, string` |
| `void` | **`CMLib_AIWaveAddRamp`** | `int, int, string` |
| `void` | **`CMLib_AIWaveAddScaled`** | `int, int, int, int, int, string` |
| `void` | **`CMLib_AIWaveAddAtDifficulty`** | `int, int, string` |
| `void` | **`CMLib_AIWaveUseGroup`** | `int, unitgroup` |
| `void` | **`CMLib_AIWaveUseUnit`** | `int, unit` |
| `void` | **`CMLib_AIWaveTargetPlayers`** | `int, playergroup` |
| `void` | **`CMLib_AIWaveTargetPlayer`** | `int, int` |
| `void` | **`CMLib_AIWaveTargetPoint`** | `int, point` |
| `void` | **`CMLib_AIWaveTargetUnit`** | `int, unit` |
| `void` | **`CMLib_AIWaveTargetMelee`** | `int` |
| `void` | **`CMLib_AIWaveWaypoint`** | `int, point, bool` |
| `void` | **`CMLib_AIWaveClearWaypoints`** | `int` |
| `int` | **`CMLib_AIWaveSend`** | `int, int, bool` |
| `int` | **`CMLib_AIWaveSendJittered`** | `int, int, int, bool` |
| `void` | **`CMLib_AIWaveCancelLast`** | `—` |
| `int` | **`CMLib_AIWaveSimple`** | `int, point, string, int, int, int` |
| `void` | **`CMLib_AISetDifficulty`** | `int, int, bool` |
| `int` | **`CMLib_AIPickByDifficulty`** | `int, int, int, int, int` |
| `int` | **`CMLib_AIScaleByDifficulty`** | `int, int, int` |
| `int` | **`CMLib_AICastSelf`** | `unit, string, int` |
| `int` | **`CMLib_AICastAtPoint`** | `unit, string, int, point` |
| `int` | **`CMLib_AICastAtUnit`** | `unit, string, int, unit` |
| `bool` | **`CMLib_AICastIfReady`** | `unit, string, int, string` |
| `void` | **`CMLib_AIBulliesInRegion`** | `int, region, bool` |
| `void` | **`CMLib_AIScriptControl`** | `unit, bool` |
| `void` | **`CMLib_AIScriptControlGroup`** | `unitgroup, bool` |
| `void` | **`CMLib_AIAttackWaveAddUnits`** | `int, int, string` |
| `void` | **`CMLib_AISetFlag`** | `int, int, bool` |
| `fixed` | **`CMLib_AIGetTime`** | `—` |
| `void` | **`CMLib_AICounterUnitSetup`** | `int, string, fixed, string, fixed, string` |
| `int` | **`CMLib_AIState`** | `int, int` |
| `void` | **`CMLib_AIUnitSuicide`** | `unit, bool` |
| `void` | **`CMLib_AIGroupSuicide`** | `unitgroup, bool` |
| `void` | **`CMLib_AIGroupScriptControlled`** | `unitgroup, bool` |
| `void` | **`CMLib_AISubStateChance`** | `int, int` |
| `void` | **`CMLib_AITimePause`** | `bool` |
| `void` | **`CMLib_TechTreeUnitHelp`** | `int, string, bool` |
| `aifilter` | **`CMLib_AIFilterNew`** | `int` |
| `void` | **`CMLib_AIFilterAlliance`** | `aifilter, int` |
| `void` | **`CMLib_AIFilterTypes`** | `aifilter, string` |
| `void` | **`CMLib_AIFilterPlane`** | `aifilter, int` |
| `void` | **`CMLib_AIFilterLife`** | `aifilter, fixed, fixed` |
| `void` | **`CMLib_AIFilterLifePercent`** | `aifilter, fixed, fixed` |
| `void` | **`CMLib_AIFilterLifeLost`** | `aifilter, fixed, fixed` |
| `void` | **`CMLib_AIFilterShields`** | `aifilter, fixed, fixed` |
| `void` | **`CMLib_AIFilterRange`** | `aifilter, unit, fixed` |
| `void` | **`CMLib_AIFilterInCombat`** | `aifilter, bool` |
| `void` | **`CMLib_AIFilterSortByLife`** | `aifilter, fixed, fixed` |
| `void` | **`CMLib_AIFilterExcludeUnit`** | `aifilter, unit` |
| `void` | **`CMLib_AIFilterLifeMod`** | `aifilter, int, fixed` |
| `void` | **`CMLib_AIFilterBehaviorCount`** | `aifilter, int, int, string` |
| `void` | **`CMLib_AIFilterMelee`** | `aifilter, bool` |
| `void` | **`CMLib_AIFilterValidPassenger`** | `aifilter, unit` |
| `void` | **`CMLib_AIFilterMarkerCount`** | `aifilter, int, int, marker` |
| `void` | **`CMLib_AIFilterLifePerMarker`** | `aifilter, fixed, marker` |
| `void` | **`CMLib_AIFilterCanAttackAlly`** | `aifilter, bool, bool` |
| `unitgroup` | **`CMLib_AIFilterApply`** | `aifilter, unitgroup` |
| `int` | **`CMLib_AIFilterApplyCount`** | `aifilter, unitgroup` |
| `unitgroup` | **`CMLib_AISelectEnemies`** | `int, unitgroup` |
| `unitgroup` | **`CMLib_AISelectAllies`** | `int, unitgroup` |
| `unitgroup` | **`CMLib_AISelectInRange`** | `int, unitgroup, unit, fixed` |
| `unitgroup` | **`CMLib_AISelectWounded`** | `int, unitgroup, fixed` |
| `unitgroup` | **`CMLib_AISelectByType`** | `int, unitgroup, string` |
| `unitgroup` | **`CMLib_AISelectGround`** | `int, unitgroup` |
| `unitgroup` | **`CMLib_AISelectAir`** | `int, unitgroup` |
| `unitgroup` | **`CMLib_AIGroupProduction`** | `unitgroup, bool` |
| `unitgroup` | **`CMLib_AIGroupPathable`** | `unitgroup, point` |
| `unitgroup` | **`CMLib_AIGroupCasters`** | `unitgroup` |
| `unitgroup` | **`CMLib_AIGroupGathering`** | `unitgroup, int, fixed` |
| `void` | **`CMLib_AIFilterEnergy`** | `aifilter, fixed, fixed` |

## cmlib_fx

> 音效 / 音乐 / 镜头 / 淡入淡出 / Ping / 飘字 / Actor

| 返回 | 函数 | 参数 |
|---|---|---|
| `soundlink` | **`CMLib_SfxLink`** | `string, int` |
| `void` | **`CMLib_SfxPlay`** | `string, playergroup, fixed` |
| `void` | **`CMLib_SfxPlayAll`** | `string` |
| `void` | **`CMLib_SfxPlayAt`** | `string, playergroup, point, fixed` |
| `void` | **`CMLib_SfxPlayOn`** | `string, playergroup, unit, fixed` |
| `void` | **`CMLib_SfxPlayForPlayer`** | `string, int, fixed` |
| `fixed` | **`CMLib_SfxLength`** | `string` |
| `void` | **`CMLib_SfxStopLast`** | `bool` |
| `void` | **`CMLib_MusicPlay`** | `playergroup, string, bool` |
| `void` | **`CMLib_MusicStop`** | `playergroup, bool` |
| `void` | **`CMLib_ChannelVolume`** | `playergroup, int, fixed, fixed` |
| `void` | **`CMLib_DuckCombatAudio`** | `playergroup, fixed, fixed` |
| `void` | **`CMLib_CamApply`** | `int, camerainfo, fixed` |
| `void` | **`CMLib_CamApplyGroup`** | `playergroup, camerainfo, fixed` |
| `void` | **`CMLib_CamPanTo`** | `int, point, fixed` |
| `void` | **`CMLib_CamPanToGroup`** | `playergroup, point, fixed` |
| `void` | **`CMLib_CamShake`** | `int, fixed, fixed` |
| `void` | **`CMLib_CamShakeGroup`** | `playergroup, fixed, fixed` |
| `void` | **`CMLib_CamShakeStop`** | `int` |
| `void` | **`CMLib_CamSetValue`** | `int, int, fixed, fixed` |
| `void` | **`CMLib_CamSetDistance`** | `int, fixed, fixed` |
| `void` | **`CMLib_CamLock`** | `playergroup, bool` |
| `void` | **`CMLib_CamReset`** | `int, fixed` |
| `void` | **`CMLib_FadeOut`** | `fixed, bool` |
| `void` | **`CMLib_FadeIn`** | `fixed, bool` |
| `void` | **`CMLib_FadeToColor`** | `color, fixed, bool` |
| `int` | **`CMLib_PingAt`** | `playergroup, point, color, fixed` |
| `int` | **`CMLib_PingOnUnit`** | `playergroup, unit, color, fixed` |
| `int` | **`CMLib_PingAtLabeled`** | `playergroup, point, color, fixed, fixed, text` |
| `void` | **`CMLib_PingKill`** | `int` |
| `void` | **`CMLib_MinimapAlert`** | `playergroup, point, color, fixed` |
| `int` | **`CMLib_FloatText`** | `text, point, playergroup, int, fixed` |
| `int` | **`CMLib_FloatTextOnUnit`** | `text, unit, playergroup, int, fixed, fixed` |
| `int` | **`CMLib_FloatTextRising`** | `text, point, playergroup, int, fixed, fixed` |
| `void` | **`CMLib_FloatTextKill`** | `int` |
| `void` | **`CMLib_ActorMsg`** | `unit, string` |
| `void` | **`CMLib_ActorMsgTo`** | `unit, string, string` |
| `void` | **`CMLib_ActorTint`** | `unit, int, int, int, fixed` |
| `void` | **`CMLib_ActorTintClear`** | `unit, fixed` |
| `void` | **`CMLib_ActorScale`** | `unit, fixed, fixed` |
| `void` | **`CMLib_ActorAnim`** | `unit, string` |
| `void` | **`CMLib_FxAtPoint`** | `int, string, point` |
| `void` | **`CMLib_FxOnUnit`** | `unit, string, unit` |
| `void` | **`CMLib_CamShakePreset`** | `int, string, string, fixed, fixed, fixed` |
| `point` | **`CMLib_CamTarget`** | `int` |
| `void` | **`CMLib_CamSave`** | `int` |
| `void` | **`CMLib_CamRestore`** | `int, fixed, fixed, fixed` |
| `void` | **`CMLib_SfxChannelMute`** | `playergroup, int, bool` |
| `void` | **`CMLib_SfxPlayAtFor`** | `string, int, playergroup, point, fixed` |
| `void` | **`CMLib_SfxPlayOwned`** | `string, int, playergroup, fixed` |
| `void` | **`CMLib_PingShow`** | `int, bool` |
| `void` | **`CMLib_PingMove`** | `int, point` |
| `void` | **`CMLib_PingTint`** | `int, color` |
| `void` | **`CMLib_PingRotate`** | `int, fixed` |
| `void` | **`CMLib_PingModel`** | `int, string` |
| `void` | **`CMLib_PingLifetime`** | `int, fixed` |
| `fixed` | **`CMLib_CamInfoValue`** | `camerainfo, int` |
| `point` | **`CMLib_CamInfoTarget`** | `camerainfo` |
| `void` | **`CMLib_CamBounds`** | `playergroup, region, bool` |
| `void` | **`CMLib_CamFollowGroup`** | `int, unitgroup, bool, bool` |
| `void` | **`CMLib_CamApplyData`** | `playergroup, string` |
| `void` | **`CMLib_MusicPause`** | `playergroup, int, bool, bool` |
| `void` | **`CMLib_MusicDefault`** | `playergroup, int, string, int, int` |
| `void` | **`CMLib_PortraitShow`** | `int, playergroup, bool, bool` |
| `void` | **`CMLib_MovieRecStart`** | `string` |
| `void` | **`CMLib_MovieRecStop`** | `—` |
| `void` | **`CMLib_TextTagShowFor`** | `int, playergroup, bool` |
| `void` | **`CMLib_PreloadModel`** | `string, bool` |
| `void` | **`CMLib_PreloadMovie`** | `string, bool` |
| `void` | **`CMLib_PreloadAsset`** | `string, bool` |
| `void` | **`CMLib_PreloadImage`** | `string, bool` |
| `void` | **`CMLib_PreloadSound`** | `string, bool` |
| `int` | **`CMLib_PreloadCSV`** | `string, string, bool` |
| `void` | **`CMLib_CutscenePlay`** | `int` |
| `bool` | **`CMLib_CutsceneBookmark`** | `int, string` |
| `void` | **`CMLib_SfxWaitFrom`** | `sound, fixed` |
| `void` | **`CMLib_SfxWaitEnd`** | `sound, fixed` |
| `actor` | **`CMLib_ActorFrom`** | `string` |
| `actorscope` | **`CMLib_ActorScopeOfUnit`** | `unit` |
| `actor` | **`CMLib_ActorCreate`** | `actorscope, string, string, string, string` |
| `actor` | **`CMLib_ActorRegionCreate`** | `actorscope, string, region` |
| `void` | **`CMLib_ActorRegionSend`** | `actor, int, string, string, string` |
| `void` | **`CMLib_ActorSendTo`** | `actor, string, string` |
| `sound` | **`CMLib_SfxLastPlayed`** | `—` |
| `camerainfo` | **`CMLib_CamInfoDefault`** | `—` |
| `camerainfo` | **`CMLib_CamInfoFromId`** | `int` |
| `void` | **`CMLib_CineMode`** | `playergroup, bool, fixed` |
| `void` | **`CMLib_CineOverlay`** | `bool, fixed, string, fixed, bool` |
| `void` | **`CMLib_CineDataRun`** | `int, playergroup, bool` |
| `void` | **`CMLib_CineDataStop`** | `—` |

## cmlib_panel

> Dialog 容器 / 计时器窗口 / 任务目标

| 返回 | 函数 | 参数 |
|---|---|---|
| `int` | **`CMLib_PanelCreate`** | `int, int, int, int, int, bool` |
| `int` | **`CMLib_PanelCreateCentered`** | `int, int` |
| `int` | **`CMLib_PanelCreateAnchored`** | `int, int, int, int` |
| `int` | **`CMLib_PanelCreateOverlay`** | `—` |
| `bool` | **`CMLib_PanelValid`** | `int` |
| `void` | **`CMLib_PanelShow`** | `int, playergroup, bool` |
| `void` | **`CMLib_PanelShowAll`** | `int, bool` |
| `void` | **`CMLib_PanelShowFor`** | `int, int, bool` |
| `bool` | **`CMLib_PanelIsVisibleFor`** | `int, int` |
| `void` | **`CMLib_PanelDestroy`** | `int` |
| `void` | **`CMLib_PanelSetBackdrop`** | `int, bool` |
| `void` | **`CMLib_PanelSetFullscreen`** | `int, bool` |
| `void` | **`CMLib_PanelSetTransparency`** | `int, fixed` |
| `void` | **`CMLib_PanelSetRenderPriority`** | `int, int` |
| `void` | **`CMLib_PanelResize`** | `int, int, int` |
| `void` | **`CMLib_PanelMove`** | `int, int, int, int` |
| `int` | **`CMLib_TimerPanelCreate`** | `timer, text, bool` |
| `int` | **`CMLib_TimerPanelStart`** | `fixed, text, playergroup` |
| `void` | **`CMLib_TimerPanelShow`** | `int, playergroup, bool` |
| `void` | **`CMLib_TimerPanelAnchor`** | `int, int, int, int` |
| `void` | **`CMLib_TimerPanelDestroy`** | `int` |
| `int` | **`CMLib_ObjCreate`** | `text, text, bool` |
| `int` | **`CMLib_ObjCreateShown`** | `text, text, bool, playergroup` |
| `void` | **`CMLib_ObjSetState`** | `int, int` |
| `int` | **`CMLib_ObjGetState`** | `int` |
| `void` | **`CMLib_ObjComplete`** | `int` |
| `void` | **`CMLib_ObjFail`** | `int` |
| `void` | **`CMLib_ObjActivate`** | `int` |
| `void` | **`CMLib_ObjHide`** | `int` |
| `bool` | **`CMLib_ObjIsResolved`** | `int` |
| `void` | **`CMLib_ObjShow`** | `int, playergroup, bool` |
| `void` | **`CMLib_ObjDestroy`** | `int` |
| `void` | **`CMLib_ObjRename`** | `int, text` |
| `int` | **`CMLib_ObjLast`** | `—` |
| `void` | **`CMLib_ObjSetPriority`** | `int, int` |
| `int` | **`CMLib_ObjPriority`** | `int` |
| `void` | **`CMLib_ObjSetPrimary`** | `int, bool` |
| `bool` | **`CMLib_ObjIsPrimary`** | `int` |
| `void` | **`CMLib_ObjSetPlayers`** | `int, playergroup` |
| `void` | **`CMLib_ObjSetDesc`** | `int, text` |
| `text` | **`CMLib_ObjDesc`** | `int` |
| `text` | **`CMLib_ObjName`** | `int` |
| `bool` | **`CMLib_ObjVisibleFor`** | `int, int` |
| `void` | **`CMLib_ObjMoveFirst`** | `int` |
| `void` | **`CMLib_ObjMoveLast`** | `int` |
| `void` | **`CMLib_ObjMoveAfter`** | `int, int` |
| `void` | **`CMLib_ObjMoveBefore`** | `int, int` |
| `void` | **`CMLib_ObjDestroyAll`** | `playergroup` |
| `void` | **`CMLib_TWColor`** | `int, int, color, fixed` |
| `void` | **`CMLib_TWFormat`** | `int, text` |
| `void` | **`CMLib_TWImageType`** | `int, int, int` |
| `void` | **`CMLib_TWTitle`** | `int, text` |
| `int` | **`CMLib_ObjCreateForPlayers`** | `text, text, int, bool, playergroup` |
| `playergroup` | **`CMLib_ObjPlayers`** | `int` |
| `void` | **`CMLib_TimerPanelBind`** | `int, timer` |
| `void` | **`CMLib_TimerPanelStyle`** | `int, int, bool` |
| `void` | **`CMLib_TimerPanelMove`** | `int, int, int` |
| `void` | **`CMLib_TimerPanelReset`** | `int` |
| `void` | **`CMLib_TimerPanelGap`** | `int, int` |
| `void` | **`CMLib_TimerPanelHeight`** | `int, int` |
| `void` | **`CMLib_TimerPanelBorder`** | `int, bool` |
| `void` | **`CMLib_TimerPanelProgressBar`** | `int, bool` |
| `void` | **`CMLib_TimerPanelProgressColor`** | `int, color, int` |
| `bool` | **`CMLib_TimerPanelVisible`** | `int, int` |

## cmlib_bank

> Bank 存档（fallback / 脏标记批量落盘 / 版本 / 枚举）

| 返回 | 函数 | 参数 |
|---|---|---|
| `bank` | **`CMLib_BankOpen`** | `string, int` |
| `void` | **`CMLib_BankFlush`** | `bank` |
| `void` | **`CMLib_BankMarkDirty`** | `—` |
| `bool` | **`CMLib_BankIsDirty`** | `—` |
| `void` | **`CMLib_BankFlushIfDirty`** | `bank` |
| `bool` | **`CMLib_BankHas`** | `bank, string, string` |
| `void` | **`CMLib_BankEnsureSection`** | `bank, string` |
| `int` | **`CMLib_BankGetInt`** | `bank, string, string, int` |
| `string` | **`CMLib_BankGetString`** | `bank, string, string, string` |
| `bool` | **`CMLib_BankGetBool`** | `bank, string, string, bool` |
| `fixed` | **`CMLib_BankGetFixed`** | `bank, string, string, fixed` |
| `void` | **`CMLib_BankSetInt`** | `bank, string, string, int` |
| `void` | **`CMLib_BankSetString`** | `bank, string, string, string` |
| `void` | **`CMLib_BankSetBool`** | `bank, string, string, bool` |
| `void` | **`CMLib_BankSetFixed`** | `bank, string, string, fixed` |
| `int` | **`CMLib_BankBump`** | `bank, string, string, int` |
| `int` | **`CMLib_BankKeepMax`** | `bank, string, string, int` |
| `int` | **`CMLib_BankKeepMin`** | `bank, string, string, int` |
| `bool` | **`CMLib_BankUnlockOnce`** | `bank, string, string` |
| `void` | **`CMLib_BankSeedInt`** | `bank, string, string, int` |
| `void` | **`CMLib_BankSeedBool`** | `bank, string, string, bool` |
| `void` | **`CMLib_BankClearKey`** | `bank, string, string` |
| `void` | **`CMLib_BankClearSection`** | `bank, string` |
| `int` | **`CMLib_BankSchemaVersion`** | `bank` |
| `void` | **`CMLib_BankSetSchemaVersion`** | `bank, int` |
| `bank` | **`CMLib_BankLast`** | `—` |
| `bool` | **`CMLib_BankExists`** | `string, int` |
| `void` | **`CMLib_BankRemove`** | `bank` |
| `void` | **`CMLib_BankWait`** | `bank` |
| `void` | **`CMLib_BankOption`** | `bank, int, bool` |
| `bool` | **`CMLib_BankOptionOn`** | `bank, int` |
| `bool` | **`CMLib_BankVerified`** | `bank` |
| `string` | **`CMLib_BankNameOf`** | `bank` |
| `int` | **`CMLib_BankPlayerOf`** | `bank` |
| `bool` | **`CMLib_BankSectionExists`** | `bank, string` |
| `int` | **`CMLib_BankSectionCount`** | `bank` |
| `string` | **`CMLib_BankSectionName`** | `bank, int` |
| `int` | **`CMLib_BankKeyCount`** | `bank, string` |
| `string` | **`CMLib_BankKeyName`** | `bank, string, int` |

## cmlib_geo

> 几何 / 寻路 / 单位自定义值 / 行为查询

| 返回 | 函数 | 参数 |
|---|---|---|
| `point` | **`CMLib_PointOffset`** | `point, fixed, fixed` |
| `fixed` | **`CMLib_PointX`** | `point` |
| `fixed` | **`CMLib_PointY`** | `point` |
| `fixed` | **`CMLib_PointHeight`** | `point` |
| `fixed` | **`CMLib_Distance`** | `point, point` |
| `fixed` | **`CMLib_AngleBetween`** | `point, point` |
| `point` | **`CMLib_PointPolar`** | `point, fixed, fixed` |
| `point` | **`CMLib_PointTowards`** | `point, point, fixed` |
| `point` | **`CMLib_LerpPoint`** | `point, point, fixed` |
| `bool` | **`CMLib_PointPassable`** | `point` |
| `bool` | **`CMLib_PointsConnected`** | `point, point` |
| `point` | **`CMLib_FindPathablePoint`** | `point, fixed` |
| `region` | **`CMLib_RegionCircle`** | `point, fixed` |
| `region` | **`CMLib_RegionRect`** | `fixed, fixed, fixed, fixed` |
| `region` | **`CMLib_RegionEmpty`** | `—` |
| `point` | **`CMLib_RegionCenter`** | `region` |
| `point` | **`CMLib_RegionRandomPoint`** | `region` |
| `bool` | **`CMLib_RegionContains`** | `region, point` |
| `void` | **`CMLib_RegionAddCircle`** | `region, bool, point, fixed` |
| `void` | **`CMLib_RegionAddRect`** | `region, bool, fixed, fixed, fixed, fixed` |
| `point` | **`CMLib_RandomPointInRadius`** | `point, fixed` |
| `fixed` | **`CMLib_UnitGetValue`** | `unit, int` |
| `void` | **`CMLib_UnitSetValue`** | `unit, int, fixed` |
| `int` | **`CMLib_UnitBehaviorCount`** | `unit, string` |
| `bool` | **`CMLib_UnitHasBehavior`** | `unit, string` |
| `fixed` | **`CMLib_PointFacing`** | `point` |
| `void` | **`CMLib_PointSetFacing`** | `point, fixed` |
| `int` | **`CMLib_PathCost`** | `point, point` |
| `void` | **`CMLib_RegionAdd`** | `region, region` |
| `point` | **`CMLib_RegionBoundsMin`** | `region` |
| `point` | **`CMLib_RegionBoundsMax`** | `region` |
| `fixed` | **`CMLib_SinDeg`** | `fixed` |
| `fixed` | **`CMLib_CosDeg`** | `fixed` |
| `fixed` | **`CMLib_NormalizeAngle`** | `fixed` |
| `void` | **`CMLib_PlayableMapSet`** | `region` |
| `fixed` | **`CMLib_TerrainHeight`** | `int, point` |
| `fixed` | **`CMLib_GroundHeight`** | `point` |
| `fixed` | **`CMLib_AirHeight`** | `point` |
| `fixed` | **`CMLib_TerrainHeightDelta`** | `int, point, point` |
| `bool` | **`CMLib_TerrainSameLevel`** | `int, point, point, fixed` |
| `point` | **`CMLib_PointById`** | `int` |
| `point` | **`CMLib_PointByName`** | `string` |
| `point` | **`CMLib_PointLerp`** | `point, point, fixed` |
| `fixed` | **`CMLib_PointCliffLevel`** | `point` |
| `point` | **`CMLib_PointReflect`** | `point, point, fixed` |
| `void` | **`CMLib_PointCopy`** | `point, point` |
| `void` | **`CMLib_PointSetHeight`** | `point, fixed` |
| `bool` | **`CMLib_PointsWithin`** | `point, point, fixed` |
| `void` | **`CMLib_RegionAttach`** | `region, unit, point` |
| `unit` | **`CMLib_RegionAttachUnit`** | `region` |
| `region` | **`CMLib_RegionById`** | `int` |
| `region` | **`CMLib_RegionByName`** | `string` |
| `point` | **`CMLib_RegionOffset`** | `region` |
| `void` | **`CMLib_RegionSetOffset`** | `region, point` |
| `void` | **`CMLib_RegionSetCenter`** | `region, point` |

## cmlib_text

> 本地化文本 / 数值格式化 / 颜色文本 / 单位名

| 返回 | 函数 | 参数 |
|---|---|---|
| `text` | **`CMLib_Loc`** | `string` |
| `void` | **`CMLib_FmtToken`** | `string, string, text` |
| `text` | **`CMLib_FmtAssemble`** | `string` |
| `text` | **`CMLib_Int`** | `int` |
| `text` | **`CMLib_Fixed`** | `fixed, int` |
| `color` | **`CMLib_Color`** | `fixed, fixed, fixed` |
| `color` | **`CMLib_ColorA`** | `fixed, fixed, fixed, fixed` |
| `text` | **`CMLib_TextColored`** | `text, color` |
| `text` | **`CMLib_TextRed`** | `text` |
| `text` | **`CMLib_TextGreen`** | `text` |
| `text` | **`CMLib_TextBlue`** | `text` |
| `text` | **`CMLib_TextYellow`** | `text` |
| `text` | **`CMLib_TextOrange`** | `text` |
| `text` | **`CMLib_TextWhite`** | `text` |
| `text` | **`CMLib_TextGray`** | `text` |
| `text` | **`CMLib_UnitName`** | `unit` |
| `text` | **`CMLib_TimeText`** | `text, int` |
| `text` | **`CMLib_TextReplace`** | `text, text, text, int, bool` |

## cmlib_trig

> 触发器编排 / 事件挂载 / 等待与计时 / 事件取参

| 返回 | 函数 | 参数 |
|---|---|---|
| `trigger` | **`CMLib_TrigNew`** | `string, string` |
| `trigger` | **`CMLib_TrigNewDisabled`** | `string, string` |
| `void` | **`CMLib_TrigRegister`** | `trigger, string, string` |
| `void` | **`CMLib_TrigUnregister`** | `trigger` |
| `int` | **`CMLib_TrigCount`** | `—` |
| `int` | **`CMLib_TrigCountByTag`** | `string` |
| `trigger` | **`CMLib_TrigFind`** | `string` |
| `bool` | **`CMLib_TrigIsRegistered`** | `trigger` |
| `bool` | **`CMLib_TrigEnabled`** | `trigger` |
| `void` | **`CMLib_TrigOn`** | `trigger` |
| `void` | **`CMLib_TrigOff`** | `trigger` |
| `void` | **`CMLib_TrigSet`** | `trigger, bool` |
| `void` | **`CMLib_TrigKill`** | `trigger` |
| `int` | **`CMLib_TrigTagOn`** | `string` |
| `int` | **`CMLib_TrigTagOff`** | `string` |
| `int` | **`CMLib_TrigTagKill`** | `string` |
| `void` | **`CMLib_TrigRun`** | `trigger` |
| `void` | **`CMLib_TrigRunNow`** | `trigger` |
| `void` | **`CMLib_TrigForce`** | `trigger` |
| `void` | **`CMLib_TrigForceNow`** | `trigger` |
| `bool` | **`CMLib_TrigTest`** | `trigger` |
| `void` | **`CMLib_TrigStopSelf`** | `—` |
| `void` | **`CMLib_TrigQueueBegin`** | `—` |
| `void` | **`CMLib_TrigQueueEnd`** | `—` |
| `int` | **`CMLib_TrigQueueDepth`** | `—` |
| `bool` | **`CMLib_TrigQueueIsEmpty`** | `—` |
| `void` | **`CMLib_TrigQueuePause`** | `bool` |
| `void` | **`CMLib_TrigOnMapInit`** | `trigger` |
| `void` | **`CMLib_TrigOnElapsed`** | `trigger, fixed` |
| `void` | **`CMLib_TrigOnPeriod`** | `trigger, fixed` |
| `void` | **`CMLib_TrigOnPeriodReal`** | `trigger, fixed` |
| `void` | **`CMLib_TrigOnTimer`** | `trigger, timer` |
| `void` | **`CMLib_TrigOnUnitDied`** | `trigger, unit` |
| `void` | **`CMLib_TrigOnUnitAttacked`** | `trigger, unit` |
| `void` | **`CMLib_TrigOnUnitChangeOwner`** | `trigger, unit` |
| `void` | **`CMLib_TrigOnUnitGainLevel`** | `trigger, unit` |
| `void` | **`CMLib_TrigOnUnitCreated`** | `trigger, unit, string, string` |
| `void` | **`CMLib_TrigOnUnitDamaged`** | `trigger, unit, string` |
| `void` | **`CMLib_TrigOnUnitIdle`** | `trigger, unit, bool` |
| `void` | **`CMLib_TrigOnUnitRegion`** | `trigger, unit, region, bool` |
| `void` | **`CMLib_TrigOnUnitRegionBoth`** | `trigger, unit, region` |
| `void` | **`CMLib_TrigOnUnitRange`** | `trigger, unit, unit, fixed, bool` |
| `void` | **`CMLib_TrigOnUnitRangePoint`** | `trigger, unit, point, fixed, bool` |
| `void` | **`CMLib_TrigOnUnitCargo`** | `trigger, unit, bool` |
| `void` | **`CMLib_TrigOnUnitSelected`** | `trigger, unit, int, bool` |
| `void` | **`CMLib_TrigOnUnitClicked`** | `trigger, unit, int` |
| `void` | **`CMLib_TrigOnUnitHighlight`** | `trigger, unit, int, bool` |
| `void` | **`CMLib_TrigOnUnitAbility`** | `trigger, unit, abilcmd, int, bool` |
| `void` | **`CMLib_TrigOnUnitAbilityUsed`** | `trigger, unit, abilcmd` |
| `void` | **`CMLib_TrigOnUnitAutoCast`** | `trigger, unit, abilcmd, int, bool` |
| `void` | **`CMLib_TrigOnUnitOrder`** | `trigger, unit, abilcmd` |
| `void` | **`CMLib_TrigOnUnitProperty`** | `trigger, unit, int` |
| `void` | **`CMLib_TrigOnUnitBehavior`** | `trigger, unit, string, int` |
| `string` | **`CMLib_EvtBehavior`** | `—` |
| `void` | **`CMLib_TrigOnConstructProgress`** | `trigger, unit, int` |
| `void` | **`CMLib_TrigOnTrainProgress`** | `trigger, unit, int` |
| `void` | **`CMLib_TrigOnResearchProgress`** | `trigger, unit, int` |
| `void` | **`CMLib_TrigOnReviveProgress`** | `trigger, unit, int` |
| `void` | **`CMLib_TrigOnLearnProgress`** | `trigger, unit, int` |
| `void` | **`CMLib_TrigOnSpecializeProgress`** | `trigger, unit, int` |
| `void` | **`CMLib_TrigOnArmMagazineProgress`** | `trigger, unit, int` |
| `void` | **`CMLib_TrigOnBuildingDone`** | `trigger, unit` |
| `void` | **`CMLib_TrigOnTrainDone`** | `trigger, unit` |
| `void` | **`CMLib_TrigOnResearchDone`** | `trigger, unit` |
| `void` | **`CMLib_TrigOnUnitRevive`** | `trigger, unit` |
| `void` | **`CMLib_TrigOnUnitPowerup`** | `trigger, unit` |
| `void` | **`CMLib_TrigOnEffectUsed`** | `trigger, int, string` |
| `void` | **`CMLib_TrigOnEffectScope`** | `trigger, int, string` |
| `unit` | **`CMLib_EvtEffectCaster`** | `—` |
| `unit` | **`CMLib_EvtEffectTarget`** | `—` |
| `void` | **`CMLib_TrigOnDialogControl`** | `trigger, int, int, int` |
| `void` | **`CMLib_TrigOnButtonClick`** | `trigger, int` |
| `region` | **`CMLib_EvtRegion`** | `—` |
| `unit` | **`CMLib_EvtRangeUnit`** | `—` |
| `unit` | **`CMLib_EvtCargoUnit`** | `—` |
| `abilcmd` | **`CMLib_EvtAbility`** | `—` |
| `int` | **`CMLib_EvtAbilityStage`** | `—` |
| `unit` | **`CMLib_EvtAbilityOtherUnit`** | `—` |
| `string` | **`CMLib_EvtProgressType`** | `—` |
| `unit` | **`CMLib_EvtProgressUnit`** | `—` |
| `string` | **`CMLib_EvtEffect`** | `—` |
| `unit` | **`CMLib_EvtEffectUnit`** | `int` |
| `point` | **`CMLib_EvtEffectPoint`** | `int` |
| `int` | **`CMLib_EvtControl`** | `—` |
| `int` | **`CMLib_EvtControlEventType`** | `—` |
| `bool` | **`CMLib_EvtIsControl`** | `int` |
| `void` | **`CMLib_TrigOnPlayerLeft`** | `trigger, int, int` |
| `void` | **`CMLib_TrigOnAllianceChange`** | `trigger, int` |
| `void` | **`CMLib_TrigOnAIWave`** | `trigger, int` |
| `void` | **`CMLib_TrigOnChat`** | `trigger, int, string, bool` |
| `void` | **`CMLib_TrigOnGeneric`** | `trigger, string` |
| `void` | **`CMLib_TrigSend`** | `string` |
| `int` | **`CMLib_EvtPlayer`** | `—` |
| `unit` | **`CMLib_EvtUnit`** | `—` |
| `unit` | **`CMLib_EvtTargetUnit`** | `—` |
| `string` | **`CMLib_EvtChat`** | `bool` |
| `void` | **`CMLib_TrigArgSetInt`** | `string, int` |
| `int` | **`CMLib_TrigArgGetInt`** | `string, int` |
| `void` | **`CMLib_TrigArgSetFixed`** | `string, fixed` |
| `fixed` | **`CMLib_TrigArgGetFixed`** | `string, fixed` |
| `void` | **`CMLib_TrigArgSetString`** | `string, string` |
| `string` | **`CMLib_TrigArgGetString`** | `string, string` |
| `void` | **`CMLib_TrigArgSetUnit`** | `string, unit` |
| `unit` | **`CMLib_TrigArgGetUnit`** | `string` |
| `void` | **`CMLib_TrigCallInt`** | `trigger, string, int` |
| `void` | **`CMLib_WaitGame`** | `fixed` |
| `void` | **`CMLib_WaitReal`** | `fixed` |
| `void` | **`CMLib_WaitAI`** | `fixed` |
| `void` | **`CMLib_Yield`** | `—` |
| `timer` | **`CMLib_TimerOnce`** | `fixed` |
| `timer` | **`CMLib_TimerLoop`** | `fixed` |
| `fixed` | **`CMLib_TimerLeft`** | `timer` |
| `fixed` | **`CMLib_TimerElapsed`** | `timer` |
| `void` | **`CMLib_TimerHold`** | `timer, bool` |
| `void` | **`CMLib_TimerReset`** | `timer` |
| `void` | **`CMLib_TrigDumpState`** | `—` |
| `void` | **`CMLib_TriggerQueueClear`** | `int` |
| `int` | **`CMLib_TrigExecCount`** | `trigger` |
| `unit` | **`CMLib_EvtCreatedUnit`** | `—` |
| `int` | **`CMLib_EvtDmgSourcePlayer`** | `—` |
| `unit` | **`CMLib_EvtDmgSourceUnit`** | `—` |
| `int` | **`CMLib_EvtEffectUsedUnitOwner`** | `int` |
| `trigger` | **`CMLib_TrigFindByFunc`** | `string` |
| `void` | **`CMLib_TrigOnPlayerPropChange`** | `trigger, int, int` |
| `string` | **`CMLib_EvtUpgradeName`** | `—` |
| `fixed` | **`CMLib_EvtDamageAmount`** | `—` |
| `string` | **`CMLib_TrigEventParamName`** | `string, string` |
| `void` | **`CMLib_OnKeyPressed`** | `trigger, int, int, bool` |
| `void` | **`CMLib_OnKeyPressedMod`** | `trigger, int, int, bool, int, int, int` |
| `void` | **`CMLib_OnButtonPressed`** | `trigger, int, string` |
| `void` | **`CMLib_OnUpgradeLevelChanged`** | `trigger, int` |
| `void` | **`CMLib_OnBehaviorCategoryChange`** | `trigger, unitref, int, int` |
| `string` | **`CMLib_EvtDamageEffect`** | `—` |
| `order` | **`CMLib_EvtOrder`** | `—` |
| `unit` | **`CMLib_EvtTarget`** | `—` |
| `point` | **`CMLib_EvtTargetPoint`** | `—` |
| `timer` | **`CMLib_EvtTimer`** | `—` |
| `wave` | **`CMLib_EvtWave`** | `—` |
| `int` | **`CMLib_EvtKey`** | `—` |
| `bool` | **`CMLib_EvtKeyShift`** | `—` |
| `bool` | **`CMLib_EvtKeyCtrl`** | `—` |
| `bool` | **`CMLib_EvtKeyAlt`** | `—` |
| `string` | **`CMLib_EvtButton`** | `—` |
| `void` | **`CMLib_SkippableBegin`** | `playergroup, int, trigger, bool, bool` |
| `void` | **`CMLib_SkippableEnd`** | `—` |
| `timer` | **`CMLib_TimerLastStarted`** | `—` |

## cmlib_game

> 游戏状态 / 胜负 / 视野迷雾 / 揭示器 / 蔓延 / 时间

| 返回 | 函数 | 参数 |
|---|---|---|
| `fixed` | **`CMLib_GameMissionTime`** | `—` |
| `int` | **`CMLib_GameMissionMinutes`** | `—` |
| `int` | **`CMLib_GameMissionSeconds`** | `—` |
| `void` | **`CMLib_GameMissionTimePause`** | `bool` |
| `bool` | **`CMLib_GameMissionTimeIsPaused`** | `—` |
| `fixed` | **`CMLib_GameMissionTimeRemaining`** | `fixed` |
| `bool` | **`CMLib_GameMissionTimePassed`** | `fixed` |
| `void` | **`CMLib_GameSpeedSet`** | `int` |
| `int` | **`CMLib_GameSpeedGet`** | `—` |
| `void` | **`CMLib_GameSpeedLock`** | `bool` |
| `void` | **`CMLib_GameTimeScaleSet`** | `fixed` |
| `fixed` | **`CMLib_GameTimeScaleGet`** | `—` |
| `void` | **`CMLib_GameSlowMotion`** | `fixed, fixed` |
| `string` | **`CMLib_GameTimeOfDayGet`** | `—` |
| `void` | **`CMLib_GameTimeOfDaySet`** | `string` |
| `void` | **`CMLib_GameTimeOfDayPause`** | `bool` |
| `bool` | **`CMLib_GameTimeOfDayIsPaused`** | `—` |
| `void` | **`CMLib_GameTimeOfDayLength`** | `fixed` |
| `void` | **`CMLib_GameLightingSet`** | `string, fixed` |
| `void` | **`CMLib_GameLockAmbience`** | `string, string` |
| `void` | **`CMLib_GameEndForPlayer`** | `int, int, bool, bool` |
| `void` | **`CMLib_GameEndForPlayers`** | `playergroup, int, bool, bool` |
| `void` | **`CMLib_GameVictory`** | `int` |
| `void` | **`CMLib_GameDefeat`** | `int` |
| `void` | **`CMLib_GameEndAllActive`** | `int` |
| `bool` | **`CMLib_GameCheatsOn`** | `int` |
| `bool` | **`CMLib_GameDevMode`** | `—` |
| `bool` | **`CMLib_GameDebugAllowed`** | `string, int` |
| `void` | **`CMLib_VisReveal`** | `int, region, fixed` |
| `void` | **`CMLib_VisRevealPermanent`** | `int, region` |
| `void` | **`CMLib_VisExplore`** | `int, region, bool` |
| `void` | **`CMLib_VisHide`** | `int, region` |
| `void` | **`CMLib_VisRevealForPlayers`** | `playergroup, region, fixed` |
| `bool` | **`CMLib_VisIsVisible`** | `int, point` |
| `void` | **`CMLib_VisFogEnable`** | `bool` |
| `void` | **`CMLib_VisMaskEnable`** | `bool` |
| `void` | **`CMLib_VisRevealMapForPlayer`** | `int` |
| `revealer` | **`CMLib_RevealerCreate`** | `int, region` |
| `void` | **`CMLib_RevealerEnable`** | `revealer, bool` |
| `void` | **`CMLib_RevealerDestroy`** | `revealer` |
| `void` | **`CMLib_RevealerRefresh`** | `revealer` |
| `void` | **`CMLib_CreepAdd`** | `point, fixed, bool` |
| `void` | **`CMLib_CreepRemove`** | `point, fixed` |
| `bool` | **`CMLib_CreepAt`** | `point` |
| `void` | **`CMLib_CreepSpeedSet`** | `int, fixed` |
| `void` | **`CMLib_GameBackground`** | `int, string, fixed` |
| `void` | **`CMLib_GameCheat`** | `int, bool` |
| `bool` | **`CMLib_GameOnline`** | `—` |
| `bool` | **`CMLib_GameTestMap`** | `bool` |

## cmlib_conv

> 过场对白（Transmission / Conversation）

| 返回 | 函数 | 参数 |
|---|---|---|
| `transmissionsource` | **`CMLib_TransFromUnit`** | `unit, bool` |
| `transmissionsource` | **`CMLib_TransFromUnitType`** | `string` |
| `transmissionsource` | **`CMLib_TransFromModel`** | `string` |
| `transmissionsource` | **`CMLib_TransFromMovie`** | `string, bool` |
| `transmissionsource` | **`CMLib_TransNone`** | `—` |
| `int` | **`CMLib_TransSay`** | `playergroup, transmissionsource, soundlink, text, text, bool` |
| `int` | **`CMLib_TransSayTimed`** | `playergroup, transmissionsource, soundlink, text, text, fixed, int, bool` |
| `int` | **`CMLib_TransSayToPlayer`** | `int, transmissionsource, soundlink, text, text, bool` |
| `int` | **`CMLib_TransSubtitle`** | `playergroup, text, fixed, bool` |
| `int` | **`CMLib_TransUnitSay`** | `playergroup, unit, soundlink, text, text, bool` |
| `int` | **`CMLib_TransLast`** | `—` |
| `void` | **`CMLib_TransWait`** | `int, fixed` |
| `void` | **`CMLib_TransWaitLast`** | `fixed` |
| `bool` | **`CMLib_TransIsDone`** | `int` |
| `void` | **`CMLib_TransClear`** | `int` |
| `void` | **`CMLib_TransClearAll`** | `—` |
| `void` | **`CMLib_TransClearFor`** | `playergroup` |
| `bool` | **`CMLib_TransPlayerBusy`** | `int` |
| `void` | **`CMLib_TransSequence2`** | `playergroup, transmissionsource, soundlink, text, text, transmissionsource, soundlink, text, text` |
| `int` | **`CMLib_ConvCreate`** | `bool` |
| `int` | **`CMLib_ConvLast`** | `—` |
| `void` | **`CMLib_ConvShow`** | `int, playergroup, bool` |
| `void` | **`CMLib_ConvDestroy`** | `int` |
| `void` | **`CMLib_ConvDestroyAll`** | `—` |
| `bool` | **`CMLib_ConvVisibleFor`** | `int, int` |
| `int` | **`CMLib_ConvReplyAdd`** | `int, text` |
| `void` | **`CMLib_ConvReplySetText`** | `int, int, text` |
| `void` | **`CMLib_ConvReplySetState`** | `int, int, int` |
| `int` | **`CMLib_ConvReplyState`** | `int, int` |
| `void` | **`CMLib_ConvReplyClear`** | `int` |
| `void` | **`CMLib_ConvBindUnit`** | `string, unit` |
| `void` | **`CMLib_ConvBindPortrait`** | `string, int` |
| `int` | **`CMLib_ConvStateCount`** | `string` |
| `string` | **`CMLib_ConvStateAt`** | `string, int` |
| `text` | **`CMLib_ConvStateName`** | `string` |
| `void` | **`CMLib_ConvDataRun`** | `string, playergroup, int, bool` |
| `void` | **`CMLib_ConvDataRunAll`** | `string` |
| `void` | **`CMLib_ConvDataStop`** | `—` |
| `bool` | **`CMLib_ConvDataCanRun`** | `string, bool` |
| `string` | **`CMLib_ConvDataSound`** | `string, bool` |
| `void` | **`CMLib_ConvDataLinePlayers`** | `string, string, playergroup` |
| `void` | **`CMLib_ConvDataLineReset`** | `string, string` |
| `void` | **`CMLib_ConvDataCamera`** | `string, string, camerainfo, trigger, bool` |
| `void` | **`CMLib_ConvDataStateSet`** | `string, int` |
| `int` | **`CMLib_ConvDataStateGet`** | `string` |
| `text` | **`CMLib_ConvDataStateTextOf`** | `string, string` |
| `void` | **`CMLib_ConvDataPreload`** | `string` |
| `int` | **`CMLib_ConvDataPreloadBatch`** | `string` |
| `fixed` | **`CMLib_ConvDataStateFixed`** | `string, string` |
| `string` | **`CMLib_ConvDataActiveSound`** | `—` |
| `void` | **`CMLib_ConvDataSaveNodes`** | `string, bank, string` |
| `void` | **`CMLib_ConvDataLoadNodes`** | `string, bank, string` |
| `void` | **`CMLib_ConvDataResetStates`** | `string` |
| `int` | **`CMLib_TransSendForPlayerSelect`** | `playergroup, transmissionsource, int, string, string, soundlink, text, text, fixed, int, bool, int, bool` |
| `void` | **`CMLib_TransSetOption`** | `int, bool` |
| `void` | **`CMLib_TransHideAlertPanel`** | `bool` |
| `void` | **`CMLib_TransSourceBypassLog`** | `transmissionsource, bool` |
| `void` | **`CMLib_TransSourcePauseAllowed`** | `transmissionsource, bool` |
| `void` | **`CMLib_TransSourceStreaming`** | `transmissionsource, bool` |

## cmlib_udata

> 数据编辑器 User Data 表读写

| 返回 | 函数 | 参数 |
|---|---|---|
| `int` | **`CMLib_UDataCount`** | `string` |
| `string` | **`CMLib_UDataAt`** | `string, int` |
| `bool` | **`CMLib_UDataHas`** | `string, string` |
| `int` | **`CMLib_UDataIndexOf`** | `string, string` |
| `int` | **`CMLib_UDataFieldCount`** | `string` |
| `string` | **`CMLib_UDataFieldAt`** | `string, int` |
| `bool` | **`CMLib_UDataFieldExists`** | `string, string` |
| `int` | **`CMLib_UDataFieldValues`** | `string, string` |
| `bool` | **`CMLib_UDataFieldWritable`** | `string, string` |
| `int` | **`CMLib_UDataInt`** | `string, string, string, int` |
| `fixed` | **`CMLib_UDataFixed`** | `string, string, string, fixed` |
| `string` | **`CMLib_UDataString`** | `string, string, string, string` |
| `text` | **`CMLib_UDataText`** | `string, string, string` |
| `string` | **`CMLib_UDataGameLink`** | `string, string, string` |
| `string` | **`CMLib_UDataUnit`** | `string, string, string` |
| `int` | **`CMLib_UDataIntAt`** | `string, string, string, int, int` |
| `fixed` | **`CMLib_UDataFixedAt`** | `string, string, string, int, fixed` |
| `string` | **`CMLib_UDataStringAt`** | `string, string, string, int, string` |
| `void` | **`CMLib_UDataSetInt`** | `string, string, string, int` |
| `void` | **`CMLib_UDataSetFixed`** | `string, string, string, fixed` |
| `void` | **`CMLib_UDataSetString`** | `string, string, string, string` |
| `void` | **`CMLib_UDataSetIntAt`** | `string, string, string, int, int` |
| `int` | **`CMLib_UDataSumInt`** | `string, string` |
| `int` | **`CMLib_UDataMaxInt`** | `string, string` |
| `string` | **`CMLib_UDataFindByInt`** | `string, string, int` |
| `string` | **`CMLib_UDataFindByString`** | `string, string, string` |
| `string` | **`CMLib_UDataUserInstance`** | `string, string, string, int` |
| `string` | **`CMLib_UDataImagePath`** | `string, string, string, int` |
| `void` | **`CMLib_UDataResetType`** | `string` |
| `string` | **`CMLib_UDataUpgrade`** | `string, string, string, int` |
| `string` | **`CMLib_UDataUpgrade0`** | `string, string, string` |

## cmlib_stock

> 电脑 AI 库存 / 科技树 / AI 用户变量

| 返回 | 函数 | 参数 |
|---|---|---|
| `void` | **`CMLib_StockSet`** | `int, int, string` |
| `void` | **`CMLib_StockAdd`** | `int, int, string` |
| `void` | **`CMLib_StockSetOpt`** | `int, int, string` |
| `void` | **`CMLib_StockSetAtTown`** | `int, int, int, string` |
| `void` | **`CMLib_StockNextIf`** | `int, int, string, bool` |
| `void` | **`CMLib_StockExtra`** | `int, int, string, int` |
| `void` | **`CMLib_StockSupply`** | `int, string, bool` |
| `void` | **`CMLib_StockWorkers`** | `int, int, string` |
| `void` | **`CMLib_StockTechNext`** | `int` |
| `bool` | **`CMLib_StockTown`** | `int, string, string` |
| `bool` | **`CMLib_StockExpand`** | `int, string, int` |
| `void` | **`CMLib_StockArmyAdd`** | `int, string, int` |
| `void` | **`CMLib_StockArmyScale`** | `int, fixed` |
| `void` | **`CMLib_StockArmyReplace`** | `int, string, int, string` |
| `void` | **`CMLib_StockArmyBatch`** | `int, string` |
| `int` | **`CMLib_TechCount`** | `int, string, int` |
| `int` | **`CMLib_TechBuilt`** | `int, string` |
| `int` | **`CMLib_TechPending`** | `int, string` |
| `bool` | **`CMLib_TechHas`** | `int, string, int` |
| `void` | **`CMLib_TechUnitAllow`** | `int, string, bool` |
| `bool` | **`CMLib_TechUnitAllowed`** | `int, string` |
| `int` | **`CMLib_TechUnitCount`** | `int, string, int` |
| `void` | **`CMLib_TechUpgradeAllow`** | `int, string, bool` |
| `bool` | **`CMLib_TechUpgradeAllowed`** | `int, string` |
| `int` | **`CMLib_TechUpgradeLevel`** | `int, string` |
| `void` | **`CMLib_TechUpgradeGrant`** | `int, string, int` |
| `void` | **`CMLib_TechAbilityAllow`** | `int, abilcmd, bool` |
| `bool` | **`CMLib_TechAbilityAllowed`** | `int, abilcmd` |
| `void` | **`CMLib_TechBehaviorAllow`** | `int, string, bool` |
| `void` | **`CMLib_TechUnitAllowBatch`** | `int, string, bool` |
| `void` | **`CMLib_TechRequirementsEnable`** | `int, bool` |
| `void` | **`CMLib_TechRestrictionsEnable`** | `int, bool` |
| `void` | **`CMLib_TechRequirementEnable`** | `int, string, bool` |
| `void` | **`CMLib_TechUnlockAll`** | `int` |
| `void` | **`CMLib_TechRestoreRules`** | `int` |
| `void` | **`CMLib_AIVarSet`** | `int, int, int` |
| `int` | **`CMLib_AIVarGet`** | `int, int` |
| `int` | **`CMLib_AIVarBump`** | `int, int, int` |
| `void` | **`CMLib_AIEnableStock`** | `int` |
| `void` | **`CMLib_AIClearStock`** | `int` |
| `void` | **`CMLib_StockAlias`** | `int, int, string, string` |
| `void` | **`CMLib_StockFree`** | `int, int, string, string` |
| `void` | **`CMLib_StockTechUncap`** | `int, int, int` |

## cmlib_board

> 排行榜面板（Board）/ 任务结算面板（VictoryPanel）

| 返回 | 函数 | 参数 |
|---|---|---|
| `int` | **`CMLib_BoardCreate`** | `int, int, string` |
| `int` | **`CMLib_BoardCreateColored`** | `int, int, string, fixed, fixed, fixed` |
| `int` | **`CMLib_BoardQuick`** | `string, string, playergroup` |
| `bool` | **`CMLib_BoardValid`** | `int` |
| `void` | **`CMLib_BoardDestroy`** | `int` |
| `void` | **`CMLib_BoardShow`** | `int, playergroup, bool` |
| `void` | **`CMLib_BoardShowAll`** | `int, bool` |
| `void` | **`CMLib_BoardAnchor`** | `int, int, int, int` |
| `void` | **`CMLib_BoardAnchorTopRight`** | `int, int, int` |
| `void` | **`CMLib_BoardAnchorTopLeft`** | `int, int, int` |
| `void` | **`CMLib_BoardAnchorTop`** | `int, int, int` |
| `void` | **`CMLib_BoardResetPosition`** | `int` |
| `void` | **`CMLib_BoardResize`** | `int, int, int` |
| `void` | **`CMLib_BoardColumnWidth`** | `int, int, fixed` |
| `void` | **`CMLib_BoardTitle`** | `int, string, string, bool` |
| `void` | **`CMLib_BoardTitleShow`** | `int, playergroup, bool` |
| `void` | **`CMLib_BoardTitleColor`** | `int, fixed, fixed, fixed` |
| `void` | **`CMLib_BoardCell`** | `int, int, int, string` |
| `void` | **`CMLib_BoardCellInt`** | `int, int, int, int` |
| `void` | **`CMLib_BoardCellFixed`** | `int, int, int, fixed, int` |
| `void` | **`CMLib_BoardCellColor`** | `int, int, int, fixed, fixed, fixed` |
| `void` | **`CMLib_BoardCellBackColor`** | `int, int, int, fixed, fixed, fixed` |
| `void` | **`CMLib_BoardCellIcon`** | `int, int, int, string, bool` |
| `void` | **`CMLib_BoardCellAlign`** | `int, int, int, int` |
| `void` | **`CMLib_BoardCellFontSize`** | `int, int, int, int` |
| `void` | **`CMLib_BoardCellProgress`** | `int, int, int, fixed, fixed, fixed, fixed, fixed, fixed` |
| `void` | **`CMLib_BoardCellProgressHide`** | `int, int, int` |
| `void` | **`CMLib_BoardHeaders`** | `int, string` |
| `void` | **`CMLib_BoardRow`** | `int, int, string` |
| `void` | **`CMLib_BoardRowInt`** | `int, int, string` |
| `void` | **`CMLib_BoardRowClear`** | `int, int` |
| `void` | **`CMLib_BoardPlayerColumn`** | `int, int, bool` |
| `void` | **`CMLib_BoardPlayersAdd`** | `int, playergroup` |
| `void` | **`CMLib_BoardPlayersRemove`** | `int, playergroup` |
| `void` | **`CMLib_BoardPlayersAddActive`** | `int` |
| `void` | **`CMLib_BoardSort`** | `int, int, bool` |
| `void` | **`CMLib_BoardSortSecondary`** | `int, int, bool` |
| `void` | **`CMLib_BoardSetState`** | `int, playergroup, int, bool` |
| `void` | **`CMLib_BoardMinimizable`** | `int, playergroup, bool` |
| `void` | **`CMLib_BoardMinimize`** | `int, playergroup, bool` |
| `void` | **`CMLib_VPanelVictoryText`** | `string` |
| `void` | **`CMLib_VPanelMission`** | `string, string` |
| `void` | **`CMLib_VPanelTime`** | `string, string` |
| `void` | **`CMLib_VPanelReward`** | `string, string, int` |
| `void` | **`CMLib_VPanelStatisticsTitle`** | `string` |
| `void` | **`CMLib_VPanelAchievementsTitle`** | `string` |
| `void` | **`CMLib_VPanelStat`** | `string, string` |
| `void` | **`CMLib_VPanelStatInt`** | `string, int` |
| `void` | **`CMLib_VPanelStatFixed`** | `string, fixed, int` |
| `void` | **`CMLib_VPanelStatBatch`** | `string` |
| `void` | **`CMLib_VPanelStatClear`** | `—` |
| `void` | **`CMLib_VPanelTracked`** | `string` |
| `void` | **`CMLib_VPanelTrackedBatch`** | `string` |
| `void` | **`CMLib_VPanelVisuals`** | `string, string, string` |
| `void` | **`CMLib_VPanelOnExit`** | `trigger, int` |
| `void` | **`CMLib_VPanelOnPlayAgain`** | `trigger, int` |
| `int` | **`CMLib_VPanelPickedDifficulty`** | `—` |
| `void` | **`CMLib_VPanelAchievement`** | `string` |
| `void` | **`CMLib_VPanelAchievementBatch`** | `string` |
| `void` | **`CMLib_BoardRowGroup`** | `int, int, int` |
| `void` | **`CMLib_BoardGroupCount`** | `int, int` |
| `void` | **`CMLib_BoardPosition`** | `int, int, int` |
| `void` | **`CMLib_BoardTitleAlign`** | `int, int, int` |
| `void` | **`CMLib_BoardName`** | `int, text, color` |
| `void` | **`CMLib_BoardMinimizeColor`** | `int, color` |
| `void` | **`CMLib_VPanelCustomStatisticText`** | `text` |
| `void` | **`CMLib_VPanelCustomStatisticValue`** | `text` |
| `void` | **`CMLib_VPanelCustomStatisticInt`** | `text, int` |

## cmlib_buff

> Behavior 增益减益 / 单位状态开关 / 玩家状态开关

| 返回 | 函数 | 参数 |
|---|---|---|
| `bool` | **`CMLib_BuffAdd`** | `unit, string, unit, int` |
| `int` | **`CMLib_BuffRemove`** | `unit, string, int` |
| `int` | **`CMLib_BuffSetCount`** | `unit, string, unit, int` |
| `int` | **`CMLib_BuffStripAll`** | `unit, string` |
| `int` | **`CMLib_BuffCount`** | `unit, string` |
| `bool` | **`CMLib_BuffHas`** | `unit, string` |
| `int` | **`CMLib_BuffCountAll`** | `unit` |
| `string` | **`CMLib_BuffNameAt`** | `unit, int` |
| `bool` | **`CMLib_BuffEnabled`** | `unit, string` |
| `fixed` | **`CMLib_BuffTimeLeft`** | `unit, string` |
| `bool` | **`CMLib_BuffAddTimed`** | `unit, string, unit, fixed` |
| `bool` | **`CMLib_BuffRefresh`** | `unit, string, fixed` |
| `bool` | **`CMLib_BuffExtend`** | `unit, string, fixed` |
| `bool` | **`CMLib_BuffHasFlag`** | `string, int` |
| `void` | **`CMLib_BuffPurgeFlag`** | `unit, int` |
| `string` | **`CMLib_BuffFindByFlag`** | `unit, int` |
| `bool` | **`CMLib_BuffAnyWithFlag`** | `unit, int` |
| `bool` | **`CMLib_BuffTransfer`** | `unit, unit, string, int` |
| `int` | **`CMLib_BuffAddGroup`** | `unitgroup, string, unit, int` |
| `int` | **`CMLib_BuffStripGroup`** | `unitgroup, string` |
| `int` | **`CMLib_BuffAddCSV`** | `unit, unit, string` |
| `bool` | **`CMLib_UStateIsReadOnly`** | `int` |
| `bool` | **`CMLib_UStateSet`** | `unit, int, bool` |
| `bool` | **`CMLib_UStateGet`** | `unit, int` |
| `bool` | **`CMLib_UStateToggle`** | `unit, int` |
| `int` | **`CMLib_UStateSetGroup`** | `unitgroup, int, bool` |
| `bool` | **`CMLib_UnitInvulnerable`** | `unit, bool` |
| `bool` | **`CMLib_UnitHide`** | `unit, bool` |
| `bool` | **`CMLib_UnitPause`** | `unit, bool` |
| `bool` | **`CMLib_UnitSelectable`** | `unit, bool` |
| `bool` | **`CMLib_UnitTargetable`** | `unit, bool` |
| `bool` | **`CMLib_UnitStatusBar`** | `unit, bool` |
| `bool` | **`CMLib_UnitStun`** | `unit, bool` |
| `bool` | **`CMLib_UnitSilence`** | `unit, bool` |
| `bool` | **`CMLib_UnitUsingSupply`** | `unit, bool` |
| `void` | **`CMLib_UnitGhostMode`** | `unit, bool` |
| `bool` | **`CMLib_UnitUnderConstruction`** | `unit` |
| `bool` | **`CMLib_UnitCloaked`** | `unit` |
| `bool` | **`CMLib_UnitHallucination`** | `unit` |
| `bool` | **`CMLib_UnitInTransport`** | `unit` |
| `bool` | **`CMLib_UnitIdleState`** | `unit` |
| `bool` | **`CMLib_UnitDeadState`** | `unit` |
| `bool` | **`CMLib_UnitBuried`** | `unit` |
| `bool` | **`CMLib_PStateSet`** | `int, int, bool` |
| `bool` | **`CMLib_PStateGet`** | `int, int, bool` |
| `int` | **`CMLib_PStateSetGroup`** | `playergroup, int, bool` |
| `void` | **`CMLib_PlayerFreeCost`** | `int, bool` |
| `void` | **`CMLib_PlayerPauseCooldowns`** | `int, bool` |
| `bool` | **`CMLib_PlayerShowScore`** | `int, bool` |
| `bool` | **`CMLib_PlayerGivesBounty`** | `int, bool` |
| `bool` | **`CMLib_PlayerInLeaderPanel`** | `int, bool` |

## cmlib_path

> 地形寻路查询 / 路线（Route）可视化编排

| 返回 | 函数 | 参数 |
|---|---|---|
| `int` | **`CMLib_RouteForUnit`** | `playergroup, unit` |
| `int` | **`CMLib_RouteForUnitType`** | `playergroup, string, int, point` |
| `int` | **`CMLib_RouteLast`** | `—` |
| `bool` | **`CMLib_RouteOk`** | `int` |
| `void` | **`CMLib_RouteDestroy`** | `int` |
| `void` | **`CMLib_RouteDestroyAll`** | `playergroup` |
| `void` | **`CMLib_RouteSetFromPoint`** | `int, point` |
| `void` | **`CMLib_RouteSetFromUnit`** | `int, unit` |
| `void` | **`CMLib_RouteSetToPoint`** | `int, point` |
| `void` | **`CMLib_RouteSetToUnit`** | `int, unit` |
| `point` | **`CMLib_RouteFromPoint`** | `int` |
| `point` | **`CMLib_RouteToPoint`** | `int` |
| `unit` | **`CMLib_RouteFromUnit`** | `int` |
| `unit` | **`CMLib_RouteToUnit`** | `int` |
| `unit` | **`CMLib_RouteUnit`** | `int` |
| `string` | **`CMLib_RouteUnitType`** | `int` |
| `void` | **`CMLib_RouteAddWay`** | `int, point` |
| `void` | **`CMLib_RouteClearWays`** | `int` |
| `int` | **`CMLib_RouteAddWayChain`** | `int, point, point, int` |
| `void` | **`CMLib_RouteShow`** | `int, bool` |
| `void` | **`CMLib_RouteShowAt`** | `int, int, bool` |
| `bool` | **`CMLib_RouteVisibleAt`** | `int, int` |
| `void` | **`CMLib_RouteColor`** | `int, color` |
| `void` | **`CMLib_RouteColorAt`** | `int, int, color` |
| `color` | **`CMLib_RouteColorGet`** | `int, int` |
| `void` | **`CMLib_RouteLineWidth`** | `int, fixed` |
| `fixed` | **`CMLib_RouteLineWidthGet`** | `int, int` |
| `void` | **`CMLib_RouteLineTexture`** | `int, string` |
| `string` | **`CMLib_RouteLineTextureGet`** | `int, int` |
| `void` | **`CMLib_RouteLineTile`** | `int, fixed` |
| `fixed` | **`CMLib_RouteLineTileGet`** | `int, int` |
| `void` | **`CMLib_RouteStepModel`** | `int, string` |
| `string` | **`CMLib_RouteStepModelGet`** | `int, int` |
| `void` | **`CMLib_RouteStepScale`** | `int, fixed` |
| `fixed` | **`CMLib_RouteStepScaleGet`** | `int, int` |
| `void` | **`CMLib_RouteStepMid`** | `int, fixed` |
| `fixed` | **`CMLib_RouteStepMidGet`** | `int, int` |
| `void` | **`CMLib_RouteMinSteps`** | `int, int` |
| `int` | **`CMLib_RouteMinStepsGet`** | `int` |
| `void` | **`CMLib_RouteMinLinear`** | `int, fixed` |
| `fixed` | **`CMLib_RouteMinLinearGet`** | `int` |
| `void` | **`CMLib_RouteMinTravel`** | `int, fixed` |
| `fixed` | **`CMLib_RouteMinTravelGet`** | `int` |
| `void` | **`CMLib_RouteAbilFilter`** | `int, int, int` |
| `int` | **`CMLib_RouteQuick`** | `playergroup, unit, point, color, fixed` |
| `int` | **`CMLib_RouteQuickToUnit`** | `playergroup, unit, unit, color, fixed` |
| `void` | **`CMLib_RouteNoFlyAdd`** | `point, fixed, fixed` |
| `void` | **`CMLib_RouteNoFlyClear`** | `region` |
| `int` | **`CMLib_PathingAt`** | `point` |
| `bool` | **`CMLib_PathingIsGround`** | `point` |
| `bool` | **`CMLib_PathingIsBuilding`** | `point` |
| `bool` | **`CMLib_PathingIsCliff`** | `point` |
| `bool` | **`CMLib_PathingIsBlocked`** | `point` |
| `string` | **`CMLib_PathingName`** | `int` |

## cmlib_env

> 装饰物 Doodad / 地形贴图 / 水面 / 战争迷雾外观

| 返回 | 函数 | 参数 |
|---|---|---|
| `doodad` | **`CMLib_DoodadById`** | `int` |
| `actor` | **`CMLib_DoodadActor`** | `int` |
| `actorscope` | **`CMLib_DoodadScope`** | `int` |
| `bool` | **`CMLib_DoodadSend`** | `int, string` |
| `bool` | **`CMLib_DoodadSendText`** | `int, text` |
| `bool` | **`CMLib_DoodadShow`** | `int, bool` |
| `bool` | **`CMLib_DoodadAnim`** | `int, string` |
| `bool` | **`CMLib_DoodadDestroyFx`** | `int` |
| `bool` | **`CMLib_DoodadTint`** | `int, color, fixed` |
| `bool` | **`CMLib_DoodadScale`** | `int, fixed, fixed` |
| `int` | **`CMLib_DoodadSendRange`** | `int, int, string` |
| `void` | **`CMLib_TerrainShow`** | `region, bool` |
| `string` | **`CMLib_TerrainTextureAt`** | `point` |
| `bool` | **`CMLib_TerrainIsTexture`** | `point, string` |
| `bool` | **`CMLib_WaterMorph`** | `string, fixed, int` |
| `bool` | **`CMLib_WaterPause`** | `string, bool` |
| `void` | **`CMLib_FogEnable`** | `bool` |
| `void` | **`CMLib_FogColor`** | `color` |
| `void` | **`CMLib_FogColorOver`** | `color, fixed` |
| `void` | **`CMLib_FogDensity`** | `fixed` |
| `void` | **`CMLib_FogDensityOver`** | `fixed, fixed` |
| `void` | **`CMLib_FogFallOff`** | `fixed` |
| `void` | **`CMLib_FogFallOffOver`** | `fixed, fixed` |
| `void` | **`CMLib_FogStartHeight`** | `fixed` |
| `void` | **`CMLib_FogStartHeightOver`** | `fixed, fixed` |
| `void` | **`CMLib_FogDisableAtUltra`** | `bool` |
| `void` | **`CMLib_FogPreset`** | `color, fixed, fixed, fixed` |
| `void` | **`CMLib_FogPresetOver`** | `color, fixed, fixed, fixed, fixed` |
| `void` | **`CMLib_FogClear`** | `—` |

## cmlib_stat

> 成就 / 分数 / 难度名 / 效果历史 / 战役模式 / 时间戳

| 返回 | 函数 | 参数 |
|---|---|---|
| `void` | **`CMLib_AchAward`** | `int, string` |
| `void` | **`CMLib_AchErase`** | `int, string` |
| `int` | **`CMLib_AchAwardGroup`** | `playergroup, string` |
| `void` | **`CMLib_AchTermSet`** | `int, string, int` |
| `void` | **`CMLib_AchTermAdd`** | `int, string, int` |
| `void` | **`CMLib_AchTermTick`** | `int, string` |
| `void` | **`CMLib_AchDisable`** | `int` |
| `bool` | **`CMLib_AchDisabled`** | `int` |
| `void` | **`CMLib_AchDisableGroup`** | `playergroup` |
| `void` | **`CMLib_AchPanelCategory`** | `playergroup, string` |
| `void` | **`CMLib_AchPanelShow`** | `playergroup, bool` |
| `text` | **`CMLib_AchPercentText`** | `int, string` |
| `void` | **`CMLib_ScoreSetInt`** | `int, string, int` |
| `void` | **`CMLib_ScoreSetFixed`** | `int, string, fixed` |
| `int` | **`CMLib_ScoreGetInt`** | `int, string` |
| `fixed` | **`CMLib_ScoreGetFixed`** | `int, string` |
| `void` | **`CMLib_ScoreAddInt`** | `int, string, int` |
| `void` | **`CMLib_ScoreAddFixed`** | `int, string, fixed` |
| `void` | **`CMLib_ScoreEnable`** | `int, string, bool` |
| `void` | **`CMLib_ScoreEnableAll`** | `int, bool` |
| `int` | **`CMLib_ScoreSetIntGroup`** | `playergroup, string, int` |
| `void` | **`CMLib_CampaignInitAI`** | `—` |
| `void` | **`CMLib_CampaignMode`** | `playergroup, bool` |
| `void` | **`CMLib_CampaignText`** | `playergroup, string, text` |
| `void` | **`CMLib_CampaignImage`** | `playergroup, string, string` |
| `void` | **`CMLib_CampaignFinished`** | `playergroup, string, bool` |
| `void` | **`CMLib_CampaignTutorialFinished`** | `playergroup, string, bool` |
| `void` | **`CMLib_CampaignSavesEnable`** | `playergroup, bool` |
| `void` | **`CMLib_CampaignCompletedSavesEnable`** | `playergroup, bool` |
| `void` | **`CMLib_CampaignDeleteSave`** | `playergroup` |
| `text` | **`CMLib_DiffName`** | `int` |
| `text` | **`CMLib_DiffNameCampaign`** | `int` |
| `bool` | **`CMLib_DiffEnabled`** | `int` |
| `int` | **`CMLib_DiffAPM`** | `int` |
| `int` | **`CMLib_DiffOfPlayer`** | `int` |
| `void` | **`CMLib_DiffSetPlayer`** | `int, int` |
| `text` | **`CMLib_DiffNameOfPlayer`** | `int, bool` |
| `effecthistory` | **`CMLib_EffHist`** | `unit, int` |
| `int` | **`CMLib_EffHistCount`** | `effecthistory` |
| `string` | **`CMLib_EffHistAbil`** | `effecthistory, int` |
| `string` | **`CMLib_EffHistEffect`** | `effecthistory, int, int` |
| `string` | **`CMLib_EffHistWeapon`** | `effecthistory, int` |
| `fixed` | **`CMLib_EffHistTime`** | `effecthistory, int` |
| `int` | **`CMLib_EffHistType`** | `effecthistory, int` |
| `unit` | **`CMLib_EffHistUnitAt`** | `effecthistory, int, int` |
| `int` | **`CMLib_EffHistAmountInt`** | `effecthistory, int, int, bool` |
| `fixed` | **`CMLib_EffHistAmountFixed`** | `effecthistory, int, int, bool` |
| `int` | **`CMLib_EffHistLast`** | `effecthistory` |
| `string` | **`CMLib_EffHistLastEffectOf`** | `unit` |
| `int` | **`CMLib_B2I`** | `bool` |
| `bool` | **`CMLib_I2B`** | `int` |
| `int` | **`CMLib_NowEpoch`** | `—` |
| `int` | **`CMLib_StartEpoch`** | `—` |
| `int` | **`CMLib_RealElapsedSecs`** | `—` |
| `int` | **`CMLib_EpochField`** | `int, int` |
| `string` | **`CMLib_EpochStamp`** | `int` |
| `int` | **`CMLib_StatEvtBegin`** | `string` |
| `bool` | **`CMLib_StatEvtOk`** | `int` |
| `void` | **`CMLib_StatEvtStr`** | `int, string, string` |
| `void` | **`CMLib_StatEvtInt`** | `int, string, int` |
| `void` | **`CMLib_StatEvtFixed`** | `int, string, fixed` |
| `bool` | **`CMLib_StatEvtSend`** | `int` |
| `int` | **`CMLib_StatEvtLast`** | `—` |
| `int` | **`CMLib_StatEvtCsvCount`** | `string` |
| `int` | **`CMLib_StatEvtStrCSV`** | `int, string` |
| `int` | **`CMLib_StatEvtIntCSV`** | `int, string` |
| `bool` | **`CMLib_StatEvtSendCSV`** | `string, string` |
| `bool` | **`CMLib_StatEvtSendInt`** | `string, string, int` |
