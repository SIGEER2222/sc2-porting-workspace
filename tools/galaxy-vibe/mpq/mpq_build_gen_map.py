"""把 generated adapter 包真正接入可编译地图，闭环 gen.* 真机执行。

根因（2026-08-08 真机取证）：生成的 `LibVibeInvokeDispatch.galaxy` 只 `#include` 各 shard
的 `_h` 头文件（原型），**不 include body**；而 `LibVibeInvokeDispatch.galaxy` 本身从未被
任何被编译的文件 include。结果 generated 包整包是死代码——`libVibeInvoke_gf_Dispatch` 与
各 `DispatchShardNN`/`CallNN` 实现未被编译，`function.invoke gen.*` 一律 FUNCTION_NOT_IN_MAP。

本脚本以 standalone 有效地图（VibeDeadOfNight.SC2Map，已知内核干净、零 ScriptError）为基线：
  1. 整体注入工作区内核（调用 dispatch 的版本，含 tagCache 等合并修复）
  2. 注入 generated 包全部 61 个 galaxy 到 Base.SC2Data/generated/亡者之夜.SC2Map/
  3. 在 MapScript.galaxy 末尾追加编译入口 include（dispatch + 27 个 shard body）
  4. 输出打包后的 .SC2Map（SC2 API 的 map_path 只接受打包文件，不接受解包目录）

铁律：Galaxy 编译失败时 SC2 静默丢弃整个 MapScript（不报错、不写日志），故做完
符号闭包 + 重定义 + include 存在性校验再交付。

StormLib v9.40 x64：本地路径 wchar_t*，MPQ 内名 ANSI；地图内文件 CRLF 行尾。
"""
from __future__ import annotations

import ctypes
import os
import re
import shutil
import sys
from ctypes import wintypes
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mpq_patch_kernel import (  # noqa: E402
    CRLF, LF, STREAM_FLAG_READ_ONLY, load_storm, mpq_read, mpq_replace,
)
import symbol_repair  # noqa: E402
import closure_doctor  # noqa: E402
import arity_doctor  # noqa: E402

WS = Path(r"E:/Code/MyMod/SC2VibeTools/sc2-porting-workspace")
WS_KERNEL = WS / "tools/galaxy-vibe/kernel/LibVibeKernel.galaxy"
# 头文件以工作区 canonical _h 为准（与内核 body 配对）：含 VIBE_GEN_007 模型库全局
# (gv_ModelBankName/gv_modelBankHandle) + tagCache + watchdog 等全部声明，且无冗余
# HANDLE_OPS 原型。地图内嵌的 _h 是陈旧快照（缺模型库全局、含冗余 HANDLE_OPS 原型
# → 触发 undefined-identifier 与 dup-proto 两道静默丢图门禁）。2026-08-09 复盘修复。
WS_KERNEL_H = WS / "tools/galaxy-vibe/kernel/LibVibeKernel_h.galaxy"
GEN_SRC = WS / "tools/galaxy-vibe/kernel/generated/亡者之夜.SC2Map"
STANDALONE = Path(r"E:/SC2/SC2new/StarCraft II/Maps/VibeDeadOfNight.SC2Map")
# VIBE_GEN_OUT 覆盖输出路径：二分阶梯图必须各自落盘，否则会互相覆盖
# （踩过：阶梯构建把已验证的全量图冲掉，白跑一轮真机）。
DST = Path(os.environ.get("VIBE_GEN_OUT") or r"C:\tmp\VibeDeadOfNight-Gen.SC2Map")

KERNEL = "Base.SC2Data\\LibVibeKernel.galaxy"
HEADER = "Base.SC2Data\\LibVibeKernel_h.galaxy"
# 【2026-08-08 真机取证】地图真正的编译入口是 **MPQ 根目录** 的 MapScript.galaxy
# （357 KB）；`Base.SC2Data\MapScript.galaxy` 不存在，往那儿写 include 等于写进空气。
# 更重要的是：MapScript 第 20 行已预留挂载点 `include "LibVibeInvokeDispatch_active"`
# （排在 include "LibVibeKernel_h" 之后、"LibVibeKernel" 之前），tier 切换的官方做法
# 就是只替换该文件内容。
#
# 【2026-08-08 形态E 根因修复】原第 20 行的挂载点**不能用于 full tier**：
#   Galaxy 与 C 同样要求「先声明后使用」，而 invoke 层（Common + shard 适配器）会直接
#   引用 MapScript 本体定义的 gf_* / auto_gf_*_TriggerFunc（本体声明从 239 行起）。
#   在 20 行展开 ⇒ use-before-declaration ⇒ 编译错误 ⇒ SC2 **静默丢弃整个 MapScript**。
#   离线 closure_doctor 的 A~D 形态是顺序无关的集合判定，对此系统性失明（曾全绿但真机 FAIL）。
# 【修复 = 原型前置，不是 include 后移】把 MapScript 本体「有定义无原型」的函数原型统一
#   补到挂载点**之前**（见 prepend_forward_protos）。include 位置保持不动。
#   ⚠ 后移方案已被真机 4/4 否决：Galaxy 的 include 存在位置硬阈值，
#     line 76 PASS / 212 PASS / 2128 PASS / 3089 FAIL / 7802 FAIL，失败形态是
#     SC2 在 join_game 阶段直接崩溃（同管线 noop 重写 MapScript 对照 PASS，已排除 MPQ 写法）。
MAPSCRIPT = "MapScript.galaxy"
ACTIVE_INC = 'include "LibVibeInvokeDispatch_active"'
RELOC_TAG = "VIBE_ACTIVE_WIRING_RELOCATED"
ACTIVE = "Base.SC2Data\\LibVibeInvokeDispatch_active.galaxy"
# include 用短名即可（SC2 以各 SC2Data 根为搜索根），generated 包平铺到 Base.SC2Data。
GEN_PREFIX = "Base.SC2Data\\"

