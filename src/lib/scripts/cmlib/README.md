# CMLib — 通用 Galaxy 函数库

从 CMRE / Reborn / 起义狂潮 等 mod 的单位、建筑、面板（UI）效果实现中提炼出的
**跨项目通用函数库**。目标是把散落在各 mod 的高频重复代码（数值钳制、字符串解析、
单位查询/生成、Catalog 运行时改值、玩家资源/联盟/科技、Dialog 控件操作）收敛成
一份可 `include` 直接复用的库，减少重复实现与回归风险。

> 语言：Galaxy（强类型 + fixed 定点数）。命名空间前缀 `CMLib_` / `CMLib` 全局量。

---

## 1. 目录与引用

```
<你的 Mod>.SC2Mod/Base.SC2Data/scripts/cmlib/
├── cmlib.galaxy            ← 聚合入口（先 include 所有 _h，再 include 所有实现）
├── cmlib_core(_h).galaxy   ← 数值 / 字符串 / 键名 / 日志 / DataTable 存储
├── cmlib_ui(_h).galaxy     ← Dialog 控件挂钩 / 创建 / 属性 / 列表 / 事件
├── cmlib_unit(_h).galaxy   ← unitfilter / 单位查询 / 生成 / 行为·武器 / 命令 / 清理
├── cmlib_catalog(_h).galaxy← Catalog 运行时读写（单位/武器/效果/行为/技能/按钮）
├── cmlib_player(_h).galaxy ← 玩家判定 / 遍历 / PlayerGroup / 资源 / 联盟 / 科技
├── cmlib_ai(_h).galaxy     ← AI 波次编排 / 难度 / 脚本控制
├── cmlib_fx(_h).galaxy     ← 音效 / 音乐 / 镜头 / 淡入淡出 / Ping / 飘字 / Actor
├── cmlib_panel(_h).galaxy  ← Dialog 容器 / 计时器窗口 / 任务目标
├── cmlib_bank(_h).galaxy   ← Bank 存档（带 fallback / 脏标记批量落盘 / 版本）
├── cmlib_geo(_h).galaxy    ← 几何 / 寻路 / 单位自定义值 / 行为查询
├── cmlib_text(_h).galaxy   ← 本地化文本 / 数值格式化 / 颜色文本 / 单位名
├── cmlib_trig(_h).galaxy   ← 触发器编排 / 事件挂载 / 等待与计时 / 队列成对保护
├── cmlib_game(_h).galaxy   ← 游戏状态 / 胜负 / 视野迷雾 / 揭示器 / 蔓延
├── cmlib_conv(_h).galaxy   ← 过场对白（Transmission / Conversation）
├── cmlib_udata(_h).galaxy  ← 数据编辑器 User Data 表读写
├── cmlib_stock(_h).galaxy  ← 电脑 AI 库存 / 科技树 / AI 用户变量
├── cmlib_board(_h).galaxy  ← 排行榜面板（Board）/ 任务结算面板（VictoryPanel）
├── cmlib_buff(_h).galaxy   ← Behavior 增益减益 / 单位状态开关 / 玩家状态开关
├── cmlib_path(_h).galaxy   ← 地形寻路查询 / 路线（Route）可视化编排
├── cmlib_env(_h).galaxy    ← 装饰物 Doodad / 地形贴图 / 水面 / 战争迷雾外观
└── cmlib_stat(_h).galaxy   ← 成就 / 分数 / 难度名 / 效果历史 / 战役模式 / 时间戳
```

**引用方式**（在你的脚本顶部）：

```galaxy
include "scripts/cmlib/cmlib"   // 一次性引入全部模块
```

或按需只引某个实现文件（其 `_h` 会被自动带入）：
```galaxy
include "scripts/cmlib/cmlib_unit"
include "scripts/cmlib/cmlib_catalog"
```

> 真实 SC2 编译器中 `natives.galaxy` 与 `GameData/*.galaxy` 由引擎自动提供，
> **无需显式 include**。本库严格遵循该约定（见第 4 节「静态校验说明」）。

---

## 2. 模块 API 速查

<!-- cmlib-readme-round17 -->

> 📇 **完整清单看 [`API_INDEX.md`](API_INDEX.md)**（21 模块 / **1239 个函数**，由
> `gen_api_index.py` 从 `_h.galaxy` 声明自动生成，与实现严格 1:1，实测零漏零多）。
>
> 本节是**精选速查**：按使用场景分组，重点讲「为什么这么设计」「踩过什么坑」——
> 这是索引给不了的。扩库后记得跑 `python gen_api_index.py` 重生成索引，
> 否则「漏记的 API 等于不存在」。

### 2.1 Core (`cmlib_core`)
| 函数 | 说明 |
|---|---|
| `int CMLib_ClampInt/ClampFixed` | 钳制到 [min,max] |
| `fixed RandF/int RandI(min,max)` / `int ModSafe(x,m)` | 随机（反序区间自动交换为 [min,max]）/ 取模（m=0 兜底返回 0，避免 ModI 除零中断触发器） |
| `int MinInt/MaxInt/AbsInt` | 极值 / 绝对值 |
| `int DivInt(fixed DivFixed)` | 除零保护（fallback） |
| `int ScalePercentInt(fixed ScalePercentFixed)` | 按百分比缩放（percent 为整数百分比） |
| `fixed Lerp(from,to,t)` | 线性插值（t∈[0,1]） |
| `bool IsValidPlayerSlot/IsActivePlayer` | 槽位有效性 / 活跃玩家 |
| `bool StrIsEmpty/StrNotEmpty(s)` | **判空唯一正确姿势** —— Galaxy 里空串与 null 等价，`s != null` 恒等于 `s != ""`，不能用来区分"未设置"与"空"（round21 真机实证，见 §8） |
| `string CharAt/StartsWith/EndsWith/Contains/TrimSpaces` | 字符串工具 |
| `string SplitAt(s,sep,index)` / `int SplitCount(s,sep)` | 按分隔符切分 |
| `int ParseInt(s,fb)` / `fixed ParseFixed(s,fb)` / `bool ParseBool(s,fb)` | 字符串→值（带 fallback） |
| `string BoolToString(b)` | 布尔→字符串 |
| `string Key1/Key2/Key3/KeyPlayer/KeyIndexed` | 拼装 DataTable 键名 |
| `Store*/Load*` (Int/Fixed/String/Bool/Unit) | 全局 DataTable 读写（global=true），`StoreHas` 先判存在 |
| `int StoreBump(key,delta)` | 原子自增并返回新值 |
| `LogSetLevel/GetLevel` + `LogError/Warn/Info/Debug(tag,msg)` | 分级日志（封装 TriggerDebugOutput） |

### 2.2 UI (`cmlib_ui`)
| 函数 | 说明 |
|---|---|
| `bool UIValid(control)` | 控件 id 是否有效 |
| `int UIHookup(parent,type,name)` / `UIHookupIndexed(...)` | 按 name 挂钩已有控件 |
| `int UIHookupStandard(type,name)` / `UIHookupPanel/Button/Label/Image` | 标准控件挂钩快捷方式 |
| `int UICreateInPanel(parent,type)` / `UICreateFromTemplate(...)` | 创建控件 |
| `UISetText/Tooltip/Image/Color/Toggled/Visible/Enabled` | 设置属性（均带 `playergroup` 维度） |
| `UISetSize/Position/PositionRelative/AnimationState/RenderPriority` | 布局 / 动画 |
| `int UICreatePlaced(...)` | 一步创建并定位 |
| `UISetVisibleRange(arrayref<CMLib_UIControlArray>,count,players,visible)` | 批量显隐（见 2.6 数组约定） |
| `UIListClear/AddItem/Select` | 列表控件操作 |
| `bool UIOnClick(trigger,control)` / `int UIOnClickRange(trigger,arrayref,count)` | 绑定点击事件 |
| `void Msg/ MsgAll/ MsgPlayer/ MsgObjective/ MsgDirective/ MsgError/ MsgSubtitle/ MsgWarning(area,text)` `MsgClear/ MsgClearAll` | 面板消息区全套（null 玩家组 / 非法槽守门，不崩） |
| `void AlertAtPoint/ AlertAtUnit(alert,player,text,icon,point/unit)` | 地图警报（null 点/单位守门） |
| `void UIFade/ UIFadeIn/ UIFadeOut(control,players,secs,targetTransp)` `UIAnimEvent(control,players,event)` | 控件淡入淡出（无效控件静默跳过；负时长钳 0）/ 动画事件 |
| `void HudCinematic/ HudWorldVisible(players,bool)` `int HudFrame/ HudFrameAll/ HudFrameCSV(players,frameSpec/bool)` | HUD 过场模式 / 世界可见 / 框架显隐（CSV 按 `21,22,6` 批量，返回应用帧数） |
| `int UIHookupButton/Label/Image(parent,name)` | 按类型挂钩的语义化快捷方式（比 `UIHookup(parent,c_triggerControlTypeX,name)` 少记一个枚举） |
| `UISetTooltip/Image/Color/Toggled/Enabled/Active(control,players,v)` | 单属性设置，全部带 `playergroup` 维度 + 无效控件守门 |
| `UISetPosition(control,players,anchor,ox,oy)` / `UISetPositionRelative(...,relative,relAnchor,ox,oy)` | 绝对锚点定位 / 相对另一控件定位 |
| `UISetAnimationState(control,players,stateGroup,state)` / `UISetRenderPriority(control,players,prio)` | 动画状态机 / 渲染层级 |
| `UIListAddItem(control,players,text)` / `UIListSelect(control,players,index)` | 列表项追加 / 选中（`index` 越界守门） |
| `UISetMode(players,mode,duration)` / `UIMode(players,mode)` | UI 模式切换（带/不带过渡时长）；`mode` 取 `c_uiModeFullscreen(0)/Letterboxed(1)/Console(2)` |
| `UIModeFullscreen/Letterbox/Console(players,duration)` | 三种模式的语义化包装，做过场时不用再记枚举值 |
| `UICursor(players,visible)` | 鼠标指针显隐（过场/纯剧情段常用） |
| `UISelectionType(players,selectionType,enabled)` | 开关某种选择方式（框选/双击同类等）。**注意：引擎没有 `c_selectionType*` 常量族，只能传裸 int**，本库自测用字面量 `0` |
| `int DlgCtrlCreate(dialog,type)` / `DlgCtrlCreateTpl(dialog,type,template)` | 在**对话框**里建控件（区别于 `UICreateInPanel` 的 UI 面板）；模板名传 `""` 自动退化成无模板版 |
| `int DlgCtrlSelectedItem(control,player)` | 列表/下拉当前选中项（1-based；无效控件返回 `0`） |
| `void DlgCtrlFullDialog(control,players,full)` | 控件铺满整个对话框（做全屏面板的常用姿势），`players` 传 null = 所有玩家 |
| `void DlgCtrlDestroy(control)` | 销毁对话框控件；无效 id 静默跳过（重复销毁不崩） |
| `void UIFaceHighlight(players,face,highlight)` | 按钮 face 高亮开关（教程引导/技能提示常用） |


### 2.3 Unit (`cmlib_unit`)
| 函数 | 说明 |
|---|---|
| `unitfilter FilterAlive/AliveVisible/AliveVisibleTargetable/Structure/NonStructure` | 预设过滤器 |
| `bool UnitOk/UnitIsStructure/UnitIsType/UnitOwnedBy` | 单位有效性 / 类型 / 归属 |
| `typedef funcref<CMLib_UnitVisitor_Proto> CMLib_UnitVisitor` | 遍历回调类型 |
| `int UGForEach/UGForEachAlive(group,visitor,arg)` | UnitGroup 遍历（倒序，安全删除） |
| `int UGSize/UGSizeAlive` `bool UGIsEmpty` `unit UGAt(group,idxFromEnd)` `unit UGFirstAlive` | 查询 |
| `UGOfTypeInMap/InRegion/NearPoint` `UGStructuresOfPlayer/UGArmyOfPlayer` | 按类型/玩家检索 |
| `unit Spawn/SpawnForced` `unitgroup SpawnMany/SpawnRing` `unit RespawnInPlace` | 生成 |
| `fixed UnitLifePercent/ShieldPercent` `UnitSetLifePercent` `UnitCopyVitalsPercent` | 生命/护盾 |
| `UnitEnsureBehavior/RemoveBehavior/ToggleBehavior` `UnitEnsureWeapon/RemoveWeapon` | 行为 / 武器 |
| `UGEnsureBehavior/UGRemoveBehavior` | 批量行为 |
| `bool UnitOrderAbility/UnitOrderAbilityAtPoint` `int UGOrderAbilityAtPoint` | 下达命令 |
| `int UGRemoveAll/UGKillAll` | 清理 |
| `int UnitWeaponCount` / `fixed UnitWeaponPeriod/UnitWeaponDamage/UnitWeaponDps/UnitDpsTotal` | 武器查询。⚠ **索引 1-based**（`[1, UnitWeaponCount]`），传 0 按越界返回 0.0，不是"第一把武器"（round21 真机钉死） |
| `void UnitRemove(unit)` | 移除单位（同步 `UnitRemove`，null/失效守门）—— 做"限时存在单位"的清理收尾 |
| `void UnitSetState(unit,state,bool)` `void UnitSetPosition(unit,point,bool)` | 状态位 / 瞬移（blend=false 瞬移；坐标受地形吸附，真机同步读回不可靠，断言只验「不崩 + 单位存活」） |
| `void UnitBehaviorAdd(unit,behavior,caster,count)` `void UnitBehaviorRemove(unit,behavior,count)` | 行为**普通变体**（带 caster 单位；区别于上面的 player 变体 `UnitEnsureBehavior/RemoveBehavior`） |
| `void UGAdd(group,unit)` `UGAddGroup(group,add)` `UGRemove(group,unit)` `UGClear(group)` `unitgroup UGCopy(group)` | 单位组增删单/整组 / 清空 / 深拷贝 |
| `unit UGUnit(group,index)` `unit UGRandomUnit(group,type)` `bool UGHasUnit(group,unit)` | 正向取值（one-based）/ 随机一个 / 成员判定 |
| `bool UnitChangeOwner(unit,player,changeColor)` `bool UnitMatchFilter(unit,player,filter)` `string UnitTypeName(type)` `UnitsPauseAll(bool)` | 归属转移（null/无效槽守门）/ 过滤器匹配 / 类型名 / 全局暂停（只调 false，自测不真暂停） |
| `bool UGIssueOrder(group,order,queue)` `UGOrderAbility(group,abil,cmdIdx,queue)` `UGOrderAbilityAtUnit(group,abil,cmdIdx,target,queue)` | 整组下令（null/空能力/空目标守门） |
| `unitgroup UGAlliance(player,alliance,region,filter,maxCount)` `UGEnemiesOf(player,max)` `UGAlliesOf(player,max)` | 按同盟关系取单位组（无效槽→空组但不崩） |
| `bool UnitOrderHasAbil(unit,ability)` | 单位当前命令队列里是否含某能力（null/空能力守门） |
| `order UnitOrderAt(unit,index)` | 读回单位第 index 条排队命令（**getter**，非下令；null/越界→null order） |
| `void SelClear(player)` | 清空某玩家当前选择（无效槽守门） |
| `unitgroup UGSelected(player)` | 取某玩家当前选中单位组（无效槽→空组） |
| `unitgroup UGFilterStr(type,player,group,filterSpec,maxCount)` | 按字符串过滤器（Engine `UnitFilterStr`）筛单位组，限最大数量 |
| `unitfilter FilterAliveVisible/AliveVisibleTargetable/Structure/NonStructure()` | 预设过滤器的具名构造（"建筑"走 **attribute** `c_unitAttributeStructure=7`，**不存在** `c_unitFlagStructure`） |
| `unitgroup UGOfTypeInRegion(type,player,region)` / `UGOfTypeNearPoint(type,player,point,radius)` | 按类型 + 区域/半径检索 |
| `unit UGClosestToPoint(group,point)` / `point UGCenterOfGroup(group)` | 最近成员 / 几何中心（空组→null / Point(0,0)，不崩） |
| `fixed UnitShieldPercent(u)` | 护盾百分比（无护盾单位返回 0 而非除零） |
| `bool UnitRemoveBehavior(u,behavior,player,count)` / `UnitToggleBehavior(u,behavior,player,on)` / `UnitRemoveWeapon(u,weapon)` | 行为/武器移除与开关 |
| `void UnitCreateEffectPoint(u,effect,point)` / `UnitAbilityEnable(u,ability,enable)` / `UnitCargoCreate(u,id,count)` | 对点施放效果 / 技能启停 / 直接往运输舱里造单位 |
| `void UnitSetHeight(u,height,duration)` / `UnitFace(u,facing,dur)` / `UnitFaceUnit(u,target,dur)` / `UnitFacePoint(u,point,dur)` | 高度 / 朝向（角度、朝单位、朝点，`duration=0` 为瞬时） |
| `unit UnitById(id)` / `int UnitTag(u)` | 运行时句柄 ↔ id/tag 互查（跨触发器传单位的正确姿势，比缓存 `unit` 变量安全） |
| `void UnitSelectFor(u,player,select)` / `UnitSelectOnly(u,player)` | 加入/移出某玩家选择 / 独占选中 |
| `void UnitInfoText(u,info,tip,subTip)` | 覆盖单位信息面板文本（做自定义单位说明） |
| `bool UnitTypeFlag(type,flag)` / `fixed UnitTypeProp(type,prop)` | **类型级**元数据查询（不需要实例）；`c_unitFlagWorker=3`、`c_unitPropLifeMax=2` |
| `bool UnitTypeIsStructure(type)` / `UnitTypeIsWorker(type)` | 上面两个的语义化包装——**建筑判定走 attribute、工兵判定走 flag**，这条差异坑过一轮 |
| `abilcmd OrderAbilCmd(order)` / `unit OrderTargetUnit(order)` / `point OrderTargetPoint(order)` | `order` 结构**读**（配合 `UnitOrderAt` 做命令队列分析） |
| `void OrderSetTargetUnit(order,u)` / `OrderSetTargetPoint(order,p)` | `order` 结构**写**（构造好再下发，避免多次 issue） |
| `order OrderOn(ability,cmdIndex,target)` / `OrderAutoCast(ability,cmdIndex,on)` | 直接构造带目标的命令 / 自动施法开关 |
| `bool UnitHasBehaviorRaw(unit,behavior)` | 直接问引擎「有没有这个 behavior」，不过 CMLib 的层数缓存（层数为 0 但 buff 仍挂着时与 `UnitBehaviorCount` 结论不同） |
| `int UnitOrderCount(unit)` | 当前命令队列长度（判「是否空闲」比 `UnitIsIdle` 更细粒度） |
| `void UnitTeamColor(unit,index)` | 覆写单位队伍色索引（区分同阵营小队常用） |
| `fixed UnitAbilChargeInfo(unit,abilcmd,type)` | 技能充能信息。`type` 取 `c_unitAbilChargeCountMax(0)/CountUse(1)/CountLeft(2)/RegenMax(3)/RegenLeft(4)` |
| `void UnitAbilReset(unit,abilcmd,location)` | 重置技能冷却/充能；`location` 是**裸 int**（引擎没有 `c_abilResetLocation*` 常量族） |
| `unitref UnitRefFromVar(varName)` | 由变量名取 unitref（存档/配置驱动的单位引用）；名字为空返回 null |
| `unitgroup UGFilterRegion(group,region,maxCount)` | 按区域筛子组。`maxCount <= 0` 归一到 `c_unitCountAll(0)` = 不限量（**负数直接丢给原生行为未定义**，所以统一夹到 0） |


### 2.4 Catalog (`cmlib_catalog`)
| 函数 | 说明 |
|---|---|
| `string CatPathIndex(field,idx)` / `CatPathIndexSub` / `CatPathSub` | 拼装字段路径 |
| `bool CatEntryExists(catalog,entry)` | 条目是否存在 |
| `CatGetString/Int/Fixed` + `CatArrayCount` | 读取（带 player + fallback） |
| `CatSetString/Int/Fixed` `CatModifyInt/Fixed(op)` `CatScalePercent` | 写入 / 修值 / 百分比缩放 |
| `UnitDataGet/Set LifeMax/ShieldMax/Speed/Armor/Supply/Cost/Food` `UnitDataBoostPercent` | 单位数据运行时改值 |
| `WeaponDataGetRange/Period` `WeaponDataAddRange` `WeaponDataSpeedUpPercent` | 武器 |
| `EffectDataGet/Set/AddAmount` `EffectDataScalePercent` | 效果 |
| `BehaviorDataGetDuration` `BehaviorDataSetDuration/ModFixed` | 行为 |
| `AbilDataSet/GetCooldown/EnergyCost` `AbilDataSet/GetTrainTime(slot)` | 技能 |
| `ButtonDataSet/GetIcon` | 按钮图标 |
| `int CatCount(catalog)` / `string CatEntryAt(catalog,index)` | 条目计数 / 取条目 id（**1-based 守门**：index 0 或越界返回空串，绝不返回脏数据） |
| `int CatFindIndex(catalog,entry)` | 反查条目下标（找不到返回 0） |
| `int CatGetIntFast(catalog,entry,field,player)` / `int CatFieldCount(catalog,entry,field,player)` / `string CatEntryScope(...)` | 快速读 int（空串/无效条目兜底 0）/ 字段数组计数 / 条目作用域 |
| `int CatCountWhere(catalog,field,value,player)` / `string CatFirstWhere(...)` | 全表条件查询（只在小目录如 Race 上跑，避免撑爆触发器预算） |
| `bool CatLinkSwap(player,catalog,idA,idB)` | 链接替换（空串/未知 id 守门返回 false） |
| `bool CatFieldExists(scope,field)` | 字段路径是否存在（用于"可选字段"探针，避免盲读空字段） |
| `bool CatRefSet(reference,player,value)` | 按引用路径写值（player 作用域；空串/无效引用守门返回 false） |

> Catalog 操作枚举 `CMLIB_CAT_OP_*` 复用引擎 `c_upgradeOperation*`（Add=0 … Set=6）。
> Catalog 类型枚举复用 `c_gameCatalog*`（Unit=94 / Weapon=103 / Effect=32 / Behavior=14 / Abil=0 / Button=17 / Upgrade=95）。

