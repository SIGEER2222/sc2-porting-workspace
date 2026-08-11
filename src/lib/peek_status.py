"""只读窥探当前 SC2 API 实例状态 —— 绝不 create_game / leave_game / kill。

用途：自动化轮次开始时判断"能不能占用 SC2 跑真机矩阵"。
  launched(1) = 停在启动器/菜单，安全可用
  in_game(3)  = 用户正在对局，必须避让（铁律：不杀用户 SC2）
"""
import os
import sys

os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'
REPO = r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
sys.path.insert(0, os.path.join(REPO, "reference", "SC2-Neuro-API-Integration"))
sys.path.insert(0, os.path.join(REPO, "src", "lib"))

from sc2_api_conn import Client, api_url, discover_api_port  # noqa: E402

NAMES = {1: "launched(菜单/启动器,可用)", 2: "init_game(死胡同,需重启)",
         3: "in_game(对局中,避让)", 4: "in_replay", 5: "ended(可复用)", 6: "quit"}

port = discover_api_port(default=0)
if not port:
    print("STATUS=NO_SC2  没发现运行中的 SC2_x64")
    sys.exit(0)

c = None
try:
    c = Client(api_url(port)).connect()
    st = c.status(20)
    print(f"PORT={port} STATUS={st} {NAMES.get(st, '?')}")
    print("USABLE=" + ("1" if st in (1, 5) else "0"))
except Exception as e:
    print(f"PORT={port} STATUS=ERR {type(e).__name__}: {e}")
    print("USABLE=0")
finally:
    if c is not None:
        c.close()
