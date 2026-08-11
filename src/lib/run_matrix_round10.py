"""三档真机矩阵驱动器：带瞬态重试，把「传输层抖动」和「真实测试结论」分开。

为什么需要它（round-8/round-10 两次踩坑）：
  · SC2 API 实例连跑十几局会自己崩，switcher 重启后端口可能从 5000 漂到别的号；
  · 濒死实例上跑出来的 FAIL（Ghost=0 但 bank 里有 Magic）是假阴性，
    直接写进结论就是污染证据链。
判定规则：
  · 抛异常（WSMessageTypeError 等传输层）      -> 瞬态，重试
  · Ghost=0 但 bank 有 Magic（脚本明明跑了）   -> 瞬态，重试
  · **运行期间 SC2 被外部杀掉 / 真人局插入**   -> 瞬态，重试（round18 新增，见下）
  · Ghost=0 且 bank 无 Magic                   -> 真 FAIL（反向对照的期望态）
  · PASS / PARTIAL                             -> 真结论，直接采信

round18 补的第三条（2026-08-09 12:12 事故）：
  本仓库有多个按小时跑的自动化都要独占 SC2。那一轮模块四的自动化正在
  "强杀 SC2 → 重起 API 模式"，SC2 处于崩溃重启循环；本矩阵的实例被外部杀掉，
  地图根本没机会跑 -> `Ghost=0 且 bank 无 Magic` -> 被当成**真 FAIL** 写进结论，
  差点让人去改一个根本没坏的库。假阴性比失败更贵。
  防线：① `SC2Lock` 跨自动化建议锁（要对方也接）；② `ApiWatch` 单边干扰探测（兜底，
  不依赖任何人配合）。
"""
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sc2_proc_guard import assert_no_human_game, human_games, kill_api_instances
from sc2_lock import ApiWatch, SC2Lock

LIB = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib")
PY = r"C:\Users\22448\AppData\Local\Programs\Python\Python311\python.exe"
RUNNER = LIB / "cmlib_runtime_test.py"

TIERS = [
    ("内联源码版", LIB / "test_cmlib.SC2Map", "PASS"),
    ("依赖挂载版", LIB / "test_cmlib_dep.SC2Map", "PASS"),
    ("反向对照", LIB / "test_cmlib_neg.SC2Map", "FAIL"),
]


def run_once(map_path: Path):
    """跑一档，并在整个运行期间盯着有没有外部干扰。

    返回 (输出文本, 干扰原因或 "")。
    """
    env = dict(os.environ, PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="python")
    watch = ApiWatch().start()
    try:
        p = subprocess.run([PY, str(RUNNER), str(map_path)], cwd=str(LIB),
                           capture_output=True, text=True, errors="replace",
                           env=env, timeout=420)
        out = (p.stdout or "") + (p.stderr or "")
    finally:
        watch.stop()
    return out, (watch.reason if watch.interfered else "")


def classify(out: str):
    """返回 (verdict, transient, detail)。"""
    if "WSMessageTypeError" in out or "Server disconnected" in out \
            or "Traceback" in out:
        return "ERROR", True, "传输层异常"
    m = re.search(r"断言通过 (\d+)/(\d+)", out)
    detail = m.group(0) if m else ""
    has_magic = "13371337" in out
    ghost0 = re.search(r"Ghost\s+= 0", out) is not None
    if "PASS —" in out:
        return "PASS", False, detail
    # 「地图根本没起来」必须先于 PARTIAL 匹配 —— 这是最根本的失败信号，
    # 也正是反向对照档的期望态。
    # round22 踩坑：runner 新加的断言会计门被插在 sentinel 门之前，反向对照
    # 被降级成 `PARTIAL — 断言会计不符`，这里又因为 PARTIAL 匹配在前而跟着
    # 误判，整轮 rc=1。runner 已修顺序；这里再加一道**双保险**：不依赖 runner
    # 的分支顺序，只要 Ghost=0 或输出里出现 sentinel 缺席字样，一律归 FAIL 家族。
    # 反向对照拿不到 FAIL = 排假阳性的防线被拆 = 正向 PASS 也随之不可信，
    # 这种判据不能只靠单点正确性。
    if ghost0 or "FAIL — sentinel" in out:
        if has_magic:
            return "FAIL?", True, "Ghost=0 但 bank 有 Magic -> 濒死实例假阴性"
        return "FAIL", False, "Ghost=0 且 bank 无 Magic（地图起不来）"
    if "PARTIAL —" in out:
        tags = re.search(r"'Result/FailTags': '([^']*)'", out)
        return "PARTIAL", False, detail + (
            f"  失败标签: {tags.group(1)}" if tags else "")
    return "UNKNOWN", True, "无法判定"


