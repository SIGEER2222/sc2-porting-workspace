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
import ctypes
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from ctypes import wintypes
import xml.etree.ElementTree as ET

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
    from .consumers.ally_ai import AllyAction, AllyPolicy
    from .strategy_audit import audit_native_strategy
    from .map_source import MapSource, read_map_source, resolve_map_source
    from .p1_ml import load_checkpoint as load_p1_action_model
except ImportError:
    # Support the documented direct-script invocation as well as package imports.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from defend_policy import DefendAction, DefendBasePolicy  # type: ignore
    # ally_ai uses package-relative imports, so retain the project root on
    # sys.path and import it through the ``vibe`` package in direct mode.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from vibe.consumers.ally_ai import AllyAction, AllyPolicy  # type: ignore
    from strategy_audit import audit_native_strategy  # type: ignore
    from vibe.map_source import MapSource, read_map_source, resolve_map_source  # type: ignore
    from vibe.p1_ml import load_checkpoint as load_p1_action_model  # type: ignore

# 默认地图（已验证可加载，3MB 打包版）
DEFAULT_MAP = r"E:\SC2\SC2new\StarCraft II\Maps\亡者之夜_p0_default_packed.SC2Map"
P1_PLAYER_ID = 1
P2_PLAYER_ID = 2
PLAYER_ID = P1_PLAYER_ID
PLAYER_TYPE_PARTICIPANT = 1
PLAYER_TYPE_COMPUTER = 2
# SC2 requires every participant in a local multiplayer game to submit the
# same server/client port topology during JoinGame. The client port pair is
# the guest slot in the shared Portconfig; it is not private to one API
# websocket.
MULTIPLAYER_PORT_BASE = 5200


def _sc2_process_id_for_api_port(port: int) -> Optional[int]:
    """Resolve the SC2 process that owns the matrix-controlled API port."""
    if os.name != "nt" or port <= 0:
        return None
    command = (
        "(Get-NetTCPConnection -LocalAddress '127.0.0.1' "
        f"-LocalPort {int(port)} -State Listen -ErrorAction SilentlyContinue "
        "| Select-Object -First 1 -ExpandProperty OwningProcess)"
    )
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        return int(completed.stdout.strip())
    except (TypeError, ValueError):
        return None


def _sc2_window_for_process(process_id: int) -> Optional[int]:
    """Find the top-level SC2 render window without assuming its title."""
    if os.name != "nt" or process_id <= 0:
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int
    candidates: list[tuple[int, int]] = []

    def visit(hwnd: int, _lparam: int) -> bool:
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == process_id and user32.IsWindowVisible(hwnd):
            class_name = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, class_name, len(class_name))
            normalized_class = class_name.value.casefold()
            # SC2 exposes both a localized wrapper and the actual D3D render
            # window. Global keyboard/mouse input is consumed by the latter.
            score = 100 if normalized_class == "d3dproxywindow" else 50
            candidates.append((score, int(hwnd)))
        return True

    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _send_reborn_loading_confirm(port: int, *, verbose: bool = False) -> bool:
    """Dismiss Reborn's native pre-Join loading confirmation once."""
    if os.name != "nt":
        return False
    process_id = _sc2_process_id_for_api_port(port)
    if process_id is None:
        if verbose:
            print("  Reborn confirm: SC2 API process not found", flush=True)
        return False
    hwnd = _sc2_window_for_process(process_id)
    if hwnd is None:
        if verbose:
            print(f"  Reborn confirm: window not found for SC2 PID={process_id}", flush=True)
        return False

    class _KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("wVk", wintypes.WORD),
            ("wScan", wintypes.WORD),
            ("dwFlags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("dwExtraInfo", ctypes.c_void_p),
        ]

    class _Input(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("ki", _KeyboardInput)]

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.GetForegroundWindow.restype = wintypes.HWND
    class _Rect(ctypes.Structure):
        _fields_ = [
            ("left", wintypes.LONG),
            ("top", wintypes.LONG),
            ("right", wintypes.LONG),
            ("bottom", wintypes.LONG),
        ]

    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(_Rect)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    user32.PostMessageW.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.keybd_event.argtypes = [
        wintypes.BYTE,
        wintypes.BYTE,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]

    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.BringWindowToTop(hwnd)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.25)
    if user32.GetForegroundWindow() != hwnd:
        if verbose:
            print(
                "  Reborn confirm: SC2 window did not become foreground; "
                "continuing targeted click",
                flush=True,
            )

    clicked = False
    rect = _Rect()
    if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        width = max(1, int(rect.right - rect.left))
        height = max(1, int(rect.bottom - rect.top))
        click_x = int(rect.left + width / 2)
        click_y = int(rect.top + height * 0.95)
        client_x = width // 2
        client_y = int(height * 0.95)
        lparam = (client_y << 16) | (client_x & 0xFFFF)
        posted_down = bool(user32.PostMessageW(hwnd, 0x0201, 1, lparam))
        posted_up = bool(user32.PostMessageW(hwnd, 0x0202, 0, lparam))
        positioned = bool(user32.SetCursorPos(click_x, click_y))
        if positioned:
            user32.mouse_event(0x0002, 0, 0, 0, None)  # MOUSEEVENTF_LEFTDOWN
            user32.mouse_event(0x0004, 0, 0, 0, None)  # MOUSEEVENTF_LEFTUP
        if posted_down or posted_up or positioned:
            clicked = True
            if verbose:
                print(
                    f"  Reborn confirm: clicked continuation strip at x={click_x} y={click_y} "
                    f"for SC2 PID={process_id}",
                    flush=True,
                )

    posted_keys: list[int] = []
    sent_keys: list[int] = []
    for virtual_key in (0x0D, 0x20):
        posted_down = bool(user32.PostMessageW(hwnd, 0x0100, virtual_key, 0))
        posted_up = bool(user32.PostMessageW(hwnd, 0x0101, virtual_key, 0))
        if posted_down or posted_up:
            posted_keys.append(virtual_key)
        key_down = _Input(type=1, ki=_KeyboardInput(wVk=virtual_key))
        key_up = _Input(type=1, ki=_KeyboardInput(wVk=virtual_key, dwFlags=0x0002))
        inputs = (_Input * 2)(key_down, key_up)
        sent = int(user32.SendInput(2, inputs, ctypes.sizeof(_Input)))
        if sent == 2:
            sent_keys.append(virtual_key)
        else:
            user32.keybd_event(virtual_key, 0, 0, None)
            time.sleep(0.06)
            user32.keybd_event(virtual_key, 0, 0x0002, None)
    if verbose:
        print(
            f"  Reborn confirm: targeted hwnd={hwnd}, posted_keys={posted_keys}, "
            f"sent_keys={sent_keys}",
            flush=True,
        )
    return clicked or bool(posted_keys) or bool(sent_keys)


def _multiplayer_port_topology(
    base_port: int,
) -> tuple[tuple[int, int], tuple[tuple[int, int], ...]]:
    """Return one shared host/guest Portconfig for a 1v1 match."""
    if base_port < 1024 or base_port + 3 > 65535:
        raise ValueError(f"invalid multiplayer port base: {base_port}")
    return (base_port, base_port + 1), ((base_port + 2, base_port + 3),)
LIVE_MAP_METADATA = {
    "source_kind": "runtime_observation_with_map_source_metadata",
    "map_name": "亡者之夜",
    "map_path": "src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map",
    "map_hash": "3b46e6afdfe4664e1ccc2f49c973331f66746425fa36832a00f5680c056ed322",
    "map_bounds": {
        "width": 144.0,
        "height": 151.0,
        "min_x": 27.5,
        "min_y": 15.5,
        "max_x": 171.5,
        "max_y": 166.5,
    },
    "native_object_count": 1319,
    "native_spawn_count": 1308,
    "native_p2_spawn_count": 0,
}


def _resolve_runtime_map_metadata(map_path: str, runtime_map_name: str) -> dict:
    """Resolve runtime replay metadata from the matching unpacked CMRE map."""

    metadata = dict(LIVE_MAP_METADATA)
    metadata["runtime_observation_source"] = "sc2api"
    metadata["runtime_game_info_map_name"] = runtime_map_name
    metadata["runtime_input_map_path"] = str(map_path)
    try:
        from .cmre_map_catalog import build_cooperative_map_scenario, list_cmre_maps

        label = runtime_map_name
        if label.startswith("[CM] "):
            label = label[5:]
        source_map = next(
            (
                candidate
                for candidate in list_cmre_maps()
                if candidate.stem == label
                or candidate.name == label
                or candidate.stem.startswith(label)
            ),
            None,
        )
        if source_map is None:
            raise FileNotFoundError(f"CMRE source map not found for runtime map {runtime_map_name!r}")
        data, _, _ = build_cooperative_map_scenario(source_map, max_enemy_per_player=1)
        metadata = dict(data.scenario["_map_metadata"])
        metadata["runtime_observation_source"] = "sc2api"
        metadata["runtime_game_info_map_name"] = runtime_map_name
        metadata["runtime_input_map_path"] = str(map_path)
        metadata["runtime_source_map_resolved"] = True
    except Exception as exc:
        metadata["runtime_source_map_resolved"] = False
        metadata["runtime_metadata_resolution_error"] = f"{type(exc).__name__}: {exc}"
    return metadata


def _write_live_replay_header(
    replay_fp,
    metadata: dict,
    computer_ally: bool,
    map_source_audit: Optional[dict] = None,
    mode_model_summary: Optional[dict] = None,
    p1_model_summary: Optional[dict] = None,
) -> None:
    replay_fp.write(json.dumps({
        "record_type": "header",
        "schema_version": "live-runtime-v1",
        "map_metadata": metadata,
        "owner_roles": {
            "1": {"relation": "leader", "name": "P1 玩家"},
            "2": {"relation": "ally", "name": "P2 AI 盟友"},
            "3": {"relation": "enemy", "name": "P3 敌军"},
            "4": {"relation": "enemy", "name": "P4 敌军"},
            "5": {"relation": "enemy", "name": "P5 敌军"},
            "6": {"relation": "enemy", "name": "P6 敌军"},
            "7": {"relation": "enemy", "name": "P7 敌军"},
        },
        "strategy_player_id": P1_PLAYER_ID if computer_ally else P2_PLAYER_ID,
        "runtime_topology": (
            "single_client_p1_participant_p2_computer"
            if computer_ally else "dual_participant_legacy_probe"
        ),
        "native_strategy": not computer_ally,
        "native_computer_ally": computer_ally,
        "debug_injection": False,
        "map_source_audit": map_source_audit or {
            "status": "not_resolved",
            "evidence_type": "blocked",
        },
        "mode_model": mode_model_summary or {
            "enabled": False,
            "evidence_type": "inference",
        },
        "p1_model": p1_model_summary or {
            "enabled": False,
            "evidence_type": "inference",
        },
    }, ensure_ascii=False) + "\n")
    replay_fp.flush()


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
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(sock_connect=15, sock_read=60)
        )
        self._ws = await self._session.ws_connect(
            f"ws://127.0.0.1:{self.port}/sc2api",
            max_msg_size=0,
            timeout=aiohttp.ClientWSTimeout(ws_close=30),
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
    session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(sock_connect=15, sock_read=60)
    )
    ws = await session.ws_connect(
        f"ws://127.0.0.1:{port}/sc2api",
        max_msg_size=0,
        timeout=aiohttp.ClientWSTimeout(ws_close=30),
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
    vespene_geysers: list[dict] = field(default_factory=list)  # 中立气矿单位


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
        "build_progress": float(getattr(u, "build_progress", 1.0)),
        "orders": [
            {
                "ability_id": int(order.ability_id),
                "progress": float(order.progress),
                "target_unit_tag": int(getattr(order, "target_unit_tag", 0)),
            }
            for order in getattr(u, "orders", ())
        ],
        "is_idle": not bool(getattr(u, "orders", ())),
    }


async def _advance_non_realtime_startup(
    conn: Sc2Connection,
    *,
    verbose: bool = True,
    max_attempts: int = 120,
) -> None:
    """Drive the first playable frames before reading GameInfo.

    ``realtime=False`` does not advance the SC2 simulation while the client
    sleeps. Map InitMap/startup triggers therefore need RequestStep calls here;
    wall-clock waiting alone can leave the staged map at its static placement
    markers with no mission-owned units or AI startup executed.
    """
    last_error = ""
    for attempt in range(max_attempts):
        try:
            step_response = await conn.send_request(
                sc_pb.Request(step=sc_pb.RequestStep(count=1)),
                timeout=15,
            )
            if step_response.error:
                last_error = ", ".join(str(error) for error in step_response.error)
            else:
                observation_response = await conn.send_request(
                    sc_pb.Request(observation=sc_pb.RequestObservation()),
                    timeout=15,
                )
                if not observation_response.error:
                    game_loop = observation_response.observation.observation.game_loop
                    if game_loop > 0:
                        if verbose:
                            print(
                                f"  Startup frames advanced with RequestStep: loop={game_loop}"
                            )
                        return
                    last_error = "observation game_loop remained 0"
                else:
                    last_error = ", ".join(
                        str(error) for error in observation_response.error
                    )
        except (ConnectionError, TimeoutError, asyncio.TimeoutError) as exc:
            last_error = str(exc)
        await asyncio.sleep(0.25)
    raise RuntimeError(
        "non-realtime SC2 startup did not advance a playable frame after "
        f"{max_attempts} RequestStep attempts: {last_error}"
    )


