#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stage26 真机编译错误修复（2026-08-09 亡者之夜 ScriptError 11.11.05）。

修复三类「静态 0 error 但真机编译失败 ⇒ 整图静默丢弃」的生成代码缺陷：

A. LibVibeHandles.galaxy —— `libCOTF_gs_HistogramData` 是 struct，被生成器当成
   普通句柄类型，产出了：
     - `int ..._Acquire_...(libCOTF_gs_HistogramData h)`  → 「仅能传递基础类型」
     - `table[i] = h;`                                    → 「不支持大容量复制」
     - `return table[id];`（返回 struct）                 → 「不支持大容量复制」
   Galaxy 只允许 struct 以 `structref<T>` 形参传递，禁止赋值/按值返回。
   降级为「仅登记存活位」的注册表：删掉 struct 数组 + Acquire/Get，
   保留 Has/Drop/Clear 以维持 kernel 的 handle.query/drop/clear 契约。

B. LibVibeInvoke_25.galaxy —— Call9746/Call9747 依赖已删除的 Get_...，
   按 symbol_repair.neutralize_functions 的约定中和为错误返回。

C. LibVibeInvokeCommon.galaxy —— `ResolveFuncref` 静态表里指向 overlay 注入的
   地图专属库（LibA3ADAPTER / LibPortingObserver）的 2 个分支，真机报
   「解析返回时出错，可能在行尾缺失分号」并直接 `脚本读取失败`。
   与 mpq_diag_variant.MISSING_FUNCREF_TARGETS 完全一致。删掉分支后 name 落到
   函数末尾兜底 return（no-op proto），语义安全降级。

用法： python fix_stage26_compile_errors.py [--check]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

WS = Path(__file__).resolve().parents[2]
MAP_NAME = "亡者之夜.SC2Map"
PKG = WS / "src/projects/cmre-porting/packages/Maps" / MAP_NAME / "Base.SC2Data"
GEN = PKG / "generated" / MAP_NAME

# LibVibeHandles.galaxy 的所有磁盘副本（package 是启动源，其余为镜像）
HANDLES_COPIES = [
    PKG / "LibVibeHandles.galaxy",
    WS / "tools/galaxy-vibe/kernel/LibVibeHandles.galaxy",
    WS / "build/GalaxyVibeDebugMod/Base.SC2Data/Trigger/LibVibeHandles.galaxy",
    WS / "tools/galaxy-vibe/galaxy-debug-mod/Base.SC2Data/LibVibeHandles.galaxy",
    WS / ("src/projects/test-arena/packages/Maps/"
          "地图调试和斗蛐蛐工具（完整功能版).SC2Map/Base.SC2Data/LibVibeHandles.galaxy"),
]

MISSING_FUNCREF_TARGETS = (
    "libA3ADAPTER_gf_UnlockAllAbilities",
    "libPortingObserver_gf_PublishPlayerInventory",
)

HISTOGRAM_BLOCK_RE = re.compile(
    r"// ---- libCOTF_gs_HistogramData \(structref\) ----.*?"
    r"void libVibeHandles_gf_Clear_libCOTF_gs_HistogramData\(\) \{.*?\n\}\n",
    re.S)

HISTOGRAM_REPLACEMENT = """// ---- libCOTF_gs_HistogramData (仅存活位注册表) ----
// 【2026-08-09 真机根因，勿退回 struct 表】Galaxy 禁止 struct 作函数形参
// （"仅能传递基础类型"）、禁止 struct 赋值与按值返回（"不支持大容量复制"）。
// Stage26 生成器把 structref 参数类型当普通句柄类型，产出的 Acquire/Get 是
// 编译错误 ⇒ SC2 静默丢弃整个 MapScript。此处降级为只登记存活位的注册表：
// 取消 Acquire/Get，保留 Has/Drop/Clear 维持 handle.query/drop/clear 契约。
bool[513] libVibeHandles_gv_histogram_used;
bool libVibeHandles_gf_Has_libCOTF_gs_HistogramData(int id) {
    if (id < 1 || id > 512) { return false; }
    return libVibeHandles_gv_histogram_used[id];
}
bool libVibeHandles_gf_Drop_libCOTF_gs_HistogramData(int id) {
    if (id < 1 || id > 512 || !libVibeHandles_gv_histogram_used[id]) { return false; }
    libVibeHandles_gv_histogram_used[id] = false;
    return true;
}
void libVibeHandles_gf_Clear_libCOTF_gs_HistogramData() {
    int i;
    for (i = 1; i <= 512; i += 1) { libVibeHandles_gv_histogram_used[i] = false; }
}
"""