### 2.5 Player (`cmlib_player`)
| 函数 | 说明 |
|---|---|
| `bool PlayerActive/IsHuman/IsComputer/IsEnvironment` | 槽位判定 |
| `typedef funcref<CMLib_PlayerVisitor_Proto> CMLib_PlayerVisitor` | 遍历回调类型 |
| `int ForEachActivePlayer/HumanPlayer/InGroup(visitor,arg)` | 玩家遍历 |
| `playergroup PGActive/Humans/Computers/Single/Pair/AlliesOf/EnemiesOf` `int PGCount` `bool PGHas` | PlayerGroup 构造与查询 |
| `int ResGet/GetMinerals/GetVespene` `ResAdd/AddMinerals/AddVespene` `ResSet` | 资源读写（扣费有下限保护） |
| `bool ResTrySpend(player,min,vesp)` | 先查后扣，不足返回 false |
| `void ResGrantGroup(group,min,vesp)` | 群体发放 |
| `int SupplyFree(player)` | 剩余补给 |
| `AllySetMutual/MakeFullAllies/MakeEnemies/GiveVision` `bool AllyIsAlly` | 联盟 |
| `int UpgradeLevel` `bool UpgradeHas` `UpgradeEnsureLevel`（幂等）/ `UpgradeGrantGroup` | 科技 |
| `point PlayerStart(player)` / `int PlayerDiff(player)` / `string PlayerRaceOf(player)` | 出生点（非法槽返回 Point(0,0) 而非 null）/ 难度 / 种族 |
| `playergroup PGCopyOf(group)` / `PGAllianceOf(type,player)` | 玩家组深拷贝（null→空组不崩）/ 按同盟类型取玩家组 |
| `bool PlayerIsHuman/IsComputer/IsEnvironment(player)` | 槽位类型判定；底层 `c_playerTypeUser=1/Computer=2/None=0`，非法槽一律 false 不崩 |
| `int ForEachHumanPlayer(visitor,arg)` / `ForEachInGroup(group,visitor,arg)` | 只遍历人类 / 遍历指定 playergroup |
| `playergroup PGHumans/PGComputers/PGSingle(p)/PGPair(a,b)/PGAlliesOf(p)/PGEnemiesOf(p)` | 常用 playergroup 构造 |
| `void PGAdd/PGRemove/PGClear(group,...)` / `int PGAt(group,index)` | playergroup 增删清空 / 按下标取（**one-based**，越界→0） |
| `int ResGetMinerals/ResGetVespene(p)` / `ResAddMinerals/ResAddVespene(p,delta)` | 单资源读写快捷方式（`ResAdd*` 扣费带下限保护，返回操作后余额） |
| `void AllyMakeFullAllies(a,b)` / `AllyMakeEnemies(a,b)` / `AllyGiveVision(from,to,value)` | 双向联盟 / 双向敌对 / 单向共享视野 |
| `text PlayerNameOf(p)` / `string PlayerHandleOf(p)` / `int PlayerTypeOf(p)` / `PlayerStatusOf(p)` | 标识与状态；`c_playerStatusUnused=0/Active=1/Left=2` |
| `int PlayerPropInt(p,prop)` | 玩家属性通用读（`c_playerPropMinerals=0` 等） |
| `int PlayerColor(p)` / `void PlayerSetColor(p,index,changeUnits)` | 颜色读写（`changeUnits=true` 时同步已有单位配色） |
| `bool PlayerTalent(p,talent)` / `fixed PlayerCooldown(p,cooldown)` / `bool PlayerCooldownReady(p,cooldown)` | 指挥官天赋 / 玩家级冷却（**未知 cooldown link 会抛错**，自测放在子块末尾） |
| `void PlayerEffectAt(p,effect,point)` / `PlayerEffectOn(p,effect,unit)` | 以玩家名义施放效果（无源单位的全局效果，如指挥官技能） |


### 2.6 数组参数约定（真机验证过的硬约束）

> ⚠️ **硬约束（2026-08-08 真机验证）**：Galaxy **不支持裸数组形参**
> （如 `void f(int[8] lp_arr)`）。任何使用裸数组形参的函数都会让 **整个 MapScript
> 被 SC2 静默丢弃**——不报错、不写日志、`InitMap()` 永不被调用。而 `galaxy-lint`
> 即便带 `--type-check` 也报 **0 错误**，静态工具完全抓不到。
> 本库因此把"数组形参"固化为 `check_cmlib.py` 的第 6 项门禁（阳性对照已验证会真响）。

可用写法（全部真机验证通过）：

| 写法 | 适用场景 | 示例 |
|---|---|---|
| `playergroup` / `unitgroup` | 玩家集 / 单位集批量操作 | `void CMLib_GameEndForPlayers(playergroup lp_players, ...)` |
| CSV 规格串 | 异构批量（类型+数量/多类型） | `void CMLib_StockArmyBatch(int lp_player, string lp_spec)`（`"Marine:5,Marauder:2"`） |
| `arrayref<具名 typedef>` | 同类型定长数组批处理 | `void CMLib_UISetVisibleRange(arrayref<CMLib_UIControlArray> lp_controls, ...)` |
| 多标量形参 | 少量固定元素 | `void CMLib_TransSequence2(playergroup, s1, snd1, ..., s2, snd2, ...)` |

```galaxy
// ❌ 致命：裸数组形参 → 真机静默丢弃整个 MapScript（lint 不报错）
void CMLib_BadExample(int[8] lp_arr, int lp_n);

// ✓ 正确：用 playergroup 传玩家集合
void CMLib_GameEndForPlayers(playergroup lp_players, int lp_endType, bool lp_showDialog, bool lp_showScore);

// ✓ 正确：用 CSV 串传异构批量
void CMLib_StockArmyBatch(int lp_player, string lp_spec);   // "Marine:5,Marauder:2,Medivac:1"

// ✓ 正确：同类型定长数组用 arrayref<具名 typedef>
const int CMLIB_UI_ARRAY_MAX = 64;
typedef int[CMLIB_UI_ARRAY_MAX] CMLib_UIControlArray;
void CMLib_UISetVisibleRange(arrayref<CMLib_UIControlArray> lp_controls, int lp_count, playergroup lp_players, bool lp_visible);
```

调用方需先 `int[CMLIB_UI_ARRAY_MAX] arr;` 填充，再传 `arrayref<CMLib_UIControlArray> arr;`。

---

### 2.7 AI (`cmlib_ai`)
波次是**隐式状态机**：必须先 `Begin` 再 `Add` 再 `Target` 最后 `Send`，中途不可穿插其它波次。
| 函数 | 说明 |
|---|---|
| `waveinfo AIWaveBegin(player,useGroup)/Add4(type,n,q,c)/Add(1 组)/AddRamp/AddScaled/AddAtDifficulty` | 构建当前波次（Add* 须紧接 Begin） |
| `waveinfo AIWaveUseGroup/UseUnit` `AIWaveTargetPoint/TargetPlayer/TargetClosest` `AIWaveWaypoint` | 指定来源/目标/路径点 |
| `AIWaveSend/SendJittered(delay,jitter)` `AIWaveCancelLast/Simple` | 发出波次（Simple = Begin+Add+Target+Send 一步） |
| `AISetDifficulty(player,d)` / `int AIPickByDifficulty(d, c,n,h,b)` / `fixed AIScaleByDifficulty(d, c,n,h,b)` | 难度常量 `CMLIB_DIFF_CASUAL=0…BRUTAL=3` |
| `AICastUnitAbility/AtPoint` `AIBulliesInRegion(region)` `AIScriptControlUnit/Group/Release` | 即时施法 / 压制 / 脚本接管 |
| `AIAttackWaveAddUnits(difficulty,count,unitType)` | 单难度波次加兵（直接对标 mod 高频调用的 `AIAttackWaveAddUnits`） |
| `AISetFlag(player,index,bool)`（index∈1..128）`fixed AIGetTime()` | AI 全局旗标 / 时钟 |
| `AICounterUnitSetup(player,seeWhat,factorSameTech,makeSameTech,factorAnyTech,makeAnyTech)` | 计数器单位配置：看到 seeWhat 时按系数补造 makeWhat |
| `void AIUnitSuicide(unit,enable)` / `AIGroupSuicide(group,enable)` | 自杀式冲锋开关：开了之后 AI 不再考虑撤退保命 |
| `void AIGroupScriptControlled(group,enable)` | 把一组单位从 AI 托管里摘出来交给脚本（做剧本化战斗必备） |
| `int AIState(player,index)` | 读 AI 状态槽；`index` 是**裸 int**（AI.galaxy 里没有 `c_ASState*` 常量族） |
| `void AISubStateChance(subState,chance)` | 调 AI 子状态触发概率（波次难度微调） |

#### 2.7.1 AI 战术过滤（round24 新增，`aifilter` 句柄族）

挑目标的标准姿势。这一族此前被历轮判为"范围外不封装"，round24 用六档真机探针推翻（详见 §11）。

**句柄层**：`New -> 若干 Set -> Apply`，多条件组合时用。

| 函数 | 说明 |
|---|---|
| `aifilter AIFilterNew(player)` | 建过滤器。玩家槽非法返回 `null`，后续 Set/Apply 全部安全短路 |
| `void AIFilterAlliance(f, c_playerGroupAlly\|Enemy\|Any)` | 阵营 |
| `void AIFilterTypes(f, filterStr)` | 类型位集，内部走 `UnitFilterStr` |
| `void AIFilterPlane(f, CMLIB_AIPLANE_GROUND\|AIR)` | 平面。常量库内自定义，不依赖 `c_planeGround`（那个在 `GameData/Game.galaxy`，用它就多一条 include 假设） |
| `void AIFilterLife/LifePercent/LifeLost/Shields(f, min, max)` | 四个数值区间。`min > max` 视为笔误 → **忽略该条件并 LogWarn**，而不是静默过滤成空组 |
| `void AIFilterRange(f, center, radius)` | 半径。`center == null` 时**跳过**而不是照传（见 §11.3 的 callall 教训） |
| `void AIFilterInCombat(f, want)` / `AIFilterSortByLife(f, lifeW, distW)` | 战斗中 / 排序参考 |
| `unitgroup AIFilterApply(f, src)` | 应用。**null 入参返回空组而不是 null**，调用方可无脑接着数 |
| `int AIFilterApplyCount(f, src)` | 只要数量时用，省一次中间组 |

**一站式层**：单条件场景一行搞定。命名用 `AISelect*` 而非 `AIPick*` —— 后者已被 `AIPickByDifficulty`（按难度选数值）占用，撞在一起会误导。

| 函数 | 说明 |
|---|---|
| `unitgroup AISelectEnemies/Allies(player, src)` | 按阵营挑 |
| `unitgroup AISelectInRange(player, src, center, radius)` | 半径内 |
| `unitgroup AISelectWounded(player, src, maxLifePct)` | 残血优先（自动按血量排序，最残在前） |
| `unitgroup AISelectByType(player, src, filterStr)` | 按类型串 |
| `unitgroup AISelectGround/Air(player, src)` | 按平面 |

**无句柄组过滤**：直接 `unitgroup -> unitgroup`。

| 函数 | 说明 |
|---|---|
| `unitgroup AIGroupProduction(src, activeOnly)` | 生产建筑。真机已验产出非空 |
| `unitgroup AIGroupPathable(src, from)` | 寻路可达。真机已验产出非空 |
| `unitgroup AIGroupCasters(src)` | 有可施放技能的。⚠ 只有"调用不中断"证据 |
| `unitgroup AIGroupGathering(src, resource, dist)` | 正在采集的。⚠ 同上 |

> **故意不封装**（未拿到正向返回值证据，见 §11.3）：`AISetFilterSelf` /
> `LifeMod` / `CanAttackEnemy` / `CanAttackAlly` / `BehaviorCount` /
> `ValidPassenger` / `Marker` / `LifePerMarker`。
> **坐实不可用**：`AIUnitGroupGetValidOrder`（前提全成立仍返回 null）。

### 2.8 FX (`cmlib_fx`)
SC2 音量为 **0.0 ~ 100.0**（非 0~1）。常量：`CMLIB_FX_VOL_FULL=100.0 / MUTE=0.0`。
| 函数 | 说明 |
|---|---|
| `SfxPlay(link,vol)/SfxPlayAtPoint/SfxPlayForPlayer` `SfxStop` | 音效（vol 走 0~100） |
| `void SfxPlayAtFor(soundId,owner,players,at,volume)` | 在指定点给指定玩家组放音效（走 `CMLib_SfxLink`+`CMLib_FxVol`+`CMLIB_FX_NO_OFFSET`） |
| `void SfxChannelMute(players,channel,mute)` | 静音指定玩家的某个音效声道（channel 用 `c_soundChannel*`） |
| `MusicPlay/Stop/SetVolume` `ChannelVolume(playerGrp,cat,vol,dur)` `DuckCombatAudio(playerGrp,duck,dur)` | 音乐 / 声道 / 战斗压低 |
| `CamApply/CamSetValue(player,field,val,dur)` `CamPan/CamShake/CamFacing` | 镜头（field 用 `c_cameraValue*`） |
| `void CamShakePreset(player,amplitude,frequency,blendIn,blendOut,duration)` | 镜头震动预设（字符串振幅/频率档位） |
| `point CamTarget(player)` | 取玩家当前镜头目标点 |
| `void CamSave(player)` / `void CamRestore(player,duration,velocity,decelerate)` | 镜头快照保存 / 带回弹参数恢复 |
| `FadeOut/FadeIn/FadeToColor(playerGrp,dur,color,hold)` | 屏幕淡入淡出 |
| `PingPlayer/PingAtPoint/PingMinimapAlert(playerGrp,point,color)` | 小地图 Ping / 警报 |
| `FloatTextAtPoint/FloatTextForPlayer(text,point,color)` | 飘字 |
| `ActorCreateFromUnit/Send(unit,msg,scope)` `ActorFromUnit` | Actor 特效挂钩 |
| `void SfxPlayOwned(soundId,owner,players,volume)` | 带归属玩家的音效播放（谁放的技能，音量归谁），空 id / 非法槽守门 |

### 2.9 Panel (`cmlib_panel`)
基于 `c_objectiveState*` 的目标状态别名：`CMLIB_OBJ_ACTIVE/COMPLETED/FAILED/HIDDEN`。
| 函数 | 说明 |
|---|---|
| `int PanelCreate(parent,type,w,h)` `PanelAddItem/SetItemText` `PanelClear` | Dialog 容器 / 列表项 |
| `int TimerWindowCreate(playerGrp,title,time,show)` `TimerWindowSetTime/Title/Hide` | 计时器窗口（倒计时 UI） |
| `int ObjCreate(title,desc,state,players)` `ObjSetState/Title/Desc` `ObjComplete/Fail` | 任务目标（Objective） |
| `int PanelCreateCentered(w,h)` / `PanelCreateAnchored(w,h,anchor,margin)` / `PanelCreateOverlay()` | 三种常用容器创建姿势（居中 / 贴边带边距 / 全屏覆盖层） |
| `bool PanelValid(panel)` / `PanelDestroy(panel)` | 有效性 / 销毁（销毁后 `PanelValid` 立即为 false） |
| `PanelShow(panel,players,v)` / `PanelShowAll(panel,v)` / `PanelShowFor(panel,player,v)` / `bool PanelIsVisibleFor(panel,player)` | 显隐三档粒度 + 单玩家可见性回读 |
| `PanelSetBackdrop/SetFullscreen/SetTransparency/SetRenderPriority(panel,...)` | 背景板 / 全屏 / 透明度 / 层级 |
| `PanelResize(panel,w,h)` / `PanelMove(panel,anchor,ox,oy)` | 尺寸 / 位置 |
| `int TimerPanelCreate(timer,title,showElapsed)` / `TimerPanelStart(secs,title,players)` | 绑已有 timer / 一步开一个倒计时窗口 |
| `TimerPanelShow(win,players,show)` / `TimerPanelAnchor(win,anchor,ox,oy)` / `TimerPanelDestroy(win)` | 计时窗显隐 / 定位 / 销毁 |
| `int ObjCreateShown(name,desc,primary,players)` | 建目标并立即对指定玩家可见（省掉 create+show 两步） |
| `int ObjGetState(obj)` / `bool ObjIsResolved(obj)` | 状态读回 / 是否已终结（完成或失败） |
| `ObjActivate/ObjFail/ObjHide/ObjShow(obj,...)` / `ObjDestroy(obj)` / `ObjDestroyAll(players)` | 状态迁移 / 显隐 / 销毁（`DestroyAll` 按玩家组批量清） |
| `ObjRename(obj,name)` / `ObjSetDesc(obj,desc)` / `text ObjName(obj)` / `text ObjDesc(obj)` | 标题/描述读写 |
| `ObjSetPriority/int ObjPriority(obj)` / `ObjSetPrimary/bool ObjIsPrimary(obj)` | 排序权重 / 主线标记 |
| `ObjSetPlayers(obj,players)` / `bool ObjVisibleFor(obj,player)` | 可见玩家集合 / 单玩家可见性 |
| `ObjMoveFirst/MoveLast(obj)` / `ObjMoveAfter/MoveBefore(obj,anchor)` | 面板内重排（`anchor` 为另一 objective id；**自身作 anchor 时守门为 no-op**） |
| `int ObjLast()` | 最近一次创建的 objective id（不用自己接返回值） |


### 2.10 Bank (`cmlib_bank`)
所有 `Get*` 强制带 fallback，键缺失不静默返回 0/""；`Set*` 自动置脏标记，配合 `FlushIfDirty` 批量落盘。
| 函数 | 说明 |
|---|---|
| `bank BankOpen(name,player)` `BankFlush/BankMarkDirty/BankIsDirty/BankFlushIfDirty` | 打开 / 落盘 / 脏标记 |
| `BankHas(section,key)` `BankEnsureSection` | 存在性 |
| `BankGetInt/String/Bool/Fixed`（均带 fallback） | 读取 |
| `BankSetInt/String/Bool/Fixed` | 写入（自动置脏） |
| `BankBump/KeepMax/KeepMin/UnlockOnce/SeedInt/SeedBool` | 累加 / 极值 / 一次性解锁 / 结构升级补字段 |
| `BankClearKey/ClearSection` `BankSchemaVersion/SetSchemaVersion` | 清理 / 存档结构版本 |
| `BankGetString/Bool/Fixed` / `BankSetString/Bool/Fixed` | 三种非 int 类型的读写（`Get*` 一律强制 fallback，`Set*` 自动置脏） |
| `int BankKeepMax/KeepMin(bank,section,key,v)` | 只在更优时写入（打最高分 / 最短用时），返回写后值 |
| `bool BankUnlockOnce(bank,section,key)` | 一次性解锁：首次调用返回 true 并落标记，之后恒 false |
| `BankSeedInt/SeedBool(bank,section,key,v)` | **仅当键不存在时**写入——存档结构升级补字段的正确姿势（不会覆盖老玩家数据） |
| `BankClearSection(bank,section)` / `BankSetSchemaVersion(bank,v)` | 整段清空 / 写结构版本号 |
| `bank BankLast()` | 最近一次 `BankOpen` 的句柄。⚠️ **绝不要跨帧缓存 bank 句柄**——极早期拿到的不可用句柄会让整局写入静默 no-op（见 §5.3） |
| `bool BankExists(name,player)` / `void BankRemove(bank)` | 存档文件级存在判定 / 删档 |
| `void BankWait(bank)` | 阻塞等待 bank 就绪。**自测不真机断言它**——阻塞语义会把测试图挂死 |
| `BankOption(bank,option,enable)` / `bool BankOptionOn(bank,option)` / `bool BankVerified(bank)` | 选项开关（`c_bankOptionSignature=0`）与签名校验状态 |
| `string BankNameOf(bank)` / `int BankPlayerOf(bank)` | 句柄反查名字/归属玩家 |
| `bool BankSectionExists(bank,section)` / `int BankSectionCount(bank)` / `string BankSectionName(bank,index)` | 段枚举 |
| `int BankKeyCount(bank,section)` / `string BankKeyName(bank,section,index)` | 键枚举（做存档巡检/迁移脚本用）。索引基数引擎未明确文档化，自测只断言"越界守门返回空串且不崩" |


### 2.11 Geo (`cmlib_geo`)
坐标为 fixed 地图坐标；角度单位 = 度（0=+X，逆时针正）。区域句柄由引擎 GC，无 Destroy 原生。
| 函数 | 说明 |
|---|---|
| `PointOffset(p,dx,dy)` `PointX/Y(p)` `PointHeight(p)` | 点构造 / 坐标 / 高度 |
| `Distance(a,b)` `AngleBetween(a,b)` `PointPolar(src,dist,ang)` `PointTowards(src,tgt,dist)` `LerpPoint(a,b,t)` | 关系量 / 极坐标 / 插值 |
| `PointPassable(p)` `PointsConnected(a,b)` `FindPathablePoint(p,maxR)` | 可达性 / 螺旋寻路回退 |
| `RegionCircle(center,r)` `RegionRect(...)` `RegionEmpty` `RegionCenter` `RegionRandomPoint` `RegionContains` `RegionAddCircle/AddRect` | 区域构造 / 查询 / 修改 |
| `void RegionAdd(target,add)` | 把 add 区域并入 target（并集，target 自身被修改） |
| `point RegionBoundsMin(region)` / `point RegionBoundsMax(region)` | 区域包围盒的左下 / 右上角点 |
| `RandomPointInRadius(center,r)` | 半径内随机点（刷兵/投放常用） |
| `fixed PointFacing(point)` / `void PointSetFacing(point,facing)` | 点的朝向读 / 写 |
| `int PathCost(a,b)` | a→b 的路径代价（寻路距离代理，不可达返回 -1） |
| `UnitGetValue/SetValue(unit,idx)` | 单位自定义值槽读写 |
| `UnitBehaviorCount(unit,behavior)` `UnitHasBehavior(unit,behavior)` | 行为层数 / 存在性查询 |
| `fixed SinDeg(deg)` / `fixed CosDeg(deg)` | 度制三角函数（引擎原生 `Sin/Cos` 就是度制，这里只是把单位写进名字，省得每次去查） |
| `fixed NormalizeAngle(deg)` | 角度归一到 `[0,360)`；做朝向差值/转向插值前先过一道，避免 `-350` 这类值把比较逻辑带沟里 |

### 2.12 Text (`cmlib_text`)
所有面向玩家的可见文本都应经本模块，保证可本地化（不硬编码中文串）。颜色分量 0.0~255.0。
| 函数 | 说明 |
|---|---|
| `text Loc(id)` | 读取 GameStrings 本地化文本（`StringExternal`） |
| `FmtToken(id,code,value)` `FmtAssemble(id)` | 带令牌的格式化文本拼装（`TextExpression*`） |
| `Int(x)` `Fixed(x,precision)` | 数值格式化（走 GameData 默认格式） |
| `Color(r,g,b)` `ColorA(r,g,b,a)` `TextColored(t,color)` | 颜色 / 彩色文本 |
| `TextRed/Green/Blue/Yellow/Orange/White/Gray(t)` | 语义色文本（错误/成功/信息分级） |
| `text UnitName(unit)` | 单位目录显示名（`StringExternal(CatalogFieldValueGet(c_gameCatalogUnit,type,"Name",1))`） |

