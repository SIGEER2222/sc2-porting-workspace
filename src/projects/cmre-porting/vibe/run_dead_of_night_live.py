"""亡者之夜 AI 盟友真机自主对局 runner。

与 run_dead_of_night.py（基于 SimulatorSession 本地模拟器）不同，本模块连接
真实 SC2 进程，通过 SC2 API 完成 CreateGame → JoinGame → Observation → 决策
→ Action 闭环。

设计原则：
- 复用 DefendBasePolicy（run_dead_of_night.py 的玩家 AI 策略）
- 不依赖 SimulatorSession / sc2_simulator
- 真机亡者之夜地图的波次/单位由 galaxy 脚本驱动，本 runner 只负责：
  1. Observation → 转成 vibe Observation 格式
  2. DefendBasePolicy.decide() → 决策
  3. DefendAction → SC2 action_raw_unit_command
  4. Step 推进游戏

用法：
    # 先启动 SC2（已验证可用）：
    #   powershell -File tools/galaxy-vibe/launch-galaxy-vibe.ps1 -Map "亡者之夜_p0_default_packed.SC2Map" -Port 5000 -ModPath ""
    # 再运行本 runner：
    python -m vibe.run_dead_of_night_live --port 5000 --max-loops 2000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 添加 vendored s2clientprotocol 到 sys.path
REPO_ROOT = Path(__file__).resolve().parents[4]
NEURO = REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"
sys.path.insert(0, str(NEURO))

import aiohttp
from s2clientprotocol import sc2api_pb2 as sc_pb
from s2clientprotocol import raw_pb2 as raw_pb
from s2clientprotocol import debug_pb2 as debug_pb
from s2clientprotocol import error_pb2  # ActionResult 定义在此（Success=1, NotSupported=2, Error=3）

# 复用 galaxy_repl 的 UNIT_MAP 构建（name <-> int 双向映射）
_GALAXY_REPL = REPO_ROOT / "tools" / "galaxy-vibe"
sys.path.insert(0, str(_GALAXY_REPL))
try:
    from galaxy_repl import _build_unit_map  # type: ignore
    UNIT_MAP: dict[str, int] = _build_unit_map()
    NAME_TO_INT = UNIT_MAP  # name -> int
    INT_TO_NAME: dict[int, str] = {v: k for k, v in UNIT_MAP.items()}
except Exception:
    UNIT_MAP = {}
    NAME_TO_INT = {}
    INT_TO_NAME = {}

# 复用 DefendBasePolicy（从 defend_policy.py 正式导入，非 exec hack）
# defend_policy.py 只依赖 dataclass/math/typing，不依赖 simulator_session，
# 因此真机 runner 可直接 import 而不会触发模拟器依赖链。
try:
    from .defend_policy import DefendAction, DefendBasePolicy
    from .strategy_audit import audit_native_strategy
except ImportError:
    # Support the documented direct-script invocation as well as package imports.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from defend_policy import DefendAction, DefendBasePolicy  # type: ignore
    from strategy_audit import audit_native_strategy  # type: ignore

# 默认地图（已验证可加载，3MB 打包版）
DEFAULT_MAP = r"E:\SC2\SC2new\StarCraft II\Maps\亡者之夜_p0_default_packed.SC2Map"
P1_PLAYER_ID = 1
P2_PLAYER_ID = 2
PLAYER_ID = P1_PLAYER_ID


# ---------------------------------------------------------------------------
# SC2 API 通信层
# ---------------------------------------------------------------------------

class Sc2Connection:
    """SC2 API WebSocket 连接管理器。

    解决 aiohttp WS 在 SC2 CreateGame/JoinGame 后频繁关闭的问题：
    - 递增 id（参考 Sc2Connection.cs，避免 id 冲突）
    - 自动重连（收到 CLOSE/CLOSED 后关闭旧连接，建立新连接，重发请求）
    - 跳过 id=0 异步通知（Realtime=false 时仍可能出现）
    """

    def __init__(self, port: int):
        self.port = port
        self._next_id = 1
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None

    async def connect(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = aiohttp.ClientSession()
        self._ws = await self._session.ws_connect(
            f"ws://127.0.0.1:{self.port}/sc2api",
            max_msg_size=0,
            timeout=30,
            autoclose=False,
            autoping=False,
        )

    async def close(self) -> None:
        if self._ws is not None and not self._ws.closed:
            try:
                await self._ws.close()
            except Exception:
                pass
        if self._session is not None and not self._session.closed:
            try:
                await self._session.close()
            except Exception:
                pass

    async def _reconnect(self) -> None:
        """关闭旧连接并建立新连接。"""
        await self.close()
        await asyncio.sleep(2)
        await self.connect()

    async def send_request(self, req: sc_pb.Request, timeout: float = 30.0,
                           max_retries: int = 3) -> sc_pb.Response:
        """发送请求并等待匹配响应。WS 关闭时自动重连重试。"""
        last_exc: Optional[Exception] = None
        for attempt in range(max_retries):
            req.id = self._next_id
            self._next_id += 1
            try:
                if self._ws is None or self._ws.closed:
                    await self._reconnect()
                await self._ws.send_bytes(req.SerializeToString())
                deadline = time.time() + timeout
                while time.time() < deadline:
                    msg = await asyncio.wait_for(self._ws.receive(), timeout=timeout)
                    if msg.type == aiohttp.WSMsgType.BINARY:
                        resp = sc_pb.Response()
                        resp.ParseFromString(msg.data)
                        if not resp.HasField("id") or resp.id == req.id:
                            return resp
                        # 跳过 id=0 异步通知
                    elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED,
                                       aiohttp.WSMsgType.ERROR):
                        raise ConnectionError(
                            f"WS closed by SC2 (type={msg.type}, "
                            f"code={getattr(msg, 'data', '?')})"
                        )
                raise TimeoutError(
                    f"timeout waiting for response to {req.WhichOneof('request')}"
                )
            except (ConnectionError, asyncio.TimeoutError) as e:
                last_exc = e
                # WS 关闭，重连后重试（用新 id）
                await asyncio.sleep(1)
                continue
        raise last_exc if last_exc else RuntimeError("send_request failed")


async def connect_ws(port: int):
    """兼容旧接口：返回 (session, ws) 元组。新代码应直接用 Sc2Connection。"""
    session = aiohttp.ClientSession()
    ws = await session.ws_connect(
        f"ws://127.0.0.1:{port}/sc2api",
        max_msg_size=0,
        timeout=30,
        autoclose=False,
        autoping=False,
    )
    return session, ws


async def send_request(ws, req: sc_pb.Request, timeout: float = 30.0) -> sc_pb.Response:
    """兼容旧接口：独立的 send_request 函数。新代码应直接用 Sc2Connection.send_request。"""
    req.id = 1
    await ws.send_bytes(req.SerializeToString())
    deadline = time.time() + timeout
    while time.time() < deadline:
        msg = await asyncio.wait_for(ws.receive(), timeout=timeout)
        if msg.type == aiohttp.WSMsgType.BINARY:
            resp = sc_pb.Response()
            resp.ParseFromString(msg.data)
            if not resp.HasField("id") or resp.id == req.id:
                return resp
            # 跳过 id=0 的异步通知
        elif msg.type in (aiohttp.WSMsgType.CLOSE, aiohttp.WSMsgType.CLOSED):
            raise ConnectionError("WebSocket closed by SC2")
    raise TimeoutError(f"timeout waiting for response to {req.WhichOneof('request')}")


# ---------------------------------------------------------------------------
# Observation 转换层：SC2 API → vibe Observation
# ---------------------------------------------------------------------------

@dataclass
class LiveObservation:
    """vibe 兼容的 Observation（从 SC2 API 构造）。"""
    loop: int
    player_id: int
    own_units: list[dict]
    visible_enemies: list[dict]
    resources: dict
    mission: dict
    visible_allies: list[dict] = field(default_factory=list)
    alliance_summary: list[dict] = field(default_factory=list)
    mineral_fields: list[dict] = field(default_factory=list)  # 中立矿物单位（owner=0）


def _unit_brief_from_sc2(u, player_id: int) -> Optional[dict]:
    """把 SC2 API 的 Unit 转成 vibe _entity_brief 格式。

    返回 None 表示该单位应被跳过（如中立非战斗单位）。
    """
    unit_type_int = u.unit_type
    unit_type_name = _LIVE_UNIT_TYPE_ALIASES_BY_ID.get(
        unit_type_int,
        _canonical_live_unit_name(INT_TO_NAME.get(unit_type_int, str(unit_type_int))),
    )
    if unit_type_name == "ACHeroSpawnPlacement":
        return None
    # SC2 的 pos 是 {x, y, z}，世界单位 float
    x = u.pos.x if u.HasField("pos") else 0.0
    y = u.pos.y if u.HasField("pos") else 0.0
    return {
        "entity_id": u.tag,  # SC2 用 tag 作为单位唯一标识
        "unit_type_int": unit_type_int,
        "unit_type_id": unit_type_name,
        "owner": u.owner,
        "alliance": int(u.alliance),
        "x": x,
        "y": y,
        "health": int(u.health * 1024) if u.health else 0,  # vibe 用 raw int（×1024）
        "shields": int(u.shield * 1024) if u.shield else 0,
        "energy": int(u.energy * 1024) if u.energy else 0,
        "state": "",
        "max_health": int(u.health_max * 1024) if u.health_max else 0,
        "orders": [
            {
                "ability_id": int(order.ability_id),
                "progress": float(order.progress),
            }
            for order in getattr(u, "orders", ())
        ],
        "is_idle": not bool(getattr(u, "orders", ())),
    }


# The live API exposes catalog names in the enum spelling (for example
# MARINE), while project policies use the map-extractor spelling (Marine).
_LIVE_UNIT_NAME_ALIASES = {
    "COMMANDCENTER": "CommandCenter",
    "SUPPLYDEPOT": "SupplyDepot",
    "REFINERY": "Refinery",
    "BARRACKS": "Barracks",
    "ENGINEERINGBAY": "EngineeringBay",
    "MISSILETURRET": "MissileTurret",
    "BUNKER": "Bunker",
    "FACTORY": "Factory",
    "STARPORT": "Starport",
    "SCV": "SCV",
    "MARINE": "Marine",
    "MARAUDER": "Marauder",
    "HELLION": "Hellion",
    "SIEGETANK": "SiegeTank",
    "MEDIVAC": "Medivac",
    "VIKINGFIGHTER": "Viking",
    "VIKING": "Viking",
    "BANSHEE": "Banshee",
    "RAVEN": "Raven",
    "THOR": "Thor",
    "MINERALFIELD": "MineralField",
    "ACHEROSPAWNPLACEMENT": "ACHeroSpawnPlacement",
}

_LIVE_UNIT_TYPE_ALIASES_BY_ID = {
    # CMRE catalog object; python-sc2 only knows the Blizzard catalog IDs.
    4051: "ACHeroSpawnPlacement",
    # Empire runtime catalog objects verified through RequestData:
    # 3diguolaogong is the worker and 3diguoqianshaojidi is the town hall.
    4382: "SCV",
    4390: "CommandCenter",
    # Mission caster present in the native P1 opening; it has no weapon and
    # must remain visible as a non-combat unit rather than a fake attacker.
    4028: "CoopCasterRaynor",
}


def _canonical_live_unit_name(name: str) -> str:
    """Map SC2 enum names to the canonical names consumed by vibe policies."""
    return _LIVE_UNIT_NAME_ALIASES.get(name.upper(), name)


def build_observation(resp: sc_pb.Response, player_id: int) -> LiveObservation:
    """从 SC2 Observation 响应构造 vibe Observation。"""
    obs = resp.observation.observation
    game_loop = obs.game_loop
    pc = obs.player_common
    raw = obs.raw_data

    own_units: list[dict] = []
    visible_enemies: list[dict] = []
    visible_allies: list[dict] = []
    mineral_fields: list[dict] = []
    if raw is not None:
        for u in raw.units:
            brief = _unit_brief_from_sc2(u, player_id)
            if brief is None:
                continue
            if u.owner == player_id:
                own_units.append(brief)
            elif u.alliance == 2:
                visible_allies.append(brief)
            # alliance: 1=Self, 2=Ally, 3=Neutral, 4=Enemy. Neutral map
            # objects must never become policy threats.
            elif u.alliance == 4:
                visible_enemies.append(brief)
            elif (u.alliance == 3
                  and brief["unit_type_id"] == "MineralField"):
                # 中立矿物单位，用于 gather 命令的 target 替换
                mineral_fields.append(brief)

    resources = {
        "minerals": pc.minerals if pc else 0,
        "vespene": pc.vespene if pc else 0,
        "supply_used": int(pc.food_used) if pc else 0,
        "supply_cap": int(pc.food_cap) if pc else 0,
    }

    alliance_summary: list[dict] = []
    grouped: dict[int, list[dict]] = {}
    for unit in own_units + visible_allies:
        grouped.setdefault(int(unit.get("owner", 0)), []).append(unit)
    for owner, units in sorted(grouped.items()):
        leader = min(units, key=lambda unit: unit["entity_id"], default=None)
        position = None if leader is None else {
            "x": leader["x"],
            "y": leader["y"],
        }
        alliance_summary.append({
            "player_id": owner,
            "is_self": owner == player_id,
            "is_ai": owner == 2,
            "unit_count": len(units),
            "alive": bool(units),
            "leader_position": position,
            "base_position": position,
            "raw_alliance": 1 if owner == player_id else 2,
        })

    return LiveObservation(
        loop=game_loop,
        player_id=player_id,
        own_units=own_units,
        visible_enemies=visible_enemies,
        resources=resources,
        mission={"win_condition": "live_sc2"},
        visible_allies=visible_allies,
        alliance_summary=alliance_summary,
        mineral_fields=mineral_fields,
    )


# ---------------------------------------------------------------------------
# Action 转换层：DefendAction → SC2 action_raw_unit_command
# ---------------------------------------------------------------------------

# 能力 ID 映射（名称 → int）。从 python-sc2 的 ability_id.py 解析。
_ABILITY_CACHE: Optional[dict[str, int]] = None


def _build_ability_map() -> dict[str, int]:
    """从 python-sc2 的 ability_id.py 解析 ability name → int 映射。"""
    global _ABILITY_CACHE
    if _ABILITY_CACHE is not None:
        return _ABILITY_CACHE
    amap: dict[str, int] = {}
    cand = REPO_ROOT / "reference" / "python-sc2" / "sc2" / "ids" / "ability_id.py"
    if cand.exists():
        import re
        txt = cand.read_text(encoding="utf-8", errors="replace")
        for mm in re.finditer(r"^\s*([A-Z][A-Z0-9_]+)\s*=\s*(\d+)\s*$", txt, re.M):
            amap[mm.group(1)] = int(mm.group(2))
    _ABILITY_CACHE = amap
    return amap


def _ability_id(name: str) -> int:
    """查 ability name → id，找不到返回 0。"""
    return _build_ability_map().get(name, 0)


# ---------------------------------------------------------------------------
# unit_type_id → ability_name 映射表
# ---------------------------------------------------------------------------
# SC2 的 ability 命名规则不一致：Terran 训练是 `<PRODUCER>TRAIN_<UNIT>`，
# 建造是 `TERRANBUILD_<BUILDING>`，Protoss/Zerg 又是另一套。
# 因此不能用 `f"TRAIN_{unit_type}"` 简单拼接，必须显式映射。
# 数据来源：reference/python-sc2/sc2/ids/ability_id.py
#
# 覆盖范围：defend_policy.py 中 PRODUCER_TYPES / ARMY_COMP 涉及的全部单位，
# 外加常用 Terran 单位以便未来扩展（Ghost/Reaper/Hellbat/Cyclone/Thor/
# WidowMine/Raven/Banshee/BattleCruiser/Liberator）。
TRAIN_ABILITY_MAP: dict[str, str] = {
    # Terran
    "SCV":             "COMMANDCENTERTRAIN_SCV",
    "Marine":          "BARRACKSTRAIN_MARINE",
    "Marauder":        "BARRACKSTRAIN_MARAUDER",
    "Reaper":          "BARRACKSTRAIN_REAPER",
    "Ghost":           "BARRACKSTRAIN_GHOST",
    "SiegeTank":       "FACTORYTRAIN_SIEGETANK",
    "Hellion":         "FACTORYTRAIN_HELLION",
    "Hellbat":         "TRAIN_HELLBAT",
    "Cyclone":         "TRAIN_CYCLONE",
    "Thor":            "FACTORYTRAIN_THOR",
    "WidowMine":       "FACTORYTRAIN_WIDOWMINE",
    "Medivac":         "STARPORTTRAIN_MEDIVAC",
    "Viking":          "STARPORTTRAIN_VIKINGFIGHTER",  # 注意：Viking → VIKINGFIGHTER
    "VikingFighter":   "STARPORTTRAIN_VIKINGFIGHTER",
    "Banshee":         "STARPORTTRAIN_BANSHEE",
    "Raven":           "STARPORTTRAIN_RAVEN",
    "BattleCruiser":   "STARPORTTRAIN_BATTLECRUISER",
    "Liberator":       "STARPORTTRAIN_LIBERATOR",
}

# Terran 建筑 unit_type_id → ability_name（build 命令用）
BUILD_ABILITY_MAP: dict[str, str] = {
    "CommandCenter":   "TERRANBUILD_COMMANDCENTER",
    "SupplyDepot":     "TERRANBUILD_SUPPLYDEPOT",
    "Refinery":        "TERRANBUILD_REFINERY",
    "Barracks":        "TERRANBUILD_BARRACKS",
    "EngineeringBay":  "TERRANBUILD_ENGINEERINGBAY",
    "MissileTurret":   "TERRANBUILD_MISSILETURRET",
    "Bunker":          "TERRANBUILD_BUNKER",
    "Factory":         "TERRANBUILD_FACTORY",
    "Starport":        "TERRANBUILD_STARPORT",
}


def build_action(
    a: DefendAction,
    player_id: int,
    source_unit_type_int: int = 0,
) -> Optional[sc_pb.Action]:
    """把 DefendAction 转成 SC2 Action。返回 None 表示跳过（如 hold）。"""
    if a.kind == "hold":
        return None  # 不发命令 = 保持当前位置

    cmd = raw_pb.ActionRawUnitCommand(
        unit_tags=[a.entity_id],
        queue_command=False,
    )

    if a.kind == "attack":
        if a.target_entity_id == 0:
            return None
        cmd.ability_id = _ability_id("ATTACK") or 23  # 23 = Attack default
        cmd.target_unit_tag = a.target_entity_id
    elif a.kind == "move":
        if source_unit_type_int == 4382:
            cmd.ability_id = _ability_id("SMART") or 1
        else:
            cmd.ability_id = _ability_id("MOVE_MOVE") or 16  # exact raw Move
        tp = cmd.target_world_space_pos
        tp.x = a.target_x
        tp.y = a.target_y
    elif a.kind == "gather":
        if a.target_entity_id == 0:
            return None
        # Empire workers expose Smart (1) but not the vanilla Harvest ability.
        # Right-clicking a mineral is the same command at this boundary.
        cmd.ability_id = _ability_id("SMART") or 1
        cmd.target_unit_tag = a.target_entity_id
    elif a.kind == "train":
        # train：通过 TRAIN_ABILITY_MAP 查 ability_name，再查 ability_id
        # （不能用 f"TRAIN_{unit_type}" 拼接：SC2 命名是 PRODUCER_TRAIN_UNIT）
        ability_name = TRAIN_ABILITY_MAP.get(a.unit_type_id, "")
        if not ability_name:
            return None  # 未知单位类型，跳过（runner 会记 train:no_action）
        aid = (
            17443
            if source_unit_type_int == 4390 and a.unit_type_id == "SCV"
            else _ability_id(ability_name)
        )
        if aid == 0:
            return None  # ability_id 解析失败（ability_id.py 缺该条目）
        cmd.ability_id = aid
    elif a.kind == "build":
        ability_name = BUILD_ABILITY_MAP.get(a.unit_type_id, "")
        if not ability_name:
            return None
        aid = _ability_id(ability_name)
        if aid == 0:
            return None
        cmd.ability_id = aid
        tp = cmd.target_world_space_pos
        tp.x = a.target_x
        tp.y = a.target_y
    else:
        return None

    action = sc_pb.Action(action_raw=raw_pb.ActionRaw(unit_command=cmd))
    return action


def build_ally_chat_action(message: str) -> sc_pb.Action:
    """Build the P1 chat action consumed by the Galaxy P2 ally trigger."""
    normalized = str(message).strip()
    if not normalized.startswith("!ally "):
        raise ValueError("ally chat messages must start with '!ally '")
    return sc_pb.Action(
        action_chat=sc_pb.ActionChat(
            channel=sc_pb.ActionChat.Team,
            message=normalized,
        )
    )


def _p2_state(obs: LiveObservation) -> list[dict]:
    """Return P2 state used for runtime before/after evidence."""
    units = obs.own_units if obs.player_id == P2_PLAYER_ID else obs.visible_allies
    return [
        {
            "entity_id": unit["entity_id"],
            "owner": unit.get("owner", 0),
            "alliance": unit.get("alliance", 0),
            "unit_type_id": unit.get("unit_type_id", ""),
            "x": round(float(unit.get("x", 0.0)), 3),
            "y": round(float(unit.get("y", 0.0)), 3),
        }
        for unit in units
        if int(unit.get("owner", 0)) == P2_PLAYER_ID
    ]


def _owner_state(obs: LiveObservation, owner_player_id: int) -> list[dict]:
    """Return only the requested owner from self/allied visible units."""
    units = obs.own_units + obs.visible_allies
    return [unit for unit in units if int(unit.get("owner", 0)) == owner_player_id]


def _has_p1_p2_participant_roster(player_roster: dict) -> bool:
    """Require both the human P1 slot and Vibe's P2 slot to be participants."""
    return all(
        int(player_roster.get(str(player_id), {}).get("type", 0)) == 1
        for player_id in (P1_PLAYER_ID, P2_PLAYER_ID)
    )


