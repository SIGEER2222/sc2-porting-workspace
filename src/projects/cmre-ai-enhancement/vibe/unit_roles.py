"""单位角色常量与辅助函数。

映射 AresSC2 UnitRole 到本项目语义，提供统一入口。
"""

from ares.consts import UnitRole


# ===== 核心角色（直接复用 Ares 定义）=====
# 经济角色
GATHERING = UnitRole.GATHERING  # 正在采矿/采气的工人
BUILDING = UnitRole.BUILDING  # 被派去建造建筑的工人
GAS_STEAL_PREVENTER = UnitRole.GAS_STEAL_PREVENTER  # 防偷气

# 战斗角色
DEFENDING = UnitRole.DEFENDING  # 基地附近防守
ATTACKING = UnitRole.ATTACKING  # 主攻击编队
ATTACKING_MAIN_SQUAD = UnitRole.ATTACKING_MAIN_SQUAD  # 主攻击小队
ATTACKING_TRANSPORT_SQUAD = UnitRole.ATTACKING_TRANSPORT_SQUAD  # 待运输攻击小队
BASE_DEFENDER = UnitRole.BASE_DEFENDER  # 扩张基地防守
BASE_BLOCKER = UnitRole.BASE_BLOCKER  # 封锁敌方基地
HARASSING = UnitRole.HARASSING  # 骚扰编队
FLANK_GROUP_ONE = UnitRole.FLANK_GROUP_ONE
FLANK_GROUP_TWO = UnitRole.FLANK_GROUP_TWO
FLANK_GROUP_THREE = UnitRole.FLANK_GROUP_THREE

# 运输/空投角色
DROP_SHIP = UnitRole.DROP_SHIP  # 运输船
DROP_UNITS_TO_LOAD = UnitRole.DROP_UNITS_TO_LOAD  # 待装载单位
DROP_UNITS_ATTACKING = UnitRole.DROP_UNITS_ATTACKING  # 已投放攻击单位

# 特殊角色
HEALING = UnitRole.HEALING  # 治疗中
BANE_FODDER = UnitRole.BANE_FODDER  # 诱饵
GATE_KEEPER = UnitRole.GATE_KEEPER  # 守门


# ===== 项目扩展角色（Dead of Night 专用）=====
class ExtendedUnitRole(str):
    """扩展角色，不在 Ares 核心枚举中。"""

    SIEGE_TANK_SIEGED = "SIEGE_TANK_SIEGED"  # 已进入围攻模式的坦克
    SIEGE_TANK_UNSIEGED = "SIEGE_TANK_UNSIEGED"  # 未围攻坦克
    MEDIVAC_HEALING = "MEDIVAC_HEALING"  # 正在治疗的医疗船
    SCOUTING = "SCOUTING"  # 侦查单位
    IDLE = "IDLE"  # 真正闲置（无命令、无角色）


# ===== 角色分组常量=====
COMBAT_ROLES = {
    DEFENDING,
    ATTACKING,
    ATTACKING_MAIN_SQUAD,
    ATTACKING_TRANSPORT_SQUAD,
    BASE_DEFENDER,
    BASE_BLOCKER,
    HARASSING,
    FLANK_GROUP_ONE,
    FLANK_GROUP_TWO,
    FLANK_GROUP_THREE,
}

ECONOMY_ROLES = {
    GATHERING,
    BUILDING,
    GAS_STEAL_PREVENTER,
}

TRANSPORT_ROLES = {
    DROP_SHIP,
    DROP_UNITS_TO_LOAD,
    DROP_UNITS_ATTACKING,
}

ALL_ARS_ROLES = (
    COMBAT_ROLES | ECONOMY_ROLES | TRANSPORT_ROLES | {HEALING, BANE_FODDER, GATE_KEEPER}
)


def is_combat_role(role: str) -> bool:
    """判断是否为战斗角色。"""
    return role in COMBAT_ROLES


def is_economy_role(role: str) -> bool:
    """判断是否为经济角色。"""
    return role in ECONOMY_ROLES


def is_transport_role(role: str) -> bool:
    """判断是否为运输相关角色。"""
    return role in TRANSPORT_ROLES


def get_default_combat_role() -> str:
    """获取默认战斗角色。"""
    return DEFENDING


def get_default_economy_role() -> str:
    """获取默认经济角色。"""
    return GATHERING
