#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""形态E 修复（解包目录版）：给 MapScript.galaxy 补 invoke 层所需的前置原型。

== 为什么需要这个文件 ==
`mpq_build_gen_map.prepend_forward_protos()` 已经解决过同一个问题，但它只认
`include "LibVibeInvokeDispatch_active"` 这一个挂载点，即**打包成 MPQ 的 gen 图**。

WebUI / launcher 走的是另一条链路：地图是**解包目录**（`Maps/XXX.SC2Map/` 下平铺
`MapScript.galaxy` + `Base.SC2Data/Lib*.galaxy`），MapScript 头部直接逐个
`include "LibVibeInvokeCommon"` / `include "LibVibeInvoke_01".."_30"`，**没有 active
挂载点**，于是形态E 修复在这条链路上从未执行过 —— 这就是 2026-08-09 真机
`LibVibeInvoke_08.galaxy (14) 参数无效，可能有不正确的变量名` 的根因。

== 问题本身（VIBE_GEN_009，勿删）==
Galaxy 与 C 一样「先声明后使用」，而 include 是纯文本展开：

    MapScript.galaxy
      line   8..51   include 块           <-- invoke 层在这里展开
      line 240..282  地图本体函数原型区    <-- 太晚了
      line 500+      地图本体函数定义

invoke 层（Common 的 funcref 静态表、shard 08~15 的 Call 适配器）会引用地图本体的
`gf_*` / `gt_*_Func` / `auto_gf_*_TriggerFunc`。展开点在原型区**之前**，所以：

  - 取址 `return gf_Foo;`  ⇒ "解析返回时出错，可能在行尾缺失分号：';'"（VIBE_GEN_008）
  - 调用 `gf_Foo(a, b);`   ⇒ "参数无效，可能有不正确的变量名"（VIBE_GEN_009，本文件）

两者都是编译错误 ⇒ SC2 **静默丢弃整个 MapScript**（P0 探针表现为 bank_keys=0）。
注意地图本体自带的原型区**也在展开点之后**，对 invoke 层同样太晚，所以判据必须是
「**挂载点之前**有没有原型」而不是「整个文件里有没有原型」。

== 为什么是「前插原型」而不是「后移 include」==
2026-08-08 真机二分实测 Galaxy include 存在位置硬阈值：
    line 76 PASS / 212 PASS / 2128 PASS / 3089 FAIL / 7802 FAIL
失败形态是 join_game 阶段**直接崩溃**（4/4 复现）。故 include 位置必须保持不动。
重复原型（前插一份 + 本体原型区一份）是合法的，同日 proto_test P0-A/P0-B 双 PASS 取证。

== 插入位置 ==
插在 `include "LibVibeKernel"` 之前 —— 此时 NativeLib/LibertyLib/SwarmLib/LibCOOC/
LibCOMI/LibCOUI 等已展开，原型签名里可能出现的库 typedef 类型都已可见；而 vibe 层
（Kernel/Handles/Common/shard/Dispatch）全部排在其后，覆盖所有引用点。

用法：
    python prepend_map_protos.py "<地图目录>"        # 注入（幂等）
    python prepend_map_protos.py "<地图目录>" --check # 只检查不写
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

LF = "\n"
CRLF = "\r\n"
PROTO_TAG = "VIBE_FORWARD_PROTOS"

# MapScript 顶层（列 0 起）的原型 / 定义。Galaxy 生成的 MapScript 参数恒为单行。
RE_MS_PROTO = re.compile(r"^([A-Za-z_]\w*)[ \t]+(\w+)[ \t]*\(([^;{)]*)\)[ \t]*;", re.M)
RE_MS_DEF = re.compile(r"^([A-Za-z_]\w*)[ \t]+(\w+)[ \t]*\(([^){]*)\)[ \t]*\{", re.M)

# 生命周期入口永不前置声明：SC2 引擎按固定签名回调，重复声明无益且徒增风险。
SKIP = {"InitMap", "InitLibs", "InitGlobals", "InitTriggers"}
# 控制流关键字：RE_MS_DEF 在列 0 也会误吞 `if (...) {`，必须排除。
KEYWORDS = {"if", "while", "for", "switch", "else", "do", "return"}