# The live API exposes catalog names in the enum spelling (for example
# MARINE), while project policies use the map-extractor spelling (Marine).
_LIVE_UNIT_NAME_ALIASES = {
    "COMMANDCENTER": "CommandCenter",
    "NEXUS": "Nexus",
    "HATCHERY": "Hatchery",
    "LAIR": "Lair",
    "HIVE": "Hive",
    "SUPPLYDEPOT": "SupplyDepot",
    "REFINERY": "Refinery",
    "BARRACKS": "Barracks",
    "ENGINEERINGBAY": "EngineeringBay",
    "MISSILETURRET": "MissileTurret",
    "BUNKER": "Bunker",
    "FACTORY": "Factory",
    "STARPORT": "Starport",
    "SCV": "SCV",
    "PROBE": "Probe",
    "DRONE": "Drone",
    "OVERLORD": "Overlord",
    "LARVA": "Larva",
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
    "PYLON": "Pylon",
    "GATEWAY": "Gateway",
    "WARPGATE": "WarpGate",
    "SPAWNINGPOOL": "SpawningPool",
    "EXTRACTOR": "Extractor",
    "ASSIMILATOR": "Assimilator",
    "QUEEN": "Queen",
    "ZERGLING": "Zergling",
    "ROACH": "Roach",
    "HYDRALISK": "Hydralisk",
    "MUTALISK": "Mutalisk",
    "ZEALOT": "Zealot",
    "STALKER": "Stalker",
    "IMMORTAL": "Immortal",
    "MINERALFIELD": "MineralField",
    "VESPENEGEYSER": "VespeneGeyser",
    "SPACEPLATFORMGEYSER": "VespeneGeyser",
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
    vespene_geysers: list[dict] = []
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
            elif (u.alliance == 3
                  and brief["unit_type_id"] == "VespeneGeyser"):
                vespene_geysers.append(brief)

    resources = {
        "minerals": pc.minerals if pc else 0,
        "vespene": pc.vespene if pc else 0,
        "supply_used": int(pc.food_used) if pc else 0,
        "supply_cap": int(pc.food_cap) if pc else 0,
        # A live observation is versioned by the SC2 game loop. This is the
        # stale-snapshot guard consumed by the typed P2 intent contract.
        "state_version": int(game_loop),
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
        vespene_geysers=vespene_geysers,
    )


P1_TOWN_HALL_TYPES = frozenset({
    "CommandCenter", "OrbitalCommand", "PlanetaryFortress",
    "Nexus", "Hatchery", "Lair", "Hive", "GreaterSpire",
})


def _valid_map_position(x: float, y: float, source: Optional[MapSource]) -> bool:
    """Reject zero/off-map catalog objects before using them as a rally point."""
    if not math.isfinite(x) or not math.isfinite(y) or (x == 0.0 and y == 0.0):
        return False
    if source is None:
        return True
    bounds = source.map_bounds
    return (
        float(bounds.get("min_x", -math.inf)) - 5.0 <= x <= float(bounds.get("max_x", math.inf)) + 5.0
        and float(bounds.get("min_y", -math.inf)) - 5.0 <= y <= float(bounds.get("max_y", math.inf)) + 5.0
    )


def _map_spawn_position(source: Optional[MapSource], player_id: int) -> Optional[tuple[float, float]]:
    if source is None:
        return None
    markers = [
        unit for unit in source.object_units
        if unit.get("unit_type") == "ACHeroSpawnPlacement"
        and int(unit.get("player", 0)) == player_id
    ]
    if not markers:
        return None
    position = markers[0].get("position", {})
    x = float(position.get("x", 0.0))
    y = float(position.get("y", 0.0))
    return (x, y) if _valid_map_position(x, y, source) else None


def resolve_p1_base_region(
    observation: LiveObservation,
    source: Optional[MapSource],
    fallback: tuple[float, float, float],
) -> tuple[float, float, float]:
    """Resolve P1's actual map-side base without trusting invalid custom units.

    CMRE commander adapters replace vanilla town halls with custom catalog
    objects.  The raw API may expose those objects as numeric IDs, and some
    transient mission objects report position ``(0, 0)``.  Prefer a valid
    observed town hall near the source-map P1 placement marker, then fall back
    to the marker itself.  This keeps rally/build decisions inside the map's
    real playable bounds.
    """
    marker = _map_spawn_position(source, P1_PLAYER_ID)
    anchor = marker or (float(fallback[0]), float(fallback[1]))
    candidates = [
        unit for unit in observation.own_units
        if str(unit.get("unit_type_id", "")) in P1_TOWN_HALL_TYPES
        and _valid_map_position(float(unit.get("x", 0.0)), float(unit.get("y", 0.0)), source)
    ]
    if not candidates:
        # Custom commander town halls are generally the only high-health
        # structures close to the source placement marker.  The explicit
        # threshold excludes workers/army while still accepting custom IDs.
        candidates = [
            unit for unit in observation.own_units
            if float(unit.get("max_health", 0.0)) >= 500_000.0
            and _valid_map_position(float(unit.get("x", 0.0)), float(unit.get("y", 0.0)), source)
        ]
    if candidates:
        base = min(
            candidates,
            key=lambda unit: math.hypot(
                float(unit.get("x", 0.0)) - anchor[0],
                float(unit.get("y", 0.0)) - anchor[1],
            ),
        )
        return (float(base["x"]), float(base["y"]), float(fallback[2]))
    if marker is not None:
        return (marker[0], marker[1], float(fallback[2]))
    return fallback


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


RuntimeAbilityCatalog = dict[tuple[str, int], int]


async def fetch_runtime_ability_catalog(
    conn: Sc2Connection,
    *,
    verbose: bool = False,
) -> RuntimeAbilityCatalog:
    """Read the active map/mod ability IDs from SC2's runtime Catalog."""
    response = await conn.send_request(
        sc_pb.Request(data=sc_pb.RequestData(ability_id=True)),
        timeout=30,
    )
    if response.error:
        raise RuntimeError(
            "runtime ability catalog request failed: "
            + ", ".join(str(error) for error in response.error)
        )
    catalog = {
        (str(ability.link_name), int(ability.link_index)): int(ability.ability_id)
        for ability in response.data.abilities
    }
    if verbose:
        print(f"  Runtime Catalog: abilities={len(catalog)}")
    return catalog


EMPIRE_BUILD_COMMANDS: dict[str, tuple[str, int]] = {
    "CommandCenter": ("3jianzao1", 0),
    "Barracks": ("3jianzao1", 3),
    "Factory": ("3jianzao1", 10),
    "Starport": ("3jianzao1", 11),
}


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
    runtime_ability_catalog: Optional[RuntimeAbilityCatalog] = None,
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
            (
                runtime_ability_catalog.get(("3xunlian1", 0), 0)
                if runtime_ability_catalog is not None
                else 17443
            )
            if source_unit_type_int == 4390 and a.unit_type_id == "SCV"
            else _ability_id(ability_name)
        )
        if aid == 0:
            return None  # ability_id 解析失败（ability_id.py 缺该条目）
        cmd.ability_id = aid
    elif a.kind == "build":
        custom_command = (
            EMPIRE_BUILD_COMMANDS.get(a.unit_type_id)
            if source_unit_type_int == 4382 and runtime_ability_catalog is not None
            else None
        )
        if custom_command is not None:
            aid = runtime_ability_catalog.get(custom_command, 0)
        else:
            ability_name = BUILD_ABILITY_MAP.get(a.unit_type_id, "")
            if not ability_name:
                return None
            aid = _ability_id(ability_name)
        if aid == 0:
            return None
        cmd.ability_id = aid
        if a.unit_type_id == "Refinery" and a.target_entity_id:
            cmd.target_unit_tag = a.target_entity_id
        else:
            tp = cmd.target_world_space_pos
            tp.x = a.target_x
            tp.y = a.target_y
    else:
        return None

    action = sc_pb.Action(action_raw=raw_pb.ActionRaw(unit_command=cmd))
    return action