### 2.13 Trig (`cmlib_trig`)
来源：对 94 个 mod 业务脚本的调用频次扫描显示，**触发器域是最大未封装缺口**
（43,250 次调用 / 168 种 API）。本模块解决四个真实痛点：① 触发器无身份/无分组；
② `TriggerExecute(t,testConds,waitUntilDone)` 双 bool 易记混；③ `TriggerQueueEnter/Exit`
漏配对会永久卡死队列；④ `Wait` 时间类型靠默写。注册表容量 `CMLIB_TRIG_MAX=256`。
| 函数 | 说明 |
|---|---|
| `trigger TrigNew(funcName,tag)` / `TrigNewDisabled` | 创建并登记（带 name+tag 分组） |
| `void TrigRegister(t,name,tag)` / `TrigUnregister(t)` | 接管 GUI 生成的触发器 / 摘除 |
| `int TrigCount()` `TrigCountByTag(tag)` `trigger TrigFind(name)` `bool TrigIsRegistered/TrigEnabled(t)` | 查询 |
| `TrigOn/Off/Set/Kill(t)` | 单触发器 启用/禁用/销毁（null 安全） |
| `int TrigTagOn/Off/Kill(tag)` | 按 tag 批量开关/销毁（关卡阶段切换主力） |
| `TrigRun/RunNow/Force/ForceNow(t)` `bool TrigTest(t)` `TrigStopSelf()` | 语义化执行（拆开 TriggerExecute 双 bool）/ 求值 / 停自己 |
| `TrigQueueBegin/End/Depth/IsEmpty/Pause` | 队列成对保护（深度计数 + 漏 Exit 告警） |
| `TrigOnMapInit/Elapsed/Period/PeriodReal/Timer(t,...)` | 生命周期事件挂载（周期≤0 会被拒） |
| `TrigOnUnitDied/Attacked/ChangeOwner/GainLevel/Created/Damaged/Idle` | 单位事件（null = 「任意单位」通配） |
| `TrigOnPlayerLeft/AllianceChange/AIWave/Chat/Generic` + `TrigSend(evt)` | 玩家/聊天/自定义事件 |
| `TrigOnUnitRegion(t,u,region,entering)` / `TrigOnUnitRegionBoth(t,u,region)` | 区域进出（Both = 同时挂 Enter+Exit，避免"区域内计数"单向漂移） |
| `TrigOnUnitRange(t,u,from,dist)` / `TrigOnUnitRangePoint(t,u,point,dist)` | 进入某单位/某点的半径范围 |
| `TrigOnUnitCargo(t,u,loading)` / `TrigOnUnitSelected(t,u,player,sel)` / `TrigOnUnitClicked` / `TrigOnUnitHighlight` | 载具装卸 / 选中 / 点击 / 鼠标悬停 |
| `TrigOnUnitAbility(t,u,abilcmd,stage,includeShared)` / `TrigOnUnitAbilityUsed(t,u,abilcmd)` | 技能事件；`AbilityUsed` = Execute 阶段 + includeShared（建造类共享技能才收得到） |
| `TrigOnUnitAutoCast` / `TrigOnUnitOrder` / `TrigOnUnitProperty(t,u,prop)` / `TrigOnUnitBehavior(t,u,behavior,change)` | 自动施法开关 / 下令 / 属性变化（生命等）/ Behavior 增删激活 |
| `TrigOnConstructProgress/TrainProgress/ResearchProgress/ReviveProgress/LearnProgress/SpecializeProgress/ArmMagazineProgress(t,u,stage)` | 七类进度事件（`stage` 取 `c_unitProgressStage*`：Start/Complete/Cancel/Pause/Resume） |
| `TrigOnBuildingDone/TrainDone/ResearchDone/UnitRevive/UnitPowerup(t,u)` | 上述进度的 Complete 快捷入口（最常用，免记 stage 常量） |
| `TrigOnEffectUsed(t,player,effect)` / `TrigOnEffectScope(t,player,scope)` | 效果触发（伤害/治疗链路挂钩） |
| `TrigOnDialogControl(t,player,control,eventType)` / `TrigOnButtonClick(t,control)` | 面板控件事件；`ButtonClick` = 任意玩家 + Click，覆盖 90% 场景 |
| `region EvtRegion()` `unit EvtRangeUnit/EvtCargoUnit/EvtProgressUnit/EvtEffectUnit/EvtEffectCaster/EvtEffectTarget()` `abilcmd EvtAbility()` `int EvtAbilityStage/EvtProgressType/EvtControl/EvtControlEventType()` `string EvtBehavior/EvtEffect()` `point EvtEffectPoint()` `bool EvtIsControl(c)` | 新增事件族取参（仅执行期有效） |
| `int EvtPlayer()` `unit EvtUnit()/EvtTargetUnit()` `string EvtChat(b)` | 事件取参（仅执行期有效） |
| `int TrigExecCount(trigger)` | 读触发器累计派发次数（含常驻/计时器触发，用于"每 N 次"逻辑） |
| `unit EvtCreatedUnit()` | 单位创建事件里被创建的单位（仅在 `TrigOnUnitCreated` 执行期有效） |
| `int EvtDmgSourcePlayer()` / `unit EvtDmgSourceUnit()` | 伤害事件的来源玩家 / 来源单位（非事件上下文调用安全回退，不崩） |
| `int EvtEffectUsedUnitOwner(int location)` | 效果使用事件里「目标单位」的归属玩家（location 用 `CMLIB_EFFECT_LOC_TARGET_UNIT` 等） |
| `TrigArgSet*/Get*(slot,val)` `TrigCallInt(t,slot,v)` | 跨触发器键值传参（DataTable，避免全局临时量） |
| `WaitGame/WaitReal/WaitAI/Yield(secs)` | 语义化等待（游戏/真实/AI 时间，Yield=让出一帧） |
| `timer TimerOnce/Loop(secs)` `TimerLeft/Elapsed/Hold/Reset(t)` | 计时器 |
| `TrigDumpState()` | 自检：注册数/启用数/溢出/队列深度 |
| `trigger TrigFindByFunc(funcName)` | 按**函数名**找引擎里已注册的 trigger（`TriggerFind`）。⚠️ 与 §2.13 的 `TrigFind` 不是一回事——后者查的是 CMLib 自己的注册表 |
| `void TrigOnPlayerPropChange(t,player,prop)` | 绑定玩家属性变化事件；`prop` 取 `c_playerPropMinerals(0)` 等 |
| `string TrigEventParamName(eventName,paramName)` | 自定义脚本事件的参数名解析（`TriggerSendEvent` 那套的配套）；任一入参为空返回 `""` |
| `fixed EvtDamageAmount()` / `string EvtUpgradeName()` | **事件上下文专用**：读本次伤害数值 / 本次升级名。脱离事件上下文调用返回 0 / `""` |

### 2.13.1 Trig 关键约束
- **`TriggerQueueBegin` 必须与 `TrigQueueEnd` 严格配对**。漏 Exit 会让队列永久卡死、
  后续所有排队触发器静默不执行且无报错；本模块用深度计数 + warn/error 日志显式化。
- **`Wait` 是异步的**：局部变量在 Wait 后依然有效，但全局变量可能已被别的触发器改写。
  跨触发器传参用 `TrigArgSet*/Get*`（DataTable 具名键值），且被调方应在函数第一件事就读取。
- **`TriggerAddEvent*` 必须作用在已存在的 trigger 上**，通常在 InitMap 阶段完成；
  不要在触发器自身执行期间给它加事件。

### 2.14 Game (`cmlib_game`)
| 函数 | 说明 |
|---|---|
| `fixed GameMissionTime()` `GameMissionMinutes/Seconds` `GameMissionTimePause/IsPaused` `GameMissionTimeRemaining/SecPassed` | 任务计时（分:秒拆解、暂停、剩余/已过） |
| `GameSpeedSet/Get/Lock` `GameTimeScaleSet/Get` `GameSlowMotion(scale,hold)` | 游戏速度 / 全局时间缩放 / 慢动作（内部用 Wait） |
| `GameTimeOfDayGet/Set/Pause/IsPaused/Length` `GameLightingSet(id,blend)` `GameLockAmbience` | 昼夜与光照 |
| `GameEndForPlayer/ForPlayers/AllActive` `GameVictory/Defeat` | 胜负结算（玩家集走 `playergroup`） |
| `GameCheatsOn(cat)` `GameDevMode()` `GameDebugAllowed(opt,player)` | 作弊 / 调试门禁 |
| `VisReveal/Permanent/Explore/Hide` `VisRevealForPlayers` `VisIsVisible` `VisFog/MaskEnable` `VisRevealMapForPlayer` | 视野 / 迷雾 |
| `RevealerCreate/Enable/Destroy/Refresh` | 可复用持久揭示器 |
| `CreepAdd/Remove/At` `CreepSpeedSet(type,percent)` | 蔓延（Creep） |

### 2.15 Conv (`cmlib_conv`)
| 函数 | 说明 |
|---|---|
| `TransFromUnit/UnitType/Model/Movie/None` | 构造通讯来源 |
| `TransSay/SayTimed/SayToPlayer/Subtitle/UnitSay` | 发送台词（`playergroup` 维度，可 `waitUntilDone`） |
| `TransLast/Wait/WaitLast/IsDone/Clear/ClearAll/ClearFor/PlayerBusy` `TransSequence2` | 通讯控制 / 串行流水线 |
| `ConvCreate/Last/Show/Destroy/DestroyAll/VisibleFor` | 对话实例 |
| `ConvReplyAdd/SetText/SetState/State/Clear` | 分支回复 |
| `ConvBindUnit/Portrait` `ConvStateCount/At/Name` | 战役对白数据表接线 |

### 2.16 UData (`cmlib_udata`)
所有 `Get*` 带 fallback + 越界保护；字段缺失走日志告警。
| 函数 | 说明 |
|---|---|
| `UDataCount` `UDataAt/Has/IndexOf` | 实例枚举与查找 |
| `UDataFieldCount/At/Exists/Values/Writable` | 字段元信息 |
| `UDataInt/Fixed/String/Text/GameLink/Unit` `UDataIntAt/FixedAt/StringAt` | 读取 |
| `UDataSetInt/Fixed/String/IntAt` | 写入（仅可写字段，否则告警跳过） |
| `UDataSumInt/MaxInt` `UDataFindByInt/ByString` | 配置表聚合查询 |
| `string UDataUserInstance(type,instance,field,index)` | 读 UserData 表里某实例的字段（数据表驱动配置的读取端），任一入参为空返回 `""` |

### 2.17 Stock (`cmlib_stock`)
电脑 AI 的「攒出来」层（`cmlib_ai` 是「打出去」层）。**必须 `include "TriggerLibs/AI"`**，否则整个 MapScript 静默编译失败。
| 函数 | 说明 |
|---|---|
| `StockSet/Add/SetOpt/SetAtTown/NextIf/Extra/Supply/Workers` `StockTechNext` `StockTown/Expand` | 建造库存（设定/增减/城镇/分矿） |
| `StockArmyAdd/Scale/Replace/Batch(spec)` | 军队配方（Batch 走 CSV `"Marine:5,..."`） |
| `TechCount/Built/Pending/Has` | 科技计数（多口径语义化） |
| `TechUnitAllow/Batch(csv)/Allowed/Count` `TechUpgrade*/Ability*/BehaviorAllow` | 科技树开关（单位/升级/技能/行为） |
| `TechRequirements/RestrictionsEnable` `TechUnlockAll/RestoreRules` | 全局科技树开关 |
| `AIVarSet/Get/Bump` | AI 用户变量（**仅电脑 AI 玩家有效**，人类玩家 Get→0 不崩） |
| `AIEnableStock(player)` / `AIClearStock(player)` | 库存总开关（启用 / 清空某玩家 AI 自动库存系统，AISetStock* 的顶层开关） |

### 2.18 Board (`cmlib_board`)
「面板效果」专项 —— 自定义排行榜（Board）+ 任务结算面板（VictoryPanel）。
缺口来源：全量 mod 扫描（1696 个 .galaxy）显示这两块 **零覆盖**，合计 1000+ 次调用
（`VictoryPanelAddCustomStatisticLine` ×578 / `BoardItemSetText` ×457 / `BoardCreate` /
`BoardSort` …），此前没有任何封装。常量：`CMLIB_BOARD_HEADER=-1`（表头行）/
`CMLIB_BOARD_ALL=-2`（整行/整列）/ `CMLIB_BOARD_NONE=0`（无效句柄）。
| 函数 | 说明 |
|---|---|
| `int CMLib_BoardCreate(cols,rows,name)` / `CreateColored(...,r,g,b)` / `Quick(name,headersCsv,players)` | 建面板；失败返回 `CMLIB_BOARD_NONE` 并写 error 日志（原生静默） |
| `bool CMLib_BoardValid(board)` / `void CMLib_BoardDestroy(board)` | 句柄守门（所有函数内部先过此关）/ 安全销毁（无效句柄直接返回） |
| `BoardShow/ShowAll(board,players,show)` / `BoardAnchor/AnchorTopRight/AnchorTopLeft/AnchorTop` / `ResetPosition/Resize/ColumnWidth` | 显示 / 锚定九宫格 / 运行时扩表 |
| `BoardTitle/TitleShow/TitleColor` | 标题文字 + 图标 + 可点击 + 颜色 |
| `BoardCell(board,col,row,text)` / `CellInt` / `CellFixed` / `CellColor` / `CellBackColor` / `CellIcon` / `CellAlign` / `CellFontSize` | 单元格逐项设置 |
| `BoardCellProgress(board,col,row,min,max,value,r,g,b)` / `CellProgressHide` | 进度条（一次配齐 Show+Range+Value+Color 四步；`max<=min` 自动兜底区间） |
| `BoardHeaders(board,csv)` / `BoardRow(board,row,csv)` / `RowInt` / `RowClear` | CSV 批量填表（一行一整排） |
| `BoardPlayerColumn(board,col,byTeams)` / `PlayersAdd/Remove(players)` / `PlayersAddActive` | 玩家列 / playergroup 批量加玩家 |
| `BoardSort(col,asc)` / `SortSecondary` / `SetState` / `Minimizable` / `Minimize` | 排序（主/次）/ 可最小化 |
| `CMLib_VPanelVictoryText/Mission/Time/Reward/StatisticsTitle/AchievementsTitle` | VictoryPanel 文案（全局单例，无句柄） |
| `CMLib_VPanelStat/StatInt/StatFixed(label,value)` / `StatBatch(csv)` / `StatClear` | 自定义统计行（`StatBatch("击杀:42,资源:3200,用时:12:30")` 按**第一个**冒号切，值可再含冒号） |
| `CMLib_VPanelTracked(stat)` / `TrackedBatch(csv)` / `Visuals(planet,bg,summaryBg)` | 追踪统计 / 星球与背景模型 |
| `CMLib_VPanelOnExit/OnPlayAgain(trigger,player)` / `int VPanelPickedDifficulty()` | 结算面板退出/再玩事件 + 读取所选难度 |

> **故意不封装**两类 API（分析结论，不是遗漏）：
> - `StatEvent*`（`StatEventCreate`/`StatEventSend`/…）只声明在 `natives_missing.galaxy`，
>   该文件**不被任何引擎库 include** → 直接调用会因符号未声明而编译失败、整段 MapScript 被丢弃。
> - `Achievement*`（`AchievementAward`/…）原生标注 `// Blizzard maps only` → 自定义地图调用无效。

### 2.19 Buff (`cmlib_buff`)
Behavior（增益/减益）与状态开关专项。缺口来源：`gap_scan.py` 显示 `UnitBehaviorAdd/Remove`
族与 `UnitSetState`/`PlayerSetState` 在 mod 里高频裸用，但**三处坑没人处理**：
① `UnitBehaviorRemove` 少传一次就残留一层；② `c_unitState*` 里有一批是 **Read-only**，
写进去静默无效；③ `PlayerGetState` 对部分 state 读不回来。本模块逐一封起来。

| 函数 | 说明 |
|---|---|
| `bool BuffAdd(u,buff,caster,count)` / `int BuffRemove(u,buff,count)` / `int BuffSetCount(u,buff,caster,target)` | 增删到指定层数（`SetCount` 自动算差值，多退少补） |
| `int BuffStripAll(u,buff)` | 一次剥干净（内部循环到 count=0，返回实际剥掉层数）—— 解决"少传一次残留一层" |
| `int BuffCount` / `bool BuffHas` / `int BuffCountAll(u)` / `string BuffNameAt(u,i)` / `bool BuffEnabled` | 查询与遍历 |
| `fixed BuffTimeLeft(u,buff)` / `bool BuffAddTimed(u,buff,caster,secs)` / `BuffRefresh` / `BuffExtend` | 计时类 buff：加带时长 / 刷新 / 延长 |
| `bool BuffHasFlag(buff,flag)` / `BuffPurgeFlag(u,flag)` / `string BuffFindByFlag(u,flag)` / `bool BuffAnyWithFlag(u,flag)` | 按 Catalog 标记批量驱散（做"净化/解控"技能的正确姿势） |
| `bool BuffTransfer(from,to,buff,count)` / `int BuffAddGroup(group,...)` / `int BuffStripGroup(group,buff)` / `int BuffAddCSV(u,caster,"A:2,B:1")` | 转移 / 批量 / CSV 规格串（避开数组形参硬约束，见 §2.6） |
| `bool UStateIsReadOnly(state)` | **写前守门**：命中只读 state 直接返回 false + 写 error 日志，不再静默失败 |
| `bool UStateSet/UStateGet/UStateToggle(u,state,...)` / `int UStateSetGroup(group,state,v)` | 单位状态开关（全部走只读守门） |
| `UnitInvulnerable/Hide/Pause/Selectable/Targetable/StatusBar/Stun/Silence/UsingSupply(u,on)` / `UnitGhostMode(u,ghost)` | 语义化常用开关；`GhostMode` = Hide+Pause+Targetable 三连（做"暂存单位"的标准组合） |
| `bool UnitUnderConstruction/Cloaked/Hallucination/InTransport/IdleState/DeadState/Buried(u)` | 只读状态查询（这些本来就只能读） |
| `bool PStateSet/PStateGet(player,state,fallback)` / `int PStateSetGroup(players,state,v)` | 玩家状态开关；**`PStateGet` 带影子缓存**——引擎对部分 state 读不回，读不到时回落到本库写入时记录的值，仍无记录才用 `fallback` |
| `PlayerFreeCost/PauseCooldowns(player,on)` / `PlayerShowScore/GivesBounty/InLeaderPanel(player,on)` | 玩家级常用开关语义化 |

> `UStateIsReadOnly` 的名单直接对照 `natives.galaxy` 里标了 `Read-only` 的 `c_unitState*`
> 常量整理。写只读 state 在引擎里**不报错也不生效**，是"改了没反应"这类问题的常见根因。
### 2.20 Path (`cmlib_path`)
地形可通行性查询 + **Route（路线）可视化编排**。Route 是 SC2 自带但极少人用的一套原生
（`RouteCreate`/`RouteAddWaypoint`/`RouteShow`…），做"进攻路线预览""空投航线指示"时比手搓
一堆 Actor 干净得多，但原生 API 分散且参数多，本模块把它收成"设一次全局样式 + 一行出路线"。

| 函数 | 说明 |
|---|---|
| `int PathingAt(point)` / `string PathingName(pathing)` | 某点的通行类型（原始 int）/ 类型名 |
| `bool PathingIsGround/IsBlocked/IsCliff/IsBuilding(point)` | 语义化判定：可走地面 / 完全不可走 / 悬崖 / 已被建筑占位 |
| `int RouteQuick(fromPoint,toPoint)` / `RouteQuickToUnit(fromPoint,unit)` | 一行出一条默认样式路线，返回 route id |
| `int RouteForUnit(unit,toPoint)` / `RouteForUnitType(unitType,player,from,to)` | 以某单位/某单位类型的移动能力算路线（会考虑飞行/地面差异） |
| `RouteSetFromPoint/SetFromUnit/SetToPoint/SetToUnit(route,...)` | 起终点改写（起终点可以是动态单位，路线自动跟随） |
| `point RouteFromPoint/ToPoint(route)` / `unit RouteFromUnit/ToUnit/RouteUnit(route)` | 起终点回读 |
| `RouteAddWay(route,point)` / `int RouteAddWayChain(route,csv)` / `RouteClearWays(route)` | 途经点：单个 / CSV 批量（避开数组形参硬约束，见 §2.6）/ 清空 |
| `RouteNoFlyAdd(route,region)` / `RouteNoFlyClear(route)` | 禁飞区（让路线绕开） |
| `RouteShow(route,show)` / `RouteShowAt(route,player,show)` / `bool RouteVisibleAt(route,player)` | 显隐（全局 / 按玩家）与回读 |
| `RouteColor(route,color)` / `RouteColorAt(route,player,color)` / `color RouteColorGet(route)` | 线色（全局 / 按玩家） |
| `RouteLineTexture/LineWidth/LineTile(route,...)` + 对应 `*Get` | 线的贴图 / 宽度 / 平铺密度 |
| `RouteStepModel/StepScale/StepMid(route,...)` + 对应 `*Get` | 步进标记的模型 / 缩放 / 中点标记 |
| `RouteMinSteps/MinLinear/MinTravel(route,...)` + 对应 `*Get` | 最少步数 / 最小直线距 / 最小行进距（控制标记密度） |
| `RouteAbilFilter(route,abilFilter)` | 按能力过滤（如只画能走"跳跃"的路线） |
| `bool RouteOk(route)` / `int RouteLast()` / `RouteDestroy(route)` / `RouteDestroyAll()` | 有效性 / 最近一条 / 单个销毁 / 全清 |

> Route 全族**都对无效 id 守门**，销毁后再调任何 setter 都是 no-op，不会崩。

### 2.21 Env (`cmlib_env`)
环境层：装饰物（Doodad）、地形贴图、水面、战争迷雾**外观**（注意与 `cmlib_game` 的
迷雾**可见性**区分——这里改的是"看起来什么样"，那边改的是"能不能看见"）。

