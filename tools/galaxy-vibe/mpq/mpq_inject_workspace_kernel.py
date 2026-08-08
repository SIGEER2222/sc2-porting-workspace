"""把工作区合并后的内核整体注入地图 MPQ，生成 VibeT5。

为什么不是逐处 patch：工作区源与 T4 是双向分叉的，逐处 patch 只能补 T4 缺的，
补不回工作区独有的 tagCache / KERNEL001 悲观响应。这里直接整体换 body。

为什么不换 header：地图内 LibVibeKernel_h.galaxy 比工作区 header 多出
libVibeHandles_* 与 HandleHandle* 原型（STAGE26 HANDLE_OPS 走的是地图侧闭包）。
整体替换 header 会把这些原型删掉，body 里的 HANDLE_OPS 立刻失去声明。
→ 只往 header 追加 body 新引用而 header 尚缺的全局变量声明。

铁律背景：Galaxy 编译失败时 SC2 静默丢弃整个 MapScript，不报错、不写日志，
静态 lint 也照样 0 错误。所以注入后必须做符号闭包检查 + 重定义检查，
再用真机 P0/P1 取证。
"""
from __future__ import annotations

import ctypes
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mpq_patch_kernel import (  # noqa: E402
    CRLF, LF, STREAM_FLAG_READ_ONLY, load_storm, mpq_read, mpq_replace,
)

WS = Path(r"E:/Code/MyMod/SC2VibeTools/sc2-porting-workspace")
WS_KERNEL = WS / "tools/galaxy-vibe/kernel/LibVibeKernel.galaxy"
WORK = Path(r"C:\tmp\vibe-p0")

KERNEL = "Base.SC2Data\\LibVibeKernel.galaxy"
HEADER = "Base.SC2Data\\LibVibeKernel_h.galaxy"

# body 新引用、header 可能尚缺的全局变量（来自工作区 header 的 tagCache 段）
TAGCACHE_DECLS = """
// ---- unit tag 查找缓存（随 VIBE_KERNEL 合并版一并注入）----
// FindUnitByTag 原本 O(15 玩家 x 全图单位) 全扫描，夜间单位量暴涨时会把触发线程
// 顶到 Galaxy 操作上限而被静默 halt，表现为 Host 侧间歇性 TIMEOUT。
int    libVibeKernel_gv_tagCacheTag = 0;
unit   libVibeKernel_gv_tagCacheUnit = null;
bool   libVibeKernel_gv_tagCacheMiss = false;
int    libVibeKernel_gv_tagCacheVersion = -1;
"""

DECL_NAMES = [
    "libVibeKernel_gv_tagCacheTag",
    "libVibeKernel_gv_tagCacheUnit",
    "libVibeKernel_gv_tagCacheMiss",
    "libVibeKernel_gv_tagCacheVersion",
]

GALAXY_IN_MPQ = [
    "Base.SC2Data\\LibVibeKernel.galaxy",
    "Base.SC2Data\\LibVibeKernel_h.galaxy",
    "Base.SC2Data\\LibVibeHandles.galaxy",
    "Base.SC2Data\\LibMapModBridge.galaxy",
    "MapScript.galaxy",
]


