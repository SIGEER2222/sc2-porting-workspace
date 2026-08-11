#!/usr/bin/env python3
"""vibe.* 参数契约三方对账（离线，零依赖 SC2）。

背景 / 为什么需要这个脚本
------------------------
`libVibeKernel_gf_HandleFunctionInvoke` 用**精确字符串**匹配派发：

    if (functionId == "vibe.visual.set_opacity" && argNames == "opacity,unit_tag") {...}

argNames 是「实参键名排序后逗号拼接」。少一个键、多一个键、名字写错，
统统落到末尾那个 catch-all，回一个**没有任何 reason 的** `INVALID_ARGS "{}"`。
更坑的是：`FindUnitByTag(tag) == null`（单位已死）也回同一个 `INVALID_ARGS "{}"`。
于是「harness 参数拼错」和「VM 不支持这个函数」在真机日志里长得一模一样。

上一轮真机扫描 6 条 vibe.* 报红，全部是 harness 侧问题（1 条键名写错、
1 条打自己人、4 条复用了被 kill 掉的 tag），VM 本身没毛病。为了以后不再
用「跑一次真机 + 肉眼看红叉」来发现这种事，把契约做成可离线断言的对账：

    harness 实际会发的 argNames  ==  registry 声明  ==  Kernel 闸门字面量

三者任意不等 → 立刻红，不用开游戏。

顺带校验 Kernel 里的数值域守卫（scale 0.01~100 / opacity 0~1 / value>=0 /
color 非空），确保 VIBE_ARG_HINTS 里填的样例值不会被守卫挡掉。

用法:  python vibe_arg_contract_check.py
退出码: 0 全绿 / 1 有不一致
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL = HERE / "kernel" / "LibVibeKernel.galaxy"
REGISTRY = HERE / "kernel" / "function-registry.json"

# Kernel 闸门：functionId == "X" && argNames == "Y"
GATE_RE = re.compile(
    r'functionId\s*==\s*"(vibe\.[\w.]+)"\s*&&\s*argNames\s*==\s*"([^"]*)"')
# 数值域守卫：scale < 0.01 || scale > 100.0 之类
RANGE_RE = re.compile(r'(\w+)\s*<\s*(-?[\d.]+)\s*\|\|\s*\1\s*>\s*([\d.]+)')
LOWER_RE = re.compile(r'(\w+)\s*<\s*(-?[\d.]+)\s*\|\|')
EMPTY_RE = re.compile(r'(\w+)\s*==\s*""')

# Kernel 局部变量名 -> 实参键名（守卫用的是局部变量名，不是 JSON 键名）
VAR2ARG = {"scale": "scale", "opacity": "opacity", "value": "value",
           "colorValue": "color"}
GUARD_FUNCS = {
    "libVibeKernel_gf_FunctionVisualSetScale": "vibe.visual.set_scale",
    "libVibeKernel_gf_FunctionVisualSetTint": "vibe.visual.set_tint",
    "libVibeKernel_gf_FunctionVisualSetOpacity": "vibe.visual.set_opacity",
    "libVibeKernel_gf_FunctionUnitSetVital": "vibe.unit.set_vital",
}


def parse_kernel_gates(src: str) -> dict[str, str]:
    gates = {m.group(1): m.group(2) for m in GATE_RE.finditer(src)}
    # ping 走的是反向判断：if (argNames != "nonce") -> reject
    if re.search(r'functionId\s*==\s*"vibe\.test\.ping"', src) and \
       re.search(r'argNames\s*!=\s*"nonce"', src):
        gates["vibe.test.ping"] = "nonce"
    return gates


def parse_kernel_guards(src: str) -> dict[str, dict]:
    """抽每个 handler 函数体第一段的数值/空串守卫。"""
    out: dict[str, dict] = {}
    for fn, fid in GUARD_FUNCS.items():
        m = re.search(re.escape("string " + fn + "(string argsJson) {"), src)
        if not m:
            continue
        body = src[m.end(): m.end() + 1400]
        head = body.split("return", 1)[0]          # 只看第一个 return 之前的守卫
        g: dict = {}
        for mm in RANGE_RE.finditer(head):
            var, lo, hi = mm.group(1), float(mm.group(2)), float(mm.group(3))
            if var in VAR2ARG:
                g[VAR2ARG[var]] = {"min": lo, "max": hi}
        for mm in LOWER_RE.finditer(head):
            var, lo = mm.group(1), float(mm.group(2))
            if var in VAR2ARG and VAR2ARG[var] not in g:
                g[VAR2ARG[var]] = {"min": lo, "max": None}
        for mm in EMPTY_RE.finditer(head):
            var = mm.group(1)
            if var in VAR2ARG:
                g[VAR2ARG[var]] = {"non_empty": True}
        if g:
            out[fid] = g
    return out


def simulate_harness(fns: dict) -> dict[str, dict]:
    """复刻 real_machine_vm_sweep2.run() 里 Tier-2 的构参逻辑（不发 RPC）。

    真机侧 tag/敌方 tag 是运行时取的，这里用非零占位 —— 契约对账只关心**键名**，
    键值合法性由下面的 guard 检查单独负责。
    """
    sys.path.insert(0, str(HERE))
    from real_machine_vm_sweep import synth_args                    # noqa: E402
    from real_machine_vm_sweep2 import VIBE_ARG_HINTS               # noqa: E402

    FAKE_SELF, FAKE_ENEMY, FAKE_SPARE = 111, 222, 333
    out: dict[str, dict] = {}
    for fid in sorted(f for f in fns if f.startswith("vibe.")):
        spec = fns[fid].get("args") or {}
        need_tag = [k for k in spec if k.endswith("_tag")]
        args = synth_args(fid, fns, tag=FAKE_SELF)
        args.update({k: v for k, v in VIBE_ARG_HINTS.get(fid, {}).items() if k in spec})
        if fid == "vibe.unit.kill":
            args["unit_tag"] = FAKE_SPARE
        elif fid == "vibe.unit.attack":
            args["attacker_tag"] = FAKE_SELF
            args["target_tag"] = FAKE_ENEMY
        else:
            for k in need_tag:
                args[k] = FAKE_SELF
        out[fid] = {k: v for k, v in args.items() if k in spec}
    return out


def check_guards(sent: dict, guards: dict) -> list[str]:
    bad = []
    for fid, g in guards.items():
        args = sent.get(fid)
        if not args:
            continue
        for key, rule in g.items():
            if key not in args:
                continue
            v = args[key]
            if rule.get("non_empty"):
                if not str(v):
                    bad.append(f"{fid}.{key} 为空串，会被 Kernel 守卫拒掉")
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                bad.append(f"{fid}.{key}={v!r} 非数值，但 Kernel 按 fixed 比较")
                continue
            lo, hi = rule.get("min"), rule.get("max")
            if lo is not None and fv < lo:
                bad.append(f"{fid}.{key}={fv} < 下界 {lo}")
            if hi is not None and fv > hi:
                bad.append(f"{fid}.{key}={fv} > 上界 {hi}")
    return bad


def main() -> int:
    src = KERNEL.read_text(encoding="utf-8", errors="replace")
    gates = parse_kernel_gates(src)
    guards = parse_kernel_guards(src)
    reg = json.loads(REGISTRY.read_text(encoding="utf-8"))
    fns = reg.get("functions") or reg
    vibe = sorted(f for f in fns if f.startswith("vibe."))
    sent = simulate_harness(fns)

    print(f"Kernel 闸门 {len(gates)} 条 / registry vibe.* {len(vibe)} 条 / "
          f"守卫 {len(guards)} 组\n")
    print(f"  {'function_id':28s} {'harness 实发':34s} {'kernel 闸门':34s} 判定")
    print("  " + "-" * 108)

    rows, bad = [], []
    for fid in vibe:
        declared = ",".join(sorted((fns[fid].get("args") or {})))
        actual = ",".join(sorted(sent.get(fid, {})))
        gate = gates.get(fid)
        if gate is None:
            verdict, ok = "NO_GATE", False
        elif actual == declared == gate:
            verdict, ok = "OK", True
        elif actual != declared:
            verdict, ok = "HARNESS_DRIFT", False
        else:
            verdict, ok = "KERNEL_MISMATCH", False
        if not ok:
            bad.append(f"{fid}: harness={actual!r} registry={declared!r} kernel={gate!r}")
        rows.append({"function_id": fid, "harness": actual, "registry": declared,
                     "kernel": gate, "verdict": verdict})
        print(f"  {'OK' if ok else 'X '} {fid:26s} {actual:34s} {str(gate):34s} {verdict}")

    # Kernel 闸门里有、registry 里没有的（反向漏网）
    orphan = sorted(set(gates) - set(vibe))
    guard_bad = check_guards(sent, guards)

    print("\n--- 数值域守卫 ---")
    for fid, g in sorted(guards.items()):
        print(f"  {fid:26s} {g}")
    for b in guard_bad:
        print(f"  X  {b}")
    if not guard_bad:
        print("  OK  VIBE_ARG_HINTS 样例值全部落在 Kernel 守卫允许区间内")

    ok = not bad and not orphan and not guard_bad
    print("\n=== 判定 ===")
    print(f"  argNames 三方一致 : {'PASS' if not bad else 'FAIL'} "
          f"({len(vibe) - len(bad)}/{len(vibe)})")
    print(f"  无孤儿闸门        : {'PASS' if not orphan else 'FAIL ' + str(orphan)}")
    print(f"  数值域合规        : {'PASS' if not guard_bad else 'FAIL'}")
    print(f"  总判定            : {'PASS' if ok else 'FAIL'}")
    for b in bad:
        print("   - " + b)

    out = HERE.parent.parent / "artifacts" / "galaxy-vibe" / "vibe-arg-contract.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"rows": rows, "gates": gates, "guards": guards,
         "orphan_gates": orphan, "guard_violations": guard_bad,
         "pass": ok}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n证据: {out}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