# 挂载点候选，按优先级。第一个命中的 include 行即插入位置。
MOUNT_CANDIDATES = (
    'include "LibVibeInvokeDispatch_active"',
    'include "LibVibeKernel"',
    'include "LibVibeInvokeCommon"',
)


def find_mount(lines: list[str]) -> tuple[int, str]:
    """返回 (插入行号, 命中的挂载点字面量)。"""
    for cand in MOUNT_CANDIDATES:
        hits = [i for i, ln in enumerate(lines) if ln.strip() == cand]
        if len(hits) == 1:
            return hits[0], cand
        if len(hits) > 1:
            raise SystemExit(f"[FAIL] 挂载点 {cand} 出现 {len(hits)} 次，应恰好 1 次")
    raise SystemExit(f"[FAIL] 找不到任何挂载点，候选: {MOUNT_CANDIDATES}")


def prepend_forward_protos(ms: str) -> tuple[str, int, str]:
    """返回 (新文本, 注入原型数, 挂载点)。已注入过则原样返回、计数 0。"""
    lines = ms.split(LF)
    at, mount = find_mount(lines)

    if f"BEGIN {PROTO_TAG}" in ms:
        return ms, 0, mount

    mount_off = len(LF.join(lines[:at]))
    have = {m.group(2) for m in RE_MS_PROTO.finditer(ms) if m.start() < mount_off}

    gen: list[str] = []
    seen: set[str] = set()
    for m in RE_MS_DEF.finditer(ms):
        typ, name, params = m.group(1), m.group(2), m.group(3).strip()
        if typ in KEYWORDS or name in SKIP or name in have or name in seen:
            continue
        seen.add(name)
        gen.append(f"{typ} {name} ({params});")

    if not gen:
        return ms, 0, mount

    lines[at:at] = (
        [f"// ==== BEGIN {PROTO_TAG} ====",
         "// 形态E / VIBE_GEN_009 修复：invoke 层（Common funcref 表 + shard 适配器）引用",
         "// 地图本体 gf_*/gt_*_Func/auto_*_TriggerFunc，Galaxy 先声明后使用，必须在挂载点",
         "// 之前补齐原型。地图自带原型区排在挂载点之后、对 invoke 层太晚。",
         "// 与后面原型区重复是合法的（2026-08-08 真机 proto_test 取证）。**勿删**。"]
        + gen + [f"// ==== END {PROTO_TAG} ====", ""])
    return LF.join(lines), len(gen), mount


def process(map_dir: Path, check_only: bool = False) -> int:
    ms_path = map_dir / "MapScript.galaxy"
    if not ms_path.is_file():
        print(f"[skip ] {map_dir.name}: 无 MapScript.galaxy")
        return 0
    raw = ms_path.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    had_crlf = CRLF.encode() in raw
    ms = raw.decode("utf-8-sig").replace(CRLF, LF)

    fixed, n, mount = prepend_forward_protos(ms)
    if n == 0:
        state = "已注入(幂等跳过)" if f"BEGIN {PROTO_TAG}" in ms else "无需注入"
        print(f"[ok   ] {map_dir.name}: {state}  挂载点={mount}")
        return 0
    if check_only:
        print(f"[CHECK] {map_dir.name}: 缺 {n} 条前置原型  挂载点={mount}")
        return n

    out = fixed.replace(LF, CRLF) if had_crlf else fixed
    data = out.encode("utf-8")
    if had_bom:
        data = b"\xef\xbb\xbf" + data
    ms_path.write_bytes(data)
    print(f"[patch] {map_dir.name}: 前置原型 x{n}  挂载点={mount}  ({len(data)} B)")
    return n


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if not a.startswith("--")]
    check = "--check" in argv
    if not args:
        print(__doc__)
        return 2
    total = 0
    for a in args:
        p = Path(a)
        targets = [p] if (p / "MapScript.galaxy").is_file() else sorted(
            d for d in p.glob("*.SC2Map") if d.is_dir())
        if not targets:
            print(f"[warn ] {p}: 未找到地图目录")
        for t in targets:
            total += process(t, check)
    if check and total:
        print(f"[FAIL] 共 {total} 条前置原型缺失")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