| 函数 | 说明 |
|---|---|
| `doodad DoodadById(id)` / `actor DoodadActor(doodad)` / `actorscope DoodadScope(doodad)` | 装饰物句柄与其 Actor / ActorScope |
| `bool DoodadShow/DoodadAnim/DoodadTint/DoodadScale(doodad,...)` | 显隐 / 播动画 / 染色 / 缩放（全部走 Actor 消息，无效句柄返回 false） |
| `bool DoodadSend(doodad,msg)` / `DoodadSendText(doodad,msg)` / `int DoodadSendRange(region,msg)` | 直接发 Actor 消息（单个 / 文本形式 / 区域内批量，返回命中数） |
| `bool DoodadDestroyFx(doodad)` | 带特效销毁（而不是硬删，观感差别很大） |
| `string TerrainTextureAt(point)` / `bool TerrainIsTexture(point,name)` / `TerrainShow(players,show)` | 地形贴图查询与整体显隐 |
| `bool WaterMorph(water,duration)` / `WaterPause(water,pause)` | 水面形态过渡 / 暂停（做涨潮退潮） |
| `FogEnable(enable)` / `FogDisableAtUltra(disable)` / `FogClear()` | 迷雾外观总开关（`AtUltra` 是给高画质档单独关的，原生里很容易漏） |
| `FogPreset(preset)` / `FogPresetOver(preset,duration)` | 预设整套外观（瞬时 / 过渡） |
| `FogColor/Density/FallOff/StartHeight(v)` + 各自的 `*Over(v,duration)` | 逐参数调：颜色 / 浓度 / 衰减 / 起始高度，均有瞬时与过渡两个变体 |

### 2.22 Stat (`cmlib_stat`)
统计与元信息：成就、分数、难度名、**效果历史（EffectHistory）**、战役模式、真实时间戳。

| 函数 | 说明 |
|---|---|
| `AchAward(ach)` / `int AchAwardGroup(players,ach)` / `AchErase(ach)` | 颁发 / 批量颁发 / 撤销 |
| `AchDisable(ach,disable)` / `AchDisableGroup(...)` / `bool AchDisabled(ach)` | 屏蔽（做"本关不计成就"） |
| `AchTermSet/AchTermAdd/AchTermTick(ach,term,...)` | 进度项：设值 / 增量 / +1 |
| `text AchPercentText(ach)` / `AchPanelShow(players,show)` / `AchPanelCategory(players,cat)` | 进度文本 / 成就面板显隐与分类 |
| `ScoreEnable(score,on)` / `ScoreEnableAll(on)` | 分数项开关 |
| `ScoreSetInt/SetFixed/AddInt/AddFixed(player,score,v)` / `int ScoreSetIntGroup(players,score,v)` | 分数读写（int / fixed 两套，避免定点数陷阱） |
| `int ScoreGetInt(...)` / `fixed ScoreGetFixed(...)` | 分数读回 |
| `bool DiffEnabled(diff)` / `int DiffOfPlayer(p)` / `DiffSetPlayer(p,diff)` / `int DiffAPM(diff)` | 难度档位查询与设置 / 该难度的 AI APM |
| `text DiffName(diff)` / `DiffNameCampaign(diff)` / `DiffNameOfPlayer(p)` | 难度显示名（普通 / 战役口径 / 按玩家） |
| `effecthistory EffHist(...)` / `int EffHistCount/EffHistLast(...)` | 效果历史句柄与计数（"谁打了我 / 我打了谁"的权威来源） |
| `EffHistType/EffHistAbil/EffHistEffect/EffHistWeapon/EffHistUnitAt/EffHistTime/EffHistAmountInt/EffHistAmountFixed` | 逐条读：类型 / 技能 / 效果 / 武器 / 单位 / 时间 / 数值 |
| `string EffHistLastEffectOf(unit)` | 最近一次作用在某单位上的效果 id（做"死于什么"判定） |
| `CampaignMode(on)` / `CampaignInitAI()` / `CampaignFinished()` / `CampaignTutorialFinished()` | 战役模式与生命周期 |
| `CampaignSavesEnable/CompletedSavesEnable(on)` / `CampaignDeleteSave(name)` | 战役存档开关与删除 |
| `CampaignImage(img)` / `CampaignText(t)` | 战役 UI 图/文 |
| `int NowEpoch()` / `StartEpoch()` / `RealElapsedSecs()` / `EpochField(field)` / `string EpochStamp()` | **真实世界时间**（不是游戏内时间）：当前 / 开局 / 已过秒数 / 年月日时分秒分量 / 格式化戳 |
| `int B2I(b)` / `bool I2B(i)` | bool ↔ int 互转（Galaxy 没有隐式转换，写 bank 时天天要用） |

**StatEvent 遥测（round23 新增）** —— 原生 `StatEvent*` 六件套的守门封装。

> ⚠️ **先读这段再决定用不用**：`StatEventCreate` 在**非暴雪签名内容**里**恒返回 0**
> （三档真机矩阵实测，见 §10.4）。0 = 无效句柄，于是本组所有 Add/Send 都会在守门处
> 早退 —— 在你我的地图/mod 里，**整组封装等价于安全 no-op**。
> 引擎注释 "Blizzard only. Sends the Stat Event to Battle.net." 是字面意思。
> **要做自己的埋点，请用 `cmlib_bank`（持久化）或 `cmlib_stock`（局内统计），别用这组。**
> 保留它的唯一理由：移植暴雪官方内容时保持调用点形态一致，且**不会崩**。

只保证可调用，不保证上报。客户端观测不到投递结果，所以本组封装只对
「句柄有效性 / 键名非空 / 是否重复 Send」负责，不对上报成功与否作任何承诺。

| 函数 | 说明 |
|---|---|
| `int StatEvtBegin(name)` | 建事件，名字为空直接返回 0（不调原生）。返回句柄，0 = 无效 |
| `bool StatEvtOk(ev)` | 句柄是否有效且未 Send —— **所有 Add/Send 前的唯一守门** |
| `StatEvtStr/StatEvtInt/StatEvtFixed(ev,key,v)` | 挂数据。句柄无效或 key 为空一律早退，不调原生 |
| `bool StatEvtSend(ev)` | 投递。内部走环形缓冲拦重复 Send（同一句柄 Send 两次，第二次返回 false） |
| `int StatEvtLast()` | 最近创建的事件句柄。**已 Send 过的也会被返回**，拿到后仍要过 `StatEvtOk` |
| `int StatEvtStrCSV/StatEvtIntCSV(ev,spec)` | `"k1:v1,k2:v2"` 批量挂载，返回成功条数（与 `VPanelStatBatch` 同款 CSV 口径：第一个冒号切） |
| `bool StatEvtSendCSV(name,spec)` | 一行完成 建 → 批量挂 → 投递 |
| `bool StatEvtSendInt(name,key,v)` | 单键整数事件的一行式写法 |
| `int StatEvtCsvCount(spec)` | **纯解析**：数 `"k1:v1,k2:v2"` 里的合法键值对条数。不碰引擎、不要句柄，因此**在任何环境都可用**，也是本组唯一能被真机断言直接验证的函数 |

> 为什么不自己 `native` 声明这六个函数：SC2 的 native 符号表是引擎内建的，
> 库里再声明一遍反而会和引擎符号撞名（`check_cmlib` 第 1c 项致命项）。
> 直接裸调即可，判据见 §9.1 / §10.1。


---

## 3. 设计约定

- **强类型 + fixed**：整数除法、百分比、插值一律用 `IntToFixed`/`FixedToInt` 与 `CMLib_Div*`
  的 fallback 形态，避免定点数陷阱。
- **日志分级**：`CMLIB_LOG_*` 常量控制输出，`CMLib_LogLevel` 全局量默认 `CMLIB_LOG_WARN`。
- **DataTable 键名**：用 `Key1/Key2/Key3/KeyPlayer/KeyIndexed` 统一拼装，避免命名冲突；
  `StoreHas` 先判存在，规避原生 Get 的静默 0。
- **遍历安全**：UnitGroup 倒序（`UnitGroupUnitFromEnd` 从 count→1），可在回调内安全删除成员。
- **空值保护**：UI/Catalog 接口对无效控件、缺失条目、无 fallback 的读取一律走日志返回，
  不抛原生异常。

---

## 4. 静态校验说明（重要）

本库用项目内 `tools/analysis/galaxy-lint.mjs`（sc2-galaxy-lang TypeChecker 驱动）做过校验。
**结论：库代码本身 0 类型错误、0 语法错误。**

首次直接对库目录跑 lint 会报约 209 条诊断，但这些**全部是独立 checker 的环境性误报**，根因如下：

1. **引擎 natives 未可达**：独立 checker 通过 `include` 链解析全局符号，不自动加载
   `natives.galaxy`。本库遵循真实 SC2 约定（不显式 include natives），故 `IntToString`、
   `CatalogFieldValueGet`、`DataTable*`、`DialogControl*` 等被误报 "Undeclared"。
   → 在验证副本中补 `include "TriggerLibs/natives"` 后全部消解。
2. **GameData 常量未加载**：checker 只加载 `GameData/Game.galaxy`，未加载同目录的
   `Upgrade.galaxy` 等，导致 `c_gameCatalog*`、`c_upgradeOperation*`、`c_playerTypeNeutral/Hostile`
   被误报。这些常量在真实 SC2 中由引擎自动提供。
3. **跨文件定义需显式 include**：真实 SC2 把 mod 内所有 .galaxy 视为同一编译单元，
   本库 `cmlib_catalog` 通过 `include "scripts/cmlib/cmlib_core_h"` 即可见
   `CMLib_LogError` 的声明；但独立 checker 要求 *实现* 也被传递 include，否则报
   "hasn't been defined"。属 checker 行为差异，非库缺陷。
4. **funcref typedef 触发 checker 崩溃（G901）**：`cmlib_unit`/`cmlib_player`/`cmlib` 因
   定义了 `funcref` 回调类型，被 sc2-galaxy-lang 的 checker 在递归类型解析时崩溃
   （`Cannot read properties of undefined (reading 'parameters')`），从而**吞掉**其全部诊断。
   该崩溃与业务逻辑无关——语法校验（`--no-type-check`）确认这 3 个文件 0 语法错误，
   且 `funcref` 回调模式与暴雪 `VoidCampaignLib.galaxy` 一致。

**验证方式（可复现，已脚本化）**：`src/lib/build_typecheck_unit.py` 把 18 个模块 + 自测脚本 +
MapScript 合并成单个编译单元 `.cache/cmlib-typecheck/cmlib_unit_all.galaxy`（5265 行），再跑
lint。模块清单**不是手抄的**，而是由 `discover_modules()` 从聚合入口 `cmlib.galaxy` 的
include 列表正则推导 —— 手抄清单曾经导致 trig 模块漏检、静态全绿但真机静默失败。

```bash
python src/lib/build_typecheck_unit.py
node tools/analysis/galaxy-lint.mjs .cache/cmlib-typecheck/cmlib_unit_all.galaxy --format text
# => 合计: 3 条 (0 错误, 0 警告, 3 建议)   ← 3 条均为未使用局部变量
```

因此本库可安全 `include` 进任意依赖 `core.sc2mod` 的 mod/地图使用。

### 4.1 门禁总入口 `gate.py`（round18 新增，**唯一合法的静态验收方式**）

以前关卡分散在几个脚本里，靠人记得挨个跑 —— 结果 round16 起有两轮**只跑了
`check_cmlib.py` 就宣布"静态全绿"**，而它压根不做类型检查，直接放行了一个编译期
致命错误（详见 §5.6）。现在统一入口：

```bash
python src/lib/gate.py          # 9 关全跑，任一关不过即非零退出
python src/lib/gate.py --fast   # 只跑 1~6 关；⚠️ 此模式的 PASS 不可作为交付依据
```

| 关卡 | 脚本 | 能抓什么 | 抓不到什么 |
|---|---|---|---|
| 1 | `test_verdict_order.py` | **判定链本身**：sentinel 门必须排在所有次级判据之前（round22 新增，见 §9.3） | 库的任何问题（它查的是验收工具） |
| 2 | `test_console_encoding.py` | **门禁自身的环境依赖**：常驻脚本在 GBK 控制台打印非 GBK 字符会崩溃成假 FAIL（round24 新增，见 §11.7） | 同上（它查的也是验收工具） |
| 3 | `check_cmlib.py` | 符号存在性 / 实参**个数** / 返回类型盲区 / 文档漂移 / 注释里的假常量 | **实参类型** |
| 4 | `check_native_ledger.py` | **受管 native 族的覆盖台账**：每个引擎符号必须「已封装」或「显式登记拒绝」，漏一个报 ghost（round25 新增，见 §13） | 封装得对不对（那是真机矩阵的事） |
| 5 | `check_g1001.py` | 局部变量未置顶（静默丢图形态之一） | 同上 |
| 6 | `verify_natives.py` | 引擎符号存在性 / 实参个数 / `c_*` 常量，**不受 lint 抑制规则影响**（round19 新增） | 类型 |
| 7 | `build_testmap.py` | 刷新 `_testmap_build`（下一关的输入） | — |
| 8 | `build_typecheck_unit.py` | 把 21 模块 + selftest + MapScript 并成单一编译单元 | — |
| 9 | `galaxy-lint.mjs` | **全量类型检查** —— `color == null`、`int x = Round(fixed)` 这一类 | funcref 家族（被第 8 关剔除） |

第 9 关是唯一能抓住「类型层编译期错误」的关卡。它用的两个工具仓库里一直都有，
**只是过去没被接进门禁 —— 工具存在 ≠ 关卡存在**。

**前两关都不查库，查的是验收工具自己。**
第 1 关：真机矩阵的 PASS/FAIL 由 runner 的分支顺序和 `classify()` 共同决定，这两处
一旦错位，后面所有关卡跑出来的结论全都失去意义（round22 实测：反向对照被打哑，
排假阳性的防线被悄悄拆掉，详见 §9.3）。
第 2 关：门禁的结论**不允许随调用者的环境变量摇摆**。round24 实测同一份代码在
`PYTHONIOENCODING=utf-8` 下 ALL PASSED、在裸 GBK 控制台下 `verify_natives` FAILED
（详见 §11.7）。两关都纯静态秒跑。

> **`--fast` 的边界也随之变化**：它跳过第 7~9 关（构建 + 类型检查）。
> 类型层错误只有第 9 关抓得到，所以 `--fast` 的 PASS 永远不能当交付依据。

---

## 5. 真机运行时验证（比静态校验更硬的证据）

静态 lint 只能证明"能解析"，**证明不了 SC2 引擎会真的编译并执行**。SC2 遇到某些错误
（最典型的是**函数重定义**）会**静默丢弃整个 MapScript**：不报错、不写日志、`InitMap()`
根本不被调用。本库为此建了真机取证回路。

### 5.1 取证设计

自测脚本 `cmlib_selftest.galaxy` 把结果编码成**可观测单位**，通过 SC2 API 的
raw observation 读回 —— 不依赖日志、不依赖 bank 子系统、不依赖账号态：

| 单位 | 含义 |
|---|---|
| Ghost ×1 | MapScript 编译成功且 `InitMap()` 被引擎调用（哨兵） |
| Marine ×1 | `cmlib_unit` 模块（`CMLib_SpawnForced`）生效 |
| Marauder ×N | N 项模块断言通过（round15 基线满分 **195**；round17 源码静态计数已达 **308**，真机待复验。观测 Marauder 数必须 == bank 自报 `Result/Passed`，见 §5.2.1） |
| Reaver ×1 | 「发射物命中→生成限时单位」能力探针的源单位真机在场（见 §5.2 说明） |
| Thor ×1 | 全部断言通过 |
| Battlecruiser ×1（加分） | 无 AI 玩家 `AIVar` 安全回退（Get→0、不崩） |
| Banshee ×1（加分） | `cmlib_stock` 的 `AISetStock` 通路存活 |

辅助通路：`CMLibRuntimeTest.SC2Bank` 写入魔数 `Result/Magic=13371337`。

### 5.2 三档验证矩阵

| 形态 | 构建 | CMLib 来源 | 最近一次实测（round15，195 条基线） |
|---|---|---|---|
| 内联源码版 | `build_testmap.py` → `test_cmlib.SC2Map` | 43 个 .galaxy 打进地图 | **PASS 195/195**（含金甲虫炮弹命中→限时单位全链 6 项） |
| 依赖挂载版 | `build_depmap.py` → `test_cmlib_dep.SC2Map` | mod 依赖 `file:Mods\CMLib\CMLib.SC2Mod` | **PASS 195/195** |
| 反向对照 | `build_depmap.py --negative` | 依赖指向不存在路径 | **FAIL 0/195**（`game_loop=0`，地图起不来） |

反向对照是必须的：没有它，正向 PASS 无法排除缓存/残留造成的假阳性。

> ✅ **round20 矩阵已出结论（并非全绿）**：守候进程在真人对局结束后自动跑完，
> 内联 / 依赖两档均为 **PARTIAL 499/504**，反向对照 FAIL 0/504（符合预期）。
> 失败标签 3 条：`unit.weapon.period`、`unit.weapon.damage`、`conv.activesound.notnull`
> （另外 2 条差额是未触发的事件断言，属 §5.2.1 已定性的非致命类）。
> **这三条恰恰证明了"静态全绿 ≠ 真机能跑"—— 它们连过五道静态门禁**。
>
> ✅ **round21 矩阵已闭环**：三条失败已定位并修复（见 §8），库扩到 21 模块 /
> **1241 个声明**（新增 `CMLib_StrIsEmpty` / `CMLib_StrNotEmpty`），自测断言
> 505 → **511 条**。三档矩阵：内联 / 依赖两档 **PASS 509/509**（bank 自报），
> 反向对照 **FAIL 0/509**（符合预期）。511 与 509 的差额当时记为"事件断言未触发"，
> **这个归因在 round22 被证伪，真相是两组 if/else 互斥分支，见 §5.2.1**。
>
> ✅ **round22 已闭环（2026-08-09 22:31）**：四件事。
> ① **断言会计翻案**——新增 `expected_asserts.py`，把"执行数 ≤ 静态数"的模糊下限
> 升级为 `511 − 2 = 509` 的**精确判等**（§5.2.1）；
> ② **补齐 35 个单位/建筑/面板域封装**（unit 编队 / 载货 / 状态条分组 / 缩放 / 老兵，
> ui 警报 / 滚屏 / 菜单 / 控件，board 计分板，panel 计时器窗口 / 任务目标，fx Actor 层，
> catalog 引用改写，core fixed 数学），全部取自 core `natives.galaxy` 的范围内符号；
> ③ **`StatEvent*` 范围判定翻案已获真机背书** —— `probe_statevent.py` 三档全 PASS，
> 判定 `USABLE`（§9.1）；
> ④ **判定链缺陷已修 + 钉成门禁第 1 关** —— ① 落地时把新判据插在了 sentinel 门前面，
> 反向对照被打哑成 PARTIAL、排假阳性防线被拆（§9.3）。
>
> 静态：`gate.py` **ALL PASSED**（7 关，typecheck errors = 0）、`check_cmlib.py`
> **PASSED 0 错 0 警**（43 文件 / 21 模块 / **1294 实现** / **1277 声明** / 3997 调用点，
> 已校验实参 3992 处）、`API_INDEX.md` 已重生成无漂移。
>
> 真机：四件产物按 round22 源码重建后（`CMLib_out.SC2Mod` 241873B —— 比 round21 的
> 228604B 大出来的正是那 35 个封装）**三档矩阵全绿 `rc=0`**：
>
> | 形态 | 期望 | 实得 |
> |---|---|---|
> | 内联源码版 `test_cmlib.SC2Map` | PASS | **PASS 509/509**（精确吻合） |
> | 依赖挂载版 `test_cmlib_dep.SC2Map`（地图内库文件 0） | PASS | **PASS 509/509** |
> | 反向对照 `test_cmlib_neg.SC2Map` | FAIL | **FAIL**（Ghost=0 且 bank 无 Magic） |
>
> 注意第一次跑出来的 `rc=1` **不是库的问题**（单跑内联档当场 PASS 509/509），
> 是验收工具自己的判定顺序缺陷 —— 详见 §9.3，这是本轮最值得记的一条。

#### 5.2.1 断言计数口径

`Marauder ×N` 的 N 必须同时满足两件事才算证据成立：

1. **源码静态计数 == 真机执行计数**（`grep -c CMLibTest_Mark` == 观测 Marauder 数）；
2. **观测数 == bank 自报** `Result/Passed`，且 `Result/FailTags` 为空。

只满足其一都不算。历史上「双记」bug 就是靠第 1 条抓出来的：AI 线自己 spawn 了 6 个
Marauder，主线又整体 spawn 一遍，总数虚高 6——**虚高会吃掉真实失败**，让证据链变成
假阳性护盾（详见 §5.3）。

**195 项断言分布（源码静态计数 == 真机执行计数，二者严格 1:1，详见下「双记修正」）**：
Ghost×1（`InitMap` 哨兵）+ 18 模块各 ≥1 项核心断言 + unit 的 12 项新封装（含 `UnitOrderAt`/
`UnitOrderHasAbil`/`SelClear`/`UGSelected`/`UGFilterStr`）+ AI 的 6 项新封装
（`AIAttackWaveAddUnits`/`AISetFlag`/`AIGetTime`/`AICounterUnitSetup` 与 `AIEnableStock`/`AIClearStock`）
+ stock 的 `AISetStock` + 第 9 轮面板消息/警报/淡变/HUD + catalog 全表遍历 + unit 归属/下令/同盟组
+ player 静态属性 + 外部 galaxy 协作 agent 贡献的 region 事件等约 20 项 + 限时单位真机闭环（金甲虫
炮弹→Reaver 死亡链→`Demo_TemporaryCaster` 旋风斩狂热者，约 11 项带标签断言）+ **事件取参 native
`EvtCreatedUnit`/`EvtDmgSourcePlayer`/`EvtDmgSourceUnit`/`EvtEffectUsedUnitOwner`/`TrigExecCount`
首次真机闭环 5 项**（主线汇合 AI 线后统一计数）+ 加分项 Battlecruiser（无 AI 玩家 `AIVar` 安全回退）
+ Banshee（`AISetStock` 通路存活）。
所有断言在 `CMLibTest_Deferred`（主）与 `CMLibTest_AIDeferred`（AI 加分，隔离线程）内运行，崩了也不
影响主证据链。

- **断言计数口径修正（2026-08-09，第 14 轮）**：早期某轮曾把「观测 Marauder 数 194 vs 源码 188」
  的差解释成"catalog/单位组动态循环内断言"，这是**错误归因**。真相是**竞态导致的证据双记**——
  `CMLibTest_AIDeferred`（6s 触发）跑完自行 spawn 了 lv_aiPassed(=6) 个 Marauder，而此时主线
  `gv_cmlibPassed` 已含这 6 条，落盘时又整体 spawn 一遍。双记最阴险处在于它会**吃掉失败**：主线
  真丢 6 条时观测仍恰好达标，判定照样 PASS。修复：AI 线只"算"，主线在 `gv_cmlibAIDone` 标志汇合后
  **统一落盘 + 编码**（带 10s 超时，AI 线若挂掉不能死等）。修正后观测数 == 源码条数，严格 1:1。
  由此也把判定从"观测 Marauder ≥ 静态条数"改为以**地图自身 Thor 信号 + bank 自报**为准。

