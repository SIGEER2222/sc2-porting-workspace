"""多变体真机跑批器：等 SC2 就绪 → 跑 P0 探针 → 分类结果 → 崩溃自愈。

【为什么需要它】
手工逐个跑变体时有三种失败会互相混淆，导致误判：
  1. SILENT-DROP  join_game 成功、但 45s 内 Bank 无地图侧 key
                  ⇒ 编译错误，SC2 静默丢弃整个 MapScript（我们要找的那个）
  2. CRASH        join_game 抛 "Received message 257"，SC2 进程当场消失
                  ⇒ 不是编译错误，是运行期崩溃，属另一类问题，不能算 FAIL 证据
  3. NOT-READY    ws 连不上（ServerDisconnectedError）
                  ⇒ SC2 没准备好，与地图无关，必须重试而不是记 FAIL

【SC2 就绪判据（勿改回内存判据）】
窗口最小化时 Windows 裁剪工作集，tasklist 只报十几 MB 但 API 完全可用。
唯一可靠信号是 /sc2api 的 websocket 握手能否成功。

用法:
    python run_variants.py <map1> [<map2> ...]
    python run_variants.py --wait 40 <map...>
"""
from __future__ import annotations

import base64
import json
import os
import socket
import struct
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
GV = HERE.parent
REPO = GV.parents[1]
PY311 = r"C:/Users/22448/AppData/Local/Programs/Python/Python311/python.exe"
VERDICT = REPO / "artifacts" / "galaxy-vibe" / "p0-probe-v3-verdict.json"
LOGDIR = REPO / "artifacts" / "galaxy-vibe" / "variant-logs"
LAUNCHER = GV / "launch-galaxy-vibe.ps1"
PORT = 5000


# ----------------------------------------------------------------- SC2 就绪
def sc2_alive() -> bool:
    # 【勿改】中文 Windows 的 tasklist 输出是 GBK，用默认 utf-8 解码会抛
    # UnicodeDecodeError，subprocess 把 stdout 置 None ⇒ 后续 `in out` 崩。
    try:
        out = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq SC2_x64.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, encoding="mbcs", errors="replace",
            timeout=15).stdout
    except Exception:                                    # noqa: BLE001
        return False
    return bool(out) and "SC2_x64" in out


def ws_ok(port: int = PORT) -> bool:
    """裸 websocket 握手；成功即 SC2 API 已接受连接。"""
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
    except OSError:
        return False
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        s.sendall((f"GET /sc2api HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                   f"Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\n"
                   f"Sec-WebSocket-Version: 13\r\n\r\n").encode())
        s.settimeout(5)
        if b"101" not in s.recv(4096).split(b"\r\n", 1)[0]:
            return False
        mask = os.urandom(4)
        pl = struct.pack(">H", 1000)
        s.sendall(b"\x88" + bytes([0x80 | len(pl)]) + mask
                  + bytes(b ^ mask[i % 4] for i, b in enumerate(pl)))
        return True
    except OSError:
        return False
    finally:
        s.close()


def wait_ready(timeout: float = 420.0) -> bool:
    t0, last = time.time(), ""
    while time.time() - t0 < timeout:
        if ws_ok():
            print(f"  [ready] SC2 API 可连（等待 {time.time() - t0:.0f}s）", flush=True)
            return True
        msg = "进程在，ws 未接受" if sc2_alive() else "SC2 进程不在"
        if msg != last:
            print(f"  [wait ] {msg}", flush=True)
            last = msg
        time.sleep(3)
    return False


def relaunch() -> bool:
    """SC2 挂了且没自动拉起时，用 launcher 重启一个干净实例。"""
    print("  [relaunch] 调 launch-galaxy-vibe.ps1 重启 SC2 ...", flush=True)
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(LAUNCHER), "-Port", str(PORT)],
        capture_output=True, text=True, timeout=600)
    return wait_ready()


# ----------------------------------------------------------------- 跑探针
def probe(map_path: str, wait_s: int) -> tuple[str, str]:
    """返回 (分类, 摘要)。分类 ∈ REG-OK / SILENT-DROP / CRASH / NOT-READY / ERROR。"""
    env = dict(os.environ)
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    p = subprocess.run(
        [PY311, str(GV / "p0_probe_v3.py"), "--map", map_path,
         "--channels", "bank", "--wait", str(wait_s)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(GV), timeout=wait_s + 300)
    out = (p.stdout or "") + (p.stderr or "")
    LOGDIR.mkdir(parents=True, exist_ok=True)
    (LOGDIR / f"{Path(map_path).stem}.log").write_text(out, encoding="utf-8")

    if "message 257" in out or "not WSMsgType.BINARY" in out:
        return "CRASH", "join_game 期间 SC2 进程消失"
    if "Server disconnected" in out or "ws_connect failed" in out:
        return "NOT-READY", "ws 连接被拒/断开"

    steps: dict[str, tuple[bool, str]] = {}
    if VERDICT.is_file():
        try:
            d = json.loads(VERDICT.read_text(encoding="utf-8"))
            # verdict 是全局单文件，必须确认它属于本次跑的地图，否则会读到上一轮残留
            if Path(d.get("map", "")).name != Path(map_path).name:
                return "ERROR", f"verdict 属于 {d.get('map')}，与本次不符"
            for st in d.get("steps", []):
                steps[st.get("step", "")] = (bool(st.get("ok")), st.get("detail", ""))
        except Exception as e:                           # noqa: BLE001
            return "ERROR", f"verdict 解析失败: {e}"

    for key, (ok, detail) in steps.items():
        if "内核注册" in key:
            return ("REG-OK" if ok else "SILENT-DROP"), detail
    # 没走到内核注册那一步 ⇒ 前置步骤挂了，报出第一个失败步骤，别笼统记 ERROR
    for key, (ok, detail) in steps.items():
        if not ok:
            kind = "CRASH" if key == "join_game" else "PRE-FAIL"
            return kind, f"{key}: {detail}"
    return "ERROR", out[-200:]


def main() -> int:
    args = sys.argv[1:]
    wait_s = 40
    if "--wait" in args:
        i = args.index("--wait")
        wait_s = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        print(__doc__)
        return 2

    rows: list[tuple[str, str, str]] = []
    for m in args:
        name = Path(m).stem
        print(f"\n{'=' * 70}\n[VARIANT] {name}\n{'=' * 70}", flush=True)
        if not Path(m).is_file():
            rows.append((name, "MISSING", m))
            continue
        for attempt in (1, 2):
            if not wait_ready(120 if attempt == 1 else 420):
                if not relaunch():
                    rows.append((name, "NOT-READY", "SC2 起不来"))
                    break
            kind, note = probe(m, wait_s)
            print(f"  -> {kind}  {note[:120]}", flush=True)
            # CRASH / NOT-READY 只有第一次才重试；重试仍同样则记录之
            if kind in {"CRASH", "NOT-READY"} and attempt == 1:
                print("  [retry] 该分类不可作为编译结论，等 SC2 恢复后重跑一次",
                      flush=True)
                time.sleep(5)
                continue
            rows.append((name, kind, note[:120]))
            break

    print(f"\n{'=' * 70}\n跑批结果\n{'=' * 70}")
    for n, k, note in rows:
        print(f"  [{k:11s}] {n}")
        if k != "REG-OK" and note:
            print(f"                {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
