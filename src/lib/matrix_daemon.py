"""真机三档矩阵守候进程（round17 新增）。

背景：本项目的自动化按小时跑，而开发机上真人对局随时可能占着 SC2。
矩阵驱动器 `run_matrix_round10.py --wait N` 已经会排队等待，但它跑在
会话的后台任务里 —— 会话一结束就被回收，等于白等。

这个脚本把矩阵**脱离会话**跑（DETACHED_PROCESS），并保证幂等：
已经有一个矩阵在跑/在等，就不再起第二个（两个矩阵同时抢 SC2 必然互相踩）。

用法：
    python matrix_daemon.py            # 起守候（默认等最多 600 分钟）
    python matrix_daemon.py --status   # 只看当前状态
    python matrix_daemon.py --stop     # 停掉守候（只停矩阵进程，不碰真人局）
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# 控制台编码自卫（round24）：本文件会打印 '⏳''✅'，GBK 编不出来 ->
# UnicodeEncodeError -> 守护进程直接死掉，而且是死在「打印进度」这种
# 与任务本身无关的地方，日志上看像是矩阵跑挂了。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from sc2_proc_guard import human_games  # noqa: E402

MARKER = "run_matrix_round10.py"
# 日志名以前写死成 matrix_round17.log —— 下一轮再挂守候会把上一轮的证据覆盖掉，
# 而且 `--status` 读到的"最新三行"其实是别人轮次的，误导性极强。
# 改成 --log 可指定，默认落到不带轮次号的 matrix_daemon_last.log。
LOG = HERE / "matrix_daemon_last.log"

DETACHED_PROCESS = 0x00000008
CREATE_NEW_PROCESS_GROUP = 0x00000200
CREATE_NO_WINDOW = 0x08000000


def _ps(cmd: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", cmd],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return (r.stdout or "").strip()


def running() -> list[tuple[int, str]]:
    """返回正在跑的矩阵进程 [(pid, cmdline)]。"""
    out = _ps(
        "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
        "Select-Object ProcessId,CommandLine | ForEach-Object "
        "{ \"$($_.ProcessId)`t$($_.CommandLine)\" }")
    hits = []
    for line in out.splitlines():
        if MARKER in line and "\t" in line:
            pid, cmd = line.split("\t", 1)
            try:
                hits.append((int(pid.strip()), cmd.strip()))
            except ValueError:
                pass
    return hits


def stop() -> int:
    hits = running()
    for pid, _ in hits:
        _ps(f"Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue")
    print(f"[daemon] 已停止 {len(hits)} 个矩阵进程"
          f"（真人对局未受影响：{len(human_games())} 局在跑）")
    return 0


def status() -> int:
    hits = running()
    hg = human_games()
    print(f"[daemon] 矩阵进程 {len(hits)} 个"
          + (f" -> PID {[p for p, _ in hits]}" if hits else " (无)"))
    print(f"[daemon] 真人对局 {len(hg)} 局"
          + (f" -> PID {[p[0] for p in hg]}" if hg else " (无)"))
    if LOG.exists():
        tail = LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-3:]
        print("[daemon] 日志尾部：")
        for t in tail:
            print("   ", t)
    return 0


def _chain_code(wait_min: int, then: list[str]) -> str:
    """矩阵跑完后串跑后续脚本的 driver 代码。

    为什么要串而不是各挂各的：两个真机任务同时开跑必然抢 SC2 的单实例锁，
    表现为其中一个连不上 API 然后被误判成 FAIL。串行是唯一安全的排法。

    注意这段代码里必须出现 run_matrix_round10.py 字面量 —— running() 的幂等
    保护就是靠在 cmdline 里找这个 MARKER，否则 daemon 会重复起第二份。

    两个坑（round22 第一次挂链式当场踩到，矩阵输出全被吞、只剩 chain 的 3 行）：

    1. **编码**：子进程 stdout 被重定向到文件后不是 tty，CPython 会退回 locale
       编码（本机 cp936）。矩阵输出里有 `✅ ⏳ ——` 这类字符，cp936 编不出来 →
       `UnicodeEncodeError` → 进程直接死，rc=1 而且**一行日志都留不下**，
       看起来就像"矩阵神秘失败"。必须显式 `PYTHONIOENCODING=utf-8`。
    2. **缓冲**：父子写同一个文件句柄，块缓冲会让两边的输出互相覆盖。
       父子都加 `-u` / `flush=True`，让写入即时且有序。
    """
    matrix = str(HERE / "run_matrix_round10.py")
    return (
        "import os,subprocess,sys\n"
        "env = dict(os.environ, PYTHONIOENCODING='utf-8')\n"
        f"rc = subprocess.run([sys.executable, '-u', r'{matrix}', '--wait', '{wait_min}'],"
        " env=env).returncode\n"
        "print('[chain] matrix rc=%d' % rc, flush=True)\n"
        f"for s in {then!r}:\n"
        "    print('[chain] ---- 接力: %s ----' % s, flush=True)\n"
        f"    rc2 = subprocess.run([sys.executable, '-u', r'{HERE}\\\\' + s,"
        " '--wait', '%d' % " f"{wait_min}], env=env).returncode\n"
        "    print('[chain] %s rc=%d' % (s, rc2), flush=True)\n"
    )


def start(wait_min: int, then: list[str] | None = None) -> int:
    hits = running()
    if hits:
        print(f"[daemon] 已有矩阵在跑/在等（PID {[p for p, _ in hits]}），跳过重复启动")
        return 0
    log = LOG.open("w", encoding="utf-8")
    if then:
        cmd = [sys.executable, "-c", _chain_code(wait_min, then)]
    else:
        # round25 修：这里以前少了 `-u`。stdout 重定向到文件后不是 tty，CPython
        # 走块缓冲，9 分钟的矩阵日志会一直卡在 0~几十字节，外面看像"守候起了但
        # 什么都没跑"。链式分支（_chain_code）当初已经加了 -u，非链式分支漏了 ——
        # 同一个坑修了一半，是最容易复发的形态。
        # 编码同理：非 tty 时退回 cp936，矩阵输出里的 ✅⏳—— 会 UnicodeEncodeError
        # 把进程打死且一行日志不留（_chain_code 的 docstring 记过这个坑）。
        cmd = [sys.executable, "-u", str(HERE / "run_matrix_round10.py"),
               "--wait", str(wait_min)]
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen(
        cmd, env=env,
        cwd=str(HERE), stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
        creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW)
    hg = human_games()
    print(f"[daemon] 已脱离会话启动矩阵 PID {p.pid}，最多排队 {wait_min} 分钟")
    if then:
        print(f"[daemon] 矩阵结束后依次接力：{then}")
    print(f"[daemon] 当前真人对局 {len(hg)} 局"
          + ("（矩阵会安静等它结束）" if hg else "（应立刻开跑）"))
    print(f"[daemon] 日志：{LOG}")
    return 0


def main() -> int:
    global LOG
    ap = argparse.ArgumentParser()
    ap.add_argument("--wait", type=int, default=600, help="最多排队分钟数")
    ap.add_argument("--log", default=None,
                    help="日志文件名（默认 matrix_daemon_last.log）。"
                         "按轮次归档请显式给 matrix_roundNN.log")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--stop", action="store_true")
    ap.add_argument("--then", action="append", default=None,
                    help="矩阵跑完后接力执行的脚本名（同目录，会带 --wait）。"
                         "可重复给多个，按给定顺序串行。")
    a = ap.parse_args()
    if a.log:
        LOG = HERE / a.log
    if a.status:
        return status()
    if a.stop:
        return stop()
    return start(a.wait, a.then)


if __name__ == "__main__":
    raise SystemExit(main())