# 工作区内核（合并版）比地图自带内核多用了一批全局状态；地图侧头文件里没有它们，
# 注入内核时必须把声明一并补进 LibVibeKernel_h.galaxy，否则就是「未定义标识符」
# ⇒ 编译错误 ⇒ **整个 MapScript 被静默丢弃**（不报错、不写 ScriptError、InitMap 不执行）。
#
# 【2026-08-08 真机取证 + closure_doctor 复现】
#   N0min（不注入工作区内核）= CLEAN / 真机 PASS
#   N0a  （仅多此一处注入）  = 未定义标识符 3 / 真机 FAIL
#   差集恰为 watchdog 三件套 —— 当初只补了 tagCache，漏了 watchdog。
# 增改工作区内核时，务必同步本块，并以 closure_doctor 的「未定义标识符 0」为准出门禁。
TAGCACHE_DECLS = """
// ---- unit tag 查找缓存（随 VIBE_KERNEL 合并版一并注入）----
int    libVibeKernel_gv_tagCacheTag = 0;
unit   libVibeKernel_gv_tagCacheUnit = null;
bool   libVibeKernel_gv_tagCacheMiss = false;
int    libVibeKernel_gv_tagCacheVersion = -1;

// ---- VIBE-KERNEL-001 watchdog 状态（同上，随合并版内核一并注入）----
trigger libVibeKernel_gt_Watchdog = null;
int     libVibeKernel_gv_watchdogLastSeen = 0;
int     libVibeKernel_gv_watchdogRestarts = 0;

// ---- VIBE_KERNEL_005 首帧 flush 标志（同上，随合并版内核一并注入）----
// PollLoop 首帧必须在 ReloadBank 与首次 ReadBankKey 之间补一次 BankSave，
// 否则 init 阶段缓冲在内存里的标记会被（当时还空的）磁盘内容覆盖掉。
bool    libVibeKernel_gv_pollLoopFirstFlushed = false;
"""
DECL_NAMES = [
    "libVibeKernel_gv_tagCacheTag",
    "libVibeKernel_gv_tagCacheUnit",
    "libVibeKernel_gv_tagCacheMiss",
    "libVibeKernel_gv_tagCacheVersion",
    "libVibeKernel_gt_Watchdog",
    "libVibeKernel_gv_watchdogLastSeen",
    "libVibeKernel_gv_watchdogRestarts",
    "libVibeKernel_gv_pollLoopFirstFlushed",
]

# 与 LibVibeInvokeDispatch.galaxy 的 shard _h include 列表严格对齐（缺 16、29）
SHARDS = [f"{i:02d}" for i in list(range(1, 16)) + list(range(17, 29)) + [30]]

# 诊断模式：VIBE_DIAG_SHARD=01,15 只接入指定 shard；VIBE_DIAG_SHARD=none 接入 0 个
# shard（纯 harness：Common + 空路由 Dispatch），用于二分定位编译失败原因。
#
# 【2026-08-08 修正】旧诊断模式注入"全部 _h（6729 原型）+ 1 个 body"，产生 6700+
# 孤儿原型。Galaxy 里"声明有原型但无实现"是编译期错误 → 整个 MapScript 静默丢弃。
# 于是"最小单元也失败"变成脚本自造的假信号。离线已验证 shard 间 cross-shard
# reference = 0（各 shard 只依赖 Common + 外部 mod 符号），故可安全生成 **reduced
# Dispatch**：只 include 选中 shard 的 _h、只路由选中 shard，其余 _h/body 一律不注入。
#
# VIBE_SKIP_KERNEL=1：保留地图自带内核，只替换 dispatch_active + 注入 generated 包。
# 用于把"内核注入"与"adapter 挂载"两个变量彻底解耦（地图自带内核已真机 p0_pass=true）。
_SKIP_KERNEL = os.environ.get("VIBE_SKIP_KERNEL") == "1"

# VIBE_FUNCREF=closure(默认) 只保留目标在编译单元里的 funcref 分支；
# VIBE_FUNCREF=none 清空整张 ResolveFuncref 表（等价真机已 PASS 的 nofuncref 变体）。
_FUNCREF_MODE = os.environ.get("VIBE_FUNCREF", "closure")
# VIBE_STAGEA=0 关闭 Stage A 自动补 include（仅诊断用，会让残余全部走 Stage B 中和）
_STAGE_A = os.environ.get("VIBE_STAGEA", "1") != "0"

# VIBE_DIAG_FORCE_INC=LibA3ADAPTER,LibEFA54406：在 active 里**强制**追加这些 include，
# 即便 symbol_repair 认为不需要（例如 VIBE_DIAG_SHARD=none 时没有任何缺失符号）。
# 用途：把「shard body 本身」与「Stage A/A2 补进来的地图自带库」拆成两个独立变量。
# 真机二分对照式：
#   none                              -> 已知 PASS（纯 harness 基线）
#   none + FORCE_INC=<Stage A 三件套>  -> 若 FAIL，元凶 = 被补进链的地图库
#   01                                -> 已知 FAIL
_FORCE_INC = [s.strip() for s in os.environ.get("VIBE_DIAG_FORCE_INC", "").split(",") if s.strip()]

# VIBE_DIAG_CALLS=1-200：只保留编号落在 [lo,hi] 的 gf_CallN（实现 + 原型 + shard
# dispatch 分支同步裁剪）。用于在**单个 shard 内部**做 adapter 级二分，定位
# closure/arity/type 三层体检都建模不到的编译错误形态。
# 形态清单（截至 2026-08-09 已知）：A 孤儿原型 / B 重复实现 / C 未定义调用 /
# D 未定义标识符 / E 迟声明 / F 未解析 include / G 元数不匹配 —— 全部已有门禁；
# 仍 FAIL 说明存在第 8 种，只能靠真机二分收敛。
_CALLS = os.environ.get("VIBE_DIAG_CALLS")
_CALL_LO, _CALL_HI = None, None
if _CALLS:
    _CALL_LO, _CALL_HI = (int(x) for x in _CALLS.split("-"))
    print(f"[diag ] VIBE_DIAG_CALLS={_CALLS}：只保留 gf_Call{_CALL_LO}..{_CALL_HI}")

RE_CALL_IMPL = re.compile(
    r"^string libVibeInvoke_gf_Call(\d+)\(string argsJson\) \{.*?^\}\n", re.M | re.S)
RE_CALL_PROTO = re.compile(
    r"^string libVibeInvoke_gf_Call(\d+)\(string argsJson\);\n", re.M)
# VIBE_GEN_002 之后 dispatch 是**扁平 early-return**（每分支一行自闭合），
# 不再有 `} else if` 链，裁剪退化成纯行删除，无需修补链首/链尾括号。
# 旧的 else-if 形态一并保留匹配，便于对历史阶梯图做回归对照。
RE_CALL_BRANCH = re.compile(
    r"^[ \t]*(?:\} else )?if \(functionId == (\d+)\) \{ "
    r"return libVibeInvoke_gf_Call\d+\(argsJson\);[ \t]*\}?\n",
    re.M)


def trim_calls(text: str, is_header: bool) -> str:
    """按 [_CALL_LO,_CALL_HI] 裁剪 adapter。裁完仍是**自洽**编译单元：
    删实现必删原型、必删 dispatch 分支，绝不制造孤儿原型（那会污染二分信号）。"""
    if _CALL_LO is None:
        return text
    keep = lambda n: _CALL_LO <= int(n) <= _CALL_HI  # noqa: E731
    if is_header:
        return RE_CALL_PROTO.sub(lambda m: m.group(0) if keep(m.group(1)) else "", text)
    text = RE_CALL_IMPL.sub(lambda m: m.group(0) if keep(m.group(1)) else "", text)
    text = RE_CALL_BRANCH.sub(lambda m: m.group(0) if keep(m.group(1)) else "", text)
    # —— 以下两条只对**历史 else-if 形态**生效，扁平形态是 no-op ——
    text = re.sub(r"(string libVibeInvoke_gf_DispatchShard\d+\(int functionId, string argsJson\) \{\n)"
                  r"[ \t]*\} else if \(", r"\1    if (", text)
    text = re.sub(r"(string libVibeInvoke_gf_DispatchShard\d+\(int functionId, string argsJson\) \{\n)"
                  r"[ \t]*\}\n(?=[ \t]*return libVibeInvoke_gf_Error)", r"\1", text)
    return text

