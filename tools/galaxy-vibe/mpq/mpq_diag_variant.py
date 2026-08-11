#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""gen.* 真机失败根因二分器 —— 逐层剥离"注入动作"的变量。

背景：把 generated adapter 包接进 VibeDeadOfNight.SC2Map 后，Kernel 完全不注册
（bank 里连 kernel_initialized 都没有）= SC2 静默丢弃了整个 MapScript = 编译失败。
离线校验（符号闭包/孤儿原型/重定义/跨文件重复原型）全绿，说明失败点在离线看不见的地方。

本脚本按"最小变更"顺序生成对照地图，每级只加一个变量：

  noop      : 把原 active 内容**原样**写回（byte-identical），不注入任何文件。
              → 验证 mpq_replace + 重打包机制本身是否破坏地图。这是所有实验的地基。
  addonly   : active 保持原 tier0 stub，但把 Common 注入 MPQ（**不** include）。
              → 验证 SFileAddFileEx 往 MPQ 加文件是否有副作用（不进 include 链应无害）。
  incl      : active = 原 tier0 stub + 顶部 include "LibVibeInvokeCommon"，注入 Common。
              → 单独验证 Common(45KB) 进编译单元是否有毒。stub 的 Dispatch 实现保持不变。
  selfact   : active = 自包含版（include Common + 内联 Dispatch 用 Common 的 Error），注入 Common。
              → 验证"改写 Dispatch 实现"这一步。
  nofuncref : 同 incl，但注入前把 Common 里的 libVibeInvoke_gf_ResolveFuncref
              （406 分支 funcref 静态表，返回无 typedef 的 CMPE_PlayerEventFunc）整体剥离。
              → 若 incl FAIL 而 nofuncref PASS，则 100% 坐实 ResolveFuncref 是编译杀手。

用法：
  python mpq_diag_variant.py <variant> <src.SC2Map> <dst.SC2Map>