def _read_runtime_bank_section(bank_name: str = "GalaxyVibe") -> dict:
    """Read the ally Bank section for runtime command acknowledgements."""
    bank_path = Path.home() / "Documents" / "StarCraft II" / "Banks" / f"{bank_name}.SC2Bank"
    if not bank_path.exists():
        return {}
    try:
        import xml.etree.ElementTree as ET
        root = ET.parse(bank_path).getroot()
    except (OSError, ET.ParseError):
        return {}
    section = next((item for item in root.findall("Section") if item.get("name") == "ally"), None)
    if section is None:
        return {}
    result: dict = {}
    for key in section.findall("Key"):
        value = key.find("Value")
        if value is None:
            continue
        name = key.get("name", "")
        if "int" in value.attrib:
            try:
                result[name] = int(value.attrib["int"])
            except ValueError:
                result[name] = value.attrib["int"]
        elif "string" in value.attrib:
            result[name] = value.attrib["string"]
    return result


def _find_nearest_mineral_field_live(mineral_fields: list[dict],
                                     x: float, y: float) -> Optional[int]:
    """从 obs.mineral_fields 找离 (x, y) 最近的 MineralField entity_id（tag）。

    defend_policy 的 gather 命令用 target_entity_id=0 表示"由 runner 解析最近矿物"，
    本函数完成该解析。返回 None 表示 obs 中无可见矿物。
    """
    best_id: Optional[int] = None
    best_sq = float("inf")
    for mf in mineral_fields:
        dx = mf["x"] - x
        dy = mf["y"] - y
        sq = dx * dx + dy * dy
        if sq < best_sq:
            best_sq = sq
            best_id = mf["entity_id"]
    return best_id


