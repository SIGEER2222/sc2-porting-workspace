# -*- coding: utf-8 -*-
"""幂等补丁：把 round16/17 新增的 165 个 API 补进 scripts/cmlib/README.md。

为什么单独写脚本而不是手改：
    README 是"库的对外契约"，漏记的 API 等于不存在——别人不会去翻 _h。
    每轮扩库都要做一次同样的"_h 声明 vs README 提及"差集补齐，
    脚本化才能保证下轮还能重复做，且不会因为手滑改坏已有表格。

幂等：靠 MARK 判定，已打过就 SKIP。
"""
import re
import sys
from pathlib import Path

README = Path(__file__).resolve().parent / "scripts" / "cmlib" / "README.md"
MARK = "<!-- cmlib-readme-round17 -->"

TREE_OLD = ("└── cmlib_buff(_h).galaxy   ← Behavior 增益减益 / 单位状态开关 / 玩家状态开关")
TREE_NEW = (
    "├── cmlib_buff(_h).galaxy   ← Behavior 增益减益 / 单位状态开关 / 玩家状态开关\n"
    "├── cmlib_path(_h).galaxy   ← 地形寻路查询 / 路线（Route）可视化编排\n"
    "├── cmlib_env(_h).galaxy    ← 装饰物 Doodad / 地形贴图 / 水面 / 战争迷雾外观\n"
    "└── cmlib_stat(_h).galaxy   ← 成就 / 分数 / 难度名 / 效果历史 / 战役模式 / 时间戳"
)

UI_ADD = """| `int UIHookupButton/Label/Image(parent,name)` | 按类型挂钩的语义化快捷方式（比 `UIHookup(parent,c_triggerControlTypeX,name)` 少记一个枚举） |
| `UISetTooltip/Image/Color/Toggled/Enabled/Active(control,players,v)` | 单属性设置，全部带 `playergroup` 维度 + 无效控件守门 |
| `UISetPosition(control,players,anchor,ox,oy)` / `UISetPositionRelative(...,relative,relAnchor,ox,oy)` | 绝对锚点定位 / 相对另一控件定位 |
| `UISetAnimationState(control,players,stateGroup,state)` / `UISetRenderPriority(control,players,prio)` | 动画状态机 / 渲染层级 |
| `UIListAddItem(control,players,text)` / `UIListSelect(control,players,index)` | 列表项追加 / 选中（`index` 越界守门） |
| `UISetMode(players,mode,duration)` / `UIMode(players,mode)` | UI 模式切换（带/不带过渡时长）；`mode` 取 `c_uiModeFullscreen(0)/Letterboxed(1)/Console(2)` |
| `UIModeFullscreen/Letterbox/Console(players,duration)` | 三种模式的语义化包装，做过场时不用再记枚举值 |
| `UICursor(players,visible)` | 鼠标指针显隐（过场/纯剧情段常用） |
| `UISelectionType(players,selectionType,enabled)` | 开关某种选择方式（框选/双击同类等）。**注意：引擎没有 `c_selectionType*` 常量族，只能传裸 int**，本库自测用字面量 `0` |

"""

UNIT_ADD = """| `unitfilter FilterAliveVisible/AliveVisibleTargetable/Structure/NonStructure()` | 预设过滤器的具名构造（"建筑"走 **attribute** `c_unitAttributeStructure=7`，**不存在** `c_unitFlagStructure`） |
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

"""

PLAYER_ADD = """| `bool PlayerIsHuman/IsComputer/IsEnvironment(player)` | 槽位类型判定；底层 `c_playerTypeUser=1/Computer=2/None=0`，非法槽一律 false 不崩 |
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

"""

PANEL_ADD = """| `int PanelCreateCentered(w,h)` / `PanelCreateAnchored(w,h,anchor,margin)` / `PanelCreateOverlay()` | 三种常用容器创建姿势（居中 / 贴边带边距 / 全屏覆盖层） |
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

"""

BANK_ADD = """| `BankGetString/Bool/Fixed` / `BankSetString/Bool/Fixed` | 三种非 int 类型的读写（`Get*` 一律强制 fallback，`Set*` 自动置脏） |
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

"""

NEW_SECTIONS = """### 2.20 Path (`cmlib_path`)
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

"""


def insert_before(text, anchor, payload, what):
    if anchor not in text:
        raise SystemExit("找不到锚点（%s）：%r" % (what, anchor[:40]))
    return text.replace(anchor, payload + anchor, 1)


def main():
    src = README.read_text(encoding="utf-8")
    if MARK in src:
        print("[readme] 已含 round17 标记，SKIP")
        return

    if TREE_OLD not in src:
        raise SystemExit("找不到目录树锚点")
    src = src.replace(TREE_OLD, TREE_NEW, 1)

    src = insert_before(src, "\n### 2.3 Unit (`cmlib_unit`)", UI_ADD, "ui")
    src = insert_before(src, "\n### 2.4 Catalog (`cmlib_catalog`)", UNIT_ADD, "unit")
    src = insert_before(src, "\n### 2.6 数组参数约定", PLAYER_ADD, "player")
    src = insert_before(src, "\n### 2.10 Bank (`cmlib_bank`)", PANEL_ADD, "panel")
    src = insert_before(src, "\n### 2.11 Geo (`cmlib_geo`)", BANK_ADD, "bank")
    src = insert_before(src, "\n---\n\n## 3. 设计约定", NEW_SECTIONS, "new-sections")

    src = src.replace("## 2. 模块 API 速查\n",
                      "## 2. 模块 API 速查\n\n" + MARK + "\n", 1)

    README.write_text(src, encoding="utf-8")

    # 补完后复算差集，确认真的没漏
    import glob
    import os
    base = README.parent
    left = {}
    for h in sorted(glob.glob(str(base / "cmlib_*_h.galaxy"))):
        mod = os.path.basename(h)[6:-9]
        fns = sorted(set(re.findall(r"^[a-z]+\s+(CMLib_([A-Za-z0-9_]+))\(",
                                    open(h, encoding="utf-8").read(), re.M)))
        miss = [n for _f, n in fns if n not in src]
        if miss:
            left[mod] = miss
    print("[readme] 补丁已写入，%d 行" % len(src.splitlines()))
    if left:
        print("[readme] 仍未记录的 API：")
        for mod, miss in left.items():
            print("  %-8s %d 个: %s" % (mod, len(miss), ", ".join(miss[:12])))
    else:
        print("[readme] 全部 _h 声明的 API 均已在 README 中出现")


main()