"""
from __future__ import annotations

import ctypes
import sys
import shutil
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mpq_patch_kernel import (  # noqa: E402
    CRLF, LF, STREAM_FLAG_READ_ONLY, load_storm, mpq_read, mpq_replace,
)

ACTIVE = "Base.SC2Data\\LibVibeInvokeDispatch_active.galaxy"
COMMON = "Base.SC2Data\\LibVibeInvokeCommon.galaxy"
GEN_SRC = (Path(__file__).resolve().parents[1] / "kernel" / "generated"
           / "亡者之夜.SC2Map")
TMP = Path(r"C:\tmp\vibe-p0")

VARIANTS = ("noop", "addonly", "incl", "selfact", "nofuncref", "dropmissing")

# 经真机+离线分析确认：这 2 个 funcref 目标函数是地图专属 porting 辅助库
# （LibA3ADAPTER / LibPortingObserver），在 standalone VibeDeadOfNight base 中缺失，
# 导致 ResolveFuncref 里 `return <未定义标识符>;` = 编译错误 = 整图静默丢弃。
MISSING_FUNCREF_TARGETS = (
    "libA3ADAPTER_gf_UnlockAllAbilities",
    "libPortingObserver_gf_PublishPlayerInventory",
)


def drop_funcref_branches(src: str, targets) -> tuple[str, int]:
    """删除 ResolveFuncref 里 `if (name == "..") { return <target>; }` 分支。"""
    import re
    n = 0
    for t in targets:
        pat = re.compile(
            r'^[ \t]*if \(name == "[^"]+"\) \{ return '
            + re.escape(t) + r'; \}[ \t]*\r?\n', re.M)
        src, k = pat.subn("", src)
        n += k
    return src, n


def strip_func(src: str, fn: str) -> str:
    """按大括号配平从 src 删掉名为 fn 的完整函数定义（含返回类型任意）。"""
    import re
    m = re.search(rf"^[^\n]*\b{re.escape(fn)}\s*\([^;{{]*\)\s*\{{", src, re.M)
    if not m:
        return src
    i = src.index("{", m.start())
    depth, j = 0, i
    while j < len(src):
        if src[j] == "{":
            depth += 1
        elif src[j] == "}":
            depth -= 1
            if depth == 0:
                j += 1
                break
        j += 1
    return src[:m.start()] + src[j:]


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[1] not in VARIANTS:
        print(__doc__)
        print(f"variants: {', '.join(VARIANTS)}")
        return 2
    variant, src, dst = sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3])
    TMP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"[copy] {src.name} -> {dst.name} ({dst.stat().st_size} B)")

    dll = load_storm()
    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(ctypes.c_wchar_p(str(dst)), 0, 0, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] open {dst}: {ctypes.get_last_error()}")
    injected: list[str] = []
    try:
        stub = mpq_read(dll, h, ACTIVE).decode("utf-8-sig").replace(CRLF, LF)
        print(f"[read] 原 active stub {len(stub)} chars")

        if variant == "noop":
            act = stub
        elif variant == "addonly":
            act = stub
        elif variant in ("incl", "nofuncref", "dropmissing"):
            # 只在 stub 顶部加一条 include，Dispatch 实现完全不动
            act = 'include "LibVibeInvokeCommon"\n' + stub
        else:  # selfact
            act = (
                'include "LibVibeInvokeCommon"\n\n'
                "string libVibeInvoke_gf_Dispatch(int functionId, string argsJson) {\n"
                '    return libVibeInvoke_gf_Error("FUNCTION_NOT_IN_MAP",'
                " IntToString(functionId));\n"
                "}\n"
            )

        ap = TMP / f"active.{variant}.galaxy"
        ap.write_bytes(act.replace(LF, CRLF).encode("utf-8"))
        mpq_replace(dll, h, ACTIVE, ap)
        print(f"[patch] active -> {variant} ({ap.stat().st_size} B, "
              f"{'原样' if act == stub else '已改'})")

        if variant != "noop":
            cf = GEN_SRC / "LibVibeInvokeCommon.galaxy"
            if variant == "nofuncref":
                # 剥离整个巨型 funcref 静态表 ResolveFuncref。
                ctext = cf.read_bytes().decode("utf-8-sig").replace(CRLF, LF)
                stripped = strip_func(ctext, "libVibeInvoke_gf_ResolveFuncref")
                if stripped == ctext:
                    raise RuntimeError("strip_func 未命中 ResolveFuncref！")
                print(f"[strip] ResolveFuncref: Common {len(ctext)}"
                      f" -> {len(stripped)} chars (删 {len(ctext) - len(stripped)})")
                cf = TMP / "LibVibeInvokeCommon.nofuncref.galaxy"
                cf.write_bytes(stripped.replace(LF, CRLF).encode("utf-8"))
            elif variant == "dropmissing":
                # 只删本图缺失的 funcref 目标分支，保留其余 404 个。
                ctext = cf.read_bytes().decode("utf-8-sig").replace(CRLF, LF)
                dropped, n = drop_funcref_branches(ctext, MISSING_FUNCREF_TARGETS)
                if n == 0:
                    raise RuntimeError("drop_funcref_branches 未命中任何分支！")
                print(f"[drop ] {n} 个缺失 funcref 分支: "
                      f"{', '.join(MISSING_FUNCREF_TARGETS)}")
                cf = TMP / "LibVibeInvokeCommon.dropmissing.galaxy"
                cf.write_bytes(dropped.replace(LF, CRLF).encode("utf-8"))
            ok = dll.SFileAddFileEx(h, str(cf), COMMON.encode("utf-8"),
                                    0x00000200 | 0x80000000, 0x02, 0x02)
            if not ok:
                raise RuntimeError(f"add Common failed: {ctypes.get_last_error()}")
            injected.append(COMMON)
            print(f"[add  ] {COMMON} ({cf.stat().st_size} B, src={cf.name})")

        dll.SFileFlushArchive(h)
    finally:
        dll.SFileCloseArchive(h)

    # 回读校验（参数顺序 szMpqName, dwPriority, dwFlags, phMpq —— 只读标志放第 3 位）
    h2 = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(h2)):
        raise SystemExit("[FAIL] 回读打开失败")
    try:
        a2 = mpq_read(dll, h2, ACTIVE).decode("utf-8-sig").replace(CRLF, LF)
        print(f"[read ] active 回读 {len(a2)} chars, 与写入一致={a2 == act}")
        for n in injected:
            print(f"[read ] {n} 回读 {len(mpq_read(dll, h2, n))} B")
        ms = mpq_read(dll, h2, "MapScript.galaxy").decode("utf-8-sig")
        mount = 'include "LibVibeInvokeDispatch_active"' in ms
        print(f"[read ] MapScript {len(ms)} chars, 挂载点={mount}")
    finally:
        dll.SFileCloseArchive(h2)
    print(f"[DONE] {dst} ({dst.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
