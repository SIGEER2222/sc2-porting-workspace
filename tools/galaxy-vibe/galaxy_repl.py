#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SC2 Vibe REPL — P1 最小热循环（所见即所得 vibe 调试）。

连接运行中 SC2 的 SC2API（ws://127.0.0.1:<port>/sc2api），提供交互式 vibe 调试。
核心目的：写/调一段逻辑，秒级在运行的游戏里看到效果，无需重编译/重开。

命令（help 查看）：
  ping                              -> 调试 Mod (dbg ping)，并读回 Bank 验证闭环
  invoke <function_id> [key=value...] -> 调用显式注册的 typed Vibe function
  echo <text>                       -> 调试 Mod (dbg echo)
  spawn <type> <count> [player] [@x,y]   -> SC2API DebugCreateUnit（秒级刷兵）
  kill <all|player N|tag t1 t2...>  -> SC2API DebugKillUnit
  set <hp|energy|shields> <val> <player N|tag t1 t2...>  -> SC2API DebugSetUnitValue
  cheat <kind> <on|off>             -> SC2API DebugGameState 全 12 项开关
                                       kind ∈ show_map/control_enemy/food/free/
                                       all_resources/god/minerals/gas/cooldown/
                                       tech_tree/upgrade/fast_build
  endgame <victory|surrender>       -> SC2API DebugEndGame
  testproc <hang|crash|exit> [ms]   -> SC2API DebugTestProcess（破坏性，仅供排错）
  setscore <score:float>            -> SC2API DebugSetScore
  draw text <text> [@x,y]           -> SC2API DebugDraw.text（屏幕绘制文本）
  draw line <x1,y1> <x2,y2>         -> SC2API DebugDraw.lines（世界坐标线段）
  draw box <x1,y1> <x2,y2>          -> SC2API DebugDraw.boxes（世界坐标方框）
  draw clear                        -> 清空所有调试绘制
  query [player N]                  -> SC2API Observation 汇总单位/资源
  obs                               -> 一次 Observation 原始摘要
  info                              -> SC2API GameInfo（地图尺寸/玩家）
  step [n]                          -> SC2API Step（推进 n 帧，默认 1）
  help                              -> 本帮助
  exit / quit                       -> 退出

非交互：
  --cmd "spawn marine 5 1"          -> 执行单条命令后退出
  --script file.txt                 -> 逐行执行文件中的命令后退出

依赖：aiohttp + s2clientprotocol（优先 vendored reference/SC2-Neuro-API-Integration，
      否则回退 pip 安装的 s2clientprotocol / python-sc2）。必须在能跑 SC2 的真机运行。

证据分类：
  - spawn/kill/set/cheat/query/step/info/obs 走 SC2API，字段名取自 vendored python-sc2
    client.py 与 debug_pb2 描述符文本（static 已核对）。
  - invoke 走正式 Vibe Bank/PollLoop 分发器；ping/echo 保留为独立调试命令。
  - 真机闭环为 runtime 证据，待 master 真机验证。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import shlex
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

REPO_ROOT = Path(__file__).resolve().parents[2]
NEURO = REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"
sys.path.insert(0, str(NEURO))
sys.path.insert(0, str(REPO_ROOT / "tools" / "galaxy-vibe"))

HAS_PROTO = False
PROTO_ERR = ""
try:
    from s2clientprotocol import sc2api_pb2 as sc_pb
    from s2clientprotocol import debug_pb2 as debug_pb
    from s2clientprotocol import common_pb2 as common_pb

    HAS_PROTO = True
except Exception as e:  # pragma: no cover
    PROTO_ERR = str(e)

import aiohttp  # 同 sc2-observer

from host.vibe_host import RpcRequest, write_bank_request  # noqa: E402
from vibe.debug_vm import DebugVm, load_function_catalog, load_function_metadata  # noqa: E402
from vibe.function_registry import FunctionRegistryError, coerce_cli_args  # noqa: E402

DEFAULT_BANK = Path.home() / "Documents" / "StarCraft II" / "Banks" / "GalaxyVibeDebug.SC2Bank"
DEFAULT_RPC_BANK = Path.home() / "Documents" / "StarCraft II" / "Banks" / "GalaxyVibe.SC2Bank"

# 断言结果落盘（外部完全可控，不碰 Bank；供冷循环/CI 消费）
ASSERT_REPORT_PATH = REPO_ROOT / "artifacts" / "galaxy-vibe" / "assert-results.json"

# unit_value 映射（依据 python-sc2 client.py doc：1=energy, 2=life, 3=shields）
UNIT_VALUE = {"energy": 1, "hp": 2, "life": 2, "shields": 3}

# DebugGameState 枚举（取自 vendored debug_pb2 DebugGameState enum，全部 12 项）
# 用 on/off 切换：on=枚举值，off=0
GAME_STATE_CHEAT = {
    "show_map": 1,        # 显示全图
    "control_enemy": 2,   # 可控制敌方单位
    "food": 3,            # 无视人口上限
    "free": 4,            # 免费建造（无资源/无建造需求）
    "all_resources": 5,   # 资源无限
    "god": 6,             # 上帝模式（无敌）
    "minerals": 7,        # 矿物无限
    "gas": 8,             # 瓦斯无限
    "vespene": 8,         # gas 别名
    "cooldown": 9,        # 无冷却
    "tech_tree": 10,      # 解锁全部科技
    "upgrade": 11,        # 给予全部升级
    "fast_build": 12,     # 快速建造
}

# DebugEndGame.EndResult 枚举
END_GAME_RESULT = {"surrender": 1, "victory": 2, "declare_victory": 2}

# DebugTestProcess.Test 枚举
TEST_PROCESS_TEST = {"hang": 1, "crash": 2, "exit": 3}

# DebugSetUnitValue.UnitValue 枚举（1=energy, 2=life, 3=shields）


def utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_unit_map() -> dict[str, int]:
    """构建单位名->id 映射。优先 python-sc2 的 UnitTypeId（权威）；不可用时解析 vendored
    unit_typeid.py 源码拿准确 id；都不行则回退空表（只认整数 id，不猜值）。"""
    umap: dict[str, int] = {}
    # 1) 优先 import python-sc2 的枚举（运行时值与 DebugCreateUnit.unit_type 一致）
    try:
        from sc2.ids.unit_typeid import UnitTypeId  # type: ignore

        for k, v in UnitTypeId.__members__.items():
            umap[k] = int(v.value)
        if umap:
            return umap
    except Exception:
        pass
    # 2) 解析 vendored 源码（避免重依赖 import，且 id 准确）
    import re

    cand = REPO_ROOT / "reference" / "python-sc2" / "sc2" / "ids" / "unit_typeid.py"
    if cand.exists():
        txt = cand.read_text(encoding="utf-8", errors="replace")
        for mm in re.finditer(r"^\s*([A-Z][A-Z0-9_]+)\s*=\s*(\d+)\s*$", txt, re.M):
            umap[mm.group(1)] = int(mm.group(2))
    return umap


UNIT_MAP = _build_unit_map()


def _unit_id_resolver():
    """返回一个 name->int 解析函数。整数直接回传；英文名查 UNIT_MAP（python-sc2 / 源码）。"""

    def resolve(name: str) -> int | None:
        s = name.strip()
        if s.isdigit():
            return int(s)
        return UNIT_MAP.get(s.upper().replace(" ", ""))

    return resolve


def _unit_name_lookup():
    """返回一个 int->name 函数（用于 query 展示）。"""
    rev = {v: k for k, v in UNIT_MAP.items()}
    return lambda i: rev.get(i, str(i))


async def send_request(ws, req_proto, timeout: float = 15.0):
    await ws.send_bytes(req_proto.SerializeToString())
    data = await asyncio.wait_for(ws.receive_bytes(), timeout=timeout)
    resp = sc_pb.Response()
    resp.ParseFromString(data)
    return resp


def parse_bank(bank_path: Path) -> dict:
    import xml.etree.ElementTree as ET

    if not bank_path.exists():
        return {}
    try:
        root = ET.parse(bank_path).getroot()
    except ET.ParseError:
        return {}
    parsed: dict = {}
    for section in root.findall("Section"):
        sn = section.get("name", "")
        if not sn:
            continue
        sd: dict = {}
        for key in section.findall("Key"):
            kn = key.get("name", "")
            vn = key.find("Value")
            if vn is None:
                continue
            if "int" in vn.attrib:
                try:
                    sd[kn] = int(vn.attrib["int"])
                except ValueError:
                    sd[kn] = vn.attrib["int"]
            elif "string" in vn.attrib:
                sd[kn] = vn.attrib["string"]
            elif "text" in vn.attrib:
                sd[kn] = vn.attrib["text"]
            elif "flag" in vn.attrib:
                sd[kn] = vn.attrib["flag"] == "1"
        parsed[sn] = sd
    return parsed


def _resume_sequence_from_bank(session_id: str, bank_path: Path = DEFAULT_RPC_BANK) -> int:
    """Recover the highest response sequence for a session before sending again."""
    highest = 0
    for raw_response in parse_bank(bank_path).get("response", {}).values():
        if not isinstance(raw_response, str):
            continue
        try:
            response = json.loads(raw_response)
        except json.JSONDecodeError:
            continue
        if response.get("session_id") != session_id:
            continue
        sequence = response.get("sequence")
        if isinstance(sequence, int) and not isinstance(sequence, bool):
            highest = max(highest, sequence)
    return highest


async def wait_bank_run_id(bank_path: Path, run_id: str, timeout: float = 5.0, poll: float = 0.1):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if bank_path.exists():
            vibe = parse_bank(bank_path).get("vibe", {})
            if vibe.get("run_id") == run_id:
                return True, time.time() - t0, vibe
        await asyncio.sleep(poll)
    return False, timeout, {}