# 连续观察到「无真人对局」多少次才算真的空闲。
# round17 实测踩坑：用户在**换地图/重开一局**时 SC2 进程会短暂消失几秒，
# 单次快照为空就开跑 -> 几秒后新局起来 -> 清场时 assert 抛错，整个矩阵崩在起跑线上。
STABLE_CHECKS = 4          # 4 次 x 30s = 连续 2 分钟无真人局
POLL_SEC = 30


def clear_sc2(max_minutes=0):
    """清场：只杀带 `-listen` 的 API 探针实例，绝不碰真人对局。

    旧实现是 `Get-Process -Name SC2_x64,SC2Switcher_x64 | Stop-Process -Force`，
    会把用户正在玩的那一局一起干掉。自动化按小时跑，撞上只是时间问题。

    max_minutes>0 时，撞上真人局不抛错而是回到排队等待（处理"等待→清场"
    之间用户又开了一局的竞态）。
    """
    for _ in range(6):
        try:
            kill_api_instances(guard=True)
            time.sleep(6)
            return
        except RuntimeError:
            if max_minutes <= 0:
                raise
            print("[matrix] 清场前又检测到真人对局（用户换局？），退回排队等待")
            wait_for_free(max_minutes)
    raise RuntimeError("清场反复被真人对局打断，放弃本轮")


def wait_for_free(max_minutes):
    """真人对局占着机器时排队等待，而不是直接失败。

    自动化按小时跑，撞上真人局是常态。硬失败会让"通用库没通过验证"
    这个结论被环境噪声污染；等待则把它变成一次干净的推迟。
    max_minutes<=0 表示不等待（撞上就抛错）。

    判据带去抖：必须连续 STABLE_CHECKS 次快照都没有真人局才认为空闲，
    避免把"换局的几秒空窗"误当成用户已经不玩了。
    """
    if max_minutes <= 0:
        assert_no_human_game("跑三档真机矩阵")
        return
    deadline = time.time() + max_minutes * 60
    notified = False
    stable = 0
    while True:
        if human_games():
            if not notified:
                print(f"[matrix] 检测到真人对局，排队等待（最多 {max_minutes} 分钟）"
                      f"…… 绝不打断用户的游戏", flush=True)
                notified = True
            if stable:
                print(f"[matrix] 空窗被打断（stable {stable}/{STABLE_CHECKS} 清零）"
                      f"—— 大概率是换局，继续等", flush=True)
            stable = 0
        else:
            stable += 1
            if stable >= STABLE_CHECKS:
                break
            if notified:
                print(f"[matrix] 无真人对局 {stable}/{STABLE_CHECKS}"
                      f"（连续 {STABLE_CHECKS} 次才开跑，防换局误判）", flush=True)
        if time.time() > deadline:
            assert_no_human_game(f"跑三档真机矩阵（已等待 {max_minutes} 分钟）")
        time.sleep(POLL_SEC)
    if notified:
        print("[matrix] 真人对局已稳定结束，开始跑矩阵", flush=True)


def main():
    # 开跑前先确认没有真人对局：矩阵要反复清场+拉起实例，
    # 撞上真人局既会误杀，也会让端口发现读到错误的进程。
    # 用 `--wait <分钟>` 让它排队等待而不是硬失败。
    wait_min = 0
    if "--wait" in sys.argv:
        wait_min = int(sys.argv[sys.argv.index("--wait") + 1])
    # `--only <子串>`：只重跑匹配的档位（round23 加）。
    # 动机：一档 ~3 分钟，全矩阵 ~9 分钟。当外部 SC2 干扰只打断了某一档时，
    # 重跑整个矩阵纯属浪费——但**只允许用于重跑被判瞬态 ERROR 的档**，
    # 不允许用它挑一个好看的档来"证明"库没问题：结论仍以全矩阵为准。
    only = ""
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]

    # 前置：产物必须比源码新（round24 加，见 README §11.8）。
    # 「测的就是交付的」此前只靠纪律维持，round24 静默破了一次：README 在构建之后
    # 才被追加章节，交付的 .SC2Mod 里装着过期文档，而三档矩阵照样全绿。
    # 同样的时序错位发生在 .galaxy 上就是"矩阵验旧库、交付新库"且毫无信号。
    # 故 fail-closed：产物陈旧就拒跑，绝不产出一个测错对象的 PASS。
    # `--skip-freshness` 只留给"明知产物就是要测的那份"的排障场景。
    if "--skip-freshness" not in sys.argv:
        fresh = subprocess.run([sys.executable, "check_artifact_freshness.py"],
                               cwd=str(Path(__file__).resolve().parent))
        if fresh.returncode != 0:
            print("[matrix] 产物与源码不同步，拒跑（先重建四件产物）。"
                  "确知无碍可加 --skip-freshness 强行开跑。")
            sys.exit(2)

    wait_for_free(wait_min)

    # 跨自动化建议锁：本仓库多个 hourly 任务都要独占 SC2，谁都可能在别人跑到
    # 一半时把实例强杀。拿不到锁就让路（不硬闯），拿到就在整轮持有。
    lock = SC2Lock("cmlib-matrix", wait_minutes=max(wait_min, 20))
    if not lock.acquire():
        print("[matrix] 另一自动化正在独占 SC2，本轮让路（不产出结论，避免假阴性）")
        sys.exit(2)

    try:
        return _run_tiers(wait_min, only)
    finally:
        lock.release()


