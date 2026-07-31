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

# 复用 DefendBasePolicy（从 run_dead_of_night 动态提取，避免触发 simulator_session 依赖链）
# run_dead_of_night.py 顶部有 from .map_extractor / .simulator_session 相对导入，
# 直接 import 会失败。用 AST 提取 DefendBasePolicy/DefendAction 类定义。
import importlib.util as _ilu
import types as _types

_vibe_dir = Path(__file__).resolve().parent
_policy_mod = _types.ModuleType("_live_policy_extract")
_policy_mod.__dict__["__builtins__"] = __builtins__
# 注入 dataclass/maths 等依赖
for _mod_name in ("dataclasses", "math", "typing"):
    _policy_mod.__dict__[_mod_name] = __import__(_mod_name)
# dataclass 装饰器内部用 sys.modules.get(cls.__module__).__dict__ 检查类型，
# 必须把伪造的模块注册进 sys.modules 才能让 @dataclass 正常工作
sys.modules["_live_policy_extract"] = _policy_mod

_run_don_src = (_vibe_dir / "run_dead_of_night.py").read_text(encoding="utf-8")
# 提取从 "class DefendAction:" 到 "def run_dead_of_night(" 之间的代码
_start = _run_don_src.find("@dataclass\nclass DefendAction:")
_end = _run_don_src.find("\n\n# ---", _start)
if _start < 0:
    _start = _run_don_src.find("class DefendAction:")
if _end < 0:
    _end = _run_don_src.find("def run_dead_of_night(")
_policy_src = _run_don_src[_start:_end]
# 需要的导入 + DefendBasePolicy 默认参数依赖的常量（来自 run_dead_of_night.py 顶部）
_policy_src_pre = """
from dataclasses import dataclass, field
from typing import Optional
import math

PLAYER_BASE_X = 85.0
PLAYER_BASE_Y = 94.0
"""
exec(_policy_src_pre + _policy_src, _policy_mod.__dict__)
DefendAction = _policy_mod.DefendAction
DefendBasePolicy = _policy_mod.DefendBasePolicy

# 默认地图（已验证可加载，3MB 打包版）
DEFAULT_MAP = r"E:\SC2\SC2new\StarCraft II\Maps\亡者之夜_p0_default_packed.SC2Map"
PLAYER_ID = 1


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


def _unit_brief_from_sc2(u, player_id: int) -> Optional[dict]:
    """把 SC2 API 的 Unit 转成 vibe _entity_brief 格式。

    返回 None 表示该单位应被跳过（如中立非战斗单位）。
    """
    unit_type_int = u.unit_type
    unit_type_name = INT_TO_NAME.get(unit_type_int, str(unit_type_int))
    # SC2 的 pos 是 {x, y, z}，世界单位 float
    x = u.pos.x if u.HasField("pos") else 0.0
    y = u.pos.y if u.HasField("pos") else 0.0
    return {
        "entity_id": u.tag,  # SC2 用 tag 作为单位唯一标识
        "unit_type_id": unit_type_name,
        "owner": u.owner,
        "x": x,
        "y": y,
        "health": int(u.health * 1024) if u.health else 0,  # vibe 用 raw int（×1024）
        "shields": int(u.shield * 1024) if u.shield else 0,
        "energy": int(u.energy * 1024) if u.energy else 0,
        "state": "",
        "max_health": int(u.health_max * 1024) if u.health_max else 0,
    }