# ---------------------------------------------------------------------------
# 真机对局 runner
# ---------------------------------------------------------------------------

@dataclass
class LiveGameReport:
    """真机对局结果报告。"""
    map_name: str
    end_loop: int
    end_reason: str
    player1_survivors: int
    enemy_survivors: dict
    total_commands_issued: int
    total_commands_dispatched: int
    duration_sec: float
    verdict: str
    summary: str
    cmd_ok_stats: dict = field(default_factory=dict)
    cmd_fail_stats: dict = field(default_factory=dict)
    cmd_ok_by_kind: dict = field(default_factory=dict)
    cmd_fail_by_kind: dict = field(default_factory=dict)
    action_result_trace: list[dict] = field(default_factory=list)
    runtime_assertions: dict = field(default_factory=dict)
    strategy_audit: dict = field(default_factory=dict)
    behavior_verdict: str = "inconclusive"
    local_map_path: str = ""
    replay_log_path: str = ""
    observed_player_id: int = P1_PLAYER_ID
    p2_unit_count: int = 0
    p2_alliance_values: list[int] = field(default_factory=list)
    player_roster: dict = field(default_factory=dict)
    ally_command_trace: list[dict] = field(default_factory=list)
    chat_received: list[dict] = field(default_factory=list)


def _write_replay_frame(fp, loop: int, obs: LiveObservation,
                        total_cmds: int, key_events: list[dict]) -> None:
    """写一帧回放日志到 JSONL 文件。"""
    p1_units_by_type: dict[str, int] = {}
    enemy_units_by_type: dict[str, int] = {}
    for u in obs.own_units:
        t = u["unit_type_id"]
        p1_units_by_type[t] = p1_units_by_type.get(t, 0) + 1
    for e in obs.visible_enemies:
        t = e["unit_type_id"]
        enemy_units_by_type[t] = enemy_units_by_type.get(t, 0) + 1
    p2_units_by_type: dict[str, int] = {}
    for e in obs.visible_allies:
        if int(e.get("owner", 0)) != P2_PLAYER_ID:
            continue
        t = e["unit_type_id"]
        p2_units_by_type[t] = p2_units_by_type.get(t, 0) + 1

    frame = {
        "loop": loop,
        "ts_sec": round(loop / 22.4, 1),
        "p1_alive": len(_owner_state(obs, P1_PLAYER_ID)),
        "enemy_alive": len(obs.visible_enemies),
        "p1_units_by_type": {
            unit_type: count
            for unit_type, count in Counter(
                unit.get("unit_type_id", "")
                for unit in _owner_state(obs, P1_PLAYER_ID)
            ).items()
        },
        "enemy_units_by_type": enemy_units_by_type,
        "p2_alive": len(_p2_state(obs)),
        "p2_units_by_type": p2_units_by_type,
        "strategy_player_id": obs.player_id,
        "strategy_player_resources": obs.resources,
        "total_cmds": total_cmds,
        "key_events": key_events,
    }
    fp.write(json.dumps(frame, ensure_ascii=False) + "\n")
    fp.flush()


