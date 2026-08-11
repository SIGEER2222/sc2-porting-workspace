"""CMLib 模块级真机编译探针。

原理：真实 SC2 引擎在 MapScript 编译失败时会静默跳过整个 InitMap()。
利用这一点做二分——MapScript 只 include 前 K 个模块并创建一个 Ghost：
  Ghost 出现   => 前 K 个模块在真引擎里编译通过
  Ghost 不出现 => 第 K 个模块引入了编译错误

用法：
  python probe_modules.py            # 累积式线性扫描，定位第一个失败模块
  python probe_modules.py 5          # 只测前 5 个模块
  python probe_modules.py file <name># 单测某个文件（含 core 前置）
"""
import os, re, sys, time, shutil, asyncio, threading, subprocess
from pathlib import Path

os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'
REPO = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace")
sys.path.insert(0, str(REPO / "reference" / "SC2-Neuro-API-Integration"))

from s2clientprotocol import sc2api_pb2 as sc_pb

LIB = REPO / "src" / "lib"
sys.path.insert(0, str(LIB))
from sc2_api_conn import acquire_launched, api_url   # noqa: E402

SRC_MAP = LIB / "_testmap_src"
BUILD = LIB / "_probe_build"
OUT_MAP = LIB / "probe.SC2Map"
CMLIB_SRC = LIB / "scripts" / "cmlib"
PACKER = REPO / "tools" / "mpq" / "scripts" / "pack_stormlib.py"
STORMLIB = REPO / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll"

def discover_modules():
    """从聚合入口 cmlib.galaxy 的 include 顺序自动推导模块清单。

    绝不手抄这张表——手抄必漂移，且漂移后症状极其阴险：
      trig 被加进 cmlib.galaxy 却漏在硬编码表里 -> `probe all` 报 PASS，
      而走聚合入口的自测地图静默失败，探针等于在测一个不存在的组合。
      （game/conv/udata/stock 四个新模块又踩了同一个坑，故改为自动推导。）
    """
    txt = (CMLIB_SRC / "cmlib.galaxy").read_text(encoding="utf-8", errors="ignore")
    mods = []
    for m in re.finditer(r'include\s+"scripts/cmlib/cmlib_(\w+?)(_h)?"', txt):
        name = m.group(1)
        if name not in mods:
            mods.append(name)
    if not mods:
        raise RuntimeError("无法从 cmlib.galaxy 推导模块清单")
    return mods


MODULES = discover_modules()

# 库外的额外源目录（selftest 是测试脚本真源，不属于 CMLib 本体）。
EXTRA_SRC_DIRS = [LIB / "selftest"]


def build_map(includes):
    if BUILD.exists():
        shutil.rmtree(BUILD)
    shutil.copytree(SRC_MAP, BUILD)
    dst = BUILD / "Base.SC2Data" / "scripts" / "cmlib"
    dst.mkdir(parents=True, exist_ok=True)
    for f in CMLIB_SRC.glob("*.galaxy"):
        shutil.copy(f, dst)
    # 额外源（如 cmlib_selftest.galaxy）后拷，且不覆盖库本体的同名文件
    for d in EXTRA_SRC_DIRS:
        if not d.exists():
            continue
        for f in d.glob("*.galaxy"):
            if not (CMLIB_SRC / f.name).exists():
                shutil.copy(f, dst)
    body = 'include "TriggerLibs/natives"\n'
    body += "".join(f'include "{i}"\n' for i in includes)
    body += (
        "\nvoid InitMap () {\n"
        '    UnitCreate(1, "Ghost", c_unitCreateIgnorePlacement, 1,\n'
        "               RegionGetCenter(RegionPlayableMap()), 270.0);\n"
        "}\n")
    (BUILD / "MapScript.galaxy").write_text(body, encoding="utf-8")
    r = subprocess.run([sys.executable, str(PACKER), str(BUILD), str(OUT_MAP),
                        "--stormlib", str(STORMLIB)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("pack failed: " + r.stderr)


def run_probe():
    """返回 True 表示 Ghost 出现（编译通过）。"""
    c = acquire_launched()
    md = OUT_MAP.read_bytes()
    r = c.send(sc_pb.Request(create_game=sc_pb.RequestCreateGame(
        local_map=sc_pb.LocalMap(map_data=md),
        player_setup=[sc_pb.PlayerSetup(type=1, race=1, player_name="P1")],
        realtime=True)), 240)
    if r.error:
        c.close(); raise RuntimeError("CreateGame: " + str(list(r.error)))
    time.sleep(1)
    r = c.send(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
        race=1, options=sc_pb.InterfaceOptions(raw=True))), 120)
    if r.error:
        c.close(); raise RuntimeError("JoinGame: " + str(list(r.error)))
    rd = c.send(sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True)), 120)
    id2name = {u.unit_id: u.name for u in rd.data.units}
    found = False
    for _ in range(3):
        time.sleep(2.5)
        ro = c.send(sc_pb.Request(observation=sc_pb.RequestObservation()), 60)
        names = [id2name.get(u.unit_type, "") for u in ro.observation.observation.raw_data.units]
        if "Ghost" in names:
            found = True
            break
    try:                       # 主动退局，让下一轮能拿到干净的 launched 状态
        c.send(sc_pb.Request(leave_game=sc_pb.RequestLeaveGame()), 20)
    except Exception:
        pass
    c.close()
    return found