- **⚠️ 上一条的收尾理由在 round22 被证伪（2026-08-09）**。round14～round21 一直说
  "差额来自事件处理器（`OnReaverTargetDied` 等）内的 `Mark`，测试局不一定触发"，
  并据此把判定降级成**下限**（执行数 ≤ 静态数即可）。round22 把 511 个
  `Mark/MarkTag` 调用点逐一定位后发现：**它们全部落在 `CMLibTest_Deferred`(499)
  与 `CMLibTest_AIDeferred`(12) 内，事件处理器里一条都没有**。旧归因是错的。

  真实成因是**互斥分支**：两组 `if/else` 的两侧各写了一条 `Mark`，静态各计 1、
  运行时只可能走一边：

  | 位置 | 分支 A | 分支 B |
  |---|---|---|
  | `cmlib_selftest.galaxy` L1665 | `unit.abilcmd.ability.roundtrip` | `unit.abilcmd.skipped.nocatalog` |
  | `cmlib_selftest.galaxy` L2003 | `ai.state.read` | `ai.state.skipped.nocomputer` |

  所以 **511 静态调用点 − 2 互斥分支 = 509 期望执行数，这是个确定值**，不是模糊下限。

  修复不是改断言，而是**把会计做精确**：新增 `expected_asserts.py`，剥注释（保持行号
  不变）后扫描 `if/else` 两侧都含 `Mark` 的互斥对、按 `min(a,b)` 扣减，导出
  `{sites, exclusive, expected, deterministic}`；`cmlib_runtime_test.py` 在
  `deterministic=True` 时改为**精确判等**（多一条少一条都判 PARTIAL），只有检出循环内
  `Mark`（计数无法静态确定）时才退化回下限。

  > **方法论**：含糊的下限判据是**退化的隐身衣**——真丢了断言也照样 PASS。
  > 宁可花力气把期望值算准，也别用"反正 ≤ 静态数"糊过去。
  > `expected_asserts.py` 自带阳性对照（注入互斥对 +4/−2、单侧不扣减、循环内 `Mark`
  > 使 `deterministic=False`、注释剥离），4/4 通过——**校验器自身也要有校验器**。

- **"发射物→限时单位"能力探针（2026-08-08 起，用户示例：金甲虫炮弹命中后生成旋风斩狂热者）**：
  用该示例对 CMLib 做能力检测，结论：
  ① 数据层正确做法是**不替换发射物本身**，而是用 Reaver 的 Scarab Effect 触发一个
  `CEffectCreateUnit`（或搜索命中单位后 `CMLib_SpawnForced`）生成限时狂热者，再由 Behavior
  （`CMLib_BuffAddTimed`/`BuffTimeLeft`）或计时器（`cmlib_trig` 的 `TimerOnce`）在旋风斩后
  `CMLib_UnitRemove` 收尾——这是"不改源行为"前提下最稳的纯数据+库方案；
  ② 探针暴露两个真缺口并补齐：**`CMLib_UnitRemove` 此前不存在**（`CMLib_UGRemoveAll` 只删组，
  单单位移除无封装）→ 新增 `void CMLib_UnitRemove(unit)`（同步 `UnitRemove`，null/失效守门）；
  **`CMLib_UnitOrderAbility`（单单位自我下令）此前未被真机验证**（selftest 只覆盖了 unitgroup 形式）→
  本次注入断言后真机验证通过。
  ③ **数据取证修正**：`VoidZealotWhirlwind` 是 `CAbilEffectInstant`（**自我施放**，非点目标），
  能放旋风斩的单位是 `ZealotAiur`（基础 `Zealot` 无技能），下达命令须用
  `CMLib_UnitOrderAbility(z, "VoidZealotWhirlwind", 0, c_orderQueueReplace)` 而非 `...AtPoint`。
  ④ **本轮（2026-08-09）把孤立断言升级为真机闭环**：不再"生成即移除"，而是在
  `CMLibTest_Deferred` 内 `SpawnForced("ZealotAiur")` → 下令 `VoidZealotWhirlwind` →
  `CMLib_WaitGame(2.5)`（限时存活窗口）→ 验证 `UnitOk==true`（demo.temp.alive）→
  `CMLib_UnitRemove` → 验证 `UnitOk==false`（demo.temp.despawn）；并新增通用可复用函数
  `CMLibTest_Demo_TemporaryCaster(unitType, ability, lifetime, pos, player)`
  （参数化，不绑定任何具体游戏功能，封装"生成→自施法→限时→移除"范式，含 `CMLib_WaitGame` 内部计时）。
  5 项带标签断言（demo.temp.spawn / demo.temp.order / demo.temp.alive / demo.temp.despawn /
  demo.temp.helper）全部真机通过。
  ⑤ **把金甲虫真正拉进图里跑通原示例（2026-08-09）**：此前的闭环只验证了「限时单位」下半段，
  始终没有真正的发射物源头（用户原话：*"都没看到金甲虫"*）。本轮补齐上半段——
  `SpawnForced("Reaver", 1, …)` 生成金甲虫 → 生成 1 血敌对假人 →
  `CMLib_TrigOnUnitDied` 注册假人死亡事件 → `CMLib_UnitOrderAbilityAtPoint(reaver,"attack",…)` 下令攻击
  → 引擎自动发射 Scarab 命中击杀 → 死亡回调里调用
  `CMLibTest_Demo_TemporaryCaster("ZealotAiur","VoidZealotWhirlwind",1.5,…)` 生成限时旋风斩狂热者。
  6 项带标签断言（demo.reaver.spawn / target / order / chain / targetdead / alive）全部真机通过，
  raw observation 里 `Reaver: 1` 常驻、`Marine` 计数 3→4→3（假人刷出→被炮弹打死）双向坐实。
  三档矩阵全 **PASS 195/195**。
  **全程零数据特化**：`Campaigns/Void.SC2Campaign` 依赖里本就带完整 Reaver CUnit（3831 B），
  测试地图自身的 `UnitData.xml` 不需要注入任何单位数据。

```bash
python src/lib/build_mod.py          # 打包 CMLib_out.SC2Mod
python src/lib/build_depmap.py       # 部署 mod + 构建依赖版地图
python src/lib/cmlib_runtime_test.py test_cmlib_dep.SC2Map
```

> **构建前置依赖**：打包走 `tools/mpq/scripts/pack_stormlib.py`（已入库），但它需要
> `artifacts/stormlib-v9.40/x64/StormLib.dll`（第三方二进制，569 KB）。`artifacts/` 整目录不入库，
> 因此 **clone 后需自行放置该 DLL** 才能执行 `build_mod.py` / `build_depmap.py`；
> 仅做静态自检（`python src/lib/check_cmlib.py`）与阅读/引用库源码则无需 StormLib。
> 库源码本体（`src/lib/scripts/cmlib/**`、`src/lib/selftest/`）与全部工具链 `src/lib/*.py` 均已入库，
> 从干净 clone 出发可完整重建 `CMLib.SC2Mod` 与 `CMLib_out.SC2Mod`。

### 5.3 已被真机抓出的真实缺陷（教训存档）

- **`CMLib_TimerOnce` / `CMLib_TimerLoop` 在 panel 与 trig 各定义了一份** → 函数重定义 →
  整段 MapScript 被引擎静默丢弃。静态 lint 当时报 0 错误，真机 Ghost 不出现。
  修复：计时器实现统一归属 `cmlib_trig`（实现更完整，带参数校验与 null 安全），
  `cmlib_panel` 只保留 `TimerWindow*` UI，`cmlib_panel_h` 改为 include `cmlib_trig_h`。
- 因此 trig 模块的 5 项断言（注册表 / 分组 / 开关 / 跨触发器传参 / 计时器）**必须常驻**
  自测脚本，防止该类撞名回归。

- **断言「观测双记」会让证据链反成假阳性护盾（2026-08-09 第 14 轮）**。若两条线（主断言链 +
  AI 加分线）都往同一个 `gv_cmlibPassed` 计数、又各自 spawn 证据单位，同样的 N 条会被记两遍，
  观测数虚高。虚高最危险处：**主线真丢 N 条时总数仍恰好达标，判定照样 PASS**——证据链应有的
  "少一条就看得见"能力被废掉。修复：证据只由一个出口产出（主线统一落盘 + 编码），其余线只"算"
  并置完成标志。配套把判定从"数 Marauder ≥ 静态条数"改为以 Thor（地图自证全过）+ bank 自报为准，
  因为事件处理器内的 `Mark` 不一定触发，执行数本就可能 < 静态数。

- **`CMLib_SpawnForced` 返回 null 的头号真因是「落点出界」，不是数据缺失**（2026-08-09，绕了两轮）。
  测试地图只有 **32×32**，而金甲虫/假人用了 `CMLib_PointOffset(origin, 20.0/25.0, 0.0)` —— 直接落到
  地图外，`UnitCreate` 连 `c_unitCreateIgnorePlacement` 都救不回来，静默返回 null。
  表象是「单位刷不出来」，极易被误诊成 catalog 缺失。**排查顺序应当是：先查坐标是否在
  `RegionPlayableMap()` 内，再查数据依赖。** 本仓库里已知安全的偏移量级是 ±10 以内。
- **别用「解包目录 grep 不到」来判定数据缺失**（同上轮的误判源头）。
  SC2 基础数据在 CASC 归档里，`Mods/`、`Campaigns/` 下的解包目录只是**局部视图**。
  阳性对照：`id="stop"`、`id="Warpable"`、`id="ProgressRally"` 这些百分百存在的核心能力，
  在解包目录里 grep 结果同样是 **0**。上一轮据此断定「`HangarQueue5` 悬空 → 金甲虫 catalog 校验失败」
  是**误判**，还因此白往测试地图注了一份多余的 Reaver CUnit（已回滚）。
  想判定「某 id 是否可用」，唯一可信手段是真机 `UnitCreate` / `CatalogEntryIsValid`。
- **顺带踩到的真坑：给测试图挂 `CMRE_Core_Base` 依赖会引发回归**。为了"补 Reaver"临时加过该依赖，
  结果 Reaver 依旧刷不出来（CMRE 只带 Reaver 的 *override*），反而把原本通过的
  `demo.temp.order`（ZealotAiur 旋风斩下令）打挂了。**加重量级依赖前先确认它真的提供你要的东西。**

- **`cmlib_game` / `cmlib_stock` 用了裸数组形参**（`void CMLib_GameEndForPlayers(int[CMLIB_PLAYER_MAX+1] lp_players, ...)` /
  `string[16] lp_unitTypes` 等共 4 处）→ 同样静默丢弃整个 MapScript。静态 lint 0 错误，
  真机 Ghost 不出现。修复：玩家集改 `playergroup` 形参、军队配方/科技批量改 CSV 规格串
  （`CMLib_StockArmyBatch(int, string "Marine:5,...")`）；并把"数组形参"固化为
  `check_cmlib.py` 第 6 项门禁（阳性对照已验证会真响）。`arrayref<具名 typedef>` 仍可用
  （`cmlib_ui` 的 `UISetVisibleRange` 在用），但裸数组形参不行——见 §2.6。

- **第 17 模块 `cmlib_board`（2026-08-08 第 6 轮补）**：用 `gap_scan.py` 量化全量
  1696 个 .galaxy 的领域覆盖率后，发现「面板效果」是用户点名三类中**唯一 0% 覆盖**的
  领域（Board/VictoryPanel 合计 1000+ 次调用）。新增 `cmlib_board`（`CMLib_Board*` /
  `CMLib_VPanel*`）补齐，并把断言从 32 → 39（+7 项 board 断言）。真机三档矩阵已含
  此模块，依赖挂载版实测 PASS 39/39（该轮基线）。该模块**故意不封装** `StatEvent*` 与 `Achievement*`
  两类 API —— 前者只声明在 `natives_missing.galaxy`（不被任何引擎库 include，调用即编译失败），
  后者原生标注 `// Blizzard maps only`（自定义地图调用无效），封装等于给使用者留假接口。

- **第 18 模块补齐 + 覆盖率闭环（2026-08-08 第 7 轮续）**：上一轮 `gap_scan.py` 因
  `DOMAIN_RULES` 缺 `board` 规则，把 `Board*`/`VictoryPanel*` 全算进 `misc`，导致「面板效果」
  覆盖率**无法独立量化**。本轮补 `("board", ^(Board|VictoryPanel))` 规则后复扫：
  **面板效果 = 89.3% 覆盖**（Board/VictoryPanel 合计 1946 次调用、1737 被 CMLib 引用），
  剩余 10.7% 几乎全是 `VictoryPanelAddAchievement`(179)（结算屏成就展示，合法但小众，未包）。
  另两个 0% 域 `leaderboard`(StatEvent*, 740) 与 `achievement`(Achievement*, 534) 仍是陷阱 API，
  正确不包。
  同时把任务点名「单位/建筑」里**唯一没吃透**的真缺口补齐：unit 域 74.3%→**80.4%**、
  unitgroup 域 74.6%→**86.1%**，新增 12 个封装——
  `UnitSetState`/`UnitSetPosition`/`UnitBehaviorAdd`(普通 caster 变体)/`UnitBehaviorRemove`，
  以及 `UGAdd`/`UGAddGroup`/`UGRemove`/`UGClear`/`UGCopy`/`UGUnit`/`UGRandomUnit`/`UGHasUnit`
  （均在 §2.3）。断言 39 → **74**（其中外部 galaxy 协作 agent 另贡献了 region 事件等约 20 项）。
- **`UnitSetPosition` 真机时序坑**：`UnitSetPosition(unit, point, false)` 在 Galaxy 中往往
  **推迟到下一模拟步才提交坐标**，同触发器内同步 `UnitGetPosition` 读回的是旧值；且目标点
  会被地形就近吸附（偏离可能 >容差）。因此自测对定位**只验「包装可调用 + 单位存活」**
  （签名正确即不崩），不卡具体坐标——这是 Galaxy 引擎行为，非库缺陷。

- **AI 波次/库存域扩展（2026-08-08 第 8 轮）**：gap_scan 复扫把 AI 域识别为**合作任务最高价值真缺口**——
  未覆盖 top 全是 `AIAttackWaveAddUnits`(3738)/`AICounterUnitSetup`(1006)/`AIEnableStock`(982)/
  `AIClearStock`(963)/`AIGetTime`(955)/`AISetFlag`(520)，且 CMLib 此前**完全没内部引用**这些原生
  （只包了 4 难度变体 `AIAttackWaveAddUnits4`，漏了单量版）。本轮补 6 个封装：
  `CMLib_AIAttackWaveAddUnits`/`AISetFlag`/`AIGetTime`/`AICounterUnitSetup`（§2.7）+ `CMLib_AIEnableStock`/
  `AIClearStock`（§2.17）。AI 域覆盖率 **78.0% → 86.2%**。
  自测策略：这 6 项放在 `CMLibTest_AIDeferred` **隔离触发器**（6s 才跑，崩了不影响主证据链），
  对人类玩家是空操作（不崩），断言只验「可调用即过」，并单独 spawn 等价数量 Marauder 计入证据链、
  回写 bank 使 Total/Passed=80。断言 74 → **80**。
  **本轮两个真机铁律再踩再封**：
  1. Galaxy **局部变量必须置顶**——在 `CMLibTest_AIDeferred` 函数体中段声明 `lv_aiPassed`/`lv_k`
     导致整段 MapScript 静默不编译（Ghost=0、units=12 全是预置单位）；移到顶部声明后复绿。
  2. 端口冲突瞬态：连续跑三档矩阵时若 `taskkill` 后端口 5000 未释放就拉起下一张图，会连到
     陈旧 SC2 实例 → 依赖图偶发 FAIL(0/80)；干净重启（等端口释放）后必 PASS。

- **裸调用 `Wait(secs)` 少传时间类型 → 静默丢弃整个 MapScript（2026-08-08 第 7 轮）**：
  自测脚本里写了 `Wait(0.2)`，而原生签名是 `void Wait(fixed inTime, int inTimeType)`。
  `galaxy-lint` 报 **0 错误**，真机却整段 MapScript 不编译（Ghost 不出现）。根因与"函数
  重定义"同类：**引擎对签名不匹配是静默失败**。修复：改用 `CMLib_WaitGame(0.2)`（本库的
  语义化封装，时间类型固化），并把**实参个数校验扩展到 selftest 文件**（`check_cmlib.py`
  第 4 项）—— 此前门禁只校验库内文件，自测脚本是盲区。阳性对照已验证：故意把
  `CMLib_BuffStripAll` 改回 1 个参数，门禁立即报 ERROR。

- **`EXPECTED_ASSERTS` 从手写改为源码自动推导（同轮）**：这个常量原来手抄在
  `cmlib_runtime_test.py` 里，多实例并发扩充 selftest 时必然漂移，症状是"真机其实全过
  却判不达标"或反过来"少跑几条仍判 PASS"——最难查的一类假阴/假阳。现改为从唯一真源
  （selftest 源码）正则统计 `CMLibTest_Mark*(` 调用数并减去定义处。**任何"清单类常量"
  都不要手抄**，这条同样适用于模块列表、include 清单。

- **第 18 模块 `cmlib_buff`（同轮）**：补 Behavior 增删与状态开关。三个真实坑被封进库：
  `BuffStripAll` 循环剥离（原生少调一次就残留一层）、`UStateIsReadOnly` 写前守门
  （只读 `c_unitState*` 写进去静默无效）、`PStateGet` 影子缓存（引擎对部分玩家 state
  读不回来）。同轮 `cmlib_trig` 扩出 20+ 个事件注册器（区域/范围/技能/进度/效果/面板控件），
  其中**区域事件做了真闭环验证**：自测里 `UnitSetPosition` 把探针挪进区域，等 1 秒后断言
  回调计数 ≥1 —— 只挂事件不触发，等于没验证。

- **第 9 轮（面板/catalog/单位 真缺口补齐，2026-08-08 18:20）**：gap_scan 复扫确认
  面板效果（UI/Dialog 77.4%）与 catalog/unit（78.9%/80.4%）是剩余最高价值真缺口
  （point/region/camera 低覆盖是 GUI 触发器 `*FromId` 自动访问器噪声，非真缺口）。
  新增 **49 个封装**（仍是 18 模块 / 37 文件，未开新模块）：面板消息/警报/淡变/动画/HUD 框架
  CSV（§2.2）、catalog 全表遍历 `CatCount/CatEntryAt(1-based 守门)/CatFindIndex/CatGetIntFast/
  CatCountWhere/CatLinkSwap` 等（§2.4）、unit/unitgroup/player 高频真缺口
  `UnitChangeOwner/UGAlliance/UGOrderAbility(AtUnit)/PlayerStart/RaceOf/Diff` 等（§2.3/§2.5）、
  core 数学 `RandF/RandI(反序区间自动交换)/ModSafe(除零兜底)/LogWarn/FilterAlive`（§2.1）。
  selftest 注入 **47 项带标签断言**（总数 80 → **127**，EXPECTED_ASSERTS 仍自动推导）。
  设计守门：全表遍历只在 Race 小目录跑（绝不扫 Unit 几千条，避免撑爆触发器预算）、
  HUD 成对恢复、null/非法槽守门、只硬断言可回读项。本轮因用户 SC2 **正在 IN_GAME**
  （`[CM] 亡者之夜`）按铁律**未开局跑真机**，三档矩阵已 staged（内联/依赖预期 PASS 127/127、
  反向 FAIL 0/127），待用户退出对局后下一轮执行。静态门禁 `check_cmlib.py` 仍
  **PASSED 0错0警**（37文件/18模块/821实现/807声明/2118调用点，selftest 一并校验实参）。

### 5.4 进程护栏：绝不误杀真人对局（round17 新增，已第 3 次撞上）

真机矩阵每档开跑前都要清场。原实现是一句简单粗暴的：

```powershell
Get-Process -Name SC2_x64,SC2Switcher_x64 | Stop-Process -Force
```

**这会把用户正在玩的那一局一起干掉。** 本项目按小时跑自动化，撞上真人对局
不是"如果"而是"什么时候"——事实上到 round17 已经撞上 3 次（round12 `亡者之夜`、
round13、round17 同一张图）。前两次靠人肉发现后手动跳过，这次直接把它变成代码约束。

`sc2_proc_guard.py` 的判定依据：

| | 命令行特征 | 处置 |
|---|---|---|
| API 探针实例 | `SC2Switcher_x64.exe **-listen** 127.0.0.1 -port <n> -debug` 拉起，其 `SC2_x64.exe` 子进程命令行同样带 `-listen` | 可以杀 |
| 真人对局 | 只有可执行路径（可能跟一个地图路径），**无 `-listen`** | **绝不碰** |

```python
from sc2_proc_guard import human_games, kill_api_instances, assert_no_human_game

assert_no_human_game("跑三档真机矩阵")   # 有真人局 -> 抛错，把误杀变成显式失败
kill_api_instances(guard=True)          # 只杀带 -listen 的，guard 时先做上面的检查
```

已接入两处（原来各写了一份危险清场）：
- `sc2_api_conn.py: ensure_sc2()` 的 `kill_stale` 分支；
- `run_matrix_round10.py` 的每档前清场与瞬态重试清场。

矩阵驱动器另加 `--wait <分钟>` 排队模式：撞上真人局时**每 30s 轮询等待**而不是硬失败，
真人局一结束自动开跑。理由：硬失败会让"通用库没通过验证"这个结论被环境噪声污染，
而等待只是把它变成一次干净的推迟。`--wait 0`（默认）保持原来的立即抛错语义。

#### 排队模式的两个坑（round17 当场踩到并修掉）

**坑 1 — 换局空窗被当成"用户不玩了"。** 第一版 `wait_for_free` 只要**一次**快照
没看到真人局就开跑。用户切地图/重开一局时 SC2 进程会消失几秒，等待循环正好撞进这个
空窗 → 打印"真人对局已结束，开始跑矩阵" → 几秒后新局起来 → `clear_sc2()` 的
`assert_no_human_game` 抛错 → **整个矩阵崩在起跑线上**（实测日志：等待成功但
`RuntimeError: 检测到 1 个真人 SC2 对局，拒绝清场`，PID 从 23644 变成 23472）。