def defined_symbols(text: str) -> set[str]:
    """函数定义 + 函数原型 + 全局变量声明。"""
    out: set[str] = set()
    out |= set(re.findall(
        r"^\s*(?:void|bool|int|string|fixed|unit|point|text|trigger|unitgroup|playergroup|"
        r"bank|order|region|timer|actor|wave|revealer|abilcmd|marker|doodad|aifilter|"
        r"unitfilter|waveinfo|wavetarget)\s+(\w+)\s*\(", text, re.M))
    out |= set(re.findall(
        r"^\s*(?:const\s+)?(?:void|bool|int|string|fixed|unit|point|text|trigger|unitgroup|"
        r"playergroup|bank|order|region|timer|actor|wave|revealer|abilcmd|marker|doodad|"
        r"aifilter|unitfilter|waveinfo|wavetarget)\s+(\w+)\s*(?:=|;|\[)", text, re.M))
    out |= set(re.findall(r"^\s*struct\s+(\w+)", text, re.M))
    return out


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\tmp\VibeT4.sc2map")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else r"C:\tmp\VibeT5.sc2map")
    if not src.exists():
        raise SystemExit(f"[FAIL] 基线不存在: {src}")
    if not WS_KERNEL.exists():
        raise SystemExit(f"[FAIL] 工作区内核不存在: {WS_KERNEL}")

    WORK.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)
    print(f"[copy] {src.name} -> {dst.name} ({dst.stat().st_size} B)")

    body = WS_KERNEL.read_bytes().decode("utf-8-sig").replace(CRLF, LF)
    print(f"[read] 工作区内核 {len(body)} chars")

    dll = load_storm()
    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, 0, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] open {dst}: {ctypes.get_last_error()}")
    try:
        header = mpq_read(dll, h, HEADER).decode("utf-8-sig").replace(CRLF, LF)
        missing = [n for n in DECL_NAMES if not re.search(rf"^\s*\w+\s+{n}\s*=", header, re.M)]
        if missing:
            anchor = "// ---- 看门狗"
            if anchor in header:
                header = header.replace(anchor, TAGCACHE_DECLS.strip() + "\n\n" + anchor, 1)
            else:
                header = header.rstrip() + "\n" + TAGCACHE_DECLS
            hp = WORK / "LibVibeKernel_h.t5.galaxy"
            hp.write_bytes(header.replace(LF, CRLF).encode("utf-8"))
            mpq_replace(dll, h, HEADER, hp)
            print(f"[patch] header 追加 {len(missing)} 个 tagCache 声明: {missing}")
        else:
            print("[skip ] header 已含 tagCache 声明")

        bp = WORK / "LibVibeKernel.t5.galaxy"
        bp.write_bytes(body.replace(LF, CRLF).encode("utf-8"))
        mpq_replace(dll, h, KERNEL, bp)
        dll.SFileFlushArchive(h)
        print(f"[patch] body 已整体写回 MPQ（{bp.stat().st_size} B）")
    finally:
        dll.SFileCloseArchive(h)

    # ---- 回读校验 ----
    h2 = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(h2)):
        raise SystemExit("[FAIL] 回读打开失败")
    texts: dict[str, str] = {}
    try:
        for name in GALAXY_IN_MPQ:
            try:
                texts[name] = mpq_read(dll, h2, name).decode("utf-8-sig").replace(CRLF, LF)
            except Exception:
                pass
    finally:
        dll.SFileCloseArchive(h2)
    print(f"[read ] 回读 {len(texts)} 个 galaxy 文件: {[Path(k).name for k in texts]}")

    b = texts[KERNEL]
    hdr = texts[HEADER]

    # 符号闭包：body 引用的 libVibe* 符号必须在某处有定义/原型
    defined: set[str] = set()
    for t in texts.values():
        defined |= defined_symbols(t)
    referenced = set(re.findall(r"\b(libVibe\w+)\b", b))
    unresolved = sorted(s for s in referenced - defined if not s.endswith("_Func"))
    # _Func 是 TriggerCreate 的字符串名，单独核对
    trig_funcs = set(re.findall(r'TriggerCreate\("(\w+)"\)', b))
    trig_missing = sorted(f for f in trig_funcs if f not in defined)

    # 函数重定义（整个 MPQ 范围）—— 触发 SC2 静默丢弃 MapScript 的头号元凶
    all_defs: list[str] = []
    for t in texts.values():
        all_defs += re.findall(
            r"^(?:void|bool|int|string|fixed|unit|point|text)\s+(\w+)\s*\([^;]*\)\s*\{", t, re.M)
    dups = sorted({n for n in all_defs if all_defs.count(n) > 1})

    checks = {
        "Fix B 标记 NO_HANDLE_CACHE": "VIBE_KERNEL_003_NO_HANDLE_CACHE" in b,
        "Fix A 标记 POLL_ORDER HEAD": "VIBE_KERNEL_002_POLL_ORDER HEAD" in b,
        "Fix A 标记 POLL_ORDER TAIL": "VIBE_KERNEL_002_POLL_ORDER TAIL" in b,
        "Watchdog 注册为异步": "TriggerExecute(libVibeKernel_gt_Watchdog, false, false)" in b,
        "Watchdog 重启 PollLoop 异步": "TriggerExecute(libVibeKernel_gt_PollLoop, false, true)" not in b,
        "工作区独有 tagCache 已带入": "libVibeKernel_gv_tagCacheVersion" in b,
        "工作区独有 悲观响应": "HANDLER_ABORTED" in b,
        "consume-before-dispatch 保留":
            b.index("libVibeKernel_gv_lastPolledRequestId = pendingId;")
            < b.index("response = libVibeKernel_gf_Dispatch(requestJson);"),
        "构建指纹 merged_fix=5": '"merged_fix", 5' in b,
        "tagCache 声明在 header": all(n in hdr for n in DECL_NAMES),
        "全文件只剩 2 处 BankLoad": b.count("BankLoad(") == 2,
        "无未解析 libVibe 符号": not unresolved,
        "TriggerCreate 目标函数均存在": not trig_missing,
        "无函数重定义": not dups,
        "未混入反向对照": "NEG_CTL_" not in b,
        "括号平衡": b.count("{") == b.count("}"),
    }
    ok = True
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'FAIL'}] {k}")
        ok = ok and bool(v)
    if unresolved:
        print(f"    unresolved: {unresolved[:12]}")
    if trig_missing:
        print(f"    trigger fn missing: {trig_missing}")
    if dups:
        print(f"    dup defs: {dups[:12]}")
    print(f"[{'DONE' if ok else 'BROKEN'}] {dst} ({dst.stat().st_size} B)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