class MapDrivenP1Policy:
    """Drive the real P1 slot from the unpacked map's objective contract.

    The policy delegates economy and production to the existing typed policy,
    then replaces idle combat orders with movement toward the exact
    ``ObjectPoint`` selected by ``MapScript.galaxy``.  Once a real shard is
    visible, it attacks the observed SC2 unit tag.  It never creates, removes,
    teleports, or mutates a unit/resource state.
    """

    def __init__(
        self,
        source: MapSource,
        base_region: tuple[float, float, float],
        command_interval: int,
        action_model: Optional[object] = None,
        action_model_summary: Optional[dict] = None,
    ) -> None:
        self.source = source
        self.economy = DefendBasePolicy(
            player_id=P1_PLAYER_ID,
            base_region=base_region,
            command_interval=command_interval,
        )
        self.objective_trace: list[dict] = []
        self._last_objective_key = ""
        self.action_model = action_model
        self.action_model_summary = dict(action_model_summary or {})
        self.ml_decision_trace: list[dict] = []
        self.ml_decision_count = 0
        # Some commander adapters already assign every worker a native gather
        # order before the first API observation. Keep one explicit, map-
        # anchored gather for the P1 runtime contract without reissuing it on
        # every decision tick.
        self._opening_gather_issued = False

    def _infer_worker_ids(self, obs: LiveObservation) -> set[int]:
        """Identify commander-replaced workers from public observation state."""
        worker_ids = {
            int(unit["entity_id"])
            for unit in obs.own_units
            if str(unit.get("unit_type_id", "")) in DefendBasePolicy.WORKER_TYPES
        }
        unknown_by_type: Counter[str] = Counter(
            str(unit.get("unit_type_id", ""))
            for unit in obs.own_units
            if str(unit.get("unit_type_id", "")).isdigit()
        )
        for unit in obs.own_units:
            unit_type = str(unit.get("unit_type_id", ""))
            if not unit_type.isdigit() or unit_type in DefendBasePolicy.BUILDING_TYPES:
                continue
            x = float(unit.get("x", 0.0))
            y = float(unit.get("y", 0.0))
            if not _valid_map_position(x, y, self.source):
                continue
            repeated = unknown_by_type[unit_type] >= 6
            mineral_order = any(
                int(order.get("target_unit_tag", 0)) in {
                    int(field.get("entity_id", 0)) for field in obs.mineral_fields
                }
                for order in unit.get("orders", ())
            )
            if _valid_map_position(x, y, self.source) and (repeated or mineral_order):
                worker_ids.add(int(unit["entity_id"]))
        return worker_ids

    @staticmethod
    def _is_combat(unit: dict) -> bool:
        unit_type = str(unit.get("unit_type_id", ""))
        return unit_type not in (
            DefendBasePolicy.WORKER_TYPES
            | DefendBasePolicy.BUILDING_TYPES
            | set(DefendBasePolicy.PRODUCER_TYPES)
            | DefendBasePolicy.NON_COMBAT_TYPES
        )

    def _stage_for_loop(self, loop: int) -> Optional[dict]:
        stages = self.source.script.get("stages", [])
        elapsed = float(loop) / 22.4
        for stage in stages:
            if stage.get("spawn_seconds") is not None and elapsed <= float(stage["spawn_seconds"]):
                return stage
        return stages[-1] if stages else None

    def decide(self, obs: LiveObservation, loop: int, resources: dict) -> list[DefendAction]:
        actions = self.economy.decide(obs, loop, resources=resources)
        worker_ids = self._infer_worker_ids(obs)
        # The shared economy policy is intentionally conservative and does not
        # know every commander replacement catalog.  Remove tactical actions
        # for custom workers before they can be mistaken for combat units.
        actions = [
            action for action in actions
            if not (
                int(action.entity_id) in worker_ids
                and action.kind in {"hold", "move", "attack"}
            )
            and not (
                action.kind == "gather"
                and int(action.target_entity_id) == 0
            )
            and action.kind not in {"build", "train", "research"}
        ]
        opening_gather_added = False
        if not self._opening_gather_issued:
            opening_mineral = min(
                obs.mineral_fields,
                key=lambda item: math.hypot(
                    float(item.get("x", 0.0)) - self.economy.base_x,
                    float(item.get("y", 0.0)) - self.economy.base_y,
                ),
                default=None,
            )
            opening_worker = next(
                (
                    unit for unit in obs.own_units
                    if int(unit.get("entity_id", 0)) in worker_ids
                ),
                None,
            )
            if opening_mineral is not None and opening_worker is not None:
                actions.append(DefendAction(
                    entity_id=int(opening_worker["entity_id"]),
                    kind="gather",
                    target_entity_id=int(opening_mineral["entity_id"]),
                    reason="map_worker_explicit_opening_gather",
                ))
                self._opening_gather_issued = True
                opening_gather_added = True
        own_by_id = {int(unit["entity_id"]): unit for unit in obs.own_units}
        combat_ids = {
            int(unit["entity_id"])
            for unit in obs.own_units
            if (
                self._is_combat(unit)
                and int(unit["entity_id"]) not in worker_ids
                and _valid_map_position(
                    float(unit.get("x", 0.0)),
                    float(unit.get("y", 0.0)),
                    self.source,
                )
            )
        }
        model_label = ""
        model_prediction: dict = {}
        if self.action_model is not None:
            decision_id = f"p1-ml:{int(loop)}:{len(self.ml_decision_trace) + 1}"
            prediction = self.action_model.predict_action(
                obs,
                decision_id=decision_id,
                player_id=P1_PLAYER_ID,
            )
            if hasattr(prediction, "to_dict"):
                model_prediction = dict(prediction.to_dict())
            elif isinstance(prediction, dict):
                model_prediction = dict(prediction)
            else:
                model_prediction = {
                    "label": str(getattr(prediction, "label", "unknown")),
                    "confidence": float(getattr(prediction, "confidence", 0.0)),
                    "probabilities": dict(getattr(prediction, "probabilities", {})),
                }
            model_label = str(model_prediction.get("label", "unknown"))
            self.ml_decision_count += 1
            self.ml_decision_trace.append({
                "loop": int(loop),
                "decision_id": decision_id,
                "issuer_player_id": P1_PLAYER_ID,
                "source": "p1_supervised_pytorch",
                "model_schema": self.action_model_summary.get("schema", ""),
                "model_hash": self.action_model_summary.get("checkpoint_sha256", ""),
                "prediction": model_prediction,
                "observation_version": int(obs.resources.get("state_version", loop)),
                "dispatch_label": model_label,
            })

        if not combat_ids and not opening_gather_added and not self._opening_gather_issued:
            # A commander adapter may expose only custom workers during the
            # first playable frames.  Exercise the real P1 economy with one
            # map-observed mineral target instead of manufacturing a combat
            # order or sending a worker to a guessed rally coordinate.
            mineral = min(
                obs.mineral_fields,
                key=lambda item: math.hypot(
                    float(item.get("x", 0.0)) - self.economy.base_x,
                    float(item.get("y", 0.0)) - self.economy.base_y,
                ),
                default=None,
            )
            worker = next(
                (
                    unit for unit in obs.own_units
                    if int(unit.get("entity_id", 0)) in worker_ids
                ),
                None,
            )
            if mineral is not None and worker is not None:
                actions.append(DefendAction(
                    entity_id=int(worker["entity_id"]),
                    kind="gather",
                    target_entity_id=int(mineral["entity_id"]),
                    reason="map_worker_opening_gather",
                ))
            elif worker is not None:
                # Some commander catalogs hide neutral mineral units from the
                # P1 raw observation during startup.  The map placement marker
                # is still authoritative, so keep one worker on a legal local
                # rally point until the native economy exposes a target.
                actions.append(DefendAction(
                    entity_id=int(worker["entity_id"]),
                    kind="move",
                    target_x=float(self.economy.base_x),
                    target_y=float(self.economy.base_y),
                    reason="map_worker_base_rally",
                ))
            return actions

        shard_targets = [
            enemy for enemy in obs.visible_enemies
            if int(enemy.get("owner", 0)) == 7
            or "voidshard" in str(enemy.get("unit_type_id", "")).lower()
        ]
        stage = self._stage_for_loop(loop)
        target = None
        if shard_targets:
            target = min(
                shard_targets,
                key=lambda item: min(
                    math.hypot(
                        float(item.get("x", 0.0)) - float(point["position"]["x"]),
                        float(item.get("y", 0.0)) - float(point["position"]["y"]),
                    )
                    for point in (stage or {}).get("points", [])
                ) if stage and stage.get("points") else 0.0,
            )

        objective_key = (
            f"shard:{int(target['entity_id'])}" if target is not None
            else f"stage:{int(stage['stage'])}" if stage is not None else ""
        )
        if objective_key and objective_key != self._last_objective_key:
            self._last_objective_key = objective_key
            self.objective_trace.append({
                "loop": int(loop),
                "objective": objective_key,
                "stage": stage,
                "observed_target": target,
                "source": "MapScript.galaxy+Objects/ObjectPoint",
            })

        replacement: dict[int, DefendAction] = {}
        # A loaded model owns the high-level P1 combat choice. Map source
        # facts still resolve the target point/unit and the transport layer
        # still validates ownership and the native ability.
        if self.action_model is not None and model_label == "hold":
            for unit_id in sorted(combat_ids):
                replacement[unit_id] = DefendAction(
                    entity_id=unit_id,
                    kind="hold",
                    reason="p1_ml_hold",
                )
        elif self.action_model is not None and model_label == "defend":
            threats = [enemy for enemy in obs.visible_enemies if int(enemy.get("owner", 0)) != P1_PLAYER_ID]
            for unit_id in sorted(combat_ids):
                unit = own_by_id[unit_id]
                threat = min(
                    threats,
                    key=lambda enemy: math.hypot(
                        float(enemy.get("x", 0.0)) - float(unit.get("x", 0.0)),
                        float(enemy.get("y", 0.0)) - float(unit.get("y", 0.0)),
                    ),
                    default=None,
                )
                if threat is not None:
                    replacement[unit_id] = DefendAction(
                        entity_id=unit_id,
                        kind="attack",
                        target_entity_id=int(threat["entity_id"]),
                        reason="p1_ml_defend_visible_threat",
                    )
                else:
                    replacement[unit_id] = DefendAction(
                        entity_id=unit_id,
                        kind="move",
                        target_x=float(self.economy.base_x),
                        target_y=float(self.economy.base_y),
                        reason="p1_ml_defend_base",
                    )
        elif self.action_model is not None and model_label == "attack" and target is not None:
            for unit_id in sorted(combat_ids):
                replacement[unit_id] = DefendAction(
                    entity_id=unit_id,
                    kind="attack",
                    target_entity_id=int(target["entity_id"]),
                    reason="p1_ml_attack_map_objective",
                )
        elif self.action_model is not None and model_label == "move":
            # Some CMRE source revisions do not expose the shard-stage
            # assignments in the parser contract. In that case the only
            # valid target we can prove statically is P1's map-owned base
            # region; do not invent an objective coordinate.
            point = (
                stage["points"][0]["position"]
                if stage and stage.get("points")
                else {"x": self.economy.base_x, "y": self.economy.base_y}
            )
            for unit_id in sorted(combat_ids):
                replacement[unit_id] = DefendAction(
                    entity_id=unit_id,
                    kind="move",
                    target_x=float(point["x"]),
                    target_y=float(point["y"]),
                    reason=(
                        "p1_ml_move_map_objective"
                        if stage and stage.get("points")
                        else "p1_ml_move_map_base_fallback"
                    ),
                )
        elif self.action_model is None and target is not None:
            for unit_id in sorted(combat_ids):
                replacement[unit_id] = DefendAction(
                    entity_id=unit_id,
                    kind="attack",
                    target_entity_id=int(target["entity_id"]),
                    reason="map_objective_visible",
                )
        elif self.action_model is None and stage and stage.get("points"):
            elapsed = float(loop) / 22.4
            spawn_seconds = stage.get("spawn_seconds")
            if spawn_seconds is None or elapsed >= float(spawn_seconds) - 180.0:
                point = stage["points"][0]["position"]
                for unit_id in sorted(combat_ids):
                    replacement[unit_id] = DefendAction(
                        entity_id=unit_id,
                        kind="move",
                        target_x=float(point["x"]),
                        target_y=float(point["y"]),
                        reason="map_objective_staging",
                    )

        if not replacement:
            return actions
        return [
            action for action in actions
            if int(action.entity_id) not in replacement
        ] + [replacement[unit_id] for unit_id in sorted(replacement)]


def build_ally_chat_action(message: str) -> sc_pb.Action:
    """Build the P1 chat action consumed by the Galaxy P2 ally trigger."""
    normalized = str(message).strip()
    if not normalized.startswith("!ally "):
        raise ValueError("ally chat messages must start with '!ally '")
    return build_team_chat_action(normalized)


def build_team_chat_action(message: str) -> sc_pb.Action:
    """Build a team chat action for P1 commands and P2 acknowledgements."""
    normalized = str(message).strip()
    if not normalized:
        raise ValueError("team chat messages must not be empty")
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
            "build_progress": round(float(unit.get("build_progress", 1.0)), 3),
            "orders": [
                {
                    "ability_id": int(order.get("ability_id", 0)),
                    "progress": round(float(order.get("progress", 0.0)), 3),
                    "target_unit_tag": int(order.get("target_unit_tag", 0)),
                }
                for order in unit.get("orders", [])
            ],
        }
        for unit in units
        if int(unit.get("owner", 0)) == P2_PLAYER_ID
    ]


def _owner_state(obs: LiveObservation, owner_player_id: int) -> list[dict]:
    """Return only the requested owner from self/allied visible units."""
    units = obs.own_units + obs.visible_allies
    return [unit for unit in units if int(unit.get("owner", 0)) == owner_player_id]


def build_p2_policy_observation(obs: LiveObservation) -> LiveObservation:
    """Re-orient the public P1 observation into the P2 policy perspective.

    The API client owns P1, so P2 units arrive as ``visible_allies``. This
    helper only rearranges units already exposed by SC2's observation; it does
    not read hidden world state or invent P2 resources. The model therefore
    receives the same public contract it receives in simulator runs, with
    unavailable P2 economy values represented as zero.
    """

    visible_units = list(obs.own_units) + list(obs.visible_allies)
    p2_units = [
        unit for unit in visible_units
        if int(unit.get("owner", 0)) == P2_PLAYER_ID
    ]
    p1_units = [
        unit for unit in visible_units
        if int(unit.get("owner", 0)) == P1_PLAYER_ID
    ]
    return LiveObservation(
        loop=obs.loop,
        player_id=P2_PLAYER_ID,
        own_units=p2_units,
        visible_enemies=list(obs.visible_enemies),
        resources={
            "minerals": 0,
            "vespene": 0,
            "supply_used": 0,
            "supply_cap": 0,
            "state_version": int(obs.loop),
            "source": "not_visible_from_p1",
        },
        mission=dict(obs.mission),
        visible_allies=p1_units,
        alliance_summary=list(obs.alliance_summary),
        mineral_fields=list(obs.mineral_fields),
        vespene_geysers=list(obs.vespene_geysers),
    )


MODEL_MODE_TO_COMMAND = {
    "follow": "follow",
    "regroup": "regroup",
    "defend_base": "defend",
    "assist_attack": "attack",
    "retreat": "retreat",
    "hold": "hold",
}


def load_p2_intent_model(model_path: str | Path) -> tuple[object, dict]:
    """Load only the versioned PyTorch P2 intent checkpoint.

    The native bridge must fail closed for the historical JSON MLP or any
    schema-drifted checkpoint. Returning a summary alongside the model keeps
    provenance in the runtime report and Bank request trace.
    """

    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"P2 intent model checkpoint not found: {path}")
    try:
        from .ml.encoder import FEATURE_SCHEMA, feature_schema_hash
        from .ml.model import MODEL_SCHEMA, load_checkpoint
    except ImportError:
        # Direct-script execution has no package parent, but the ML modules
        # still use package-relative imports. Import through ``vibe`` after
        # adding the project package root instead of using a broken top-level
        # ``ml`` package.
        project_root = Path(__file__).resolve().parents[1]
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        from vibe.ml.encoder import FEATURE_SCHEMA, feature_schema_hash  # type: ignore
        from vibe.ml.model import MODEL_SCHEMA, load_checkpoint  # type: ignore

    model = load_checkpoint(path, device="cpu")
    summary = {
        "enabled": True,
        "backend": "pytorch",
        "evidence_type": "runtime",
        "path": str(path),
        "schema": MODEL_SCHEMA,
        "feature_schema": FEATURE_SCHEMA,
        "feature_schema_hash": feature_schema_hash(),
        "checkpoint_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "controller_player_id": P2_PLAYER_ID,
        "transport": "GalaxyVibe typed P2 intent Bank -> Galaxy PollLoop -> native P2 AI/economy orders",
        "p2_resources": "GalaxyVibe ally snapshot published by native bridge",
    }
    return model, summary


def load_p1_action_policy(model_path: str | Path) -> tuple[object, dict]:
    """Load the versioned PyTorch P1 action policy and its provenance."""

    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"P1 action model checkpoint not found: {path}")
    model = load_p1_action_model(path)
    metadata = dict(getattr(model, "checkpoint_metadata", {}) or {})
    return model, {
        "enabled": True,
        "backend": "pytorch",
        "evidence_type": "runtime",
        "path": str(path),
        "schema": str(metadata.get("schema", "cmre-p1-action-pytorch.v1")),
        "feature_schema": str(metadata.get("feature_schema", "")),
        "feature_schema_hash": str(metadata.get("feature_schema_hash", "")),
        "checkpoint_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "controller_player_id": P1_PLAYER_ID,
        "transport": "P1 PyTorch high-level action -> map source target resolver -> typed SC2 action",
        "training": metadata.get("training", {}),
    }