修法两层：
- **去抖**：连续 `STABLE_CHECKS=4` 次（4 × 30s = 2 分钟）都没有真人局才认为空闲；
  中途被打断就把计数清零并打印"空窗被打断（大概率是换局）"。
- **清场失败回退等待**：`clear_sc2(max_minutes)` 捕获 `RuntimeError`，
  重新进 `wait_for_free()` 而不是崩掉（最多 6 轮）。

> 教训：**"资源空闲"是个需要去抖的信号，不是一次读数**。任何"等别人用完我再上"的
> 逻辑，单次采样都会在对方短暂重启时误判，而误判的代价通常落在最尴尬的位置（清场）。

**坑 2 — 排队等在会话后台任务里，会话一结束就白等。** 自动化按小时跑，一轮跑完
会话回收，正在排队的矩阵一起被回收，等于从没等过。改用 `matrix_daemon.py`
把矩阵**脱离会话**跑（`DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW`），
并做幂等保护——已有矩阵在跑/在等就跳过，避免两个矩阵同时抢 SC2：

```bash
python src/lib/matrix_daemon.py --wait 600   # 起守候，最多排队 10 小时
python src/lib/matrix_daemon.py --status     # 看矩阵进程 / 真人局 / 日志尾部
python src/lib/matrix_daemon.py --stop       # 只停矩阵，不碰真人局
```

这样用户什么时候退出游戏，矩阵就什么时候自动跑完并写 `matrix_round17.log`，
下一轮自动化直接读结论即可。

> 教训：**清场类操作必须能区分"我起的"和"别人的"**。按进程名杀是最省事也最危险的写法，
> 它在开发机上迟早会毁掉一次用户正在进行的工作。判据要用"我启动时加的特征参数"，
> 而不是"进程叫什么名字"。

### 5.5 门禁的两个新增项：盲区自检 + 文档漂移（round17）

静态门禁最危险的失败模式不是"报错"，而是**它以为自己检查了，其实压根没看见**。
`check_cmlib.py` 靠 `TYPE` 白名单正则识别函数签名：返回类型不在白名单里的函数，
`IMPL_RE` / `DECL_RE` 直接匹配不到，于是它的声明/实现配对、实参个数校验**全部跳过**，
而报告里照样是 `PASSED — 0 错误`。

round17 真踩了：`cmlib_stat` 的 `effecthistory CMLib_EffHist(...)` 因为
`effecthistory` 缺席白名单，连续两轮完全没被校验过，报告里连它的存在都看不到
（声明数 1052 而不是 1053）。它是靠新加的文档漂移检查"多了 1 个函数"才暴露的。

于是加了两项：

| 项 | 级别 | 判据 | 修复 |
|---|---|---|---|
| **门禁盲区自检** | ERROR | 用宽松正则扫所有 `CMLib_*` 定义行，返回类型不匹配 `TYPE` 白名单即报 | 把类型加进 `check_cmlib.py` 的 `TYPE` |
| **文档漂移** | WARN | `API_INDEX.md` 的函数名集合必须与 `_h` 声明集合**双向相等**（缺了/多了都报） | `python src/lib/gen_api_index.py` 重生成 |

盲区自检做过阳性对照：临时把 `effecthistory` 从 `TYPE` 里删掉 →
`ERROR [门禁盲区] ... FAILED — 1 个错误`；还原 → `PASSED — 0 错误, 0 个警告`。
文档漂移两个方向也都真响过（先报"少了 1052 个"暴露正则写错，改对后报"多了 1 个"
抓出上面那个盲区函数）。

> 教训：**校验器自身要有校验器**。白名单式的识别逻辑天然会漏，
> 漏的部分表现为"静默通过"，比直接报错难查一个数量级。
> 凡是"匹配到才检查"的门禁，都要配一条"没匹配到的是什么"的反向清点。

### 5.6 `color == null`：潜伏两轮的编译期致命项（round18，代价最大的一次）

**症状**：round18 三档矩阵，内联源码版与依赖挂载版**同时**真 FAIL —— `Ghost=0 且 bank 无
Magic`，即地图根本起不来、`InitMap()` 从未被调用。而此前 `check_cmlib.py` 连续报
`PASSED 0 错误 0 警告`。

**真凶**（`cmlib_path.galaxy`，round16 引入）：

```galaxy
// 两处都是 Galaxy 编译期错误
if ((CMLib_RouteOk(lp_route) == false) || (lp_color == null)) { ... }   // ①
color CMLib_RouteColorGet(...) { ... return null; ... }                 // ②
```

`color` 在 Galaxy 里是**值类型**，既不能与 `null` 比较，也不能为 `null`。checker 原话：
`Type 'null' is not comparable to type 'color'` / `not assignable to type 'color'`。
SC2 对这类编译失败的反应还是那一招：**静默丢弃整个 MapScript**。

**为什么潜伏了两轮**（三个因素叠加，缺一不会烂这么久）：

1. `check_cmlib.py` 只校验实参**个数**，不校验**类型** —— 这类错误对它天然不可见；
2. 能抓它的 `build_typecheck_unit.py` + `galaxy-lint.mjs` 仓库里一直都有，
   但**从来不是门禁的一环**，靠人记得手动跑 —— **工具存在 ≠ 关卡存在**；
3. round17 的三档矩阵因真人局全程占机**一次都没跑成**，唯一能兜底的真机关卡缺席。
   于是"静态全绿 + 真机未跑"被当成了"通过"。

**更刺眼的是**：同一条规则 `cmlib_text.galaxy:57` 早就写过注释记着了 ——
知识存在于代码注释里，却拦不住隔壁模块再犯。**注释是给人看的，门禁才是给机器执行的。**

**修复与治理**：
- ① 删掉对 `lp_color` 的判空（非法路线 id 才是唯一守门条件）；
  ② 失败态返回哨兵色 `ColorWithAlpha(0,0,0,0)`（全透明黑），并写进 `_h` 的 API 契约；
- 新建 `gate.py`（§4.1）把全量类型检查钉成**必过关卡**，阳性对照已验证
  （把 `return null` 塞回去 → `[gate] FAILED —— typecheck(1 个 error)`；还原 → 全绿）；
- 规矩加一条：**真机矩阵没跑成，就不能说"这一轮通过了"**。矩阵被真人局挤掉时，
  该轮状态是"未验证"，不是"通过"。

---

## 6. 分发与接入

打包产物：`CMLib_out.SC2Mod`（MPQ，约 220 KB），内部布局**必须**是

```
CMLib.SC2Mod/
  modinfo.xml
  Base.SC2Data/scripts/cmlib/*.galaxy    ← 43 个文件
```

路径不能平铺到 `Base.SC2Data/` 根目录 —— 库文件内部一律写
`include "scripts/cmlib/cmlib_xxx"`，平铺会导致 include 解析失败（旧版曾踩此坑）。

接入步骤：

1. 把 `CMLib_out.SC2Mod` 放进 `StarCraft II/Mods/CMLib/CMLib.SC2Mod`；
2. 给你的地图加依赖 `file:Mods\CMLib\CMLib.SC2Mod`
   （**DocumentHeader 与 DocumentInfo 必须同步改**，只改前者会被编辑器覆盖回去）；
3. MapScript 里 `include "scripts/cmlib/cmlib"`，即可调用全部 21 个模块。

> DocumentHeader 依赖区格式（本仓库实测）：`0x2c` 处 uint32 为依赖计数，`0x30` 起是
> **紧密相连**的 null-terminated 依赖串 —— 串与串之间**没有**任何 per-dependency 元数据头。
> 参考实现见 `build_depmap.py:patch_document_header`。

---

## 7. round20 的两条新教训（自检器又抓到了人写不出来的错）

### 7.1 `void` 函数不能出现在比较表达式里 —— 而 lint 抑制会让你看不见

round20 写真机断言时，两处把 **void setter 的"返回值"拿去比较**：

```galaxy
// ✗ 错：CMLib_UnitBuffDuration / CMLib_VPanelAchievementBatch 都是 void
CMLibTest_MarkTag(CMLib_UnitBuffDuration(null, "x", 1.0) == false, "unit.buff.duration.guard");
CMLibTest_MarkTag(CMLib_VPanelAchievementBatch("") == 0,           "board.achievement.batch.guard");
```

`check_cmlib.py` 只校验**实参个数**，放行；只有 `gate.py` 的全量 typecheck 报出
`Type 'false' is not comparable to type 'void'`。但 typecheck 输出里同时抑制了 1900+ 条
良性诊断，两条真 error 混在里面极易被眼睛滑过去 —— 必须**认准 `[gate] typecheck errors = N`
这一行**，而不是"看起来没红字"。

守卫态断言的正确写法是**裸调用 + 存活哨兵**：

```galaxy
// ✓ 对：真机上若 native 对 null/空串抛运行时错误，后面的 Mark 根本不会执行，
//        断言总数会掉 —— 守卫态验证照样成立，而且比比较返回值更贴近真实语义。
CMLib_UnitBuffDuration(null, "x", 1.0);
CMLibTest_MarkTag(true, "unit.buff.duration.guard");
```

配套的机械化排查（一行找出全部误用）：

```bash
python -c "
import io,re,glob
voids=set()
for f in glob.glob('scripts/cmlib/*_h.galaxy'):
    for m in re.finditer(r'^\s*void\s+(CMLib_\w+)\s*\(', io.open(f,encoding='utf-8').read(), re.M):
        voids.add(m.group(1))
for i,l in enumerate(io.open('selftest/cmlib_selftest.galaxy',encoding='utf-8'),1):
    for v in voids:
        if v+'(' in l and re.search(r'(==|!=|>=|<=|>|<)',l): print(i,v,l.strip()[:100])
"
```

### 7.2 写测试反过来暴露 API 缺口，比读 native 清单更准

round20 的断言里很自然地写下 `CMLib_DTSetInt(...)` 和 `CMLib_UGOf(marine)`，
`verify_natives.py` 直接判"未知函数 4 处 —— 真机会静默丢整个 MapScript"。查下来两件事：

* **DT 强类型族是半拉子**：round20 只补了 `Bool / UG / Timer / Objective / Region`，
  漏了 `Int / Fixed / String / Unit / Point` 五对。老接口 `CMLib_StoreInt/LoadInt`
  把 `global` 写死成 `true`，**没有任何办法访问 local 表** —— 缺口是真的。
* **缺"单位 → 单元素组"**：`CMLib_UGOf(unit)` 是把单个单位喂给一切 `unitgroup` API
  的必经桥，居然一直没有。

于是有了 `extend_round20b.py`（11 个函数）。结论：**先写测试，再补库**。
读 native 清单只能发现"引擎有而我没封"，写测试才能发现"我自己用起来别扭/根本用不了"——
后者才是通用库真正的缺陷。

---

## 8. round21 的两条引擎级发现（真机矩阵抓出来的，静态门禁全都放行了）

round20 的三档矩阵跑出 **PARTIAL 499/504**，3 条失败标签。它们的共同点：
**过了 `gate.py` 全部五道关**（符号层 / G1001 / 构建 / 类型检查 / galaxy-lint），
一条都没被拦下。原因很直白 —— 静态检查能验证"类型对不对、符号存不存在"，
但验证不了"引擎在运行时到底怎么定义语义"。

### 8.1 武器索引是 1-based，传 0 不是"第一把武器"

```galaxy
// ✗ 断言这么写，真机必挂
CMLib_UnitWeaponPeriod(marine, 0) > 0.0      // 返回 0.0
// ✓ 1 才是第一把武器
CMLib_UnitWeaponPeriod(marine, 1) > 0.0
```

`natives.galaxy` 只给了 `native fixed UnitWeaponPeriod(unit inUnit, int inIndex);`，
**没有任何一处文档说明索引基准**。库实现按 1-based 写了守卫（`< 1` 直接返回 0.0），
而自测断言按 0-based 写 —— 两边打架，静态层面谁也发现不了。

**怎么判定谁对的**（这是本节真正的方法论）：同一轮里 `unit.weapon.dps` 断言
**通过了**，而 `CMLib_UnitDpsTotal` 的实现是 `for i in 1..UnitWeaponCount` 循环累加，
它拿到了 `> 0.0` 的结果 ⇒ **索引 1 是合法武器索引** ⇒ native 是 1-based ⇒
实现正确、断言写错。**用同一轮里"通过的那条断言"去反推"失败的那条谁对"，
比翻文档快也比翻文档准。**

修法不只是把 0 改成 1，还补了 `unit.weapon.period.zero` / `unit.weapon.damage.zero`
两条断言把"0 属越界"这个契约钉死，并在 `cmlib_unit_h.galaxy` 写进注释。

### 8.2 Galaxy 里空串与 null 等价 —— `s != null` 判非空是错的

```galaxy
// ✗ 恒为 false（哪怕函数返回的是字面量 ""）
CMLib_ConvDataActiveSound() != null
// ✓
CMLib_StrIsEmpty(CMLib_ConvDataActiveSound())
```

推演过程（两条路径收敛到同一结论，所以是**推出来的不是猜的**）：

* 若 native 返回 null → 实现里 `lv_id == null` 命中 → 返回字面量 `""`，
  此时断言 `"" != null` 判 false ⇒ 说明 `"" == null` 成立；
* 若那次 `== null` 没命中 → 原值直接返回，断言同样判 false ⇒ 说明该值 `== null`。

两条路都指向同一件事：**空串与 null 在 Galaxy 字符串上不可区分**。

顺手做了全库扫描（`scan_strnull_round21.py`）：库内共 **18 处**对 string 做 null 比较，
逐处复核后**全部是"空即跳过"语义，等价、无 bug**，不构成系统性缺陷 ——
但写法有误导性，正确姿势统一为 `CMLib_StrIsEmpty` / `CMLib_StrNotEmpty`
（这两个函数刻意用顺序 `if` 而不是 `a || b || c`：Galaxy 的短路求值无明文保证，
`StringLength(null)` 一旦被求值就有风险）。

注意 `text` 类型**不**适用本条：同一轮 `unit.customname.guard` 断言
`CMLib_UnitCustomName(null) != null` 是通过的（`StringToText("")` 不等于 null）。
**`string` 和 `text` 在 null 语义上不一致** —— 这是最容易踩的地方。

### 8.3 把推论落成硬证据，而不是留在文档里

上面两条结论都是推演出来的。为了让下一轮不必重新推，selftest 落盘时额外写了
**四个诊断探针**进 bank（是探针不是断言，失败也不会把矩阵判红）：

| bank 键 | 含义 |
|---|---|
| `Result/StrNullEquiv` | `("" == null)` 的真值（1/0） |
| `Result/WpnIdx0` / `WpnIdx1` | 直接调 native `UnitWeaponPeriod(marine, 0/1)` 的毫秒值 |
| `Result/WpnCount` | `UnitWeaponCount(marine)` |

`CMLibTest_StrNullEquiv()` 刻意走局部变量而不是 `"" == null` 字面量比较：
字面量与 null 的比较是否合法在 Galaxy 里无明文保证，而**编译期失败会让 SC2
静默丢弃整个 MapScript**（§5.3 头号教训），不值得为一个诊断探针去赌。

## 9. round22：两次「判定翻案」

这一轮没有新增功能性 bug，抓到的是两条**判据本身**的错误——比 bug 更值得记，
因为错判据会让后续每一轮都建立在假前提上。

### 9.1 "符号不在 `natives.galaxy` 就不能用" —— 错

历轮有一条铁律：**范围外符号不封装**。理由是真机上调用未声明的 native 会导致
MapScript 编译失败，而 SC2 对编译失败是**静默丢弃整张图**（§5.3 头号教训），
代价极高。这条铁律本身没问题，问题出在"范围外"的判定标准上。

之前的判定是：**符号在不在 `core.sc2mod/.../TriggerLibs/natives.galaxy` 里**。
按这个标准，`StatEvent*` 家族（`StatEventCreate` / `StatEventSend` /
`StatEventAddDataString|Int|Fixed` / `StatEventLastCreated`）被判为范围外，
因为它们只出现在 `natives_missing.galaxy`。于是 `gap_scan_round22.json` 里
leaderboard 域覆盖率长期挂 **0%（740 处调用无一封装）**。

round22 复查发现这个标准站不住脚，两条反证：

1. `core.sc2mod/.../NativeLib.TriggerLib` 里 `StatEventCreate` 带 `<FlagNative/>`
   —— 官方触发器 GUI 就能生成对它的直接调用，说明**引擎侧注册了这个 native**。
2. 更硬的一条：官方合作模式 mod 的 `LibCOOC.galaxy`（就是我们 stage26 真机跑通过的
   `preselected-commander-overlay`）只 include 了 `TriggerLibs/NativeLib` +
   `TriggerLibs/LibertyLib`，**没有任何 `native ... StatEvent` 自声明**，却在
   L5254 直接 `StatEventCreate(lp_name);`、L5306 `StatEventSend(...)`。

=> **SC2 的 native 符号表是引擎内建的**；`.galaxy` 里的 `native` 声明只是给编辑器和
lint 用的元数据。`natives.galaxy` 文本缺声明 ≠ 真机不能调，
`natives_missing.galaxy` 正是社区从 TriggerLib 元数据回填的补充声明。

**但推论仍然只是推论**。而且 `natives_missing.galaxy` 的文档注释明写 "Blizzard only."
—— 引擎完全可能做了发行方鉴权，自定义地图调用时抛运行时错误。所以在把 `StatEvent*`
纳入 `cmlib_stat` 之前，先落一个真机能力探针 **`probe_statevent.py`**：

| 档位 | MapScript 行为 | 真机结果（2026-08-09 22:00） |
|---|---|---|
| `baseline` | 只造 Ghost + Marine，不碰 StatEvent | **PASS**（观测链路有效，其它档结论才作数） |
| `call` | Ghost → StatEvent 全链路直调 → Marine | **PASS** |
| `wrapped` | Ghost → CMLib 风格守门包装再调 → Marine | **PASS** |

**结论 `USABLE`** —— 三档全 `Ghost + Marine`，落 `probe_statevent_result.json`。
`StatEvent*` 在真机**可编译、可调用、不中断 trigger**，连 CMLib 的守门封装形态也 PASS。
判定翻案成立：**"符号不在 `natives.galaxy` 就不能用"是错的**，正确判据是
**引擎有没有注册这个 native**（查 `NativeLib.TriggerLib` 的 `<FlagNative/>`，
再用探针背书）。

三态判读（这是本节可复用的部分）：

- **Ghost 有 + Marine 有** = `PASS`：可编译、可调用、不中断 trigger；
- **Ghost 有 + Marine 无** = `TRAP`：能编译，但调用抛 runtime error 掐断了 `InitMap` 后续语句；
- **两个都无** = `COMPILE_FAIL`：整图被静默丢弃，就是那条铁律的症状。

> 关键设计：**把"能编译"和"能调用"拆成两个独立可观测信号**。只放一个哨兵单位的话，
> 编译失败和运行时中断的现象完全一样（都是啥也没有），根本没法区分该改声明还是该弃用符号。
>
> `wrapped` 档也不是多余的：直调 PASS 不等于封装 PASS —— 封装引入了函数边界和
> null/空串守门，而 CMLib 交付的就是封装形态，不测封装等于没测。

> 注意边界：探针只证明**调用安全、不炸脚本**，不证明数据真的被 Battle.net 接收
> （注释写着 "Blizzard only."，很可能自定义地图侧就是个空操作）。
> 所以 `cmlib_stat` 封装它时的定位是**「可安全调用的埋点通道」**，
> 文档必须写明"不保证上报"，不能让使用者误以为拿到了统计后端。

**后续（round23）**：把 `StatEvent*` 纳入 `cmlib_stat`，补 `CMLib_StatEvt*` 一组封装，
并同步修正 `gap_scan` 的范围判据 —— 现在的判据只看 `natives.galaxy`，
会继续把其它同类符号（同样在 `natives_missing.galaxy` 但引擎已注册的）误判为范围外。

### 9.2 "执行数 ≤ 静态数，差额是良性的" —— 也错

详见 §5.2.1。一句话版：把 511 个断言点逐一定位后发现事件处理器里一条都没有，
差额的真身是**两组 `if/else` 互斥分支**，`511 − 2 = 509` 是个**确定值**。

含糊的下限判据是**退化的隐身衣**：真丢了断言照样 PASS。已升级为
`expected_asserts.py` 的分支感知精确判等，并配了 4 项阳性对照。

### 9.3 新判据插错位置，把反向对照打哑了（§9.2 的直接后果）

§9.2 的精确判等落地后，三档矩阵立刻 `rc=1`。第一反应是"round22 新增的 35 个封装
引入了真机回归"——**错了**。单跑内联档：`PASS 509/509`，精确吻合，库好得很。

真因在 `cmlib_runtime_test.py` 的失败分支顺序。新判据是这样加进去的：

```python
if ok: ... return 0
if not acct_ok:                     # ← round22 新增，插在了最前面
    print("[t] PARTIAL — 断言会计不符"); return 3
if bank_fails: ...
if sentinel >= 1: ...
print("[t] FAIL — sentinel 未出现")  # ← 从此永远走不到
```

反向对照图的期望态是"地图根本起不来"：`sentinel=0`、`passed=0`，于是
`acct_ok = (0 == 509)` 为 False，**在 sentinel 门之前就被判成 PARTIAL 返回了**。
矩阵的 `classify()` 又恰好把 `"PARTIAL —"` 匹配排在 `ghost0` 之前，跟着一起误判。

表面症状只是 rc=1。真正的危害是：**反向对照失去了产出 FAIL 的能力**。
它存在的唯一意义就是排假阳性（§5.2 的第三档），一旦哑火，
另外两档的 `PASS` 也不再能证明任何事情——这道防线等于被悄悄拆了。

**根因是判据的排序语义**：`sentinel=0` 表示 MapScript 压根没编译成功 / `InitMap`
没被调用，**地图没跑**。此时任何以"执行数"为输入的次级判据（断言会计、失败标签、
Thor 缺席）都必然同时不成立——但它们描述的都是"跑起来之后哪里不对"，
拿它们去解释"根本没跑"就是错误归因。

修复与加固：

1. `cmlib_runtime_test.py`：`if sentinel < 1 -> FAIL` 提到所有失败分支最前。
2. `run_matrix_round10.py` 的 `classify()`：**不依赖 runner 的分支顺序**，
   只要 `Ghost=0` 或输出里出现 sentinel 缺席字样，一律归 FAIL 家族（双保险）。
3. `run_matrix_round10.py` 补 `if __name__ == "__main__"` 守卫 —— 它此前是裸
   `main()`，`from run_matrix_round10 import classify` 会当场把三档真机矩阵整个
   跑起来，而且 `main()` 末尾的 `sys.exit` 会把调用方的后续断言全部吃掉
   （测试"通过"得毫无声息）。写回归钉时当场踩到。