_DIAG = os.environ.get("VIBE_DIAG_SHARD")
if _DIAG:
    if _DIAG.strip().lower() in {"none", "0", "empty"}:
        SHARDS = []
    else:
        SHARDS = [s.strip() for s in _DIAG.split(",") if s.strip()]
    print(f"[diag ] VIBE_DIAG_SHARD={_DIAG}：reduced 接入 {len(SHARDS)} shard {SHARDS}"
          f"（只注入这些 shard 的 _h + body，其余一律不注入，零孤儿原型）")


def build_full_active(shards: list[str], extra_includes: list[str] | None = None) -> str:
    """生成 tier=full 的 LibVibeInvokeDispatch_active.galaxy —— 自包含、零重复原型。

    【2026-08-08 真机根因，勿回退】L1 纯 harness（0 adapter）真机 reg={} 全灭，
    二分定位到"重复原型声明"：
      * `LibVibeKernel_h.galaxy` 已声明 `libVibeInvoke_gf_Dispatch`（MapScript line 18 已 include）。
        active 若再 include `LibVibeInvokeDispatch`（其首行 include `LibVibeInvokeDispatch_h`），
        同一原型在编译单元里声明 2 次 ⇒ Galaxy 单遍编译器报错 ⇒ SC2 **静默丢弃整个 MapScript**
        （InitMap 不执行、无 ScriptError、无日志），表现为 Kernel 从未注册。
      * 同理各 `LibVibeInvoke_NN_h` 已被对应 body 自行 include，active 不得再 include `_h`。
    故正确接法（与原图 tier0 stub 的设计一致）：
      active = include Common + include 各 shard **body** + **内联** Dispatch 路由函数体，
      完全不 include、也不注入 `LibVibeInvokeDispatch.galaxy` / `LibVibeInvokeDispatch_h.galaxy`。
    """
    txt = (GEN_SRC / "LibVibeInvokeDispatch.galaxy").read_text(
        encoding="utf-8-sig").replace(CRLF, LF)
    ranges = {nn: (lo, hi) for lo, hi, nn in re.findall(
        r"functionId\s*>=\s*(\d+)\s*&&\s*functionId\s*<=\s*(\d+)\s*\)\s*\{\s*"
        r"return\s+libVibeInvoke_gf_DispatchShard(\d+)\s*\(", txt, re.S)}
    missing = [s for s in shards if s not in ranges]
    if missing:
        raise SystemExit(f"[FAIL] 原 Dispatch 无 shard 区间: {missing}")
    out = [
        "// LibVibeInvokeDispatch_active.galaxy — tier=full（self-contained, generated, do not edit）",
        f"// 接入 {len(shards)} shard: {','.join(shards) if shards else '<none>'}",
        "// 【禁止 include LibVibeInvokeDispatch 或 LibVibeInvokeDispatch_h】",
        "//   libVibeInvoke_gf_Dispatch 原型已由 LibVibeKernel_h 提供；二次声明 ⇒ 编译错误",
        "//   ⇒ SC2 静默丢弃整个 MapScript（Kernel 永不注册）。真机已取证 2026-08-08。",
        '// 各 shard body 自带 include "LibVibeInvoke_NN_h"，故此处只 include body，不 include _h。',
    ]
    if extra_includes:
        out += [
            "// ---- symbol_repair Stage A：补进编译单元的地图自带库 ----",
            "//   generated 包引用了这些库的函数，但 MapScript 的 include 链没有它们；",
            "//   未定义标识符 ⇒ 编译错误 ⇒ SC2 静默丢弃整个 MapScript（真机已取证）。",
        ]
        out += [f'include "{inc}"' for inc in extra_includes]
        out.append("")
    out.append('include "LibVibeInvokeCommon"')
    out += [f'include "LibVibeInvoke_{s}"' for s in shards]
    out += ["", "string libVibeInvoke_gf_Dispatch(int functionId, string argsJson) {"]
    for i, s in enumerate(shards):
        lo, hi = ranges[s]
        kw = "if" if i == 0 else "} else if"
        out.append(f"    {kw} (functionId >= {lo} && functionId <= {hi}) {{")
        out.append(f"        return libVibeInvoke_gf_DispatchShard{s}(functionId, argsJson);")
    if shards:
        out.append("    }")
    out.append('    return libVibeInvoke_gf_Error("FUNCTION_NOT_IN_MAP", IntToString(functionId));')
    out.append("}")
    return "\n".join(out) + "\n"

GALAXY_IN_MPQ = [
    "Base.SC2Data\\LibVibeKernel.galaxy",
    "Base.SC2Data\\LibVibeKernel_h.galaxy",
    "Base.SC2Data\\LibVibeHandles.galaxy",
    "Base.SC2Data\\LibMapModBridge.galaxy",
    "Base.SC2Data\\LibVibeInvokeDispatch_active.galaxy",
    "MapScript.galaxy",
]


def defined_symbols(text: str) -> set[str]:
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


def read_mpq_galaxy(dll, h) -> dict[str, str]:
    """回读 MPQ 内全部 galaxy（内名 -> 文本），供符号闭包分析。

    跳过 `\\generated\\` 子目录：那是上一代快照，中文路径在 StormLib 里名字编码不
    一致读不出来，而且它们**不在 include 链上**（active 只 include 平铺的短名），
    属于死文件，不影响编译单元。
    """
    out: dict[str, str] = {}
    try:
        names = mpq_read(dll, h, "(listfile)").decode("gbk", "replace")
    except Exception as e:
        raise SystemExit(f"[FAIL] 读不到 (listfile): {e}")
    for name in names.replace(CRLF, LF).split(LF):
        name = name.strip()
        if not name.lower().endswith(".galaxy") or "\\generated\\" in name:
            continue
        try:
            out[name] = mpq_read(dll, h, name).decode("utf-8-sig", "replace") \
                .replace(CRLF, LF)
        except Exception:
            continue
    return out