def _has_p1_p2_participant_roster(player_roster: dict) -> bool:
    """Require both P1 and P2 to be native Participant slots."""
    return all(
        int(player_roster.get(str(player_id), {}).get("type", 0))
        == PLAYER_TYPE_PARTICIPANT
        for player_id in (P1_PLAYER_ID, P2_PLAYER_ID)
    )


def _has_p1_p2_computer_roster(player_roster: dict) -> bool:
    """Require the single-client native topology: P1 human, P2 computer."""
    return (
        int(player_roster.get(str(P1_PLAYER_ID), {}).get("type", 0))
        == PLAYER_TYPE_PARTICIPANT
        and int(player_roster.get(str(P2_PLAYER_ID), {}).get("type", 0))
        == PLAYER_TYPE_COMPUTER
    )


def _runtime_bank_path(bank_name: str = "GalaxyVibe") -> Path:
    return Path.home() / "Documents" / "StarCraft II" / "Banks" / f"{bank_name}.SC2Bank"


def _read_runtime_bank_section(
    bank_name: str = "GalaxyVibe",
    section_name: str = "ally",
) -> dict:
    """Read one runtime Bank section without mixing command and debug state."""
    bank_path = _runtime_bank_path(bank_name)
    if not bank_path.exists():
        return {}
    try:
        root = ET.parse(bank_path).getroot()
    except (OSError, ET.ParseError):
        return {}
    section = next(
        (item for item in root.findall("Section") if item.get("name") == section_name),
        None,
    )
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


def _read_p2_model_bank_state() -> dict:
    """Read the P2 economy snapshot across the split Bank channels.

    VIBE_GEN_007 / N1 (2026-08-09): the kernel used to publish ``p2_*`` into the
    same ``GalaxyVibe`` bank that carries the RPC channel, so every snapshot
    ``BankSave`` flushed the whole kernel memory state over the host-written
    request. The kernel now writes those counters to a dedicated
    ``GalaxyVibeModel`` bank instead.

    This reader stays backward compatible on purpose: it starts from the legacy
    ``GalaxyVibe/ally`` section (older kernels, replayed evidence bundles) and
    overlays ``GalaxyVibeModel/ally`` when present, so a map running either
    kernel generation resolves the same keys.
    """

    state = _read_runtime_bank_section("GalaxyVibe", "ally")
    model_state = _read_runtime_bank_section("GalaxyVibeModel", "ally")
    if model_state:
        state.update(model_state)
    return state


def _reset_runtime_ally_bridge(
    bank_name: str = "GalaxyVibe",
    bank_path: Optional[Path] = None,
) -> tuple[bool, str]:
    """Clear transient P2 bridge state before creating a native game.

    SC2 Banks survive across local sessions. A prior pending model decision
    must not be mistaken for an acknowledgement in the next run.
    """

    target = bank_path or _runtime_bank_path(bank_name)
    if not target.exists():
        return True, ""
    try:
        tree = ET.parse(target)
        root = tree.getroot()
        section = next(
            (item for item in root.findall("Section") if item.get("name") == "ally"),
            None,
        )
        if section is None:
            section = ET.SubElement(root, "Section", {"name": "ally"})

        reset_values = {
            "pending_command": ("string", ""),
            "pending_player_id": ("int", "0"),
            "pending_source": ("string", ""),
            "pending_model_schema": ("string", ""),
            "pending_model_hash": ("string", ""),
            "pending_decision_id": ("string", ""),
            "pending_economy_intent": ("string", ""),
            "pending_production_intent": ("string", ""),
            "last_command": ("string", ""),
            "last_result": ("string", ""),
            "last_mode": ("string", ""),
            "last_signal": ("string", ""),
            "last_source": ("string", ""),
            "last_issuer_player_id": ("int", "0"),
            "last_model_schema": ("string", ""),
            "last_model_hash": ("string", ""),
            "last_model_decision_id": ("string", ""),
            "last_model_economy": ("string", ""),
            "last_model_production": ("string", ""),
            "last_model_economy_result": ("string", ""),
            "last_model_production_result": ("string", ""),
            "last_model_economy_dispatched": ("int", "0"),
            "last_model_production_dispatched": ("int", "0"),
            "command_count": ("int", "0"),
            "signal_count": ("int", "0"),
        }
        for key_name, (value_kind, value) in reset_values.items():
            key = next(
                (item for item in section.findall("Key") if item.get("name") == key_name),
                None,
            )
            if key is None:
                key = ET.SubElement(section, "Key", {"name": key_name})
            value_node = key.find("Value")
            if value_node is None:
                value_node = ET.SubElement(key, "Value")
            value_node.attrib.clear()
            value_node.set(value_kind, value)

        temp_path = target.with_name(f".{target.name}.bridge-reset.tmp")
        tree.write(temp_path, encoding="utf-8", xml_declaration=True)
        os.replace(temp_path, target)
    except (OSError, ET.ParseError, ValueError) as exc:
        try:
            if "temp_path" in locals() and temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        return False, str(exc)
    return True, ""


def _queue_runtime_ally_command(
    command: str,
    bank_name: str = "GalaxyVibe",
    bank_path: Optional[Path] = None,
    issuer_player_id: int = P1_PLAYER_ID,
    source: str = "p1_chat",
    model_schema: str = "",
    model_hash: str = "",
    decision_id: str = "",
    economy_intent: str = "",
    production_intent: str = "",
) -> tuple[bool, str]:
    """Queue a typed ally command for API-mode Galaxy polling.

    SC2 API can expose the chat message to the client while not delivering the
    corresponding Galaxy ChatMessage event. The map PollLoop consumes this
    short-lived bridge record. P1 chat and the external P2 model use separate
    issuer/source fields so the model never impersonates a player command.
    The model head labels travel in separate typed Bank fields; the chat
    string remains only the tactical compatibility projection.
    """
    normalized = str(command).strip()
    if not normalized.startswith("!ally "):
        return False, "ally command must start with '!ally '"
    issuer = int(issuer_player_id)
    normalized_source = str(source).strip()
    if issuer not in {P1_PLAYER_ID, P2_PLAYER_ID}:
        return False, "ally issuer must be player 1 or player 2"
    if issuer == P1_PLAYER_ID and normalized_source != "p1_chat":
        return False, "player 1 ally commands require source=p1_chat"
    if issuer == P2_PLAYER_ID and normalized_source != "ml_policy":
        return False, "player 2 ally commands require source=ml_policy"
    if issuer == P2_PLAYER_ID and (not model_schema or not model_hash or not decision_id):
        return False, "model ally commands require schema, hash, and decision_id"
    target = bank_path or _runtime_bank_path(bank_name)
    if not target.exists():
        return False, f"bank not found: {target}"
    try:
        tree = ET.parse(target)
        root = tree.getroot()
        section = next(
            (item for item in root.findall("Section") if item.get("name") == "ally"),
            None,
        )
        if section is None:
            section = ET.SubElement(root, "Section", {"name": "ally"})

        def set_value(key_name: str, value_kind: str, value: str) -> None:
            key = next(
                (item for item in section.findall("Key") if item.get("name") == key_name),
                None,
            )
            if key is None:
                key = ET.SubElement(section, "Key", {"name": key_name})
            value_node = key.find("Value")
            if value_node is None:
                value_node = ET.SubElement(key, "Value")
            value_node.attrib.clear()
            value_node.set(value_kind, value)

        set_value("pending_command", "string", normalized)
        set_value("pending_player_id", "int", str(issuer))
        set_value("pending_source", "string", normalized_source)
        set_value("pending_model_schema", "string", model_schema)
        set_value("pending_model_hash", "string", model_hash)
        set_value("pending_decision_id", "string", decision_id)
        set_value("pending_economy_intent", "string", economy_intent)
        set_value("pending_production_intent", "string", production_intent)
        temp_path = target.with_name(f".{target.name}.bridge-request.tmp")
        tree.write(temp_path, encoding="utf-8", xml_declaration=True)
        os.replace(temp_path, target)
    except (OSError, ET.ParseError, ValueError) as exc:
        try:
            if "temp_path" in locals() and temp_path.exists():
                temp_path.unlink()
        except OSError:
            pass
        return False, str(exc)
    return True, ""


def _ack_mode_model_decisions(
    decision_trace: list[dict], bank_state: dict, current_loop: int
) -> None:
    """Close ML requests only after Galaxy records the matching P2 result."""
    last_command = str(bank_state.get("last_command", ""))
    last_result = str(bank_state.get("last_result", ""))
    last_model_decision_id = str(bank_state.get("last_model_decision_id", ""))
    if not last_command and not last_model_decision_id:
        return
    for entry in decision_trace:
        if not entry.get("bridge_queued") or entry.get("acknowledged"):
            continue
        model_match = (
            bool(last_model_decision_id)
            and entry.get("decision_id") == last_model_decision_id
        )
        command_match = bool(last_command) and entry.get("message") == last_command
        if model_match or (not last_model_decision_id and command_match):
            entry.update({
                "acknowledged": True,
                "ack_loop": int(current_loop),
                "ack_result": (
                    "model_acknowledged" if model_match else last_result
                ),
            })


def _apply_p2_bank_resources(observation: LiveObservation, bank_state: dict) -> dict:
    """Overlay the P2 resource snapshot published by the native bridge.

    The API client is P1, so ``ResponseObservation.player_common`` only
    contains P1's economy. The Galaxy bridge publishes P2's own counters in
    the ally Bank; using that explicit snapshot keeps the ML input public and
    avoids treating P1's resources as P2's state.
    """

    resource_map = {
        "minerals": "p2_minerals",
        "vespene": "p2_vespene",
        "supply_used": "p2_supply_used",
        "supply_cap": "p2_supply_cap",
    }
    if not all(key in bank_state for key in resource_map.values()):
        return dict(observation.resources)
    resources = dict(observation.resources)
    for resource_name, bank_key in resource_map.items():
        resources[resource_name] = int(bank_state[bank_key])
    resources["state_version"] = int(observation.loop)
    resources["source"] = "galaxy_p2_bank"
    observation.resources = resources
    return resources


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


def _target_state_by_tag(obs: LiveObservation) -> dict[int, dict]:
    """Index every observable target used by native action trace records.

    Gas gathering targets an owned Refinery, while mineral gathering targets a
    neutral MineralField. Keeping both in the index makes the trace prove the
    actual target owner/type instead of silently recording an unknown target.
    """
    return {
        int(unit["entity_id"]): unit
        for unit in (
            obs.own_units
            + obs.visible_allies
            + obs.visible_enemies
            + obs.mineral_fields
        )
    }


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
    replay_html_path: str = ""
    native_replay_path: str = ""
    native_replay_error: str = ""
    native_player_results: dict = field(default_factory=dict)
    map_source_audit_path: str = ""
    map_source_summary: dict = field(default_factory=dict)
    map_objective_trace: list[dict] = field(default_factory=list)
    observed_player_id: int = P1_PLAYER_ID
    p2_unit_count: int = 0
    p2_alliance_values: list[int] = field(default_factory=list)
    p1_visible_alliance_values: list[int] = field(default_factory=list)
    player_roster: dict = field(default_factory=dict)
    ally_command_trace: list[dict] = field(default_factory=list)
    chat_received: list[dict] = field(default_factory=list)
    p1_command_trace: list[dict] = field(default_factory=list)
    p2_signal_trace: list[dict] = field(default_factory=list)
    ally_mode_history: list[str] = field(default_factory=list)
    ally_bank_initial: dict = field(default_factory=dict)
    ally_bank_final: dict = field(default_factory=dict)
    native_ally_debug_initial: dict = field(default_factory=dict)
    native_ally_debug_final: dict = field(default_factory=dict)
    runtime_catalog_summary: dict = field(default_factory=dict)
    mode_model_summary: dict = field(default_factory=dict)
    mode_model_decision_trace: list[dict] = field(default_factory=list)
    p1_model_summary: dict = field(default_factory=dict)
    p1_model_decision_trace: list[dict] = field(default_factory=list)


def _replay_entity(unit: dict, owner: int) -> dict:
    """Convert a live observation unit to the browser replay entity shape."""
    entity_id = int(unit.get("entity_id", 0))
    return {
        "id": entity_id,
        "p": int(owner),
        "t": str(unit.get("unit_type_id", "Unknown")),
        "x": float(unit.get("x", 0.0)),
        "y": float(unit.get("y", 0.0)),
        "hp": int(unit.get("health", 0)),
        "alive": int(unit.get("health", 0)) > 0,
        "build_progress": round(float(unit.get("build_progress", 1.0)), 3),
        "orders": list(unit.get("orders", [])),
    }