def build_observation(resp: sc_pb.Response, player_id: int) -> LiveObservation:
    """从 SC2 Observation 响应构造 vibe Observation。"""
    obs = resp.observation.observation
    game_loop = obs.game_loop
    pc = obs.player_common
    raw = obs.raw_data

    own_units: list[dict] = []
    visible_enemies: list[dict] = []
    if raw is not None:
        for u in raw.units:
            brief = _unit_brief_from_sc2(u, player_id)
            if brief is None:
                continue
            if u.owner == player_id:
                own_units.append(brief)
            elif u.owner != 0 and u.alliance == 4:  # 4 = Enemy
                visible_enemies.append(brief)
            # alliance: 1=Self, 2=Ally, 4=Enemy, 3=Neutral
            elif u.owner != 0 and u.alliance in (3, 4):
                visible_enemies.append(brief)

    resources = {
        "minerals": pc.minerals if pc else 0,
        "vespene": pc.vespene if pc else 0,
        "supply_used": int(pc.food_used) if pc else 0,
        "supply_cap": int(pc.food_cap) if pc else 0,
    }

    return LiveObservation(
        loop=game_loop,
        player_id=player_id,
        own_units=own_units,
        visible_enemies=visible_enemies,
        resources=resources,
        mission={"win_condition": "live_sc2"},
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


def build_action(a: DefendAction, player_id: int) -> Optional[sc_pb.Action]:
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
        cmd.ability_id = _ability_id("MOVE") or 16  # 16 = Move default
        tp = cmd.target_world_space_pos
        tp.x = a.target_x
        tp.y = a.target_y
    elif a.kind == "gather":
        if a.target_entity_id == 0:
            return None
        cmd.ability_id = _ability_id("SMART") or 2  # 2 = Smart (right-click)
        cmd.target_unit_tag = a.target_entity_id
    elif a.kind == "train":
        # train 需要 ability_id（如 TRAIN_MARINE=560）
        # 简化：用 SMART 替代（无法真正训练，但验证闭环）
        # 完整实现需要 unit_type → train_ability 映射
        ability_name = f"TRAIN_{a.unit_type_id.upper()}"
        aid = _ability_id(ability_name)
        if aid == 0:
            return None  # 找不到训练能力，跳过
        cmd.ability_id = aid
    elif a.kind == "build":
        ability_name = f"BUILD_{a.unit_type_id.upper()}"
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
    replay_log_path: str = ""


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

    frame = {
        "loop": loop,
        "ts_sec": round(loop / 22.4, 1),
        "p1_alive": len(obs.own_units),
        "enemy_alive": len(obs.visible_enemies),
        "p1_units_by_type": p1_units_by_type,
        "enemy_units_by_type": enemy_units_by_type,
        "p1_resources": obs.resources,
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
    """
    start_time = time.time()
    conn = Sc2Connection(port)
    await conn.connect()
    cmd_ok_stats: Counter = Counter()
    cmd_fail_stats: Counter = Counter()
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
    map_name = os.path.basename(map_path)
    player_id = PLAYER_ID
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
        local_map = sc_pb.LocalMap(map_path=map_path.replace('\\', '/'))
        req = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=local_map,
            player_setup=[
                sc_pb.PlayerSetup(type=1, race=1, player_name="P1"),  # Terran Participant
                sc_pb.PlayerSetup(type=2, race=1, difficulty=2, player_name="AI"),  # Terran Computer
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
        if verbose:
            print(f"  JoinGame OK! player_id={player_id}")

        # 等 15s 让 galaxy 脚本初始化（参考 RealProfile：15s 等待）
        if verbose:
            print("  等 15s 让 galaxy 脚本初始化...")
        await asyncio.sleep(15)

        # 5. GameInfo（获取地图名）
        r = await conn.send_request(sc_pb.Request(game_info=sc_pb.RequestGameInfo()), timeout=15)
        map_name = r.game_info.map_name or os.path.basename(map_path)
        if verbose:
            print(f"[5] Map: {map_name}")

        # 6. 玩家 AI 策略
        policy = DefendBasePolicy(player_id=player_id, command_interval=decision_interval)

        # 7. 主循环
        if verbose:
            print(f"[6] 运行对局 (max_loops={max_loops}, step_size={step_size})...")
        last_decide_loop = -10_000
        last_replay_loop = -10_000
        report_interval = max(50, max_loops // 20)
        last_report_loop = 0
        current_loop = 0
        consecutive_failures = 0
        max_consecutive_failures = 5

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
            current_loop = obs.loop

            # 检查游戏是否结束
            if r.observation.player_result:
                results = {pr.player_id: pr.result for pr in r.observation.player_result}
                if verbose:
                    print(f"  游戏结束: {results}")
                break

            # 决策
            if current_loop - last_decide_loop >= decision_interval:
                last_decide_loop = current_loop
                actions = policy.decide(obs, current_loop, resources=obs.resources)
                total_commands_issued += len(actions)

                # 收集 action 并批量发送
                sc2_actions: list[sc_pb.Action] = []
                for a in actions:
                    if a.kind == "hold":
                        continue
                    action = build_action(a, player_id)
                    if action is not None:
                        sc2_actions.append(action)
                        total_commands_dispatched += 1
                    else:
                        cmd_fail_stats[f"{a.kind}:no_action"] += 1

                if sc2_actions:
                    try:
                        action_req = sc_pb.Request(action=sc_pb.RequestAction(
                            actions=sc2_actions))
                        ar = await conn.send_request(action_req, timeout=10)
                        # 统计结果
                        for result in ar.action.result:
                            if result == 0:  # SUCCESS
                                cmd_ok_stats["dispatched"] += 1
                            else:
                                cmd_fail_stats[f"sc2_result:{result}"] += 1
                    except (ConnectionError, TimeoutError) as e:
                        if verbose:
                            print(f"  Action send failed: {e}")
                        cmd_fail_stats["action_send_exception"] += 1

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
    p1_survivors = len(final_obs.own_units) if final_obs is not None else 0
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
        replay_log_path=str(replay_path),
    )

    if verbose:
        print(f"\n=== 真机对局结束 ===")
        print(f"地图: {report.map_name}")
        print(f"结果: {report.verdict.upper()}")
        print(f"Loop: {report.end_loop}/{max_loops} ({report.end_loop/max_loops:.0%})")
        print(f"耗时: {report.duration_sec}s")
        print(f"Player 1 幸存: {report.player1_survivors}")
        print(f"敌方幸存: {report.enemy_survivors}")
        print(f"命令下发: {report.total_commands_issued}")
        print(f"命令执行: {report.total_commands_dispatched}")
        print(f"命令成功: {report.cmd_ok_stats}")
        print(f"命令失败: {report.cmd_fail_stats}")
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
    ))

    if args.output:
        report_path = Path(args.output)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_data = {k: v for k, v in report.__dict__.items()}
        report_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n报告已写入: {report_path}")

    return 0 if report.verdict == "victory" else 1


if __name__ == "__main__":
    sys.exit(main())