def _split_flags(args):
    """从断言参数里抽出 --player N / --within S（支持 `--player=N` 形式），其余原样返回。"""
    rest, player, within = [], None, None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--player" and i + 1 < len(args):
            try:
                player = int(args[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if a.startswith("--player="):
            try:
                player = int(a.split("=", 1)[1])
            except ValueError:
                pass
            i += 1
            continue
        if a == "--within" and i + 1 < len(args):
            try:
                within = float(args[i + 1])
            except ValueError:
                pass
            i += 2
            continue
        if a.startswith("--within="):
            try:
                within = float(a.split("=", 1)[1])
            except ValueError:
                pass
            i += 1
            continue
        rest.append(a)
        i += 1
    return rest, player, within


class VibeREPL:
    def __init__(
        self,
        port: int,
        resolve,
        name_lookup,
        map_path: str = "",
        join_wait: float = 15.0,
        rpc_session_id: str = "",
        realtime: bool = False,
    ):
        self.port = port
        self.resolve = resolve
        self.name_lookup = name_lookup
        self.map_path = map_path
        self.join_wait = join_wait
        self.realtime = realtime
        self.map_center = common_pb.Point2D(x=50.0, y=50.0)
        self._have_map = False
        self._resume_requested = bool(rpc_session_id)
        self.assert_results: list[dict] = []
        self.rpc_session_id = rpc_session_id or ("repl_" + uuid.uuid4().hex[:12])
        self.rpc_sequence = 0

    async def connect(self):
        url = f"ws://127.0.0.1:{self.port}/sc2api"
        self.session = aiohttp.ClientSession()
        self.ws = await self.session.ws_connect(url, max_msg_size=0)
        # 连通性 ping
        resp = await send_request(self.ws, sc_pb.Request(ping=sc_pb.RequestPing()))
        if resp.error:
            raise RuntimeError(f"SC2API ping error: {resp.error}")
        if self._resume_requested:
            self.rpc_sequence = _resume_sequence_from_bank(self.rpc_session_id)
        if self.map_path:
            await self.ensure_in_game(self.map_path)
        # 拉一次 GameInfo 拿地图中心（失败不影响核心功能）
        try:
            gi = await send_request(self.ws, sc_pb.Request(game_info=sc_pb.RequestGameInfo()))
            ms = gi.game_info.start_raw.map_size
            self.map_center = common_pb.Point2D(x=ms.x / 2.0, y=ms.y / 2.0)
            self._have_map = True
        except Exception:
            pass
        return True

    async def ensure_in_game(self, map_path: str) -> None:
        """Run CreateGame + JoinGame on the same websocket used by REPL commands."""
        normalized_map = str(Path(map_path).resolve()).replace("\\", "/")
        try:
            await send_request(self.ws, sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), timeout=10.0)
            await asyncio.sleep(1.0)
        except Exception:
            pass

        player_sets = [
            [sc_pb.PlayerSetup(type=1, race=1, player_name="P1")],
            [
                sc_pb.PlayerSetup(type=1, race=1, player_name="P1"),
                sc_pb.PlayerSetup(type=2, race=1, difficulty=2, player_name="AI"),
            ],
        ]
        created = False
        last_error = ""
        for setup in player_sets:
            req = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
                local_map=sc_pb.LocalMap(map_path=normalized_map),
                player_setup=setup,
                realtime=self.realtime,
            ))
            try:
                resp = await send_request(self.ws, req, timeout=60.0)
            except Exception as exc:
                last_error = str(exc)
                continue
            if resp.error:
                last_error = repr(list(resp.error))
                continue
            if resp.HasField("create_game") and resp.create_game.HasField("error"):
                last_error = f"{resp.create_game.error} {resp.create_game.error_details}"
                continue
            created = True
            print(f"[game] CreateGame OK: {normalized_map}")
            break
        if not created:
            print(f"[game] CreateGame not confirmed, attempting JoinGame anyway: {last_error}")

        join_req = sc_pb.Request(join_game=sc_pb.RequestJoinGame(
            race=1,
            options=sc_pb.InterfaceOptions(raw=True, score=True),
        ))
        joined = False
        last_join_error = ""
        for attempt in range(30):
            try:
                resp = await send_request(self.ws, join_req, timeout=30.0)
                if resp.error:
                    last_join_error = repr(list(resp.error))
                    await asyncio.sleep(0.5)
                    continue
                if resp.HasField("join_game") and resp.join_game.HasField("error"):
                    last_join_error = f"{resp.join_game.error} {resp.join_game.error_details}"
                    await asyncio.sleep(0.5)
                    continue
                joined = True
                player_id = resp.join_game.player_id if resp.HasField("join_game") else 0
                print(f"[game] JoinGame OK player_id={player_id}")
                break
            except Exception as exc:
                last_join_error = str(exc)
                await asyncio.sleep(0.5)
        if not joined:
            try:
                obs = await send_request(self.ws, sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=15.0)
                if not obs.error:
                    joined = True
                    print("[game] Observation OK; treating client as in_game")
            except Exception as exc:
                last_join_error = str(exc)
        if not joined:
            raise RuntimeError(f"JoinGame failed and client is not in_game: {last_join_error}")
        if self.join_wait > 0:
            print(f"[game] Advancing {self.join_wait:.1f}s for map scripts to initialize...")
            await self.advance_game(seconds=self.join_wait, step_count=8, sleep_seconds=0.25)

    async def advance_game(self, seconds: float = 0.0, step_count: int = 1, sleep_seconds: float = 0.1) -> bool:
        """Advance frames for non-realtime CreateGame sessions while preserving wall-clock waits."""
        deadline = time.time() + max(0.0, seconds)
        advanced = False
        while True:
            try:
                resp = await send_request(
                    self.ws,
                    sc_pb.Request(step=sc_pb.RequestStep(count=max(1, step_count))),
                    timeout=5.0,
                )
                if resp.error:
                    return advanced
                advanced = True
            except Exception:
                return advanced
            if time.time() >= deadline:
                return advanced
            await asyncio.sleep(max(0.0, sleep_seconds))

    @staticmethod
    def _unit_is_alive(unit) -> bool:
        return getattr(unit, "health", 1) > 0

    async def close(self):
        try:
            await self.ws.close()
            await self.session.close()
        except Exception:
            pass

    # ---------- 各命令实现 ----------
    async def cmd_ping(self, args):
        run_id = f"repl_{int(time.time() * 1000)}"
        await send_request(self.ws, sc_pb.Request(map_command=sc_pb.RequestMapCommand(trigger_cmd=f"dbg ping {run_id}")))
        ok, lat, sec = await wait_bank_run_id(DEFAULT_BANK, run_id, timeout=5.0)
        if ok and sec.get("result") == "pong":
            print(f"[ping] OK 闭环闭合 latency={lat*1000:.0f}ms run_id={run_id}")
        else:
            print(f"[ping] 未确认闭环（Mod 未挂？或 Bank 未回写）run_id={run_id}")
        return True

    async def invoke_function_request(self, function_id: str, call_args: dict):
        """Send one validated function.invoke and return its structured result."""
        try:
            coerce_cli_args(function_id, {key: str(value) for key, value in call_args.items()})
        except FunctionRegistryError as exc:
            return {"kind": "error", "error_code": exc.code, "payload": {"reason": exc.detail}}
        self.rpc_sequence += 1
        request = RpcRequest(
            session_id=self.rpc_session_id,
            request_id=uuid.uuid4().hex[:12],
            sequence=self.rpc_sequence,
            operation="function.invoke",
            args={"function_id": function_id, "args": call_args},
        )
        try:
            if not write_bank_request("GalaxyVibe", request.request_id, request):
                return {"kind": "error", "error_code": "INTERNAL_ERROR", "payload": {"reason": "bank_write_failed"}}
        except Exception as exc:
            return {"kind": "error", "error_code": "INTERNAL_ERROR", "payload": {"reason": str(exc)}}
        deadline = time.time() + 5.0
        raw = ""
        while time.time() < deadline:
            data = parse_bank(DEFAULT_RPC_BANK)
            raw = data.get("response", {}).get(request.request_id, "")
            if raw:
                break
            # CreateGame(realtime=False) 只会在 RequestStep 后推进 Galaxy
            # PollLoop/BankPoll；sleep 本身不会推进游戏帧。
            try:
                step_resp = await send_request(
                    self.ws,
                    sc_pb.Request(step=sc_pb.RequestStep(count=1)),
                    timeout=5.0,
                )
                if step_resp.error:
                    # 兼容 realtime 会话：step 被拒绝时继续 wall-clock 轮询。
                    pass
            except Exception:
                pass
            await asyncio.sleep(0.1)
        if not raw:
            return {
                "kind": "error",
                "error_code": "INTERNAL_ERROR",
                "request_id": request.request_id,
                "payload": {"reason": "timeout"},
            }
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {
                "kind": "error",
                "error_code": "INTERNAL_ERROR",
                "request_id": request.request_id,
                "payload": {"reason": "malformed_response", "raw": raw},
            }

    async def cmd_invoke(self, args):
        if not args:
            print("[invoke] usage: invoke <function_id> [key=value ...]")
            return True
        function_id = args[0]
        raw_args = {}
        for item in args[1:]:
            if "=" not in item:
                print("[invoke] arguments must use key=value")
                return True
            key, value = item.split("=", 1)
            if not key:
                print("[invoke] argument name cannot be empty")
                return True
            raw_args[key] = value
        try:
            call_args = coerce_cli_args(function_id, raw_args)
        except FunctionRegistryError as exc:
            print(f"[invoke] {exc.code}: {exc.detail}")
            return True
        parsed = await self.invoke_function_request(function_id, call_args)
        print(f"[invoke] {parsed.get('error_code')} payload={parsed.get('payload', {})}")
        return True

    async def cmd_vm(self, args):
        if not args:
            print("[vm] usage: vm <program.json>")
            return True
        program_path = Path(args[0]).resolve()
        if not program_path.exists():
            print(f"[vm] program not found: {program_path}")
            return False
        try:
            program = json.loads(program_path.read_text(encoding="utf-8-sig"))
            metadata = load_function_metadata()
            catalog_path = program.get("catalog_path")
            if catalog_path:
                catalog_file = (program_path.parent / catalog_path).resolve()
            else:
                catalog_file = REPO_ROOT / "artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/discovery/function-catalog.json"
            if not catalog_file.is_relative_to(REPO_ROOT):
                print(f"[vm] catalog path must stay inside repository: {catalog_file}")
                return False
            catalog = load_function_catalog(catalog_file) if catalog_file.exists() else []

            class ReplBridge:
                async def call(inner_self, function_id, call_args):
                    return await self.invoke_function_request(function_id, call_args)

                async def step(inner_self, loops):
                    response = await send_request(
                        self.ws,
                        sc_pb.Request(step=sc_pb.RequestStep(count=loops)),
                        timeout=10.0,
                    )
                    if response.error:
                        return {"kind": "error", "error_code": "STEP_FAILED", "payload": {"errors": list(response.error)}}
                    return {"kind": "result", "error_code": "OK", "payload": {"requested_loops": loops}}

            result = await DebugVm(
                ReplBridge(),
                function_metadata=metadata,
                catalog=catalog,
            ).run(program)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return result["status"] == "passed"
        except Exception as exc:
            print(f"[vm] {exc}")
            return False

    async def cmd_echo(self, args):
        cmd = "dbg echo " + " ".join(args)
        resp = await send_request(self.ws, sc_pb.Request(map_command=sc_pb.RequestMapCommand(trigger_cmd=cmd)))
        if resp.error:
            print(f"[echo] error: {resp.error}")
        else:
            print(f"[echo] 已下发: {cmd}")
        return True

    async def cmd_spawn(self, args):
        # spawn <type> <count> [player] [@x,y]
        if len(args) < 2:
            print("[spawn] 用法: spawn <type> <count> [player] [@x,y]")
            return True
        uid = self.resolve(args[0])
        if uid is None:
            print(f"[spawn] 未知单位类型: {args[0]}（用整数 id 或 python-sc2 支持的英文名）")
            return True
        try:
            count = int(args[1])
        except ValueError:
            print("[spawn] count 必须是整数")
            return True
        player = 1
        pos = self.map_center
        rest = args[2:]
        if rest and not rest[0].startswith("@"):
            try:
                player = int(rest[0])
                rest = rest[1:]
            except ValueError:
                pass
        if rest and rest[0].startswith("@"):
            coord = rest[0][1:]
            try:
                x, y = (float(v) for v in coord.split(","))
                pos = common_pb.Point2D(x=x, y=y)
            except ValueError:
                print("[spawn] 坐标格式错误，应为 @x,y")
                return True
        before_count = None
        before_counts, before_err = await self._player_counts_by_id(player)
        if before_err is None:
            before_count = before_counts.get(uid, 0)

        req = sc_pb.Request(
            debug=sc_pb.RequestDebug(
                debug=[
                    debug_pb.DebugCommand(
                        create_unit=debug_pb.DebugCreateUnit(
                            unit_type=uid, owner=player, pos=pos, quantity=count
                        )
                    )
                ]
            )
        )
        resp = await send_request(self.ws, req)
        if resp.error:
            print(f"[spawn] error: {resp.error}")
        else:
            observed = None
            target_count = None if before_count is None else before_count + count
            deadline = time.time() + 3.0
            while time.time() < deadline:
                await self.advance_game(seconds=0.0, step_count=4, sleep_seconds=0.0)
                await asyncio.sleep(0.1)
                counts, err = await self._player_counts_by_id(player)
                if err is not None:
                    continue
                observed = counts.get(uid, 0)
                if (target_count is not None and observed >= target_count) or (
                    target_count is None and observed >= count
                ):
                    break
            suffix = f"; observed={observed}" if observed is not None else ""
            print(f"[spawn] 已创建 {count}x {args[0]} -> player {player} @({pos.x},{pos.y}){suffix}")
        return True

    async def _collect_units(self, player=None):
        resp = await send_request(self.ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
        if resp.error:
            print(f"[obs] error: {resp.error}")
            return []
        raw = resp.observation.observation.raw_data
        if raw is None:
            print("[obs] 无 raw_data（确认游戏以 raw 接口启动）")
            return []
        units = []
        for u in raw.units:
            if (player is None or u.owner == player) and self._unit_is_alive(u):
                units.append(u)
        return units

    async def cmd_kill(self, args):
        rest, player_filter, _within = _split_flags(args)
        if not rest:
            print("[kill] 用法: kill <all|player N|tag t1 t2 ...|unit_type [--player N]>")
            return True
        targets = []
        if rest[0] == "all":
            units = await self._collect_units(player_filter)
            targets = [u.tag for u in units]
        elif rest[0] == "player" and len(rest) >= 2:
            units = await self._collect_units(int(rest[1]))
            targets = [u.tag for u in units]
        elif rest[0] == "tag":
            targets = [int(t) for t in rest[1:] if t.lstrip("-").isdigit()]
        else:
            uid = self.resolve(rest[0])
            if uid is not None:
                player = player_filter or 1
                units = await self._collect_units(player)
                targets = [u.tag for u in units if u.unit_type == uid]
            else:
                targets = [int(t) for t in rest if t.lstrip("-").isdigit()]
        if not targets:
            print("[kill] 未解析到目标单位")
            return True
        resp = await send_request(
            self.ws,
            sc_pb.Request(debug=sc_pb.RequestDebug(debug=[debug_pb.DebugCommand(kill_unit=debug_pb.DebugKillUnit(tag=targets))])),
        )
        if resp.error:
            print(f"[kill] error: {resp.error}")
        else:
            await self.advance_game(seconds=1.0, step_count=8, sleep_seconds=0.1)
            print(f"[kill] 已击杀 {len(targets)} 个单位")
        return True

    async def cmd_set(self, args):
        # set <hp|energy|shields> <val> <player N|tag t1 t2...>
        if len(args) < 3:
            print("[set] 用法: set <hp|energy|shields> <val> <player N|tag t1 t2 ...>")
            return True
        stat = args[0].lower()
        if stat not in UNIT_VALUE:
            print(f"[set] 未知属性: {stat}（支持 hp/energy/shields）")
            return True
        try:
            val = float(args[1])
        except ValueError:
            print("[set] val 必须是数字")
            return True
        rest = args[2:]
        targets = []
        if rest[0] == "player" and len(rest) >= 2:
            units = await self._collect_units(int(rest[1]))
            targets = [u.tag for u in units]
        elif rest[0] == "tag":
            targets = [int(t) for t in rest[1:] if t.lstrip("-").isdigit()]
        else:
            targets = [int(t) for t in rest if t.lstrip("-").isdigit()]
        if not targets:
            print("[set] 未解析到目标单位（用 player N 或 tag t1 t2）")
            return True
        cmds = [
            debug_pb.DebugCommand(
                unit_value=debug_pb.DebugSetUnitValue(unit_value=UNIT_VALUE[stat], value=val, unit_tag=t)
            )
            for t in targets
        ]
        resp = await send_request(self.ws, sc_pb.Request(debug=sc_pb.RequestDebug(debug=cmds)))
        if resp.error:
            print(f"[set] error: {resp.error}")
        else:
            print(f"[set] 已将 {len(targets)} 个单位的 {stat} 设为 {val}")
        return True

    async def cmd_cheat(self, args):
        if len(args) < 2:
            print("[cheat] 用法: cheat <kind> <on|off>  kind ∈ {show_map|control_enemy|food|free|all_resources|god|minerals|gas|cooldown|tech_tree|upgrade|fast_build}")
            return True
        kind = args[0].lower()
        if kind not in GAME_STATE_CHEAT:
            print(f"[cheat] 未知作弊: {kind}（支持 {sorted(GAME_STATE_CHEAT.keys())}）")
            return True
        on = args[1].lower() in ("on", "1", "true", "yes")
        # SC2 DebugGameState 是 toggle 语义：每次发请求都切换状态，枚举无 0 值。
        # on/off 都发同一枚举值；用户需自行记住当前状态（SC2 API 无查询当前作弊状态的接口）。
        state = GAME_STATE_CHEAT[kind]
        resp = await send_request(self.ws, sc_pb.Request(debug=sc_pb.RequestDebug(debug=[debug_pb.DebugCommand(game_state=state)])))
        if resp.error:
            print(f"[cheat] error: {resp.error}")
        else:
            action = "开启(toggle)" if on else "关闭(toggle)"
            print(f"[cheat] {kind} {action}  (DebugGameState={state}, SC2 切换语义)")
        return True

    async def cmd_endgame(self, args):
        # endgame <victory|surrender>  -> DebugEndGame
        if not args:
            print("[endgame] 用法: endgame <victory|surrender>  (victory=DeclareVictory, surrender=Surrender)")
            return True
        kind = args[0].lower()
        if kind not in END_GAME_RESULT:
            print(f"[endgame] 未知结果: {kind}（支持 victory/surrender）")
            return True
        resp = await send_request(
            self.ws,
            sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                debug_pb.DebugCommand(end_game=debug_pb.DebugEndGame(end_result=END_GAME_RESULT[kind]))
            ])),
        )
        if resp.error:
            print(f"[endgame] error: {resp.error}")
        else:
            print(f"[endgame] 已下发 {kind}（DebugEndGame.EndResult={END_GAME_RESULT[kind]}）")
        return True

    async def cmd_testproc(self, args):
        # testproc <hang|crash|exit> [delay_ms]  -> DebugTestProcess
        if not args:
            print("[testproc] 用法: testproc <hang|crash|exit> [delay_ms]")
            print("  注：hang/crash 会使 SC2 进程卡死/崩溃；exit 让 SC2 正常退出；仅供排错用。")
            return True
        kind = args[0].lower()
        if kind not in TEST_PROCESS_TEST:
            print(f"[testproc] 未知 test: {kind}（支持 hang/crash/exit）")
            return True
        delay_ms = 0
        if len(args) >= 2:
            try:
                delay_ms = int(args[1])
            except ValueError:
                print(f"[testproc] delay_ms 必须是整数: {args[1]}")
                return True
        resp = await send_request(
            self.ws,
            sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                debug_pb.DebugCommand(test_process=debug_pb.DebugTestProcess(
                    test=TEST_PROCESS_TEST[kind], delay_ms=delay_ms
                ))
            ])),
        )
        if resp.error:
            print(f"[testproc] error: {resp.error}")
        else:
            print(f"[testproc] 已下发 {kind} delay_ms={delay_ms}（注意：hang/crash 会破坏 SC2 进程）")
        return True

    async def cmd_setscore(self, args):
        # setscore <score>  -> DebugSetScore
        if not args:
            print("[setscore] 用法: setscore <score:float>  (设置玩家当前分数；仅在含分数的地图有效)")
            return True
        try:
            score = float(args[0])
        except ValueError:
            print(f"[setscore] score 必须是数字: {args[0]}")
            return True
        resp = await send_request(
            self.ws,
            sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                debug_pb.DebugCommand(score=debug_pb.DebugSetScore(score=score))
            ])),
        )
        if resp.error:
            print(f"[setscore] error: {resp.error}")
        else:
            print(f"[setscore] 已设置 score={score}")
        return True

    async def cmd_draw(self, args):
        # draw text <text> [@x,y]      -> DebugDraw.text
        # draw line <x1,y1> <x2,y2>    -> DebugDraw.lines
        # draw box <x1,y1> <x2,y2>     -> DebugDraw.boxes
        # draw clear                   -> DebugDraw 空（清屏）
        # 注：Color 与 Line 在 debug.proto 中定义（debug_pb2.Color / debug_pb2.Line），不在 common_pb2
        if not args:
            print("[draw] 用法:")
            print("  draw text <text> [@x,y]            屏幕绘制文本（默认 virtual_pos=0,0）")
            print("  draw line <x1,y1> <x2,y2>          绘制线段（世界坐标）")
            print("  draw box <x1,y1> <x2,y2>           绘制方框（世界坐标）")
            print("  draw clear                          清空所有调试绘制")
            return True
        sub = args[0].lower()
        if sub == "clear":
            # 发送空 DebugDraw 清屏
            resp = await send_request(
                self.ws,
                sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                    debug_pb.DebugCommand(draw=debug_pb.DebugDraw())
                ])),
            )
            if resp.error:
                print(f"[draw clear] error: {resp.error}")
            else:
                print("[draw clear] 已清空调试绘制")
            return True
        if sub == "text":
            if len(args) < 2:
                print("[draw text] 用法: draw text <text> [@x,y]")
                return True
            text = " ".join(args[1:])
            vp = common_pb.Point(x=0.0, y=0.0)
            # 抽取 @x,y
            if "@" in text:
                parts = text.rsplit("@", 1)
                text = parts[0].strip()
                try:
                    xs, ys = parts[1].split(",")
                    vp = common_pb.Point(x=float(xs), y=float(ys))
                except ValueError:
                    print("[draw text] @x,y 格式错误")
                    return True
            resp = await send_request(
                self.ws,
                sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                    debug_pb.DebugCommand(draw=debug_pb.DebugDraw(text=[
                        debug_pb.DebugText(
                            color=debug_pb.Color(r=255, g=255, b=255),
                            text=text, virtual_pos=vp, size=14,
                        )
                    ]))
                ])),
            )
            if resp.error:
                print(f"[draw text] error: {resp.error}")
            else:
                print(f"[draw text] 已绘制: {text} @({vp.x},{vp.y})")
            return True
        if sub == "line":
            if len(args) < 3:
                print("[draw line] 用法: draw line <x1,y1> <x2,y2>")
                return True
            try:
                x1, y1 = (float(v) for v in args[1].split(","))
                x2, y2 = (float(v) for v in args[2].split(","))
            except ValueError:
                print("[draw line] 坐标格式错误（应为 x,y）")
                return True
            resp = await send_request(
                self.ws,
                sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                    debug_pb.DebugCommand(draw=debug_pb.DebugDraw(lines=[
                        debug_pb.DebugLine(
                            color=debug_pb.Color(r=0, g=255, b=0),
                            line=debug_pb.Line(
                                p0=common_pb.Point(x=x1, y=y1),
                                p1=common_pb.Point(x=x2, y=y2),
                            ),
                        )
                    ]))
                ])),
            )
            if resp.error:
                print(f"[draw line] error: {resp.error}")
            else:
                print(f"[draw line] 已绘制 ({x1},{y1})->({x2},{y2})")
            return True
        if sub == "box":
            if len(args) < 3:
                print("[draw box] 用法: draw box <x1,y1> <x2,y2>")
                return True
            try:
                x1, y1 = (float(v) for v in args[1].split(","))
                x2, y2 = (float(v) for v in args[2].split(","))
            except ValueError:
                print("[draw box] 坐标格式错误（应为 x,y）")
                return True
            resp = await send_request(
                self.ws,
                sc_pb.Request(debug=sc_pb.RequestDebug(debug=[
                    debug_pb.DebugCommand(draw=debug_pb.DebugDraw(boxes=[
                        debug_pb.DebugBox(
                            color=debug_pb.Color(r=255, g=0, b=0),
                            min=common_pb.Point(x=x1, y=y1),
                            max=common_pb.Point(x=x2, y=y2),
                        )
                    ]))
                ])),
            )
            if resp.error:
                print(f"[draw box] error: {resp.error}")
            else:
                print(f"[draw box] 已绘制 ({x1},{y1})->({x2},{y2})")
            return True
        print(f"[draw] 未知子命令: {sub}（支持 text/line/box/clear）")
        return True

    async def cmd_query(self, args):
        player = int(args[0]) if args and args[0].isdigit() else None
        resp = await send_request(self.ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
        if resp.error:
            print(f"[query] error: {resp.error}")
            return True
        obs = resp.observation.observation
        pc = obs.player_common
        if pc is not None:
            print(f"[query] 资源(玩家{pc.player_id}): 矿物={pc.minerals} 气={pc.vespene} 补给={pc.food_used}/{pc.food_cap}")
        raw = obs.raw_data
        if raw is None:
            print("[query] 无 raw_data")
            return True
        by_player: dict[int, dict[str, int]] = {}
        for u in raw.units:
            if player is not None and u.owner != player:
                continue
            by_player.setdefault(u.owner, {})
            name = self.name_lookup(u.unit_type)
            by_player[u.owner][name] = by_player[u.owner].get(name, 0) + 1
        for pid, counts in sorted(by_player.items()):
            summary = ", ".join(f"{n}×{c}" for n, c in sorted(counts.items(), key=lambda kv: -kv[1]))
            print(f"  玩家{pid}: {summary}")

    async def cmd_obs(self, args):
        resp = await send_request(self.ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
        if resp.error:
            print(f"[obs] error: {resp.error}")
            return True
        raw = resp.observation.observation.raw_data
        if raw is None:
            print("[obs] 无 raw_data")
            return True
        gl = getattr(resp.observation.observation, "game_loop", None) or getattr(resp.observation, "game_loop", None)
        print(f"[obs] 单位总数: {len(raw.units)}; 游戏循环: {gl}")
        return True

    async def cmd_info(self, args):
        resp = await send_request(self.ws, sc_pb.Request(game_info=sc_pb.RequestGameInfo()))
        if resp.error:
            print(f"[info] error: {resp.error}")
            return True
        gi = resp.game_info
        try:
            print(f"[info] 地图: {gi.map_name}")
        except Exception:
            print("[info] 地图: (未暴露)")
        try:
            ms = gi.start_raw.map_size
            print(f"[info] 尺寸: {ms.x}×{ms.y}")
        except Exception:
            print("[info] 尺寸: (本 proto 未暴露 start_raw)")
        try:
            for p in gi.player_info:
                print(f"  玩家{p.player_id} type={p.type} race={p.race}")
        except Exception:
            pass
        return True

    async def cmd_step(self, args):
        n = int(args[0]) if args and args[0].isdigit() else 1
        resp = await send_request(self.ws, sc_pb.Request(step=sc_pb.RequestStep(count=n)))
        if resp.error:
            print(f"[step] error: {resp.error}")
        else:
            print(f"[step] 已推进 {n} 帧")
        return True

    # ---------- P2 状态断言 ----------
    async def _player_counts_by_id(self, player):
        """返回 {unit_type_id: count}，仅统计指定玩家；失败返回 (None, err)。"""
        resp = await send_request(self.ws, sc_pb.Request(observation=sc_pb.RequestObservation()))
        if resp.error:
            return None, resp.error
        raw = resp.observation.observation.raw_data
        if raw is None:
            return None, "无 raw_data（确认游戏以 raw 接口启动）"
        counts: dict[int, int] = {}
        for u in raw.units:
            if u.owner == player and self._unit_is_alive(u):
                counts[u.unit_type] = counts.get(u.unit_type, 0) + 1
        return counts, None

    async def _eval_assert(self, op, unit, player, cmp=None, n=None, lo=None, hi=None):
        counts, err = await self._player_counts_by_id(player)
        if err:
            return False, f"采集失败: {err}"
        uid = self.resolve(unit)
        if uid is None:
            return False, f"未知单位: {unit}（用整数 id 或 python-sc2 支持的英文名）"
        actual = counts.get(uid, 0)
        name = self.name_lookup(uid)
        if op == "exists":
            ok = actual >= 1
            want = "至少 1 个"
        elif op == "not_exists":
            ok = actual == 0
            want = "0 个"
        elif op == "count":
            if cmp == "==":
                ok = actual == n
            elif cmp == ">=":
                ok = actual >= n
            elif cmp == "<=":
                ok = actual <= n
            elif cmp == ">":
                ok = actual > n
            elif cmp == "<":
                ok = actual < n
            else:
                return False, f"非法比较符: {cmp}"
            want = f"{cmp} {n}"
        elif op == "range":
            ok = lo <= actual <= hi
            want = f"{lo}..{hi}"
        else:
            return False, f"未知断言 op: {op}"
        verdict = "PASS" if ok else "FAIL"
        detail = f"{verdict} {op} {unit}({name}) 玩家{player} 实际={actual} 期望={want}"
        return ok, detail

    async def _run_assert_inner(self, rest, player):
        """解析内部断言 op（exists/not_exists/count/range）并判定。rest 已剥离 flags。"""
        if not rest:
            return False, "断言为空"
        op = rest[0].lower()
        if op == "exists":
            if len(rest) < 2:
                return False, "exists 需指定 unit"
            return await self._eval_assert("exists", rest[1], player)
        if op == "not_exists":
            if len(rest) < 2:
                return False, "not_exists 需指定 unit"
            return await self._eval_assert("not_exists", rest[1], player)
        if op == "count":
            if len(rest) < 4:
                return False, "count 需 <unit> <cmp> <N>"
            unit, cmp, n = rest[1], rest[2], rest[3]
            if cmp not in ("==", ">=", ">", "<=", "<"):
                return False, f"非法比较符: {cmp}"
            try:
                nv = int(n)
            except ValueError:
                return False, f"N 非整数: {n}"
            return await self._eval_assert("count", unit, player, cmp=cmp, n=nv)
        if op == "range":
            if len(rest) < 3:
                return False, "range 需 <unit> <min> <max>"
            unit, lo, hi = rest[1], rest[2], rest[3]
            try:
                lo, hi = int(lo), int(hi)
            except ValueError:
                return False, "min/max 非整数"
            return await self._eval_assert("range", unit, player, lo=lo, hi=hi)
        return False, f"未知断言 op: {op}"

    def _record(self, ok, expr, detail):
        self.assert_results.append(
            {"pass": bool(ok), "expr": expr, "detail": detail, "ts": utcnow()}
        )

    def write_assert_report(self):
        if not self.assert_results:
            return
        total = len(self.assert_results)
        passed = sum(1 for r in self.assert_results if r["pass"])
        report = {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "all_passed": passed == total,
            "results": self.assert_results,
            "generated_at": utcnow(),
        }
        ASSERT_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ASSERT_REPORT_PATH.write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"[assert] 汇总 {passed}/{total} 通过 -> {ASSERT_REPORT_PATH}")

    async def cmd_assert(self, args):
        # assert <op> <...> [--player N] [--within S]
        #   op: exists | not_exists | count | range | eventually
        rest, player, within = _split_flags(args)
        if not rest:
            print(
                "[assert] 用法: assert <exists|not_exists|count|range|eventually> <unit> ... "
                "[--player N] [--within S]"
            )
            return True
        player = player or 1
        op = rest[0].lower()
        if op == "eventually":
            inner = rest[1:]
            if not inner:
                print("[assert] eventually 需跟一个断言 op，如: eventually exists marine")
                return True
            within = within or 5.0
            deadline = time.time() + within
            poll = 0.25
            passed = False
            last = ""
            while time.time() < deadline:
                ok, last = await self._run_assert_inner(inner, player)
                if ok:
                    passed = True
                    break
                await asyncio.sleep(poll)
            print(f"[assert] eventually({within}s) {'PASS' if passed else 'FAIL'}: {last}")
            self._record(passed, "eventually " + " ".join(inner), last)
            return True
        ok, detail = await self._run_assert_inner(rest, player)
        print(f"[assert] {detail}")
        self._record(ok, " ".join(rest), detail)
        return True

    async def dispatch(self, line: str):
        line = line.strip()
        if not line:
            return True
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        op = parts[0].lower()
        args = parts[1:]
        handlers = {
            "ping": self.cmd_ping,
            "invoke": self.cmd_invoke,
            "vm": self.cmd_vm,
            "echo": self.cmd_echo,
            "spawn": self.cmd_spawn,
            "kill": self.cmd_kill,
            "set": self.cmd_set,
            "cheat": self.cmd_cheat,
            "endgame": self.cmd_endgame,
            "testproc": self.cmd_testproc,
            "setscore": self.cmd_setscore,
            "draw": self.cmd_draw,
            "query": self.cmd_query,
            "assert": self.cmd_assert,
            "obs": self.cmd_obs,
            "info": self.cmd_info,
            "step": self.cmd_step,
            "help": self.cmd_help,
            "?": self.cmd_help,
        }
        h = handlers.get(op)
        if h is None:
            print(f"[?] 未知命令: {op}（输入 help 查看）")
            return True
        try:
            return await h(args)
        except Exception as e:  # pragma: no cover
            print(f"[!] 执行 {op} 异常: {e}")
            return False

    async def cmd_help(self, args):
        print(
            "SC2 Vibe REPL 命令：\n"
            "  ping                                  验证 Mod 闭环\n"
            "  invoke <function_id> [key=value ...]  调用显式注册的 typed Vibe function\n"
            "  vm <program.json>                      热加载并执行 Debug VM 程序\n"
            "  echo <text>                           回显文本到 Bank\n"
            "  spawn <type> <count> [player] [@x,y]  秒级刷兵（type 可用英文名或整数 id）\n"
            "  kill <all|player N|tag t1 t2...>      击杀单位\n"
            "  set <hp|energy|shields> <val> <player N|tag ...>  设单位属性\n"
            "  cheat <kind> <on|off>                 DebugGameState 作弊开关\n"
            "    kind ∈ {show_map|control_enemy|food|free|all_resources|god|\n"
            "            minerals|gas|cooldown|tech_tree|upgrade|fast_build}\n"
            "  endgame <victory|surrender>           DebugEndGame 结束游戏\n"
            "  testproc <hang|crash|exit> [delay_ms] DebugTestProcess（破坏性，仅供排错）\n"
            "  setscore <score:float>                DebugSetScore 设置分数\n"
            "  draw text <text> [@x,y]               DebugDraw 屏幕绘制文本\n"
            "  draw line <x1,y1> <x2,y2>             DebugDraw 绘制线段（世界坐标）\n"
            "  draw box <x1,y1> <x2,y2>              DebugDraw 绘制方框（世界坐标）\n"
            "  draw clear                            清空所有调试绘制\n"
            "  query [player N]                      汇总单位与资源\n"
            "  assert <exists|not_exists|count|range|eventually> <unit> ... [--player N] [--within S]  自动判定\n"
            "  obs                                    观察原始摘要\n"
            "  info                                   地图/玩家信息\n"
            "  step [n]                               推进 n 帧\n"
            "  help | ?                               本帮助\n"
            "  exit | quit                            退出\n"
            "注：function_id 必须存在于 kernel/function-registry.json；不存在的函数会被拒绝。"
        )
        return True

    async def run_interactive(self):
        print("SC2 Vibe REPL 已连接。输入 help 查看命令，exit 退出。")
        if not self._have_map:
            print("（未取到地图中心，spawn 默认落点 50,50；可用 @x,y 指定）")
        loop = asyncio.get_event_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, lambda: input("vibe> "))
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if line.strip().lower() in ("exit", "quit"):
                break
            await self.dispatch(line)

    async def run_script(self, path: Path):
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip().lstrip("\ufeff")
            if not line or line.startswith("#"):
                continue
            print(f"vibe> {line}")
            await self.dispatch(line)