async def run_live(
    port: int = 5000,
    map_path: str = DEFAULT_MAP,
    max_loops: int = 2000,
    step_size: int = 4,  # 每次推进 4 帧（约 0.18s）
    decision_interval: int = 22,  # 1 秒决策一次
    verbose: bool = True,
    replay_log_path: Optional[str] = None,
    force_map_path: bool = True,
    ally_commands: Optional[list[str]] = None,
) -> LiveGameReport:
    """运行真机 AI 盟友自主对局。

    Args:
        port: SC2 API 端口
        map_path: 地图文件路径
        max_loops: 最大 game loop 数
        step_size: 每次 Step 推进的帧数
        decision_interval: 决策间隔（帧数）
        verbose: 是否打印进度
        replay_log_path: JSONL 回放日志路径
        force_map_path: 使用原生地图路径，保留 CMRE 的外部依赖链
    """
    start_time = time.time()
    conn = Sc2Connection(port)
    await conn.connect()
    cmd_ok_stats: Counter = Counter()
    cmd_fail_stats: Counter = Counter()
    cmd_ok_by_kind: Counter = Counter()
    cmd_fail_by_kind: Counter = Counter()
    action_result_trace: list[dict] = []
    action_result_count_mismatches = 0
    total_commands_issued = 0
    total_commands_dispatched = 0

    # 回放日志
    if replay_log_path is None:
        from datetime import datetime as _dt
        ts = _dt.now().strftime("%Y%m%d_%H%M%S")
        replay_log_path = str(
            Path(__file__).resolve().parents[1] / "artifacts" / f"live_replay_{ts}.jsonl"
        )
    replay_path = Path(replay_log_path)
    replay_path.parent.mkdir(parents=True, exist_ok=True)
    replay_fp = open(replay_path, "w", encoding="utf-8")
    if verbose:
        print(f"  回放日志: {replay_path}")

    final_obs: Optional[LiveObservation] = None
    initial_obs: Optional[LiveObservation] = None
    map_name = os.path.basename(map_path)
    local_map_path = ""
    strategy_player_id = P2_PLAYER_ID
    player_id = strategy_player_id
    player_roster: dict = {}
    ally_command_trace: list[dict] = []
    chat_received: list[dict] = []
    try:
        # 1. Ping
        r = await conn.send_request(sc_pb.Request(ping=sc_pb.RequestPing()))
        if verbose:
            print(f"[1] Ping: version={r.ping.game_version} base={r.ping.base_build}")

        # 2. LeaveGame（清理之前状态；失败正常，说明之前不在游戏中）
        try:
            await conn.send_request(
                sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), timeout=10)
            if verbose:
                print("[2] LeaveGame OK")
        except Exception as e:
            if verbose:
                print(f"[2] LeaveGame skipped: {e}")
        await asyncio.sleep(2)

        # 3. CreateGame（realtime=False 避免异步通知干扰）
        if verbose:
            print(f"[3] CreateGame: {os.path.basename(map_path)}")
        map_file = Path(map_path)
        if not map_file.is_file():
            raise FileNotFoundError(
                f"Live runtime requires a packed .SC2Map file: {map_file}"
            )
        map_data = map_file.read_bytes()
        if not map_data:
            raise ValueError(f"Packed .SC2Map is empty: {map_file}")
        # Keep the native path by default. CMRE maps rely on external mod
        # dependencies; embedding a small archive as TempLaunchMap.SC2Map can
        # load the terrain while skipping the map initialization dependency
        # chain. The old embedding path remains available for transport-only
        # probes.
        if not force_map_path and len(map_data) <= 32 * 1024 * 1024:
            local_map = sc_pb.LocalMap(map_data=map_data)
        else:
            # SC2's Windows client expects a native path for dependency-bearing
            # maps. POSIX separators can make the API resolve a different map
            # while still returning a successful CreateGame response.
            local_map = sc_pb.LocalMap(map_path=str(map_file.resolve()))
        req = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=local_map,
            player_setup=[
                sc_pb.PlayerSetup(type=1, race=1, player_name="P1"),  # Human player slot
                sc_pb.PlayerSetup(type=1, race=1, player_name="P2"),  # Vibe strategy slot
            ],
            realtime=False,
        ))
        r = await conn.send_request(req, timeout=60, max_retries=5)
        if r.HasField("create_game") and r.create_game.HasField("error"):
            err = r.create_game.error
            if verbose:
                print(f"  CreateGame error: {err} (可能已在 in_game，尝试直接 JoinGame)")
        else:
            if verbose:
                print("  CreateGame OK")

        # 4. JoinGame（raw 接口）—— 参考 RealProfile：重试 30 次每次 500ms
        if verbose:
            print("[4] JoinGame...")
        join_req = sc_pb.Request(join_game=sc_pb.RequestJoinGame(
            race=1,  # Terran
            player_name="P2",
            options=sc_pb.InterfaceOptions(raw=True),
        ))
        joined = False
        for attempt in range(30):
            try:
                r = await conn.send_request(join_req, timeout=30, max_retries=2)
                if r.error:
                    if verbose and attempt == 0:
                        print(f"  JoinGame attempt {attempt+1}: error={r.error}")
                    await asyncio.sleep(0.5)
                    continue
                joined = True
                break
            except Exception as e:
                if verbose and attempt == 0:
                    print(f"  JoinGame attempt {attempt+1} exc: {e}")
                await asyncio.sleep(0.5)
        if not joined:
            # 最后一次尝试：用 Observation 探测是否已在 in_game
            try:
                r = await conn.send_request(
                    sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=15)
                if not r.error:
                    if verbose:
                        print("  JoinGame 超时但已在 in_game (Observation OK)")
                    joined = True
                else:
                    raise RuntimeError(f"JoinGame failed and not in_game: {r.error}")
            except Exception as e2:
                raise RuntimeError(f"JoinGame failed: {e2}")
        if r.HasField("join_game") and r.join_game.HasField("error"):
            # Observation 成功的情况没有 join_game 字段，跳过检查
            if not (r.HasField("observation")):
                raise RuntimeError(f"JoinGame failed: {r.join_game.error} {r.join_game.error_details}")
        if r.HasField("join_game"):
            player_id = r.join_game.player_id
        if player_id != strategy_player_id:
            raise RuntimeError(
                f"Vibe strategy must join P2, but SC2 assigned player_id={player_id}"
            )
        if verbose:
            print(f"  JoinGame OK! player_id={player_id}")

        # 等 15s 让 galaxy 脚本初始化（参考 RealProfile：15s 等待）
        if verbose:
            print("  等 15s 让 galaxy 脚本初始化...")
        await asyncio.sleep(15)

        # 5. GameInfo（获取地图名）
        r = await conn.send_request(sc_pb.Request(game_info=sc_pb.RequestGameInfo()), timeout=15)
        map_name = r.game_info.map_name or os.path.basename(map_path)
        local_map_path = r.game_info.local_map_path
        player_roster = {
            str(info.player_id): {
                "player_id": int(info.player_id),
                "type": int(info.type),
                "race_requested": int(info.race_requested),
                "race_actual": int(info.race_actual),
                "difficulty": int(info.difficulty),
                "player_name": info.player_name,
            }
            for info in r.game_info.player_info
        }
        if not _has_p1_p2_participant_roster(player_roster):
            raise RuntimeError(
                "P2 strategy requires a participant roster for both P1 and P2; "
                f"observed={player_roster}"
            )
        if verbose:
            print(f"[5] Map: {map_name} | local_map_path={local_map_path}")

        # 6. Native P2 task policy. P1 is the human player; this runner owns
        # only P2 units and every raw action is issued by the P2 participant.
        policy = DefendBasePolicy(player_id=player_id, command_interval=decision_interval)

        # 7. P1 -> P2 chat is intentionally disabled in the P2 participant
        # runner. It is a separate player-command channel, not Vibe strategy.
        run_token = str(int(start_time))
        commands = [] if player_id == P2_PLAYER_ID else (ally_commands or [
            f"!ally status stage25_{run_token}_status",
            f"!ally defend stage25_{run_token}_defend",
            f"!ally attack stage25_{run_token}_attack",
        ])
        command_cursor = 0
        command_due_loops = [0, max(1, max_loops // 4), max(2, max_loops // 2)]
        pending_command: Optional[dict] = None

        # 8. 主循环
        if verbose:
            print(f"[6] 运行对局 (max_loops={max_loops}, step_size={step_size})...")
        last_decide_loop = -10_000
        last_replay_loop = -10_000
        report_interval = max(50, max_loops // 20)
        last_report_loop = 0
        current_loop = 0
        last_native_decide_loop = -10_000
        consecutive_failures = 0
        max_consecutive_failures = 5
        train_backoff_until: dict[int, int] = {}

        while current_loop < max_loops:
            try:
                # Step 推进游戏
                await conn.send_request(
                    sc_pb.Request(step=sc_pb.RequestStep(count=step_size)),
                    timeout=15)

                # Observation
                r = await conn.send_request(
                    sc_pb.Request(observation=sc_pb.RequestObservation()),
                    timeout=15)
                consecutive_failures = 0
            except (ConnectionError, TimeoutError, RuntimeError) as e:
                consecutive_failures += 1
                if verbose:
                    print(f"  loop {current_loop}: 第 {consecutive_failures} 次失败: {e}")
                if consecutive_failures >= max_consecutive_failures:
                    if verbose:
                        print(f"  连续 {max_consecutive_failures} 次失败，对局结束")
                    break
                await asyncio.sleep(2)
                continue

            obs = build_observation(r, player_id)
            if (
                initial_obs is None
                and obs.own_units
                and obs.resources.get("supply_cap", 0) > 0
            ):
                initial_obs = obs
            current_loop = obs.loop

            # 检查游戏是否结束
            if r.observation.player_result:
                results = {pr.player_id: pr.result for pr in r.observation.player_result}
                if verbose:
                    print(f"  游戏结束: {results}")
                break

            for received in r.observation.chat:
                chat_received.append({
                    "loop": current_loop,
                    "player_id": int(received.player_id),
                    "message": received.message,
                })

            # Native strategy action adapter. Every entry in
            # action_result_trace comes from this block and is eligible for
            # the no-injection strategy audit.
            if current_loop - last_native_decide_loop >= decision_interval:
                last_native_decide_loop = current_loop
                actions = policy.decide(obs, current_loop, resources=obs.resources)
                total_commands_issued += len([a for a in actions if a.kind != "hold"])
                sc2_actions: list[sc_pb.Action] = []
                action_contexts: list[dict] = []
                own_by_tag = {u["entity_id"]: u for u in obs.own_units}
                target_by_tag = {
                    u["entity_id"]: u
                    for u in obs.visible_enemies + obs.mineral_fields
                }
                for action_decision in actions:
                    if action_decision.kind == "hold":
                        continue
                    source_unit = own_by_tag.get(action_decision.entity_id, {})
                    if action_decision.kind == "train":
                        producer_tag = int(action_decision.entity_id)
                        if source_unit.get("orders") or current_loop < train_backoff_until.get(
                            producer_tag, 0
                        ):
                            cmd_fail_stats["train:producer_busy"] += 1
                            cmd_fail_by_kind["train:ProducerBusy"] += 1
                            if len(action_result_trace) < 500:
                                action_result_trace.append({
                                    "loop": current_loop,
                                    "kind": "train",
                                    "entity_id": producer_tag,
                                    "unit_type_id": source_unit.get("unit_type_id", ""),
                                    "unit_type_int": source_unit.get("unit_type_int", 0),
                                    "ability_id": 0,
                                    "target_entity_id": 0,
                                    "target_unit_type_id": "",
                                    "target_owner": 0,
                                    "target_alliance": 0,
                                    "target_x": 0.0,
                                    "target_y": 0.0,
                                    "reason": action_decision.reason,
                                    "result": "ProducerBusy",
                                })
                            continue

                    action_for_transport = action_decision
                    if (action_for_transport.kind == "gather"
                            and action_for_transport.target_entity_id == 0):
                        worker = own_by_tag.get(action_for_transport.entity_id, {})
                        nearest_mineral = _find_nearest_mineral_field_live(
                            obs.mineral_fields,
                            worker.get("x", 0.0),
                            worker.get("y", 0.0),
                        )
                        if nearest_mineral is None:
                            cmd_fail_stats["gather:no_mineral"] += 1
                            continue
                        action_for_transport = DefendAction(
                            entity_id=action_for_transport.entity_id,
                            kind=action_for_transport.kind,
                            target_entity_id=nearest_mineral,
                            unit_type_id=action_for_transport.unit_type_id,
                            reason=action_for_transport.reason,
                        )

                    sc2_action = build_action(
                        action_for_transport,
                        player_id,
                        source_unit_type_int=source_unit.get("unit_type_int", 0),
                    )
                    if sc2_action is None:
                        cmd_fail_stats[f"{action_for_transport.kind}:no_action"] += 1
                        continue
                    sc2_actions.append(sc2_action)
                    raw_command = sc2_action.action_raw.unit_command
                    target_tag = (
                        raw_command.target_unit_tag
                        if raw_command.HasField("target_unit_tag") else 0
                    )
                    action_contexts.append({
                        "loop": current_loop,
                        "kind": action_for_transport.kind,
                        "entity_id": action_for_transport.entity_id,
                        "issuer_player_id": player_id,
                        "source_owner": source_unit.get("owner", 0),
                        "unit_type_id": source_unit.get("unit_type_id", ""),
                        "command_unit_type_id": action_for_transport.unit_type_id,
                        "unit_type_int": source_unit.get("unit_type_int", 0),
                        "ability_id": raw_command.ability_id,
                        "target_entity_id": target_tag,
                        "target_unit_type_id": target_by_tag.get(target_tag, {}).get(
                            "unit_type_id", ""
                        ),
                        "target_owner": target_by_tag.get(target_tag, {}).get("owner", 0),
                        "target_alliance": target_by_tag.get(target_tag, {}).get("alliance", 0),
                        "target_x": action_for_transport.target_x,
                        "target_y": action_for_transport.target_y,
                        "reason": action_for_transport.reason,
                    })
                    total_commands_dispatched += 1

                if sc2_actions:
                    try:
                        action_response = await conn.send_request(
                            sc_pb.Request(action=sc_pb.RequestAction(actions=sc2_actions)),
                            timeout=10,
                        )
                        results = list(action_response.action.result)
                        if len(results) != len(action_contexts):
                            action_result_count_mismatches += 1
                        for index, result in enumerate(results):
                            context = (
                                action_contexts[index]
                                if index < len(action_contexts)
                                else {"loop": current_loop, "kind": "unmatched"}
                            )
                            if result == error_pb2.ActionResult.Success:
                                cmd_ok_stats["dispatched"] += 1
                                cmd_ok_by_kind[context["kind"]] += 1
                                result_name = "Success"
                            else:
                                try:
                                    result_name = error_pb2.ActionResult.Name(result)
                                except ValueError:
                                    result_name = f"unknown({result})"
                                cmd_fail_stats[f"sc2:{result_name}"] += 1
                                cmd_fail_by_kind[
                                    f"{context['kind']}:{result_name}"
                                ] += 1
                                if (context["kind"] == "train"
                                        and result_name == "QueueIsFull"):
                                    train_backoff_until[int(context["entity_id"])] = (
                                        current_loop + max(96, decision_interval * 4)
                                    )
                            if len(action_result_trace) < 500:
                                action_result_trace.append({
                                    **context,
                                    "result": result_name,
                                })
                    except (ConnectionError, TimeoutError) as exc:
                        cmd_fail_stats["action_send_exception"] += 1
                        if verbose:
                            print(f"  Action send failed: {exc}")

            # P1 sends an explicit chat signal; the Galaxy handler owns P2's
            # unit group and writes the acknowledgement to the ally Bank.
            if current_loop - last_decide_loop >= decision_interval:
                last_decide_loop = current_loop
                if command_cursor < len(commands) and current_loop >= command_due_loops[command_cursor]:
                    command = str(commands[command_cursor]).strip()
                    before_state = _p2_state(obs)
                    bank_before = _read_runtime_bank_section()
                    try:
                        chat_request = sc_pb.Request(action=sc_pb.RequestAction(
                            actions=[build_ally_chat_action(command)]
                        ))
                        chat_response = await conn.send_request(chat_request, timeout=10)
                        sent_ok = not bool(chat_response.error)
                        if sent_ok:
                            total_commands_issued += 1
                            total_commands_dispatched += 1
                            cmd_ok_stats["ally_chat"] += 1
                            cmd_ok_by_kind["ally_chat"] += 1
                        else:
                            cmd_fail_stats["ally_chat"] += 1
                            cmd_fail_by_kind["ally_chat"] += 1
                        pending_command = {
                            "loop": current_loop,
                            "message": command,
                    "source_player_id": player_id,
                            "target_player_id": P2_PLAYER_ID,
                            "transport": "sc2api_action_chat",
                            "request_ok": sent_ok,
                            "response_errors": list(chat_response.error),
                            "p2_before": before_state,
                            "bank_before": bank_before,
                        }
                    except (ConnectionError, TimeoutError) as e:
                        cmd_fail_stats["ally_chat_exception"] += 1
                        pending_command = {
                            "loop": current_loop,
                            "message": command,
                            "source_player_id": player_id,
                            "target_player_id": P2_PLAYER_ID,
                            "transport": "sc2api_action_chat",
                            "request_ok": False,
                            "error": str(e),
                            "p2_before": before_state,
                            "bank_before": bank_before,
                        }
                    command_cursor += 1

            if pending_command is not None:
                bank_after = _read_runtime_bank_section()
                if bank_after.get("last_command") == pending_command["message"]:
                    pending_command["p2_after"] = _p2_state(obs)
                    pending_command["bank_after"] = bank_after
                    pending_command["completed"] = True
                    pending_command["p2_position_changed"] = (
                        pending_command["p2_before"] != pending_command["p2_after"]
                    )
                    ally_command_trace.append(pending_command)
                    pending_command = None

            # 回放日志记录
            if current_loop - last_replay_loop >= 50:
                last_replay_loop = current_loop
                _write_replay_frame(replay_fp, current_loop, obs,
                                    total_commands_dispatched, [])

            # 进度报告
            if verbose and current_loop - last_report_loop >= report_interval:
                last_report_loop = current_loop
                elapsed = time.time() - start_time
                print(f"  loop {current_loop}/{max_loops} ({current_loop/max_loops:.0%}) "
                      f"elapsed={elapsed:.1f}s | P1:{len(obs.own_units)} "
                      f"Enemy:{len(obs.visible_enemies)} "
                      f"M:{obs.resources['minerals']} V:{obs.resources['vespene']} "
                      f"Sup:{obs.resources['supply_used']}/{obs.resources['supply_cap']} "
                      f"Cmds:{total_commands_dispatched} "
                      f"OK:{dict(cmd_ok_stats)} FAIL:{dict(cmd_fail_stats)}",
                      flush=True)

        # 最终 Observation
        try:
            r = await conn.send_request(
                sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=15)
            final_obs = build_observation(r, player_id)
            _write_replay_frame(replay_fp, current_loop, final_obs,
                                total_commands_dispatched, [])
        except Exception:
            pass

    finally:
        await conn.close()
        replay_fp.close()

    # 计算结果
    elapsed = time.time() - start_time
    p1_survivors = (
        len(_owner_state(final_obs, P1_PLAYER_ID)) if final_obs is not None else 0
    )
    p2_state = _p2_state(final_obs) if final_obs is not None else []
    if pending_command is not None:
        pending_command["p2_after"] = p2_state
        pending_command["bank_after"] = _read_runtime_bank_section()
        pending_command["completed"] = False
        pending_command["p2_position_changed"] = (
            pending_command["p2_before"] != pending_command["p2_after"]
        )
        ally_command_trace.append(pending_command)
        pending_command = None
    enemy_survivors: dict = {}
    if final_obs is not None:
        for e in final_obs.visible_enemies:
            owner = e.get("owner", 0)
            if owner != 0:
                enemy_survivors[owner] = enemy_survivors.get(owner, 0) + 1

    # 判定胜负
    if p1_survivors > 0 and current_loop >= max_loops:
        verdict = "victory"
        summary = f"玩家存活到 loop {current_loop}，剩余 {p1_survivors} 单位"
    elif p1_survivors == 0:
        verdict = "defeat"
        summary = f"玩家在 loop {current_loop} 全灭"
    else:
        verdict = "inconclusive"
        summary = f"对局在 loop {current_loop} 结束"

    strategy_audit = audit_native_strategy(
        action_result_trace,
        initial_observation=(initial_obs.__dict__ if initial_obs is not None else None),
        final_observation=(final_obs.__dict__ if final_obs is not None else None),
        expected_player_id=strategy_player_id,
        required_buildings=("Barracks", "Refinery"),
        required_units=("Marine",),
    )

    report = LiveGameReport(
        map_name=map_name,
        end_loop=current_loop,
        end_reason="max_loops_reached" if current_loop >= max_loops else "game_over",
        player1_survivors=p1_survivors,
        enemy_survivors=enemy_survivors,
        total_commands_issued=total_commands_issued,
        total_commands_dispatched=total_commands_dispatched,
        duration_sec=round(elapsed, 2),
        verdict=verdict,
        summary=summary,
        cmd_ok_stats=dict(cmd_ok_stats),
        cmd_fail_stats=dict(cmd_fail_stats),
        cmd_ok_by_kind=dict(cmd_ok_by_kind),
        cmd_fail_by_kind=dict(cmd_fail_by_kind),
        action_result_trace=action_result_trace,
        runtime_assertions={
            "frames_advanced": current_loop > 0,
            "player_units_observed": p1_survivors > 0,
            "strategy_player_id_is_p2": strategy_player_id == P2_PLAYER_ID,
            "p1_p2_participant_roster": _has_p1_p2_participant_roster(player_roster),
            "strategy_player_units_observed": len(p2_state) > 0,
            "action_results_correlated": action_result_count_mismatches == 0,
            "action_success_observed": cmd_ok_stats.get("dispatched", 0) > 0,
            "native_strategy_action_success": strategy_audit["status"] == "PASS",
            "p2_roster_observed": bool(p2_state),
            "p2_command_ack_observed": any(
                item.get("completed")
                and item.get("bank_after", {}).get("last_result")
                in {"status", "acknowledged", "attack_issued", "attack_no_target"}
                for item in ally_command_trace
            ),
            "native_strategy_no_debug_injection": strategy_audit["checks"][
                "no_debug_injection"
            ],
            "native_strategy_state_delta": strategy_audit["checks"][
                "state_observed_before_after"
            ],
        },
        strategy_audit=strategy_audit,
        behavior_verdict=(
            "pass"
            if strategy_audit["status"] == "PASS"
            else "fail"
        ),
        local_map_path=local_map_path,
        replay_log_path=str(replay_path),
        observed_player_id=strategy_player_id,
        p2_unit_count=len(p2_state),
        p2_alliance_values=sorted({int(item.get("alliance", 0)) for item in p2_state}),
        player_roster=player_roster,
        ally_command_trace=ally_command_trace,
        chat_received=chat_received,
    )

    if verbose:
        print(f"\n=== 真机对局结束 ===")
        print(f"地图: {report.map_name}")
        print(f"结果: {report.verdict.upper()}")
        print(f"Loop: {report.end_loop}/{max_loops} ({report.end_loop/max_loops:.0%})")
        print(f"耗时: {report.duration_sec}s")
        print(f"Player 1 幸存: {report.player1_survivors}")
        print(f"P2 盟友可见单位: {report.p2_unit_count} alliance={report.p2_alliance_values}")
        print(f"P1->P2 盟友命令: {len(report.ally_command_trace)}")
        print(f"敌方幸存: {report.enemy_survivors}")
        print(f"命令下发: {report.total_commands_issued}")
        print(f"命令执行: {report.total_commands_dispatched}")
        print(f"命令成功: {report.cmd_ok_stats}")
        print(f"命令失败: {report.cmd_fail_stats}")
        print(f"按类型成功: {report.cmd_ok_by_kind}")
        print(f"按类型失败: {report.cmd_fail_by_kind}")
        print(f"行为断言: {report.runtime_assertions}")
        print(f"总结: {report.summary}")
        print(f"回放: {report.replay_log_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="亡者之夜 AI 盟友真机自主对局")
    parser.add_argument("--port", type=int, default=5000, help="SC2 API 端口")
    parser.add_argument("--map", type=str, default=DEFAULT_MAP, help="地图文件路径")
    parser.add_argument("--max-loops", type=int, default=2000, help="最大 loop 数")
    parser.add_argument("--step-size", type=int, default=4, help="每次 Step 帧数")
    parser.add_argument("--decision-interval", type=int, default=22, help="决策间隔（帧数）")
    parser.add_argument(
        "--embed-map-data",
        action="store_true",
        help="显式使用 SC2 API map_data 嵌入路径（仅用于 transport-only probes）",
    )
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    parser.add_argument("--output", type=str, default=None, help="报告输出 JSON 路径")
    args = parser.parse_args()

    report = asyncio.run(run_live(
        port=args.port,
        map_path=args.map,
        max_loops=args.max_loops,
        step_size=args.step_size,
        decision_interval=args.decision_interval,
        verbose=not args.quiet,
        force_map_path=not args.embed_map_data,
    ))

    if args.output:
        report_path = Path(args.output)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_data = {k: v for k, v in report.__dict__.items()}
        report_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入: {report_path}")

    return 0 if report.verdict == "victory" and report.behavior_verdict == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
