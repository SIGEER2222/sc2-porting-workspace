#!/usr/bin/env python3
"""p0_probe_v2.py — Vibe Kernel P0 传输层真机验证（第二代）

相对 p0_direct.py 的三处关键改进（都是踩坑换来的）：

1. **地图字节直传**。用 create_game(local_map=LocalMap(map_data=<原始字节>))，
   而不是把地图路径丢给 SC2Switcher 当位置参数。
   -> 彻底绕开 `MissingMap`：地图不必放进 SC2 的 Maps 目录，也不依赖账号态。
   这条路径由 src/lib/cmlib_runtime_test.py 在真机上验证通过（16/16 断言）。

2. **复用 src/lib/sc2_api_conn**（端口自动发现 + 崩溃自愈 + launched 态保证）。
   硬编码 5000 是错的：switcher 在 5000 处于 TIME_WAIT 时会静默回退到别的端口。

3. **分层判定**，避免把"传输层现象"误判成"内核没跑"：
       P0-A  内核注册    Bank 出现 kernel 标记         -> MapScript 编译成功 + 触发器执行
       P0-B  RPC 往返    system.ping -> response 里 pong -> Bank 双向通道打通
   P0-A 失败 = 真的编译/注册失败（去看 GameLogs/*ScriptError.txt）。
   P0-A 过、P0-B 挂 = BankLoad 缓存问题（CMRE-RUNTIME-003），不是编译失败。

前置门禁（务必先跑，别拿没过静态检查的地图去开 SC2）：
    python galaxy_compile_check.py --map <地图目录>      # 必须 0 errors
    python wire_map_includes.py   --map <地图目录>        # 装配 Vibe include 图
    python pack_map_mirror.py     --out <打包 .SC2Map>

用法:
    python p0_probe_v2.py --map "E:/SC2/SC2new/StarCraft II/Maps/VibeKernelTest.SC2Map"
    python p0_probe_v2.py --map <...> --wait 40 --skip-rpc
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]                      # sc2-porting-workspace
sys.path.insert(0, str(REPO / "reference" / "SC2-Neuro-API-Integration"))
sys.path.insert(0, str(REPO / "src" / "lib"))
sys.path.insert(0, str(HERE))

from s2clientprotocol import sc2api_pb2 as sc_pb          # noqa: E402
from sc2_api_conn import acquire_launched, api_url        # noqa: E402

BANK_NAME = "GalaxyVibe"
BANKS_ROOT = Path(os.environ.get("USERPROFILE", "C:/Users/22448")) / "Documents" / "StarCraft II" / "Banks"
RACE_TERRAN = 1

# Kernel 注册后应当出现的标记（任一命中即算注册成功）
KERNEL_MARKERS = (
    "index/kernel_initialized",
    "index/initlib_entered",
    "index/init_entered",
    "index/state_version",
    "index/stage16_after_vibe",
    "index/stage16_before_vibe",
)


# --------------------------------------------------------------------------- bank
def find_banks() -> list[Path]:
    """整棵 Banks/ 树里找 GalaxyVibe.SC2Bank（API 模式下可能落在 Banks/<n>/ 子目录）。"""
    if not BANKS_ROOT.is_dir():
        return []
    return sorted(BANKS_ROOT.rglob(f"{BANK_NAME}.SC2Bank"))


def parse_bank(path: Path) -> dict[str, str]:
    try:
        root = ET.parse(path).getroot()
    except Exception as exc:                              # 半写状态是常态，不要炸
        return {"__parse_error__": str(exc)}
    out: dict[str, str] = {}
    for sec in root.iter("Section"):
        sname = sec.get("name")
        for key in sec.iter("Key"):
            v = key.find("Value")
            if v is None:
                continue
            val = v.get("int") or v.get("string") or v.get("fixed") or v.text or ""
            out[f"{sname}/{key.get('name')}"] = val
    return out


def snapshot() -> tuple[list[Path], dict[str, str]]:
    banks = find_banks()
    merged: dict[str, str] = {}
    for b in banks:
        merged.update(parse_bank(b))
    return banks, merged


def pong_for(keys: dict[str, str], rid: str) -> bool:
    """严格判定：keys 中存在 response/<rid>，其 JSON 的 request_id 与 rid 一致且 payload.pong 为真。

    这条判定是 P0-B 唯一可信的通过条件。任何"整个 bank 里出现过 pong 字样"式的
    宽松匹配都会被 SC2 的 Bank 缓存（CMRE-RUNTIME-003）骗过去。
    """
    raw = keys.get(f"response/{rid}")
    if not raw:
        return False
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return False
    if data.get("request_id") != rid:
        return False
    return bool(data.get("payload", {}).get("pong"))


_pong_for = pong_for


def clear_banks() -> list[str]:
    removed = []
    for b in find_banks():
        try:
            b.unlink()
            removed.append(str(b))
        except OSError:
            pass
    return removed


# --------------------------------------------------------------------------- main
def run(args) -> dict:
    res: dict = {
        "map": args.map,
        "api_url": None,
        "steps": [],
        "bank_keys": {},
        "verdict": {"p0a_kernel_registered": False, "p0b_rpc_pong": False, "p0_pass": False},
    }

    def step(name: str, ok: bool, detail: str = "") -> None:
        res["steps"].append({"step": name, "ok": ok, "detail": detail})
        print(f"[{'OK' if ok else 'XX'}] {name}" + (f" — {detail}" if detail else ""))

    map_path = Path(args.map)
    if not map_path.is_file():
        step("map_exists", False, f"找不到 {map_path}")
        return res
    data = map_path.read_bytes()
    step("map_exists", True, f"{len(data)} bytes")

    res["api_url"] = api_url()
    print(f"[i] SC2 API = {res['api_url']}")

    try:
        client = acquire_launched()
    except Exception as exc:
        step("acquire_launched", False, str(exc))
        return res
    step("acquire_launched", True, "SC2 处于 launched 态")

    removed = clear_banks()
    step("clear_bank", True, f"清掉 {len(removed)} 个旧 bank" if removed else "无旧 bank")

    try:
        r = client.send(sc_pb.Request(create_game=sc_pb.RequestCreateGame(
            local_map=sc_pb.LocalMap(map_data=data),
            player_setup=[sc_pb.PlayerSetup(type=1, race=RACE_TERRAN, player_name="P1")],
            realtime=True,
        )), 240)
    except Exception as exc:
        step("create_game", False, str(exc))
        client.close()
        return res
    if r.error:
        step("create_game", False, f"error={list(r.error)} {r.error_details}")
        client.close()
        return res
    step("create_game", True, "地图字节直传成功")

    time.sleep(1)
    try:
        r = client.send(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
            race=RACE_TERRAN, options=sc_pb.InterfaceOptions(raw=True))), 180)
    except Exception as exc:
        step("join_game", False, str(exc))
        client.close()
        return res
    if r.error:
        step("join_game", False, f"error={list(r.error)} {r.error_details}")
        client.close()
        return res
    step("join_game", True, f"player_id={r.join_game.player_id}")

    # ---- P0-A: 等 Kernel 注册标记 ----
    deadline = time.time() + args.wait
    found_marker = None
    keys: dict[str, str] = {}
    while time.time() < deadline:
        time.sleep(2)
        _, keys = snapshot()
        hit = [m for m in KERNEL_MARKERS if m in keys]
        if hit:
            found_marker = hit
            break
        try:
            ro = client.send(sc_pb.Request(observation=sc_pb.RequestObservation()), 60)
            loop = ro.observation.observation.game_loop
        except Exception:
            loop = -1
        print(f"    ...等待内核注册 loop={loop} bank_keys={len(keys)}")

    res["bank_keys"] = keys
    if found_marker:
        res["verdict"]["p0a_kernel_registered"] = True
        step("P0-A 内核注册", True, f"命中标记 {found_marker}")
    else:
        step("P0-A 内核注册", False,
             f"{args.wait}s 内 Bank 无内核标记（bank_keys={len(keys)}）→ 查 GameLogs/*ScriptError.txt")

    # ---- P0-B: RPC 往返 ----
    if found_marker and not args.skip_rpc:
        try:
            from host.vibe_host import RpcRequest, write_bank_request     # noqa: E402
            rid = uuid.uuid4().hex[:12]
            req = RpcRequest(session_id="p0v2", request_id=rid, sequence=1, operation="system.ping")
            write_bank_request(BANK_NAME, rid, req)
            step("write_rpc_request", True, f"request_id={rid} operation=system.ping")

            rpc_deadline = time.time() + args.rpc_wait
            pong = False
            while time.time() < rpc_deadline:
                time.sleep(1.5)
                _, keys = snapshot()
                # 严格判定：必须是 *本次* request_id 的 response，且 payload.pong 为真。
                # 旧写法 `rid in blob and "pong" in blob` 是假阳性发生器 ——
                # rid 来自探针自己写的 request/<rid>，"pong" 可能来自上一场遗留的
                # response/<其它 id>（SC2 Bank 缓存会把旧内容重新落盘）。
                # 2026-08-08 实测：15:11 那次 "P0 PASS" 就是这样蒙出来的。
                if _pong_for(keys, rid):
                    pong = True
                    break
            res["bank_keys"] = keys
            res["verdict"]["p0b_rpc_pong"] = pong
            step("P0-B RPC 往返", pong,
                 "收到 pong" if pong else
                 f"{args.rpc_wait}s 内无响应 → 疑似 BankLoad 缓存 (CMRE-RUNTIME-003)，非编译失败")
        except Exception as exc:
            step("P0-B RPC 往返", False, f"异常: {exc}")
    elif args.skip_rpc:
        step("P0-B RPC 往返", False, "--skip-rpc 跳过")

    client.leave()
    client.close()

    res["verdict"]["p0_pass"] = res["verdict"]["p0a_kernel_registered"] and (
        res["verdict"]["p0b_rpc_pong"] or args.skip_rpc)
    return res


def main() -> int:
    ap = argparse.ArgumentParser(description="Vibe Kernel P0 真机验证 v2（地图字节直传）")
    ap.add_argument("--map", default=r"E:/SC2/SC2new/StarCraft II/Maps/VibeKernelTest.SC2Map")
    ap.add_argument("--wait", type=float, default=45.0, help="等待内核注册的秒数")
    ap.add_argument("--rpc-wait", type=float, default=25.0, help="等待 RPC 响应的秒数")
    ap.add_argument("--skip-rpc", action="store_true", help="只验 P0-A 注册")
    ap.add_argument("--out", default=str(REPO / "artifacts" / "galaxy-vibe" / "p0-probe-v2-verdict.json"))
    args = ap.parse_args()

    res = run(args)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")

    v = res["verdict"]
    print("\n=================== VERDICT ===================")
    print(f"  P0-A 内核注册 : {'PASS' if v['p0a_kernel_registered'] else 'FAIL'}")
    print(f"  P0-B RPC 往返 : {'PASS' if v['p0b_rpc_pong'] else 'FAIL'}")
    print(f"  P0 总体       : {'PASS' if v['p0_pass'] else 'FAIL'}")
    print(f"  verdict -> {out}")
    return 0 if v["p0_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