def _write_replay_frame(fp, loop: int, obs: LiveObservation,
                        total_cmds: int, key_events: list[dict]) -> None:
    """写一帧回放日志到 JSONL 文件。"""
    p1_state = _owner_state(obs, P1_PLAYER_ID)
    p2_state = _owner_state(obs, P2_PLAYER_ID)
    p1_units_by_type: dict[str, int] = {}
    enemy_units_by_type: dict[str, int] = {}
    for u in p1_state:
        t = u["unit_type_id"]
        p1_units_by_type[t] = p1_units_by_type.get(t, 0) + 1
    for e in obs.visible_enemies:
        t = e["unit_type_id"]
        enemy_units_by_type[t] = enemy_units_by_type.get(t, 0) + 1
    p2_units_by_type: dict[str, int] = {}
    for e in p2_state:
        t = e["unit_type_id"]
        p2_units_by_type[t] = p2_units_by_type.get(t, 0) + 1

    entities_by_player: dict[str, list[dict]] = {}
    for unit in obs.mineral_fields + obs.vespene_geysers:
        entities_by_player.setdefault("0", []).append(_replay_entity(unit, 0))
    for unit in obs.visible_allies:
        owner = int(unit.get("owner", 0))
        entities_by_player.setdefault(str(owner), []).append(_replay_entity(unit, owner))
    for unit in obs.own_units:
        owner = int(unit.get("owner", obs.player_id))
        entities_by_player.setdefault(str(owner), []).append(
            _replay_entity(unit, owner)
        )
    for unit in obs.visible_enemies:
        owner = int(unit.get("owner", 0))
        entities_by_player.setdefault(str(owner), []).append(_replay_entity(unit, owner))

    frame = {
        "record_type": "frame",
        "loop": loop,
        "ts_sec": round(loop / 22.4, 1),
        "p1_alive": len(p1_state),
        "enemy_alive": len(obs.visible_enemies),
        "p1_units_by_type": p1_units_by_type,
        "enemy_units_by_type": enemy_units_by_type,
        "p2_alive": len(p2_state),
        "p2_units_by_type": p2_units_by_type,
        "entities_by_player": entities_by_player,
        "strategy_player_id": obs.player_id,
        "strategy_player_resources": obs.resources,
        "p1_resources": obs.resources if obs.player_id == P1_PLAYER_ID else None,
        "p2_resources": obs.resources if obs.player_id == P2_PLAYER_ID else None,
        "total_cmds": total_cmds,
        "key_events": key_events,
    }
    fp.write(json.dumps(frame, ensure_ascii=False) + "\n")
    fp.flush()