4. **新增 `test_verdict_order.py` 并接进 `gate.py` 第 1 关**：
   - `classify()` 五种代表性输出的判定（含"带 round22 错误 PARTIAL 文案的反向对照"
     这份历史样本，它必须被判成 FAIL）；
   - AST 静态校验 `main()` 里 sentinel 门排在所有次级判据之前。
     识别"判定分支"不能只看 `if`+`return`（`if r.error:` 那类连接层错误处理会被
     误收——本回归钉第一版当场自己踩到），要认 body 里是否真的打印了
     `PASS —`/`PARTIAL —`/`FAIL —` 文案。
   - **阳性对照**：`--src` 指向一份把顺序改坏的临时副本，必须变红（实测红 2 项，
     还原即绿）。恒绿的校验器等于没有校验器。

放第 1 关的理由：判定链不可信时，后面所有关卡跑出来的结论都没有意义。

> 可复用判据：**给判定链新增判据，一律往后插，永远不要挡在"东西到底起没起来"
> 这个最根本的信号前面。** 这类缺陷语法合法、类型检查全绿、静态门禁一路放行，
> 只有针对判定链本身的测试抓得到。

---

## 10. round23：把 §9.1 的翻案落成代码（判据 + 封装）

round22 只是**在文档里**推翻了"不在 `natives.galaxy` 就不可调用"这条判据，
代码层的判据一行没改 —— 于是它继续在每一次 `gap_scan` / `check_cmlib` 里
按错误标准出结论。这一轮把翻案落地。

### 10.1 `StatEvent*` 正式进库（`cmlib_stat`，11 个封装）

见 §2.22 表格末尾。三条设计取舍：

1. **不自己 `native` 声明**。库里再声明一遍会与引擎内建符号撞名，
   `check_cmlib` 第 1c 项（库内符号与引擎 native 撞名）是致命项。
   直接裸调即可 —— 这也正是 round22 `probe_statevent.py` 三档真机探针
   验证过的 wrapped 形态。
2. **只承诺"可调用"，不承诺"上报成功"**。原生注释是 "Blizzard only.
   Sends the Stat Event to Battle.net."，投递结果客户端观测不到。
   因此 selftest 的 18 条断言只验**库自身语义**（守门早退 / 重复 Send 拦截 /
   CSV 解析条数），一条都不去断言上报结果 —— 断言不可观测的东西
   等于给自己埋一颗随机失败的雷。
3. **重复 Send 用环形缓冲拦**（`CMLib_StatEvtSentRing`）。原生
   `StatEventLastCreated()` 会把**已经 Send 过的**句柄照样返回，
   不拦就会出现"拿 Last 再 Send 一次"的静默双投。

### 10.2 两个静态门禁的 native 判据同步修正

| 脚本 | 旧判据 | 新判据 |
|---|---|---|
| `check_cmlib.py` `load_engine_symbols()` | 硬编码 `srcs` 列表，只含 `natives.galaxy` + `GameData/*.galaxy` + `NativeLib/AI*.galaxy` | 追加 `natives_missing.galaxy`，并解析 `NativeLib.TriggerLib` 里全部带 `<FlagNative/>` 的 `FunctionDef` |
| `gap_scan.py` | 只把"扫到的 mod 源码里出现 `native X(...)`"当真 native（`NATIVES_HINTS` 实为死常量） | 先用 core.sc2mod 的权威集合打底：`natives.galaxy` ∪ `natives_missing.galaxy` ∪ `<FlagNative/>` |

实测口径：权威 native **2679** 个，其中 `.galaxy` 声明 2436 个、
**仅由 `<FlagNative/>` 背书的 243 个** —— 这 243 个正是旧判据会误判成
"不可调用"的增量。引擎符号表从 9312 涨到 **9865**。

> 顺带发现一处判据不一致：`verify_natives.py` 用 `CORE.rglob("*.galaxy")`
> 递归，天然包含 `natives_missing.galaxy`，所以它一直是绿的；
> `check_cmlib.py` 用硬编码列表，所以它一加 `StatEvent*` 就报 6 个未知符号。
> **同一个问题、两个脚本、两套答案** —— 这种不一致比单点错误更难查，
> 因为它会让人以为"另一个脚本说没问题，那应该是这个脚本的 bug"。

### 10.3 可复用判据

> **判"某个引擎符号能不能调"，不要只看某一个 `.galaxy` 文件。**
> SC2 的 native 符号表是引擎内建的，`.galaxy` 里的 `native` 声明只是
> 编辑器 / lint 元数据。权威来源是 `NativeLib.TriggerLib` 的 `<FlagNative/>`，
> 兜底是真机探针。

> **推翻一条判据之后，要顺着它去改所有"实现了这条判据"的代码。**
> 否则文档说 A、工具做 B，下一轮又会拿工具的输出当证据。

### 10.4 「可调用 ≠ 可用」：`StatEventCreate` 在非签名内容里恒返回 0

round23 第一次跑三档矩阵时，内联 / 依赖两档**同时** 516/527，
失败标签整齐是 11 条 `statevt.*`，反向对照照常 FAIL。
两档结果完全一致 = 确定性缺陷，不是抖动。

拆开看更有意思：18 条 statevt 断言里，**7 条"守门/负向"断言全过、
11 条"正向"断言全挂**。这个分布只有一个解释 ——
`CMLib_StatEvtBegin()` 拿回来的句柄是 0，于是库的守门把后续每一步都
正确地早退了，负向断言因此全绿，正向断言因此全红。**库是对的，
是引擎不给句柄。**

原生注释 "Blizzard only. Sends the Stat Event to Battle.net." 是字面意思：
`StatEventCreate` 在非暴雪签名内容里直接返回无效句柄。

那 round22 的探针为什么判 USABLE？翻 `probe_statevent.py` 的判据：
`"编译通过 + 调用未中断 trigger"` —— 它只证明了**可调用**，
**从来没有检查过返回值**。判据写得太宽，结论就飘。

| 层次 | round22 探针 | round23 矩阵 |
|---|---|---|
| 编译不炸 | ✅ 验了 | ✅ |
| 调用不中断 trigger | ✅ 验了 | ✅ |
| **返回可用句柄** | ❌ **没验** | ❌ 实测恒 0 |

处置（保留封装，改断言口径）：

1. **封装保留**。每个入口都有守门，句柄无效时全是 no-op，
   在普通地图上零风险；哪天在签名内容里跑就直接可用。
2. **抽出纯解析 `CMLib_StatEvtCsvCount(spec)`**。CSV 解析本来是纯逻辑，
   却因为被塞在"要句柄"的函数里而变得不可测。拆出来之后，
   7 条解析断言在任何环境下都成立。
3. **正向断言改成"一致性断言"**：不断言"句柄一定有效"，
   而断言 `Ok(ev) == (ev != 0)`、`Send(ev) == (ev != 0)` ——
   这类命题在"引擎给句柄"和"引擎不给句柄"两种环境里**都为真**，
   不会因为环境变好而变红。
4. **真实句柄值降级为 bank 诊断探针**（`Result/StatEvtHandle`、
   `Result/StatEvtLast`），和 round21 的 `StrNullEquiv` / `WpnIdx0` 一个待遇。

> 可复用判据 ①：**探针的判据必须覆盖你要下的结论。**
> 想说"能用"，就得验到"返回值可用"；只验"没崩"，最多只能说"能调"。
> 判据比结论宽一格，结论就会错一轮。

> 可复用判据 ②：**不要断言当前环境观测不到的东西。**
> 观测不到就降级成诊断探针写进 bank —— 探针失败不会把矩阵判红，
> 但它把事实钉在证据链上，下一轮不必重新推。

> 可复用判据 ③：**纯逻辑不要和引擎调用绑在同一个函数里。**
> CSV 解析被"要句柄"这件事挟持了可测性；拆成纯函数后，
> 同一套逻辑立刻从"不可测"变成"任何环境都可测"。

## 11. round24：把"范围外不封装"的判定推翻（AI 战术过滤族入库）

`AIFilter` / `AIGetFilterGroup` / `AISetFilter*` 这一族，从 round12 起就被写在案上
"刻意不包"，理由是：**它们在 `Tactical/TacticalAI.galaxy`，不是 core 默认 include，
包了有真机静默编译失败的风险**。这条判定在案上躺了 12 轮。round24 把它推翻了。

### 11.1 三条反证

1. **`aifilter` 不是 typedef，是引擎内建 handle 类型。**
   `natives.galaxy` 全文 0 个 typedef，却在 1203/1204 行直接写
   `DataTableSetAIFilter(bool, string, aifilter)` —— 默认 include 链的核心文件
   自己就在用这个类型名。类型名从来就不需要 include TacticalAI。
2. **这一族在 `NativeLib.TriggerLib` 里全部带 `<FlagNative/>`。**
   这正是 §9.1 / §10.2 已经确立的权威判据：**SC2 的 native 符号表是引擎内建的，
   `.galaxy` 里的 `native` 声明只是编辑器/lint 元数据。**
   同一条判据在 round22 用来给 `StatEvent*` 翻案，这里再用一次。
3. **真机探针六档全 PASS，而且验到了返回值。**

### 11.2 六档探针设计（`probe_aifilter.py`）

判据设计吃了 §10.4 的教训：**要下"能用"的结论，就必须验到返回值可用。**
所以档位沿两条正交轴铺开 —— 纵轴是"验多深"，横轴是"是否自带 native 声明"。

| 档 | 验什么 | 结果 |
|---|---|---|
| `baseline` | 空 MapScript 哨兵（排除环境问题） | PASS |
| `decl` | `aifilter lv_f;` 局部变量声明能否编译 | PASS（类型名可用） |
| `call` / `calln` | 全链路裸调 vs 自带 7 条 native 声明 | 双双 PASS（**裸调即可用**） |
| `value` / `valuen` | `AIFilter(1) != null` + `AIGetFilterGroup` 产出**非空组** | 双双 **USABLE** |

`value` 档把每层结论各绑一个可观测单位：Marauder = 句柄非 null，
Thor = 过滤真的产出了东西，Banshee = 全链路没被运行时错误中断。
意外收获：这是在**人类玩家 player 1** 上过的 —— 不需要该玩家挂 AI，
比预期宽松（原本担心踩 round5 那个"`AISetUserInt` 只对已挂 AI 玩家有效"的坑）。

**本模块最终不 include `TriggerLibs/Tactical/TacticalAI`**：既然裸调实证可行，
就没必要引入它 —— 那个文件里除 native 外还有一批普通 Galaxy 函数
（`AICampSkirDiffTest` / `AITacticalRetreat` …），宿主地图若也 include 它，
就有**函数重定义**的风险，而那是"SC2 静默丢弃整个 MapScript"最经典的诱因。

### 11.3 `callall` 档：一次没能定位成因的失败，就老实记成没定位

`value` 档只验了 6 个 setter。按"判据必须覆盖结论"的纪律，那就只能对这 6 个下结论。
于是加 `callall` 档，把 TacticalAI 里其余 setter 一次性全调，参数**全取最宽松值**
（否则 Thor 缺席时无法区分"这个 setter 坏了"和"我把条件写太严"）。

结果：**Thor 缺席、Banshee 在** —— 没崩，但过滤成了空组。
再加 `callmid` 档二分，只留 5 个语义确定的数值型 setter
（Range / LifeLost / LifePercent / LifeSortReference / Shields）→ **USABLE**。

所以成因落在剩下那 6 个语义型 setter 里，但**具体是哪个没二分出来**。
处置就按事实写：那 6 个 **不封装**，README 和头注释里都写明"未拿到正向证据、下轮继续"。
不封装不是因为它们坏，是因为**我还没有能支撑"它能用"这句话的证据**。

### 11.4 `AIUnitGroupGetValidOrder`：又一个"可调用不可用"

`order` 档拿到 `NULL_RETURN`。但这个结论一开始是**不可归因**的 ——
返回 null 可能是"函数坏"，也可能是"我喂进去的 order 本身就是 null"。

于是加 `order2` 档，把**前提**也绑上可观测单位：
Marauder = 输入 unitgroup 非空，Thor = order 构造成功，SiegeTank = 最终结论。
跑出来 Marauder ✓ / Thor ✓ / SiegeTank ✗ —— 前提全部成立，它仍然返回 null。
坐实为 §10.4 那一类"可调用不可用"，**不封装**。

> 可复用判据 ④：**结论型断言旁边要放前提型断言。**
> 只断言结论，失败时你分不清是"结论不成立"还是"前提没建立"，
> 只能靠二分回头补。前提断言的成本是一行，省下的是一整轮。

### 11.5 顺带修掉的一个判定链缺陷（和 §9.3 同源）

只跑 `baseline group order` 三个子集时，`decide()` 打印了
"call/calln 都没能 PASS" —— 可这两档**根本没跑**。
这就是 §9.3 那个事故的同款：**把"没跑"说成"没过"。**

修法：`decide()` 加 `SUBSET_ONLY` 分支，主结论严格按**实跑档数**分支；
附属族（group / order2）的结论独立先报，不依赖主结论是否存在。
同一条纪律 round23 已经在 `run_matrix_round10.py --only` 上落过一次
（单档跑绝不打印"三档矩阵全部符合预期"），这轮是它在探针侧的第二次落地。

### 11.6 门禁加固

`check_cmlib.load_engine_symbols()` 现在追加加载
`GameData` / `TriggerLibs` / `Tactical` 下所有 `.galaxy` 的 **native 声明**，
引擎符号表 9865 → **9886**。

关键克制：**只收 `native` 声明，绝不收普通 Galaxy 函数。**
把普通库函数也当成"已知符号"收进来，等于亲手拆掉
"裸调库函数 → 真机静默编译失败"这条防线 —— 那正是 round4 抓到的头号杀手。

### 11.7 门禁自己被环境变量摆了一道（一次假 FAIL + 一次假 ALL PASSED）

收口阶段复跑门禁，同一份代码给出了两个相反的结论：

| 环境 | 结果 |
|---|---|
| `PYTHONIOENCODING=utf-8` | `[gate] ALL PASSED` |
| 裸 Windows 控制台（GBK/gb2312） | `[gate] FAILED —— 未通过的关卡: verify_natives` |

根因不在库，也不在 `verify_natives` 的核对逻辑 —— 它**核对通过了**，崩的是最后
那句"恭喜"：

```python
print("\n[verify] \u2713 符号存在性 / 实参个数 / 引擎常量 三项均与引擎声明一致")
# UnicodeEncodeError: 'gbk' codec can't encode character '\u2713'
```

`'✓'`(U+2713) 不在 GBK 字符集里 → `print` 抛异常 → 脚本 rc=1 → `gate.py` 判这一关
FAILED。**「打印崩了」被门禁读成了「这一关没过」。**

更早一步，`gate.py` 自己也栽在同一个坑：它的第 1 关打印子进程输出时遇到
pytest 输出里的 `'ʧ'`(U+02A7)，直接 `UnicodeEncodeError` 退出，连关卡都没跑完。

还有一处**没报错但证据已经脏了**的问题：`gate.py` 用 `encoding="utf-8"` 解码子进程
输出，子进程却按 GBK 编码 —— 编解码口径不一致，中文被 `errors="replace"` 悄悄糊成
乱码，日志看着"有内容"，其实已经不可信。

**三处修法**

1. `gate.py` 给所有子进程显式传 `PYTHONIOENCODING=utf-8`，让子进程的编码与
   父进程的解码口径对齐；
2. 常驻入口脚本（`verify_natives.py` / `expected_asserts.py` / `matrix_daemon.py`）
   在 import 段后自卫：

   ```python
   for _s in (sys.stdout, sys.stderr):
       try:
           _s.reconfigure(errors="replace")
       except Exception:
           pass
   ```

   **只改 `errors` 策略，不改 `encoding`** —— 改成 utf-8 会让 GBK 控制台上的中文
   全变乱码，治了 A 病生 B 病。降级后 `✓` 显示成 `?`，信息量损失为零。
3. 新增 `test_console_encoding.py` 钉成**第 2 关**，含反向对照
   （`test_detector_actually_detects`）：合成样本必须被判为不安全、纯中文必须被放过。
   没有这条反向对照，探测函数一旦写坏就全表恒绿 —— 那正是"校验器自身要有校验器"
   要防的东西。

> **可复用判据：判定不能依赖与被测对象无关的环境细节。**
> round22 的教训是"别让次级判据插到 sentinel 前面"，这次是同一母题的另一面。
> 一个结论取决于调用者当时有没有 `export` 某个变量的门禁，**等于没有门禁**。
> 假 FAIL 比假 PASS 温和，但它同样会训练人去忽略红灯 —— 而红灯一旦被习惯性忽略，
> 下一次真的红灯也就没人看了。

### 11.8 「测的就是交付的」一直没有机器校验，这轮静默破了一次

round23 的收口报告里写着"构建后无 `.galaxy` 变更（测的就是交付的）"。
这轮才发现：**这条性质从来只靠纪律维持，仓库里没有任何检查在守它。**

现场翻出来的漂移：

```
CMLib.SC2Mod/README.md      117181 B   02:28:04   <- 构建时拷进去的，内容只到 round23
scripts/cmlib/README.md     127033 B   02:30:50   <- 源文件，§11 round24 在这里
```

`build_mod.py` 会把源 README 拷进 mod 目录，但 README 是在构建**之后**才被追加
round24 章节的 —— 于是交付的 `.SC2Mod` 里装着一份过期文档，而四件产物、三档矩阵
全都若无其事地绿着。README 不是代码，这次没有功能后果；但同样的时序错位发生在
`.galaxy` 上，结果就是**矩阵验的是旧库、交付的是新库**，且没有任何信号。

**修法**：新增 `check_artifact_freshness.py`，在真机矩阵开跑前做前置校验 ——
凡是进入产物的源文件（`scripts/cmlib/*.galaxy`、`selftest/*.galaxy`、`README.md`），
mtime 必须**早于**四件产物；否则 fail-closed 拒跑，并直接给出"先 rebuild"的指令。

> **可复用判据：写进报告的性质，必须有一个进程在守。**
> "构建后无源码变更"作为一句自觉遵守的纪律写了两轮，这轮就破了 ——
> 而且破得毫无声息。纪律的半衰期很短，检查没有。

## 12. round25：把 round24「未获证据」的清单整个翻掉

round24 在头文件里留了一份 8 项的「未获正向证据、**故意不封装**」清单，
理由写的是「callall 档把它们全加上后过滤产出空组，没崩但也没结果」。

这一轮先复查了那个探针，结论是：**清单是探针设计缺陷造成的，不是符号缺陷。**

### 12.1 `callall` 档从设计上就拿不到任何结论

`callall` 把 7 个未知 setter 一次性全加到同一个 filter 上。而 aifilter 的
条件是 **AND 关系** —— 只要其中任意一个把结果掐成空，整档就是空。

于是「7 个一起上 → 空」和「其中某 1 个坏」之间**没有推理路径**。更糟的是，
它连下面这两种情况都区分不了：

- setter 真的不可用；
- setter 工作得很好，只是我给的参数本来就该把一切过滤掉 —— 而这是**被测对象
  正常工作**的表现。

> **可复用判据：一个不能归因的失败，和没测过，信息量是一样的。**
> 这是 round22「反向对照要精确失败在被测判据上」的镜像面。当时关心的是
> 失败要够精确，这次是失败必须**可归因到单个变量**，否则那次运行白跑。

改法很朴素：一张地图、多个独立 filter、**每档只比公共基线多一个未知 setter**，
用不同的可观测单位编码每一条独立结论，一次真机运行取全部证据
（`probe_aifilter25.py`，iso1~iso4 四档）。判据是双向的：

| 档型 | 参数选择 | 期望 | 落空意味着 |
|---|---|---|---|
| permissive | 一个正常过滤器不该筛掉任何东西 | `count > 0` | 这个 setter 真有问题 |
| restrictive | 一个正常过滤器必须筛成空 | `count == 0` | 过滤器根本没在过滤（平凡解刷绿） |

只有 permissive 会退化 —— 任何「`AIGetFilterGroup` 原样返回源组」的实现都能让
permissive 全绿。restrictive 就是防这个的。

结果：原清单 8 项里 **7 项当场转正**。

### 12.2 `AISetFilterCanAttackEnemy`：非单调响应，拒绝封装

唯一没转正的是它，但失败形态和 round24 猜的完全不是一回事。

iso3 用「能力不同的两种单位 × 不同敌情参数」做交叉判别，打出一个解释不了的
模式：陆战队**能**打地面，可 `(ground=1, air=0)` 照样把它筛空。当时几乎就要
写下「只有 air 参数生效」的结论了 —— iso4 固定 Marine 源组、`air` 恒 0、
**单变量扫 ground**，一扫就翻案：

```
(0,0)  空      (1,0)  空      (5,0)  非空    (99,0)  非空
(0,1)  非空    (0,99) 非空    (1,1)  非空    (99,99) 非空
```

`ground` 从 0→1→5 是 **空→空→非空** 的**非单调**响应。一个名字叫
`enemyGroundCount` 的参数出现非单调跳变，那它就不是数量语义。还有更硬的一条：
`(ground=1, air=0)` 在 Marine 组和 Hellion 组上**同样为空** —— 这两种单位对地
能力天差地别却给出同一结果，证明这一点跟"打不打得到"无关。

它不是不能调用（同图的 restrictive 判决项都命中了，排除了平凡解），是**行为
与文档化的参数名不符**。把这种 API 封进通用库比不封装更危险：调用方会照着
参数名去理解它，然后在最常见的取值 `1` 上拿到一个静默的空组。归 round23
「可调用 ≠ 可用」的变种 —— 那个是恒返回 0，这个是**语义骗人**。

> **可复用判据一：非单调响应 = 参数语义不是你以为的那个。**
> 数量/阈值型参数在 0→1→5 上出现空→空→非空，就别再调参猜语义了，
> 直接判定该 API 语义不可预测。而**单变量扫描是唯一能发现非单调的手段**，
> 多点乱试永远看不出来。
>
> **可复用判据二：三个点连成的直线可以骗人。**
> iso3 的四个数据点全都能被「只有 air 生效」完美解释，可 `ground` 在那四个点里
> 只取过 0/1/99 且从没单独变化过 —— **那是采样不足，不是结论**。
> 简约解释很诱人，采信前必须用单变量扫描证伪一次。

### 12.3 一个从台账上整个漏掉的符号

`AISetFilterMelee` 既不在 round24 的「已验可用」列表里，也不在「故意不封装」
清单里 —— 它在 `callall` 里其实被调用了，只是记录时整个漏掉了。

