"""AI 战术过滤族 —— 逐符号隔离探针（round25）。

## 为什么要重做一遍探针

round24 的 `callall` 档把 **7 个未知 setter 一次性全加上**，结果 Thor 缺席
（过滤产出空组），当时记的结论是「成因未二分定位，下轮继续」。

复查后判定：**`callall` 这个档的设计本身就是坏的，它拿不到任何可归因的结论**。

    17 个条件是 AND 关系。只要其中任意一个把结果掐成空，整档就是空。
    「7 个一起上 -> 空」和「其中某 1 个坏」之间没有推理路径。
    更糟的是：它连「到底是 setter 不可用，还是我给的参数本来就该过滤掉一切」
    都区分不了 —— 而后者是**被测对象正常工作**的表现。

这正是 round22 记的那条「反向对照要精确失败在被测判据上」的镜像：
**一个不能归因的失败，和没测过，信息量是一样的。**

## round25 的设计：一次运行，逐符号隔离 + 双向判据

改成「一张地图、多个独立 filter、每个 filter 只比基线多一个未知 setter」，
用不同的可观测单位编码每一条独立结论。一次真机运行拿全部证据。

判据是**双向**的，缺一不可：

    permissive 档   给「一个正常工作的过滤器不该筛掉任何东西」的参数
                    -> 期望 count > 0。落空 = 这个 setter 真有问题。
    restrictive 档  给「一个正常工作的过滤器必须筛成空」的参数
                    -> 期望 count == 0。落空 = 过滤器根本没在过滤
                                          （结果恒等于输入组 = 平凡解刷绿）。

只有 permissive 档会退化：任何「AIGetFilterGroup 直接把源组原样返回」的实现
都能让 permissive 全绿。restrictive 档就是防这个的 —— round22 那条
「单一标量指标都可被退化到平凡解刷绿」的直接应用。

## 顺带补上一个记账漏洞

round24 的头文件把「未获正向证据、故意不封装」列了 8 个，但
`AISetFilterMelee` **一个都没提** —— 它既没被封装，也不在那份清单里，
是从台账上整个漏掉的。（`callall` 里其实调了它，只是没记进清单。）
本轮把它一并纳入探测，并另建机器可推导的台账门禁防止再漏（见
`check_native_ledger.py`）。

`AISetFilterMarker` / `AISetFilterLifePerMarker` 历轮**从未进过任何探针**
（它们要 `marker` 句柄，callall 也没带上），本轮首次覆盖。

## 用法

    python probe_aifilter25.py                # 两档全跑
    python probe_aifilter25.py iso1           # 只跑指定档
    python probe_aifilter25.py --wait 60      # 真人局占机时排队等待
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
sys.path.insert(0, str(REPO / "reference" / "SC2-Neuro-API-Integration"))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402

LIB = REPO / "src" / "lib"
sys.path.insert(0, str(LIB))

from sc2_api_conn import acquire_launched  # noqa: E402
from sc2_proc_guard import human_games     # noqa: E402

SRC_MAP = LIB / "_testmap_src"
BUILD = LIB / "_aifilter25_build"
OUT_MAP = LIB / "probe_aifilter25.SC2Map"
PACKER = REPO / "tools" / "mpq" / "scripts" / "pack_stormlib.py"
STORMLIB = REPO / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll"
RESULT = LIB / "probe_aifilter25_result.json"

# 观测编码用的单位型号。全部是 WoL 就有的人族单位，避免「型号在依赖里不存在
# -> UnitCreate 静默返回 null」被误读成「结论为否」。
MARKERS = ("Ghost", "Banshee", "VikingFighter", "Marauder", "Reaper",
           "Hellion", "SiegeTank", "Thor", "Raven", "Battlecruiser",
           "WidowMine", "Cyclone", "SCV", "Medivac")

_SPAWN = ('    UnitCreate({n}, "{u}", c_unitCreateIgnorePlacement, {p},\n'
          "               RegionGetCenter(RegionPlayableMap()), 270.0);\n")


def spawn(u: str, n: int = 1, p: int = 1) -> str:
    return _SPAWN.format(u=u, n=n, p=p)


# round24 已验可用的 5 个 permissive setter，作为每个隔离档的公共基线。
# 之所以要带基线而不是"裸 filter + 一个 setter"：callmid 档已实证这 5 个
# 组合起来产出非空组，用它打底才能保证"空组"只可能由本档新增那一个引起。
BASE = ("    AISetFilterAlliance({f}, c_playerGroupAny);\n"
        '    AISetFilterBits({f}, UnitFilterStr(""));\n'
        "    AISetFilterPlane({f}, 0);\n"
        "    AISetFilterLife({f}, 0.0, 100000.0);\n"
        "    AISetFilterInCombat({f}, false);\n")


def case(idx: int, extra: str, marker: str, want_empty: bool = False,
         grp: str = "lv_all") -> str:
    """生成一个隔离档：基线 + 一条 extra，按 count 是否满足期望 spawn marker。

    want_empty=False -> count > 0 才 spawn（permissive 判据）
    want_empty=True  -> count == 0 才 spawn（restrictive 反向对照）
    """
    f = "lv_f"
    cmp_ = "== 0" if want_empty else "> 0"
    return (f"    {f} = AIFilter(1);\n"
            + BASE.format(f=f)
            + extra.format(f=f)
            + f"    lv_n = UnitGroupCount(AIGetFilterGroup({f}, {grp}),"
              " c_unitCountAll);\n"
            + f"    if (lv_n {cmp_}) {{\n"
            + "    " + spawn(marker).lstrip()
            + "    }\n")


# ---------------------------------------------------------------------------
# iso1：round24 callall 里那 7 个未知 setter，逐个隔离（全 permissive 参数）
# ---------------------------------------------------------------------------
_ISO1_HEAD = (
    "void InitMap () {\n"
    "    aifilter  lv_f;\n"
    "    unitgroup lv_all;\n"
    "    unit      lv_u;\n"
    "    unit      lv_med;\n"
    "    point     lv_c;\n"
    "    int       lv_n;\n"
    + spawn("Ghost")
    + "    lv_c = RegionGetCenter(RegionPlayableMap());\n"
      '    UnitCreate(1, "Medivac", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      "    lv_med = UnitLastCreated();\n"
      '    UnitCreate(3, "Marine", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      "    lv_u = UnitLastCreated();\n"
      '    lv_all = UnitGroup("Marine", 1, RegionEntireMap(), UnitFilterStr(""), 0);\n'
)

BODY_ISO1 = (
    _ISO1_HEAD
    # 前提：只有基线（round24 callmid 已验）的过滤器必须产出非空组。
    # 前提塌了，本档所有结论一律不作数 —— 判定链顺序铁律。
    + case(0, "", "VikingFighter")
    # exclude=null 应当"什么都不排除"
    + case(1, "    AISetFilterSelf({f}, null);\n", "Marauder")
    # type=0 / mod=1.0：倍率 1 应当等价于不改
    + case(2, "    AISetFilterLifeMod({f}, 0, 1.0);\n", "Reaper")
    # 要求"能打到 >= 0 个地面 / 0 个空中敌人"——恒真
    + case(3, "    AISetFilterCanAttackEnemy({f}, 0, 0);\n", "Hellion")
    # 不要求能打友军
    + case(4, "    AISetFilterCanAttackAlly({f}, false, false);\n", "SiegeTank")
    # Stimpack 层数落在 [0,1000] —— 陆战队一层都没有，0 也在区间内
    + case(5, '    AISetFilterBehaviorCount({f}, 0, 1000, "Stimpack");\n', "Thor")
    # 不要求近战（陆战队是远程）
    + case(6, "    AISetFilterMelee({f}, false);\n", "Raven")
    # 医疗运输机在场，陆战队是合法乘客
    + case(7, "    AISetFilterValidPassenger({f}, lv_med);\n", "Battlecruiser")
    + spawn("Banshee")
    + "}\n"
)

# ---------------------------------------------------------------------------
# iso2：marker 族首测 + 反向对照（证明过滤器真的在过滤，不是原样返回）
# ---------------------------------------------------------------------------
BODY_ISO2 = (
    "void InitMap () {\n"
    "    aifilter  lv_f;\n"
    "    unitgroup lv_all;\n"
    "    unit      lv_u;\n"
    "    marker    lv_m;\n"
    "    point     lv_c;\n"
    "    int       lv_n;\n"
    + spawn("Ghost")
    + "    lv_c = RegionGetCenter(RegionPlayableMap());\n"
      '    UnitCreate(3, "Marine", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      "    lv_u = UnitLastCreated();\n"
      '    lv_all = UnitGroup("Marine", 1, RegionEntireMap(), UnitFilterStr(""), 0);\n'
      # marker 句柄。UnitMarker 在 natives.galaxy:4235，索引按本项目 1-based 约定。
      "    lv_m = UnitMarker(lv_u, 1);\n"
    # 前提（同 iso1）
    + case(0, "", "VikingFighter")
    # --- marker 族首测（permissive）---
    + case(1, "    AISetFilterMarker({f}, 0, 1000, lv_m);\n", "Marauder")
    + case(2, "    AISetFilterLifePerMarker({f}, 100000.0, lv_m);\n", "Reaper")
    # --- 反向对照：正常工作的过滤器**必须**把这些筛成空 ---
    # 陆战队是远程单位，要求近战 -> 应当一个不剩
    + case(3, "    AISetFilterMelee({f}, true);\n", "Hellion", want_empty=True)
    # 生命值必须落在 [100000, 200000] -> 不可能
    + case(4, "    AISetFilterLife({f}, 100000.0, 200000.0);\n",
           "SiegeTank", want_empty=True)
    # 要求能同时打到 99 个地面 + 99 个空中敌人 -> 图上根本没敌人
    + case(5, "    AISetFilterCanAttackEnemy({f}, 99, 99);\n",
           "Thor", want_empty=True)
    # 只要空中单位（陆战队是地面）-> 应当为空
    + case(6, "    AISetFilterPlane({f}, 1);\n", "Raven", want_empty=True)
    + spawn("Banshee")
    + "}\n"
)

# ---------------------------------------------------------------------------
# iso3：CanAttack* 语义定性（iso1/iso2 的直接产物，不是补测）
# ---------------------------------------------------------------------------
# iso1 拿到 CanAttackEnemy(0,0) -> 空，iso2 拿到 CanAttackEnemy(99,99) -> 非空。
# 两点连起来把我原先的假设推翻了：这两个参数**不是**「至少要能打到几个敌人」
# 的下限（那样 0 应当最宽松），而是**在描述场上敌人的构成**——
# 「有 N 个地面敌人、M 个空中敌人，把能对付它们的单位留下」。
# (0,0) = 根本没有敌人要打 -> 谁都不符合 -> 空，是**正确行为**。
#
# 所以这不是"setter 坏了"，是我给的参数语义反了。round23 那条
# 「失败标签整齐扎堆一个域，先怀疑环境/前提」在这儿的变体是：
# **先怀疑自己对参数语义的假设，别急着给引擎判死刑。**
#
# 本档用「能力不同的两种单位 × 不同的敌情参数」做交叉判别，把语义钉死：
#   陆战队 Marine  能打地面 + 能打空中
#   火蜥蛛 Hellion 只能打地面
# 若语义假设成立，则 CanAttackEnemy(0,1)（只有空中敌人）作用在 Hellion 组上
# **必须筛成空**，而作用在 Marine 组上必须非空 —— 这是一对**能互相证伪**的
# 断言，比"非空即通过"强得多。
BODY_ISO3 = (
    "void InitMap () {\n"
    "    aifilter  lv_f;\n"
    "    unitgroup lv_all;\n"
    "    unitgroup lv_hel;\n"
    "    point     lv_c;\n"
    "    int       lv_n;\n"
    + spawn("Ghost")
    + "    lv_c = RegionGetCenter(RegionPlayableMap());\n"
      '    UnitCreate(3, "Marine", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      '    UnitCreate(3, "Hellion", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      '    lv_all = UnitGroup("Marine", 1, RegionEntireMap(), UnitFilterStr(""), 0);\n'
      '    lv_hel = UnitGroup("Hellion", 1, RegionEntireMap(), UnitFilterStr(""), 0);\n'
    # 两个前提：两组各自在纯基线过滤下都非空
    + case(0, "", "VikingFighter")
    + case(0, "", "SCV", grp="lv_hel")
    # --- CanAttackEnemy 语义交叉判别 ---
    # 有地面敌人 -> 陆战队能打 -> 非空
    + case(1, "    AISetFilterCanAttackEnemy({f}, 1, 0);\n", "Marauder")
    # 有空中敌人 -> 陆战队能打 -> 非空
    + case(2, "    AISetFilterCanAttackEnemy({f}, 0, 1);\n", "Reaper")
    # 有地面敌人 -> 火蜥蛛能打 -> 非空
    + case(3, "    AISetFilterCanAttackEnemy({f}, 1, 0);\n", "Thor", grp="lv_hel")
    # 有空中敌人 -> 火蜥蛛打不到 -> **必须为空**（本档最关键的一条）
    + case(4, "    AISetFilterCanAttackEnemy({f}, 0, 1);\n", "SiegeTank",
           want_empty=True, grp="lv_hel")
    # --- CanAttackAlly 同法 ---
    + case(5, "    AISetFilterCanAttackAlly({f}, true, false);\n", "Raven")
    + case(6, "    AISetFilterCanAttackAlly({f}, false, true);\n", "Medivac")
    # 火蜥蛛打不到空中友军 -> **必须为空**
    + case(7, "    AISetFilterCanAttackAlly({f}, false, true);\n",
           "Battlecruiser", want_empty=True, grp="lv_hel")
    + spawn("Banshee")
    + "}\n"
)

# ---------------------------------------------------------------------------
# iso4：CanAttackEnemy 的 ground 分支单变量扫描（纯测量档，不是断言档）
# ---------------------------------------------------------------------------
# iso3 打出一个我解释不了的模式：陆战队**能**打地面，可 (ground=1, air=0)
# 照样把它筛空；而 (ground=0, air=1) 就能过。把历轮 Marine 组的点并起来：
#
#       (0,0) -> 空      (1,0) -> 空
#       (0,1) -> 非空    (99,99) -> 非空
#
# 四个点全都只由 **air 参数**就能解释，ground 参数看不出任何贡献。
# 但四个点里 ground 只取过 0 / 1 / 99 三个值且从没单独变化过，
# 说不出"ground 无效"还是"ground 需要更大的值"。**这是采样不足，不是结论。**
# （round23 那条「n=20 时 p95 退化成 max」的同类错误：别在样本撑不起
#   结论的时候下结论。）
#
# 本档只做一件事：**固定 Marine 源组，单变量扫 ground，另拿 air 做正对照。**
# 这里刻意全部用 permissive 形式（count>0 才 spawn），因为我要的是"测量读数"
# 而不是"通过/失败"——缺席在这一档同样是有效数据，不代表缺陷。
BODY_ISO4 = (
    "void InitMap () {\n"
    "    aifilter  lv_f;\n"
    "    unitgroup lv_all;\n"
    "    point     lv_c;\n"
    "    int       lv_n;\n"
    + spawn("Ghost")
    + "    lv_c = RegionGetCenter(RegionPlayableMap());\n"
      '    UnitCreate(3, "Marine", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      '    lv_all = UnitGroup("Marine", 1, RegionEntireMap(), UnitFilterStr(""), 0);\n'
    + case(0, "", "VikingFighter")
    # --- 单变量扫 ground（air 恒为 0）---
    + case(1, "    AISetFilterCanAttackEnemy({f}, 1, 0);\n", "Marauder")
    + case(2, "    AISetFilterCanAttackEnemy({f}, 5, 0);\n", "Reaper")
    + case(3, "    AISetFilterCanAttackEnemy({f}, 99, 0);\n", "Thor")
    # --- air 正对照：只要 air>=1 就该复现 iso3 的"非空" ---
    + case(4, "    AISetFilterCanAttackEnemy({f}, 0, 1);\n", "Battlecruiser")
    + case(5, "    AISetFilterCanAttackEnemy({f}, 0, 99);\n", "Raven")
    # --- 混合：ground 与 air 同时非零，看 ground 会不会把 air 的通过掐掉 ---
    + case(6, "    AISetFilterCanAttackEnemy({f}, 1, 1);\n", "SiegeTank")
    + spawn("Banshee")
    + "}\n"
)

TIERS = {"iso1": BODY_ISO1, "iso2": BODY_ISO2, "iso3": BODY_ISO3,
         "iso4": BODY_ISO4}

SENTINELS = {"iso1": ("Ghost", "Banshee"), "iso2": ("Ghost", "Banshee"),
             "iso3": ("Ghost", "Banshee"), "iso4": ("Ghost", "Banshee")}

# 每档的前提项：不成立时该档结论一律不作数。
PRECOND = {
    "iso1": {"VikingFighter": "仅基线 5 个 setter 的过滤器产出非空组"},
    "iso2": {"VikingFighter": "仅基线 5 个 setter 的过滤器产出非空组"},
    # iso3 有两个源组，两组都必须先在纯基线下非空，否则"筛空"无从区分
    # 「过滤器起作用」和「源组本来就空」—— 这正是 round22 那条
    # 「退化到平凡解」的对偶：平凡解也能让 restrictive 档假绿。
    "iso3": {"VikingFighter": "Marine 源组在纯基线过滤下非空",
             "SCV": "Hellion 源组在纯基线过滤下非空"},
    "iso4": {"VikingFighter": "Marine 源组在纯基线过滤下非空"},
}

# 结论项：单位 -> (被测符号, 这条结论的含义)
CLAIMS = {
    "iso1": {
        "Marauder":      ("AISetFilterSelf", "exclude=null 不误杀（permissive）"),
        "Reaper":        ("AISetFilterLifeMod", "type=0/mod=1.0 不误杀"),
        "Hellion":       ("AISetFilterCanAttackEnemy", "(0,0) 不误杀"),
        "SiegeTank":     ("AISetFilterCanAttackAlly", "(false,false) 不误杀"),
        "Thor":          ("AISetFilterBehaviorCount", '[0,1000]"Stimpack" 不误杀'),
        "Raven":         ("AISetFilterMelee", "want=false 不误杀"),
        "Battlecruiser": ("AISetFilterValidPassenger", "Medivac 载具下不误杀"),
    },
    "iso2": {
        "Marauder":  ("AISetFilterMarker", "[0,1000]+UnitMarker 不误杀"),
        "Reaper":    ("AISetFilterLifePerMarker", "each=100000 不误杀"),
        "Hellion":   ("AISetFilterMelee", "[反向] want=true 把远程兵筛空"),
        "SiegeTank": ("AISetFilterLife", "[反向] 不可能血量区间筛空"),
        "Thor":      ("AISetFilterCanAttackEnemy", "[反向] (99,99) 筛空"),
        "Raven":     ("AISetFilterPlane", "[反向] 只要空中把地面兵筛空"),
    },
    # iso3 的每一条都是"语义断言"而不是"可用性断言"：符号早在 iso1/iso2
    # 证明可调用了，这里问的是**参数到底什么意思**。
    # 关键在最后两条 want_empty —— 它们让整组断言变得可证伪：
    # 若引擎其实忽略这两个参数（原样返回源组），Marauder/Reaper/Thor/Raven/
    # Medivac 照样全绿，但 SiegeTank/Battlecruiser 一定缺席。
    "iso3": {
        "Marauder":      ("AISetFilterCanAttackEnemy",
                          "Marine 组 + (ground=1,air=0) -> 非空（能打地面）"),
        "Reaper":        ("AISetFilterCanAttackEnemy",
                          "Marine 组 + (ground=0,air=1) -> 非空（能打空中）"),
        "Thor":          ("AISetFilterCanAttackEnemy",
                          "Hellion 组 + (ground=1,air=0) -> 非空（能打地面）"),
        "SiegeTank":     ("AISetFilterCanAttackEnemy",
                          "[判决] Hellion 组 + (ground=0,air=1) -> 必须空"
                          "（火蜥蛛对空无武器）"),
        "Raven":         ("AISetFilterCanAttackAlly",
                          "Marine 组 + (ground=true,air=false) -> 非空"),
        "Medivac":       ("AISetFilterCanAttackAlly",
                          "Marine 组 + (ground=false,air=true) -> 非空"),
        "Battlecruiser": ("AISetFilterCanAttackAlly",
                          "[判决] Hellion 组 + (ground=false,air=true) -> 必须空"),
    },
    # iso4 是测量档：这里的 ✓/× 读作"非空/空"，不读作"通过/失败"。
    "iso4": {
        "Marauder":      ("AISetFilterCanAttackEnemy", "[测量] (g=1,  a=0)"),
        "Reaper":        ("AISetFilterCanAttackEnemy", "[测量] (g=5,  a=0)"),
        "Thor":          ("AISetFilterCanAttackEnemy", "[测量] (g=99, a=0)"),
        "Battlecruiser": ("AISetFilterCanAttackEnemy", "[测量] (g=0,  a=1)"),
        "Raven":         ("AISetFilterCanAttackEnemy", "[测量] (g=0,  a=99)"),
        "SiegeTank":     ("AISetFilterCanAttackEnemy", "[测量] (g=1,  a=1)"),
    },
}


def build_map(body: str) -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(SRC_MAP, BUILD)
    script = 'include "TriggerLibs/natives"\n\n' + body
    (BUILD / "MapScript.galaxy").write_text(script, encoding="utf-8")
    r = subprocess.run([sys.executable, str(PACKER), str(BUILD), str(OUT_MAP),
                        "--stormlib", str(STORMLIB)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("pack failed: " + (r.stderr or r.stdout))


def observe(want: tuple[str, ...]) -> set[str]:
    c = acquire_launched()
    md = OUT_MAP.read_bytes()
    r = c.send(sc_pb.Request(create_game=sc_pb.RequestCreateGame(
        local_map=sc_pb.LocalMap(map_data=md),
        player_setup=[sc_pb.PlayerSetup(type=1, race=1, player_name="P1")],
        realtime=True)), 240)
    if r.error:
        c.close()
        raise RuntimeError("CreateGame: " + str(list(r.error)))
    time.sleep(1)
    r = c.send(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
        race=1, options=sc_pb.InterfaceOptions(raw=True))), 120)
    if r.error:
        c.close()
        raise RuntimeError("JoinGame: " + str(list(r.error)))
    rd = c.send(sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True)), 120)
    id2name = {u.unit_id: u.name for u in rd.data.units}
    seen: set[str] = set()
    for _ in range(4):
        time.sleep(2.5)
        ro = c.send(sc_pb.Request(observation=sc_pb.RequestObservation()), 60)
        for u in ro.observation.observation.raw_data.units:
            n = id2name.get(u.unit_type, "")
            if n in MARKERS:
                seen.add(n)
        if set(want) <= seen:
            break
    try:
        c.send(sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), 20)
    except Exception:
        pass
    c.close()
    return seen


def observe_retry(want: tuple[str, ...], attempts: int = 3) -> set[str]:
    last = None
    for i in range(attempts):
        try:
            return observe(want)
        except Exception as e:
            last = e
            print(f"  (第 {i + 1}/{attempts} 次传输层失败: {e}; 重试)", flush=True)
            time.sleep(3)
    raise RuntimeError(f"探针连续 {attempts} 次传输层失败: {last}")


def classify(tier: str, seen: set[str]) -> dict:
    head, tail = SENTINELS[tier]
    if head not in seen:
        return {"verdict": "COMPILE_FAIL",
                "note": "MapScript 被引擎静默丢弃（符号/类型无法解析）",
                "claims": {}}
    if tail not in seen:
        return {"verdict": "TRAP",
                "note": "能编译，但某个调用触发 runtime error 中断了 InitMap",
                "claims": {}}
    miss_pre = [v for u, v in PRECOND[tier].items() if u not in seen]
    if miss_pre:
        return {"verdict": "PRECOND_FAIL",
                "note": "前提不成立，本档结论不作数：" + "；".join(miss_pre),
                "claims": {}}
    claims = {}
    for unit, (sym, desc) in CLAIMS[tier].items():
        claims.setdefault(sym, []).append(
            {"desc": desc, "ok": unit in seen})
    ok_all = all(c["ok"] for lst in claims.values() for c in lst)
    return {"verdict": "USABLE" if ok_all else "PARTIAL",
            "note": "全部结论命中" if ok_all else "部分结论落空（详见 claims）",
            "claims": claims}


def wait_for_free(max_minutes: int) -> bool:
    if not human_games():
        return True
    print(f"[probe25] 检测到真人对局，排队等待（最多 {max_minutes} 分钟）…",
          flush=True)
    for _ in range(max_minutes * 2):
        time.sleep(30)
        if not human_games():
            # 去抖：连续 4 次采样都空闲才算真空闲（round17 教训）
            for _ in range(3):
                time.sleep(30)
                if human_games():
                    break
            else:
                return True
    return False


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    wait_min = 0
    for a in sys.argv[1:]:
        if a.startswith("--wait"):
            wait_min = int(a.split("=", 1)[1]) if "=" in a else 60
    tiers = args or list(TIERS)

    if wait_min:
        free = wait_for_free(wait_min)
    else:
        free = not human_games()
    if not free:
        print("[probe25] 有真人对局占机，按铁律不清场，本轮放弃。")
        return 2

    results: dict[str, dict] = {}
    for t in tiers:
        print(f"\n=== [{t}] 构建并运行 ===", flush=True)
        build_map(TIERS[t])
        want = tuple(SENTINELS[t]) + tuple(CLAIMS[t])
        seen = observe_retry(want)
        res = classify(t, seen)
        res["seen"] = sorted(seen)
        results[t] = res
        print(f"  观测: {sorted(seen)}")
        print(f"  判定: {res['verdict']} —— {res['note']}")
        for sym, lst in res["claims"].items():
            for c in lst:
                print(f"    [{'✓' if c['ok'] else '×'}] {sym}: {c['desc']}")

    RESULT.write_text(json.dumps(results, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"\n[probe25] 结果已写入 {RESULT}")
    bad = [t for t, r in results.items()
           if r["verdict"] in ("COMPILE_FAIL", "TRAP", "PRECOND_FAIL")]
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
