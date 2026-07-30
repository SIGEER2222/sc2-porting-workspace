"""Vibe Host — SC2 Vibe 框架的编排主机。

依据 sc2-vibe完整实施计划.md:
  - 接收意图，生成 task.json，判定热/冷循环，编排执行，最多自动修正 3 次
  - 通过 Transport 下发 RPC 请求到 Kernel
  - 通过 State Observer / Visual Observer 采集证据
  - 通过 Evaluator 生成 result.json

通信流程（P0 传输闸门）:
  1. Host 将请求写入 Bank(GalaxyVibe, section="request", key=request_id)
  2. Host 通过 SC2API RequestMapCommand("dbg <request_id>") 触发 Kernel
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
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "reference" / "SC2-Neuro-API-Integration"))

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


def read_bank(bank_name: str, player: int = 1) -> dict[str, dict[str, Any]]:
    """读取 Bank 文件，返回 {section: {key: value}} 字典。"""
    bank_path = DEFAULT_BANK_DIR / f"{bank_name}.SC2Bank"
    if not bank_path.exists():
        return {}
    try:
        tree = ET.parse(bank_path)
    except ET.ParseError:
        return {}
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
    return parsed


def write_bank_request(bank_name: str, request_id: str, request: RpcRequest, player: int = 1) -> None:
    """将请求写入 Bank 的 request section。

    SC2 Bank 文件由游戏进程管理，外部程序直接写入不会被运行中的 SC2 消费。
    本函数用于 PoC/测试；运行时通过 SC2API DebugCommand 或预置文件实现。
    """
    # 注意：实际运行时，Host 不直接写 Bank 文件（SC2 会覆盖）
    # 而是通过 SC2API 的 DebugCommand 或其他机制让 Kernel 读取
    # 这里仅生成请求字符串供 Host 内部使用
    pass  # 实际写入由 Transport 层负责


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
    ) -> bool:
        """发送 CreateGame 请求加载地图（SC2 在主菜单时调用）。

        Args:
            map_data: MPQ 格式的 .SC2Map 字节流（优先于 map_path）
            map_path: SC2 可见的本地地图路径
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
            realtime=True,
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
        """发送聊天消息（备用 transport）。"""
        try:
            req = sc_pb.Request(action=sc_pb.RequestAction(
                actions=[sc_pb.Action(
                    action_chat=sc_pb.ActionChat(channel=0, message=message),
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
    ):
        self.sc2_port = sc2_port
        self.bank_name = bank_name
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
                    return True
                # JoinGame 失败 → SC2 可能在 in_game（地图不对）或主菜单
                # 先 LeaveGame 确保回到主菜单，避免 CreateGame 在 in_game 状态下行为不确定
                print("[VibeHost] JoinGame 失败，LeaveGame 退出当前对局...", file=sys.stderr)
                self.client.leave_game(timeout=15.0)
                time.sleep(2.0)
                # CreateGame 加载新地图
                if map_data:
                    print(f"[VibeHost] CreateGame with map_data ({len(map_data)} bytes)...", file=sys.stderr)
                    if not self.client.create_game(map_data=map_data, timeout=120.0):
                        print("[VibeHost] CreateGame 失败", file=sys.stderr)
                        return False
                else:
                    # map_path 模式（SC2 直接访问路径，不读文件到内存）
                    print(f"[VibeHost] CreateGame with map_path: {map_path}", file=sys.stderr)
                    if not self.client.create_game(map_path=map_path, timeout=120.0):
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
            return True
        except Exception as e:
            print(f"[VibeHost] SC2 连接失败: {e}", file=sys.stderr)
            self.client = None
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
        transport: str = "map_command",
    ) -> RpcResponse:
        """发送 RPC 请求并等待响应。

        Args:
            operation: 白名单操作名
            args: 操作参数
            timeout: 等待响应超时（秒）
            transport: "map_command" | "chat" | "input"

        Returns:
            RpcResponse
        """
        if not self.session_id:
            self.start_session()
        if args is None:
            args = {}

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
        self.requests_log.append(req_record)

        # 通过 Transport 发送
        if transport == "map_command":
            ok = self._send_via_map_command(request)
        elif transport == "chat":
            ok = self._send_via_chat(request)
        elif transport == "input":
            ok = self._send_via_input(request)
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

        # 轮询 Bank 等待响应
        response = self._poll_response(request.request_id, timeout)
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
        """通过 SC2API RequestMapCommand 发送。

        流程：
        1. 将请求 args 字符串写入 Bank section="request" key=request_id
           （注：SC2 运行时 Bank 由游戏管理，Host 无法直接写文件；
           实际通过 SC2API DebugCommand 或预置方式）
        2. 发送 MapCommand("dbg <request_id>")
        """
        if not self.client:
            return False
        # 简化实现：将完整请求嵌入 MapCommand 字符串
        # Galaxy Kernel 解析 MapCommand 文本获取 request_id
        # 但 MapCommand 有长度限制，长请求走 Bank
        # PoC 阶段：直接传 request_id，请求内容预置在 Bank
        # 实际运行时 Host 写 Bank + 发 MapCommand
        cmd = f"dbg {request.request_id}"
        return self.client.map_command(cmd)

    def _send_via_chat(self, request: RpcRequest) -> bool:
        """通过 SC2API 聊天消息发送（备用 transport）。"""
        if not self.client:
            return False
        msg = f"!dbg {request.request_id}"
        return self.client.send_chat(msg)

    def _send_via_input(self, request: RpcRequest) -> bool:
        """通过键盘输入模拟发送（最后回退 transport）。

        使用 pyautogui 或类似库模拟聊天框输入。
        PoC 阶段标记为未实现。
        """
        # 输入回退需要游戏窗口焦点，不稳定，仅作最后手段
        return False

    def _poll_response(self, request_id: str, timeout: float) -> RpcResponse:
        """轮询 Bank 等待响应。"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            bank = read_bank(self.bank_name)
            resp_section = bank.get("response", {})
            raw = resp_section.get(request_id, "")
            if raw:
                return RpcResponse.from_json(raw)
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

    # ---- 清理 ----

    def close(self) -> None:
        self.disconnect()