讽刺的是，补测之后它成了本族**唯一拿到双向证据**的条件：
`want=false` 不误杀（permissive）+ `want=true` 把远程兵筛空（restrictive）。
一个证据最硬的符号，因为手工记账漏项，白白多等了一轮。

> **可复用判据：手工维护的符号台账一定会漏。**
> 「已验 / 未验 / 拒绝」三个清单靠人手同步，就必然出现既不在 A 也不在 B 的
> 幽灵项。这和 round9 那条「模块清单一律从聚合入口自动推导，禁手抄」是同一条，
> 只是这次漏的是 native 而不是模块。

### 12.4 入库的 8 个条件，以及把探针发现变成守门逻辑

新增封装（`CMLib_AIFilter*`）：`ExcludeUnit` · `LifeMod` · `BehaviorCount` ·
`Melee` · `ValidPassenger` · `MarkerCount` · `LifePerMarker` · `CanAttackAlly`。

其中最值得说的是 `CanAttackAlly`。它的两个 bool 描述「要照顾的友军里有没有
地面/空中」，真机实证 `(false, false)` 会把结果**筛成空组**。可绝大多数调用方
会把两个 `false` 读成「我不关心这个维度」—— 语义反了 180 度，而且失败形态是
静默空组，属于最难查的那种。所以库里直接拦掉：

```galaxy
if ((lp_groundAllies == false) && (lp_airAllies == false)) {
    CMLib_LogWarn("AI", "...会筛成空组，不是「不限制」，条件已忽略。");
    return;
}
```

selftest 里对应加了 `ai.filter.canattackally.bothfalse.ignored` 等 9 条断言，
静态断言点 **549 → 558**，期望执行 **547 → 556**。这批断言测的不是引擎行为
（那是探针的活），而是**库自己的防御逻辑**：所有"参数无效"的条件叠加多少条
都不许改变过滤结果，任何一条偷偷传给 native 并掐窄了结果，count 就会偏离基准。

### 12.5 顺手踩到的一条 Galaxy 语法铁律

```galaxy
// 这样写会报 G000 "Expected 2 arguments, got 3" + G1001
CMLib_LogWarn("AI", "前半句"
                    "后半句");
```

**Galaxy 没有 C/Python 那种相邻字符串字面量隐式拼接。** 两行相邻字面量会被
解析成多传一个实参。要拼接必须用 `+`，或者干脆写成一行。

值得庆幸的是这条被全量类型检查（现第 9 关）当场逮住了 —— 属于「静态门禁确实
拦下了一个会让 SC2 静默丢弃整个 MapScript 的错误」的正面案例。

---

## 13. round25 补刀：把「人肉名单」换成可机器推导的台账

§12 收尾时留了个尾巴，值得单独拎出来说，因为它是一类**靠再仔细一点也发现不了**
的缺陷。

### 13.1 症状：一个符号在名单上消失了两轮

round24 在 `cmlib_ai_h.galaxy` 里维护了两张人肉名单：

- 「已验证并封装」的 AIFilter 条件
- 「未获正向证据、故意不封装」的 8 个 `AISetFilter*`

round25 逐符号复测时才发现，`AISetFilterMelee` **两张名单都不在**。它既没被判
"能用"，也没被判"不能用"——它根本没有进入过判断流程。而且它还是本轮唯一拿到
**双向证据**的符号（`want=false` 不误杀 + `want=true` 把远程兵筛空），本该是最
容易过审的那个。

为什么复查发现不了：**你只会核对名单上写了的条目，不会想到名单缺了谁。**
遗漏和错误的可发现性完全不同——错误会在核对时对不上，遗漏在核对时静悄悄。

### 13.2 修法：把名单变成集合等式

不是"下次更仔细"，而是让"仔细"这件事不再由人承担。判据写成三个集合的关系：

```
引擎声明全集(自动扫 TacticalAI.galaxy)
        ==  CMLib 实际调用(自动扫 .galaxy 源)  ∪  显式登记拒绝(人写在头文件)
   且    CMLib 实际调用  ∩  显式登记拒绝  ==  ∅
```

三个集合里**两个是自动推导的，只有一个由人维护**，而人维护的那个只能"多"不能
"少"——少了立刻暴露成 ghost。这就把"别漏"从一个需要注意力的任务，变成了一个
需要主动绕过才能违反的约束。

登记语法就是头文件里一行注释，但它是**机器可读**的：

```galaxy
// @ledger-reject AISetFilterCanAttackEnemy ground 参数 0→1→5 呈空→空→非空的非单调响应，语义与参数名不符（round25 §12.2）
```

四类失败各有明确含义：

| 判定 | 含义 | 典型成因 |
|---|---|---|
| `ghost` | 既没封装也没登记 | 就是 round25 踩的坑：新符号进来没人管 |
| `conflict` | 登记了拒绝，代码里却在调用 | 结论和实现打架 |
| `stale` | 登记了引擎里已经不存在的符号 | 引擎升级后台账没跟着退休 |
| `blank` | 登记了但理由为空 | 为过门禁而写的敷衍登记 |

### 13.3 门禁自己也要有反向对照

这条门禁落地时立刻做了 A/B，否则它可能只是一个恒绿的摆设：

- **删掉登记行** → `FAIL`，精确报 `幽灵项 1 个：AISetFilterCanAttackEnemy`
- **加回登记行** → `PASS`，`24 = 已封装 23 + 登记拒绝 1`

失败是**精确落在被测判据上**的（不是靠崩溃或超时失败），符合 §10.4 对反向对照
的质量要求。

### 13.4 这条门禁在说一件更普遍的事

README 里已经写过好几条"性质"——"测的就是交付的"、"模块清单禁手抄"、
"判定链 sentinel 优先"。round23、round24 各自被打脸一次的原因是同一个：

> **写进文档的性质会自己腐烂，除非有一个进程在守它。**

`check_artifact_freshness.py` 守"测的就是交付的"，`test_verdict_order.py` 守
判定链顺序，`test_console_encoding.py` 守"结论不随环境摇摆"，现在
`check_native_ledger.py` 守"符号覆盖无遗漏"。

规律很清楚：**每一条被写进文档却没有守护进程的性质，都会在两到三轮内被违反。**
纪律有半衰期，检查没有。
---

## 14. round26：把台账门禁从 1 族扩到 14 族

round25 建了 `check_native_ledger.py`（§13），但它当时只管 `aifilter` 一族，
24 个符号。一条只覆盖 1/N 的门禁，绿灯的含金量就是 1/N。

本轮把 `FAMILIES` 从 1 族扩到 **14 族**。扩完立刻炸出 **74 个幽灵项** ——
族内既没被任何 CMLib 函数调用、也没有 `@ledger-reject` 登记的引擎符号。

### 14.1 74 个幽灵项，一个都没往外推

历轮处理"没证据的符号"有两种偷懒姿势：一是登记拒绝（写个理由就完事），
二是把族从 `FAMILIES` 里摘掉（门禁立刻变绿）。两种都是**用判据去迁就现状**，
而不是用现状去满足判据。

本轮的处置是全部封装，**零登记拒绝**。逐族清点：

| 族 | 新封装 | 落在模块 | 代表符号 |
|---|---|---|---|
| `string` | 13 | `cmlib_core` | `StringCase` / `StringCompare` / `StringContains` / `StringWord` / `StringReplace` / `StringReplaceWord` / `StringToAbilCmd` / `StringToDateTime` / `StringExternalAsset` / `StringExternalHotkey` |
| `point` | 9 | `cmlib_geo` | `PointInterpolate` / `PointSet` / `PointSetHeight` / `PointsInRange` / `PointReflect` / `PointPathingCliffLevel` / `PointFromId` / `PointFromName` |
| `region` | 6 | `cmlib_geo` | `RegionSetCenter` / `RegionSetOffset` / `RegionGetOffset` / `RegionAttachToUnit` / `RegionGetAttachUnit` |
| `catalog` | 12 | `cmlib_catalog` | `CatalogEntryClass` / `CatalogEntryParent` / `CatalogField*`（6 个反射） / `CatalogReferenceGet(AsInt)` |
| `order` | 11 | `cmlib_unit` | `OrderSetPlayer` / `OrderGetPlayer` / `OrderSetFlag` / `OrderSetAbilityCommand` / `OrderTargeting*`（3 个构造器） |
| `timer` | 11 | `cmlib_panel` | `TimerLastStarted` / `TimerWindowVisible` / `TimerWindowSet*`（8 个样式 setter） |
| `transmiss` | 5 | `cmlib_conv` | `TransmissionSendForPlayerSelect` / `TransmissionSetOption` / `TransmissionSource*`（3 个） |
| `cinematic` | 4 | `cmlib_fx` | `CinematicMode` / `CinematicOverlay` / `CinematicDataRun` / `CinematicDataStop` |
| `aistock` | 3 | `cmlib_stock` | `AISetStockAlias` / `AISetStockFree` / `AISetStockTechNextUnCap` |
| `vpanel` | 2 | `cmlib_board` | `VictoryPanelSetCustomStatisticText` / `...Value` |
| `aifilter` | 1 | `cmlib_ai` | `AISetFilterEnergy` |
| **合计** | **74** | 11 个模块 | 台账 285 已封装 / 1 登记拒绝 |

唯一的登记拒绝仍是 round25 那条 `AISetFilterCanAttackEnemy`（§12.2 非单调响应，
有硬证据）。**"拒绝"这一栏应该很难写进去，不是很好用的出口。**

### 14.2 ParamDef 元数据不权威，`.galaxy` 源码才是

抽签名时踩到一个和 §12.2 同款诱因的坑：`TransmissionSendForPlayerSelect` 在
`NativeLib.TriggerLib` 的 ParamDef 里返回类型标的是 `transmission`，
但 `natives_missing.galaxy:1596` 的源码写的是 **`native int`**。

照元数据写就是 `transmission CMLib_TransSendForPlayerSelect(...)` —— 类型不匹配，
真机静默丢整个 MapScript。

> **规则：签名一律以 `.galaxy` 源码为准，`.TriggerLib` 的 ParamDef 只当索引用。**

`sig_round26.py` 已按此实现：先扫 `.galaxy` 拿 `decl`，拿不到才回落 `flag`。
74 个符号里 `decl` 命中 74、`no_signature` 0，没有一个是靠元数据蒙的。

### 14.3 自检断言：有读回路径才配写硬断言

74 个封装配了 47 个新断言点（静态 581 → **628**，期望执行 **626**）。
分配原则沿用 §10.3 第 ②、③ 条，没有一刀切：

**写双向 / 往返硬断言**（有独立期望值可比对）：

- `string`：`StringCase` 大小写双向、`StringCompare` 三态、`StringContains`
  三种模式（Begin/End/Anywhere）× 大小写敏感、`StringWord` 1-based 取词、
  `StringReplace` **1-based 闭区间**（官方用例 `StringReplace(s, sub,
  len-subLen+1, len)` 佐证）、`StringReplaceWord` 全替换 / 单次替换。
- `point`：`PointInterpolate` 在 `[0,1]` 外**双向夹紧**、`PointSet(p1,p2)`
  的拷贝方向（是把 p2 写进 p1，不是反过来）、`PointsInRange` 距离双向、
  `PointSetHeight`→`PointGetHeight` 往返。
- `region`：`SetCenter` / `SetOffset` / `AttachToUnit` 三组往返，外加
  **解绑后 `GetAttachUnit` 返 null** 的反向断言。
- `order`：`OrderSetPlayer`→`OrderGetPlayer` 往返、`OrderSetFlag` 双向、
  三个 `OrderTargeting*` 构造器返回非 null。
- `catalog`：`CatalogEntryClass` 同类相等 **且** 缺失条目不等（正反各一），
  `CatalogReferenceGet` 与 `...AsInt` 交叉一致。
- `timer`：`TimerLastStarted` 匹配刚启动的 timer、`TimerWindowVisible` 双向、
  8 个样式 setter 跑完窗口仍可见。

**降级成 bank 诊断探针**（纯 setter，环境里没有读回路径）：
`TimerWindow*` 的位置 / 间距 / 颜色、`Cinematic*`、`TransmissionSource*`、
`VictoryPanelSetCustomStatistic*`、`AISetStock*`、Catalog scope 反射族。
只走调用路径 + 记录返回值，**不判定**。

这条纪律是 round23（`StatEventCreate` 恒返 0）和 round25
（`AISetFilterCanAttackEnemy` 语义骗人）两次教训的直接产物：
**观测不到的东西不要写成断言，写了就是同义反复，恒绿等于没有。**

### 14.4 `isSelect` 参数：57 处官方调用全是 `false`

`TransmissionSendForPlayerSelect` 比普通 `TransmissionSend` 多一个尾参
`isSelect`。翻遍 reference 树，**57 处官方调用一律传 `false`**，`true` 分支
零观测。

处置：封装如实透传，**不为 `true` 分支写任何兜底或"智能"处理**。
理由同 §10.4 —— 没有观测就没有语义，替一个自己没验证过的分支写兜底逻辑，
只是把"不知道"包装成"看起来知道"。头文件里把这个事实写成注释，
调用方自己决定。

### 14.5 门禁自身的两处顺带修

1. **`check_cmlib.py` 会校验注释里的常量**。自检脚本里写了句注释提到
   `c_orderFlag*`，被判「照着写会编译失败」并 WARN —— 引擎确实没为 order flag
   导出具名常量族，只能传裸 int。这不是误报，是门禁在防"文档教人写错代码"。
   改掉措辞即绿。
2. **`test_ledger_sources.py`**（新增）：台账取数从「`.galaxy` 声明」单源扩成
   「`.galaxy` 声明 ∪ `<FlagNative/>`」并集（2875 ∪ 2527 = **2881**），
   新增测试钉住并集逻辑本身。`aistock` 族的 `AISetStockAlias` /
   `AISetStockFree` 就是只有 `<FlagNative/>` 背书、`.galaxy` 里没有声明的，
   单源取数会整个漏掉它们 —— 又一个"遗漏静悄悄"的实例。

### 14.6 这轮的判据教训

> **一条门禁的价值 = 覆盖率 × 判据强度，两者任一为零则整体为零。**

round25 的台账门禁判据很强（集合等式 + 反向对照），但覆盖率只有 1/14，
所以它当时守住的东西比看起来少得多。扩族这个动作本身没有技术含量，
但它把 74 个"从来没人看过一眼"的符号从阴影里拖了出来 —— 而这 74 个里，
没有一个在扩族之前被任何检查报过。

推论：**新建一条门禁之后，紧接着要问的不是"它绿了吗"，而是"它管着多少"。**

---

## 15. round26b：marker 单位标记的不可观测性取证，与一次**有证据的判据降级**

round26 的三档真机矩阵第一次跑出 **BAD**：内联源码版与依赖挂载版都是
`PARTIAL 624/626`，反向对照正常 FAIL。两档失败标签完全一致：

```
marker.aifilter.roundtrip, marker.unit.add
```

**两档同因 + 反向对照仍正确 FAIL = 真实缺陷，不是瞬态。** 这一节记录怎么把
它定位成「引擎性质不可观测」而不是「库有 bug」，以及为什么这次降级判据是
对的、而不是在放水。

### 15.1 现象

```galaxy
CMLib_UnitMarkerAdd(lv_r27u, lv_r27m);
CMLibTest_MarkTag(CMLib_UnitMarkerCount(lv_r27u, lv_r27m) >= 1, "marker.unit.add");  // 实得 0
```

库封装是薄透传 + null 守门，没有写反的余地：

```galaxy
void CMLib_UnitMarkerAdd(unit lp_unit, marker lp_marker) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    if (lp_marker == null) { return; }
    UnitMarkerAdd(lp_unit, lp_marker);
}
```

### 15.2 四条独立取证

1. **marker 句柄是活的，不是死壳。** 同一个 `lv_r27m` 上，
   `marker.matchflag.set` / `marker.matchflag.clear`（`MarkerSetMatchFlag`
   → `MarkerGetMatchFlag` 往返）与 `marker.dt.roundtrip`
   （`DataTableSetMarker` → `DataTableGetMarker`）**四条真机全过**。
   所以 `Marker()` 造出来的对象引擎认、能改、能存取 —— 问题不在生产端。

2. **`UnitMarkerAdd` 在整棵官方参考树里零调用。** 扫过 core.sc2mod、
   三部战役（Liberty / Swarm / Void）、starcoop、alliedcommanders、
   SC Evo Complete，`UnitMarkerAdd` 一次都没被调过。而 `UnitMarkerCount`
   的官方用法**全部**是这一种形态：

   ```galaxy
   marker AIMarker (unit aiUnit, string name) {
       marker mark = MarkerCastingUnit(name, aiUnit);
       MarkerSetMatchFlag(mark, c_markerMatchLink, true);
       MarkerSetMatchFlag(mark, c_markerMatchCasterPlayer, true);
       return mark;
   }
   // ...
   if (UnitMarkerCount(unitToCheck, mark) > 0) { return null; }  // 已被标记过，跳过
   // ...
   AICast(aiUnit, ord, mark, retreat);   // <-- 标记是**引擎**在这一步打上去的
   ```

   即 marker 是引擎为 `AICast` 做的**防重复施法记账**：写端在引擎里，
   脚本只有读端。

3. **marker 族 native 没有 Id / Duration 的 setter。** 全集只有：

   | 生产 | 施法者 | 匹配 | 单位标记表 | DataTable |
   |---|---|---|---|---|
   | `Marker` / `MarkerCastingPlayer` / `MarkerCastingUnit` | `MarkerSet/GetCastingPlayer` · `MarkerSet/GetCastingUnit` | `MarkerSet/GetMatchFlag` · `MarkerSet/GetMismatchFlag` | `UnitMarker` / `UnitMarkerAdd` / `UnitMarkerCount` / `UnitMarkerRemove` | `DataTableSet/GetMarker` |

   而 `c_markerMatchId = 0` 明确说明 **Id 参与匹配**。脚本能设 link、能设
   施法者、能设匹配标志，唯独设不了 Id —— 造不出带引擎身份的完整 marker。

4. **替代假设也一并证伪。** 「是不是少设了 match flag」是最像的另一种解释
   （官方 `AIMarker()` 确实必设两个 flag）。所以这轮没有靠推断结案，而是把
   三种变体做成 bank 探针一次跑完，让数据自己说话：

   | bank 键 | 变体 | 真机实测 |
   |---|---|---|
   | `Result/MkPlain` | 裸 `Marker(link)`，不设任何 flag（原失败写法） | **0** |
   | `Result/MkLinkPre` | `MarkerCastingUnit("Abil/Snipe/AI", u)` + `c_markerMatchLink`，**add 前**（对照基线） | **0** |
   | `Result/MkLink` | 同上，**add 后** | **0** |
   | `Result/MkOfficial` | 再叠 `c_markerMatchCasterPlayer`（逐字复刻 `AIMarker()`） | **0** |
   | `Result/MkAIWith` / `Result/MkAIWithout` | AI 线 `AISetFilterMarker` 打标记 / 不打标记两态 | **0 / 0** |

   **替代假设就此证伪。** 连「真实技能 link（`Abil/Snipe/AI` 就是
   core.sc2mod `RequirementsAI.galaxy` 里 `c_MK_Snipe` 的原值）+
   `MarkerCastingUnit` + 两个官方 match flag」这种逐字复刻 `AIMarker()` 的
   写法都是 0，且 add 前 / add 后**没有任何变化** —— 不是 flag 设漏了，是
   脚本构造的 marker 根本进不了单位的标记表。15.2 的结论至此坐实。

   探针留在原地，只记录、不判定。**将来任一变体出现非 0，就能凭证据把硬
   断言提回来** —— 降级不是删除，是把结论换成一个自带观测点的开放问题。

### 15.3 为什么这次降级不是放水

判据坏死有两种：**恒红**（断言与被测系统设计冲突）和**恒绿**（同义反复）。
`marker.unit.add` 属于第一种 —— 它断言的根本不是库的行为，而是
「引擎的 `UnitMarkerAdd` 对脚本构造的 marker 生效」这条**引擎性质**，而这
条性质在纯脚本环境里没有任何可观测路径。

对照 round25 处置 `AISetFilterCanAttackEnemy` 的先例，判断标准是同一条：

> **有读回路径 / 独立期望值 → 写双向硬断言；没有 → 降级为诊断探针，
> 只记录不判定。**

所以这次动的只有「往返」这一条，**守门判据一条没减**：
`marker.create` / `marker.create.empty` / `marker.unit.count.clean` /
`marker.unit.remove` / `marker.unit.nullsafe` / `marker.cast.player` /
`marker.cast.unit` / `marker.cast.degrade` / `marker.matchflag.set` /
`marker.matchflag.clear` / `marker.matchflag.oob` / `marker.dt.roundtrip` /
`marker.dt.miss` 全部保留为硬断言。封装也一个没删 —— 配合 `AICast` 写入的
marker 时，读路径依然是有效能力。

**"修 bug ≠ 放宽判据" 的边界在这里：** 删掉一条**能测出库缺陷**的断言是
放水；删掉一条**测的是环境而不是库**的断言是纠错。区别在于有没有拿到证据、
以及降级后有没有留下可复查的观测点。这两样这轮都做了。

### 15.4 顺带揪出一条**恒绿**判据

`marker.aifilter.lifepermarker.roundtrip` 一直是绿的，看起来在守
`AISetFilterLifePerMarker` 的 marker 语义。但它绿得有问题：

本局单位实际标记数为 **0**，引擎把 life-per-marker 退化成了纯生命门槛
（门槛 `1.0` 放行、`99999.0` 筛掉，响应单调）。也就是说这条判据证明的是
**`each` 形参被正确透传**，跟 marker 形参一点关系都没有 —— 换个 marker、
甚至传 null，它照样绿。

没删它（它对 `each` 仍是有效判据），但在源码里写死了注释，避免下一轮有人
把它当 marker 覆盖率来用。**一条判据"绿着"和"守着你以为它守的东西"是两回
事**，这是本轮第二次踩到同一个模式。

### 15.5 教训

> **判据失败时的第一个问题不是"怎么让它变绿"，而是"它到底在断言谁"。**

`marker.unit.add` 断言的主语其实是引擎，不是库。主语搞错的判据，无论怎么
调都不会给出有用信息 —— 修它、删它、放宽它，三条路全是错的，唯一对的是
**把它换成能回答问题的观测**。

配套推论：**零官方调用的 native 是高危信号。** `UnitMarkerAdd` 在
`natives.galaxy` 里声明得清清楚楚、签名合理、静态检查全过、运行时也不报错
—— 唯一的异常信号就是"全世界没人调过它"。这一条比任何静态检查都更早地
指向了正确答案，值得写进例行排查顺序。
