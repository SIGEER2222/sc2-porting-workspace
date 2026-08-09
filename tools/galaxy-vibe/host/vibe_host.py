"""Vibe Host — SC2 Vibe 框架的编排主机。

依据 sc2-vibe完整实施计划.md:
  - 接收意图，生成 task.json，判定热/冷循环，编排执行，最多自动修正 3 次
  - 通过 Transport 下发 RPC 请求到 Kernel
  - 通过 State Observer / Visual Observer 采集证据
  - 通过 Evaluator 生成 result.json

通信流程（P0 传输闸门）:
  1. Host 将请求写入 Bank(GalaxyVibe, section="request", key=request_id)
  2. Host 通过 RequestStep 驱动 Kernel 的 Bank/PollLoop 入口
  3. Kernel 从 Bank 读取请求、处理、写回响应到 section="response"
  4. Host 轮询 Bank 读取响应

使用：
  from vibe_host import VibeHost
  host = VibeHost(sc2_port=5000, bank_name="GalaxyVibe")
  host.start_session()
  resp = host.request("system.ping", {})
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import threading
import time
import uuid
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from xml.etree import ElementTree as ET

# 复用 sc2api-baseline 的 SC2API websocket 封装
# vibe_host.py 位于 tools/galaxy-vibe/host/，parents[3] 才是仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))
sys.path.insert(0, str(REPO_ROOT / "src" / "projects" / "cmre-porting"))

from vibe.function_registry import (  # noqa: E402
    FunctionRegistryError,
    normalize_request_args,
    wire_function_args,
)

try:
    from s2clientprotocol import sc2api_pb2 as sc_pb
    HAS_PROTOBUF = True
except ImportError:
    HAS_PROTOBUF = False

try:
    import aiohttp
    HAS_AIOHTTP = True
except ImportError:
    HAS_AIOHTTP = False

try:
    import websocket  # websocket-client 同步库
    HAS_WEBSOCKET = True
except ImportError:
    HAS_WEBSOCKET = False


# ---- RPC 协议数据类 ----

PROTOCOL_VERSION = "vibe/1.0"
BANK_WRITE_RETRIES = 20
BANK_WRITE_RETRY_DELAY_SEC = 0.1


@dataclass
class RpcRequest:
    """RPC 请求 schema（依据 rpc-schema.json）。"""
    session_id: str
    request_id: str
    sequence: int
    operation: str
    args: dict[str, Any] = field(default_factory=dict)
    issued_at: str = ""
    checksum: str = ""

    def __post_init__(self):
        if not self.issued_at:
            self.issued_at = time.strftime("%Y-%m-%dT%H:%M:%S+08:00", time.localtime())
        if not self.checksum:
            self.checksum = self._compute_checksum()

    def _compute_checksum(self) -> str:
        """CRC32 校验和（8 位 hex）。"""
        raw = f"{self.session_id}|{self.request_id}|{self.sequence}|{self.operation}"
        return f"{zlib.crc32(raw.encode('utf-8')) & 0xFFFFFFFF:08x}"

    def to_args_string(self) -> str:
        """序列化为 Galaxy Kernel 可解析的 key=value;key=value 格式。"""
        parts = [
            f"protocol_version={PROTOCOL_VERSION}",
            f"session_id={self.session_id}",
            f"request_id={self.request_id}",
            f"sequence={self.sequence}",
            f"operation={self.operation}",
            f"checksum={self.checksum}",
        ]
        if self.operation == "function.invoke":
            function_id, call_args = normalize_request_args(self.args)
            for k, v in wire_function_args(function_id, call_args).items():
                parts.append(f"{k}={v}")
        else:
            for k, v in self.args.items():
                parts.append(f"{k}={v}")
        return ";".join(parts)


@dataclass
class RpcResponse:
    """RPC 响应。"""
    kind: str  # ack | result | error
    session_id: str
    request_id: str
    sequence: int
    operation: str = ""
    error_code: str = "OK"
    payload: dict[str, Any] = field(default_factory=dict)
    state_version: int = 0
    started_at: str = ""
    completed_at: str = ""
    raw: str = ""

    @classmethod
    def from_json(cls, raw: str) -> "RpcResponse":
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return cls(kind="error", session_id="", request_id="", sequence=0,
                       error_code="INTERNAL_ERROR", raw=raw)
        return cls(
            kind=data.get("kind", "error"),
            session_id=data.get("session_id", ""),
            request_id=data.get("request_id", ""),
            sequence=data.get("sequence", 0),
            operation=data.get("operation", ""),
            error_code=data.get("error_code", "OK"),
            payload=data.get("payload", {}),
            state_version=data.get("state_version", 0),
            started_at=data.get("started_at", ""),
            completed_at=data.get("completed_at", ""),
            raw=raw,
        )

    @property
    def is_ok(self) -> bool:
        return self.kind == "result" and self.error_code == "OK"


# ---- Bank 文件操作 ----

DEFAULT_BANK_DIR = Path.home() / "Documents" / "StarCraft II" / "Banks"
# ARENA-007：SC2 的 Bank 物理路径不是 Banks root，而是 Banks/<AuthorHash>/
# （亡者之夜对应 /14/，斗蛐蛐可能对应 /1/ 或其他数字子目录）。
# GalaxyLoad("GalaxyVibe", 1) 从 <AuthorHash> 子目录加载文件，BankSave 也刷回
# 同一子目录；但 Python 侧之前只读 Banks root，造成 "Galaxy 写入成功却 probe
# 永远读不到 kernel_initialized" 的现象。因此我们把 Banks/<digits>/ 全部视为
# 候选定位点：读时取"最新修改的一份"，写时同步到 root + 所有数字子目录。


def _iter_bank_candidates(bank_name: str):
    """生成 (Path, priority) 候选；priority 越高越优先（root 优先，子目录按 mtime 排）。"""
    fname = f"{bank_name}.SC2Bank"
    # 1) Banks root (Python 侧 canonical 路径)
    root_p = DEFAULT_BANK_DIR / fname
    yield ("root", root_p)
    # 2) Banks/<digits>/ 下的所有已存在同名文件 + 所有数字目录（即使文件不存在
    #    也需要作为写入候选，保证 CreateGame 时 AuthorHash 目录存在就能落盘）
    if DEFAULT_BANK_DIR.is_dir():
        for sub in sorted(DEFAULT_BANK_DIR.iterdir()):
            if sub.is_dir() and sub.name.isdigit():
                yield (f"id-{sub.name}", sub / fname)


def _parse_bank_file(path: Path) -> tuple[dict[str, dict[str, Any]], float]:
    """解析单个 Bank 文件，返回 (parsed_dict, mtime_ns_or_0)。"""
    if not path.exists():
        return ({}, 0.0)
    try:
        tree = ET.parse(path)
    except ET.ParseError:
        return ({}, 0.0)
    parsed: dict[str, dict[str, Any]] = {}
    for section in tree.getroot().findall("Section"):
        sname = section.get("name", "")
        if not sname:
            continue
        sdict: dict[str, Any] = {}
        for key in section.findall("Key"):
            kname = key.get("name", "")
            vnode = key.find("Value")
            if vnode is None:
                continue
            if "flag" in vnode.attrib:
                sdict[kname] = vnode.attrib["flag"] == "1"
            elif "int" in vnode.attrib:
                try:
                    sdict[kname] = int(vnode.attrib["int"])
                except ValueError:
                    sdict[kname] = vnode.attrib["int"]
            elif "fixed" in vnode.attrib:
                try:
                    sdict[kname] = float(vnode.attrib["fixed"])
                except ValueError:
                    sdict[kname] = vnode.attrib["fixed"]
            elif "string" in vnode.attrib:
                sdict[kname] = vnode.attrib["string"]
            elif "text" in vnode.attrib:
                sdict[kname] = vnode.attrib["text"]
        parsed[sname] = sdict
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = 0.0
    return (parsed, mtime)


def read_bank(bank_name: str, player: int = 1) -> dict[str, dict[str, Any]]:
    """读取 Bank 文件：在 root + 所有数字 ID 子目录中取最新修改的一份。

    ARENA-007 兼容：Galaxy 端从 Banks/<AuthorHash>/GalaxyVibe.SC2Bank 读写，
    Python 侧必须扫描该路径下的候选才能拿到 kernel_initialized / response
    等真实状态。
    """
    best_parsed: dict[str, dict[str, Any]] = {}
    best_mtime = -1.0
    for _, path in _iter_bank_candidates(bank_name):
        parsed, mtime = _parse_bank_file(path)
        if mtime > best_mtime:
            best_mtime = mtime
            best_parsed = parsed
    # 兜底：如果数字子目录有 kernel_initialized 但 root 没有/更旧，仍应返回
    # （上面已经按 mtime 取最大，自动满足）。
    return best_parsed


def _write_tree_to_all_candidates(bank_name: str, tree) -> list[Path]:
    """把 ElementTree 同步写到 root + 所有数字子目录候选，返回成功路径列表。"""
    written_paths: list[Path] = []
    for tag, path in _iter_bank_candidates(bank_name):
        # 父目录不存在则跳过（通常只可能是 root 路径不存在；数字目录之前 scan
        # 时已存在）。
        parent = path.parent
        if not parent.exists():
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                continue
        # 原子写：tmp 再 os.replace，避免 Galaxy 端 BankReload 撞见截断 XML。
        tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
        ok = False
        for attempt in range(BANK_WRITE_RETRIES):
            try:
                tree.write(str(tmp), encoding="utf-8", xml_declaration=True)
                os.replace(tmp, path)
                ok = True
                break
            except (PermissionError, OSError):
                if attempt + 1 >= BANK_WRITE_RETRIES:
                    break
                time.sleep(BANK_WRITE_RETRY_DELAY_SEC)
        if ok:
            written_paths.append(path)
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return written_paths


def write_bank_request(bank_name: str, request_id: str, request: RpcRequest, player: int = 1) -> bool:
    """将请求写入 Bank：root + 所有数字 Author 子目录同步。

    ARENA-007 兼容：Galaxy 端从 Banks/<AuthorHash>/ 读取 pending_request_id，
    仅写 Banks root 的话永远进不了 PollLoop / BankPoll 轮询视野。
    """
    args_string = request.to_args_string()
    # 从候选中挑一份最"完整"且**最新**的作为基底；若全部不存在则新建空白 Bank。
    #
    # ！！！铁律 VIBE_GEN_007（2026-08-09 真机取证）！！！
    # 旧实现用 `score > cur_score`（严格大于）遍历候选，而 root 是第一个候选，
    # 于是只要 root 有 index+request 就永远当选基底 —— 完全忽略 mtime。
    # 但 root 只有 Host 会写，Galaxy 端实际读写的是 Banks/<AuthorHash>/。
    # 结果：Host 每次发请求都把内核刚落盘的 response/index 回滚成"自己上一次的
    # 快照"，等于让内核状态时间倒流，并可能连带抹掉尚未被读走的旧请求。
    # 修法：基底按 (完整度, mtime) 取最优，保证 Host 的写入是在内核最新状态之上
    # 做增量，而不是覆盖式回滚。
    base_root = None
    base_parsed: dict[str, dict[str, Any]] | None = None
    best_key: tuple[int, float] = (-1, -1.0)
    for _, path in _iter_bank_candidates(bank_name):
        parsed, mtime = _parse_bank_file(path)
        if not parsed:
            continue
        score = int("index" in parsed) * 2 + int("request" in parsed)
        if (score, mtime) > best_key:
            best_key = (score, mtime)
            base_root = path
            base_parsed = parsed

    if base_parsed and base_root and base_root.exists():
        try:
            tree = ET.parse(str(base_root))
            root_el = tree.getroot()
        except (ET.ParseError, FileNotFoundError):
            root_el = ET.Element("Bank")
            root_el.set("version", "1")
            tree = ET.ElementTree(root_el)
    else:
        root_el = ET.Element("Bank")
        root_el.set("version", "1")
        tree = ET.ElementTree(root_el)

    # 写入 request section: key=request_id
    req_sec = root_el.find("Section[@name='request']")
    if req_sec is None:
        req_sec = ET.SubElement(root_el, "Section")
        req_sec.set("name", "request")
    for k in list(req_sec.findall("Key")):
        if k.get("name") == request_id:
            req_sec.remove(k)
    rk = ET.SubElement(req_sec, "Key")
    rk.set("name", request_id)
    rv = ET.SubElement(rk, "Value")
    rv.set("string", args_string)

    # 设置 pending_request_id 触发 BankPoll
    idx_sec = root_el.find("Section[@name='index']")
    if idx_sec is None:
        idx_sec = ET.SubElement(root_el, "Section")
        idx_sec.set("name", "index")
    for k in list(idx_sec.findall("Key")):
        if k.get("name") == "pending_request_id":
            idx_sec.remove(k)
    pk = ET.SubElement(idx_sec, "Key")
    pk.set("name", "pending_request_id")
    pv = ET.SubElement(pk, "Value")
    pv.set("string", request_id)

    paths = _write_tree_to_all_candidates(bank_name, tree)
    return len(paths) > 0


def bank_request_landed(bank_name: str, request_id: str) -> bool:
    """校验请求是否仍然存在于**所有**候选 Bank 文件上（Galaxy 端能读到）。

    ！！！铁律 VIBE_GEN_007！！！
    Bank 是"双写单文件"通道：Host 与 Galaxy 都以**全量覆盖**语义写同一个文件，
    没有任何锁。两类丢失都真机复现过：

      (a) 内核在 `ReloadBank()` 之后、下一次 `BankSave()` 之前的窗口内，
          Host 写盘的 request/<id> 会被内核内存态全量覆盖抹掉。
          请求分发（Dispatch）耗时越长，这个窗口越宽 —— 这正是 gen 图上
          `vibe.query.units`（紧跟重量级 unit.spawn 之后发出）稳定丢失、
          而 standalone 图不丢的原因。
      (b) 写 Banks/<digits>/ 子目录时若撞上 SC2 正在 BankSave 持有句柄，
          `os.replace` 抛 PermissionError；重试耗尽后该子目录保持陈旧，
          而 root 写成功 → `write_bank_request` 仍返回 True，Host 以为发出去了。

    两种情况下请求都不会进 Dispatch，表现完全一致：没有 response、
    没有 HANDLER_ABORTED 兜底、state_version 也不 bump（因为内核压根没看见）。
    因此"写完即认为送达"是错的，必须回读校验 + 重发。

    这里要求**每一个已存在的候选文件**都带有该请求：只要有一份陈旧/被抹除，
    就可能正好是 Galaxy 端在读的那一份。
    """
    seen_any = False
    for _, path in _iter_bank_candidates(bank_name):
        parsed, _ = _parse_bank_file(path)
        if not parsed:
            continue
        seen_any = True
        has_req = request_id in parsed.get("request", {})
        pending = str(parsed.get("index", {}).get("pending_request_id", ""))
        if not has_req or pending != request_id:
            return False
    return seen_any


# ---- SC2API 连接（aiohttp + 后台 event loop 同步封装）----

# SC2 API race 枚举（common.proto）：NoRace=0, Terran=1, Zerg=2, Protoss=3, Random=4
RACE_TERRAN = 1
# PlayerType 枚举（sc2api.proto）：Participant=1, Computer=2, Observer=3
PLAYER_PARTICIPANT = 1
PLAYER_COMPUTER = 2


class Sc2ApiClient:
    """同步 SC2API WebSocket 客户端（aiohttp 内部封装）。

    SC2 API 协议是 WebSocket（ws://<host>:<port>/sc2api），帧体为裸 protobuf。
    用后台 event loop + run_coroutine_threadsafe 保持同步接口，同时复用 aiohttp 的 WebSocket 实现。
    参考 reference/SC2-Neuro-API-Integration/sc2api_load_map.py。
    """

    def __init__(self, port: int = 5000, host: str = "127.0.0.1"):
        self.port = port
        self.host = host
        self._url = f"ws://{host}:{port}/sc2api"
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session: Optional["aiohttp.ClientSession"] = None
        self._ws: Optional["aiohttp.websockets.ClientWebSocketResponse"] = None

    # ---- 后台 event loop 管理 ----

    def _ensure_loop(self) -> asyncio.AbstractEventLoop:
        """启动后台 event loop（若未启动）。"""
        if self._loop is None or not self._loop.is_running():
            self._loop = asyncio.new_event_loop()
            self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
            self._thread.start()
        return self._loop

    def _submit(self, coro, timeout: float = 30.0):
        """提交协程到后台 event loop 并同步等待结果。"""
        loop = self._ensure_loop()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        return future.result(timeout=timeout)

    # ---- 连接管理 ----

    def connect(self, timeout: float = 10.0) -> None:
        """连接 SC2API WebSocket 端点 ws://<host>:<port>/sc2api。"""
        if not HAS_PROTOBUF:
            raise RuntimeError("缺少 s2clientprotocol 依赖")
        if not HAS_AIOHTTP:
            raise RuntimeError("缺少 aiohttp 依赖：pip install aiohttp")
        self._submit(self._async_connect(timeout), timeout=timeout + 5)

    async def _async_connect(self, timeout: float) -> None:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        )
        self._ws = await self._session.ws_connect(self._url)

    def close(self) -> None:
        """关闭 WebSocket 连接 + session + 后台 event loop。"""
        if self._loop is None:
            return
        try:
            self._submit(self._async_close(), timeout=5)
        except Exception:
            pass
        try:
            self._loop.call_soon_threadsafe(self._loop.stop)
            if self._thread:
                self._thread.join(timeout=5)
        except Exception:
            pass
        self._loop = None
        self._thread = None
        self._session = None
        self._ws = None

    async def _async_close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        if self._session is not None:
            await self._session.close()
            self._session = None

    # ---- 请求发送 ----

    def _send_request(self, req: sc_pb.Request, timeout: float = 30.0) -> sc_pb.Response:
        """同步发送请求并返回响应。"""
        if self._ws is None:
            raise RuntimeError("SC2API 未连接")
        return self._submit(self._async_send_request(req), timeout=timeout)

    async def _async_send_request(self, req: sc_pb.Request) -> sc_pb.Response:
        await self._ws.send_bytes(req.SerializeToString())
        resp_data = await self._ws.receive_bytes()
        if isinstance(resp_data, str):
            resp_data = resp_data.encode("utf-8")
        resp = sc_pb.Response()
        resp.ParseFromString(resp_data)
        return resp

    # ---- 高层 API ----

    def ping(self) -> bool:
        """SC2API 层 ping（与 RPC system.ping 不同）。返回 True 若 ping 成功。"""
        try:
            resp = self._send_request(sc_pb.Request(ping=sc_pb.RequestPing()), timeout=10)
            return resp.HasField("ping")
        except Exception:
            return False

    def create_game(
        self,
        map_data: Optional[bytes] = None,
        map_path: Optional[str] = None,
        timeout: float = 120.0,
        realtime: bool = True,
    ) -> bool:
        """发送 CreateGame 请求加载地图（SC2 在主菜单时调用）。

        Args:
            map_data: MPQ 格式的 .SC2Map 字节流（优先于 map_path）
            map_path: SC2 可见的本地地图路径
            realtime: 是否让 SC2 自动推进；False 时由 RequestStep 驱动
            timeout: 超时秒数（地图大时加载慢）

        Returns:
            True 若 CreateGame 成功
        """
        local_map = sc_pb.LocalMap()
        if map_data:
            local_map.map_data = map_data
        elif map_path:
            local_map.map_path = map_path
        else:
            raise ValueError("create_game 需要 map_data 或 map_path")
        req = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=local_map,
            player_setup=[
                sc_pb.PlayerSetup(
                    type=PLAYER_PARTICIPANT, race=RACE_TERRAN, player_name="P1",
                ),
                sc_pb.PlayerSetup(
                    type=PLAYER_COMPUTER, race=RACE_TERRAN,
                    difficulty=2, player_name="AI",
                ),
            ],
            realtime=realtime,
        ))
        try:
            resp = self._send_request(req, timeout=timeout)
            # Response.error 是 repeated string，不能用 HasField；用真值检查列表是否非空
            if resp.error:
                print(f"[Sc2ApiClient] CreateGame error: {list(resp.error)}", file=sys.stderr)
                return False
            if resp.HasField("create_game") and resp.create_game.HasField("error"):
                print(f"[Sc2ApiClient] CreateGame error: {resp.create_game.error}", file=sys.stderr)
                return False
            return True
        except Exception as e:
            print(f"[Sc2ApiClient] CreateGame exception: {e}", file=sys.stderr)
            return False

    def join_game(self, timeout: float = 60.0) -> bool:
        """发送 JoinGame 请求以 Participant 身份加入对局（race=Terran, raw APM）。"""
        try:
            resp = self._send_request(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
                race=RACE_TERRAN,
                options=sc_pb.InterfaceOptions(raw=True),
            )), timeout=timeout)
            if resp.error:
                print(f"[Sc2ApiClient] JoinGame error: {list(resp.error)}", file=sys.stderr)
                return False
            if resp.HasField("join_game") and resp.join_game.HasField("error"):
                print(f"[Sc2ApiClient] JoinGame error: {resp.join_game.error} details: {resp.join_game.error_details}", file=sys.stderr)
                return False
            return True
        except Exception as e:
            print(f"[Sc2ApiClient] JoinGame exception: {e}", file=sys.stderr)
            return False

    def leave_game(self, timeout: float = 30.0) -> bool:
        """发送 LeaveGame 请求退出当前对局，返回 SC2 到主菜单。"""
        try:
            resp = self._send_request(sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), timeout=timeout)
            if resp.error:
                # LeaveGame 在非 in_game 状态下可能返回错误，不算致命
                print(f"[Sc2ApiClient] LeaveGame note: {list(resp.error)}", file=sys.stderr)
            return True
        except Exception as e:
            print(f"[Sc2ApiClient] LeaveGame exception: {e}", file=sys.stderr)
            return False

    def observation(self, timeout: float = 30.0) -> Optional[sc_pb.Response]:
        """发送 Observation 请求，返回完整 Response（调用方自行检查 HasField）。"""
        try:
            return self._send_request(sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=timeout)
        except Exception as e:
            print(f"[Sc2ApiClient] Observation exception: {e}", file=sys.stderr)
            return None

    def step(self, count: int = 1, timeout: float = 30.0) -> bool:
        """Advance a non-realtime game by ``count`` simulation steps."""
        try:
            resp = self._send_request(
                sc_pb.Request(step=sc_pb.RequestStep(count=max(1, int(count)))),
                timeout=timeout,
            )
            return not resp.error
        except Exception as e:
            print(f"[Sc2ApiClient] Step exception: {e}", file=sys.stderr)
            return False

    def map_command(self, command: str) -> bool:
        """发送 RequestMapCommand，触发 Galaxy Kernel 的 MapCommand 事件。"""
        try:
            req = sc_pb.Request(map_command=sc_pb.RequestMapCommand(trigger_cmd=command))
            resp = self._send_request(req, timeout=10)
            if resp.error:
                return False
            if resp.HasField("map_command") and not resp.map_command.HasField("error"):
                return True
            return False
        except Exception:
            return False

    def send_chat(self, message: str) -> bool:
        """发送聊天消息（备用 transport）。

        ActionChat.Channel 枚举：Broadcast=1, Team=2（无 0 值）。
        用 Broadcast 确保触发 Galaxy EventChatMessage。
        """
        try:
            req = sc_pb.Request(action=sc_pb.RequestAction(
                actions=[sc_pb.Action(
                    action_chat=sc_pb.ActionChat(channel=1, message=message),
                )],
            ))
            resp = self._send_request(req, timeout=10)
            return not resp.error
        except Exception:
            return False