async def run_p1_anchor(
    port: int,
    map_path: str,
    wait_sec: float = 90.0,
    commands: Optional[list[str]] = None,
    verbose: bool = True,
    output_path: Optional[str] = None,
    multiplayer_port_base: int = MULTIPLAYER_PORT_BASE,
    multiplayer_ports: bool = False,
) -> dict:
    """Create the two-participant game and hold the real P1 API client.

    SC2 assigns the first JoinGame client to P1.  The native P2 strategy must
    therefore join through a second client; this anchor owns CreateGame and
    also provides the real P1 chat/signal source for the P2 policy.
    """
    conn = Sc2Connection(port)
    report: dict = {
        "status": "inconclusive",
        "port": port,
        "map_path": str(Path(map_path)),
        "player_id": 0,
        "player_roster": {},
        "commands": [],
    }
    try:
        await conn.connect()
        ping = await conn.send_request(sc_pb.Request(ping=sc_pb.RequestPing()))
        if verbose:
            print(f"[anchor] Ping: version={ping.ping.game_version}")
        try:
            await conn.send_request(
                sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), timeout=10
            )
        except Exception:
            pass
        await asyncio.sleep(2)

        map_file = Path(map_path)
        if not map_file.is_file() or not map_file.read_bytes():
            raise FileNotFoundError(f"P1 anchor requires a packed map: {map_file}")
        create = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=sc_pb.LocalMap(map_path=str(map_file.resolve())),
            player_setup=[
                sc_pb.PlayerSetup(type=1),
                sc_pb.PlayerSetup(type=1),
            ],
            realtime=False,
        ))
        response = await conn.send_request(create, timeout=60, max_retries=5)
        if response.error:
            raise RuntimeError(f"P1 anchor CreateGame failed: {list(response.error)}")
        if verbose:
            print("[anchor] CreateGame OK")

        join = sc_pb.Request(join_game=sc_pb.RequestJoinGame(
            race=1,
            player_name="P1",
            options=sc_pb.InterfaceOptions(raw=True),
        ))
        # The default stays on SC2's local JoinGame path. A real two-client
        # run can opt into the complete shared Portconfig explicitly.
        if multiplayer_ports:
            server_ports, client_ports = _multiplayer_port_topology(
                multiplayer_port_base
            )
            join.join_game.server_ports.game_port = server_ports[0]
            join.join_game.server_ports.base_port = server_ports[1]
            for game_port, base_port in client_ports:
                port = join.join_game.client_ports.add()
                port.game_port = game_port
                port.base_port = base_port
        joined = False
        join_timeout = 180 if multiplayer_ports else 30
        join_retries = 1 if multiplayer_ports else 2
        for attempt in range(30):
            response = await conn.send_request(
                join, timeout=join_timeout, max_retries=join_retries
            )
            if not response.error:
                joined = True
                break
            if verbose and attempt == 0:
                print(f"[anchor] JoinGame retry: {list(response.error)}")
            await asyncio.sleep(0.5)
        if not joined or not response.HasField("join_game"):
            raise RuntimeError("P1 anchor JoinGame did not return a join_game response")
        report["player_id"] = int(response.join_game.player_id)
        if report["player_id"] != P1_PLAYER_ID:
            raise RuntimeError(
                f"P1 anchor expected player_id=1, got {report['player_id']}"
            )
        if verbose:
            print(f"[anchor] JoinGame OK! player_id={report['player_id']}")

        # The first client is P1, but SC2 does not publish the second
        # participant in GameInfo until the P2 client has completed JoinGame.
        # Poll the authoritative roster while the separate P2 client joins;
        # reading it only once creates a false topology failure.
        roster_deadline = time.monotonic() + min(max(wait_sec, 30.0), 60.0)
        while True:
            info = await conn.send_request(
                sc_pb.Request(game_info=sc_pb.RequestGameInfo()), timeout=15
            )
            report["player_roster"] = {
                str(item.player_id): {
                    "player_id": int(item.player_id),
                    "type": int(item.type),
                    "race_requested": int(item.race_requested),
                    "race_actual": int(item.race_actual),
                    "player_name": item.player_name,
                }
                for item in info.game_info.player_info
            }
            if _has_p1_p2_participant_roster(report["player_roster"]):
                break
            if time.monotonic() >= roster_deadline:
                raise RuntimeError(
                    "P1 anchor did not observe P1/P2 participant roster before timeout: "
                    f"{report['player_roster']}"
                )
            await asyncio.sleep(0.5)

        scheduled = commands or [
            "!ally status stage25_p1_anchor_status",
            "!ally defend stage25_p1_anchor_defend",
            "!ally attack stage25_p1_anchor_attack",
        ]
        start = time.monotonic()
        cursor = 0
        command_times = [8.0, 24.0, 42.0]
        while time.monotonic() - start < wait_sec:
            elapsed = time.monotonic() - start
            if cursor < len(scheduled) and elapsed >= command_times[min(cursor, len(command_times) - 1)]:
                message = str(scheduled[cursor]).strip()
                result = await conn.send_request(
                    sc_pb.Request(action=sc_pb.RequestAction(
                        actions=[build_ally_chat_action(message)]
                    )),
                    timeout=10,
                )
                entry = {
                    "elapsed_sec": round(elapsed, 2),
                    "message": message,
                    "request_ok": not bool(result.error),
                    "response_errors": list(result.error),
                    "source_player_id": P1_PLAYER_ID,
                    "target_player_id": P2_PLAYER_ID,
                }
                report["commands"].append(entry)
                if verbose:
                    print(f"[anchor] P1 -> P2: {message} ok={entry['request_ok']}")
                cursor += 1
            await asyncio.sleep(0.5)
        report["status"] = "PASS"
    finally:
        await conn.close()
    if output_path:
        destination = Path(output_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report


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
    join_existing: bool = False,
    multiplayer_ports: bool = False,
    multiplayer_port_base: int = MULTIPLAYER_PORT_BASE,
    computer_ally: bool = True,
    map_source_dir: Optional[str] = None,
    map_source_audit_path: Optional[str] = None,
    render_html: bool = False,
    mode_model_path: Optional[str] = None,
    p1_model_path: Optional[str] = None,
    realtime: bool = False,
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
        join_existing: 跳过建局，仅加入另一个 API client 已创建的当前对局
        multiplayer_ports: 为旧双 Participant 探针提交共享端口拓扑
        multiplayer_port_base: shared Portconfig base port for multiplayer_ports
        computer_ally: use one P1 client plus native Computer P2 (the default)
        map_source_dir: unpacked source map directory; auto-resolved for CMRE maps
        map_source_audit_path: optional raw-map audit JSON path
        render_html: opt-in legacy browser projection; native acceptance leaves it off
        mode_model_path: optional PyTorch P2 intent checkpoint. The model
            emits a typed four-head intent; the Galaxy bridge owns P2 order
            execution after validating the tactical command projection.
        p1_model_path: optional PyTorch P1 high-level action checkpoint. The
            model chooses only an action family; map facts and typed SC2
            validation resolve the actual target and transport.
    """
    start_time = time.time()
    mode_model = None
    mode_model_summary: dict = {
        "enabled": bool(mode_model_path),
        "evidence_type": "runtime" if mode_model_path else "inference",
    }
    if mode_model_path:
        mode_model, mode_model_summary = load_p2_intent_model(mode_model_path)
    p1_model = None
    p1_model_summary: dict = {
        "enabled": bool(p1_model_path),
        "evidence_type": "runtime" if p1_model_path else "inference",
    }
    if p1_model_path:
        p1_model, p1_model_summary = load_p1_action_policy(p1_model_path)
    conn = Sc2Connection(port)
    await conn.connect()
    server_ports, client_ports = _multiplayer_port_topology(multiplayer_port_base)
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
    native_replay_path = ""
    native_replay_error = ""
    native_player_results: dict[int, int] = {}
    # None means the live Catalog request was unavailable. Keep that distinct
    # from an intentionally resolved catalog so custom Empire commands do not
    # silently turn into ability_id=0 no-ops.
    runtime_ability_catalog: Optional[RuntimeAbilityCatalog] = None
    runtime_catalog_summary: dict = {}
    map_name = os.path.basename(map_path)
    live_map_metadata: dict = dict(LIVE_MAP_METADATA)
    map_source: Optional[MapSource] = None
    map_source_summary: dict = {}
    map_source_audit_file = ""
    local_map_path = ""
    strategy_player_id = P1_PLAYER_ID if computer_ally else P2_PLAYER_ID
    player_id = strategy_player_id
    player_roster: dict = {}
    ally_command_trace: list[dict] = []
    chat_received: list[dict] = []
    try:
        # 1. Ping
        r = await conn.send_request(sc_pb.Request(ping=sc_pb.RequestPing()))
        if verbose:
            print(f"[1] Ping: version={r.ping.game_version} base={r.ping.base_build}")

        if join_existing:
            if verbose:
                print("[2-3] Join existing game; P1 anchor owns CreateGame")
        else:
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

            bridge_reset_ok, bridge_reset_error = _reset_runtime_ally_bridge()
            if not bridge_reset_ok:
                raise RuntimeError(
                    f"failed to reset persistent P2 ally Bank bridge: {bridge_reset_error}"
                )
            if verbose:
                print("  P2 ally Bank bridge reset")

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
            player_setup = [sc_pb.PlayerSetup(
                type=PLAYER_TYPE_PARTICIPANT,
                race=1,
                player_name="P1",
            )]
            if computer_ally:
                player_setup.append(sc_pb.PlayerSetup(
                    type=PLAYER_TYPE_COMPUTER,
                    race=1,
                    difficulty=2,
                    player_name="P2 AI",
                ))
            else:
                player_setup.append(sc_pb.PlayerSetup(
                    type=PLAYER_TYPE_PARTICIPANT,
                    race=1,
                    player_name="P2",
                ))
            req = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
                local_map=local_map,
                player_setup=player_setup,
                realtime=realtime,
            ))
            r = await conn.send_request(req, timeout=60, max_retries=5)
            if r.HasField("create_game") and r.create_game.HasField("error"):
                err = r.create_game.error
                if verbose:
                    print(f"  CreateGame error: {err} (可能已在 in_game，尝试直接 JoinGame)")
            else:
                if verbose:
                    print("  CreateGame OK")

        # Reborn's standalone campaign frontend can leave a native loading
        # confirmation between CreateGame and JoinGame.  The approved launcher
        # can handle DirectMap launches, while API sessions need the same
        # input after the client has actually loaded this map.
        reborn_confirm_attempts = 0
        if realtime and not join_existing:
            await asyncio.sleep(0.5)
            reborn_confirm_attempts += 1
            _send_reborn_loading_confirm(port, verbose=verbose)

        # 4. JoinGame（raw 接口）—— 参考 RealProfile：重试 30 次每次 500ms
        if verbose:
            print("[4] JoinGame...")
        join_req = sc_pb.Request(join_game=sc_pb.RequestJoinGame(
            race=1,  # Terran
            player_name="P1" if computer_ally else "P2",
            options=sc_pb.InterfaceOptions(raw=True),
        ))
        if multiplayer_ports:
            join_req.join_game.server_ports.game_port = server_ports[0]
            join_req.join_game.server_ports.base_port = server_ports[1]
            for game_port, base_port in client_ports:
                client_port = join_req.join_game.client_ports.add()
                client_port.game_port = game_port
                client_port.base_port = base_port
        joined = False
        join_timeout = 180 if multiplayer_ports else 30
        join_retries = 1 if multiplayer_ports else 2
        for attempt in range(30):
            try:
                r = await conn.send_request(
                    join_req, timeout=join_timeout, max_retries=join_retries
                )
                if r.error:
                    if verbose and attempt == 0:
                        print(f"  JoinGame attempt {attempt+1}: error={r.error}")
                    if realtime and not join_existing and reborn_confirm_attempts < 2:
                        reborn_confirm_attempts += 1
                        _send_reborn_loading_confirm(port, verbose=verbose)
                    await asyncio.sleep(0.5)
                    continue
                joined = True
                break
            except Exception as e:
                if verbose and attempt == 0:
                    print(f"  JoinGame attempt {attempt+1} exc: {e}")
                if realtime and not join_existing and reborn_confirm_attempts < 2:
                    reborn_confirm_attempts += 1
                    _send_reborn_loading_confirm(port, verbose=verbose)
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
        elif r.HasField("observation"):
            observed_common = r.observation.observation.player_common
            if observed_common.player_id:
                player_id = observed_common.player_id
        if player_id != strategy_player_id:
            raise RuntimeError(
                f"runtime client expected player_id={strategy_player_id}, "
                f"but SC2 assigned player_id={player_id}"
            )
        if verbose:
            print(f"  JoinGame OK! player_id={player_id}")

        # Non-realtime SC2 is frame-driven. Advance the startup graph instead
        # of sleeping and assuming that Galaxy has already executed.
        # Realtime mode: the simulation advances on its own; just wait for
        # map initialization to complete (Reborn SwarmSetup uses Wait(c_timeGame)
        # which deadlocks in non-realtime mode).
        if realtime:
            if verbose:
                print("  realtime 模式：等待地图初始化（15s）...")
            await asyncio.sleep(15)
        else:
            if verbose:
                print("  驱动首帧，让 Galaxy 地图初始化...")
            await _advance_non_realtime_startup(conn, verbose=verbose)
        try:
            runtime_ability_catalog = await fetch_runtime_ability_catalog(
                conn,
                verbose=verbose,
            )
            runtime_catalog_summary = {
                "status": "resolved",
                "evidence_type": "runtime",
                "ability_count": len(runtime_ability_catalog),
                "empire_commands": {
                    f"{link}:{index}": runtime_ability_catalog.get((link, index), 0)
                    for link, index in (
                        ("3jianzao1", 0),
                        ("3jianzao1", 3),
                        ("3jianzao1", 10),
                        ("3jianzao1", 11),
                        ("3xunlian1", 0),
                    )
                },
            }
        except Exception as exc:
            runtime_catalog_summary = {
                "status": "blocked",
                "evidence_type": "blocked",
                "error": str(exc),
            }
            if verbose:
                print(f"  Runtime Catalog unavailable: {exc}")

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
        roster_ready = (
            _has_p1_p2_computer_roster(player_roster)
            if computer_ally
            else _has_p1_p2_participant_roster(player_roster)
        )
        if not roster_ready:
            roster_message = (
                "single-client runtime requires P1 Participant + P2 Computer; "
                if computer_ally
                else "legacy P2 strategy requires two Participant slots; "
            )
            raise RuntimeError(roster_message + f"observed={player_roster}")
        source_dir = resolve_map_source(map_name, map_source_dir)
        if source_dir is not None:
            map_source = read_map_source(source_dir)
            map_source_summary = {
                "status": "resolved",
                "evidence_type": "static",
                "map_dir": map_source.map_dir,
                "map_name": map_source.map_name,
                "source_hash": map_source.source_hash,
                "object_unit_count": len(map_source.object_units),
                "object_point_count": len(map_source.object_points),
                "region_count": len(map_source.regions),
                "component_count": len(map_source.component_hashes),
                "p1_spawn_markers": [
                    item for item in map_source.object_units
                    if item.get("unit_type") == "ACHeroSpawnPlacement"
                    and int(item.get("player", 0)) == P1_PLAYER_ID
                ],
                "p2_spawn_markers": [
                    item for item in map_source.object_units
                    if item.get("unit_type") == "ACHeroSpawnPlacement"
                    and int(item.get("player", 0)) == P2_PLAYER_ID
                ],
                "objective_required_count": map_source.script.get("objective_required_count", 0),
                "stages": map_source.script.get("stages", []),
                "native_ai": map_source.script.get("native_ai", {}),
                "alliance_contract": map_source.script.get("alliance_contract", {}),
                "victory_triggers": map_source.script.get("victory_triggers", []),
                "terrain": map_source.terrain,
                "pathing": map_source.pathing,
            }
            audit_path = Path(map_source_audit_path) if map_source_audit_path else replay_path.with_name("map-source-audit.json")
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_path.write_text(
                json.dumps(map_source.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            map_source_audit_file = str(audit_path)
        else:
            map_source_summary = {
                "status": "not_resolved",
                "evidence_type": "blocked",
                "runtime_map_name": map_name,
                "requested_source_dir": map_source_dir,
            }
        live_map_metadata = _resolve_runtime_map_metadata(map_path, map_name)
        live_map_metadata["map_source"] = map_source_summary
        _write_live_replay_header(
            replay_fp,
            live_map_metadata,
            computer_ally,
            map_source_audit=map_source_summary,
            mode_model_summary=mode_model_summary,
            p1_model_summary=p1_model_summary,
        )
        if verbose:
            print(f"[5] Map: {map_name} | local_map_path={local_map_path}")
            print(
                "  Map source: "
                f"{map_source_summary.get('status')} "
                f"objects={map_source_summary.get('object_unit_count', 0)} "
                f"points={map_source_summary.get('object_point_count', 0)} "
                f"stages={len(map_source_summary.get('stages', []))}"
            )

        # 6. Native task policy. In the Computer-ally topology P1 is the only
        # API-controlled participant, while P2 remains a native Computer. The
        # policy therefore issues only P1 actions and reads map objectives from
        # the unpacked source contract.
        policy: Optional[DefendBasePolicy | MapDrivenP1Policy] = None
        ally_policy: Optional[AllyPolicy] = None
        p1_command_trace: list[dict] = []
        p2_signal_trace: list[dict] = []
        default_p2_base = (76.0, 103.0, 15.0)
        ally_bank_initial = _read_runtime_bank_section()
        native_ally_debug_initial = _read_runtime_bank_section(
            "CMRERebornDebug", "debug"
        )
        mode_model_decision_trace: list[dict] = []
        p1_model_decision_trace: list[dict] = []
        last_mode_model_decide_loop = -10_000
        last_mode_model_label = "follow"

        # 7. P1 chat is a real participant-to-participant command channel.
        # P2 parses it through the same AllyPolicy contract used by the
        # simulator, emits a P2 acknowledgement, and then continues its own
        # native economy/tactical loop.
        run_token = str(int(start_time))
        model_run_token = f"{run_token}-{time.time_ns() % 1000000:06d}"
        commands = [] if player_id == P2_PLAYER_ID else (ally_commands or [
            f"!ally status stage25_{run_token}_status",
            f"!ally defend stage25_{run_token}_defend",
            f"!ally attack stage25_{run_token}_attack",
        ])
        command_cursor = 0
        command_due_loops = [0, max(1, max_loops // 4), max(2, max_loops // 2)]
        pending_command: Optional[dict] = None
        initial_p2_state: Optional[list[dict]] = None
        latest_p2_state: list[dict] = []

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
                # Step 推进游戏（realtime 模式下游戏自动推进，无需 RequestStep）
                if not realtime:
                    await conn.send_request(
                        sc_pb.Request(step=sc_pb.RequestStep(count=step_size)),
                        timeout=15)
                else:
                    await asyncio.sleep(0.1)

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
            current_p2_state = _p2_state(obs)
            if initial_p2_state is None and current_p2_state:
                initial_p2_state = current_p2_state
            if current_p2_state:
                latest_p2_state = current_p2_state
            if (
                initial_obs is None
                and obs.own_units
                and obs.resources.get("supply_cap", 0) > 0
            ):
                initial_obs = obs
            current_loop = obs.loop

            # A model command is acknowledged by the Galaxy side after the
            # Bank PollLoop consumes its explicitly P2-tagged request. Keep
            # this separate from the P1 chat command trace.
            if mode_model_decision_trace:
                model_bank = _read_runtime_bank_section()
                acknowledged_before = {
                    entry.get("decision_id")
                    for entry in mode_model_decision_trace
                    if entry.get("acknowledged")
                }
                _ack_mode_model_decisions(
                    mode_model_decision_trace,
                    model_bank,
                    current_loop,
                )
                for model_entry in mode_model_decision_trace:
                    if (
                        model_entry.get("acknowledged")
                        and model_entry.get("decision_id") not in acknowledged_before
                    ):
                        model_entry["bank_after"] = dict(model_bank)
                        model_entry["p2_after"] = _p2_state(obs)

            # 检查游戏是否结束
            if r.observation.player_result:
                native_player_results = {
                    int(pr.player_id): int(pr.result)
                    for pr in r.observation.player_result
                }
                if verbose:
                    print(f"  游戏结束(player_result): {native_player_results}")
                break

            for received in r.observation.chat:
                chat_entry = {
                    "loop": current_loop,
                    "player_id": int(received.player_id),
                    "message": received.message,
                }
                chat_received.append(chat_entry)
                if (
                    int(received.player_id) == P1_PLAYER_ID
                    and str(received.message).strip().startswith("!ally")
                ):
                    if computer_ally:
                        p1_command_trace.append({
                            **chat_entry,
                            "accepted": True,
                            "command_kind": "native_computer_ally",
                            "mode": "forwarded_to_p2",
                            "response": "forwarded_to_native_p2",
                        })
                    else:
                        if ally_policy is None:
                            ally_policy = AllyPolicy(
                                player_id=P2_PLAYER_ID,
                                leader_entity_id=0,
                                base_region=default_p2_base,
                                leader_player_id=P1_PLAYER_ID,
                                command_interval=decision_interval,
                            )
                        notice = ally_policy.receive_player_command(
                            str(received.message),
                            source_player_id=P1_PLAYER_ID,
                            loop=current_loop,
                            command_id=f"p1:{current_loop}:{received.message}",
                        )
                        p1_command_trace.append({
                            **chat_entry,
                            "accepted": bool(notice.accepted),
                            "command_kind": notice.kind,
                            "mode": notice.mode,
                            "response": notice.message,
                        })
                elif computer_ally and "[Ally P2]" in str(received.message):
                    p2_signal_trace.append({
                        **chat_entry,
                        "source": "galaxy_ui_message",
                        "recipient_player_id": P1_PLAYER_ID,
                        "request_ok": True,
                    })

            if policy is None:
                native_base = next(
                    (
                        unit for unit in obs.own_units
                        if unit.get("unit_type_id") in {
                            "CommandCenter", "OrbitalCommand", "PlanetaryFortress"
                        }
                    ),
                    None,
                )
                base_region = (
                    (
                        float(native_base.get("x", default_p2_base[0])),
                        float(native_base.get("y", default_p2_base[1])),
                        default_p2_base[2],
                    )
                    if native_base is not None else default_p2_base
                )
                if computer_ally and map_source is not None:
                    base_region = resolve_p1_base_region(obs, map_source, base_region)
                if computer_ally and map_source is not None:
                    policy = MapDrivenP1Policy(
                        source=map_source,
                        base_region=base_region,
                        command_interval=decision_interval,
                        action_model=(p1_model if player_id == P1_PLAYER_ID else None),
                        action_model_summary=p1_model_summary,
                    )
                else:
                    policy = DefendBasePolicy(
                        player_id=player_id,
                        base_region=base_region,
                        command_interval=decision_interval,
                    )
            if not computer_ally and ally_policy is None:
                leader_unit = next(
                    (
                        unit for unit in obs.visible_allies
                        if int(unit.get("owner", 0)) == P1_PLAYER_ID
                    ),
                    None,
                )
                ally_policy = AllyPolicy(
                    player_id=P2_PLAYER_ID,
                    leader_entity_id=(
                        int(leader_unit["entity_id"]) if leader_unit else 0
                    ),
                    base_region=(policy.base_x, policy.base_y, policy.base_r),
                    leader_player_id=P1_PLAYER_ID,
                    command_interval=decision_interval,
                )
                ally_policy.base_x = policy.base_x
                ally_policy.base_y = policy.base_y
                ally_policy.base_r = policy.base_r
            elif not computer_ally and ally_policy.leader_entity_id == 0:
                leader_unit = next(
                    (
                        unit for unit in obs.visible_allies
                        if int(unit.get("owner", 0)) == P1_PLAYER_ID
                    ),
                    None,
                )
                if leader_unit is not None:
                    ally_policy.leader_entity_id = int(leader_unit["entity_id"])

            # Native strategy action adapter. Every entry in
            # action_result_trace comes from this block and is eligible for
            # the no-injection strategy audit.
            if (
                policy is not None
                and current_loop - last_native_decide_loop >= decision_interval
            ):
                last_native_decide_loop = current_loop
                policy_resources = dict(obs.resources)
                policy_resources["vespene_geysers"] = obs.vespene_geysers
                own_by_tag = {u["entity_id"]: u for u in obs.own_units}
                actions = policy.decide(obs, current_loop, resources=policy_resources)
                tactical_actions = (
                    ally_policy.decide(obs, current_loop)
                    if not computer_ally and ally_policy is not None
                    else []
                )
                tactical_ids = {
                    int(action.entity_id)
                    for action in tactical_actions
                    if action.kind != "hold"
                    and int(action.entity_id) in own_by_tag
                    and own_by_tag[int(action.entity_id)].get("unit_type_id", "")
                    not in (
                        DefendBasePolicy.WORKER_TYPES
                        | DefendBasePolicy.BUILDING_TYPES
                        | set(DefendBasePolicy.PRODUCER_TYPES)
                        | DefendBasePolicy.NON_COMBAT_TYPES
                    )
                }
                if tactical_ids:
                    actions = [
                        action for action in actions
                        if int(action.entity_id) not in tactical_ids
                    ]
                    for tactical in tactical_actions:
                        if int(tactical.entity_id) not in tactical_ids:
                            continue
                        actions.append(DefendAction(
                            entity_id=int(tactical.entity_id),
                            kind="move" if tactical.kind == "follow" else tactical.kind,
                            target_entity_id=int(tactical.target_entity_id),
                            target_x=float(tactical.target_x),
                            target_y=float(tactical.target_y),
                            reason=tactical.reason,
                        ))
                total_commands_issued += len([a for a in actions if a.kind != "hold"])
                sc2_actions: list[sc_pb.Action] = []
                action_contexts: list[dict] = []
                target_by_tag = _target_state_by_tag(obs)
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
                        runtime_ability_catalog=runtime_ability_catalog,
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
                _ack_mode_model_decisions(
                    mode_model_decision_trace,
                    _read_runtime_bank_section(),
                    current_loop,
                )
                model_inflight = any(
                    item.get("bridge_queued") and not item.get("acknowledged")
                    for item in mode_model_decision_trace
                )
                p1_command_sent = False
                if (
                    not model_inflight
                    and command_cursor < len(commands)
                    and current_loop >= command_due_loops[command_cursor]
                ):
                    command = str(commands[command_cursor]).strip()
                    p1_command_sent = True
                    before_state = _p2_state(obs)
                    bank_before = _read_runtime_bank_section()
                    try:
                        chat_request = sc_pb.Request(action=sc_pb.RequestAction(
                            actions=[build_ally_chat_action(command)]
                        ))
                        chat_response = await conn.send_request(chat_request, timeout=10)
                        sent_ok = not bool(chat_response.error)
                        bank_bridge_ok = False
                        bank_bridge_error = ""
                        if sent_ok:
                            bank_bridge_ok, bank_bridge_error = _queue_runtime_ally_command(command)
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
                            "bank_bridge_ok": bank_bridge_ok,
                            "bank_bridge_error": bank_bridge_error,
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
                            "bank_bridge_ok": False,
                            "error": str(e),
                            "p2_before": before_state,
                            "bank_before": bank_before,
                        }
                    command_cursor += 1

                # The external PyTorch policy is a P2 controller, not a
                # second P1 chat client. Tactical/command stay on the legacy
                # chat projection, while economy/production are sent as
                # separate typed Bank labels for native P2 execution.
                model_inflight = any(
                    item.get("bridge_queued") and not item.get("acknowledged")
                    for item in mode_model_decision_trace
                )
                if (
                    computer_ally
                    and mode_model is not None
                    and not p1_command_sent
                    and not model_inflight
                    and current_loop - last_mode_model_decide_loop >= decision_interval
                ):
                    last_mode_model_decide_loop = current_loop
                    p2_view = build_p2_policy_observation(obs)
                    # VIBE_GEN_007 分库：p2_* 现由内核写入独立的 GalaxyVibeModel
                    # 库，此处合并读取（旧内核的 GalaxyVibe/ally 仍兼容）。
                    p2_bank_state = _read_p2_model_bank_state()
                    _apply_p2_bank_resources(p2_view, p2_bank_state)
                    p2_base = next(
                        (
                            unit for unit in p2_view.own_units
                            if unit.get("unit_type_id") in {
                                "CommandCenter", "OrbitalCommand", "PlanetaryFortress"
                            }
                        ),
                        None,
                    )
                    p2_base_region = (
                        (
                            float(p2_base.get("x", default_p2_base[0])),
                            float(p2_base.get("y", default_p2_base[1])),
                            default_p2_base[2],
                        )
                        if p2_base is not None else default_p2_base
                    )
                    decision_id = (
                        f"p2-ml:{model_run_token}:{int(current_loop)}:"
                        f"{len(mode_model_decision_trace) + 1}"
                    )
                    intent = mode_model.predict_intent(
                        p2_view,
                        requested_mode=last_mode_model_label,
                        decision_id=decision_id,
                        issuer_player_id=P2_PLAYER_ID,
                        base_region=p2_base_region,
                        support_range=14.0,
                    )
                    predicted_mode = str(intent.tactical)
                    command_projection = str(intent.command)
                    command_mode = MODEL_MODE_TO_COMMAND.get(
                        command_projection
                    ) or MODEL_MODE_TO_COMMAND.get(predicted_mode)
                    # ``command=none`` is a valid economy/production-only
                    # decision. Preserve those heads instead of rejecting the
                    # whole intent; the native bridge treats hold as no
                    # tactical mutation while still applying the two typed
                    # task labels.
                    if command_mode is None:
                        command_mode = "hold"
                    model_entry = {
                        "loop": current_loop,
                        "decision_id": decision_id,
                        "economy_intent": str(intent.economy),
                        "production_intent": str(intent.production),
                        "predicted_mode": predicted_mode,
                        "command_projection": command_projection,
                        "command_mode": command_mode or "rejected_unknown_mode",
                        "intent": intent.to_dict(),
                        "confidence": float(intent.confidence),
                        "probabilities": dict(intent.probabilities),
                        "observation_version": int(intent.observation_version),
                        "issuer_player_id": P2_PLAYER_ID,
                        "source": "ml_policy",
                        "model_schema": mode_model_summary.get("schema", ""),
                        "model_hash": mode_model_summary.get("checkpoint_sha256", ""),
                        "p2_resources_before": dict(p2_view.resources),
                        "p2_before": _p2_state(obs),
                        "acknowledged": False,
                    }
                    model_command = f"!ally {command_mode} {decision_id}"
                    queued, queue_error = _queue_runtime_ally_command(
                        model_command,
                        issuer_player_id=P2_PLAYER_ID,
                        source="ml_policy",
                        model_schema=str(mode_model_summary.get("schema", "")),
                        model_hash=str(mode_model_summary.get("checkpoint_sha256", "")),
                        decision_id=decision_id,
                        economy_intent=str(intent.economy),
                        production_intent=str(intent.production),
                    )
                    model_entry.update({
                        "message": model_command,
                        "transport": "bank_to_galaxy_p2_typed_intent",
                        "bridge_queued": queued,
                        "bridge_error": queue_error,
                    })
                    if queued:
                        total_commands_issued += 1
                        total_commands_dispatched += 1
                        cmd_ok_stats["ml_ally_mode"] += 1
                        cmd_ok_by_kind["ml_ally_mode"] += 1
                    else:
                        cmd_fail_stats["ml_ally_mode"] += 1
                        cmd_fail_by_kind["ml_ally_mode"] += 1
                    mode_model_decision_trace.append(model_entry)
                    last_mode_model_label = command_mode or predicted_mode

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

        # RequestSaveReplay is the native SC2 replay artifact. The JSONL file
        # above is intentionally kept as an auditable observation/browser
        # replay, but it cannot replace SC2's own replay container.
        try:
            native_response = await conn.send_request(
                sc_pb.Request(save_replay=sc_pb.RequestSaveReplay()),
                timeout=45,
                max_retries=2,
            )
            replay_data = bytes(native_response.save_replay.data)
            if not replay_data:
                native_replay_error = "RequestSaveReplay returned empty data"
            else:
                native_path = replay_path.with_suffix(".SC2Replay")
                native_path.write_bytes(replay_data)
                native_replay_path = str(native_path)
                if verbose:
                    print(f"  Native SC2 replay: {native_path}")
        except Exception as exc:
            native_replay_error = str(exc)
            if verbose:
                print(f"  Native SC2 replay unavailable: {exc}")

    finally:
        await conn.close()
        replay_fp.close()

    # 计算结果
    elapsed = time.time() - start_time
    p1_survivors = (
        len(_owner_state(final_obs, P1_PLAYER_ID)) if final_obs is not None else 0
    )
    p2_state = _p2_state(final_obs) if final_obs is not None else []
    ally_bank_final = _read_runtime_bank_section()
    native_ally_debug_final = _read_runtime_bank_section(
        "CMRERebornDebug", "debug"
    )
    signal_count_before = int(ally_bank_initial.get("signal_count", 0) or 0)
    signal_count_after = int(ally_bank_final.get("signal_count", 0) or 0)
    if (
        computer_ally
        and signal_count_after > signal_count_before
        and ally_bank_final.get("last_signal")
    ):
        p2_signal_trace.append({
            "loop": current_loop,
            "player_id": P2_PLAYER_ID,
            "message": ally_bank_final["last_signal"],
            "source": "galaxy_ui_message_bank_marker",
            "recipient_player_id": P1_PLAYER_ID,
            "request_ok": True,
        })
    native_p2_melee_init_observed = all(
        native_ally_debug_final.get(f"ally_{key}") == 1
        for key in (
            "computer_ally_ready",
            "p2_starting_units_initialized",
            "p2_starting_resources_initialized",
            "p2_native_ai_path",
        )
    )
    p1_visible_alliance_values = sorted({
        int(item.get("alliance", 0))
        for item in (final_obs.visible_allies if final_obs is not None else [])
        if int(item.get("owner", 0)) == P1_PLAYER_ID
    })
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

    p2_state_delta_observed = bool(
        initial_p2_state
        and latest_p2_state
        and initial_p2_state != latest_p2_state
    )
    p2_command_ack_observed = any(
        item.get("completed")
        and item.get("bank_after", {}).get("last_result")
        in {"status", "acknowledged", "attack_issued", "attack_no_target", "hold"}
        for item in ally_command_trace
    ) or bool(p2_signal_trace)
    mode_model_typed_intent_ok = (
        not bool(mode_model_path)
        or any(
            item.get("bridge_queued")
            and item.get("acknowledged")
            and item.get("issuer_player_id") == P2_PLAYER_ID
            and item.get("source") == "ml_policy"
            and item.get("economy_intent")
            and item.get("production_intent")
            and item.get("bank_after", {}).get("last_model_economy")
                == item.get("economy_intent")
            and item.get("bank_after", {}).get("last_model_production")
                == item.get("production_intent")
            for item in mode_model_decision_trace
        )
    )
    mode_model_bridge_ok = (
        not bool(mode_model_path)
        or any(
            item.get("bridge_queued")
            and item.get("acknowledged")
            and item.get("issuer_player_id") == P2_PLAYER_ID
            and item.get("source") == "ml_policy"
            and item.get("model_hash") == mode_model_summary.get("checkpoint_sha256")
            for item in mode_model_decision_trace
        )
        and mode_model_typed_intent_ok
    )

    # A native run is complete only when SC2 emits a player_result. Reaching
    # max_loops while units are alive is an observation cutoff, not victory.
    p1_result = native_player_results.get(P1_PLAYER_ID)
    if p1_result == 1:
        verdict = "victory"
        end_reason = "player_result_victory"
        summary = f"SC2 player_result=Victory at loop {current_loop}"
    elif p1_result == 2 or p1_survivors == 0:
        verdict = "defeat"
        end_reason = "player_result_defeat" if p1_result == 2 else "p1_units_eliminated"
        summary = f"玩家在 loop {current_loop} 全灭"
    else:
        verdict = "inconclusive"
        end_reason = "max_loops_reached" if current_loop >= max_loops else "game_over_without_player_result"
        summary = f"对局在 loop {current_loop} 结束"

    if computer_ally:
        strategy_audit = audit_native_strategy(
            action_result_trace,
            initial_observation=(initial_obs.__dict__ if initial_obs is not None else None),
            final_observation=(final_obs.__dict__ if final_obs is not None else None),
            expected_player_id=P1_PLAYER_ID,
            required_buildings=("Barracks", "Refinery"),
            required_units=("Marine",),
        )
        strategy_audit = {
            **strategy_audit,
            "mode": "native_p1_map_driven_with_p2_computer_ally",
            "checks": {
                **strategy_audit.get("checks", {}),
                "state_observed_before_after": p2_state_delta_observed,
                "p2_computer_roster": _has_p1_p2_computer_roster(player_roster),
                "p2_command_acknowledged": p2_command_ack_observed,
                "p2_owned_units_observed": bool(p2_state),
                "p2_native_melee_init_observed": native_p2_melee_init_observed,
                "map_source_resolved": map_source_summary.get("status") == "resolved",
                "native_player_result_victory": p1_result == 1,
                "raw_p2_actions_issued": False,
                "mode_model_bridge": mode_model_bridge_ok,
                "mode_model_typed_intent": mode_model_typed_intent_ok,
            },
        }
        if not mode_model_bridge_ok:
            strategy_audit["status"] = "FAIL"
    else:
        strategy_audit = audit_native_strategy(
            action_result_trace,
            initial_observation=(initial_obs.__dict__ if initial_obs is not None else None),
            final_observation=(final_obs.__dict__ if final_obs is not None else None),
            expected_player_id=strategy_player_id,
            required_buildings=("Barracks", "Refinery"),
            required_units=("Marine",),
        )

    map_objective_trace = (
        list(policy.objective_trace)
        if isinstance(policy, MapDrivenP1Policy)
        else []
    )
    replay_html_path = replay_path.with_name("full-map-player.html") if render_html else Path("")
    report = LiveGameReport(
        map_name=map_name,
        end_loop=current_loop,
        end_reason=end_reason,
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
            "strategy_player_id_is_p1": computer_ally and strategy_player_id == P1_PLAYER_ID,
            "p1_p2_computer_roster": computer_ally and _has_p1_p2_computer_roster(player_roster),
            "strategy_player_id_is_p2": (not computer_ally) and strategy_player_id == P2_PLAYER_ID,
            "p1_p2_participant_roster": (not computer_ally) and _has_p1_p2_participant_roster(player_roster),
            "p2_owned_units_observed": len(p2_state) > 0,
            "action_results_correlated": action_result_count_mismatches == 0,
            "action_success_observed": (
                cmd_ok_stats.get("dispatched", 0) > 0 if computer_ally
                else cmd_ok_stats.get("dispatched", 0) > 0
            ),
            "native_strategy_action_success": strategy_audit["status"] == "PASS",
            "p2_roster_observed": bool(p2_state),
            "p2_visible_as_p1_ally": any(
                int(item.get("owner", 0)) == P2_PLAYER_ID
                and int(item.get("alliance", 0)) == 2
                for item in (final_obs.visible_allies if final_obs is not None else [])
            ),
            "p2_command_ack_observed": p2_command_ack_observed,
            "p2_native_melee_init_observed": native_p2_melee_init_observed,
            "p2_starting_units_initialized": native_ally_debug_final.get(
                "ally_p2_starting_units_initialized"
            ) == 1,
            "p2_starting_resources_initialized": native_ally_debug_final.get(
                "ally_p2_starting_resources_initialized"
            ) == 1,
            "native_strategy_no_debug_injection": strategy_audit["checks"][
                "no_debug_injection"
            ],
            "native_strategy_state_delta": strategy_audit["checks"][
                "state_observed_before_after"
            ],
            "p1_command_received": bool(p1_command_trace),
            "p2_signal_observed": bool(p2_signal_trace),
            "p2_ml_model_bridge": mode_model_bridge_ok,
            "p2_ml_typed_intent_bridge": mode_model_typed_intent_ok,
            "p1_ml_model_loaded": bool(p1_model_summary.get("enabled")),
            "p1_ml_decision_observed": bool(
                isinstance(policy, MapDrivenP1Policy) and policy.ml_decision_trace
            ),
            "p1_ml_dispatch_label_observed": bool(
                isinstance(policy, MapDrivenP1Policy)
                and any(item.get("dispatch_label") for item in policy.ml_decision_trace)
            ),
            "p2_ml_economy_intent_observed": any(
                item.get("acknowledged") and item.get("economy_intent")
                for item in mode_model_decision_trace
            ),
            "p2_ml_production_intent_observed": any(
                item.get("acknowledged") and item.get("production_intent")
                for item in mode_model_decision_trace
            ),
            "p2_ml_decision_observed": bool(mode_model_decision_trace),
            "p2_ml_decision_acknowledged": any(
                item.get("acknowledged") for item in mode_model_decision_trace
            ),
            "ally_mode_observed": bool(
                (computer_ally and p2_command_ack_observed)
                or (ally_policy is not None and ally_policy.mode_history)
            ),
        },
        strategy_audit=strategy_audit,
        behavior_verdict=(
            "pass"
            if strategy_audit["status"] == "PASS"
            else "fail"
        ),
        local_map_path=local_map_path,
        replay_log_path=str(replay_path),
        replay_html_path=str(replay_html_path) if render_html else "",
        native_replay_path=native_replay_path,
        native_replay_error=native_replay_error,
        native_player_results={str(key): value for key, value in native_player_results.items()},
        map_source_audit_path=map_source_audit_file,
        map_source_summary=map_source_summary,
        map_objective_trace=map_objective_trace,
        observed_player_id=strategy_player_id,
        p2_unit_count=len(p2_state),
        p2_alliance_values=sorted({int(item.get("alliance", 0)) for item in p2_state}),
        p1_visible_alliance_values=p1_visible_alliance_values,
        player_roster=player_roster,
        ally_command_trace=ally_command_trace,
        chat_received=chat_received,
        p1_command_trace=p1_command_trace,
        p2_signal_trace=p2_signal_trace,
        ally_mode_history=(ally_policy.mode_history if ally_policy is not None else []),
        ally_bank_initial=ally_bank_initial,
        ally_bank_final=ally_bank_final,
        native_ally_debug_initial=native_ally_debug_initial,
        native_ally_debug_final=native_ally_debug_final,
        runtime_catalog_summary=runtime_catalog_summary,
        mode_model_summary=mode_model_summary,
        mode_model_decision_trace=mode_model_decision_trace,
        p1_model_summary=p1_model_summary,
        p1_model_decision_trace=(
            list(policy.ml_decision_trace)
            if isinstance(policy, MapDrivenP1Policy)
            else []
        ),
    )

    # Keep the report as a final JSONL record so the same file is both a
    # browser replay source and an auditable native-runtime evidence stream.
    with replay_path.open("a", encoding="utf-8") as summary_fp:
        summary_fp.write(json.dumps({
            "record_type": "summary",
            "status": report.verdict.upper(),
            "runtime_report": report.__dict__,
        }, ensure_ascii=False) + "\n")

    if render_html:
        try:
            from .replay_player import load_replay, render_player_html
            render_player_html(load_replay(replay_path), replay_path, replay_html_path)
        except Exception as exc:
            report.replay_html_path = ""
            if verbose:
                print(f"  Browser replay unavailable: {exc}")

    if verbose:
        print(f"\n=== 真机对局结束 ===")
        print(f"地图: {report.map_name}")
        print(f"结果: {report.verdict.upper()}")
        print(f"Loop: {report.end_loop}/{max_loops} ({report.end_loop/max_loops:.0%})")
        print(f"耗时: {report.duration_sec}s")
        print(f"Player 1 幸存: {report.player1_survivors}")
        print(f"P2 盟友可见单位: {report.p2_unit_count} alliance={report.p2_alliance_values}")
        print(f"P2 视角 P1 alliance: {report.p1_visible_alliance_values}")
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
        print(f"原生 SC2 回放: {report.native_replay_path}")
        print(f"地图源审计: {report.map_source_audit_path}")
        if report.replay_html_path:
            print(f"可选浏览器投影: {report.replay_html_path}")

    return report


def main():
    parser = argparse.ArgumentParser(description="亡者之夜 AI 盟友真机自主对局")
    parser.add_argument("--port", type=int, default=5000, help="SC2 API 端口")
    parser.add_argument("--map", type=str, default=DEFAULT_MAP, help="地图文件路径")
    parser.add_argument(
        "--anchor",
        action="store_true",
        help="旧双 Participant 探针：作为 P1 anchor 创建对局并发送盟友指令",
    )
    parser.add_argument(
        "--participant-p2",
        dest="computer_ally",
        action="store_false",
        help="显式启用旧双 Participant P2 策略路径；默认使用单客户端 Computer P2",
    )
    parser.add_argument(
        "--anchor-wait-sec",
        type=float,
        default=90.0,
        help="P1 anchor 保持连接并提供命令通道的秒数",
    )
    parser.add_argument(
        "--anchor-output",
        type=str,
        default=None,
        help="P1 anchor 报告 JSON 路径",
    )
    parser.add_argument("--max-loops", type=int, default=2000, help="最大 loop 数")
    parser.add_argument("--step-size", type=int, default=4, help="每次 Step 帧数")
    parser.add_argument("--decision-interval", type=int, default=22, help="决策间隔（帧数）")
    parser.add_argument(
        "--embed-map-data",
        action="store_true",
        help="显式使用 SC2 API map_data 嵌入路径（仅用于 transport-only probes）",
    )
    parser.add_argument(
        "--join-existing",
        action="store_true",
        help="跳过 CreateGame，加入由另一个 API client 创建的当前对局",
    )
    parser.add_argument(
        "--multiplayer-ports",
        action="store_true",
        help="JoinGame 时提交共享 server/client 端口拓扑（需要多个 SC2 client）",
    )
    parser.add_argument(
        "--anchor-multiplayer-ports",
        action="store_true",
        help="P1 anchor JoinGame 时提交完整双 participant 端口拓扑",
    )
    parser.add_argument(
        "--multiplayer-port-base",
        type=int,
        default=MULTIPLAYER_PORT_BASE,
        help="共享 multiplayer Portconfig 的 server game_port 起点",
    )
    parser.add_argument(
        "--replay-log",
        type=str,
        default=None,
        help="真机 JSONL 审计日志路径；原生 SC2Replay 与其同目录",
    )
    parser.add_argument(
        "--map-source",
        type=str,
        default=None,
        help="unpacked .SC2Map source directory; otherwise resolve by runtime map name",
    )
    parser.add_argument(
        "--map-source-audit",
        type=str,
        default=None,
        help="raw map source audit JSON path",
    )
    parser.add_argument(
        "--render-html",
        action="store_true",
        help="explicitly enable the legacy browser projection; disabled by default",
    )
    parser.add_argument(
        "--mode-model",
        type=str,
        default=None,
        help="P2 imitation-learning checkpoint; model output is sent through the explicit Galaxy P2 bridge",
    )
    parser.add_argument(
        "--p1-model",
        type=str,
        default=None,
        help="P1 PyTorch high-level action checkpoint; map source resolves targets and native transport validates actions",
    )
    parser.add_argument("--quiet", action="store_true", help="静默模式")
    parser.add_argument("--realtime", action="store_true", help="realtime 模式（Reborn 地图需要）")
    parser.add_argument("--output", type=str, default=None, help="报告输出 JSON 路径")
    args = parser.parse_args()

    if args.anchor:
        anchor_report = asyncio.run(run_p1_anchor(
            port=args.port,
            map_path=args.map,
            wait_sec=args.anchor_wait_sec,
            verbose=not args.quiet,
            output_path=args.anchor_output or args.output,
            multiplayer_port_base=args.multiplayer_port_base,
            multiplayer_ports=args.anchor_multiplayer_ports,
        ))
        if args.quiet:
            print(json.dumps(anchor_report, ensure_ascii=False))
        return 0 if anchor_report.get("status") == "PASS" else 1

    report = asyncio.run(run_live(
        port=args.port,
        map_path=args.map,
        max_loops=args.max_loops,
        step_size=args.step_size,
        decision_interval=args.decision_interval,
        verbose=not args.quiet,
        force_map_path=not args.embed_map_data,
        join_existing=args.join_existing,
        multiplayer_ports=args.multiplayer_ports,
        multiplayer_port_base=args.multiplayer_port_base,
        replay_log_path=args.replay_log,
        computer_ally=args.computer_ally,
        map_source_dir=args.map_source,
        map_source_audit_path=args.map_source_audit,
        render_html=args.render_html,
        mode_model_path=args.mode_model,
        p1_model_path=args.p1_model,
        realtime=args.realtime,
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
