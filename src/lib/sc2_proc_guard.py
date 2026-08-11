# -*- coding: utf-8 -*-
"""SC2 进程守卫：区分「API 探针实例」和「真人对局」，绝不误杀后者。

背景（2026-08-09 差点踩到）：
    真机矩阵每档开跑前都要清场，原实现是
        Get-Process -Name SC2_x64,SC2Switcher_x64 | Stop-Process -Force
    这会把用户正在玩的那一局一起干掉。自动化任务在后台按小时跑，
    撞上真人对局只是时间问题。

判定依据：
    API 实例一定是 `SC2Switcher_x64.exe -listen 127.0.0.1 -port <n> -debug`
    拉起来的，其 SC2_x64.exe 子进程命令行里同样带 `-listen`。
    真人对局的命令行只有可执行路径（可能跟一个地图路径），没有 `-listen`。

用法：
    from sc2_proc_guard import human_games, kill_api_instances, assert_no_human_game
"""
import re
import subprocess

_PS = ("powershell", "-NoProfile", "-NonInteractive", "-Command")

# 用 `|` 拼字段，避免命令行里出现空格/中文地图名时被切碎
_LIST = (
    "Get-CimInstance Win32_Process "
    "-Filter \"Name='SC2_x64.exe' or Name='SC2Switcher_x64.exe'\" "
    "| ForEach-Object { \"$($_.ProcessId)|$($_.Name)|$($_.CommandLine)\" }"
)

_KILL_API = (
    "Get-CimInstance Win32_Process "
    "-Filter \"Name='SC2_x64.exe' or Name='SC2Switcher_x64.exe'\" "
    "| Where-Object { $_.CommandLine -match '-listen' } "
    "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force "
    "-ErrorAction SilentlyContinue }"
)


def _ps(cmd, timeout=60):
    try:
        return subprocess.run(_PS + (cmd,), capture_output=True, text=True,
                              errors="replace", timeout=timeout).stdout or ""
    except Exception:
        return ""


def list_sc2():
    """返回 [(pid, name, cmdline, is_api), ...]。"""
    rows = []
    for line in _ps(_LIST).splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        parts = line.split("|", 2)
        if len(parts) < 3:
            continue
        pid, name, cmd = parts[0].strip(), parts[1].strip(), parts[2]
        if not pid.isdigit():
            continue
        rows.append((int(pid), name, cmd, "-listen" in cmd))
    return rows


def human_games():
    """只返回**不带 -listen** 的 SC2_x64 进程，即真人对局。"""
    return [r for r in list_sc2() if r[1].lower() == "sc2_x64.exe" and not r[3]]


def api_instances():
    return [r for r in list_sc2() if r[3]]


def assert_no_human_game(action="清场"):
    """有真人对局就抛错，把「误杀」变成一次显式失败。"""
    hg = human_games()
    if hg:
        detail = "; ".join("pid=%d %s" % (p, re.sub(r"\s+", " ", c))[:160]
                           for p, _n, c, _a in hg)
        raise RuntimeError(
            "检测到 %d 个真人 SC2 对局，拒绝%s（铁律：绝不误杀真人局）：%s"
            % (len(hg), action, detail))


def kill_api_instances(guard=True):
    """只杀 API 探针实例。guard=True 时先确认没有真人对局。

    返回被清掉的进程数（调用前的计数）。
    """
    if guard:
        assert_no_human_game()
    n = len(api_instances())
    if n:
        _ps(_KILL_API)
    return n


if __name__ == "__main__":
    for pid, name, cmd, is_api in list_sc2():
        print("%-6d %-20s %-5s %s" % (pid, name, "API" if is_api else "HUMAN",
                                      re.sub(r"\s+", " ", cmd)[:120]))
    hg = human_games()
    print("---")
    print("真人对局 = %d，API 实例 = %d" % (len(hg), len(api_instances())))
