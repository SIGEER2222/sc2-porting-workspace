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

// ---- VIBE_GEN_007 模型库分库（随 VIBE_KERNEL 合并版一并注入）----
// RPC 通道(GalaxyVibe) 与模型快照库(GalaxyVibeModel) 拆开，模型写入不再挤占 RPC 库，
// 这是 VIBE_GEN_007「Bank RPC 有损通道」的治本项。body 引用这两个全局，2026-08-09 之前
// 打包的老地图 header 里没有；不补就是「未解析符号」→ SC2 静默丢整个 MapScript。
const string libVibeKernel_gv_ModelBankName = "GalaxyVibeModel";
bank   libVibeKernel_gv_modelBankHandle = null;

// ---- VIBE_KERNEL watchdog / 首帧 flush 状态（随 VIBE_KERNEL 合并版一并注入）----
// 当前内核 body 引用这 4 个全局；Jul31/Aug8 老地图 header 里没有，不补就是
// 「未解析符号」→ SC2 静默丢整个 MapScript。2026-08-09 复盘补进声明表。
trigger libVibeKernel_gt_Watchdog = null;
int     libVibeKernel_gv_watchdogLastSeen = 0;
int     libVibeKernel_gv_watchdogRestarts = 0;
bool    libVibeKernel_gv_pollLoopFirstFlushed = false;
"""

DECL_NAMES = [
    "libVibeKernel_gv_tagCacheTag",
    "libVibeKernel_gv_tagCacheUnit",
    "libVibeKernel_gv_tagCacheMiss",
    "libVibeKernel_gv_tagCacheVersion",
    "libVibeKernel_gv_ModelBankName",
    "libVibeKernel_gv_modelBankHandle",
    "libVibeKernel_gt_Watchdog",
    "libVibeKernel_gv_watchdogLastSeen",
    "libVibeKernel_gv_watchdogRestarts",
    "libVibeKernel_gv_pollLoopFirstFlushed",
]

GALAXY_IN_MPQ = [
    "Base.SC2Data\\LibVibeKernel.galaxy",
    "Base.SC2Data\\LibVibeKernel_h.galaxy",
    "Base.SC2Data\\LibVibeHandles.galaxy",
    "Base.SC2Data\\LibMapModBridge.galaxy",
    "MapScript.galaxy",
]

# ---- 基底血统判据（2026-08-10 事故治本）----
# gen 血统 MapScript 是 VibeT4 血统的**严格超集**：多出的 267 行就是 VIBE_FORWARD_PROTOS。
# 两者 include 集合完全相同 —— 即 VibeT4 也挂了 invoke 派发层却没有前向原型，
# 这正是"能通过所有内核自检、却在真机静默丢图"的那类基底。
INVOKE_INCLUDE_RE = re.compile(r'^\s*include\s+"LibVibeInvokeDispatch', re.M)
FWD_BEGIN = "// ==== BEGIN VIBE_FORWARD_PROTOS ===="
FWD_END = "// ==== END VIBE_FORWARD_PROTOS ===="


def _count_code(text: str, token: str) -> int:
    """统计 token 在**非注释**代码中的出现次数。

    Galaxy 只有 `//` 行注释。这里按行剥掉 `//` 之后的部分再计数，避免文档/示例
    注释污染门禁断言（曾把 `// gv_bankHandle = BankLoad(...)` 数进 BankLoad 处数）。
    """
    total = 0
    for line in text.split("\n"):
        code = line.split("//", 1)[0]
        total += code.count(token)
    return total


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


USAGE = """用法: python mpq_inject_workspace_kernel.py <基底图> <产出图> [--allow-lineage-mismatch]

  基底**必须显式给**，不再有默认值。两种合法用途：
    - gen 图重建 : 基底须为 gen 血统（如 C:/tmp/VibeDeadOfNight-Gen-k004.SC2Map，5.4MB+）
    - 纯内核测试 : C:/tmp/VibeT4.sc2map -> C:/tmp/VibeT5.sc2map

  2026-08-10 事故：本脚本旧版默认基底写死 C:\\tmp\\VibeT4.sc2map（"生成 VibeT5"的原始用途），
  被当成"重建 gen 图"用时静默产出 VibeT4 血统的图（4.65MB，gen 血统是 5.50MB），
  16 项自检全绿、真机 kernel_registered=false 且 0 ScriptError，被误诊成 Bank 逻辑回归。
  默认值在此类"一脚本两用途"场景里就是陷阱本身，故改为 fail closed。"""


def check_map_lineage(mapscript: str) -> tuple[bool, str]:
    """判定基底图是否具备**可编译的 invoke 挂载**结构。

    2026-08-10 事故根因：VibeT4 血统的 MapScript 同样 `include "LibVibeInvokeDispatch_active"`，
    却缺 `VIBE_FORWARD_PROTOS` 前向原型区 —— invoke 层引用的 MapScript 本体函数
    （gf_* / auto_gf_*_TriggerFunc / gt_*_Func）全部无声明 → Galaxy 编译失败 →
    **SC2 静默丢弃整个 MapScript**（不报错、不写日志、静态 lint 照样 0 错误）。
    真机表现为 kernel_registered=false + 0 ScriptError，极易被误诊成 Bank / 内核逻辑回归。

    判据必须覆盖"我要下的结论"（这张图能跑 tier100），而不是只覆盖"内核注入对不对"：
    原 16 项自检全是内核**内部**性质，对基底血统完全无感——恰恰漏掉唯一致命的那项。

    反向对照：`C:/tmp/VibeT4.sc2map` 必须**精确失败在本判据上**（而非崩溃/超时）。
    """
    m = INVOKE_INCLUDE_RE.search(mapscript)
    if not m:
        return True, "未挂载 invoke 派发层 → 血统判据不适用（纯内核图）"
    if FWD_BEGIN not in mapscript or FWD_END not in mapscript:
        return False, ("挂载了 LibVibeInvokeDispatch 却缺 VIBE_FORWARD_PROTOS 前向原型区 → "
                       "invoke 层引用 MapScript 本体函数无声明 → 编译失败 → SC2 静默丢整个 MapScript")
    if mapscript.index(FWD_END) > m.start():
        return False, "VIBE_FORWARD_PROTOS 落在 invoke include 之后 → 声明太晚，等同于没有"
    return True, "gen 血统（invoke 挂载 + 前向原型区位于挂载点之前）"


def read_mapscript(dll, path: Path) -> str:
    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(path), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] 打开归档失败: {path}")
    try:
        return mpq_read(dll, h, "MapScript.galaxy").decode("utf-8-sig").replace(CRLF, LF)
    finally:
        dll.SFileCloseArchive(h)


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    allow_mismatch = "--allow-lineage-mismatch" in flags
    if len(args) < 2:
        raise SystemExit(USAGE)
    src = Path(args[0])
    dst = Path(args[1])
    if not src.exists():
        raise SystemExit(f"[FAIL] 基线不存在: {src}")
    if not WS_KERNEL.exists():
        raise SystemExit(f"[FAIL] 工作区内核不存在: {WS_KERNEL}")

    dll = load_storm()

    # ---- 前置血统门禁：不产出坏图，fail fast ----
    src_ms = read_mapscript(dll, src)
    lineage_ok, lineage_why = check_map_lineage(src_ms)
    print(f"[lineage] 基底 {src.name} ({src.stat().st_size} B): "
          f"{'OK' if lineage_ok else 'FAIL'} — {lineage_why}")
    if not lineage_ok and not allow_mismatch:
        raise SystemExit(
            f"[FAIL] 基底血统门禁未过：{lineage_why}\n"
            f"       用这张基底产出的图，SC2 会**静默丢弃整个 MapScript**，真机表现为\n"
            f"       kernel_registered=false 且 0 ScriptError，看起来像内核 bug，其实是基底错。\n"
            f"       如确知在做纯内核实验，显式加 --allow-lineage-mismatch。\n\n{USAGE}")
    if not lineage_ok:
        print("[warn] --allow-lineage-mismatch 已显式放行：产出图预期无法在真机跑通 invoke 层")

    WORK.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)
    print(f"[copy] {src.name} -> {dst.name} ({dst.stat().st_size} B)")

    body = WS_KERNEL.read_bytes().decode("utf-8-sig").replace(CRLF, LF)
    print(f"[read] 工作区内核 {len(body)} chars")

    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, 0, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] open {dst}: {ctypes.get_last_error()}")
    try:
        header = mpq_read(dll, h, HEADER).decode("utf-8-sig").replace(CRLF, LF)
        # 【勿去掉 (?:const\s+)?】ModelBankName 是 `const string X = ...`，两个类型词。
        # 老正则只吃一个词，会把已存在的声明误判成 missing，反复重复追加。
        missing = [
            n for n in DECL_NAMES
            if not re.search(rf"^\s*(?:const\s+)?\w+\s+{n}\s*=", header, re.M)
        ]
        if missing:
            anchor = "// ---- 看门狗"
            if anchor in header:
                header = header.replace(anchor, TAGCACHE_DECLS.strip() + "\n\n" + anchor, 1)
            else:
                header = header.rstrip() + "\n" + TAGCACHE_DECLS
            hp = WORK / "LibVibeKernel_h.t5.galaxy"
            hp.write_bytes(header.replace(LF, CRLF).encode("utf-8"))
            mpq_replace(dll, h, HEADER, hp)
            print(f"[patch] header 追加 {len(missing)} 个缺失全局声明: {missing}")
        else:
            print("[skip ] header 已含全部所需全局声明")

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
        "所需全局声明在 header": all(n in hdr for n in DECL_NAMES),
        # VIBE_KERNEL_003：RPC 库 handle 绝不跨帧缓存，每次无条件 BankLoad（2 处）。
        # VIBE_GEN_007 分库后模型库自带 1 处 BankLoad（内核私有、单向写，不走 RPC 语义），
        # 故合并版是 3 处。老断言硬写 ==2，分库后必然误报。
        # 【必须剥注释再数】内核里有一行 `// gv_bankHandle = BankLoad(name, player);`
        # 讲解用示例，直接 count 会数成 4。凡是对源码做计数的断言都要先去掉注释，
        # 否则以后任何人加一句带该 token 的注释都会把门禁弄红，然后被随手改阈值糊弄过去。
        "BankLoad 代码处数=3（RPC 2 + 模型库 1）": _count_code(b, "BankLoad(") == 3,
        "无未解析 libVibe 符号": not unresolved,
        "TriggerCreate 目标函数均存在": not trig_missing,
        "无函数重定义": not dups,
        "未混入反向对照": "NEG_CTL_" not in b,
        "括号平衡": b.count("{") == b.count("}"),
        # 后置血统断言：前置门禁管"别拿错基底"，这里管"产出的图本身成立"。
        # 两层都要有——只做前置，任何绕过入口的改动都会重新打开同一个坑。
        "产出图 invoke 血统成立": check_map_lineage(texts.get("MapScript.galaxy", ""))[0],
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