def _inject_kernel(dll, h, body: str) -> None:
    """把工作区内核 body 写回 MPQ，并按需给 header 补 tagCache 全局声明。"""
    # 头文件以工作区 canonical _h 为准（见 WS_KERNEL_H 注释），不再读地图内陈旧的 _h。
    # 始终用 canonical _h 覆盖地图内 _h：canonical _h 与内核 body 配对（含模型库全局 +
    # tagCache + watchdog 等），地图内 _h 是陈旧快照（缺模型库全局、含冗余 HANDLE_OPS
    # 原型 → 触发 undefined-identifier 与 dup-proto 两道静默丢图门禁）。2026-08-09 复盘。
    header = WS_KERNEL_H.read_text(encoding="utf-8-sig").replace(CRLF, LF)
    missing = [n for n in DECL_NAMES if not re.search(rf"^\s*\w+\s+{n}\s*=", header, re.M)]
    if missing:
        # 兜底：canonical _h 理论上已含全部所需全局，此处仅在意外缺漏时补 TAGCACHE_DECLS。
        anchor = "// ---- 看门狗"
        if anchor in header:
            header = header.replace(anchor, TAGCACHE_DECLS.strip() + "\n\n" + anchor, 1)
        else:
            header = header.rstrip() + "\n" + TAGCACHE_DECLS
    hp = Path(r"C:\tmp\vibe-p0") / "LibVibeKernel_h.gen.galaxy"
    hp.parent.mkdir(parents=True, exist_ok=True)
    hp.write_bytes(header.replace(LF, CRLF).encode("utf-8"))
    mpq_replace(dll, h, HEADER, hp)
    print(f"[patch] header 已用 canonical _h 覆盖（缺失 {missing} 已兜底补齐）")

    # 内核不需要额外 include：libVibeInvoke_gf_Dispatch 的原型由 LibVibeKernel_h
    # 提供（MapScript line 18 已 include），实现由 LibVibeInvokeDispatch_active
    # 提供（line 20，排在内核 line 21 之前）。
    kp = Path(r"C:\tmp\vibe-p0\LibVibeKernel.gen.galaxy")
    kp.parent.mkdir(parents=True, exist_ok=True)
    kp.write_bytes(body.replace(LF, CRLF).encode("utf-8"))
    mpq_replace(dll, h, KERNEL, kp)
    print(f"[patch] 内核 body 已写回 ({kp.stat().st_size} B)")


# MapScript 顶层（列 0 起）的原型 / 定义。Galaxy 生成的 MapScript 参数恒为单行。
RE_MS_PROTO = re.compile(r"^([A-Za-z_]\w*)[ \t]+(\w+)[ \t]*\(([^;{)]*)\)[ \t]*;", re.M)
RE_MS_DEF = re.compile(r"^([A-Za-z_]\w*)[ \t]+(\w+)[ \t]*\(([^){]*)\)[ \t]*\{", re.M)
PROTO_TAG = "VIBE_FORWARD_PROTOS"


def prepend_forward_protos(ms: str) -> tuple[str, int]:
    """在 active 的 include **之前**补齐 MapScript 本体函数的前置原型。

    == 解决什么（形态E / use-before-declare）==
    invoke 层（Common 的 funcref 表、shard 08~15 适配器）会直接引用 MapScript 本体的
    gf_* / auto_gf_*_TriggerFunc。Galaxy 与 C 一样要求先声明后使用，而挂载点在第 20 行、
    本体符号从 212 行起才声明 ⇒ 编译错误 ⇒ SC2 **静默丢弃整个 MapScript**。

    == 为什么不是「后移 include」（曾经的方案，已被真机否决）==
    2026-08-08 真机二分实测，Galaxy 的 include 存在**位置硬阈值**：
        line 76(gvars) PASS / 212(protos) PASS / 2128 PASS / 3089 FAIL / 7802(InitMap 前) FAIL
    且失败形态是 SC2 在 join_game 阶段**直接崩溃**（4/4 复现），而同管线 noop 重写
    MapScript（内容 0 改动）对照 PASS —— 排除 MPQ 写入姿势。故 include 必须留在头部。

    == 安全边界 ==
    判据是「挂载点**之前**有没有原型」，不是「整个文件里有没有原型」。
    MapScript 自带的原型区在 212 行起、也排在挂载点(20 行)之后，对 invoke 层同样太晚；
    第一版按全文件差集去重，导致这 36 个「有晚原型」的 gf_* 被误跳过（迟声明 298->36 卡住）。
    重复原型本身合法——2026-08-08 真机 proto_test 已单独取证（`gf_AIPrepareAttackDirection`
    在挂载点前后各声明一次，P0-A/P0-B 双 PASS）。
    """
    lines = ms.split(LF)
    hits = [i for i, ln in enumerate(lines) if ln.strip() == ACTIVE_INC]
    if len(hits) != 1:
        raise SystemExit(f"[FAIL] active 挂载点应恰好 1 处，实得 {len(hits)}")
    mount_off = len(LF.join(lines[:hits[0]]))

    have = {m.group(2) for m in RE_MS_PROTO.finditer(ms) if m.start() < mount_off}
    skip = {"InitMap", "InitLibs", "InitGlobals", "InitTriggers"}
    gen: list[str] = []
    seen: set[str] = set()
    for m in RE_MS_DEF.finditer(ms):
        typ, name, params = m.group(1), m.group(2), m.group(3).strip()
        if name in have or name in skip or name in seen:
            continue
        if typ in ("if", "while", "for", "switch", "else", "do", "return"):
            continue
        seen.add(name)
        gen.append(f"{typ} {name} ({params});")
    if not gen:
        return ms, 0

    lines[hits[0]:hits[0]] = (
        [f"// ==== BEGIN {PROTO_TAG} ====",
         "// 形态E 修复：invoke 层引用 MapScript 本体函数，必须在挂载点之前先声明。",
         "// 判据 = 挂载点之前无原型（文件自带原型区在挂载点之后，一样太晚）。",
         "// 与后面原型区重复是合法的，真机 proto_test 已取证。**勿删**。"]
        + gen + [f"// ==== END {PROTO_TAG} ====", ""])
    return LF.join(lines), len(gen)


