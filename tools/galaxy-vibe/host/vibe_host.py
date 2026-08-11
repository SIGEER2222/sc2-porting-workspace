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


def _active_candidate(bank_name: str) -> Path | None:
    """返回 Galaxy 内核当前实际读取的候选 Bank 路径。

    Galaxy 端从 ``Banks/<AuthorHash>/`` 下读取 ``pending_request_id`` 与
    ``request`` 段，每次 `BankSave` 后该目录 mtime 最新。Python 侧
    ``read_bank`` 也以 (含 index 段 + mtime 最大) 为优先级选取同一份，
    故"active 候选"与 `read_bank` 返回的是同一物理文件。内核只读这一份。
    """
    best: Path | None = None
    best_mtime = -1.0
    for _, path in _iter_bank_candidates(bank_name):
        parsed, mtime = _parse_bank_file(path)
        if "index" not in parsed:
            continue
        if mtime > best_mtime:
            best_mtime = mtime
            best = path
    return best


def bank_request_landed(bank_name: str, request_id: str) -> bool:
    """校验请求是否已落进 Galaxy 内核实际读取的那一份 Bank（active 候选）。

    ！！！铁律 VIBE_GEN_007 + VIBE-KERNEL-005b！！！
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

    **判定口径（VIBE-KERNEL-005b 修正）**：只检查 **active 候选**的
    ``request`` 段是否含该 ``request_id``，**不**要求 ``pending_request_id == rid``，
    **不**要求所有候选都带请求。理由：

      1. Galaxy 内核只读 active 候选（``Banks/<AuthorHash>/``）那一份；
         16 个历史遗留数字子目录是不同会话的陈旧 Bank，内核永不读它们，
         要求它们带请求只会制造**假性 False** 触发无谓重发。
      2. 内核处理完请求后通常会清空/改写 active 候选的 ``pending_request_id``；
         若还要求 `pending == rid` 通过，则响应一落盘就又判 False → 每请求每
         ~2s 一次虚假重发循环，正是真机 16s 卡死样本的来源。
      3. 一旦 ``request_id`` 写进 active 候选的 ``request`` 段，内核 PollLoop
         必然读取并分发，故"已 landed"的正确判据就是该段含此 rid；丢失的判据
         是 active 候选的 ``request`` 段**不含**此 rid（对应上述 (a)(b)）。

    该修正消除两类虚假重发、且与内核只读单目录的事实一致；真丢失（active 候选
    的 request 段缺 rid）仍被准确检测并触发重发。
    """
    active = _active_candidate(bank_name)
    if active is None:
        return False
    parsed, _ = _parse_bank_file(active)
    if not parsed:
        return False
    return request_id in parsed.get("request", {})


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
        # 【2026-08-09 修】仅放 1 个 Participant（P1），与 tier100 真机探针一致。
        # 之前放 Participant + Computer 双玩家会在 realtime 下让 AI 对手接管并
        # 频繁触发内核 BankSave，放大 VIBE_GEN_007 有损通道对 pending_request_id
        # 的覆盖概率；单玩家下内核 PollLoop/BankPoll 行为与被验证的 tier100 路径一致。
        req = sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=local_map,
            player_setup=[
                sc_pb.PlayerSetup(
                    type=PLAYER_PARTICIPANT, race=RACE_TERRAN, player_name="P1",
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
        fresh_bank: bool = False,
    ):
        self.sc2_port = sc2_port
        self.bank_name = bank_name
        self.runtime_bank_name = runtime_bank_name
        self.require_initialization = require_initialization
        self.realtime = realtime
        self.poll_step_count = max(1, int(poll_step_count))
        self.fresh_bank = fresh_bank
        self.initialization_complete = not require_initialization
        self.initialization_status: dict[str, Any] = {}
        self.initialization_error = ""
        self.session_id: str = ""
        self.sequence: int = 0
        self.client: Optional[Sc2ApiClient] = None
        self.requests_log: list[dict[str, Any]] = []
        self.responses_log: list[dict[str, Any]] = []
        # VIBE-KERNEL-005b 诊断：每次 reassert 触发时记录 active 候选与哪些候选
        # 缺请求，用于区分「active 目录真丢失（文件句柄竞争）」与「陈旧/stale 目录
        # 导致 bank_request_landed 假性 False」。仅诊断用，不影响判定逻辑。
        self.reassert_diags: list[dict[str, Any]] = []
        # VIBE-KERNEL-006 诊断（观察-only）：读到 HANDLER_ABORTED 时继续观察 grace 秒，
        # 记录该 rid 的 response 是否被真响应覆盖，用来区分「抢读悲观占位符」与
        # 「handler 真的 abort」。> 0 才启用；**绝不改变 _poll_response 的返回值**，
        # 因此不可能把红判据刷绿。仅在 legacy 模式（abort_is_terminal=True）下有意义。
        self.aborted_grace_probe: float = 0.0
        self.provisional_diags: list[dict[str, Any]] = []
        # VIBE-KERNEL-006 修复开关。False（默认，正确语义）= HANDLER_ABORTED 视为
        # **provisional**，继续轮询等真响应；True = 旧行为，读到即当终态立刻返回。
        # 保留 True 分支是为了做反向对照（A/B 证明差异确实来自本修复）。
        self.abort_is_terminal: bool = False
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
                # 【2026-08-09 修】fresh-bank：kernel_initialized 是 Bank 持久 key，
                # 会跨地图加载残留。即便新地图 MapScript 被 SC2 静默丢弃（编译失败），
                # 旧值仍在，导致“内核已注册”假阳性；更糟的是残留的 request/pending
                # 会与本次请求在同一份 Bank 上竞争，放大 VIBE_GEN_007 有损通道的覆盖
                # 概率。create_game 前把 GalaxyVibe.SC2Bank 移走，使“标记/响应出现”
                # 成为“本次加载确实编译并运行了内核”的无歧义证据，并清空 stale 请求。
                if self.fresh_bank:
                    bp = DEFAULT_BANK_DIR / f"{self.bank_name}.SC2Bank"
                    if bp.exists():
                        arch = bp.with_suffix(f".SC2Bank.stale-{int(time.time())}")
                        try:
                            bp.replace(arch)
                            print(f"[VibeHost] fresh-bank 归档旧 Bank: {arch}", file=sys.stderr)
                        except OSError as exc:  # noqa: BLE001
                            print(f"[VibeHost] fresh-bank 归档失败（忽略）: {exc}", file=sys.stderr)
                    # VIBE-KERNEL-005b：历史会话遗留的 Banks/<digits>/GalaxyVibe.SC2Bank
                    # 会让 bank_request_landed 的"全候选"旧口径假性 False，并让每次
                    # write_bank_request 多写 ~16 份冗余文件。fresh-bank 须一并归档这些
                    # 陈旧 author 目录的 GalaxyVibe.SC2Bank，使本次运行只留 root +
                    # 新 CreateGame 生成的 active 目录两个候选，降低写竞争面。
                    for sub in sorted(DEFAULT_BANK_DIR.iterdir()):
                        if sub.is_dir() and sub.name.isdigit():
                            stale = sub / f"{self.bank_name}.SC2Bank"
                            if stale.exists():
                                try:
                                    stale.replace(
                                        stale.with_suffix(f".SC2Bank.stale-{int(time.time())}")
                                    )
                                    print(f"[VibeHost] fresh-bank 归档陈旧候选 Bank: {stale}",
                                          file=sys.stderr)
                                except OSError as exc:  # noqa: BLE001
                                    print(f"[VibeHost] fresh-bank 归档陈旧候选失败（忽略）: {exc}",
                                          file=sys.stderr)
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
        reassert: bool = True,
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
        # bank_poll 通道启用 at-least-once 重发（VIBE_GEN_007），其余 transport
        # 不重发（map_command 的重发需连带重新 MapCommand 唤醒，语义不同）。
        response = self._poll_response(
            request.request_id,
            timeout,
            advance_frames=transport in ("map_command", "bank_poll"),
            reassert=reassert and transport == "bank_poll",
            original_request=request,
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

    def _observe_aborted_supersede(self, request_id: str, raw_first: str) -> None:
        """VIBE-KERNEL-006 取证：HANDLER_ABORTED 是"真 abort"还是"抢读占位符"？

        内核 ``KERNEL001_PESSIMISTIC`` 在 handler 运行**之前**就写
        ``response/<rid> = HANDLER_ABORTED``，而 ``gf_WriteBankKey`` 内部
        （LibVibeKernel.galaxy:194-195）是 ``BankValueSetFromString`` + **立即
        ``BankSave``**。于是磁盘上会短暂存在一个"看起来是终态"的悲观占位符。
        Host 的 50ms 轮询若恰好落在 [占位符刷盘, 真响应刷盘) 这个窗口内，就会把
        provisional 占位符当终态读走并立刻返回。

        本函数**只取证不干预**：继续观察 ``aborted_grace_probe`` 秒，看同一 rid 的
        response 是否被一份**不同的**内容覆盖。

        - ``superseded=True``  → 抢读竞态成立，handler 根本没 abort（内核缺陷是
          "provisional 与 terminal 不可区分"，不是 handler 崩了）
        - ``superseded=False`` → HANDLER_ABORTED 是真裁决

        无论结果如何都不修改 ``_poll_response`` 的返回值，判据一分不放宽。
        """
        diag: dict[str, Any] = {
            "request_id": request_id,
            "superseded": False,
            "supersede_ms": None,
            "final_error_code": "HANDLER_ABORTED",
            "grace_s": self.aborted_grace_probe,
        }
        started = time.time()
        deadline = started + self.aborted_grace_probe
        try:
            while time.time() < deadline:
                time.sleep(0.02)
                later = read_bank(self.bank_name).get("response", {}).get(request_id, "")
                if later and later != raw_first:
                    later_resp = RpcResponse.from_json(later)
                    diag["superseded"] = True
                    diag["supersede_ms"] = round((time.time() - started) * 1000, 2)
                    diag["final_error_code"] = later_resp.error_code
                    break
        except Exception:  # noqa: BLE001 - 取证路径绝不允许影响主流程
            diag["observe_error"] = True
        self.provisional_diags.append(diag)

    def _poll_response(
        self,
        request_id: str,
        timeout: float,
        advance_frames: bool = False,
        reassert: bool = False,
        original_request: Optional[RpcRequest] = None,
    ) -> RpcResponse:
        """轮询 Bank 等待响应，并按需推进非实时 SC2 帧。

        bank_poll 通道在 ``reassert=True`` 时启用 at-least-once 重发
        （VIBE_GEN_007 真机取证）：Bank 是 Host 与 Galaxy 对同一文件全量覆盖、
        无锁的有损通道，请求可能在内核 ReloadBank 之后、下次 BankSave 之前被
        内核内存态整份抹掉。仅当请求确实已从所有候选 Bank 上消失
        （``bank_request_landed`` 为假）时才用同一 ``request_id`` 重发；
        rid 不变，内核靠 ``lastPolledRequestId`` 去重，重复投递不会重复执行。
        """
        deadline = time.time() + timeout
        last_assert = time.time()
        self._poll_started = time.time()
        reassert_sec = 2.0
        # VIBE-KERNEL-006：provisional 占位符状态（见下方 if 分支的长注释）
        provisional_resp: Optional[RpcResponse] = None
        provisional_raw = ""
        provisional_at = 0.0
        while time.time() < deadline:
            bank = read_bank(self.bank_name)
            resp_section = bank.get("response", {})
            raw = resp_section.get(request_id, "")
            if raw:
                resp = RpcResponse.from_json(raw)
                # VIBE-KERNEL-006：HANDLER_ABORTED 在内核里**只有一个产生点** ——
                # KERNEL001_PESSIMISTIC（LibVibeKernel.galaxy:1483-1485）在 handler
                # 运行**之前**就把它写进 response/<rid>，而 gf_WriteBankKey 内部立即
                # BankSave。所以它天生是 provisional 占位符，不是裁决结果。
                # Host 每 50ms 轮询，若恰好落在 [占位符刷盘, 真响应刷盘) 窗口内就会
                # 误把它当终态读走 —— 真机取证（p0-transport-k006-forensic-rep2/rep3）
                # 显示 7/7 个 HANDLER_ABORTED 都在 37~54ms 内被真 OK 覆盖，**零个真 abort**。
                # 正确语义：继续轮询。占位符的原始设计意图（handler 真崩时 Host 不必
                # 无从判断）完整保留 —— 见下方超时分支：超时后盘上仍是占位符，才判定
                # 「dispatch 开始过但从未完成」并返回 HANDLER_ABORTED 终态。
                # 这不是放宽判据：若假说是错的（真 abort 占多数），修复后延迟会暴涨到
                # poll_timeout 且 all_acked 依然红 —— 修复自带证伪机制。
                if resp.error_code == "HANDLER_ABORTED" and not self.abort_is_terminal:
                    if provisional_resp is None:
                        provisional_resp = resp
                        provisional_raw = raw
                        provisional_at = time.time()
                    time.sleep(0.02)
                    continue
                if provisional_resp is not None and raw != provisional_raw:
                    self.provisional_diags.append({
                        "request_id": request_id,
                        "superseded": True,
                        "supersede_ms": round((time.time() - provisional_at) * 1000, 2),
                        "final_error_code": resp.error_code,
                        "mode": "poll_continue",
                    })
                if self.aborted_grace_probe > 0.0 and resp.error_code == "HANDLER_ABORTED":
                    self._observe_aborted_supersede(request_id, raw)
                return resp
            # VIBE_GEN_007：仅在请求确已丢失时重发，避免无谓覆盖内核刚写的
            # response（write_bank_request 现在以最新候选为基底，重发也不会回滚）。
            now = time.time()
            if reassert and original_request is not None and now - last_assert >= reassert_sec:
                last_assert = now
                if not bank_request_landed(self.bank_name, request_id):
                    # VIBE-KERNEL-005b 诊断：记录触发重发时的候选明细，用于区分
                    # "active 目录真丢失（文件句柄竞争）" 与 "陈旧目录导致假性 False"。
                    try:
                        diag = {
                            "request_id": request_id,
                            "t": round(now - self._poll_started, 3) if hasattr(self, "_poll_started") else None,
                            "active": None,
                            "active_has_req": None,
                            "stale_without_req": [],
                            "candidate_count": 0,
                        }
                        active = _active_candidate(self.bank_name)
                        if active is not None:
                            ap, _ = _parse_bank_file(active)
                            diag["active"] = str(active)
                            diag["active_has_req"] = request_id in ap.get("request", {})
                        for tag, path in _iter_bank_candidates(self.bank_name):
                            diag["candidate_count"] += 1
                            if path == active:
                                continue
                            p, _ = _parse_bank_file(path)
                            if p and request_id not in p.get("request", {}):
                                diag["stale_without_req"].append(tag)
                        self.reassert_diags.append(diag)
                    except Exception:  # noqa: BLE001
                        pass
                    write_bank_request(self.bank_name, request_id, original_request)
            if advance_frames and self.client and not self.realtime:
                # 仅非实时模式需要 RequestStep 推进 Galaxy PollLoop/BankPoll。
                # 实时模式下 SC2 必然拒绝 RequestStep，但内核的 PollLoop/BankPoll
                # 由游戏自身实时推进，step 失败是**预期**的，绝不能据此中止轮询
                # —— 否则 realtime 下每个 bank_poll 请求都会在第一轮迭代即 INTERNAL_ERROR，
                # 表现与 tier100 真机探针"只 sleep 不 step 即闭环"完全相反。
                # （此前 Step 4 全量抽样 0/53 的真相：create_game 默认 realtime=true，
                # _poll_response 第一轮 step 即被拒 → 立即 INTERNAL_ERROR，内核响应根本
                # 没机会被读到，与"gen 分发失败"无关。）
                # 非实时 peer 真正断开时 step 也返回 False，此时及早结束轮询以免
                # 在已关闭的 websocket 上反复写入直到 timeout。
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
        # VIBE-KERNEL-006：整段观测窗口结束，盘上仍停在 provisional 占位符 ⇒ dispatch
        # 确实开始过（内核写下了占位符）但从未完成 ⇒ 这才是**真的** handler abort。
        # 此处返回 HANDLER_ABORTED 而非 INTERNAL_ERROR，正是占位符的原始设计意图：
        # 让 Host 能区分「handler 崩了」与「内核根本没收到请求」（后者盘上无 response，
        # 走下面的 INTERNAL_ERROR）。判据强度不变：真 abort 依旧计为 non-ok。
        if provisional_resp is not None:
            self.provisional_diags.append({
                "request_id": request_id,
                "superseded": False,
                "supersede_ms": None,
                "final_error_code": "HANDLER_ABORTED",
                "mode": "poll_continue",
                "waited_ms": round((time.time() - provisional_at) * 1000, 2),
            })
            return provisional_resp
        # 超时且盘上无任何 response = host 侧超时（内核未产出裁决）
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

    def leave_game(self, timeout: float = 30.0) -> bool:
        """退出当前对局回到主菜单（委托给底层 SC2 API 客户端），用于善后避免孤儿 in-game 态。"""
        if self.client is None:
            return False
        try:
            return bool(self.client.leave_game(timeout=timeout))
        except Exception as exc:  # noqa: BLE001
            print(f"[VibeHost] leave_game 异常（忽略）: {exc}", file=sys.stderr)
            return False

    def close(self) -> None:
        self.disconnect()