async def amain(args):
    if not HAS_PROTO:
        print(f"ERR s2clientprotocol: {PROTO_ERR}", file=sys.stderr)
        return 2
    resolve = _unit_id_resolver()
    name_lookup = _unit_name_lookup()
    repl = VibeREPL(
        args.port,
        resolve,
        name_lookup,
        map_path=args.map,
        join_wait=args.join_wait,
        rpc_session_id=args.rpc_session_id,
        realtime=args.realtime,
    )
    try:
        await repl.connect()
    except Exception as e:
        print(f"ERR 连接 SC2 API 失败: {e}", file=sys.stderr)
        print("确认：游戏已通过 tools/galaxy-vibe/launch-galaxy-vibe.ps1 启动且 /sc2api 已绑定。", file=sys.stderr)
        return 2

    try:
        command_ok = True
        if args.vm_program:
            command_ok = await repl.dispatch(f"vm {shlex.quote(args.vm_program)}")
        elif args.cmd:
            command_ok = await repl.dispatch(args.cmd)
        elif args.script or args.assert_file:
            await repl.run_script(Path(args.assert_file or args.script))
        else:
            await repl.run_interactive()
        repl.write_assert_report()
        rc = 0
        if command_ok is False:
            rc = 1
        if repl.assert_results and not all(r["pass"] for r in repl.assert_results):
            rc = 1
        return rc
    finally:
        await repl.close()


def main():
    ap = argparse.ArgumentParser(description="SC2 Vibe REPL — P1 最小热循环")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--map", default="", help="CreateGame + JoinGame this map before running commands")
    ap.add_argument("--join-wait", type=float, default=15.0, help="Seconds to wait after JoinGame for map scripts")
    ap.add_argument("--realtime", action="store_true", help="Create a realtime game so the visible SC2 window is not step-paused")
    ap.add_argument("--rpc-session-id", default="", help="恢复当前游戏内已有的 Vibe Kernel session_id")
    ap.add_argument("--cmd", help="执行单条命令后退出")
    ap.add_argument("--vm-program", help="加载并执行 JSON Debug VM 程序后退出")
    ap.add_argument("--script", help="逐行执行脚本文件后退出")
    ap.add_argument("--assert-file", help="逐行执行断言/scenario 文件，结束打印 PASS/FAIL 汇总并以退出码返回")
    a = ap.parse_args()
    raise SystemExit(asyncio.run(amain(a)))


if __name__ == "__main__":
    main()