def relocate_active_include(ms: str) -> str:
    """【已废弃 · 真机否决，保留仅作反例记录，勿在管线启用】

    把 active include 后移到 InitMap() 之前。真机 4/4 复现 SC2 在 join_game 阶段
    **崩溃**（不是静默丢弃）；根因是 Galaxy include 的位置硬阈值，详见
    prepend_forward_protos 的 docstring。
    """
    lines = ms.split(LF)
    hits = [i for i, ln in enumerate(lines) if ln.strip() == ACTIVE_INC]
    if len(hits) != 1:
        raise SystemExit(f"[FAIL] active 挂载点应恰好 1 处，实得 {len(hits)}")
    lines[hits[0]] = f"// [{RELOC_TAG}] 原挂载点已后移至 InitMap 之前（形态E 修复，勿还原）"

    ini = [i for i, ln in enumerate(lines)
           if re.match(r"^\s*void\s+InitMap\s*\(\s*\)\s*\{", ln)]
    if len(ini) != 1:
        raise SystemExit(f"[FAIL] InitMap 定义应恰好 1 处，实得 {len(ini)}")
    at = ini[0]
    lines[at:at] = [
        f"// ==== BEGIN {RELOC_TAG} ====",
        "// 形态E（use-before-declare）修复：invoke 层引用 MapScript 本体 gf_*，",
        "// 必须在其全部声明之后展开，否则 SC2 静默丢弃整个 MapScript。**勿上移**。",
        ACTIVE_INC,
        f"// ==== END {RELOC_TAG} ====",
        "",
    ]
    return LF.join(lines)


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else STANDALONE
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else DST
    if not src.exists():
        raise SystemExit(f"[FAIL] 基线不存在: {src}")
    if not WS_KERNEL.exists():
        raise SystemExit(f"[FAIL] 工作区内核不存在: {WS_KERNEL}")
    if not GEN_SRC.is_dir():
        raise SystemExit(f"[FAIL] generated 源不存在: {GEN_SRC}")

    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)
    print(f"[copy] {src.name} -> {dst.name} ({dst.stat().st_size} B)")

    body = WS_KERNEL.read_bytes().decode("utf-8-sig").replace(CRLF, LF)
    gen_files = sorted(p for p in GEN_SRC.glob("*.galaxy"))
    print(f"[read] 内核 {len(body)} chars; generated {len(gen_files)} 个 galaxy")

    if _CALL_LO is not None:
        # 裁剪版写到独立临时目录后再入链；GEN_SRC（版本库产物）保持只读不动。
        trim_dir = Path(r"C:\tmp\vibe-p0\gen-trimmed")
        if trim_dir.exists():
            shutil.rmtree(trim_dir)
        trim_dir.mkdir(parents=True)
        trimmed: list[Path] = []
        n_impl = n_proto = 0
        for gf in gen_files:
            txt = gf.read_bytes().decode("utf-8-sig").replace(CRLF, LF)
            if re.match(r"LibVibeInvoke_\d+(_h)?\.galaxy$", gf.name):
                new = trim_calls(txt, gf.name.endswith("_h.galaxy"))
                if new != txt:
                    if gf.name.endswith("_h.galaxy"):
                        n_proto += txt.count("gf_Call") - new.count("gf_Call")
                    else:
                        n_impl += (len(RE_CALL_IMPL.findall(txt))
                                   - len(RE_CALL_IMPL.findall(new)))
                    out = trim_dir / gf.name
                    out.write_bytes(new.replace(LF, CRLF).encode("utf-8"))
                    trimmed.append(out)
                    continue
            trimmed.append(gf)
        gen_files = trimmed
        print(f"[diag ] 裁剪后：删实现 {n_impl} / 删原型 {n_proto} -> {trim_dir}")

    dll = load_storm()
    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, 0, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] open {dst}: {ctypes.get_last_error()}")
    try:
        # ---- 0) 先把 MPQ 内全部 galaxy 回读到内存（**必须在任何写操作之前**）----
        # 【2026-08-08 踩坑】StormLib 一旦执行过 SFileAddFileEx/mpq_replace，档案进入
        # "已修改待重建" 状态，此时读 `(listfile)` 拿到的是空/残缺内容 → read_mpq_galaxy
        # 返回 0 个文件 → 符号闭包分析把内核自身符号也误判为缺失 → Stage B 把全部 Call
        # 函数中和 → 最终 FAIL。故回读必须排在 _inject_kernel 之前。
        mpq_texts = read_mpq_galaxy(dll, h)
        print(f"[symrep] MPQ 内可读 galaxy {len(mpq_texts)} 个")
        if len(mpq_texts) < 10:
            raise SystemExit(
                f"[FAIL] MPQ galaxy 回读异常（只有 {len(mpq_texts)} 个），"
                f"符号闭包分析不可信，拒绝继续")

        # ---- 1) 注入工作区内核 body + header tagCache ----
        if _SKIP_KERNEL:
            print("[skip ] VIBE_SKIP_KERNEL=1：保留地图自带内核，不做任何内核改动")
        else:
            _inject_kernel(dll, h, body)
            # 内存快照同步为 **注入后** 的内核文本，否则符号集按旧内核算会偏差
            mpq_texts[KERNEL] = body
            # 头文件同样以 canonical _h 同步内存快照（见 WS_KERNEL_H 注释），
            # 避免符号闭包分析按地图内陈旧 _h 误判缺失符号
            mpq_texts[HEADER] = WS_KERNEL_H.read_text(
                encoding="utf-8-sig").replace(CRLF, LF)

        # ---- 2) 把 tier0 stub 换成 full 派发层（MapScript 完全不动）----
        ms = mpq_read(dll, h, MAPSCRIPT).decode("utf-8-sig").replace(CRLF, LF)
        if 'include "LibVibeInvokeDispatch_active"' not in ms:
            raise SystemExit("[FAIL] MapScript 缺少 LibVibeInvokeDispatch_active 挂载点")

        # ---- 2.5) 符号闭包修复（编译期未定义标识符 = SC2 静默丢弃全图）----
        allow = {"LibVibeInvokeCommon.galaxy"}
        for s in SHARDS:
            allow.add(f"LibVibeInvoke_{s}.galaxy")
            allow.add(f"LibVibeInvoke_{s}_h.galaxy")
        gen_texts = {
            gf.name: gf.read_bytes().decode("utf-8-sig").replace(CRLF, LF)
            for gf in gen_files
            if gf.name in allow and "tier" not in gf.name.lower()
        }
        seed_inc = ["LibVibeInvokeCommon"] + [f"LibVibeInvoke_{s}" for s in SHARDS]
        rep = symbol_repair.repair(mpq_texts, ms, gen_texts, seed_inc,
                                   funcref_mode=_FUNCREF_MODE, stage_a=_STAGE_A)
        if rep.still_missing:
            raise SystemExit(
                f"[FAIL] 符号闭包不完整，拒绝交付会静默丢弃的地图: "
                f"{sorted(rep.still_missing)[:20]}")

        # active 自包含（Common + 各 shard body + 内联 Dispatch 路由）；
        # 绝不 include/注入 LibVibeInvokeDispatch(_h)（详见 build_full_active docstring）。
        act_incs = list(rep.extra_includes)
        for inc in _FORCE_INC:                      # 诊断：强制并入（去重、保持顺序）
            if inc not in act_incs:
                act_incs.append(inc)
        if _FORCE_INC:
            print(f"[diag ] VIBE_DIAG_FORCE_INC 强制 include: {_FORCE_INC} -> 最终 {act_incs}")
        act = build_full_active(SHARDS, act_incs)
        ap = Path(r"C:\tmp\vibe-p0\LibVibeInvokeDispatch_active.gen.galaxy")
        ap.parent.mkdir(parents=True, exist_ok=True)
        ap.write_bytes(act.replace(LF, CRLF).encode("utf-8"))
        mpq_replace(dll, h, ACTIVE, ap)
        print(f"[patch] dispatch_active -> tier=full（自包含: Common + {len(SHARDS)} body"
              f" + 内联 Dispatch，不含 Dispatch/_h）")

        # ---- 2.7) 形态E 修复：在挂载点之前补齐 MapScript 本体前置原型 ----
        # 【勿改回 relocate_active_include】include 后移已被真机 4/4 否决（位置硬阈值 ⇒
        #  join_game 崩溃）。这里 include 位置**保持不动**，只在其前面插入原型块。
        ms_fix, n_proto = prepend_forward_protos(ms)
        msp = Path(r"C:\tmp\vibe-p0\MapScript.protos.galaxy")
        msp.write_bytes(ms_fix.replace(LF, CRLF).encode("utf-8"))
        mpq_replace(dll, h, MAPSCRIPT, msp)
        mpq_texts[MAPSCRIPT] = ms_fix
        print(f"[patch] MapScript 前置原型 x{n_proto}（形态E，{msp.stat().st_size} B）")

        # ---- 3) 注入 generated 包（只注入真正进 include 链的文件）----
        # allow-set（已在 2.5 构建）：Common + 选中 shard 的 body & _h。
        # 【勿加 Dispatch/Dispatch_h】它们不进 include 链（active 已内联 Dispatch），
        # 注入进去也会因 include 链缺失而不参与编译；且 Dispatch_h 会二次声明
        # libVibeInvoke_gf_Dispatch。各 shard body 自带 include "_NN_h"，故 _NN_h 文件
        # 必须存在于 MPQ（供 body include），但 active 不再直接 include 它。
        patch_dir = Path(r"C:\tmp\vibe-p0\gen-patched")
        patch_dir.mkdir(parents=True, exist_ok=True)

        added = 0
        injected: list[str] = []
        for gf in gen_files:
            if "tier" in gf.name.lower() or gf.name not in allow:
                continue
            local = gf
            if gf.name in rep.patched:          # Stage B 改写过的走临时副本
                local = patch_dir / gf.name
                local.write_bytes(rep.patched[gf.name].replace(LF, CRLF).encode("utf-8"))
            archived = (GEN_PREFIX + gf.name).encode("utf-8")
            ok = dll.SFileAddFileEx(
                h, str(local), archived,
                0x00000200 | 0x80000000, 0x02, 0x02)
            if not ok:
                raise RuntimeError(f"SFileAddFileEx failed for {gf.name}: {ctypes.get_last_error()}")
            added += 1
            injected.append(GEN_PREFIX + gf.name)
        print(f"[add  ] generated 包 {added}/{len(gen_files)} 个文件 -> {GEN_PREFIX}<name>")
        dll.SFileFlushArchive(h)
    finally:
        dll.SFileCloseArchive(h)

    # ---- 4) 回读校验 ----
    # 参数顺序 (szMpqName, dwPriority, dwFlags, phMpq)。回读校验**必须**真的只读：
    # 把 STREAM_FLAG_READ_ONLY 填错到 dwPriority 槽会以读写方式重开刚写完的档案，
    # 校验本身就有回写风险，等于自己证明自己。
    h2 = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(h2)):
        raise SystemExit("[FAIL] 回读打开失败")
    texts: dict[str, str] = {}
    # Stage A 补进编译单元的库（及其 _h / _Catalog）也要纳入门禁范围
    extra_in_mpq: list[str] = []
    for inc in rep.extra_includes:
        for suffix in ("", "_h", "_Catalog"):
            nm = f"Base.SC2Data\\{inc}{suffix}.galaxy"
            if nm in mpq_texts:
                extra_in_mpq.append(nm)
    try:
        for name in GALAXY_IN_MPQ + extra_in_mpq:
            try:
                texts[name] = mpq_read(dll, h2, name).decode("utf-8-sig").replace(CRLF, LF)
            except Exception:
                pass
        # generated 包（严格按实际 ADD 清单回读）
        for archived in injected:
            try:
                texts[archived] = mpq_read(dll, h2, archived).decode("utf-8-sig").replace(CRLF, LF)
            except Exception as e:
                texts[archived] = f"<<READ FAIL: {e}>>"
    finally:
        dll.SFileCloseArchive(h2)

    print(f"[read ] 回读 {len(texts)} 个 galaxy")

    defined: set[str] = set()
    for t in texts.values():
        defined |= defined_symbols(t)

    # 关键符号必须存在定义（诊断模式下按实际接入的首个 shard 取样）
    must_define = ["libVibeInvoke_gf_Dispatch",
                   "libVibeInvoke_gf_Ok", "libVibeInvoke_gf_Error"]
    sample_shard = SHARDS[0] if SHARDS else None
    sample_call = None
    if sample_shard:
        must_define.append(f"libVibeInvoke_gf_DispatchShard{sample_shard}")
        st = texts.get(GEN_PREFIX + f"LibVibeInvoke_{sample_shard}.galaxy", "")
        m = re.search(r"(libVibeInvoke_gf_Call\d+)\s*\(", st)
        if m:
            sample_call = m.group(1)
            must_define.append(sample_call)
    missing_def = [s for s in must_define if s not in defined]

    # ---- 孤儿原型检测（离线复现 Galaxy 编译期错误）----
    # Galaxy：函数有原型声明但无实现 ⇒ 编译期错误 ⇒ SC2 静默丢弃整个 MapScript。
    # 旧诊断模式正是踩了这个坑（注入 6729 原型只给 1 个 body），本检查把它变成硬门禁。
    protos: set[str] = set()
    impls: set[str] = set()
    typ = (r"(?:void|bool|int|string|fixed|unit|point|text|trigger|unitgroup|playergroup|"
           r"bank|order|region|timer|actor|wave|revealer|abilcmd|marker|doodad|aifilter|"
           r"unitfilter|waveinfo|wavetarget)")
    # 【2026-08-08 真机根因修正，勿收窄】原正则只认 `libVibeInvoke_gf_*`，于是 Common
    # 里的 funcref 原型 `void libVibeInvoke_gp_VoidIntProto (int lp_p0);`（_gp_ 前缀、
    # 只有声明没有实现）完美绕过本门禁 ⇒ 门禁 13/13 全绿但真机 P0 全灭（Kernel 从未
    # 注册），排查代价极高。改为匹配任意函数名，覆盖 _gp_/_gt_ 等全部前缀。
    for n, t in texts.items():
        if not n.startswith(GEN_PREFIX + "LibVibeInvoke"):
            continue
        protos |= set(re.findall(rf"^\s*{typ}\s+(\w+)\s*\([^;{{]*\)\s*;", t, re.M))
        impls |= set(re.findall(rf"^\s*{typ}\s+(\w+)\s*\([^;{{]*\)\s*\{{", t, re.M))
    orphans = sorted(protos - impls)

    # 符号闭包：内联在 active 里的 Dispatch 路由引用的每个 DispatchShardNN
    # 都必须在编译单元里有定义。缺定义 ⇒ 运行时该 trigger 线程直接中止
    # （无响应、无 ScriptError），就是 "kernel 活着但 gen.* 请求超时" 的真因。
    act_txt = texts.get(ACTIVE, "")
    referenced = sorted(set(re.findall(r"libVibeInvoke_gf_(DispatchShard\d+)", act_txt)))
    unresolved = [f"libVibeInvoke_gf_{n}" for n in referenced
                  if f"libVibeInvoke_gf_{n}" not in defined]

    # 重定义检查（全 MPQ 范围）
    all_defs: list[str] = []
    for t in texts.values():
        all_defs += re.findall(
            r"^(?:void|bool|int|string|fixed|unit|point|text)\s+(\w+)\s*\([^;]*\)\s*\{", t, re.M)
    dups = sorted({n for n in all_defs if all_defs.count(n) > 1})

    # ---- 跨文件重复原型声明检测（2026-08-08 真机根因，硬门禁）----
    # Galaxy 单遍编译器：同一函数原型在编译单元里被声明 2 次 ⇒ 编译错误
    # ⇒ SC2 静默丢弃整个 MapScript（无 ScriptError、无日志，Kernel 永不注册）。
    # 事故：active include LibVibeInvokeDispatch → 其 include Dispatch_h，
    # 而 LibVibeKernel_h 已声明 libVibeInvoke_gf_Dispatch → 二次声明 → 全灭。
    # 只统计真正进 include 链的文件（未被 include 的文件不参与编译）。
    unit_files = list(GALAXY_IN_MPQ) + extra_in_mpq + list(injected)
    proto_owner: dict[str, list[str]] = {}
    defined_anywhere: set[str] = set()
    for n in unit_files:
        t = texts.get(n)
        if not t:
            continue
        for fn in set(re.findall(rf"^\s*{typ}\s+(\w+)\s*\([^;{{]*\)\s*;", t, re.M)):
            proto_owner.setdefault(fn, []).append(n.rsplit("\\", 1)[-1])
        defined_anywhere |= set(re.findall(
            rf"^\s*{typ}\s+(\w+)\s*\([^;{{]*\)\s*\{{", t, re.M))
    # 仅当某函数被 2+ 文件原型声明且**编译单元内无任何定义**时才算真错误
    # （正文里原型+定义齐全、_h 里再声明一次原型 = Galaxy 合法的前向声明，不会静默丢图；
    # 已实机验证的 LIVE-PASS 地图正是此模式）。有定义的函数即使跨文件多原型也放行，
    # 避免把良性前向声明误判为 BROKEN。无定义的多原型仍会被 undefined_* 门禁覆盖捕获。
    dup_protos = sorted(f"{k} @ {'+'.join(v)}"
                        for k, v in proto_owner.items()
                        if len(v) > 1 and k not in defined_anywhere)

    # include 入口正确：Common + 各 shard body，且**绝不**含 Dispatch/_h
    # 只看真正的 include 语句行（排除注释），避免注释里的字面量误判。
    act_incs = set(re.findall(r'^\s*include\s+"([^"]+)"', act_txt, re.M))
    entry_ok = ("LibVibeInvokeCommon" in act_incs
                and all(f"LibVibeInvoke_{s}" in act_incs for s in SHARDS)
                and "LibVibeInvokeDispatch" not in act_incs
                and "LibVibeInvokeDispatch_h" not in act_incs)
    ms_txt = texts.get(MAPSCRIPT, "")

    # ---- 编译闭包全量体检（closure_doctor）：交付前最后一道 fail-closed 门禁 ----
    # 上面那些检查都只看「我注入的文件」，而 Galaxy 是按**整个 include 闭包**编译的：
    # 闭包里任何一处孤儿原型 / 重复实现 / 未定义调用都会让 SC2 静默丢弃整个 MapScript。
    # closure_doctor 用 compile_unit.resolve() 的真实闭包做基准（对已知能跑的
    # standalone 基线图实测 0/0/0，零误报），故可直接当门禁。
    diag = closure_doctor.diagnose(dst)
    print(f"  [info] closure_doctor: {diag.summary()}")

    # ---- 调用签名体检（arity_doctor）：closure_doctor 覆盖不到的第 7 种形态 ----
    # closure_doctor 只回答「符号存不存在 / 声明够不够早」，完全不看签名。
    # 但 Galaxy 是强类型单遍编译器：实参个数 != 形参个数 ⇒ 编译错误
    # ⇒ SC2 静默丢弃整个 MapScript（无 ScriptError、无日志、bank_keys=0）。
    # 【VIBE_GEN_001 真机取证 2026-08-09】shard=none PASS / shard=01 FAIL，
    # 二分到生成器把 `FixedToString(f, precision)` 写成单参，全 bundle 共 99 处
    # （亡者之夜 14 个 shard），Common 里恰好 0 处 —— 完美解释 none/01 的分界。
    ar = arity_doctor.audit(dst)
    print(f"  [info] arity_doctor: 签名表 {ar.n_sigs} / 受检 {ar.n_files} 文件"
          f"；元数不匹配 {len(ar.bad_arity)}、void 当右值 {len(ar.bad_void)}")
    for s in (ar.bad_arity + ar.bad_void)[:10]:
        print(f"         ! {s}")

    for s in diag.native_argtypes[:10]:
        print(f"         ! {s}")

    # ---- Bank handle 缓存语义门禁（2026-08-09 真机 L1/L2/L2a/L2b 四点对照根因）----
    # 内核任何 `gv_bankHandle = BankLoad(...)` 都必须包在 `gv_bankHandle == null` 守卫内。
    # 无条件覆盖会在 InitMap 同步阶段（BankLoad 返回 null）把已有的有效 handle 打成 null，
    # 于是 WriteBankInt 的 `if (handle == null) return;` 静默吞掉全部初始化标记 ——
    # 表现为 watchdog_last_seen_poll 正常递增但 kernel_initialized 永不出现，
    # 极易被误判成「MapScript 被静默丢弃」。详见内核 VIBE_KERNEL_003_HANDLE_CACHE 注释。
    def _bank_handle_cached(kernel_txt: str) -> bool:
        # 先剥注释：注释里出现 BankLoad( 不该影响判定（旧门禁按纯文本计数被自己的注释误伤过）。
        code = re.sub(r"/\*.*?\*/", "", kernel_txt, flags=re.S)
        code = re.sub(r"//[^\n]*", "", code)
        loads = list(re.finditer(r"\w*bankHandle\s*=\s*BankLoad\s*\(", code))
        if len(loads) != 2:                       # 恰好 ReloadBank + EnsureBankLoaded 各一处
            return False
        for m in loads:
            head = code[max(0, m.start() - 220):m.start()]
            guard = re.search(r"if\s*\(\s*\w*bankHandle\s*==\s*null\s*\)\s*\{[^{}]*$", head)
            if not guard:
                return False
        return True

    # 门禁 VIBE_KERNEL_004：InitLib() 里严禁同步调用 RegisterEntryPoints()。
    # map-init 阶段 BankSave 尚未 flush；同步注册会立刻派发 PollLoop，
    # 其 ReloadBank()(BankRemove+BankLoad) 把未落盘的内存态 Bank 清空重读，
    # 于是 initlib_entered / init_entered / kernel_initialized / register_entrypoints_*
    # 全部灰飞烟灭，只剩 Wait 之后异步线程写的键 —— 伪装成「MapScript 被静默丢弃」。
    # 真机 L1(基准) PASS / L2,L2a,L2b(带同步调用) FAIL 五点对照取证。
    def _initlib_no_sync_register(kernel_txt: str) -> bool:
        code = re.sub(r"/\*.*?\*/", "", kernel_txt, flags=re.S)
        code = re.sub(r"//[^\n]*", "", code)
        m = re.search(r"void\s+libVibeKernel_InitLib\s*\(\s*\)\s*\{", code)
        if not m:
            return False
        depth, k = 0, code.index("{", m.start())
        while k < len(code):
            if code[k] == "{":
                depth += 1
            elif code[k] == "}":
                depth -= 1
                if depth == 0:
                    break
            k += 1
        body = code[m.start():k + 1]
        # 允许 TriggerCreate("..._RegisterEntryPoints_Func") 字符串形式的延迟注册，
        # 只禁止直接的同步函数调用 libVibeKernel_gf_RegisterEntryPoints(...)
        return not re.search(r"libVibeKernel_gf_RegisterEntryPoints\s*\(", body)

    checks = {
        "generated 包全部读回": all("READ FAIL" not in texts.get(n, "FAIL") for n in injected),
        # 形态E：挂载点保持在头部（后移已被真机否决），但前置原型块必须排在它之前。
        "MapScript 前置原型块在挂载点之前": (
            ms_txt.count(ACTIVE_INC) == 1
            and PROTO_TAG in ms_txt
            and (lambda p, a: 0 <= p < a)(
                ms_txt.find(f"BEGIN {PROTO_TAG}"), ms_txt.find(ACTIVE_INC))
            and RELOC_TAG not in ms_txt          # 严禁走回后移老路
            and "[STAGE26]" not in ms_txt),
        "dispatch_active 已替换为 full": entry_ok,
        "libVibeInvoke_gf_Dispatch 已定义": "libVibeInvoke_gf_Dispatch" not in missing_def,
        f"DispatchShard{sample_shard or '--'} 已定义": (
            not sample_shard
            or f"libVibeInvoke_gf_DispatchShard{sample_shard}" not in missing_def),
        f"{sample_call or 'Call(样本)'} 已定义": (
            sample_call is None if not SHARDS else sample_call not in missing_def),
        "Ok/Error(Common) 已定义": not ({"libVibeInvoke_gf_Ok",
                                        "libVibeInvoke_gf_Error"} & set(missing_def)),
        **({} if _SKIP_KERNEL else {
            "内核仍含 tagCache": "libVibeKernel_gv_tagCacheVersion" in texts.get(KERNEL, ""),
            "内核 Bank handle 缓存语义（2 处 BankLoad 均在 ==null 守卫内）":
                _bank_handle_cached(texts.get(KERNEL, "")),
            "InitLib 未同步调用 RegisterEntryPoints（VIBE_KERNEL_004）":
                _initlib_no_sync_register(texts.get(KERNEL, ""))}),
        "无函数重定义": not dups,
        "零孤儿原型（有声明必有实现）": not orphans,
        "零跨文件重复原型声明": not dup_protos,
        "DispatchShardNN 符号闭包": not unresolved,
        "编译单元符号闭包（symbol_repair）": not rep.still_missing,
        "闭包体检·零孤儿原型": not diag.orphan_protos,
        "闭包体检·零重复实现": not diag.dup_impls,
        "闭包体检·零未定义调用": not diag.undefined_calls,
        # 形态 D：非调用位置的变量/trigger 引用。真机 N0a vs N0min 差集验证过，
        # 漏掉 watchdog 三件套声明就是这一项报 3、整图静默丢弃。
        "闭包体检·零未定义标识符": not diag.undefined_idents,
        # 形态 E：DFS 展开序上「引用早于声明」。A~D 都是顺序无关的集合判定，对此失明。
        # 真机取证：T-all 离线 A~D 全绿却 FAIL，根因就是这一项（Common:284 引用
        # gf_AIPrepareAttackDirection，而其声明在 MapScript:239 —— 而挂载点在 line 20）。
        "闭包体检·零迟声明（形态E）": not diag.late_decls,
        "闭包体检·零局部迟声明（形态H）": not diag.local_late_decls,
        # VIBE_GEN_002：else-if 链 > 65 分支 ⇒ 语法树嵌套超限 ⇒ 整图静默丢弃
        "闭包体检·零超长else-if链（形态I）": not diag.overlong_elseif,
        # VIBE_GEN_003：native 实参/赋值类型错配（arity 只数个数，看不到类型）
        "闭包体检·零类型错配（形态J）": not diag.native_argtypes,
        # VIBE_GEN_004：调用只有原型没有实现体的函数（funcref 签名模板）
        "闭包体检·零调用空原型（形态K）": not diag.protoonly_calls,
        # VIBE_GEN_005：跨文件调用 static（file-local）函数 ⇒ 未定义符号
        "闭包体检·零跨文件调用static（形态L）": not diag.cross_file_static,
        "闭包体检·include 全解析": not diag.unresolved_includes,
        # 形态 G（VIBE_GEN_001）：签名/元数不匹配。符号存在、声明也够早，
        # 但实参个数对不上形参 ⇒ 编译错误 ⇒ 静默丢弃整图。closure_doctor 对此失明。
        "签名体检·零元数不匹配": not ar.bad_arity,
        "签名体检·零 void 当右值": not ar.bad_void,
    }
    ok = True
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'FAIL'}] {k}")
        ok = ok and bool(v)
    print(f"  [info] 原型 {len(protos)} / 实现 {len(impls)} / 接入 shard {len(SHARDS)}")
    print(f"  [info] symbol_repair: 初始缺失 {len(rep.initial_missing)}"
          f" / Stage A 补 include {rep.extra_includes}（回滚 {rep.banned}）"
          f" / Stage C funcref 保留 {rep.funcref_kept}、删除 {rep.funcref_dropped}"
          f" / Stage B 删赋值 {rep.dropped_assign}、删 funcref {rep.dropped_funcref}、"
          f"中和函数 {len(rep.neutralized)}{rep.neutralized[:6]}")
    if missing_def:
        print(f"    missing defs: {missing_def}")
    if unresolved:
        print(f"    unresolved shard impls: {unresolved}")
    if orphans:
        print(f"    orphan protos ({len(orphans)}): {orphans[:12]}")
    if dups:
        print(f"    dup defs: {dups[:12]}")
    if dup_protos:
        print(f"    dup protos ({len(dup_protos)}): {dup_protos[:12]}")
    if diag.orphan_protos:
        print(f"    [doctor] 孤儿原型 {len(diag.orphan_protos)}: "
              f"{diag.orphan_protos[:10]}")
        for k, v in sorted(diag.orphan_by_file.items(), key=lambda x: -x[1])[:8]:
            print(f"             {v:5d}  {k}")
    if diag.dup_impls:
        print(f"    [doctor] 重复实现 {len(diag.dup_impls)}: {diag.dup_impls[:10]}")
    if diag.undefined_calls:
        print(f"    [doctor] 未定义调用 {len(diag.undefined_calls)}: "
              f"{sorted(diag.undefined_calls)[:12]}")
    if diag.undefined_idents:
        print(f"    [doctor] 未定义标识符 {len(diag.undefined_idents)}（变量/trigger 无声明）:")
        for nm in sorted(diag.undefined_idents)[:12]:
            print(f"             {nm}  <- {diag.undefined_idents[nm][:3]}")
    if diag.unresolved_includes:
        print(f"    [doctor] 未解析 include: {diag.unresolved_includes[:8]}")
    print(f"[{'DONE' if ok else 'BROKEN'}] {dst} ({dst.stat().st_size} B)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
