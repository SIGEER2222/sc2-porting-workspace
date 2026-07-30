"""Comprehensive Vibe Kernel initialization test.

Strategy:
1. Start SC2 with map path directly (triggers InitMap() during startup)
   - CMRE mods take a long time to load; allow up to 600s for port to open
2. Connect to SC2 API
3. JoinGame to get observation access
4. Check observation for Kernel debug marker (Marine at 50,50) and InitMap marker (Marine at 45,45)
5. Send chat command !vibe to test Kernel response
6. Step game loops and re-check bank file
"""
import os, sys, time, subprocess, threading, socket
os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'
sys.path.insert(0, r'E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\reference\SC2-Neuro-API-Integration')

import aiohttp
import asyncio
from s2clientprotocol import sc2api_pb2 as sc_pb

SC2_ROOT = r'E:\SC2\SC2new\StarCraft II'
SC2_SWITCHER = os.path.join(SC2_ROOT, 'Support64', 'SC2Switcher_x64.exe')
MAP_FILE = r'E:\SC2\SC2new\StarCraft II\Maps\亡者之夜_vibe_live.SC2Map'
API_HOST = '127.0.0.1'
API_PORT = 5000
API_URL = f'ws://{API_HOST}:{API_PORT}/sc2api'

RACE_TERRAN = 1


def wait_port(host, port, timeout=600):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1)
            s.connect((host, port))
            s.close()
            return True
        except Exception:
            time.sleep(3)
    return False


def start_sc2_with_map():
    """Start SC2 with map path directly (triggers InitMap during startup).
    CMRE mods take a long time to load; allow up to 600s for port to open."""
    print(f'[test] Starting SC2 with map: {os.path.basename(MAP_FILE)}', flush=True)
    args = [MAP_FILE,
            '-listenPort', str(API_PORT),
            '-displayMode', '0',
            '-windowWidth', '1280', '-windowHeight', '720',
            '-novid']
    proc = subprocess.Popen(
        [SC2_SWITCHER] + args,
        cwd=SC2_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f'[test] SC2Switcher PID={proc.pid}, waiting for port {API_PORT} (up to 600s for CMRE)...', flush=True)
    if not wait_port(API_HOST, API_PORT, timeout=600):
        print(f'[test] ERROR: SC2 API port {API_PORT} not listening after 600s', flush=True)
        return False
    print(f'[test] SC2 API port {API_PORT} is listening', flush=True)
    time.sleep(5)
    return True


class AsyncSc2Client:
    def __init__(self):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.session = None
        self.ws = None

    def _submit(self, coro, timeout=60):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return fut.result(timeout=timeout)

    async def _connect(self):
        self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60))
        self.ws = await self.session.ws_connect(API_URL)

    async def _close(self):
        if self.ws:
            await self.ws.close()
            self.ws = None
        if self.session:
            await self.session.close()
            self.session = None

    async def _send(self, req):
        await self.ws.send_bytes(req.SerializeToString())
        data = await self.ws.receive_bytes()
        if isinstance(data, str):
            data = data.encode('utf-8')
        resp = sc_pb.Response()
        resp.ParseFromString(data)
        return resp

    def connect(self):
        self._submit(self._connect(), timeout=30)

    def close(self):
        try:
            self._submit(self._close(), timeout=10)
        except Exception:
            pass
        try:
            self.loop.call_soon_threadsafe(self.loop.stop)
        except Exception:
            pass

    def send(self, req, timeout=60):
        return self._submit(self._send(req), timeout=timeout)


