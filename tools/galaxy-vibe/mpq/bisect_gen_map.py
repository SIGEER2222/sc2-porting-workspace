"""gen 图「编译期静默丢弃」二分定位驱动。

背景：closure_doctor 已把孤儿原型 / 重复实现 / 未定义调用 / 未解析 include 全部
清零（对基线图零误报），但 gen 图真机仍 kernel_registered=false —— 说明还存在
closure_doctor 覆盖不到的编译期错误形态（重复全局变量、类型/元数不匹配、
编译器规模上限等）。这类错误 Galaxy 一律静默丢弃整个 MapScript，只能二分。

方法：以「地图自带内核 + 0 shard 纯 harness」为最小增量起点，逐级加变量：
    A  SKIP_KERNEL=1, shard=none      只换 active（harness）+ 注入 Common
    B  SKIP_KERNEL=1, shard=01        + 1 个 adapter shard
    C  SKIP_KERNEL=1, shard=<全部>    + 全部 28 shard
    D  内核注入,      shard=none      只换内核
    E  内核注入,      shard=<全部>    全量（已知 FAIL）
每级：构建 -> p0 探针 -> 记录 kernel_registered。第一个 FAIL 的台阶即真凶所在。

用法:
    python bisect_gen_map.py A B C          # 只跑指定台阶
    python bisect_gen_map.py                # 跑全部
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GV = HERE.parent
REPO = GV.parents[1]
MAP = r"C:/tmp/VibeDeadOfNight-Gen.SC2Map"
PY311 = r"C:/Users/22448/AppData/Local/Programs/Python/Python311/python.exe"
PY = sys.executable

# 台阶名 -> (构建环境变量, 说明)
STEPS: dict[str, tuple[dict[str, str], str]] = {
    "A": ({"VIBE_SKIP_KERNEL": "1", "VIBE_DIAG_SHARD": "none"},
          "地图自带内核 + 0 shard 纯 harness"),
    "B": ({"VIBE_SKIP_KERNEL": "1", "VIBE_DIAG_SHARD": "01"},
          "地图自带内核 + 1 shard"),
    "C": ({"VIBE_SKIP_KERNEL": "1"},
          "地图自带内核 + 全部 shard"),
    "D": ({"VIBE_DIAG_SHARD": "none"},
          "注入工作区内核 + 0 shard"),
    "E": ({},
          "注入工作区内核 + 全部 shard（全量）"),
}


def build(env_extra: dict[str, str]) -> tuple[bool, str]:
    env = dict(os.environ)
    env.update(env_extra)
    p = subprocess.run([PY, str(HERE / "mpq_build_gen_map.py")],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, cwd=str(HERE))
    out = (p.stdout or "") + (p.stderr or "")
    return p.returncode == 0, out


def probe() -> tuple[bool, str]:
    """跑 p0 探针，返回 (kernel_registered, 摘要)。"""
    env = dict(os.environ)
    env["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
    p = subprocess.run(
        [PY311, str(GV / "p0_probe_v3.py"), "--map", MAP,
         "--channels", "bank", "--wait", "70"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, cwd=str(GV))
    out = (p.stdout or "") + (p.stderr or "")
    verdict = REPO / "artifacts" / "galaxy-vibe" / "p0-probe-v3-verdict.json"
    reg = False
    note = ""
    if verdict.is_file():
        try:
            d = json.loads(verdict.read_text(encoding="utf-8"))
            reg = bool(d.get("kernel_registered") or d.get("registered")
                       or (d.get("verdict") or {}).get("kernel_registered"))
            note = json.dumps(d.get("verdict") or d, ensure_ascii=False)[:300]
        except Exception as e:                       # noqa: BLE001
            note = f"verdict 解析失败: {e}"
    if not note:
        note = out[-400:]
    if not reg:
        reg = bool(re.search(r"kernel_initialized|registered\s*[:=]\s*True", out))
    return reg, note


def main() -> int:
    want = [a.upper() for a in sys.argv[1:]] or list(STEPS)
    rows = []
    for name in want:
        if name not in STEPS:
            print(f"[skip] 未知台阶 {name}")
            continue
        env_extra, desc = STEPS[name]
        print(f"\n{'=' * 72}\n[STEP {name}] {desc}  env={env_extra or '{}'}\n{'=' * 72}")
        ok, out = build(env_extra)
        gates = [ln for ln in out.splitlines()
                 if ln.strip().startswith(("[OK]", "[FAIL]", "  [FAIL]"))]
        doctor = next((ln for ln in out.splitlines() if "closure_doctor:" in ln), "")
        print(f"  build: {'DONE' if ok else 'BROKEN'}；{doctor.strip()}")
        for ln in gates:
            if "FAIL" in ln:
                print(f"  {ln.strip()}")
        if not ok:
            rows.append((name, desc, "BUILD-FAIL", ""))
            continue
        reg, note = probe()
        print(f"  probe: kernel_registered={reg}")
        rows.append((name, desc, "REG-OK" if reg else "REG-FAIL", note[:160]))

    print(f"\n{'=' * 72}\n二分结果\n{'=' * 72}")
    for n, d, r, note in rows:
        print(f"  [{r:9s}] {n}  {d}")
        if r == "REG-FAIL" and note:
            print(f"              {note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