def probe_retry(attempts=3):
    """真机探针 + 重试。

    SC2 在连续 create_game/leave_game 十几轮后经常自崩，表现为
    ServerDisconnected。那是环境噪声，不是被测代码的编译结论，
    必须重试而不是记成 FAIL——否则会把好模块冤枉成坏模块。
    """
    last = None
    for i in range(attempts):
        try:
            return run_probe()
        except Exception as e:
            last = e
            print(f"[probe]   (attempt {i+1}/{attempts} 传输层失败: {e}; 重试)",
                  flush=True)
            time.sleep(3)
    raise RuntimeError(f"探针连续 {attempts} 次传输层失败: {last}")


def includes_for(k):
    hs = [f'scripts/cmlib/cmlib_{m}_h' for m in MODULES[:k]]
    impls = [f'scripts/cmlib/cmlib_{m}' for m in MODULES[:k]]
    return hs + impls


def main():
    print(f"[probe] SC2 API = {api_url()}", flush=True)

    # 一次性测全库（改完 include 后最常用：只想知道整库能不能编译）
    if len(sys.argv) > 1 and sys.argv[1] == "all":
        build_map(includes_for(len(MODULES)))
        ok = probe_retry()
        print(f"[probe] ALL {len(MODULES)} 模块 -> {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1

    # 二分定位首个失败模块：累积 include 具单调性（前 k 通过 => 前 k-1 也通过），
    # 11 个模块只要 ~4 轮，比线性扫描省一大半真机加载时间。
    if len(sys.argv) > 1 and sys.argv[1] == "bisect":
        lo = int(sys.argv[2]) if len(sys.argv) > 2 else 1   # 已知通过的下界
        hi = len(MODULES)
        first_fail = None
        while lo <= hi:
            mid = (lo + hi) // 2
            build_map(includes_for(mid))
            ok = probe_retry()
            print(f"[probe] k={mid:2d} (…+{MODULES[mid-1]:8s}) -> "
                  f"{'PASS' if ok else 'FAIL'}", flush=True)
            if ok:
                lo = mid + 1
            else:
                first_fail = mid
                hi = mid - 1
        print("\n[probe] ==== 结论 ====")
        if first_fail is None:
            print(f"[probe] 全部 {len(MODULES)} 个模块通过真机编译")
            return 0
        print(f"[probe] 首个真机编译失败的模块: cmlib_{MODULES[first_fail-1]} "
              f"(k={first_fail})")
        return 1

    # 任意 include 组合的裸探针：用来单独验证某个引擎库本身能不能挂。
    #   python probe_modules.py raw TriggerLibs/AI
    if len(sys.argv) > 2 and sys.argv[1] == "raw":
        incs = sys.argv[2:]
        build_map(incs)
        ok = probe_retry()
        print(f"[probe] raw {incs} -> {'PASS' if ok else 'FAIL'}")
        return 0 if ok else 1

    if len(sys.argv) > 2 and sys.argv[1] == "file":
        name = sys.argv[2]
        inc = ["scripts/cmlib/cmlib_core_h", "scripts/cmlib/cmlib_core", f"scripts/cmlib/{name}"]
        build_map(inc)
        print(f"[probe] file {name}: {'PASS' if probe_retry() else 'FAIL'}")
        return 0

    limit = int(sys.argv[1]) if len(sys.argv) > 1 else len(MODULES)
    first_fail = None
    aborted = None       # 传输层错误 != 编译失败，必须区分，否则会误报"全部通过"
    done = 0
    for k in range(1, limit + 1):
        build_map(includes_for(k))
        try:
            ok = probe_retry()
        except Exception as e:
            aborted = f"k={k} ({MODULES[k-1]}): {e}"
            print(f"[probe] k={k} ({MODULES[k-1]}) ERROR {e}", flush=True)
            break
        done = k
        print(f"[probe] k={k:2d} +{MODULES[k-1]:8s} -> {'PASS' if ok else 'FAIL'}", flush=True)
        if not ok:
            first_fail = MODULES[k - 1]
            break
    print("\n[probe] ==== 结论 ====")
    if aborted:
        print(f"[probe] INCONCLUSIVE —— 探针在传输层中断（非编译结论）: {aborted}")
        print(f"[probe] 已确认通过的模块数: {done}/{limit}；请重启 SC2 API 实例后重跑。")
        return 2
    if first_fail:
        print(f"[probe] 首个在真实 SC2 引擎中编译失败的模块: cmlib_{first_fail}")
        return 1
    print(f"[probe] 前 {limit} 个模块全部通过真机编译")
    return 0


if __name__ == "__main__":
    sys.exit(main())
