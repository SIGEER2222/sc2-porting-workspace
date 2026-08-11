"""README round18 补丁：把本轮新增的 28 个 API 写进 §2.x 速查表（幂等）。

为什么要单写补丁脚本而不是手改：
  README 有 965 行、22 个模块小节，手改极易插错小节（插到隔壁模块的表里
  读者就再也找不到）。脚本按「小节标题 -> 该小节最后一行表格行」定位，
  插错的可能性归零；重跑时按函数名去重，不会追加重复行。

去重判据：每组 rows 的第一行里的函数名如果已在 README 中出现，则整组跳过。
"""
import re
import sys
from pathlib import Path

README = Path(__file__).resolve().parent / "scripts" / "cmlib" / "README.md"

# (小节标题前缀, [要追加的表格行, ...])
SECTIONS: list[tuple[str, list[str]]] = [
    ("### 2.2 UI (`cmlib_ui`)", [
        "| `int DlgCtrlCreate(dialog,type)` / `DlgCtrlCreateTpl(dialog,type,template)` | 在**对话框**里建控件（区别于 `UICreateInPanel` 的 UI 面板）；模板名传 `\"\"` 自动退化成无模板版 |",
        "| `int DlgCtrlSelectedItem(control,player)` | 列表/下拉当前选中项（1-based；无效控件返回 `0`） |",
        "| `void DlgCtrlFullDialog(control,players,full)` | 控件铺满整个对话框（做全屏面板的常用姿势），`players` 传 null = 所有玩家 |",
        "| `void DlgCtrlDestroy(control)` | 销毁对话框控件；无效 id 静默跳过（重复销毁不崩） |",
        "| `void UIFaceHighlight(players,face,highlight)` | 按钮 face 高亮开关（教程引导/技能提示常用） |",
    ]),
    ("### 2.3 Unit (`cmlib_unit`)", [
        "| `bool UnitHasBehaviorRaw(unit,behavior)` | 直接问引擎「有没有这个 behavior」，不过 CMLib 的层数缓存（层数为 0 但 buff 仍挂着时与 `UnitBehaviorCount` 结论不同） |",
        "| `int UnitOrderCount(unit)` | 当前命令队列长度（判「是否空闲」比 `UnitIsIdle` 更细粒度） |",
        "| `void UnitTeamColor(unit,index)` | 覆写单位队伍色索引（区分同阵营小队常用） |",
        "| `fixed UnitAbilChargeInfo(unit,abilcmd,type)` | 技能充能信息。`type` 取 `c_unitAbilChargeCountMax(0)/CountUse(1)/CountLeft(2)/RegenMax(3)/RegenLeft(4)` |",
        "| `void UnitAbilReset(unit,abilcmd,location)` | 重置技能冷却/充能；`location` 是**裸 int**（引擎没有 `c_abilResetLocation*` 常量族） |",
        "| `unitref UnitRefFromVar(varName)` | 由变量名取 unitref（存档/配置驱动的单位引用）；名字为空返回 null |",
        "| `unitgroup UGFilterRegion(group,region,maxCount)` | 按区域筛子组。`maxCount <= 0` 归一到 `c_unitCountAll(0)` = 不限量（**负数直接丢给原生行为未定义**，所以统一夹到 0） |",
    ]),
    ("### 2.7 AI (`cmlib_ai`)", [
        "| `void AIUnitSuicide(unit,enable)` / `AIGroupSuicide(group,enable)` | 自杀式冲锋开关：开了之后 AI 不再考虑撤退保命 |",
        "| `void AIGroupScriptControlled(group,enable)` | 把一组单位从 AI 托管里摘出来交给脚本（做剧本化战斗必备） |",
        "| `int AIState(player,index)` | 读 AI 状态槽；`index` 是**裸 int**（AI.galaxy 里没有 `c_ASState*` 常量族） |",
        "| `void AISubStateChance(subState,chance)` | 调 AI 子状态触发概率（波次难度微调） |",
    ]),
    ("### 2.8 FX (`cmlib_fx`)", [
        "| `void SfxPlayOwned(soundId,owner,players,volume)` | 带归属玩家的音效播放（谁放的技能，音量归谁），空 id / 非法槽守门 |",
    ]),
    ("### 2.11 Geo (`cmlib_geo`)", [
        "| `fixed SinDeg(deg)` / `fixed CosDeg(deg)` | 度制三角函数（引擎原生 `Sin/Cos` 就是度制，这里只是把单位写进名字，省得每次去查） |",
        "| `fixed NormalizeAngle(deg)` | 角度归一到 `[0,360)`；做朝向差值/转向插值前先过一道，避免 `-350` 这类值把比较逻辑带沟里 |",
    ]),
    ("### 2.13 Trig (`cmlib_trig`)", [
        "| `trigger TrigFindByFunc(funcName)` | 按**函数名**找引擎里已注册的 trigger（`TriggerFind`）。⚠️ 与 §2.13 的 `TrigFind` 不是一回事——后者查的是 CMLib 自己的注册表 |",
        "| `void TrigOnPlayerPropChange(t,player,prop)` | 绑定玩家属性变化事件；`prop` 取 `c_playerPropMinerals(0)` 等 |",
        "| `string TrigEventParamName(eventName,paramName)` | 自定义脚本事件的参数名解析（`TriggerSendEvent` 那套的配套）；任一入参为空返回 `\"\"` |",
        "| `fixed EvtDamageAmount()` / `string EvtUpgradeName()` | **事件上下文专用**：读本次伤害数值 / 本次升级名。脱离事件上下文调用返回 0 / `\"\"` |",
    ]),
    ("### 2.16 UData (`cmlib_udata`)", [
        "| `string UDataUserInstance(type,instance,field,index)` | 读 UserData 表里某实例的字段（数据表驱动配置的读取端），任一入参为空返回 `\"\"` |",
    ]),
]


def find_section_insert_point(lines: list[str], heading: str) -> int:
    """返回该小节最后一行表格行的下标（插入点在其后）。找不到返回 -1。"""
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith(heading))
    except StopIteration:
        return -1
    last_row = -1
    for i in range(start + 1, len(lines)):
        l = lines[i]
        if l.startswith("### ") or l.startswith("## "):
            break
        if l.startswith("| ") and not l.startswith("|---"):
            last_row = i
    return last_row


def main() -> int:
    text = README.read_text(encoding="utf-8")
    lines = text.split("\n")
    added = 0
    skipped = []
    # 从后往前插，避免前面的插入把后面的下标顶偏
    for heading, rows in reversed(SECTIONS):
        key = re.search(r"`[a-z]+ (\w+)\(", rows[0])
        keyname = key.group(1) if key else rows[0][:20]
        if keyname in text:
            skipped.append(f"{heading.split()[1]}({keyname} 已存在)")
            continue
        at = find_section_insert_point(lines, heading)
        if at < 0:
            print(f"[readme18] !! 找不到小节或表格: {heading}")
            return 1
        lines[at + 1:at + 1] = rows
        added += len(rows)

    if added:
        README.write_text("\n".join(lines), encoding="utf-8")
    print(f"[readme18] 追加 {added} 行；跳过 {len(skipped)} 个小节"
          + (f"（{', '.join(skipped)}）" if skipped else ""))
    return 0


sys.exit(main())
