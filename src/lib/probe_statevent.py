"""StatEvent* 族真机能力探针（round22 新增）。

## 为什么要有这个探针

`gap_scan_round22.json` 扫出 leaderboard 域覆盖率 0%（StatEvent* 家族 740 处
调用），此前历轮一律按"范围外符号不封装"的铁律跳过，理由是：

    StatEventCreate / StatEventSend / StatEventLastCreated / StatEventAddData*
    只出现在 natives_missing.galaxy，core 的 natives.galaxy 里没有文本声明。

但 round22 复查发现这个理由站不住脚，有两条反证：

1. `core.sc2mod/.../NativeLib.TriggerLib` 里 `StatEventCreate` 带 `<FlagNative/>`
   —— 官方 GUI 触发器就能生成对它的直接调用，说明引擎侧注册了这个 native。
2. 更硬的证据：官方合作模式 mod 的 `LibCOOC.galaxy`（我们 stage26 真机跑通过
   的 preselected-commander-overlay）只 include 了 `TriggerLibs/NativeLib` +
   `TriggerLibs/LibertyLib`，**没有任何 `native ... StatEvent` 自声明**，却在
   第 5254 行直接 `StatEventCreate(lp_name);`、5306 行 `StatEventSend(...)`。

=> 推论：SC2 的 native 符号表是**引擎内建**的，`natives.galaxy` 的文本声明只是
   给编辑器/lint 用的元数据；文本里缺声明 ≠ 真机不能调。
   `natives_missing.galaxy` 正是社区从 TriggerLib 元数据回填的补充声明。

但铁律摆在这儿：**静态推理不等于真机能跑**。而且 natives_missing 的文档注释里
写着 "Blizzard only." —— 有可能引擎做了发行方鉴权，自定义地图调用时抛运行时
错误。所以在把 StatEvent* 纳入 CMLib 之前，必须先用真机探针定性。

## 编码方案（可观测单位三态）

单张探针地图的 InitMap 里按顺序做三件事：

    1. UnitCreate Ghost              <- 编译通过 + InitMap 被调用
    2. StatEvent 全链路调用          <- 被测行为
    3. UnitCreate Marine             <- 调用没有中断 trigger 执行

读回 raw observation 后：

    Ghost 有 + Marine 有  => PASS      可编译、可调用、不中断
    Ghost 有 + Marine 无  => TRAP      能编译，但调用触发 runtime error 中断
    Ghost 无 + Marine 无  => COMPILE   编译失败，整图被静默丢弃（铁律症状）

另配一档基线（baseline）：同样造 Ghost+Marine 但不碰 StatEvent。基线必须
PASS，否则说明观测手段本身坏了，被测档的任何结论都不作数（这是反向对照的
另一半——防的是"探针自身失效导致把好符号判成坏符号"）。

## 用法

    python probe_statevent.py            # 基线 + 直调 + 封装形态，全跑
    python probe_statevent.py --wait 60  # SC2 被真人局占用时最多等 60 分钟
    python probe_statevent.py baseline   # 只跑基线
    python probe_statevent.py call       # 只跑直调档
    python probe_statevent.py wrapped    # 只跑 CMLib 封装形态档
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'

REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
sys.path.insert(0, str(REPO / "reference" / "SC2-Neuro-API-Integration"))

from s2clientprotocol import sc2api_pb2 as sc_pb  # noqa: E402

LIB = REPO / "src" / "lib"
sys.path.insert(0, str(LIB))

from sc2_api_conn import acquire_launched, api_url            # noqa: E402
from sc2_proc_guard import human_games                        # noqa: E402

SRC_MAP = LIB / "_testmap_src"
BUILD = LIB / "_statevent_build"
OUT_MAP = LIB / "probe_statevent.SC2Map"
PACKER = REPO / "tools" / "mpq" / "scripts" / "pack_stormlib.py"
STORMLIB = REPO / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll"
RESULT = LIB / "probe_statevent_result.json"

# ---------------------------------------------------------------------------
# 三档 MapScript 主体
# ---------------------------------------------------------------------------

_SPAWN = (
    '    UnitCreate(1, "{u}", c_unitCreateIgnorePlacement, 1,\n'
    "               RegionGetCenter(RegionPlayableMap()), 270.0);\n"
)

# 基线：不碰 StatEvent，纯粹验证"造两个单位并读回"这条观测链路是通的。
BODY_BASELINE = (
    "void InitMap () {\n"
    + _SPAWN.format(u="Ghost")
    + _SPAWN.format(u="Marine")
    + "}\n"
)

# 直调档：Ghost 之后走 StatEvent 全链路，再造 Marine。
# 刻意把 Create/AddData*/Send/LastCreated 全用一遍——只测 Create 的话，
# 万一是 Send 这一步才鉴权失败，就会漏判成"可用"。
BODY_CALL = (
    "void InitMap () {\n"
    "    int lv_ev;\n"
    "    int lv_last;\n"
    + _SPAWN.format(u="Ghost")
    + '    lv_ev = StatEventCreate("CMLibProbe");\n'
      '    StatEventAddDataString(lv_ev, "k_str", "v");\n'
      '    StatEventAddDataInt(lv_ev, "k_int", 42);\n'
      '    StatEventAddDataFixed(lv_ev, "k_fix", 1.5);\n'
      "    lv_last = StatEventLastCreated();\n"
      "    StatEventSend(lv_ev);\n"
    + _SPAWN.format(u="Marine")
    + "}\n"
)

# 封装档：按 CMLib 的实际形态（带守门早退的 void/int 包装函数）再走一遍。
# 直调 PASS 不等于封装 PASS——封装引入了额外的函数边界和 null/空串守门，
# 而 Galaxy 对 native 的某些约束（例如常量折叠要求）在包装后可能变化。
BODY_WRAPPED = (
    "int CMLibProbe_StatEventBegin (string lp_name) {\n"
    '    if (lp_name == "") { return 0; }\n'
    "    return StatEventCreate(lp_name);\n"
    "}\n"
    "\n"
    "void CMLibProbe_StatEventInt (int lp_ev, string lp_key, int lp_value) {\n"
    "    if (lp_ev == 0) { return; }\n"
    '    if (lp_key == "") { return; }\n'
    "    StatEventAddDataInt(lp_ev, lp_key, lp_value);\n"
    "}\n"
    "\n"
    "void CMLibProbe_StatEventEnd (int lp_ev) {\n"
    "    if (lp_ev == 0) { return; }\n"
    "    StatEventSend(lp_ev);\n"
    "}\n"
    "\n"
    "void InitMap () {\n"
    "    int lv_ev;\n"
    + _SPAWN.format(u="Ghost")
    + '    lv_ev = CMLibProbe_StatEventBegin("CMLibProbeWrapped");\n'
      '    CMLibProbe_StatEventInt(lv_ev, "k_int", 7);\n'
      '    CMLibProbe_StatEventInt(0, "guarded", 1);\n'
      '    CMLibProbe_StatEventInt(lv_ev, "", 1);\n'
      "    CMLibProbe_StatEventEnd(lv_ev);\n"
    + _SPAWN.format(u="Marine")
    + "}\n"
)

TIERS = {
    "baseline": BODY_BASELINE,
    "call": BODY_CALL,
    "wrapped": BODY_WRAPPED,
}


def build_map(body: str) -> None:
    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(SRC_MAP, BUILD)
    script = 'include "TriggerLibs/natives"\n\n' + body
    (BUILD / "MapScript.galaxy").write_text(script, encoding="utf-8")
    r = subprocess.run([sys.executable, str(PACKER), str(BUILD), str(OUT_MAP),
                        "--stormlib", str(STORMLIB)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("pack failed: " + (r.stderr or r.stdout))


def observe() -> set[str]:
    """跑一局，返回观测到的单位名集合。"""
    c = acquire_launched()
    md = OUT_MAP.read_bytes()
    r = c.send(sc_pb.Request(create_game=sc_pb.RequestCreateGame(
        local_map=sc_pb.LocalMap(map_data=md),
        player_setup=[sc_pb.PlayerSetup(type=1, race=1, player_name="P1")],
        realtime=True)), 240)
    if r.error:
        c.close()
        raise RuntimeError("CreateGame: " + str(list(r.error)))
    time.sleep(1)
    r = c.send(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
        race=1, options=sc_pb.InterfaceOptions(raw=True))), 120)
    if r.error:
        c.close()
        raise RuntimeError("JoinGame: " + str(list(r.error)))
    rd = c.send(sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True)), 120)
    id2name = {u.unit_id: u.name for u in rd.data.units}
    seen: set[str] = set()
    for _ in range(3):
        time.sleep(2.5)
        ro = c.send(sc_pb.Request(observation=sc_pb.RequestObservation()), 60)
        for u in ro.observation.observation.raw_data.units:
            n = id2name.get(u.unit_type, "")
            if n:
                seen.add(n)
        if {"Ghost", "Marine"} <= seen:
            break
    try:
        c.send(sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), 20)
    except Exception:
        pass
    c.close()
    return seen


def observe_retry(attempts: int = 3) -> set[str]:
    """SC2 连续 create/leave 十几轮后会自崩，那是环境噪声不是结论。"""
    last = None
    for i in range(attempts):
        try:
            return observe()
        except Exception as e:
            last = e
            print(f"  (attempt {i + 1}/{attempts} 传输层失败: {e}; 重试)", flush=True)
            time.sleep(3)
    raise RuntimeError(f"探针连续 {attempts} 次传输层失败: {last}")


def classify(seen: set[str]) -> tuple[str, str]:
    ghost = "Ghost" in seen
    marine = "Marine" in seen
    if ghost and marine:
        return "PASS", "编译通过 + 调用未中断 trigger"
    if ghost and not marine:
        return "TRAP", "能编译，但调用触发 runtime error，中断了 InitMap 后续语句"
    if not ghost and not marine:
        return "COMPILE_FAIL", "MapScript 被引擎静默丢弃（未声明符号导致编译失败）"
    return "WEIRD", "只看到 Marine 没看到 Ghost —— 观测链路异常，结论不作数"


def wait_for_free(max_minutes: int) -> bool:
    """真人局占机时排队等待。铁律：有真人对局绝不清场。"""
    if not human_games():
        return True
    if max_minutes <= 0:
        return False
    deadline = time.time() + max_minutes * 60
    print(f"[probe] 检测到真人局，按铁律不清场，排队等待（最多 {max_minutes} 分钟）…",
          flush=True)
    while time.time() < deadline:
        time.sleep(30)
        if not human_games():
            print("[probe] 真人局已结束，开跑。", flush=True)
            time.sleep(5)
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tiers", nargs="*", default=None,
                    help="要跑的档位: baseline / call / wrapped（默认全跑）")
    ap.add_argument("--wait", type=int, default=0,
                    help="SC2 被真人局占用时最多等待的分钟数")
    args = ap.parse_args()

    order = args.tiers or ["baseline", "call", "wrapped"]
    for t in order:
        if t not in TIERS:
            print(f"未知档位: {t}（可选 {list(TIERS)}）")
            return 2

    if not wait_for_free(args.wait):
        hg = human_games()
        print(f"[probe] SC2 被真人局占用 {hg}，且未等到空闲；按铁律不清场，退出。")
        print("[probe] 提示：加 --wait N 可排队等待 N 分钟。")
        return 3

    print(f"[probe] SC2 API = {api_url()}", flush=True)
    results: dict[str, dict] = {}
    for t in order:
        print(f"\n[probe] ==== 档位 {t} ====", flush=True)
        build_map(TIERS[t])
        seen = observe_retry()
        verdict, why = classify(seen)
        interesting = sorted(x for x in seen if x in ("Ghost", "Marine"))
        print(f"[probe] {t:9s} -> {verdict:12s} {why}")
        print(f"[probe]   观测到: {interesting}")
        results[t] = {"verdict": verdict, "why": why, "units": interesting}

    print("\n[probe] ==== 结论 ====")
    base = results.get("baseline", {}).get("verdict")
    if "baseline" in results and base != "PASS":
        print("[probe] 基线未 PASS —— 观测链路本身有问题，其它档位结论一律不作数。")
        verdict = "INVALID"
    else:
        call = results.get("call", {}).get("verdict")
        wrap = results.get("wrapped", {}).get("verdict")
        if call == "PASS" and wrap in (None, "PASS"):
            verdict = "USABLE"
            print("[probe] StatEvent* 在真机可用（含 CMLib 封装形态）。")
            print("[probe] => 可以撤销'范围外不封装'的判定，纳入 cmlib_stat 模块。")
            print("[probe] 注意：可用 != 数据会被 Battle.net 接收（注释写着 "
                  "Blizzard only）；本探针只证明「调用安全、不炸脚本」。")
        elif call == "COMPILE_FAIL" or wrap == "COMPILE_FAIL":
            verdict = "UNUSABLE_COMPILE"
            print("[probe] StatEvent* 会导致 MapScript 编译失败 —— 维持不封装。")
        elif call == "TRAP" or wrap == "TRAP":
            verdict = "UNUSABLE_RUNTIME"
            print("[probe] StatEvent* 能编译但调用会中断 trigger —— 维持不封装。")
        else:
            verdict = "INCONCLUSIVE"
            print("[probe] 结论不明确，需人工看上面的分档明细。")

    payload = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "verdict": verdict,
        "tiers": results,
    }
    RESULT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(f"[probe] 结果已写入 {RESULT}")
    return 0 if verdict in ("USABLE", "UNUSABLE_COMPILE", "UNUSABLE_RUNTIME") else 1


if __name__ == "__main__":
    sys.exit(main())
