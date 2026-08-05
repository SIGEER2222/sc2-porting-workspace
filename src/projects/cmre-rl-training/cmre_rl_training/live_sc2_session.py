"""Blocking raw SC2 API session used by the live RL bridge.

The module deliberately keeps protocol imports lazy. Offline project tests can
exercise observation normalization and action grounding without an SC2 install,
while the runtime runner supplies the checked-in s2client-proto package.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .action_space import ACTION_NAMES


RACE_TERRAN = 1
PLAYER_PARTICIPANT = 1
PLAYER_COMPUTER = 2
DIFFICULTY_EASY = 2
ACTION_RESULT_SUCCESS = 1
PLAYER_RESULT_NAMES = {
    1: "victory",
    2: "defeat",
    3: "tie",
    4: "undecided",
}

# Stable SC2 catalog names required by the shared encoder and action mask.
# Unknown IDs remain numeric strings so the raw observation is not discarded.
UNIT_TYPE_NAMES: dict[int, str] = {
    18: "CommandCenter",
    19: "SupplyDepot",
    20: "Refinery",
    21: "Barracks",
    22: "EngineeringBay",
    23: "MissileTurret",
    24: "Bunker",
    25: "SensorTower",
    26: "GhostAcademy",
    27: "Factory",
    28: "Starport",
    29: "Armory",
    30: "FusionCore",
    32: "SiegeTankSieged",
    33: "SiegeTank",
    34: "VikingAssault",
    35: "VikingFighter",
    37: "BarracksTechLab",
    38: "BarracksReactor",
    39: "FactoryTechLab",
    40: "FactoryReactor",
    41: "StarportTechLab",
    42: "StarportReactor",
    45: "SCV",
    47: "SupplyDepotLowered",
    48: "Marine",
    49: "Reaper",
    50: "Ghost",
    51: "Marauder",
    52: "Thor",
    53: "Hellion",
    54: "Medivac",
    55: "Banshee",
    56: "Raven",
    57: "Battlecruiser",
    59: "Nexus",
    60: "Pylon",
    81: "WarpPrism",
    84: "Probe",
    86: "Hatchery",
    87: "CreepTumor",
    104: "Drone",
    105: "Zergling",
    106: "Overlord",
    107: "Hydralisk",
    109: "Ultralisk",
    110: "Roach",
    146: "RichMineralField",
    147: "RichMineralField750",
    341: "MineralField",
    342: "VespeneGeyser",
    343: "SpacePlatformGeyser",
    344: "RichVespeneGeyser",
    460: "SCV",
    483: "PurifierMineralField",
    484: "PurifierRichMineralField",
    489: "Medivac",
    880: "RichMineralField750",
    883: "VespeneGeyser",
    884: "SpacePlatformGeyser",
    885: "RichVespeneGeyser",
}
MINERAL_FIELD_IDS = frozenset({146, 147, 341, 483, 484, 880})
VESpENE_GEYSER_IDS = frozenset({342, 343, 344, 883, 884, 885})

# Basic ability IDs are from the SC2 multiplayer data used by the approved
# runtime probe. They are transport details, not policy-facing action names.
ABILITY_IDS = {
    "MOVE": 16,
    "PATROL": 17,
    "HOLDPOSITION": 18,
    "STOP": 3665,
    "ATTACK": 3674,
    "HARVEST_GATHER": 3666,
    "LOAD": 3668,
    "UNLOADALL": 3664,
    "RALLY_COMMANDCENTER": 203,
    "EFFECT_STIM": 3675,
    "EFFECT_REPAIR": 3685,
    "CANCEL": 3659,
}
BUILD_ABILITIES = {
    "SupplyDepot": 319,
    "Barracks": 321,
    "Refinery": 320,
    "CommandCenter": 318,
    "EngineeringBay": 322,
    "Factory": 328,
    "Starport": 329,
    "Bunker": 324,
    "Armory": 331,
    "SensorTower": 326,
    "GhostAcademy": 327,
    "FusionCore": 333,
    "TechLab": 3682,
    "Reactor": 3683,
}
TRAIN_ABILITIES = {
    "SCV": 524,
    "Marine": 560,
    "Marauder": 563,
    "Reaper": 561,
    "Ghost": 566,
    "SiegeTank": 591,
    "Hellion": 589,
    "Thor": 596,
    "Medivac": 620,
    "VikingFighter": 621,
    "Banshee": 624,
    "Raven": 619,
    "Battlecruiser": 626,
}
RESEARCH_ABILITIES = {
    "TerranInfantryWeaponsLevel1": 652,
    "TerranInfantryWeaponsLevel2": 653,
    "TerranInfantryWeaponsLevel3": 654,
    "TerranInfantryArmorLevel1": 656,
    "TerranInfantryArmorLevel2": 657,
    "TerranInfantryArmorLevel3": 658,
    "Stimpack": 730,
    "CombatShield": 731,
    "ConcussiveShells": 732,
}
MORPH_ABILITIES = {
    "SiegeMode": 388,
    "SiegeTankSieged": 388,
    "Unsiege": 390,
    "OrbitalCommand": 1516,
    "PlanetaryFortress": 1450,
}
CAST_ABILITIES = {"Stimpack": 3675, "Repair": 3685}


class LiveSc2Error(RuntimeError):
    """Raised when the SC2 raw API refuses a lifecycle operation."""


class RawActionError(ValueError):
    """Raised when a grounded action cannot become a raw unit command."""


@dataclass(frozen=True)
class RawActionSpec:
    """Protocol-independent representation of an ActionRawUnitCommand."""

    action_id: str
    ability_id: int
    target_type: str
    unit_tag: int
    target_unit_tag: int = 0
    target_x: float = 0.0
    target_y: float = 0.0


def unit_type_name(unit_type_id: Any) -> str:
    """Return a stable policy-facing unit name for a raw Catalog ID."""

    try:
        numeric = int(unit_type_id)
    except (TypeError, ValueError):
        return str(unit_type_id)
    return UNIT_TYPE_NAMES.get(numeric, str(numeric))


def resolve_ability_and_target(action_id: str, args: Mapping[str, Any] | None) -> tuple[int, str]:
    """Resolve one of the 19 policy actions to ability and target kind."""

    action = str(action_id)
    values = dict(args or {})
    simple = {
        "move_units": ("MOVE", "point"),
        "stop_units": ("STOP", "none"),
        "hold_units": ("HOLDPOSITION", "none"),
        "patrol_units": ("PATROL", "point"),
        "attack_move_units": ("ATTACK", "point"),
        "attack_units": ("ATTACK", "unit"),
        "gather_resources": ("HARVEST_GATHER", "unit"),
        "repair_units": ("EFFECT_REPAIR", "unit"),
        "rally_producer": ("RALLY_COMMANDCENTER", "point"),
        "load_units": ("LOAD", "unit"),
        "unload_units": ("UNLOADALL", "none"),
        "cancel_order": ("CANCEL", "none"),
        "cast_no_target_ability": ("EFFECT_STIM", "none"),
    }
    if action in simple:
        key, target_type = simple[action]
        return ABILITY_IDS[key], target_type
    if action == "build_structure":
        return BUILD_ABILITIES.get(str(values.get("unit_type_id", values.get("unit_type", "SupplyDepot"))), 319), "point"
    if action == "produce_unit":
        return TRAIN_ABILITIES.get(str(values.get("unit_type_id", values.get("unit_type", "Marine"))), 560), "none"
    if action == "research_upgrade":
        return RESEARCH_ABILITIES.get(str(values.get("upgrade_id", values.get("upgrade", "TerranInfantryWeaponsLevel1"))), 652), "none"
    if action == "cast_point_ability":
        return CAST_ABILITIES.get(str(values.get("ability_id", values.get("ability", "Stimpack"))), 3675), "point"
    if action == "cast_unit_ability":
        return CAST_ABILITIES.get(str(values.get("ability_id", values.get("ability", "Repair"))), 3685), "unit"
    if action == "morph_unit":
        return MORPH_ABILITIES.get(str(values.get("unit_type_id", values.get("unit_type", "SiegeTankSieged"))), 388), "none"
    raise RawActionError(f"unknown_action:{action}")


def build_raw_action_spec(
    action_id: str,
    args: Mapping[str, Any] | None,
    own_units: list[Mapping[str, Any]],
    *,
    observation: Mapping[str, Any] | None = None,
) -> RawActionSpec:
    """Convert canonical ActionGrounder args into a raw command spec."""

    if action_id not in ACTION_NAMES:
        raise RawActionError(f"unknown_action:{action_id}")
    if not own_units:
        raise RawActionError("no_own_units")
    values = dict(args or {})
    ability_id, target_type = resolve_ability_and_target(action_id, values)
    actor = _pick_actor(action_id, own_units, values)
    unit_tag = _entity_id(actor)
    if unit_tag <= 0:
        raise RawActionError("unit_entity_id_invalid")

    if target_type == "unit":
        target = values.get("target_entity_id", values.get("target_tag", 0))
        if not target:
            target = _pick_target(action_id, observation)
        try:
            target_tag = int(target)
        except (TypeError, ValueError) as exc:
            raise RawActionError("target_entity_id_invalid") from exc
        if target_tag <= 0:
            raise RawActionError("no_target_unit")
        return RawActionSpec(action_id, ability_id, target_type, unit_tag, target_unit_tag=target_tag)

    if target_type == "point":
        try:
            x = float(values.get("target_x", 70.0))
            y = float(values.get("target_y", 80.0))
        except (TypeError, ValueError) as exc:
            raise RawActionError("target_point_invalid") from exc
        return RawActionSpec(action_id, ability_id, target_type, unit_tag, target_x=x, target_y=y)

    return RawActionSpec(action_id, ability_id, target_type, unit_tag)


def build_raw_action(spec: RawActionSpec, raw_pb: Any, common_pb: Any) -> Any:
    """Build the generated protobuf message only at the transport boundary."""

    command = raw_pb.ActionRawUnitCommand(
        ability_id=int(spec.ability_id),
        unit_tags=[int(spec.unit_tag)],
        queue_command=False,
    )
    if spec.target_type == "point":
        command.target_world_space_pos.CopyFrom(
            common_pb.Point2D(x=float(spec.target_x), y=float(spec.target_y))
        )
    elif spec.target_type == "unit":
        command.target_unit_tag = int(spec.target_unit_tag)
    return raw_pb.ActionRaw(unit_command=command)


def wrap_raw_action(raw_action: Any, sc_pb: Any) -> Any:
    """Wrap ActionRaw in the sc2api Action envelope required by RequestAction."""

    return sc_pb.Action(action_raw=raw_action)


def parse_observation_response(
    response: Any,
    *,
    player_id: int,
    map_name: str,
    progress_loop_limit: int = 100000,
) -> dict[str, Any]:
    """Parse a raw SC2 ResponseObservation into the shared RL observation shape."""

    if not response.HasField("observation"):
        raise LiveSc2Error("observation_response_missing")
    response_observation = response.observation.observation
    raw = response_observation.raw_data
    player_common = response_observation.player_common
    own_units: list[dict[str, Any]] = []
    visible_enemies: list[dict[str, Any]] = []
    visible_allies: list[dict[str, Any]] = []
    mineral_fields: list[dict[str, Any]] = []
    vespene_geysers: list[dict[str, Any]] = []

    for unit in raw.units:
        type_id = int(unit.unit_type)
        owner = int(unit.owner)
        position = unit.pos
        info: dict[str, Any] = {
            "entity_id": int(unit.tag),
            "unit_type_id": unit_type_name(type_id),
            "unit_type_int": type_id,
            "owner": owner,
            "x": float(position.x),
            "y": float(position.y),
            "health": float(unit.health),
            "health_max": float(unit.health_max),
            "shields": float(unit.shield),
            "shield_max": float(unit.shield_max),
            "energy": float(unit.energy),
            "orders": [{"ability_id": int(order.ability_id)} for order in unit.orders],
            "is_flying": bool(unit.is_flying),
            "is_burrowed": bool(unit.is_burrowed),
        }
        if owner == player_id or int(getattr(unit, "alliance", 0)) == 1:
            own_units.append(info)
        elif type_id in MINERAL_FIELD_IDS:
            mineral_fields.append(info)
        elif type_id in VESpENE_GEYSER_IDS:
            vespene_geysers.append(info)
        elif int(getattr(unit, "alliance", 0)) == 2:
            visible_allies.append(info)
        elif owner != 0:
            visible_enemies.append(info)

    loop = int(response_observation.game_loop)
    limit = max(1, int(progress_loop_limit))
    progress = min(1.0, max(0.0, loop / limit))
    player_results = [
        {
            "player_id": int(result.player_id),
            "result": int(result.result),
            "result_name": PLAYER_RESULT_NAMES.get(int(result.result), "unknown"),
        }
        for result in response.observation.player_result
    ]
    player_result = next(
        (result for result in player_results if result["player_id"] == int(player_id)),
        None,
    )
    terminal = player_result is not None
    end_reason = (
        f"player_result_{player_result['result_name']}"
        if player_result is not None
        else ""
    )
    return {
        "loop": loop,
        "player_id": int(player_id),
        "map_name": str(map_name),
        "own_units": own_units,
        "visible_enemies": visible_enemies,
        "visible_allies": visible_allies,
        "resources": {
            "minerals": int(player_common.minerals),
            "vespene": int(player_common.vespene),
            "supply_used": int(player_common.food_used),
            "supply_cap": int(player_common.food_cap),
            "state_version": loop,
        },
        "mission": {
            "phase": "terminal" if terminal else "active",
            "night": 0,
            "wave": 0,
            "terminated": terminal,
            "end_reason": end_reason,
            "win_condition": "player_result" if terminal else "runtime_step_budget",
            "progress": 1.0 if terminal else progress,
            "state_version": loop,
        },
        "mineral_fields": mineral_fields,
        "vespene_geysers": vespene_geysers,
        "tech": {"completed_upgrades": [], "researching": []},
        "action_errors": [],
        "player_result": player_results,
        "strategic_points": [],
    }


class Sc2ApiClient:
    """Synchronous facade over the SC2 websocket API."""

    def __init__(
        self,
        port: int,
        *,
        timeout: float = 120.0,
        reconnect_delay: float = 0.5,
    ) -> None:
        self.port = int(port)
        self.timeout = float(timeout)
        self.reconnect_delay = max(0.1, float(reconnect_delay))
        self.api_url = f"ws://127.0.0.1:{self.port}/sc2api"
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._session: Any = None
        self._websocket: Any = None
        self._next_request_id = 1

    def connect(self) -> None:
        self._submit(self._connect_with_retry(timeout=30.0), timeout=35.0)

    def send(
        self,
        request: Any,
        *,
        timeout: float | None = None,
        retry_on_disconnect: bool = False,
    ) -> Any:
        request_timeout = timeout or self.timeout
        return self._submit(
            self._send(
                request,
                timeout=request_timeout,
                retry_on_disconnect=retry_on_disconnect,
            ),
            timeout=request_timeout + 5.0,
        )

    def close(self) -> None:
        try:
            self._submit(self._close(), timeout=10.0)
        except Exception:
            pass
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3.0)

    def _submit(self, coroutine: Any, *, timeout: float) -> Any:
        future = asyncio.run_coroutine_threadsafe(coroutine, self._loop)
        return future.result(timeout=timeout)

    async def _connect(self) -> None:
        import aiohttp

        await self._close()
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(sock_connect=15, sock_read=self.timeout)
        )
        self._websocket = await self._session.ws_connect(
            self.api_url,
            max_msg_size=0,
            timeout=aiohttp.ClientWSTimeout(ws_close=30),
            autoclose=False,
            autoping=False,
        )

    async def _connect_with_retry(self, *, timeout: float) -> None:
        deadline = time.monotonic() + max(0.1, float(timeout))
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            try:
                await self._connect()
                return
            except Exception as exc:
                last_error = exc
                await self._close()
                await asyncio.sleep(min(self.reconnect_delay, max(0.0, deadline - time.monotonic())))
        raise LiveSc2Error(f"sc2_api_connect_timeout:{last_error}") from last_error

    async def _send(
        self,
        request: Any,
        *,
        timeout: float,
        retry_on_disconnect: bool = False,
    ) -> Any:
        from s2clientprotocol import sc2api_pb2 as sc_pb

        import aiohttp

        request_name = request.WhichOneof("request") or "request"
        deadline = time.monotonic() + max(0.1, float(timeout))
        attempts = 0
        try:
            request.id = self._next_request_id
            self._next_request_id += 1
        except (AttributeError, TypeError):
            request_id = 0
        else:
            request_id = int(request.id)
        while True:
            try:
                if self._websocket is None or self._websocket.closed:
                    if not retry_on_disconnect:
                        raise LiveSc2Error("sc2_api_not_connected")
                    await self._connect_with_retry(timeout=min(15.0, max(0.1, deadline - time.monotonic())))
                await self._websocket.send_bytes(request.SerializeToString())
                while time.monotonic() < deadline:
                    remaining = max(0.1, deadline - time.monotonic())
                    message = await asyncio.wait_for(
                        self._websocket.receive(), timeout=remaining
                    )
                    if message.type == aiohttp.WSMsgType.BINARY:
                        response = sc_pb.Response()
                        response.ParseFromString(bytes(message.data))
                        if not response.HasField("id") or not request_id or response.id == request_id:
                            return response
                        continue
                    if message.type in (
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.ERROR,
                    ):
                        raise ConnectionError(
                            f"sc2_api_websocket_closed:{message.type}:{getattr(message, 'data', '')}"
                        )
                    raise ConnectionError(f"sc2_api_non_binary_response:{message.type}")
                raise TimeoutError(f"timeout waiting for response to {request_name}")
            except (
                ConnectionError,
                asyncio.TimeoutError,
                TimeoutError,
                aiohttp.ClientError,
            ) as exc:
                if not retry_on_disconnect or time.monotonic() >= deadline:
                    if isinstance(exc, (ConnectionError, asyncio.TimeoutError, TimeoutError)):
                        raise LiveSc2Error(str(exc)) from exc
                    raise
                attempts += 1
                await self._close()
                await asyncio.sleep(min(self.reconnect_delay * min(attempts, 4), max(0.0, deadline - time.monotonic())))
                await self._connect_with_retry(timeout=min(15.0, max(0.1, deadline - time.monotonic())))

    async def _close(self) -> None:
        if self._websocket is not None:
            await self._websocket.close()
            self._websocket = None
        if self._session is not None:
            await self._session.close()
            self._session = None


class LiveRawSc2Session:
    """Create and drive one participant session through the raw SC2 API."""

    def __init__(
        self,
        map_path: str | Path,
        *,
        port: int,
        protocol_root: str | Path | None = None,
        player_name: str = "CMRE-RL-P1",
        computer_name: str = "CMRE-RL-Computer",
        computer_difficulty: int = DIFFICULTY_EASY,
        realtime: bool = False,
        progress_loop_limit: int = 100000,
        join_existing: bool = False,
        client: Sc2ApiClient | None = None,
    ) -> None:
        self.map_path = Path(map_path).resolve()
        if not self.map_path.is_file():
            raise FileNotFoundError(f"map_not_found:{self.map_path}")
        self.port = int(port)
        self.protocol_root = Path(protocol_root).resolve() if protocol_root else None
        self.player_name = str(player_name)
        self.computer_name = str(computer_name)
        self.computer_difficulty = int(computer_difficulty)
        self.realtime = bool(realtime)
        self.progress_loop_limit = max(1, int(progress_loop_limit))
        self.join_existing = bool(join_existing)
        self.client = client or Sc2ApiClient(self.port)
        self._sc_pb: Any = None
        self._raw_pb: Any = None
        self._common_pb: Any = None
        self._map_name = self.map_path.name
        self._player_id = 1
        self._last_observation: dict[str, Any] | None = None
        self._connected = False
        self._joined = False
        self.runtime_stats: dict[str, Any] = {
            "api_url": f"ws://127.0.0.1:{self.port}/sc2api",
            "create_game": False,
            "join_existing": self.join_existing,
            "join_game": False,
            "join_attempts": 0,
            "observations": 0,
            "request_steps": 0,
            "requested_step_loops": 0,
            "action_requests": 0,
            "action_results": [],
            "action_trace": [],
            "action_successes": 0,
            "action_errors": 0,
            "terminal_results": [],
            "save_replay": False,
            "replay_bytes": 0,
            "leave_game": False,
        }

    @property
    def player_id(self) -> int:
        return self._player_id

    def reset(self, map_name: str, player_id: int) -> Mapping[str, Any]:
        self._load_protocol()
        self._map_name = str(map_name) or self.map_path.name
        if not self._connected:
            self.client.connect()
            self._connected = True
        if not self.join_existing:
            map_data = self.map_path.read_bytes()
            create = self._sc_pb.Request(
                create_game=self._sc_pb.RequestCreateGame(
                    local_map=self._sc_pb.LocalMap(map_data=map_data),
                    player_setup=[
                        self._sc_pb.PlayerSetup(
                            type=PLAYER_PARTICIPANT,
                            race=RACE_TERRAN,
                            player_name=self.player_name,
                        ),
                        self._sc_pb.PlayerSetup(
                            type=PLAYER_COMPUTER,
                            race=RACE_TERRAN,
                            difficulty=self.computer_difficulty,
                            player_name=self.computer_name,
                        ),
                    ],
                    realtime=self.realtime,
                )
            )
            create_response = self.client.send(create, timeout=120.0)
            _raise_response_error(create_response, "CreateGame")
            self.runtime_stats["create_game"] = True

        join = self._sc_pb.Request(
            join_game=self._sc_pb.RequestJoinGame(
                race=RACE_TERRAN,
                options=self._sc_pb.InterfaceOptions(raw=True, score=True, show_cloaked=True),
            )
        )
        # DirectMapApi exposes the socket before the map's game state is ready.
        # JoinGame is safe to retry here; action requests deliberately are not.
        join_deadline = time.monotonic() + 120.0
        join_response: Any = None
        last_join_error: Exception | None = None
        while time.monotonic() < join_deadline:
            self.runtime_stats["join_attempts"] += 1
            remaining = max(1.0, join_deadline - time.monotonic())
            try:
                join_response = self.client.send(
                    join,
                    timeout=min(15.0, remaining),
                    retry_on_disconnect=True,
                )
                _raise_response_error(join_response, "JoinGame")
                break
            except LiveSc2Error as exc:
                last_join_error = exc
                time.sleep(min(0.5, max(0.0, join_deadline - time.monotonic())))
        else:
            raise LiveSc2Error(f"JoinGame_timeout:{last_join_error}") from last_join_error
        if join_response is None:
            raise LiveSc2Error(f"JoinGame_failed:{last_join_error}") from last_join_error
        self._player_id = int(join_response.join_game.player_id or player_id)
        self._joined = True
        self.runtime_stats["join_game"] = True
        return self.observe()

    def observe(self) -> Mapping[str, Any]:
        self._load_protocol()
        response = self.client.send(
            self._sc_pb.Request(observation=self._sc_pb.RequestObservation()),
            timeout=30.0,
        )
        _raise_response_error(response, "Observation")
        observation = parse_observation_response(
            response,
            player_id=self._player_id,
            map_name=self._map_name,
            progress_loop_limit=self.progress_loop_limit,
        )
        self._last_observation = observation
        self.runtime_stats["observations"] += 1
        self.runtime_stats["terminal_results"] = list(observation.get("player_result", []))
        action_trace = self.runtime_stats.get("action_trace", [])
        if action_trace and action_trace[-1].get("loop_after") is None:
            action_trace[-1]["loop_after"] = int(observation.get("loop", 0))
        return observation

    def dispatch(self, action_id: str, args: Mapping[str, Any]) -> Mapping[str, Any]:
        self._load_protocol()
        observation = self._last_observation or dict(self.observe())
        trace_entry: dict[str, Any] = {
            "decision_index": len(self.runtime_stats["action_trace"]),
            "action_id": str(action_id),
            "args": dict(args or {}),
            "loop_before": int(observation.get("loop", 0)),
            "loop_after": None,
        }
        self.runtime_stats["action_trace"].append(trace_entry)
        try:
            spec = build_raw_action_spec(
                action_id,
                args,
                list(observation.get("own_units", [])),
                observation=observation,
            )
            raw_action = build_raw_action(spec, self._raw_pb, self._common_pb)
        except RawActionError as exc:
            self.runtime_stats["action_errors"] += 1
            trace_entry.update({"translated": False, "success": False, "error": str(exc)})
            return {
                "success": False,
                "translated": False,
                "error": str(exc),
                "action_id": action_id,
            }

        response = self.client.send(
            self._sc_pb.Request(
                action=self._sc_pb.RequestAction(
                    actions=[wrap_raw_action(raw_action, self._sc_pb)]
                )
            ),
            timeout=30.0,
        )
        errors = list(response.error)
        results: list[int] = []
        if response.HasField("action"):
            results = [int(value) for value in response.action.result]
        success = not errors and bool(results) and all(value == ACTION_RESULT_SUCCESS for value in results)
        self.runtime_stats["action_requests"] += 1
        self.runtime_stats["action_results"].extend(results)
        if success:
            self.runtime_stats["action_successes"] += 1
        else:
            self.runtime_stats["action_errors"] += 1
        trace_entry.update({
            "translated": True,
            "success": success,
            "ability_id": spec.ability_id,
            "unit_tag": spec.unit_tag,
            "target_type": spec.target_type,
            "target_unit_tag": spec.target_unit_tag,
            "target_x": spec.target_x,
            "target_y": spec.target_y,
            "results": results,
            "errors": [str(error) for error in errors],
        })
        return {
            "success": success,
            "translated": True,
            "action_id": action_id,
            "ability_id": spec.ability_id,
            "unit_tag": spec.unit_tag,
            "target_type": spec.target_type,
            "target_unit_tag": spec.target_unit_tag,
            "target_x": spec.target_x,
            "target_y": spec.target_y,
            "results": results,
            "errors": [str(error) for error in errors],
        }

    def step(self, step_mul: int) -> None:
        self._load_protocol()
        count = int(step_mul)
        if count < 1:
            raise ValueError("step_mul must be >= 1")
        response = self.client.send(
            self._sc_pb.Request(step=self._sc_pb.RequestStep(count=count)),
            timeout=30.0,
        )
        _raise_response_error(response, "RequestStep")
        self.runtime_stats["request_steps"] += 1
        self.runtime_stats["requested_step_loops"] += count
        return None

    def save_replay(self) -> bytes:
        """Save the native SC2 replay while the session is still active."""

        self._load_protocol()
        response = self.client.send(
            self._sc_pb.Request(save_replay=self._sc_pb.RequestSaveReplay()),
            timeout=45.0,
        )
        _raise_response_error(response, "SaveReplay")
        data = bytes(response.save_replay.data)
        self.runtime_stats["save_replay"] = bool(data)
        self.runtime_stats["replay_bytes"] = len(data)
        if not data:
            raise LiveSc2Error("SaveReplay_empty")
        return data

    def leave(self) -> None:
        try:
            if self._connected and self._joined:
                response = self.client.send(
                    self._sc_pb.Request(leave_game=self._sc_pb.RequestLeaveGame()),
                    timeout=15.0,
                )
                self.runtime_stats["leave_game"] = not list(response.error)
        finally:
            self.client.close()
            self._connected = False
            self._joined = False

    close = leave

    def _load_protocol(self) -> None:
        if self._sc_pb is not None:
            return
        if self.protocol_root is not None and str(self.protocol_root) not in sys.path:
            sys.path.insert(0, str(self.protocol_root))
        try:
            from s2clientprotocol import common_pb2, raw_pb2, sc2api_pb2
        except ImportError as exc:
            raise LiveSc2Error(
                "s2clientprotocol is unavailable; pass protocol_root=reference/SC2-Neuro-API-Integration"
            ) from exc
        self._sc_pb = sc2api_pb2
        self._raw_pb = raw_pb2
        self._common_pb = common_pb2


def _raise_response_error(response: Any, operation: str) -> None:
    errors = list(getattr(response, "error", ()))
    if errors:
        details = list(getattr(response, "error_details", ()))
        suffix = f" details={details}" if details else ""
        raise LiveSc2Error(f"{operation}_failed:{errors}{suffix}")
    if operation == "JoinGame" and getattr(response, "HasField", None):
        try:
            has_join_response = bool(response.HasField("join_game"))
        except (TypeError, ValueError):
            has_join_response = False
        if has_join_response:
            join_response = response.join_game
            try:
                has_join_error = bool(join_response.HasField("error"))
            except (AttributeError, TypeError, ValueError):
                has_join_error = False
            if has_join_error:
                details = list(getattr(join_response, "error_details", ()))
                suffix = f" details={details}" if details else ""
                raise LiveSc2Error(
                    f"{operation}_failed:{join_response.error}{suffix}"
                )


def _entity_id(unit: Mapping[str, Any]) -> int:
    try:
        return int(unit.get("entity_id", unit.get("tag", 0)))
    except (TypeError, ValueError):
        return 0


def _unit_type(unit: Mapping[str, Any]) -> str:
    return unit_type_name(unit.get("unit_type_id", unit.get("unit_type_int", "")))


def _pick_actor(
    action_id: str,
    own_units: list[Mapping[str, Any]],
    args: Mapping[str, Any],
) -> Mapping[str, Any]:
    requested_ids = args.get("entity_ids", ())
    if isinstance(requested_ids, (list, tuple)):
        requested = {int(value) for value in requested_ids if str(value).isdigit()}
        for unit in own_units:
            if _entity_id(unit) in requested:
                return unit

    workers = [unit for unit in own_units if _unit_type(unit) in {"SCV", "Probe", "Drone"}]
    producers = [
        unit for unit in own_units
        if _unit_type(unit) in {
            "CommandCenter", "OrbitalCommand", "PlanetaryFortress", "Barracks",
            "Factory", "Starport", "EngineeringBay", "Armory", "GhostAcademy",
            "FusionCore", "BarracksTechLab", "FactoryTechLab", "StarportTechLab",
        }
    ]
    transports = [unit for unit in own_units if _unit_type(unit) in {"Medivac", "Bunker", "WarpPrism", "Overlord", "NydusWorm"}]
    combat = [
        unit for unit in own_units
        if _unit_type(unit) not in {
            "SCV", "Probe", "Drone", "CommandCenter", "OrbitalCommand", "PlanetaryFortress",
            "Barracks", "Factory", "Starport", "EngineeringBay", "Armory", "GhostAcademy",
            "FusionCore", "BarracksTechLab", "FactoryTechLab", "StarportTechLab", "Medivac",
            "SupplyDepot", "Refinery", "Bunker",
        }
    ]
    if action_id in {"gather_resources", "build_structure", "repair_units"} and workers:
        return workers[0]
    if action_id in {"produce_unit", "research_upgrade", "rally_producer"} and producers:
        return producers[0]
    if action_id in {"load_units", "unload_units"} and transports:
        return transports[0]
    return (combat or own_units)[0]


def _pick_target(action_id: str, observation: Mapping[str, Any] | None) -> int:
    if not isinstance(observation, Mapping):
        return 0
    if action_id == "gather_resources":
        values = observation.get("mineral_fields", ())
    elif action_id == "attack_units":
        values = observation.get("visible_enemies", ())
    else:
        values = observation.get("own_units", ())
    if isinstance(values, (list, tuple)):
        for value in values:
            if isinstance(value, Mapping):
                tag = _entity_id(value)
                if tag > 0:
                    return tag
    return 0


__all__ = [
    "ABILITY_IDS",
    "LiveRawSc2Session",
    "LiveSc2Error",
    "PLAYER_RESULT_NAMES",
    "RawActionError",
    "RawActionSpec",
    "Sc2ApiClient",
    "build_raw_action",
    "build_raw_action_spec",
    "parse_observation_response",
    "resolve_ability_and_target",
    "unit_type_name",
    "wrap_raw_action",
]