# ---- Vibe Host 主类 ----

class VibeHost:
    """Vibe 框架的编排主机。

    管理会话、发送请求、接收响应、收集证据。
    """

    def __init__(
        self,
        sc2_port: int = 5000,
        bank_name: str = "GalaxyVibe",
        artifacts_dir: Optional[Path] = None,
        runtime_bank_name: str = "CMRERebornDebug",
        require_initialization: bool = False,
        realtime: bool = True,
        poll_step_count: int = 1,
    ):
        self.sc2_port = sc2_port
        self.bank_name = bank_name
        self.runtime_bank_name = runtime_bank_name
        self.require_initialization = require_initialization
        self.realtime = realtime
        self.poll_step_count = max(1, int(poll_step_count))
        self.initialization_complete = not require_initialization
        self.initialization_status: dict[str, Any] = {}
        self.initialization_error = ""
        self.session_id: str = ""
        self.sequence: int = 0
        self.client: Optional[Sc2ApiClient] = None
        self.requests_log: list[dict[str, Any]] = []
        self.responses_log: list[dict[str, Any]] = []
        self.artifacts_dir = artifacts_dir or (REPO_ROOT / "artifacts" / "galaxy-vibe")
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)

    # ---- 会话管理 ----

    def start_session(self) -> str:
        """启动新会话，生成 session_id。"""
        self.session_id = uuid.uuid4().hex[:16]
        self.sequence = 0
        return self.session_id

    def restore_session(self, session_id: str, last_sequence: int) -> bool:
        """恢复已有会话（Host 重启后续接）。"""
        self.session_id = session_id
        self.sequence = last_sequence
        return True

    # ---- SC2 连接 ----

    def connect_sc2(self, map_data: Optional[bytes] = None, map_path: Optional[str] = None) -> bool:
        """连接 SC2 API WebSocket。若提供 map_data/map_path，则 CreateGame + JoinGame 进图。

        Args:
            map_data: MPQ 格式的 .SC2Map 字节流（优先于 map_path）
            map_path: SC2 可见的本地地图路径（无需读文件，SC2 直接访问）
        """
        self.client = Sc2ApiClient(port=self.sc2_port)
        try:
            self.client.connect()
            # 先 ping 确认 WebSocket 连接正常
            if not self.client.ping():
                print("[VibeHost] SC2 ping 失败", file=sys.stderr)
                return False
            # 若提供了地图，尝试 CreateGame + JoinGame
            if map_data or map_path:
                # 先尝试 JoinGame（SC2 可能已在 in_game 且地图正确）
                if self.client.join_game(timeout=10.0):
                    print("[VibeHost] 已 JoinGame（SC2 之前在 in_game）", file=sys.stderr)
                    if self.require_initialization and not self.wait_for_initialization():
                        print(f"[VibeHost] 初始化门禁失败: {self.initialization_error}", file=sys.stderr)
                        return False
                    return True
                # JoinGame 失败 → SC2 可能在 in_game（地图不对）或主菜单
                # 先 LeaveGame 确保回到主菜单，避免 CreateGame 在 in_game 状态下行为不确定
                print("[VibeHost] JoinGame 失败，LeaveGame 退出当前对局...", file=sys.stderr)
                self.client.leave_game(timeout=15.0)
                time.sleep(2.0)
                # CreateGame 加载新地图
                if map_data:
                    print(f"[VibeHost] CreateGame with map_data ({len(map_data)} bytes)...", file=sys.stderr)
                    if not self.client.create_game(
                        map_data=map_data, timeout=120.0, realtime=self.realtime
                    ):
                        print("[VibeHost] CreateGame 失败", file=sys.stderr)
                        return False
                else:
                    # map_path 模式（SC2 直接访问路径，不读文件到内存）
                    print(f"[VibeHost] CreateGame with map_path: {map_path}", file=sys.stderr)
                    if not self.client.create_game(
                        map_path=map_path, timeout=120.0, realtime=self.realtime
                    ):
                        print("[VibeHost] CreateGame 失败", file=sys.stderr)
                        return False
                # CreateGame 后短暂等待 SC2 处理（参考 sc2api_load_map.py）
                time.sleep(3.0)
                # 再次 ping 确认状态
                if not self.client.ping():
                    print("[VibeHost] CreateGame 后 ping 失败", file=sys.stderr)
                    return False
                # CreateGame 成功后 JoinGame
                if not self.client.join_game(timeout=60.0):
                    print("[VibeHost] JoinGame 失败（CreateGame 后）", file=sys.stderr)
                    return False
                print("[VibeHost] CreateGame + JoinGame 成功，已进入游戏", file=sys.stderr)
                if self.require_initialization and not self.wait_for_initialization():
                    print(f"[VibeHost] 初始化门禁失败: {self.initialization_error}", file=sys.stderr)
                    return False
            return True
        except Exception as e:
            print(f"[VibeHost] SC2 连接失败: {e}", file=sys.stderr)
            self.client = None
            return False

    def wait_for_initialization(self, timeout: float = 120.0, stable_reads: int = 2) -> bool:
        """Wait for map initialization before allowing Vibe function calls.

        API reachability and a bridge heartbeat are weaker than map readiness.
        The CMRE marker also proves the declared starting structures and
        workers exist. RequestStep keeps non-realtime Galaxy waits moving.
        """
        self.initialization_complete = False
        self.initialization_error = ""
        if not self.client:
            self.initialization_error = "SC2 API 未连接"
            return False

        required = (
            "runtime_listener_started",
            "runtime_listener_ready",
            "bridge_heartbeat",
            "initialization_complete",
            "initialization_building_ready_p1",
            "initialization_building_ready_p2",
            "initialization_units_ready_p1",
            "initialization_units_ready_p2",
        )
        deadline = time.monotonic() + timeout
        consecutive = 0
        last_status: dict[str, Any] = {}
        while time.monotonic() < deadline:
            debug = read_bank(self.runtime_bank_name).get("debug", {})
            status = {key: debug.get(key, 0) for key in required}
            status["world_cover_dialog_visible_p1"] = debug.get("world_cover_dialog_visible_p1", 0)
            last_status = status
            ready = all(int(status.get(key, 0) or 0) > 0 for key in required)
            ready = ready and int(status.get("world_cover_dialog_visible_p1", 0) or 0) == 0
            if ready:
                consecutive += 1
                if consecutive >= max(1, stable_reads):
                    self.initialization_complete = True
                    self.initialization_status = status
                    print(
                        "[VibeHost] map initialization gate passed: "
                        f"heartbeat={status['bridge_heartbeat']}",
                        file=sys.stderr,
                    )
                    return True
            else:
                consecutive = 0

            # In realtime this request may be rejected; in non-realtime it is
            # the required frame driver for the map's Wait/BankPoll triggers.
            self.client.step(count=1, timeout=min(5.0, max(0.1, timeout)))
            time.sleep(0.1)

        self.initialization_status = last_status
        missing = [key for key in required if int(last_status.get(key, 0) or 0) <= 0]
        if int(last_status.get("world_cover_dialog_visible_p1", 0) or 0) != 0:
            missing.append("world_cover_dialog_visible_p1=0")
        self.initialization_error = (
            "未观察到稳定的完整地图初始化 marker; "
            f"missing={','.join(missing) or 'stable-read'}"
        )
        return False

    def disconnect(self) -> None:
        if self.client:
            self.client.close()
            self.client = None

    # ---- 请求发送 ----

    def request(
        self,
        operation: str,
        args: Optional[dict[str, Any]] = None,
        timeout: float = 5.0,
        transport: str = "bank_poll",
    ) -> RpcResponse:
        """发送 RPC 请求并等待响应。

        Args:
            operation: 白名单操作名
            args: 操作参数
            timeout: 等待响应超时（秒）
            transport: "bank_poll" | "chat" | "input" | "map_command"

        Returns:
            RpcResponse
        """
        if not self.session_id:
            self.start_session()
        if args is None:
            args = {}

        if operation == "function.invoke":
            try:
                normalize_request_args(args)
            except FunctionRegistryError as exc:
                return RpcResponse(
                    kind="error", session_id=self.session_id,
                    request_id=uuid.uuid4().hex[:12], sequence=self.sequence,
                    operation=operation, error_code=exc.code,
                    payload={"reason": exc.detail},
                )

        self.sequence += 1
        request = RpcRequest(
            session_id=self.session_id,
            request_id=uuid.uuid4().hex[:12],
            sequence=self.sequence,
            operation=operation,
            args=args,
        )

        # 记录请求
        req_record = {
            "request_id": request.request_id,
            "sequence": request.sequence,
            "operation": operation,
            "args": args,
            "issued_at": request.issued_at,
            "transport": transport,
        }
        if operation == "function.invoke":
            # Stage 26: 策略审计区分生成 adapter 族与手写 handler 族
            try:
                invoke_fid, _ = normalize_request_args(args)
            except FunctionRegistryError:
                invoke_fid = str(args.get("function_id", "") if isinstance(args, dict) else "")
            req_record["family"] = "invoke.generated" if str(invoke_fid).startswith("gen.") else "invoke.handwritten"
        self.requests_log.append(req_record)

        # 通过 Transport 发送
        if transport == "map_command":
            ok = self._send_via_map_command(request)
        elif transport == "chat":
            ok = self._send_via_chat(request)
        elif transport == "input":
            ok = self._send_via_input(request)
        elif transport == "bank_poll":
            ok = self._send_via_bank_poll(request)
        else:
            return RpcResponse(
                kind="error", session_id=self.session_id,
                request_id=request.request_id, sequence=request.sequence,
                operation=operation, error_code="REQUEST_REJECTED",
            )

        if not ok:
            return RpcResponse(
                kind="error", session_id=self.session_id,
                request_id=request.request_id, sequence=request.sequence,
                operation=operation, error_code="INTERNAL_ERROR",
            )

        # 非实时 SC2 不会因为 wall-clock sleep 自行推进；BankPoll
        # transport 必须在等待响应期间驱动 RequestStep，才能让 Galaxy PollLoop
        # 和 BankPoll 继续执行。实时会话中 step 失败时 _poll_response 仍会继续轮询。
        response = self._poll_response(
            request.request_id,
            timeout,
            advance_frames=transport in ("map_command", "bank_poll"),
        )
        # Locally synthesized transport failures do not come from the Kernel
        # and therefore may omit protocol identity fields. Preserve the
        # originating request identity so callers can correlate every result.
        response.session_id = response.session_id or request.session_id
        response.request_id = response.request_id or request.request_id
        response.sequence = response.sequence or request.sequence
        response.operation = response.operation or request.operation
        resp_record = {
            "request_id": request.request_id,
            "operation": operation,
            "response": response.raw if response.raw else "",
            "error_code": response.error_code,
            "latency_ms": 0,  # 由调用方填充
            "received_at": time.strftime("%Y-%m-%dT%H:%M:%S+08:00"),
        }
        self.responses_log.append(resp_record)
        return response

    def _send_via_map_command(self, request: RpcRequest) -> bool:
        """通过 SC2API RequestMapCommand 发送（仅触发 Kernel，不传请求内容）。

        注：MapCommand 只能传唤醒标识符，不能传任意数据。
        请求内容先写入 Bank，Kernel 收到 MapCommand 后从 pending_request_id 读取。
        """
        if not self.client:
            return False
        if not write_bank_request(self.bank_name, request.request_id, request):
            return False
        return self.client.map_command("vibe")

    def _send_via_chat(self, request: RpcRequest) -> bool:
        """通过 SC2API 聊天消息发送完整请求。

        格式: !vibe <args_string>
        其中 args_string 由 RpcRequest.to_args_string() 生成，包含完整请求字段。
        Kernel 端通过 TriggerAddEventChatMessage 监听 "!vibe" 前缀，直接解析请求。
        """
        if not self.client:
            return False
        msg = f"!vibe {request.to_args_string()}"
        return self.client.send_chat(msg)

    def _send_via_input(self, request: RpcRequest) -> bool:
        """通过键盘输入模拟发送（最后回退 transport）。

        使用 pyautogui 或类似库模拟聊天框输入。
        PoC 阶段标记为未实现。
        """
        # 输入回退需要游戏窗口焦点，不稳定，仅作最后手段
        return False

    def _send_via_bank_poll(self, request: RpcRequest) -> bool:
        """通过 Bank 文件写入 + Kernel BankPoll 触发器发送。

        Kernel 的 BankPoll 触发器每 0.5 秒调用 BankLoad 从磁盘重新加载 Bank，
        读取 pending_request_id，发现新请求后读取完整请求并分发。
        本方法将请求写入 Bank 文件，不依赖 SC2API action_chat。
        """
        try:
            return write_bank_request(self.bank_name, request.request_id, request)
        except Exception as e:
            print(f"[VibeHost] write_bank_request 异常: {e}", file=sys.stderr)
            return False

    def _poll_response(
        self,
        request_id: str,
        timeout: float,
        advance_frames: bool = False,
    ) -> RpcResponse:
        """轮询 Bank 等待响应，并按需推进非实时 SC2 帧。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            bank = read_bank(self.bank_name)
            resp_section = bank.get("response", {})
            raw = resp_section.get(request_id, "")
            if raw:
                return RpcResponse.from_json(raw)
            if advance_frames and self.client:
                # RequestStep 在 realtime=true 会被 SC2 拒绝，但 client.step 已
                # 将该失败收敛为 False。非实时 peer 断开时立即结束轮询，
                # 否则每个请求都会在 websocket 已关闭后重复写入直到 timeout。
                if not self.client.step(
                    count=self.poll_step_count,
                    timeout=min(5.0, max(0.1, timeout)),
                ):
                    return RpcResponse(
                        kind="error",
                        session_id=self.session_id,
                        request_id=request_id,
                        sequence=self.sequence,
                        error_code="INTERNAL_ERROR",
                        payload={"reason": "request_step_failed"},
                    )
            time.sleep(0.05)  # 50ms 轮询
        # 超时
        return RpcResponse(
            kind="error", session_id=self.session_id,
            request_id=request_id, sequence=self.sequence,
            error_code="INTERNAL_ERROR",
        )

    # ---- 证据记录 ----

    def save_evidence(self, phase: str, name: str, data: dict[str, Any]) -> Path:
        """保存证据到 artifacts 目录。"""
        evidence_dir = self.artifacts_dir / phase
        evidence_dir.mkdir(parents=True, exist_ok=True)
        path = evidence_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def save_requests_log(self, phase: str = "p0-transport") -> Path:
        """保存请求日志（requests.jsonl）。"""
        path = self.artifacts_dir / phase / "requests.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for req in self.requests_log:
                f.write(json.dumps(req, ensure_ascii=False) + "\n")
        return path

    # ---- 高层 API ----

    def ping(self) -> RpcResponse:
        """便捷方法：发送 system.ping。"""
        return self.request("system.ping", {})

    def invoke_function(self, function_id: str, args: Optional[dict[str, Any]] = None,
                        timeout: float = 5.0, transport: str = "bank_poll") -> RpcResponse:
        """Invoke one explicitly registered typed function."""
        return self.request(
            "function.invoke",
            {"function_id": function_id, "args": args or {}},
            timeout=timeout,
            transport=transport,
        )

    def spawn_units(self, unit_type: str, count: int, player: int = 1,
                    x: float = 0.0, y: float = 0.0) -> RpcResponse:
        """便捷方法：刷单位。"""
        return self.request("unit.spawn", {
            "unit_type": unit_type,
            "count": count,
            "player": player,
            "x": x,
            "y": y,
        })

    def query_units(self, player: int = 1, unit_type: str = "") -> RpcResponse:
        """便捷方法：查询单位。"""
        return self.request("query.units", {
            "player": player,
            "unit_type": unit_type,
        })

    def kill_units(self, player: int = 1, unit_type: str = "", all_flag: bool = False) -> RpcResponse:
        """便捷方法：杀单位。"""
        return self.request("unit.kill", {
            "player": player,
            "unit_type": unit_type,
            "all": "1" if all_flag else "0",
        })

    def set_resource(self, player: int, resource: str, value: int) -> RpcResponse:
        """便捷方法：设置资源。"""
        return self.request("player.set_resource", {
            "player": player,
            "resource": resource,
            "value": value,
        })

    def reset_scenario(self) -> RpcResponse:
        """便捷方法：重置场景。"""
        return self.request("scenario.reset", {})

    def query_mission(self) -> RpcResponse:
        """便捷方法：查询任务状态。"""
        return self.request("query.mission", {})

    def upgrade_set_level(self, player: int, upgrade: str, level: int) -> RpcResponse:
        """便捷方法：设置玩家升级等级。"""
        return self.request("upgrade.set_level", {
            "player": player,
            "upgrade": upgrade,
            "level": level,
        })

    def tech_tree_check(self, player: int, upgrade: str) -> RpcResponse:
        """便捷方法：检查升级是否已解锁。"""
        return self.request("tech_tree.check", {
            "player": player,
            "upgrade": upgrade,
        })

    def query_unit_tags(self, player: int = 1, unit_type: str = "") -> RpcResponse:
        """便捷方法：查询单位 tag 列表。"""
        return self.request("query.unit_tags", {
            "player": player,
            "unit_type": unit_type,
        })

    def query_unit_attrs(self, unit_tag: int) -> RpcResponse:
        """便捷方法：查询单位属性（life/armor/shields/energy）。"""
        return self.request("query.unit_attrs", {
            "unit_tag": unit_tag,
        })

    def attack_unit(self, attacker_tag: int, target_tag: int,
                    timeout: float = 5.0, transport: str = "bank_poll") -> RpcResponse:
        """Issue the explicit typed combat function against one target tag."""
        return self.invoke_function(
            "vibe.unit.attack",
            {"attacker_tag": attacker_tag, "target_tag": target_tag},
            timeout=timeout,
            transport=transport,
        )

    def query_structures(self, owner_player: int = 0, unit_type: str = "",
                         timeout: float = 5.0, transport: str = "bank_poll") -> RpcResponse:
        """Read the live structure census without changing game state."""
        return self.invoke_function(
            "vibe.query.structures",
            {"owner_player": owner_player, "unit_type": unit_type},
            timeout=timeout,
            transport=transport,
        )

    # ---- 清理 ----

    def close(self) -> None:
        self.disconnect()