def _run_tiers(wait_min: int, only: str = ""):
    tiers = [t for t in TIERS if not only or only in t[0] or only in t[1].name]
    if not tiers:
        print(f"[matrix] --only {only!r} 没匹配到任何档位，可选：" +
              " / ".join(t[0] for t in TIERS))
        sys.exit(2)
    if only:
        print(f"[matrix] 只跑 {len(tiers)}/{len(TIERS)} 档（--only {only}）；"
              f"完整结论仍需三档齐全")
    results = []
    for name, path, expect in tiers:
        # 每档前清掉 SC2，确保本档在全新实例上跑。原因（2026-08-08 实测）：
        # 150 个 Marauder 的生成循环会被 SC2 按「每 tick 触发器时间预算」切成多 tick
        # 完成；上一档残留状态 / 实例变热会让末段滞后落进观测窗口之外，误判 PARTIAL。
        # harness 会在 create_game 时自拉起一个干净实例。
        clear_sc2(wait_min)
        print(f"\n{'=' * 68}\n[matrix] {name}  <- {path.name}  期望={expect}\n{'=' * 68}")
        verdict, transient, detail = "UNKNOWN", True, ""
        for attempt in range(1, 6):
            out, interference = run_once(path)
            verdict, transient, detail = classify(out)
            if interference:
                # 外部干扰下任何结论都不可信 —— 包括看起来"通过"的。
                # 12:12 事故就是把被外部杀掉的实例判成了真 FAIL。
                verdict, transient = "ERROR", True
                detail = f"外部干扰: {interference}"
            print(f"[matrix]   第 {attempt} 次: {verdict}  {detail}")
            if not transient:
                break
            print("[matrix]   -> 判为瞬态，清场后重试")
            clear_sc2(wait_min)
        ok = (verdict == expect) or (expect == "FAIL" and verdict == "FAIL")
        results.append((name, expect, verdict, detail, ok))

    print(f"\n{'=' * 68}\n[matrix] 汇总\n{'=' * 68}")
    allok = True
    for name, expect, verdict, detail, ok in results:
        allok = allok and ok
        print(f"  {'OK ' if ok else 'BAD'}  {name:<12} 期望={expect:<5} "
              f"实得={verdict:<8} {detail}")
    # 措辞必须诚实反映实际跑了几档：`--only` 单档通过时打印"三档矩阵全部符合预期"
    # 会让一次局部重跑被当成完整证据引用 —— 这正是本文件开头那类假结论的温床。
    partial = len(results) < len(TIERS)
    if not allok:
        tail = "存在不符合预期的档位"
    elif partial:
        tail = (f"已跑的 {len(results)}/{len(TIERS)} 档符合预期"
                f"（**非完整矩阵，不能单独作为结论**，需三档齐全）")
    else:
        tail = "三档矩阵全部符合预期"
    print("\n[matrix] " + tail)
    sys.exit(0 if allok else 1)


# 必须带 __main__ 守卫：`classify()` 是纯函数，值得被别的脚本（判定顺序回归钉
# test_verdict_order.py）直接 import 复用；裸 `main()` 会让一次 import 就把三档
# 真机矩阵整个跑起来 —— round22 当场踩到：一个本该 0.2 秒的单元测试变成 5 分钟
# 真机跑，还会去抢 SC2 单实例锁，而且 main() 末尾的 sys.exit 会把调用方的后续
# 断言全部吃掉（测试"通过"得毫无声息）。
if __name__ == "__main__":
    main()