CALL_SIG_RE = re.compile(r"^string\s+(libVibeInvoke_gf_Call\d+)\s*\(", re.M)


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8-sig")


def write(p: Path, s: str, newline: str) -> None:
    p.write_text(s, encoding="utf-8", newline=newline)


def detect_newline(raw: bytes) -> str:
    return "\r\n" if b"\r\n" in raw else "\n"


def fix_handles(p: Path) -> str:
    raw = p.read_bytes()
    nl = detect_newline(raw)
    src = raw.decode("utf-8-sig").replace("\r\n", "\n")
    if "libVibeHandles_gf_Acquire_libCOTF_gs_HistogramData" not in src:
        return "skip (already fixed)"
    new, n = HISTOGRAM_BLOCK_RE.subn(HISTOGRAM_REPLACEMENT, src)
    if n != 1:
        return f"FAIL (block matched {n} times)"
    write(p, new, nl)
    return "patched"


def neutralize(p: Path, fnames: list[str]) -> str:
    raw = p.read_bytes()
    nl = detect_newline(raw)
    lines = raw.decode("utf-8-sig").replace("\r\n", "\n").split("\n")
    starts = [(i, m.group(1)) for i, ln in enumerate(lines)
              if (m := CALL_SIG_RE.match(ln))]
    done = []
    for i, fname in reversed(starts):
        if fname not in fnames:
            continue
        j = i + 1
        while j < len(lines) and not lines[j].startswith("}"):
            j += 1
        if j >= len(lines):
            continue
        if "SYMBOL_NOT_IN_MAP" in "\n".join(lines[i:j + 1]):
            continue
        lines[i:j + 1] = [
            f"// [stage26-fix] {fname} 中和：依赖 struct 句柄 "
            f"libCOTF_gs_HistogramData（Galaxy 禁止 struct 传参/赋值/返回）",
            lines[i],
            '    return libVibeInvoke_gf_Error("SYMBOL_NOT_IN_MAP",'
            ' "libCOTF_gs_HistogramData");',
            "}",
        ]
        done.append(fname)
    if not done:
        return "skip (already neutralized)"
    write(p, "\n".join(lines), nl)
    return f"neutralized {sorted(done)}"


def drop_funcref(p: Path, targets: tuple[str, ...]) -> str:
    raw = p.read_bytes()
    nl = detect_newline(raw)
    src = raw.decode("utf-8-sig").replace("\r\n", "\n")
    total = 0
    for t in targets:
        pat = re.compile(
            r'^([ \t]*)if \(name == "([^"]+)"\) \{ return '
            + re.escape(t) + r'; \}[ \t]*$', re.M)
        src, k = pat.subn(
            lambda m: f"{m.group(1)}// [stage26-fix] funcref dropped "
                      f"(overlay-injected map lib): {m.group(2)}", src)
        total += k
    if not total:
        return "skip (already dropped)"
    write(p, src, nl)
    return f"dropped {total} branch(es)"


def main() -> int:
    print(f"workspace = {WS}")
    print("== A. LibVibeHandles: 移除 libCOTF struct 句柄表 ==")
    for p in HANDLES_COPIES:
        if not p.exists():
            print(f"  [miss] {p}")
            continue
        print(f"  [{fix_handles(p)}] {p.relative_to(WS)}")

    print("== B. LibVibeInvoke_25: 中和依赖 struct 句柄的 Call9746/Call9747 ==")
    for p in (GEN / "LibVibeInvoke_25.galaxy",
              WS / "tools/galaxy-vibe/kernel/generated" / MAP_NAME
              / "LibVibeInvoke_25.galaxy"):
        if not p.exists():
            print(f"  [miss] {p}")
            continue
        print(f"  [{neutralize(p, ['libVibeInvoke_gf_Call9746', 'libVibeInvoke_gf_Call9747'])}]"
              f" {p.relative_to(WS)}")

    print("== C. LibVibeInvokeCommon: 删除 overlay 库 funcref 分支 ==")
    for p in (GEN / "LibVibeInvokeCommon.galaxy",
              WS / "tools/galaxy-vibe/kernel/generated" / MAP_NAME
              / "LibVibeInvokeCommon.galaxy"):
        if not p.exists():
            print(f"  [miss] {p}")
            continue
        print(f"  [{drop_funcref(p, MISSING_FUNCREF_TARGETS)}] {p.relative_to(WS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
