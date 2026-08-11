"""AI 战术过滤族（aifilter 句柄）真机能力探针（round24 新增）。

## 为什么要有这个探针

`gap_scan` 历轮都显示 **ai 域覆盖率最低（88.5%）**，而未覆盖 top 里绝大多数是
战术过滤族：AIFilter(472) / AIGetFilterGroup(484) / AISetFilterAlliance(315) /
AISetFilterBits(236) / AIUnitGroupGetValidOrder(202) / AISetFilterRange(179) …

历轮（round12 起）一律"刻意不包"，写在案的理由是：

    AIFilter / AIGetFilterGroup / AISetFilterAlliance 在 Tactical/TacticalAI.galaxy，
    非 core 默认 include -> 包了有真机静默编译失败风险。

**round24 复查认为这个理由已经站不住脚**，三条反证：

1. round22/23 已确立：SC2 的 native 符号表是**引擎内建**的，`.galaxy` 里的
   `native` 声明只是编辑器/lint 元数据。判"能否调用"要查 `NativeLib.TriggerLib`
   的 `<FlagNative/>`。实测这一族全部 `flag=True`（AIFilter / AIGetFilterGroup /
   AISetFilterAlliance / AISetFilterBits / AISetFilterRange / AISetFilterPlane /
   AISetFilterLifeSortReference / AIUnitGroupGetValidOrder 均在 2527 条背书里）。
2. 更硬的一条：`aifilter` **根本不是 typedef，是引擎内建 handle 类型**。
   证据 —— `natives.galaxy` 全文 **0 个 typedef**，却在 1203/1204 行直接写
   `native void DataTableSetAIFilter (bool global, string name, aifilter val);`
   和 `native aifilter DataTableGetAIFilter (bool global, string name);`。
   也就是说默认 include 链的核心文件自己就在用这个类型 => 类型名不需要 include。
   `unitfilter` 同理（natives.galaxy:4586 `native unitfilter UnitFilter(...)`）。
3. 过滤所需常量 `c_playerGroupAlly/Enemy/Any` 也在 natives.galaxy:2824-2826。

## 但 round23 的血泪摆在这儿：可调用 != 可用

round22 判 StatEvent* 为 `USABLE`，round23 真机翻案 —— 因为那个探针**只验了
"编译通过 + 调用没中断 trigger"，从未验返回值**，而 `StatEventCreate` 在非暴雪
签名内容里恒返回 0。

所以本探针的判据必须**覆盖到"返回值可用"**这一层，否则拿到的 PASS 一文不值。
另外还得防住 round5 那类坑（`AISetUserInt` 只对已挂 AI 的玩家有效）——
`AIFilter(player)` 很可能也要求 player 有 AI，人类玩家上会拿到空句柄。

## 六档设计（两条正交轴：风险逐级解锁 × 是否自带 native 声明）

风险轴（每档只多引入一个未知量）：

    baseline  Ghost + Marine，完全不碰 aifilter
              -> 必须 PASS，否则观测链路本身坏了，其它档结论一律不作数
    decl      仅声明 `aifilter lv_f;` 局部变量，不调用任何 AI native
              -> 单独隔离"**类型名**在自制地图编译单元里是否可用"
    call*     AIFilter + 全套 AISetFilter* + AIGetFilterGroup 都调一遍，
              但不对返回值做任何判断
              -> 隔离"**函数符号**能否解析、调用会不会中断 trigger"
    value*    返回值判定（本探针的核心，round23 教训的落地）：
                Ghost      编译通过 + InitMap 被调用
                Marauder   AIFilter(1) 返回的句柄 != null   <- 句柄有效性
                Thor       AIGetFilterGroup 返回组 count > 0 <- 过滤语义真生效
                Banshee    走完全链路没被中断

声明轴（`*` = 无后缀 / `n` 后缀），这是**决策价值最高的一维**：

    call / value    只 `include "TriggerLibs/natives"`，不写 AI native 声明。
                    验证 round22/23 那条"符号表引擎内建"的假设。
    calln / valuen  在 MapScript 顶层**自带 7 条 native 声明**再调用。

2x2 结果表 -> CMLib 该怎么封装：

    call PASS, calln PASS   两条路都通，选**不带声明**（避免与宿主已 include 的
                            TacticalAI.galaxy 撞重复声明）
    call FAIL, calln PASS   必须自带声明 -> 在 cmlib_ai_h.galaxy 补 native 声明，
                            **仍然可以封装**（这正是历轮判死刑时漏掉的路径）
    call PASS, calln FAIL   引擎不许重复声明 -> 直接裸调
    两者都 FAIL             真不可用 -> 写进 gap_scan 排除表，永久闭合

`value` 档刻意先造 3 个 Marine 再过滤，这样"过滤结果非空"才有意义 ——
空地图上过滤出空组，是无法区分"过滤坏了"和"本来就没单位"的。

## 用法

    python probe_aifilter.py                 # 六档全跑
    python probe_aifilter.py baseline decl   # 只跑指定档
    python probe_aifilter.py --wait 60       # 真人局占机时排队等待
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'

REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
sys.path.insert(0, str(REPO / "reference" / "SC2-Neuro-API-Integration"))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402

LIB = REPO / "src" / "lib"
sys.path.insert(0, str(LIB))

from sc2_api_conn import acquire_launched, api_url            # noqa: E402
from sc2_proc_guard import human_games                        # noqa: E402

SRC_MAP = LIB / "_testmap_src"
BUILD = LIB / "_aifilter_build"
OUT_MAP = LIB / "probe_aifilter.SC2Map"
PACKER = REPO / "tools" / "mpq" / "scripts" / "pack_stormlib.py"
STORMLIB = REPO / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll"
RESULT = LIB / "probe_aifilter_result.json"

# 观测编码：每种单位对应一条独立结论，缺席即该结论为否。
MARKERS = ("Ghost", "Marine", "Marauder", "Thor", "Banshee", "SiegeTank")

# ---------------------------------------------------------------------------
# 各档 MapScript 主体
# ---------------------------------------------------------------------------

# native unitgroup UnitCreate (int inCount, string inUnitType, int inFlags,
#                              int inPlayer, point inPos, fixed inAngle);
_SPAWN = ('    UnitCreate({n}, "{u}", c_unitCreateIgnorePlacement, {p},\n'
          "               RegionGetCenter(RegionPlayableMap()), 270.0);\n")


def spawn(u: str, n: int = 1, p: int = 1) -> str:
    return _SPAWN.format(u=u, n=n, p=p)


# TacticalAI.galaxy 里的原始签名，逐字抄（round24 已 grep 核对）。
# 注意 AISetFilterPlane 的常量是 c_planeGround（在 GameData/Game.galaxy，
# **不在 natives.galaxy**），本探针只 include natives，所以直接用字面量 0，
# 免得把"我写错常量名"误判成"符号不可用"。
NAT_DECLS = (
    "native aifilter  AIFilter (int player);\n"
    "native void      AISetFilterAlliance (aifilter filter, int want);\n"
    "native void      AISetFilterBits (aifilter filter, unitfilter uf);\n"
    "native void      AISetFilterPlane (aifilter filter, int plane);\n"
    "native void      AISetFilterLife (aifilter filter, fixed min, fixed max);\n"
    "native void      AISetFilterInCombat (aifilter filter, bool inCombat);\n"
    "native unitgroup AIGetFilterGroup (aifilter filter, unitgroup group);\n"
    "\n"
)

BODY_BASELINE = (
    "void InitMap () {\n"
    + spawn("Ghost")
    + spawn("Marine")
    + "}\n"
)

# 只声明类型，不调用任何函数 —— 把"类型名可用性"单独拎出来测。
# 注意 Galaxy 局部变量必须置顶（G1001 铁律）。
BODY_DECL = (
    "void InitMap () {\n"
    "    aifilter   lv_f;\n"
    "    unitfilter lv_uf;\n"
    + spawn("Ghost")
    + spawn("Marine")
    + "}\n"
)

# 全链路调用但不判返回值。刻意把 Set 系列都用一遍——万一是某个具体
# setter 才炸，只测 AIFilter 会漏判成"可用"。
BODY_CALL = (
    "void InitMap () {\n"
    "    aifilter  lv_f;\n"
    "    unitgroup lv_all;\n"
    "    unitgroup lv_out;\n"
    + spawn("Ghost")
    + "    lv_all = UnitGroupEmpty();\n"
      "    lv_f = AIFilter(1);\n"
      "    AISetFilterAlliance(lv_f, c_playerGroupAny);\n"
      '    AISetFilterBits(lv_f, UnitFilterStr(""));\n'
      "    AISetFilterPlane(lv_f, 0);\n"
      "    AISetFilterLife(lv_f, 0.0, 100000.0);\n"
      "    AISetFilterInCombat(lv_f, false);\n"
      "    lv_out = AIGetFilterGroup(lv_f, lv_all);\n"
    + spawn("Marine")
    + "}\n"
)

# 核心档：把每一层结论各绑一个可观测单位。
BODY_VALUE = (
    "void InitMap () {\n"
    "    aifilter  lv_f;\n"
    "    unitgroup lv_all;\n"
    "    unitgroup lv_out;\n"
    "    point     lv_c;\n"
    "    int       lv_n;\n"
    + spawn("Ghost")
    + "    lv_c = RegionGetCenter(RegionPlayableMap());\n"
      # 先铺 3 个自己的 Marine，让"过滤出非空组"这件事有意义
      '    UnitCreate(3, "Marine", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      '    lv_all = UnitGroup(null, c_playerAny, RegionEntireMap(), UnitFilterStr(""), 0);\n'
      "    lv_f = AIFilter(1);\n"
      # 结论 1：句柄有效性（round23 教训的正面落地 —— 验返回值而非"没崩"）
      "    if (lv_f != null) {\n"
    + "    " + spawn("Marauder").lstrip()
    + "    }\n"
      "    AISetFilterAlliance(lv_f, c_playerGroupAny);\n"
      "    lv_out = AIGetFilterGroup(lv_f, lv_all);\n"
      "    lv_n = UnitGroupCount(lv_out, c_unitCountAll);\n"
      # 结论 2：过滤语义真的产出了东西
      "    if (lv_n > 0) {\n"
    + "    " + spawn("Thor").lstrip()
    + "    }\n"
      # 结论 3：全链路没被运行时错误中断
    + spawn("Banshee")
    + "}\n"
)

# 同族但**不吃 aifilter 句柄**的 4 个组过滤 native（TacticalAI.galaxy:112-115）。
# 单独一档，因为它们的失败模式和句柄族不同：句柄族可能"句柄恒空"，
# 这几个只可能"返回空组"。同样只认返回值，不认"没崩"。
BODY_GROUP = (
    "void InitMap () {\n"
    "    unitgroup lv_all;\n"
    "    unitgroup lv_prod;\n"
    "    unitgroup lv_cast;\n"
    "    unitgroup lv_path;\n"
    "    unitgroup lv_gath;\n"
    "    point     lv_c;\n"
    + spawn("Ghost")
    + "    lv_c = RegionGetCenter(RegionPlayableMap());\n"
      '    UnitCreate(3, "Marine", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      # Barracks 是生产建筑，专门喂给 AIFilterProduction，否则它返回空组
      # 我无法区分"函数坏了"和"本来就没生产建筑"
      '    UnitCreate(1, "Barracks", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      '    lv_all = UnitGroup(null, c_playerAny, RegionEntireMap(), UnitFilterStr(""), 0);\n'
      "    lv_prod = AIFilterProduction(lv_all, false);\n"
      "    lv_cast = AIFilterCasters(lv_all);\n"
      "    lv_path = AIFilterPathable(lv_all, lv_c);\n"
      "    lv_gath = AIFilterGathering(lv_all, 0, 100.0);\n"
      "    if (UnitGroupCount(lv_prod, c_unitCountAll) > 0) {\n"
    + "    " + spawn("Marauder").lstrip()
    + "    }\n"
      "    if (UnitGroupCount(lv_path, c_unitCountAll) > 0) {\n"
    + "    " + spawn("Thor").lstrip()
    + "    }\n"
    # Casters / Gathering 在这张空图上本来就该是空组，所以**不作正向断言** ——
    # 断言一个当前环境观测不到的东西，是 round23 明确记过的错误。
    # 它们只贡献"调用不中断"这一条（由 tail 哨兵 Banshee 承担）。
    + spawn("Banshee")
    + "}\n"
)

# AIUnitGroupGetValidOrder：引用 202 次，返回 order 句柄。
BODY_ORDER = (
    "void InitMap () {\n"
    "    unitgroup lv_all;\n"
    "    unit      lv_u;\n"
    "    order     lv_o;\n"
    "    order     lv_r;\n"
    "    point     lv_c;\n"
    + spawn("Ghost")
    + "    lv_c = RegionGetCenter(RegionPlayableMap());\n"
      '    UnitCreate(3, "Marine", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      "    lv_u = UnitLastCreated();\n"
      '    lv_all = UnitGroup("Marine", 1, RegionEntireMap(), UnitFilterStr(""), 0);\n'
      '    lv_o = OrderTargetingPoint(AbilityCommand("move", 0), lv_c);\n'
      "    lv_r = AIUnitGroupGetValidOrder(lv_all, lv_o, lv_u, true);\n"
      "    if (lv_r != null) {\n"
    + "    " + spawn("Marauder").lstrip()
    + "    }\n"
    + spawn("Banshee")
    + "}\n"
)

# 全 setter 覆盖档。
#
# value 档只验了 6 个 setter，按"判据必须覆盖结论"的纪律，那就只能对这 6 个
# 下结论。本档把 TacticalAI.galaxy 里其余 setter 一次性全调，收口整族。
#
# 关键设计：**每个参数都取"不排除任何东西"的最宽松值**。否则 Thor 缺席时
# 无法区分"这个 setter 坏了"和"我把过滤条件写太严、本来就该是空组"——
# 又是一次判据覆盖不到结论。所有条件对 Marine 都应放行，Thor 必须出现。
#
# 排除 AISetFilterMarker / AISetFilterLifePerMarker：它们要 `marker` 句柄，
# 构造成本高，本轮不封装（记为下轮 TODO，不假装验过）。
BODY_CALLALL = (
    "void InitMap () {\n"
    "    aifilter  lv_f;\n"
    "    unitgroup lv_all;\n"
    "    unitgroup lv_out;\n"
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
      "    lv_f = AIFilter(1);\n"
      "    AISetFilterAlliance(lv_f, c_playerGroupAny);\n"
      "    AISetFilterSelf(lv_f, null);\n"
      '    AISetFilterBits(lv_f, UnitFilterStr(""));\n'
      "    AISetFilterRange(lv_f, lv_u, 100000.0);\n"
      "    AISetFilterInCombat(lv_f, false);\n"
      "    AISetFilterLife(lv_f, 0.0, 100000.0);\n"
      "    AISetFilterLifeLost(lv_f, 0.0, 100000.0);\n"
      "    AISetFilterLifePercent(lv_f, 0.0, 100.0);\n"
      "    AISetFilterLifeSortReference(lv_f, 0.0, 0.0);\n"
      "    AISetFilterLifeMod(lv_f, 0, 0.0);\n"
      "    AISetFilterShields(lv_f, 0.0, 100000.0);\n"
      "    AISetFilterPlane(lv_f, 0);\n"
      "    AISetFilterCanAttackEnemy(lv_f, 0, 0);\n"
      "    AISetFilterCanAttackAlly(lv_f, false, false);\n"
      '    AISetFilterBehaviorCount(lv_f, 0, 1000, "Stimpack");\n'
      "    AISetFilterMelee(lv_f, false);\n"
      "    AISetFilterValidPassenger(lv_f, lv_med);\n"
      "    lv_out = AIGetFilterGroup(lv_f, lv_all);\n"
      "    lv_n = UnitGroupCount(lv_out, c_unitCountAll);\n"
      "    if (lv_n > 0) {\n"
    + "    " + spawn("Thor").lstrip()
    + "    }\n"
    + spawn("Banshee")
    + "}\n"
)

# callall 拿到 NULL_RETURN（Thor 缺席但 Banshee 在 = 没崩，是被过滤空了）之后的
# 二分档。把 17 个 setter 按"语义确定性"分成两半，先测确定性高的数值型：
#
#   本档收（纯数值区间，语义就是"落在 [min,max] 内的放行"）：
#       Range / LifeLost / LifePercent / LifeSortReference / Shields
#   本档不收（语义型，最可疑，留给下轮继续二分）：
#       Self(null 入参) / LifeMod(type 语义不明) / CanAttackEnemy /
#       CanAttackAlly / BehaviorCount(catalog link 可能无效) / ValidPassenger
BODY_CALLMID = (
    "void InitMap () {\n"
    "    aifilter  lv_f;\n"
    "    unitgroup lv_all;\n"
    "    unitgroup lv_out;\n"
    "    unit      lv_u;\n"
    "    point     lv_c;\n"
    "    int       lv_n;\n"
    + spawn("Ghost")
    + "    lv_c = RegionGetCenter(RegionPlayableMap());\n"
      '    UnitCreate(3, "Marine", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      "    lv_u = UnitLastCreated();\n"
      '    lv_all = UnitGroup("Marine", 1, RegionEntireMap(), UnitFilterStr(""), 0);\n'
      "    lv_f = AIFilter(1);\n"
      # 已验的 6 个打底
      "    AISetFilterAlliance(lv_f, c_playerGroupAny);\n"
      '    AISetFilterBits(lv_f, UnitFilterStr(""));\n'
      "    AISetFilterPlane(lv_f, 0);\n"
      "    AISetFilterLife(lv_f, 0.0, 100000.0);\n"
      "    AISetFilterInCombat(lv_f, false);\n"
      # 本档新增的 5 个数值型
      "    AISetFilterRange(lv_f, lv_u, 100000.0);\n"
      "    AISetFilterLifeLost(lv_f, 0.0, 100000.0);\n"
      "    AISetFilterLifePercent(lv_f, 0.0, 100.0);\n"
      "    AISetFilterLifeSortReference(lv_f, 0.0, 0.0);\n"
      "    AISetFilterShields(lv_f, 0.0, 100000.0);\n"
      "    lv_out = AIGetFilterGroup(lv_f, lv_all);\n"
      "    lv_n = UnitGroupCount(lv_out, c_unitCountAll);\n"
      "    if (lv_n > 0) {\n"
    + "    " + spawn("Thor").lstrip()
    + "    }\n"
    + spawn("Banshee")
    + "}\n"
)

# order 档拿到 NULL_RETURN 之后的追加自查档。
#
# 「返回 null」有两种完全不同的成因，混在一起就等于没测：
#   (a) AIUnitGroupGetValidOrder 本身在自制内容里不可用     <- 真结论
#   (b) 我喂进去的 order / unitgroup 本来就是空的            <- 我的测试写错了
# 所以把两个**前提**也各绑一个观测单位，前提不成立时结论一律不作数。
# round23 记的是"判据要覆盖结论"，这里是它的镜像：别把自己的构造错误
# 记到被测对象头上。
BODY_ORDER2 = (
    "void InitMap () {\n"
    "    unitgroup lv_all;\n"
    "    unit      lv_u;\n"
    "    order     lv_o;\n"
    "    order     lv_r;\n"
    "    point     lv_c;\n"
    "    int       lv_n;\n"
    + spawn("Ghost")
    + "    lv_c = RegionGetCenter(RegionPlayableMap());\n"
      '    UnitCreate(3, "Marine", c_unitCreateIgnorePlacement, 1, lv_c, 270.0);\n'
      "    lv_u = UnitLastCreated();\n"
      '    lv_all = UnitGroup("Marine", 1, RegionEntireMap(), UnitFilterStr(""), 0);\n'
      "    lv_n = UnitGroupCount(lv_all, c_unitCountAll);\n"
      # 前提 1：输入组真的非空
      "    if (lv_n > 0) {\n"
    + "    " + spawn("Marauder").lstrip()
    + "    }\n"
      '    lv_o = OrderTargetingPoint(AbilityCommand("move", 0), lv_c);\n'
      # 前提 2：order 真的构造出来了
      "    if (lv_o != null) {\n"
    + "    " + spawn("Thor").lstrip()
    + "    }\n"
      "    lv_r = AIUnitGroupGetValidOrder(lv_all, lv_o, lv_u, true);\n"
      # 结论
      "    if (lv_r != null) {\n"
    + "    " + spawn("SiegeTank").lstrip()
    + "    }\n"
    + spawn("Banshee")
    + "}\n"
)

TIERS = {
    "baseline": (BODY_BASELINE, False),
    "decl":     (BODY_DECL,     False),
    "call":     (BODY_CALL,     False),
    "calln":    (BODY_CALL,     True),
    "value":    (BODY_VALUE,    False),
    "valuen":   (BODY_VALUE,    True),
    "callall":  (BODY_CALLALL,  False),
    "callmid":  (BODY_CALLMID,  False),
    "group":    (BODY_GROUP,    False),
    "order":    (BODY_ORDER,    False),
    "order2":   (BODY_ORDER2,   False),
}

# 每档"编译通过就该出现"的哨兵单位（head），以及"跑完全程"的尾哨兵（tail）
SENTINELS = {
    "baseline": ("Ghost", "Marine"),
    "decl":     ("Ghost", "Marine"),
    "call":     ("Ghost", "Marine"),
    "calln":    ("Ghost", "Marine"),
    "value":    ("Ghost", "Banshee"),
    "valuen":   ("Ghost", "Banshee"),
    "callall":  ("Ghost", "Banshee"),
    "callmid":  ("Ghost", "Banshee"),
    "group":    ("Ghost", "Banshee"),
    "order":    ("Ghost", "Banshee"),
    "order2":   ("Ghost", "Banshee"),
}

# order2 档的前提项：这些不成立时，该档的结论一律不作数。
PRECONDS = {
    "order2": {"Marauder": "输入 unitgroup 非空",
               "Thor": "OrderTargetingPoint 构造出非 null order"},
}

# 返回值断言：单位 -> 它代表的那条结论。缺席即该条结论为否。
EXTRA = {
    "value":  {"Marauder": "AIFilter 返回句柄非 null",
               "Thor": "AIGetFilterGroup 产出非空组"},
    "valuen": {"Marauder": "AIFilter 返回句柄非 null",
               "Thor": "AIGetFilterGroup 产出非空组"},
    "callall": {"Thor": "17 个 setter 全调完 AIGetFilterGroup 仍产出非空组"},
    "callmid": {"Thor": "已验 6 个 + 5 个数值型 setter 后仍产出非空组"},
    "group":  {"Marauder": "AIFilterProduction 产出非空组",
               "Thor": "AIFilterPathable 产出非空组"},
    "order":  {"Marauder": "AIUnitGroupGetValidOrder 返回非 null order"},
    "order2": {"Marauder": "输入 unitgroup 非空（前提）",
               "Thor": "order 构造成功（前提）",
               "SiegeTank": "AIUnitGroupGetValidOrder 返回非 null order"},
}

ALL_TIERS = ["baseline", "decl", "call", "calln", "value", "valuen",
             "group", "order2"]


def build_map(body: str, with_decls: bool) -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(SRC_MAP, BUILD)
    script = 'include "TriggerLibs/natives"\n\n'
    if with_decls:
        script += NAT_DECLS
    script += body
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
    """SC2 连续 create/leave 十几轮后会自崩，那是环境噪声不是结论。"""
    last = None
    for i in range(attempts):
        try:
            return observe(want)
        except Exception as e:
            last = e
            print(f"  (attempt {i + 1}/{attempts} 传输层失败: {e}; 重试)", flush=True)
            time.sleep(3)
    raise RuntimeError(f"探针连续 {attempts} 次传输层失败: {last}")


def classify(tier: str, seen: set[str]) -> tuple[str, str]:
    head, tail = SENTINELS[tier]
    if head not in seen:
        return "COMPILE_FAIL", "MapScript 被引擎静默丢弃（符号/类型无法解析）"
    if tail not in seen:
        return "TRAP", "能编译，但调用触发 runtime error，中断了 InitMap 后续语句"
    if tier not in EXTRA:
        return "PASS", "编译通过 + 调用未中断 trigger"

    if tier in ("value", "valuen"):
        handle = "Marauder" in seen
        group = "Thor" in seen
        if handle and group:
            return "USABLE", "句柄有效 + 过滤语义产出非空组"
        if handle and not group:
            return "HANDLE_ONLY", "句柄非 null，但 AIGetFilterGroup 返回空组"
        if not handle and not group:
            return "NULL_HANDLE", "AIFilter 返回空句柄（可调用不可用，StatEvent 同款）"
        return "WEIRD", "过滤有产出但句柄判空 —— 逻辑矛盾，结论不作数"

    # group / order：通用返回值断言。
    # 前提必须先于结论判定 —— 前提塌了还去读结论，读到的是自己的 bug
    # 不是被测对象的性质（round22 判定链顺序铁律的同一条）。
    pre = PRECONDS.get(tier, {})
    bad = [v for u, v in pre.items() if u not in seen]
    if bad:
        return "PRECOND_FAIL", "前提不成立，本档结论不作数：" + "；".join(bad)
    want = {u: v for u, v in EXTRA[tier].items() if u not in pre}
    hit = [u for u in want if u in seen]
    miss = [u for u in want if u not in seen]
    if not miss:
        return "USABLE", "全部返回值断言命中：" + "；".join(want.values())
    if not hit:
        return "NULL_RETURN", "全部返回值断言落空：" + "；".join(want.values())
    return "PARTIAL", ("命中 " + "；".join(want[u] for u in hit)
                       + " / 落空 " + "；".join(want[u] for u in miss))


def wait_for_free(max_minutes: int) -> bool:
    """真人局占机时排队等待。铁律：有真人对局绝不清场。"""
    if not human_games():
        return True
    if max_minutes <= 0:
        return False
    deadline = time.time() + max_minutes * 60
    print(f"[probe] 检测到真人局，按铁律不清场，排队等待（最多 {max_minutes} 分钟）…",
          flush=True)
    while time.time() < deadline:
        time.sleep(30)
        if not human_games():
            print("[probe] 真人局已结束，开跑。", flush=True)
            time.sleep(5)
            return True
    return False


def decide(results: dict[str, dict]) -> tuple[str, list[str]]:
    """把六档明细收敛成一条可执行结论。

    判定链顺序是有讲究的（round22 血泪）：最根本的失败信号必须排在最前，
    任何次级判据都不许插到它前面。这里 baseline 就是那个 sentinel。
    """
    log: list[str] = []
    g = lambda t: results.get(t, {}).get("verdict")  # noqa: E731

    if "baseline" in results and g("baseline") != "PASS":
        log.append("基线未 PASS —— 观测链路本身有问题，其它档位结论一律不作数。")
        return "INVALID", log

    # 附属族结论（group / order*）独立于主结论，先报，避免只跑子集时丢信息。
    for t, label in (("group", "无句柄组过滤族 AIFilterProduction/Casters/"
                               "Pathable/Gathering"),
                     ("order", "AIUnitGroupGetValidOrder"),
                     ("order2", "AIUnitGroupGetValidOrder（含前提自查）")):
        r = g(t)
        if r is None:
            continue
        if r == "USABLE":
            log.append(f"[附属] {label}：返回值断言全中 -> 可封装。")
        elif r == "PARTIAL":
            log.append(f"[附属] {label}：{results[t]['why']} -> 只封装命中的部分。")
        elif r == "PRECOND_FAIL":
            log.append(f"[附属] {label}：{results[t]['why']}")
        else:
            log.append(f"[附属] {label}：{r} -> 不封装。")

    # 只跑了子集时，主结论必须显式弃权。
    # round22 血泪的同一条：汇总措辞要按**实跑档数**分支，绝不能把"没跑"
    # 说成"没过"——那是在悄悄拆掉判假阳性的防线。
    if g("call") is None and g("calln") is None:
        log.append("本次未跑 call/calln 档 —— aifilter 句柄族主结论本轮弃权，"
                   "沿用上一次完整跑的结论。")
        return "SUBSET_ONLY", log

    if g("decl") == "COMPILE_FAIL":
        log.append("`aifilter` 类型名在自制地图编译单元不可用 —— 维持不封装，")
        log.append("并把该结论写进 gap_scan 排除表，永久闭合。")
        return "TYPE_UNAVAILABLE", log

    plain, natd = g("call"), g("calln")
    ok_plain, ok_natd = plain == "PASS", natd == "PASS"

    if plain == "COMPILE_FAIL" and natd == "COMPILE_FAIL":
        log.append("裸调与自带 native 声明两条路都编译失败 —— 符号真的不可解析。")
        log.append("=> 维持不封装，写进 gap_scan 排除表，永久闭合。")
        return "SYMBOL_UNAVAILABLE", log
    if plain == "TRAP" or natd == "TRAP":
        log.append("能编译但调用中断 trigger（runtime error）—— 维持不封装。")
        return "UNUSABLE_RUNTIME", log

    # 选一条能编译的路，优先裸调（不与宿主 TacticalAI 撞重复声明）
    if ok_plain:
        style, vt = "plain", "value"
        log.append("链接方式：**裸调可行**（引擎内建符号表假设成立），"
                   "封装时不要自带 native 声明，避免与宿主 TacticalAI 冲突。")
    elif ok_natd:
        style, vt = "natdecl", "valuen"
        log.append("链接方式：裸调不行，但**自带 native 声明后可行** —— "
                   "历轮判死刑时漏掉的正是这条路。封装需在 cmlib_ai_h 补声明。")
    else:
        log.append("call/calln 都没能 PASS，看分档明细。")
        return "INCONCLUSIVE", log

    v = g(vt)
    if v == "USABLE":
        log.append(f"AI 战术过滤族真机可用（句柄有效 + 过滤产出非空，{style} 链接）。")
        log.append("=> 撤销历轮'范围外不封装'判定，纳入 cmlib_ai。")
        return "USABLE", log
    if v == "NULL_HANDLE":
        log.append("AIFilter 返回空句柄 —— 与 StatEvent 同款'可调用不可用'。")
        log.append("很可能要求 player 已挂 AI（参照 AISetUserInt 的已知约束）。")
        return "CALLABLE_NOT_USABLE", log
    if v == "HANDLE_ONLY":
        log.append("句柄有效但过滤返回空组 —— 需进一步区分是过滤条件还是环境。")
        return "PARTIAL", log
    if v == "COMPILE_FAIL":
        log.append(f"{vt} 档编译失败而 {vt.replace('value', 'call')} 档能过 —— "
                   "问题出在 `lv_f != null` 比较或 AIGetFilterGroup 赋值上。")
        return "INCONCLUSIVE", log
    log.append("结论不明确，看上面分档明细。")
    return "INCONCLUSIVE", log


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tiers", nargs="*", default=None)
    ap.add_argument("--wait", type=int, default=0)
    args = ap.parse_args()

    order = args.tiers or ALL_TIERS
    for t in order:
        if t not in TIERS:
            print(f"未知档位: {t}（可选 {list(TIERS)}）")
            return 2

    if not wait_for_free(args.wait):
        print(f"[probe] SC2 被真人局占用 {human_games()}，按铁律不清场，退出。")
        return 3

    print(f"[probe] SC2 API = {api_url()}", flush=True)
    results: dict[str, dict] = {}
    for t in order:
        body, with_decls = TIERS[t]
        print(f"\n[probe] ==== 档位 {t} "
              f"({'自带 native 声明' if with_decls else '裸调'}) ====", flush=True)
        build_map(body, with_decls)
        want = tuple(SENTINELS[t]) + tuple(EXTRA.get(t, {}))
        seen = observe_retry(want)
        verdict, why = classify(t, seen)
        print(f"[probe] {t:9s} -> {verdict:12s} {why}")
        print(f"[probe]   观测到: {sorted(seen)}")
        results[t] = {"verdict": verdict, "why": why, "units": sorted(seen),
                      "native_decls": with_decls}

    print("\n[probe] ==== 结论 ====")
    verdict, log = decide(results)
    for line in log:
        print("[probe] " + line)
    print(f"[probe] VERDICT = {verdict}")

    payload = {"ts": time.strftime("%Y-%m-%d %H:%M:%S"),
               "verdict": verdict, "notes": log, "tiers": results}
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"[probe] 结果已写入 {RESULT}")
    return 0 if verdict not in ("INVALID", "INCONCLUSIVE", "WEIRD") else 1


if __name__ == "__main__":
    sys.exit(main())
