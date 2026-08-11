"""SC2 API 连接层：端口自动发现 + 状态机安全的连接获取。

踩过的三个坑，全部封装在这里，调用方不要再各写一份：

1) **端口不固定**。用 `SC2Switcher_x64.exe -listen 127.0.0.1 -port 5000` 启动时，
   如果 5000 还被上一个刚死掉的实例占在 TIME_WAIT，switcher 会**静默回退**到
   另一个端口（实测见过 18220）。所以永远不要硬编码 5000，
   要从 SC2_x64.exe 的命令行里把 `-port <n>` 读出来。

2) **leave_game 会让服务端主动关闭 websocket**。之后任何 send 都会抛
   `Server disconnected` 或 `Received message 257(CLOSED) is not WSMsgType.BINARY`。
   这是传输层现象，不是游戏逻辑失败，更不是脚本编译失败——必须重连，
   绝不能当成测试结论。

3) **对 launched(1) 状态发 leave_game 同样会被断开**。要先 ping 看 status。
"""
import asyncio
import os
import re
import subprocess
import threading
import time

import aiohttp
from s2clientprotocol import sc2api_pb2 as sc_pb

from sc2_proc_guard import kill_api_instances

# RequestPing 返回的 Status 枚举
ST_LAUNCHED, ST_INIT, ST_IN_GAME, ST_IN_REPLAY, ST_ENDED, ST_QUIT = 1, 2, 3, 4, 5, 6

_PS = ("powershell", "-NoProfile", "-NonInteractive", "-Command")
_QUERY = ("Get-CimInstance Win32_Process -Filter \"Name='SC2_x64.exe'\" "
          "| ForEach-Object { $_.CommandLine }")


def discover_api_port(default=5000):
    """从正在运行的 SC2_x64.exe 命令行里解析 `-port <n>`。

    找不到就回退到 SC2_API_PORT 环境变量，再回退到 default。
    """
    try:
        out = subprocess.run(_PS + (_QUERY,), capture_output=True, text=True, errors="replace",
                             timeout=25).stdout or ""
    except Exception:
        out = ""
    ports = [int(m) for m in re.findall(r"-listen\s+\S+\s+-port\s+(\d+)", out)]
    if not ports:
        ports = [int(m) for m in re.findall(r"-port\s+(\d+)", out)]
    if ports:
        return ports[0]
    return int(os.environ.get("SC2_API_PORT", default))


def api_url(port=None):
    return f"ws://127.0.0.1:{port or discover_api_port()}/sc2api"


class Client:
    """跑在后台事件循环上的极简同步 SC2 API 客户端。"""

    def __init__(self, url=None):
        self.url = url or api_url()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.session = None
        self.ws = None

    def _run(self, coro, t=180):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(timeout=t)

    async def _connect(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=180))
        self.ws = await self.session.ws_connect(self.url)

    async def _send(self, req):
        await self.ws.send_bytes(req.SerializeToString())
        data = await self.ws.receive_bytes()
        r = sc_pb.Response()
        r.ParseFromString(data)
        return r

    async def _close(self):
        if self.ws is not None:
            await self.ws.close()
        if self.session is not None:
            await self.session.close()

    def connect(self):
        self._run(self._connect(), 30)
        return self

    def send(self, req, t=180):
        return self._run(self._send(req), t)

    def status(self, t=30):
        return self.send(sc_pb.Request(ping=sc_pb.RequestPing()), t).status

    def leave(self):
        """尽力退局；断连是预期行为，不抛。"""
        try:
            self.send(sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), 20)
        except Exception:
            pass

    def close(self):
        try:
            self._run(self._close(), 10)
        except Exception:
            pass
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            pass


SC2_ROOT = os.environ.get("SC2_ROOT", r"E:\SC2\SC2new\StarCraft II")
SC2_SWITCHER = os.path.join(SC2_ROOT, "Support64", "SC2Switcher_x64.exe")


