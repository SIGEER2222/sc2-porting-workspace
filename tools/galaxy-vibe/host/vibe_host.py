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

import json
import os
import socket
import struct
import sys
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


# ---- SC2API 连接（同步封装）----

class Sc2ApiClient:
    """同步 SC2API websocket 客户端，封装 RequestMapCommand 等调用。"""

    def __init__(self, port: int = 5000, host: str = "127.0.0.1"):
        self.port = port
        self.host = host
        self._sock: Optional[socket.socket] = None

    def connect(self, timeout: float = 10.0) -> None:
        if not HAS_PROTOBUF:
            raise RuntimeError("缺少 s2clientprotocol 依赖")
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(timeout)
        self._sock.connect((self.host, self.port))
        # SC2API 握手
        self._send_request(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
            observed_player_id=1,
            options=sc_pb.RequestJoinGame.ObserverOptions(),
        )))

    def _send_request(self, req: sc_pb.Request) -> sc_pb.Response:
        if self._sock is None:
            raise RuntimeError("SC2API 未连接")
        data = req.SerializeToString()
        header = struct.pack("<i", len(data))
        self._sock.sendall(header + data)
        resp_len_bytes = self._recv_exactly(4)
        if len(resp_len_bytes) < 4:
            raise RuntimeError("SC2API 响应长度读取失败")
        resp_len = struct.unpack("<i", resp_len_bytes)[0]
        resp_data = self._recv_exactly(resp_len)
        resp = sc_pb.Response()
        resp.ParseFromString(resp_data)
        return resp

    def _recv_exactly(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))  # type: ignore
            if not chunk:
                break
            buf += chunk
        return buf

    def ping(self) -> bool:
        """SC2API 层 ping（与 RPC system.ping 不同）。"""
        try:
            resp = self._send_request(sc_pb.Request(ping=sc_pb.RequestPing()))
            return resp.HasField("ping")
        except Exception:
            return False

    def map_command(self, command: str) -> bool:
        """发送 RequestMapCommand，触发 Galaxy Kernel 的 MapCommand 事件。"""
        try:
            req = sc_pb.Request(map_command=sc_pb.RequestMapCommand(trigger_cmd=command))
            resp = self._send_request(req)
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
            resp = self._send_request(req)
            return not resp.HasField("error")
        except Exception:
            return False

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None


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

    def connect_sc2(self) -> bool:
        """连接 SC2 API。"""
        self.client = Sc2ApiClient(port=self.sc2_port)
        try:
            self.client.connect()
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