def main():
    # Kill any existing SC2 first
    subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         "Get-Process -Name 'SC2*','SC2Switcher*' -ErrorAction SilentlyContinue | Stop-Process -Force"],
        capture_output=True, timeout=10
    )
    time.sleep(3)

    # Clear bank file
    bank_path = os.path.expanduser(r'~\Documents\StarCraft II\Banks\GalaxyVibe.SC2Bank')
    if os.path.exists(bank_path):
        os.remove(bank_path)
        print(f'[test] Cleared old bank file', flush=True)

    # Start SC2 with map path directly
    if not start_sc2_with_map():
        sys.exit(1)

    # Check bank file - InitMap() should have run during map load
    print(f'[test] === Bank file check (after map load) ===', flush=True)
    if os.path.exists(bank_path):
        with open(bank_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        print(f'[test] Bank file exists ({len(content)} bytes):', flush=True)
        print(content[:800], flush=True)
    else:
        print(f'[test] Bank file does NOT exist (InitMap may not have run)', flush=True)

    client = AsyncSc2Client()
    try:
        client.connect()
        print(f'[test] Connected to SC2 API', flush=True)
    except Exception as e:
        print(f'[test] Connect failed: {e}', flush=True)
        sys.exit(1)

    # Ping
    try:
        resp = client.send(sc_pb.Request(ping=sc_pb.RequestPing()), timeout=10)
        print(f'[test] Ping: has_ping={resp.HasField("ping")}', flush=True)
    except Exception as e:
        print(f'[test] Ping failed: {e}', flush=True)

    # JoinGame to get observation access
    print(f'[test] JoinGame...', flush=True)
    try:
        resp = client.send(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
            race=RACE_TERRAN,
            options=sc_pb.InterfaceOptions(raw=True),
        )), timeout=60)
        if resp.error:
            print(f'[test] JoinGame FAILED: {list(resp.error)}', flush=True)
        elif resp.HasField('join_game') and resp.join_game.HasField('error'):
            print(f'[test] JoinGame error: {resp.join_game.error} details: {resp.join_game.error_details}', flush=True)
        else:
            print(f'[test] JoinGame success, player_id={resp.join_game.player_id}', flush=True)
    except Exception as e:
        print(f'[test] JoinGame exception: {e}', flush=True)

    # Observation #1 - check for debug Marines
    print(f'[test] === Observation #1 ===', flush=True)
    try:
        resp = client.send(sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=30)
        if not resp.HasField('observation'):
            print(f'[test] No observation in response', flush=True)
        else:
            obs = resp.observation.observation
            units = obs.raw_data.units if obs.HasField('raw_data') else []
            print(f'[test] game_loop={obs.game_loop} units={len(units)}', flush=True)
            kernel_units = [u for u in units if abs(u.pos.x - 50.0) < 5.0 and abs(u.pos.y - 50.0) < 5.0]
            initmap_units = [u for u in units if abs(u.pos.x - 45.0) < 5.0 and abs(u.pos.y - 45.0) < 5.0]
            all_marines = [u for u in units if u.unit_type == 74]
            print(f'[test] Units near (50,50) [Kernel Init]: {len(kernel_units)}', flush=True)
            for u in kernel_units:
                print(f'  -> tag={u.tag} type={u.unit_type} owner={u.owner} pos=({u.pos.x:.1f},{u.pos.y:.1f})', flush=True)
            print(f'[test] Units near (45,45) [InitMap debug]: {len(initmap_units)}', flush=True)
            for u in initmap_units:
                print(f'  -> tag={u.tag} type={u.unit_type} owner={u.owner} pos=({u.pos.x:.1f},{u.pos.y:.1f})', flush=True)
            print(f'[test] All Marines (type=74): {len(all_marines)}', flush=True)
            for u in all_marines[:5]:
                print(f'  -> tag={u.tag} owner={u.owner} pos=({u.pos.x:.1f},{u.pos.y:.1f})', flush=True)
    except Exception as e:
        print(f'[test] Observation failed: {e}', flush=True)

    # Send chat command via ActionChat
    print(f'[test] === Sending chat !vibe ===', flush=True)
    chat_msg = '!vibe protocol_version=vibe/1.0;session_id=test;request_id=r1;sequence=1;operation=system.ping;checksum=00000001'
    action = sc_pb.Action(action_chat=sc_pb.ActionChat(channel=1, message=chat_msg))
    try:
        resp = client.send(sc_pb.Request(action=sc_pb.RequestAction(actions=[action])), timeout=30)
        print(f'[test] chat sent (has_action={resp.HasField("action")})', flush=True)
    except Exception as e:
        print(f'[test] Chat send failed: {e}', flush=True)

    # Step the game forward a few loops so chat trigger fires
    try:
        for i in range(10):
            client.send(sc_pb.Request(step=sc_pb.RequestStep(count=8)), timeout=10)
        print(f'[test] Stepped 80 game loops', flush=True)
    except Exception as e:
        print(f'[test] Step failed: {e}', flush=True)

    # Wait and re-check bank file
    time.sleep(3)
    print(f'[test] === Bank file check (after chat) ===', flush=True)
    if os.path.exists(bank_path):
        with open(bank_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        print(f'[test] Bank file exists ({len(content)} bytes):', flush=True)
        print(content[:1500], flush=True)
    else:
        print(f'[test] Bank file does NOT exist', flush=True)

    # Final observation
    print(f'[test] === Final Observation ===', flush=True)
    try:
        resp = client.send(sc_pb.Request(observation=sc_pb.RequestObservation()), timeout=30)
        if resp.HasField('observation'):
            obs = resp.observation.observation
            units = obs.raw_data.units if obs.HasField('raw_data') else []
            print(f'[test] game_loop={obs.game_loop} units={len(units)}', flush=True)
            all_marines = [u for u in units if u.unit_type == 74]
            print(f'[test] Marines: {len(all_marines)}', flush=True)
    except Exception as e:
        print(f'[test] Final observation failed: {e}', flush=True)

    client.close()
    print(f'[test] Done.', flush=True)


if __name__ == '__main__':
    main()