def _sc2_alive(port):
    """轻量存活探测：能建 ws 并 ping 通才算活。"""
    async def _probe():
        async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=15)) as s:
            async with s.ws_connect(f"ws://127.0.0.1:{port}/sc2api") as ws:
                await ws.send_bytes(
                    sc_pb.Request(ping=sc_pb.RequestPing()).SerializeToString())
                await ws.receive_bytes()
                return True
    try:
        return asyncio.new_event_loop().run_until_complete(_probe())
    except Exception:
        return False


def ensure_sc2(port=5000, boot_wait=90, kill_stale=True, force=False):
    """保证有一个可用的 SC2 API 实例，返回其 ws url。

    真机探针要反复 create_game/leave_game，SC2 跑十几轮后经常自己崩。
    没有自愈就得人肉重启，整条流水线没法无人值守。

    force=True 时跳过"活着就复用"的快捷路径，强制杀掉重启。
    用于 init_game 卡死这类"进程活着但状态机出不来"的场景。
    """
    if not force:
        live = discover_api_port(default=0)
        if live and _sc2_alive(live):
            return f"ws://127.0.0.1:{live}/sc2api"

    if kill_stale:
        # 只杀带 `-listen` 的 API 探针实例。绝不能用
        # `Get-Process -Name SC2_x64 | Stop-Process -Force`——那会把用户
        # 正在玩的真人对局一起干掉（自动化按小时跑，撞上只是时间问题）。
        # guard=True 时若检测到真人对局会直接抛错，把误杀变成显式失败。
        kill_api_instances(guard=True)
        time.sleep(3)

    subprocess.run(_PS + (
        f"Start-Process -FilePath '{SC2_SWITCHER}' "
        f"-ArgumentList '-listen','127.0.0.1','-port','{port}','-debug' "
        f"-WorkingDirectory '{SC2_ROOT}'",), capture_output=True,
        text=True, timeout=60)

    deadline = time.time() + boot_wait
    while time.time() < deadline:
        time.sleep(4)
        p = discover_api_port(default=0)
        if p and _sc2_alive(p):
            return f"ws://127.0.0.1:{p}/sc2api"
    raise RuntimeError(f"SC2 API 实例在 {boot_wait}s 内未就绪")


def acquire_launched(url=None, max_wait=90, init_grace=25.0):
    """返回一个处于 launched(1) 状态的新连接。

    SC2 挂了会自动重启实例（ensure_sc2），所以调用方可以连跑几十轮探针
    而不用管进程死活。彻底拿不到才抛 RuntimeError。

    **init_game(2) 是死胡同**：只 create_game 不 join_game（探针中途异常退出、
    或只做协议 dump 的脚本）会把 SC2 永久留在 init_game。这个状态既不能
    leave_game 退出，也不会自己超时——只能杀进程重启。所以在 init_game 上
    停留超过 init_grace 秒就强制重启一次实例，否则后续所有探针全部假阴性。
    """
    url = url or ensure_sc2()
    last = None
    deadline = time.time() + max_wait
    restarted = False
    init_since = None
    while time.time() < deadline:
        try:
            c = Client(url).connect()
            last = c.status()
        except Exception:
            if not restarted:          # 连不上 => 实例大概率已崩，重启一次
                restarted = True
                url = ensure_sc2()
                deadline = time.time() + max_wait
            else:
                time.sleep(2.0)
            continue
        if last == ST_LAUNCHED:
            return c
        if last in (ST_IN_GAME, ST_IN_REPLAY, ST_ENDED):
            c.leave()
            init_since = None
        elif last == ST_INIT:
            init_since = init_since or time.time()
            if not restarted and time.time() - init_since > init_grace:
                c.close()
                restarted = True
                init_since = None
                url = ensure_sc2(force=True)   # init_game 卡死：唯一出路是重启
                deadline = time.time() + max_wait
                continue
        c.close()
        time.sleep(2.0)
    raise RuntimeError(f"SC2 未回到 launched 状态（最后 status={last}, url={url}）")
