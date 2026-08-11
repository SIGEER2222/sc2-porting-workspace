# -*- coding: utf-8 -*-
"""幂等地把第 18 模块 cmlib_buff 与 trig 事件注册器族补进 README。

为什么不用编辑器的 Edit：本仓库同一时段可能有多个自动化实例在写同一份 README，
Edit 的 read-before-write 校验会被并发写打断。这里用「读-判断-写」一次完成，
且每处补丁都先检查标记是否已存在（幂等），重复执行不会产生重复段落。
"""
import io
import os
import sys

README = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "scripts", "cmlib", "README.md")

TREE_OLD = "└── cmlib_board(_h).galaxy  ← 排行榜面板（Board）/ 任务结算面板（VictoryPanel）"
TREE_NEW = (
    "├── cmlib_board(_h).galaxy  ← 排行榜面板（Board）/ 任务结算面板（VictoryPanel）\n"
    "└── cmlib_buff(_h).galaxy   ← Behavior 增益减益 / 单位状态开关 / 玩家状态开关"
)

TRIG_ANCHOR = ("| `TrigOnPlayerLeft/AllianceChange/AIWave/Chat/Generic` + "
               "`TrigSend(evt)` | 玩家/聊天/自定义事件 |")
TRIG_INSERT = """| `TrigOnUnitRegion(t,u,region,entering)` / `TrigOnUnitRegionBoth(t,u,region)` | 区域进出（Both = 同时挂 Enter+Exit，避免"区域内计数"单向漂移） |
| `TrigOnUnitRange(t,u,from,dist)` / `TrigOnUnitRangePoint(t,u,point,dist)` | 进入某单位/某点的半径范围 |
| `TrigOnUnitCargo(t,u,loading)` / `TrigOnUnitSelected(t,u,player,sel)` / `TrigOnUnitClicked` / `TrigOnUnitHighlight` | 载具装卸 / 选中 / 点击 / 鼠标悬停 |
| `TrigOnUnitAbility(t,u,abilcmd,stage,includeShared)` / `TrigOnUnitAbilityUsed(t,u,abilcmd)` | 技能事件；`AbilityUsed` = Execute 阶段 + includeShared（建造类共享技能才收得到） |
| `TrigOnUnitAutoCast` / `TrigOnUnitOrder` / `TrigOnUnitProperty(t,u,prop)` / `TrigOnUnitBehavior(t,u,behavior,change)` | 自动施法开关 / 下令 / 属性变化（生命等）/ Behavior 增删激活 |
| `TrigOnConstructProgress/TrainProgress/ResearchProgress/ReviveProgress/LearnProgress/SpecializeProgress/ArmMagazineProgress(t,u,stage)` | 七类进度事件（`stage` 取 `c_unitProgressStage*`：Start/Complete/Cancel/Pause/Resume） |
| `TrigOnBuildingDone/TrainDone/ResearchDone/UnitRevive/UnitPowerup(t,u)` | 上述进度的 Complete 快捷入口（最常用，免记 stage 常量） |
| `TrigOnEffectUsed(t,player,effect)` / `TrigOnEffectScope(t,player,scope)` | 效果触发（伤害/治疗链路挂钩） |
| `TrigOnDialogControl(t,player,control,eventType)` / `TrigOnButtonClick(t,control)` | 面板控件事件；`ButtonClick` = 任意玩家 + Click，覆盖 90% 场景 |
| `region EvtRegion()` `unit EvtRangeUnit/EvtCargoUnit/EvtProgressUnit/EvtEffectUnit/EvtEffectCaster/EvtEffectTarget()` `abilcmd EvtAbility()` `int EvtAbilityStage/EvtProgressType/EvtControl/EvtControlEventType()` `string EvtBehavior/EvtEffect()` `point EvtEffectPoint()` `bool EvtIsControl(c)` | 新增事件族取参（仅执行期有效） |"""

BUFF_ANCHOR = "---\n\n## 3. 设计约定"
BUFF_SECTION = """### 2.19 Buff (`cmlib_buff`)
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

---

## 3. 设计约定"""


LESSON_ANCHOR = "---\n\n## 6. 分发与接入"
LESSON_TEXT = """- **裸调用 `Wait(secs)` 少传时间类型 → 静默丢弃整个 MapScript（2026-08-08 第 7 轮）**：
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

"""


def main() -> int:
    with io.open(README, encoding="utf-8") as f:
        txt = f.read()
    orig = txt
    done = []

    # 1) 目录树补 cmlib_buff
    if "cmlib_buff(_h).galaxy" not in txt and TREE_OLD in txt:
        txt = txt.replace(TREE_OLD, TREE_NEW, 1)
        done.append("目录树 +cmlib_buff")

    # 2) Trig 表格补事件注册器族
    if "TrigOnUnitRegionBoth" not in txt and TRIG_ANCHOR in txt:
        txt = txt.replace(TRIG_ANCHOR, TRIG_ANCHOR + "\n" + TRIG_INSERT, 1)
        done.append("§2.13 +事件注册器族")

    # 3) 新增 §2.19 Buff
    if "### 2.19 Buff" not in txt and BUFF_ANCHOR in txt:
        txt = txt.replace(BUFF_ANCHOR, BUFF_SECTION, 1)
        done.append("+§2.19 Buff")

    # 4) §5.3 追加本轮（第 7 轮）真机/门禁抓出的缺陷
    if "裸调用 `Wait(secs)`" not in txt and LESSON_ANCHOR in txt:
        txt = txt.replace(LESSON_ANCHOR, LESSON_TEXT + LESSON_ANCHOR, 1)
        done.append("§5.3 +第 7 轮教训")

    # 5) 计数订正（幂等：只改还没改的）
    fixes = [
        ("Base.SC2Data/scripts/cmlib/*.galaxy    ← 35 个文件",
         "Base.SC2Data/scripts/cmlib/*.galaxy    ← 37 个文件"),
        ("即可调用全部 17 个模块。", "即可调用全部 18 个模块。"),
        ("打包产物：`CMLib_out.SC2Mod`（MPQ，110 KB）",
         "打包产物：`CMLib_out.SC2Mod`（MPQ，126 KB）"),
        ("依赖挂载版实测 PASS 39/39。", "依赖挂载版实测 PASS 39/39（该轮基线）。"),
        ("`src/lib/build_typecheck_unit.py` 把 17 个模块",
         "`src/lib/build_typecheck_unit.py` 把 18 个模块"),
    ]
    for old, new in fixes:
        if old in txt:
            txt = txt.replace(old, new, 1)
            done.append("计数订正: " + old[:24])

    if txt == orig:
        print("[readme] 无需改动（已是最新）")
        return 0
    with io.open(README, "w", encoding="utf-8", newline="\n") as f:
        f.write(txt)
    print("[readme] 已应用: " + " | ".join(done))
    return 0


if __name__ == "__main__":
    sys.exit(main())
