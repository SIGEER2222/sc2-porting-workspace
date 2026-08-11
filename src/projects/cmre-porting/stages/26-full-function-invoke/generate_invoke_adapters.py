# -*- coding: utf-8 -*-
"""Stage 26 full-function invoke generator.

Reads the Stage 25 function catalog and emits:
  1. artifacts/.../stage26-full-function-invoke/invoke-plan.json  (invoke plan)
  2. tools/galaxy-vibe/kernel/function-registry.json               (rewritten, hand-written entries kept)
  3. tools/galaxy-vibe/kernel/LibVibeHandles.galaxy                (handle registry)
  4. tools/galaxy-vibe/kernel/generated/<MapName>/*                (per-map adapter shards + dispatch)
  5. Idempotent marker-guarded patches to LibVibeKernel.galaxy / LibVibeKernel_h.galaxy
  6. Sync: kernel -> galaxy-debug-mod/Base.SC2Data -> 亡者之夜 map mirror

Policy: static compile-time dispatch only (arbitrary_reflection stays false).
Every generated entry is debug_only=true.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

STAGE_DIR = Path(__file__).resolve().parent
ROOT = STAGE_DIR.parents[4]
CATALOG_PATH = ROOT / "artifacts/projects/cmre-porting/stage25-ai-ally-capability-completion/discovery/function-catalog.json"
# Catalog paths are relative to this root (function-catalog.json -> sources[0].root).
SOURCE_ROOT = ROOT / "src/projects/cmre-porting/packages"
ART_DIR = ROOT / "artifacts/projects/cmre-porting/stage26-full-function-invoke"
KERNEL = ROOT / "tools/galaxy-vibe/kernel"
REGISTRY_PATH = KERNEL / "function-registry.json"
WHITELIST_PATH = KERNEL / "whitelist.json"
DEBUG_MOD = ROOT / "tools/galaxy-vibe/galaxy-debug-mod/Base.SC2Data"
MAP_MIRROR = ROOT / "src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map/Base.SC2Data"

SHARD_SIZE = 400
# 分档放量（计划风险节）：每档生成一个只挂载低区间分片的 dispatch 变体。
ROLLOUT_TIERS = (100, 1000)
MARKER = "STAGE26_FULL_INVOKE"
# funcref 类型名。**必须用 Stage 26 自有前缀**：早期版本借用了 `CMPE_PlayerEventFunc`，
# 但那个名字在 CMRE 源里只有同前缀的**函数**（CMPE_RunHeroEventForPlayer 等
# TriggerStrings 条目），**从来没有任何类型声明**。对照实验已坐实：
#   libCOTF_gs_HistogramData → LibCOTF_h.galaxy:52 有 `struct ... {`  ✅ 找得到
#   CMPE_PlayerEventFunc     → 全部源文件零声明                        ❌ 找不到
# 未声明类型 → Galaxy 编译失败 → SC2 **静默丢弃整个 MapScript**（不报错、
# 不写 ScriptError.txt、InitMap 根本不被调用），而 galaxy-lint 只做语法/符号
# 检查、看不到跨文件类型闭包，所以照样报 0 error。
# 自有前缀同时杜绝与源 mod 符号重定义（重定义同样是静默丢弃）。
# 门禁：tools/galaxy-vibe/check_undeclared_types.py
FUNCREF_TYPE = "libVibeInvoke_gt_VoidIntFunc"
FUNCREF_PROTO = "libVibeInvoke_gp_VoidIntProto"
STRUCTREF_TYPE = "structref<libCOTF_gs_HistogramData>"
STRUCT_CTYPE = "libCOTF_gs_HistogramData"

BASIC_TYPES = {"int", "fixed", "bool", "string", "text", "void"}
NULLABLE_HANDLES = {
    "unit", "unitgroup", "point", "region", "playergroup", "trigger", "bank",
    "timer", "actor", "wave", "wavetarget", "waveinfo", "aifilter", "marker",
    "revealer", "doodad", "unitfilter",
}
VALUE_HANDLES = {"color", "abilcmd", "order", "soundlink", "datetime"}
HANDLE_TYPES = sorted(NULLABLE_HANDLES | VALUE_HANDLES)

# Per-type literal constructor grammar (wire value -> Galaxy expression).
# `id:<int>` always means handle-registry lookup for NULLABLE handles.
HANDLE_CTOR = {
    "unitgroup": {"empty": "UnitGroupEmpty()"},
    "point": {"xy": "Point({a0}, {a1})"},
    "region": {"entire_map": "RegionEntireMap()"},
    "playergroup": {"empty": "PlayerGroupEmpty()", "all": "PlayerGroupAll()"},
    "timer": {"create": "TimerCreate()"},
    # 【2026-08-08 真机根因，勿改回】曾写成臆造的 `RevealerCreate(...)`。Galaxy 里
    # 根本没有这个 native（真名 `VisRevealerCreate(int player, region area)`）。
    # 未定义 native 调用 = 编译失败 = SC2 静默丢弃整个 MapScript。
    "revealer": {"create": "VisRevealerCreate({a0}, RegionEntireMap())"},
    "unitfilter": {"zero": "UnitFilter(0, 0, 0, 0)"},
    "color": {"rgb": "Color({a0}, {a1}, {a2})"},
    "abilcmd": {"cmd": "AbilityCommand({a0}, {a1})"},
    "order": {"abilcmd": "Order(AbilityCommand({a0}, {a1}))", "cmd": "Order(AbilityCommand({a0}, 0))"},
    "soundlink": {"link": "SoundLink({a0}, {a1})"},
    # 【2026-08-08 真机根因，勿改回】曾写成臆造的 `DateTime(y,m,d,h,mi,s)`。Galaxy
    # 没有 y/m/d 构造器，只有 `IntToDateTime(int epoch)`（配套读取器是
    # GetDateTimeYear/Month/... 与 DateTimeToInt）。改用 epoch 语法：`epoch:<int>`。
    "datetime": {"epoch": "IntToDateTime({a0})"},
}
HANDLE_ERRORS = {"HANDLE_NOT_FOUND", "HANDLE_INVALID", "HANDLE_TABLE_FULL"}

GEN_MARKER_OPEN = f"// ==== BEGIN {MARKER} ===="
GEN_MARKER_CLOSE = f"// ==== END {MARKER} ===="


def gx_str(value: str) -> str:
    """Galaxy string literal (escape backslash and double quote)."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def json_esc(text: str) -> str:
    """Escape a runtime string for embedding in a JSON payload."""
    out = text.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\n", "\\n").replace("\r", "\\r").replace("\t", "\\t")
    return out


def classify(ttype: str) -> str:
    if ttype in BASIC_TYPES:
        return "basic"
    if ttype == FUNCREF_TYPE:
        return "funcref"
    if ttype.startswith("structref<"):
        return "structref"
    if ttype in HANDLE_TYPES:
        return "handle"
    return "unknown"


def arg_wire_type(ttype: str) -> str:
    if ttype == "int" or ttype == "bool":
        return "integer"
    if ttype == "fixed":
        return "fixed"
    return "string"


def arg_registry_type(ttype: str) -> str:
    if ttype in ("int", "bool"):
        return "integer"
    if ttype == "fixed":
        return "fixed"
    return "string"


# ---------------------------------------------------------------------------
# Invoke plan
# ---------------------------------------------------------------------------

# GEN-SELF-001: the vibe kernel injects its own .galaxy files into the packages
# it instruments, so a re-scanned function catalog feeds the kernel's own symbols
# straight back into the callable plan. That is not just noise:
#   * `libVibeInvoke_gf_Dispatch` as a gen.<id> adapter makes dispatch reentrant;
#   * `libVibeKernel_gf_WriteBankKey` would let the Host rewrite the RPC bank and
#     forge responses, bypassing the whitelist entirely.
# The kernel's surface is the RPC contract, never a generated adapter target.
VIBE_OWN_BASENAMES = {
    "LibVibeKernel.galaxy",
    "LibVibeKernel_h.galaxy",
    "LibVibeHandles.galaxy",
    "LibVibeHandles_h.galaxy",
}
VIBE_OWN_PREFIXES = ("LibVibeInvoke",)


def is_vibe_own_file(path: str) -> bool:
    normalized = path.replace("\\", "/")
    if "/generated/" in normalized:
        return True
    base = normalized.rsplit("/", 1)[-1]
    return base in VIBE_OWN_BASENAMES or base.startswith(VIBE_OWN_PREFIXES)


def load_owned_entries() -> list[dict]:
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    return [
        e for e in data["functions"]
        if e.get("source_id") == "cmre-owned-project" and not is_vibe_own_file(e["path"])
    ]


def package_of(path: str) -> str:
    """Return the owning `.SC2Mod` / `.SC2Map` package prefix of a catalog path.

    `Mods/CMRE/CMRE_Core_Base.SC2Mod/Base.SC2Data/x.galaxy` -> `Mods/CMRE/CMRE_Core_Base.SC2Mod`
    `Mods/kit_mutations.SC2Mod/Base.SC2Data/x.galaxy`       -> `Mods/kit_mutations.SC2Mod`
    `Maps/亡者之夜.SC2Map/MapScript.galaxy`                  -> `Maps/亡者之夜.SC2Map`

    The old fixed "first three segments" rule mis-bucketed single-level mods
    (it returned `Mods/kit_mutations.SC2Mod/Base.SC2Data`), which made the
    dependency scoping below impossible to express. Anchoring on the package
    suffix is both correct and depth-independent.
    """
    parts = path.replace("\\", "/").split("/")
    for index, segment in enumerate(parts):
        if segment.endswith(".SC2Mod") or segment.endswith(".SC2Map"):
            return "/".join(parts[: index + 1])
    return parts[0]


def top_dir(path: str) -> str:
    return package_of(path)


# ---------------------------------------------------------------------------
# VIBE_GEN_004 — 不可调用符号过滤（2026-08-08 真机二分坐实）
# ---------------------------------------------------------------------------
# 真机证据链：
#   shard 二分  1..2 PASS / 1..3 FAIL           -> 首个坏 shard = 03
#   adapter 二分 801-1015 PASS / 801-1016 FAIL  -> 首个坏 adapter = Call#1016
#   Call#1016 = `CMPE_PlayerEvent_Proto(lv_p0);`
#   目标声明   = cm_pointer_events_h.galaxy:3 `void CMPE_PlayerEvent_Proto(int);`
#                cm_pointer_events_h.galaxy:4 `typedef funcref<CMPE_PlayerEvent_Proto> ...`
# 这是 Galaxy 的 **funcref 签名模板**惯例：原型故意没有实现体，只用来给
# `typedef funcref<>` 提供签名。**调用它 = 编译失败 = SC2 静默丢弃整个 MapScript**。
#
# 反面教训（别把判据写成"catalog 里没有 has_body"）：
#   `AIChooseNextLateGameBuild` / `AINeedsDefending` / `AttackStateName` 等
#   MeleeAI.galaxy 里的前置声明同样 has_body=False，但它们在**同文件内被调用**，
#   实现体来自未 vendored 的暴雪基础库 —— 真机 shard01（含 gen.75 / gen.286 /
#   gen.681）已 PASS，证明"只有原型"本身并不致命。
#
# 因此判据是两级的：
#   1) 硬排除：名字出现在 `typedef funcref<NAME>` 里 -> 签名模板，永不可调用。
#   2) 兜底排除（fail-closed）：无实现体、非 native、且**全源零调用点** ->
#      没有任何证据表明该符号能在编译单元里解析，宁可不生成。
# 影响面（2026-08-08 实测）：全局排除 110 个，亡者之夜 bundle 只掉 1 个
# （正是 Call#1016），零可用能力损失。
# 静态门禁对应体检项：closure_doctor.py 形态 K（_check_protoonly_calls）。

RE_FUNCREF_TYPEDEF = re.compile(r"typedef\s+funcref\s*<\s*(\w+)\s*>")


def _source_galaxy_texts() -> dict[str, str]:
    """All vendored `.galaxy` sources, excluding our own generated adapters."""
    texts: dict[str, str] = {}
    for path in SOURCE_ROOT.rglob("*.galaxy"):
        rel = path.relative_to(SOURCE_ROOT).as_posix()
        if "/generated/" in rel:
            continue
        texts[rel] = path.read_text(encoding="utf-8", errors="replace")
    return texts


def detect_uncallable(entries: list[dict]) -> tuple[set[str], set[str]]:
    """Return (funcref_signature_templates, proto_only_unresolved) name sets."""
    by_name: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_name[e["name"]].append(e)

    texts = _source_galaxy_texts()
    line_cache: dict[str, list[str]] = {}

    def decl_line(path: str, line: int) -> str:
        if path not in line_cache:
            line_cache[path] = texts.get(path, "").splitlines()
        lines = line_cache[path]
        return lines[line - 1] if 0 < line <= len(lines) else ""

    templates: set[str] = set()
    for text in texts.values():
        templates.update(RE_FUNCREF_TYPEDEF.findall(text))

    unresolved: set[str] = set()
    for name, group in by_name.items():
        if any(e["has_body"] for e in group):
            continue
        if any(decl_line(e["path"], e["line"]).lstrip().startswith("native") for e in group):
            continue  # engine native: no body by design, always callable
        declared_at = {(e["path"], e["line"]) for e in group}
        pattern = re.compile(r"(?<!\w)" + re.escape(name) + r"\s*\(")
        called = False
        for path, text in texts.items():
            for match in pattern.finditer(text):
                if (path, text.count("\n", 0, match.start()) + 1) in declared_at:
                    continue  # the declaration itself, not a call
                called = True
                break
            if called:
                break
        if not called:
            unresolved.add(name)
    return templates, unresolved


# ---------------------------------------------------------------------------
# VIBE_GEN_005 — static（文件局部）函数不可跨文件调用（2026-08-08 真机二分坐实）
# ---------------------------------------------------------------------------
# 真机证据链（修掉 VIBE_GEN_004 之后的第二个坑）：
#   shard 二分   1..6 PASS / 1..7 FAIL          -> 首个坏 shard = 07
#   adapter 二分 2401-2472 PASS / 2401-2473 FAIL -> 首个坏 adapter = Call#2473
#   Call#2473 = `CallDownMule(lv_p0, lv_p1);`
#   目标声明  = tactterrai.galaxy:971 `static bool CallDownMule (int, unit) {`
#
# Galaxy 的 `include` **不是** C 式文本内联：每个 .galaxy 是独立编译单元，
# 普通符号跨文件可见，但 `static` 把符号限死在**定义它的那个文件里**。
# 我们生成的 adapter 住在 LibVibeInvoke_NN.galaxy，调用别的文件的 static 函数
# = 未定义符号 = 编译失败 = SC2 静默丢弃整个 MapScript。
#
# catalog 早就有 `static` 字段，只是生成器一直没用（本次补上）。
# 影响面（2026-08-08 实测）：全库 5 个，亡者之夜 bundle 4 个，最小 id 正是 2473 —
# 与真机二分阈值逐位吻合。
# 静态门禁对应体检项：closure_doctor.py 形态 L（_check_cross_file_static_calls）。


def detect_static_only(entries: list[dict]) -> set[str]:
    """Names whose *every* implementation is `static` ⇒ not callable cross-file."""
    by_name: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_name[e["name"]].append(e)
    result: set[str] = set()
    for name, group in by_name.items():
        bodies = [e for e in group if e["has_body"]]
        if bodies and all(e.get("static") for e in bodies):
            result.add(name)
    return result


# --- VIBE_GEN_006 -----------------------------------------------------------
# MapScript 生命周期入口：**永不导出**。两条独立理由，任一条都足以否决。
#
# 1) 编译期（这才是致命的那条）。注入管线在 `MapScript.galaxy:20` 挂载 invoke 层，
#    并在挂载点之前补一块前置原型（mpq_build_gen_map.prepend_forward_protos）。
#    那块原型**刻意跳过**这 4 个名字（`skip = {...}`，见该函数）—— 于是
#    `InitGlobals()` 的定义在第 470 行、调用点在第 20 行 ⇒ use-before-declare
#    ⇒ 编译错误 ⇒ SC2 **静默丢弃整个 MapScript**。
#    真机二分：shard07 `2474-2513 PASS / 2474-2514 FAIL`，Call#2514 恰是
#    `InitGlobals();`；同 shard 另有 InitLibs/InitMap/InitTriggers 三个同类。
#
# 2) 语义。就算能编译，运行期 RPC 调 `InitGlobals()` 会把全部全局变量重置回初值、
#    `InitTriggers()` 会把所有触发器再注册一遍 —— 这是拿整局存档换一次调用，
#    没有任何合理用例。fail-closed 排除，零能力损失。
#
# 一般化教训：**导出清单与前置原型清单必须同源**。任何被原型块跳过、却仍被导出的
# MapScript 本体函数，都是一颗静默丢弃的定时炸弹。
# 静态门禁对应体检项：closure_doctor.py 形态 E+（_check_late_decls 的调用点分支）。
MAPSCRIPT_LIFECYCLE = {"InitMap", "InitLibs", "InitGlobals", "InitTriggers"}

DEP_FILE_RE = re.compile(r"file:([^<,\"]+)")


def read_document_info_deps(package_rel: str) -> list[str]:
    """Direct `file:` dependencies declared in a package's DocumentInfo (XML)."""
    info = SOURCE_ROOT / package_rel / "DocumentInfo"
    if not info.is_file():
        return []
    raw = info.read_bytes()
    text = ""
    for encoding in ("utf-8", "utf-16", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    block = re.search(r"<Dependencies>(.*?)</Dependencies>", text, re.S)
    if not block:
        return []
    return [dep.strip().replace("\\", "/") for dep in DEP_FILE_RE.findall(block.group(1))]


def dependency_closure(package_rel: str) -> set[str]:
    """Transitive `file:` dependency closure of a package, restricted to vendored packages.

    GEN-SCOPE-001: adapters used to be generated from the *whole* catalog for
    *every* map, so e.g. 亡者之夜 got `XMChallenge_*` funcref candidates out of
    `Mods/Commanders/CoreRuntime.SC2Mod`, which it does not depend on. Those
    symbols do not exist in that map's compile unit; Galaxy has no cross
    compile-unit linking, so a single undefined symbol makes SC2 drop the whole
    MapScript silently. Scope must come from the real DocumentInfo closure.

    External deps (bnet-only, e.g. `Mods/StarCoop/StarCoop.SC2Mod`) are not
    vendored here and therefore contribute no catalog symbols — skipping them
    is fail-closed, not a loss.
    """
    seen: set[str] = set()
    stack = [package_rel]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        for dep in read_document_info_deps(current):
            if dep not in seen and (SOURCE_ROOT / dep).is_dir():
                stack.append(dep)
    return seen


def map_of(path: str) -> str:
    parts = path.replace("\\", "/").split("/")
    return parts[1] if parts[0] == "Maps" else ""


def signature(entry: dict) -> str:
    return entry["return_type"] + "(" + ",".join(p["type"] for p in entry["parameters"]) + ")"


def build_plan(entries: list[dict]) -> dict:
    by_name: dict[str, list[dict]] = defaultdict(list)
    for e in entries:
        by_name[e["name"]].append(e)

    # VIBE_GEN_004: never emit an adapter that calls a symbol with no body.
    funcref_templates, proto_unresolved = detect_uncallable(entries)
    # VIBE_GEN_005: never emit an adapter that calls a file-local `static` symbol.
    static_only = detect_static_only(entries)

    functions: list[dict] = []
    excluded: list[dict] = []
    fid = 0
    for name in sorted(by_name):
        group = by_name[name]
        sigs = {signature(e) for e in group}
        if len(sigs) > 1:
            excluded.append({
                "name": name, "reason": "ambiguous_overloads",
                "signatures": sorted(sigs), "declarations": len(group),
            })
            continue
        if name in funcref_templates:
            excluded.append({
                "name": name, "reason": "funcref_signature_template",
                "signatures": sorted(sigs), "declarations": len(group),
            })
            continue
        if name in proto_unresolved:
            excluded.append({
                "name": name, "reason": "proto_only_unresolved",
                "signatures": sorted(sigs), "declarations": len(group),
            })
            continue
        if name in static_only:
            excluded.append({
                "name": name, "reason": "static_file_local",
                "signatures": sorted(sigs), "declarations": len(group),
            })
            continue
        if name in MAPSCRIPT_LIFECYCLE:
            excluded.append({
                "name": name, "reason": "mapscript_lifecycle",
                "signatures": sorted(sigs), "declarations": len(group),
            })
            continue
        # Prefer a body definition, then Mods copies, then earliest location.
        rep = sorted(group, key=lambda e: (not e["has_body"], not e["path"].startswith("Mods/"), e["path"], e["line"]))[0]
        fid += 1
        params = []
        for idx, p in enumerate(rep["parameters"]):
            params.append({
                "arg": f"p{idx}", "name": p["name"], "type": p["type"],
                "class": classify(p["type"]),
            })
        unknown = [p for p in params if p["class"] == "unknown"]
        if unknown or classify(rep["return_type"]) == "unknown":
            excluded.append({
                "name": name, "reason": "unsupported_type",
                "signatures": sorted(sigs), "declarations": len(group),
            })
            fid -= 1
            continue
        functions.append({
            "function_id": f"gen.{fid}",
            "id": fid,
            "name": name,
            "kind": rep["kind"],
            "return_type": rep["return_type"],
            "return_class": classify(rep["return_type"]),
            "params": params,
            "declared_at": {"path": rep["path"], "line": rep["line"], "has_body": rep["has_body"]},
            "available_in": sorted({top_dir(e["path"]) for e in group}),
            "declarations": len(group),
        })

    # funcref static table candidates: every void(int) function known to the catalog.
    # VIBE_GEN_004: a bodyless symbol is useless as a funcref target too — resolving
    # to it would jump into nothing at runtime. Compile-wise `return Proto;` is
    # benign (真机 shard01 PASS 时表里就有 CMPE_PlayerEvent_Proto)，删掉只会更安全。
    uncallable = (funcref_templates | proto_unresolved | static_only
                  | MAPSCRIPT_LIFECYCLE)
    # VIBE_GEN_008（2026-08-09 真机取证，勿删）：**MapScript.galaxy 本地函数不能进
    # funcref 静态表**。地图脚本的结构是「include 块（第 1..N 行）→ 地图自有函数原型
    # （N+K 行）」，而 LibVibeInvokeCommon 是被 include 的库，解析时地图本地 `gf_*/gt_*`
    # 原型**尚未出现**。
    #   - 调用 `gf_Foo(x);` 没问题：符号在后续 pass 里解析（全图 287 处这样用，真机通过）。
    #   - 取址 `return gf_Foo;` 会炸：funcref 必须在**解析期**拿到原型去比对
    #     `typedef funcref<...>` 的签名，拿不到就报
    #     "解析返回时出错，可能在行尾缺失分号：';'" ⇒ 脚本读取失败 ⇒ 整图丢弃。
    # 坑点：编译器把错误行号报成**下一行**，极易误判成下一条条目有问题（2026-08-09
    # 就因此误删了两条完全合法的 lib 条目）。定位时一律看报错行的**上一行**。
    map_local_symbols = {
        e["name"] for e in entries
        if e["path"].endswith("MapScript.galaxy")
    }
    uncallable_funcref = uncallable | map_local_symbols
    funcref_candidates = sorted({
        e["name"] for e in entries
        if e["return_type"] == "void" and [p["type"] for p in e["parameters"]] == ["int"]
        and e["name"] not in uncallable_funcref
    })

    maps = sorted({map_of(e["path"]) for e in entries if e["path"].startswith("Maps/")})

    # GEN-SCOPE-001: each map may only see symbols from its own DocumentInfo
    # dependency closure. Anything else is not in that map's compile unit.
    map_scopes: dict[str, list[str]] = {}
    funcref_by_map: dict[str, list[str]] = {}
    bundles = {}
    for m in maps:
        scope = dependency_closure(f"Maps/{m}")
        map_scopes[m] = sorted(scope)
        ids = [f for f in functions if any(d in scope for d in f["available_in"])]
        bundles[m] = {"function_count": len(ids), "shards": (len(ids) + SHARD_SIZE - 1) // SHARD_SIZE}
        funcref_by_map[m] = sorted({
            e["name"] for e in entries
            if e["return_type"] == "void"
            and [p["type"] for p in e["parameters"]] == ["int"]
            and package_of(e["path"]) in scope
            and e["name"] not in uncallable_funcref  # VIBE_GEN_004 / VIBE_GEN_008
        })

    return {
        "generated_by": "generate_invoke_adapters.py",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "stage": "26-full-function-invoke",
        "catalog": CATALOG_PATH.relative_to(ROOT).as_posix(),
        "policy": {
            "arbitrary_reflection": False,
            "static_generated_dispatch": True,
            "inventory_only_functions_are_not_runtime_callable": False,
            "debug_only": True,
        },
        "shard_size": SHARD_SIZE,
        "handle_types": HANDLE_TYPES,
        "handle_ctor_grammar": {k: sorted(v) for k, v in HANDLE_CTOR.items()},
        "summary": {
            "catalog_declarations": len(entries),
            "callable_functions": len(functions),
            "excluded": len(excluded),
            "excluded_funcref_signature_template": len(funcref_templates),
            "excluded_proto_only_unresolved": len(proto_unresolved),
            "excluded_static_file_local": len(static_only),
            "excluded_mapscript_lifecycle": len(MAPSCRIPT_LIFECYCLE),
            # VIBE_GEN_008: map-local symbols stay callable, just never funcref-able.
            "excluded_funcref_map_local": len(map_local_symbols),
            "funcref_candidates": len(funcref_candidates),
            "maps": len(maps),
        },
        "bundles": bundles,
        "functions": functions,
        "excluded": excluded,
        "funcref_candidates": funcref_candidates,
        # GEN-SCOPE-001 evidence: the exact package set each map is allowed to see.
        "map_scopes": map_scopes,
        "funcref_candidates_by_map": funcref_by_map,
    }


# ---------------------------------------------------------------------------
# Galaxy emission helpers
# ---------------------------------------------------------------------------

def emit_arg_decode(fn: dict) -> tuple[list[str], list[str], list[str]]:
    """Return (decl_lines, decode_lines, call_args)."""
    decls, decodes, call_args = [], [], []
    for p in fn["params"]:
        arg, ttype, cls = p["arg"], p["type"], p["class"]
        key = gx_str("arg_" + arg)
        if cls == "basic":
            if ttype == "int":
                decls.append(f"    int lv_{arg};")
                decodes.append(f"    lv_{arg} = libVibeKernel_gf_ArgsGetInt(argsJson, {key});")
            elif ttype == "bool":
                decls.append(f"    bool lv_{arg};")
                decodes.append(f"    lv_{arg} = (libVibeKernel_gf_ArgsGetInt(argsJson, {key}) != 0);")
            elif ttype == "fixed":
                decls.append(f"    fixed lv_{arg};")
                decodes.append(f"    lv_{arg} = libVibeKernel_gf_ArgsGetFixed(argsJson, {key});")
            elif ttype == "string":
                decls.append(f"    string lv_{arg};")
                decodes.append(f"    lv_{arg} = libVibeKernel_gf_ArgsGet(argsJson, {key});")
            else:  # text
                decls.append(f"    text lv_{arg};")
                decodes.append(f"    lv_{arg} = StringToText(libVibeKernel_gf_ArgsGet(argsJson, {key}));")
            call_args.append(f"lv_{arg}")
        elif cls == "funcref":
            decls.append(f"    {FUNCREF_TYPE} lv_{arg};")
            decodes.append(f"    lv_{arg} = libVibeInvoke_gf_ResolveFuncref(libVibeKernel_gf_ArgsGet(argsJson, {key}));")
            decodes.append(f"    if (lv_{arg} == null) {{ return libVibeInvoke_gf_Error({gx_str('FUNCREF_UNKNOWN')}, {gx_str('p' + str(p['arg'][1:]))}); }}")
            call_args.append(f"lv_{arg}")
        elif cls == "structref":
            decls.append(f"    int lv_{arg}_id;")
            decls.append(f"    {STRUCT_CTYPE} lv_{arg};")
            decodes.append(f"    lv_{arg}_id = libVibeKernel_gf_ArgsGetInt(argsJson, {key});")
            decodes.append(f"    if (!libVibeHandles_gf_Has_{STRUCT_CTYPE}(lv_{arg}_id)) {{ return libVibeInvoke_gf_Error({gx_str('HANDLE_NOT_FOUND')}, {key}); }}")
            decodes.append(f"    lv_{arg} = libVibeHandles_gf_Get_{STRUCT_CTYPE}(lv_{arg}_id);")
            call_args.append(f"lv_{arg}")
        else:  # handle
            decls.append(f"    string lv_{arg}_s;")
            decls.append(f"    {ttype} lv_{arg};")
            decodes.append(f"    lv_{arg}_s = libVibeKernel_gf_ArgsGet(argsJson, {key});")
            decodes.extend(emit_handle_resolve(ttype, arg))
            call_args.append(f"lv_{arg}")
    return decls, decodes, call_args


def emit_handle_resolve(ttype: str, arg: str) -> list[str]:
    """Decode lv_<arg>_s into lv_<arg> of handle type, with structured errors.

    Galaxy semantics: StringFind is 1-based (-1 absent); StringSub(s,a,b) is
    1-based with inclusive end (mirrors LibVibeKernel_gf_ArgsGet).
    """
    a, s = f"lv_{arg}", f"lv_{arg}_s"
    err_nf, err_inv = gx_str("HANDLE_NOT_FOUND"), gx_str("HANDLE_INVALID")
    lines: list[str] = []
    if ttype == "unit":
        lines += [
            f"    if (StringSub({s}, 1, 4) == \"tag:\") {{",
            f"        {a} = libVibeKernel_gf_FindUnitByTag(StringToInt(StringSub({s}, 5, StringLength({s}))));",
            f"    }} else if (StringSub({s}, 1, 3) == \"id:\") {{",
            f"        {a} = libVibeHandles_gf_Get_unit(StringToInt(StringSub({s}, 4, StringLength({s}))));",
            f"    }} else {{",
            f"        return libVibeInvoke_gf_Error({err_inv}, {gx_str(arg)});",
            f"    }}",
            f"    if ({a} == null) {{ return libVibeInvoke_gf_Error({err_nf}, {gx_str(arg)}); }}",
        ]
        return lines
    if ttype in VALUE_HANDLES:
        # Value handles: literal construction only (they cannot be null).
        branches = []
        for form, tmpl in HANDLE_CTOR[ttype].items():
            body = [f"        {a} = " + ctor_expr_typed(ttype, form, tmpl, s) + ";"]
            branches.append((form, body))
        first, *rest = branches
        lines.append(f"    if (StringSub({s}, 1, {len(first[0]) + 1}) == \"{first[0]}:\") {{")
        lines.extend(first[1])
        for form, body in rest:
            lines.append(f"    }} else if (StringSub({s}, 1, {len(form) + 1}) == \"{form}:\") {{")
            lines.extend(body)
        lines.append("    } else {")
        lines.append(f"        return libVibeInvoke_gf_Error({err_inv}, {gx_str(arg)});")
        lines.append("    }")
        return lines
    # NULLABLE registry handles: id:<int> or literal ctor forms.
    lines.append(f"    if (StringSub({s}, 1, 3) == \"id:\") {{")
    lines.append(f"        {a} = libVibeHandles_gf_Get_{ttype}(StringToInt(StringSub({s}, 4, StringLength({s}))));")
    ctors = HANDLE_CTOR.get(ttype, {})
    for form, tmpl in ctors.items():
        lines.append(f"    }} else if (StringSub({s}, 1, {len(form) + 1}) == \"{form}:\") {{")
        lines.append(f"        {a} = " + ctor_expr_typed(ttype, form, tmpl, s) + ";")
    lines.append("    } else {")
    lines.append(f"        return libVibeInvoke_gf_Error({err_inv}, {gx_str(arg)});")
    lines.append("    }")
    lines.append(f"    if ({a} == null) {{ return libVibeInvoke_gf_Error({err_nf}, {gx_str(arg)}); }}")
    return lines


# 【VIBE_GEN_003 — 2026-08-09 真机二分坐实，勿改回启发式】
# 每个 ctor 槽位的目标类型必须**逐条对齐 native 真实签名**，不能靠"除了 X 都是 int"
# 这类启发式。以下签名全部取自 core.sc2mod/.../TriggerLibs/natives.galaxy：
#     native point     Point            (fixed x, fixed y);                    L2842
#     native color     Color            (fixed r, fixed g, fixed b);           L943
#     native abilcmd   AbilityCommand   (string inAbil, int inCmdIndex);       L2212
#     native order     Order            (abilcmd inAbilCmd);                   L2224
#     native soundlink SoundLink        (string soundId, int soundIndex);      L3174
#     native datetime  IntToDateTime    (int epoch);                           L1376
#     native revealer  VisRevealerCreate(int player, region area);             L5219
#     native unitfilter UnitFilter      (int, int, int, int);                  L4586
# 事故复盘：旧实现只给 soundlink 槽 0 开了 string 例外，abilcmd/order 的槽 0
# （技能链接名，string）被兜底成 `StringToInt(...)` → 类型不匹配 → 编译错误 →
# SC2 **静默丢弃整个 MapScript**（无 ScriptError、无日志）。因为 Call#66 是第一个
# 带 `order` 参数的 adapter，真机二分呈现为「1-65 PASS / 1-66 FAIL」这一干净边界，
# 极易被误读成"嵌套深度上限"。closure(A~I)/arity/type 三层体检**全部漏报**：
# 它们只核对 adapter 直接调用的目标函数，看不进 ctor 模板内层的 native 实参。
CTOR_SLOT_KIND: dict[tuple[str, int], str] = {
    ("point", 0): "fixed", ("point", 1): "fixed",
    ("color", 0): "fixed", ("color", 1): "fixed", ("color", 2): "fixed",
    ("abilcmd", 0): "string", ("abilcmd", 1): "int",
    ("order", 0): "string", ("order", 1): "int",
    ("soundlink", 0): "string", ("soundlink", 1): "int",
    ("datetime", 0): "int",
    ("revealer", 0): "int",
}


def ctor_expr_typed(ttype: str, form: str, tmpl: str, s: str) -> str:
    """Wrap ctor part extracts with per-slot conversions (see CTOR_SLOT_KIND)."""
    argc = tmpl.count("{a")
    start = len(form) + 2
    expr = tmpl
    for i in range(argc):
        if argc == 1:
            raw = f"StringSub({s}, {start}, StringLength({s}))"
        elif argc == 2:
            raw = f"libVibeInvoke_gf_Part2_{i + 1}({s}, {start})"
        elif argc == 3:
            raw = f"libVibeInvoke_gf_Part3({s}, {start}, {i})"
        else:
            raw = f"libVibeInvoke_gf_Part6({s}, {start}, {i})"
        kind = CTOR_SLOT_KIND.get((ttype, i), "int")
        if kind == "fixed":
            wrapped = f"StringToFixed({raw})"
        elif kind == "string":
            wrapped = raw          # 已是 string，再转就是类型错误
        else:
            wrapped = f"StringToInt({raw})"
        expr = expr.replace("{a%d}" % i, wrapped)
    return expr


def emit_return(fn: dict, call_args: list[str]) -> tuple[list[str], str]:
    """Emit the call + response building. Returns (lines, extra_decls)."""
    name, rtype, rcls = fn["name"], fn["return_type"], fn["return_class"]
    args_txt = ", ".join(call_args)
    lines: list[str] = []
    if rtype == "void":
        lines.append(f"    {name}({args_txt});")
        lines.append("    return libVibeInvoke_gf_Ok(\"void\", \"\");")
        return lines, []
    decls = []
    if rcls == "basic":
        decls.append(f"    {rtype} lv_ret;")
        lines.append(f"    lv_ret = {name}({args_txt});")
        if rtype == "int":
            lines.append('    return libVibeInvoke_gf_Ok("int", IntToString(lv_ret));')
        elif rtype == "bool":
            decls.append("    string lv_rets;")
            lines.append('    lv_rets = "false";')
            lines.append('    if (lv_ret) { lv_rets = "true"; }')
            lines.append('    return libVibeInvoke_gf_Ok("bool", lv_rets);')
        elif rtype == "fixed":
            # 【VIBE_GEN_001 · 勿改回单参】Galaxy 原生签名是
            #     string FixedToString(fixed f, int precision);
            # 单参调用 = 元数不匹配 = 编译错误 ⇒ SC2 **静默丢弃整个 MapScript**
            # （无 ScriptError、无日志，表现为内核从未注册 / bank_keys=0）。
            # 2026-08-09 真机二分取证：shard=none PASS、shard=01 FAIL；
            # arity_doctor 定位到本行产出的 99 处单参调用（横跨 14 个 shard）。
            # c_fixedPrecisionAny = 按需精度，与暴雪官方战役 MapScript 用法一致。
            lines.append('    return libVibeInvoke_gf_Ok("fixed", '
                         'FixedToString(lv_ret, c_fixedPrecisionAny));')
        elif rtype == "string":
            lines.append('    return libVibeInvoke_gf_Ok("string", libVibeInvoke_gf_JsonEscape(lv_ret));')
        else:  # text
            lines.append('    return libVibeInvoke_gf_Ok("text", libVibeInvoke_gf_JsonEscape(TextToString(lv_ret)));')
        return lines, decls
    if rcls == "handle":
        decls.append(f"    {rtype} lv_ret;")
        decls.append("    int lv_ret_id;")
        lines.append(f"    lv_ret = {name}({args_txt});")
        if rtype in VALUE_HANDLES:
            lines.append('    return libVibeInvoke_gf_OkHandle("' + rtype + '", -1);')
        elif rtype == "unit":
            lines.append("    lv_ret_id = -1;")
            lines.append("    if (lv_ret != null) { lv_ret_id = libVibeHandles_gf_Acquire_unit(lv_ret); }")
            lines.append('    return libVibeInvoke_gf_OkHandle("unit", lv_ret_id);')
        else:
            lines.append("    lv_ret_id = -1;")
            lines.append(f"    if (lv_ret != null) {{ lv_ret_id = libVibeHandles_gf_Acquire_{rtype}(lv_ret); }}")
            lines.append(f'    return libVibeInvoke_gf_OkHandle("{rtype}", lv_ret_id);')
        return lines, decls
    if rcls == "funcref":
        decls.append(f"    {FUNCREF_TYPE} lv_ret;")
        decls.append("    string lv_rets;")
        lines.append(f"    lv_ret = {name}({args_txt});")
        lines.append('    lv_rets = "opaque";')
        lines.append('    if (lv_ret == null) { lv_rets = ""; }')
        lines.append('    return libVibeInvoke_gf_Ok("funcref", lv_rets);')
        return lines, decls
    # structref
    decls.append(f"    {STRUCT_CTYPE} lv_ret;")
    decls.append("    int lv_ret_id;")
    lines.append(f"    lv_ret = {name}({args_txt});")
    lines.append(f"    lv_ret_id = libVibeHandles_gf_Acquire_{STRUCT_CTYPE}(lv_ret);")
    lines.append(f'    return libVibeInvoke_gf_OkHandle("{STRUCT_CTYPE}", lv_ret_id);')
    return lines, decls


def emit_adapter(fn: dict) -> list[str]:
    # Struct values are opaque to the Bank transport and cannot be copied by
    # value in Galaxy. Preserve the catalog entry for truthful accounting, but
    # emit a fail-closed adapter instead of source that SC2 cannot compile.
    struct_param = any(p["class"] == "structref" for p in fn["params"])
    if struct_param or fn["return_class"] == "structref":
        expected = ",".join(p["arg"] for p in fn["params"])
        detail = "structref_parameter" if struct_param else "structref_return"
        out = [
            f"// gen.{fn['id']} {fn['name']} ({fn['kind']}) @ {fn['declared_at']['path']}:{fn['declared_at']['line']}",
            f"// Stage 26: structref adapter intentionally neutralized ({detail}).",
            f"string libVibeInvoke_gf_Call{fn['id']}(string argsJson) {{",
        ]
        if fn["params"]:
            out.append(f"    if (libVibeKernel_gf_ArgsGet(argsJson, \"arg_names\") != \"{expected}\") {{ return libVibeInvoke_gf_Error(\"INVALID_ARGS\", \"arg_names\"); }}")
        out.append(f"    return libVibeInvoke_gf_Error(\"SYMBOL_NOT_IN_MAP\", \"{detail}\");")
        out.append("}")
        return out
    decls, decodes, call_args = emit_arg_decode(fn)
    ret_lines, ret_decls = emit_return(fn, call_args)
    expected = ",".join(p["arg"] for p in fn["params"])
    out = [
        f"// gen.{fn['id']} {fn['name']} ({fn['kind']}) @ {fn['declared_at']['path']}:{fn['declared_at']['line']}",
        f"string libVibeInvoke_gf_Call{fn['id']}(string argsJson) {{",
    ]
    out += decls + ret_decls
    if fn["params"]:
        out.append(f"    if (libVibeKernel_gf_ArgsGet(argsJson, \"arg_names\") != \"{expected}\") {{ return libVibeInvoke_gf_Error(\"INVALID_ARGS\", \"arg_names\"); }}")
    out += decodes
    out += ret_lines
    out.append("}")
    return out


# ---------------------------------------------------------------------------
# Per-map bundle emission
# ---------------------------------------------------------------------------

def emit_shard_prototypes(shard_fns: list[dict], idx: int) -> str:
    lines = [
        f"// LibVibeInvoke_{idx:02d}_h.galaxy — generated by Stage 26 (do not edit)",
        f"// Shard {idx}: gen ids {shard_fns[0]['id']}..{shard_fns[-1]['id']}",
        "",
    ]
    for fn in shard_fns:
        lines.append(f"string libVibeInvoke_gf_Call{fn['id']}(string argsJson);")
    return "\n".join(lines) + "\n"


def emit_shard_body(shard_fns: list[dict], idx: int, map_name: str) -> str:
    lines = [
        f"// LibVibeInvoke_{idx:02d}.galaxy — generated by Stage 26 (do not edit)",
        f"// Map bundle: {map_name}; shard {idx} ({len(shard_fns)} adapters)",
        f'include "LibVibeInvoke_{idx:02d}_h"',
        "",
    ]
    for fn in shard_fns:
        lines.extend(emit_adapter(fn))
        lines.append("")
    return "\n".join(lines)


def emit_dispatch_header() -> str:
    return "\n".join([
        "// LibVibeInvokeDispatch_h.galaxy — generated by Stage 26 (do not edit)",
        "string libVibeInvoke_gf_Dispatch(int functionId, string argsJson);",
        "",
    ])


def emit_dispatch(shard_ranges: list[tuple[int, int, int]], map_name: str, fn_count: int, tier: int | None = None) -> str:
    """两级整数区间分派：顶层按全局 id 区间路由，片内 if 链精确匹配。

    分片必须按全局 id 区间切分（而非 available 列表位置），否则每图
    的 available 子集存在空洞时顶层路由会错片。tier 用于分档放量：
    仅挂载 lo <= tier 的片，超出 tier 的 id 结构化拒绝。
    """
    name = f"LibVibeInvokeDispatch{'_tier' + str(tier) if tier else ''}.galaxy"
    suffix = f" (rollout tier <= {tier})" if tier else ""
    lines = [
        f"// {name} — generated by Stage 26 (do not edit)",
        f"// Map bundle: {map_name}; {fn_count} adapters across {len(shard_ranges)} shards{suffix}",
        'include "LibVibeInvokeDispatch_h"',
    ]
    active = [r for r in shard_ranges if tier is None or r[1] <= tier]
    for idx, lo, hi in active:
        lines.append(f'include "LibVibeInvoke_{idx:02d}_h"')
    lines += [
        "",
        "string libVibeInvoke_gf_Dispatch(int functionId, string argsJson) {",
    ]
    if tier is not None:
        lines.append(f'    if (functionId > {tier}) {{ return libVibeInvoke_gf_Error("FUNCTION_NOT_IN_MAP", IntToString(functionId)); }}')
    # 同 VIBE_GEN_002：一律扁平 early-return。顶层目前只有 ~30 个 shard 分支、
    # 尚未触及 65 层上限，但分片数随导出规模增长，留着 else-if 链等于埋雷。
    for idx, lo, hi in active:
        lines.append(f"    if (functionId >= {lo} && functionId <= {hi}) {{")
        lines.append(f"        return libVibeInvoke_gf_DispatchShard{idx:02d}(functionId, argsJson);")
        lines.append("    }")
    lines += [
        f'    return libVibeInvoke_gf_Error("FUNCTION_NOT_IN_MAP", IntToString(functionId));',
        "}",
        "",
    ]
    return "\n".join(lines)


def emit_shard_dispatch(shard_fns: list[dict], idx: int) -> str:
    lo = shard_fns[0]["id"]
    hi = shard_fns[-1]["id"]
    # Append the shard dispatch into the shard body file instead of a separate
    # file to halve the include count; the prototype lives in the _h header.
    #
    # 【VIBE_GEN_002 — 防御性扁平化。注意：嵌套深度上限是**未证实的假说**】
    # 起因：真机二分得「1-65 分支 PASS / 1-66 分支 FAIL」，当时按
    # `} else if (c) {` == `else { if (c) {...} }`（N 分支 = N 层嵌套）解释为
    # 「Galaxy 嵌套硬上限 65」。改扁平后 1-66 **仍 FAIL** → 该解释被证伪，
    # 真因是 VIBE_GEN_003（Call#66 是第一个带 order 参数的 adapter，
    # ctor 槽位类型错配），两者恰好预测同一边界，属巧合共解释。
    # 扁平 early-return 仍然保留：嵌套深度恒为 1、与分支数无关，代价为零，
    # 且把「深度」这一变量从后续二分中彻底消掉，避免再次混淆归因。
    lines = [
        "",
        f"string libVibeInvoke_gf_DispatchShard{idx:02d}(int functionId, string argsJson) {{",
    ]
    for fn in shard_fns:
        lines.append(f"    if (functionId == {fn['id']}) {{ return libVibeInvoke_gf_Call{fn['id']}(argsJson); }}")
    lines += [
        f'    return libVibeInvoke_gf_Error("FUNCTION_NOT_IN_MAP", IntToString(functionId));',
        "}",
    ]
    return "\n".join(lines)


# Galaxy 原生 StringReplace 的签名是
#     string StringReplace(string s, string replaceWith, int start, int end)
# —— 按 1-based 下标区间替换，**不是** JS 风格的 find/replace。
# Stage 26 早期生成的 `StringReplace(s, "\\", "\\\\", true)` 是 4 参 find/replace 写法，
# 类型和语义都不对，会让整个 LibVibeInvokeCommon.galaxy 编译失败，进而拖垮
# 整个 MapScript 编译单元（Galaxy 单编译单元、无跨单元链接）。
# 这里改为逐字符扫描：语义明确、可编译、无原生签名依赖。
JSON_ESCAPE_GALAXY = r'''string libVibeInvoke_gf_JsonEscape(string s) {
    string res;
    string ch;
    int i;
    int n;
    res = "";
    n = StringLength(s);
    for (i = 1; i <= n; i += 1) {
        ch = StringSub(s, i, i);
        if (ch == "\\") {
            res = res + "\\\\";
        } else if (ch == "\"") {
            res = res + "\\\"";
        } else if (ch == "\n") {
            res = res + "\\n";
        } else if (ch == "\r") {
            res = res + "\\r";
        } else if (ch == "\t") {
            res = res + "\\t";
        } else {
            res = res + ch;
        }
    }
    return res;
}'''


def emit_common(map_name: str, funcref_candidates: list[str]) -> str:
    lines = [
        "// LibVibeInvokeCommon.galaxy — generated by Stage 26 (do not edit)",
        f"// Map bundle: {map_name}; shared adapter helpers",
        "",
        *JSON_ESCAPE_GALAXY.splitlines(),
        "",
        "string libVibeInvoke_gf_Error(string code, string detail) {",
        '    return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "function.invoke", code, "{\\"reason\\":\\"" + code + "\\",\\"detail\\":\\"" + libVibeInvoke_gf_JsonEscape(detail) + "\\"}");',
        "}",
        "",
        # VIBE_INVOKE_010：valueExpr 必须先变成**合法 JSON 字面量**再拼进去。
        # 历史缺陷：void 传 ""（拼出 `"return_value":`）、string/text/funcref 传未加引号
        # 的裸文本（拼出 `"return_value":hello`）—— 两者都是非法 JSON，任何 json.loads
        # 的消费方都会解析失败，把「函数其实跑成功了」误报成「调用失败」。
        # 长期没暴露是因为 tier100 只探过 int/fixed/bool 返回，那三类裸字面量恰好合法。
        # 在 gf_Ok 单点收口而非每个适配器各拼一遍：11676 个适配器，改一处比改一万处安全。
        "string libVibeInvoke_gf_Ok(string retKind, string valueExpr) {",
        "    string lv_json;",
        "    lv_json = valueExpr;",
        '    if (retKind == "void") {',
        '        lv_json = "null";',
        '    } else if (retKind == "string" || retKind == "text" || retKind == "funcref") {',
        '        lv_json = "\\"" + valueExpr + "\\"";',
        "    }",
        '    return libVibeKernel_gf_MakeResponse("result", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "function.invoke", "OK", "{\\"return_kind\\":\\"" + retKind + "\\",\\"return_value\\":" + lv_json + "}");',
        "}",
        "",
        "string libVibeInvoke_gf_OkHandle(string handleType, int handleId) {",
        '    return libVibeKernel_gf_MakeResponse("result", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "function.invoke", "OK", "{\\"return_kind\\":\\"handle\\",\\"handle_type\\":\\"" + handleType + "\\",\\"handle_id\\":" + IntToString(handleId) + "}");',
        "}",
        "",
        "// ctor helpers: extract comma-separated parts of `form:a,b,c` payloads.",
        "// StringFind is 1-based; StringSub(s,a,b) has inclusive end.",
        "string libVibeInvoke_gf_Part2_1(string s, int start) {",
        "    int p1;",
        '    p1 = StringFind(s, ",", true);',
        "    if (p1 <= start) { return \"\"; }",
        "    return StringSub(s, start, p1 - 1);",
        "}",
        "",
        "string libVibeInvoke_gf_Part2_2(string s, int start) {",
        "    int p1;",
        '    p1 = StringFind(s, ",", true);',
        "    if (p1 <= start) { return \"\"; }",
        "    return StringSub(s, p1 + 1, StringLength(s));",
        "}",
        "",
        "string libVibeInvoke_gf_Part3(string s, int start, int index) {",
        "    int p1;",
        "    int p2;",
        '    p1 = StringFind(s, ",", true);',
        "    if (p1 <= start) { return \"\"; }",
        '    p2 = StringFind(StringSub(s, p1 + 1, StringLength(s)), ",", true);',
        "    if (p2 < 1) { return \"\"; }",
        "    p2 = p1 + p2;",
        "    if (index == 0) { return StringSub(s, start, p1 - 1); }",
        "    if (index == 1) { return StringSub(s, p1 + 1, p2 - 1); }",
        "    return StringSub(s, p2 + 1, StringLength(s));",
        "}",
        "",
        "string libVibeInvoke_gf_Part6(string s, int start, int index) {",
        "    int cut;",
        "    int segStart;",
        "    int i;",
        "    string rest;",
        "    segStart = start;",
        '    cut = StringFind(s, ",", true);',
        "    for (i = 0; i < index; i += 1) {",
        "        if (cut < segStart) { return \"\"; }",
        "        segStart = cut + 1;",
        "        rest = StringSub(s, segStart, StringLength(s));",
        '        cut = StringFind(rest, ",", true);',
        "        if (cut >= 1) { cut = segStart + cut - 1; }",
        "    }",
        "    if (cut >= segStart) { return StringSub(s, segStart, cut - 1); }",
        "    return StringSub(s, segStart, StringLength(s));",
        "}",
        "",
        "// funcref 原型 + typedef —— Galaxy 要求 funcref 类型必须「先声明原型函数，",
        "// 再 typedef funcref<原型>」。缺这两行 = 使用未声明类型 = 整个 MapScript",
        "// 编译失败并被 SC2 静默丢弃（无 ScriptError、InitMap 不执行）。",
        "// 该模式与 CMLib 的 CMLib_PlayerVisitor 同构，已真机验证。",
        f"void {FUNCREF_PROTO} (int lp_p0);",
        f"typedef funcref<{FUNCREF_PROTO}> {FUNCREF_TYPE};",
        "",
        "// 【2026-08-08 真机根因，勿删】原型必须配一个实现。Galaxy 里「有声明无实现」",
        "// 是编译期错误 ⇒ SC2 静默丢弃整个 MapScript（无 ScriptError、InitMap 不执行、",
        "// Kernel 永不注册）。旧版只发原型不发实现，导致 gen 图 P0 全灭且难以定位。",
        "// CMLib 的 CMLib_PlayerVisitor_Proto 同样是「_h 声明 + .galaxy 空实现」。",
        f"void {FUNCREF_PROTO} (int lp_p0) {{",
        "}",
        "",
        f"// funcref static table: {len(funcref_candidates)} void(int) candidates",
        f"{FUNCREF_TYPE} libVibeInvoke_gf_ResolveFuncref(string name) {{",
    ]
    for cand in funcref_candidates:
        lines.append(f"    if (name == {gx_str(cand)}) {{ return {cand}; }}")
    lines += [
        "    return null;",
        "}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# LibVibeHandles emission
# ---------------------------------------------------------------------------

HANDLE_CAPACITY = 512
REGISTRY_HANDLE_TYPES = sorted(NULLABLE_HANDLES - {"unit"})


def emit_handles() -> str:
    lines = [
        "// LibVibeHandles.galaxy — generated by Stage 26 (do not edit)",
        "// Runtime handle registry for generated function.invoke adapters.",
        "// unit identity = engine tag (no storage table); all other nullable",
        "// handle types keep an int->handle table with explicit drop/clear.",
        f"const int libVibeHandles_gc_capacity = {HANDLE_CAPACITY};",
        "",
        "// ---- unit (engine tags) ----",
        "int libVibeHandles_gf_Acquire_unit(unit h) {",
        "    if (h == null) { return -1; }",
        "    return UnitGetTag(h);",
        "}",
        "unit libVibeHandles_gf_Get_unit(int id) {",
        "    if (id <= 0) { return null; }",
        "    return libVibeKernel_gf_FindUnitByTag(id);",
        "}",
        "bool libVibeHandles_gf_Has_unit(int id) {",
        "    return libVibeHandles_gf_Get_unit(id) != null;",
        "}",
        "",
    ]
    for ttype in REGISTRY_HANDLE_TYPES:
        var = f"libVibeHandles_gv_{ttype}_table"
        nxt = f"libVibeHandles_gv_{ttype}_cursor"
        lines += [
            f"// ---- {ttype} ----",
            f"{ttype}[{HANDLE_CAPACITY + 1}] {var};",
            f"int {nxt} = 0;",
            f"int libVibeHandles_gf_Acquire_{ttype}({ttype} h) {{",
            "    int i;",
            "    if (h == null) { return -1; }",
            f"    for (i = 1; i <= {HANDLE_CAPACITY}; i += 1) {{",
            f"        if ({var}[i] == null) {{ {var}[i] = h; return i; }}",
            "    }",
            f"    {nxt} += 1;",
            f"    if ({nxt} > {HANDLE_CAPACITY}) {{ {nxt} = 1; }}",
            f"    {var}[{nxt}] = h;",
            f"    return {nxt};",
            "}",
            f"{ttype} libVibeHandles_gf_Get_{ttype}(int id) {{",
            f"    if (id < 1 || id > {HANDLE_CAPACITY}) {{ return null; }}",
            f"    return {var}[id];",
            "}",
            f"bool libVibeHandles_gf_Has_{ttype}(int id) {{",
            f"    if (id < 1 || id > {HANDLE_CAPACITY}) {{ return false; }}",
            f"    return {var}[id] != null;",
            "}",
            f"bool libVibeHandles_gf_Drop_{ttype}(int id) {{",
            f"    if (id < 1 || id > {HANDLE_CAPACITY} || {var}[id] == null) {{ return false; }}",
            f"    {var}[id] = null;",
            "    return true;",
            "}",
            f"void libVibeHandles_gf_Clear_{ttype}() {{",
            "    int i;",
            f"    for (i = 1; i <= {HANDLE_CAPACITY}; i += 1) {{ {var}[i] = null; }}",
            "}",
            f"int libVibeHandles_gf_Count_{ttype}() {{",
            "    int i;",
            "    int n;",
            "    n = 0;",
            f"    for (i = 1; i <= {HANDLE_CAPACITY}; i += 1) {{ if ({var}[i] != null) {{ n += 1; }} }}",
            "    return n;",
            "}",
            "",
        ]
    # structref registry: Galaxy cannot pass/assign struct values by value. Keep
    # only liveness bits so handle.query/drop/clear remain explicit and the
    # generated source never emits an illegal Acquire/Get implementation.
    lines += [
        f"// ---- {STRUCT_CTYPE} (structref liveness only) ----",
        f"bool[{HANDLE_CAPACITY + 1}] libVibeHandles_gv_histogram_used;",
        f"bool libVibeHandles_gf_Has_{STRUCT_CTYPE}(int id) {{",
        f"    if (id < 1 || id > {HANDLE_CAPACITY}) {{ return false; }}",
        "    return libVibeHandles_gv_histogram_used[id];",
        "}",
        f"bool libVibeHandles_gf_Drop_{STRUCT_CTYPE}(int id) {{",
        f"    if (id < 1 || id > {HANDLE_CAPACITY} || !libVibeHandles_gv_histogram_used[id]) {{ return false; }}",
        "    libVibeHandles_gv_histogram_used[id] = false;",
        "    return true;",
        "}",
        f"void libVibeHandles_gf_Clear_{STRUCT_CTYPE}() {{",
        "    int i;",
        f"    for (i = 1; i <= {HANDLE_CAPACITY}; i += 1) {{ libVibeHandles_gv_histogram_used[i] = false; }}",
        "}",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Kernel patching (idempotent, marker-guarded)
# ---------------------------------------------------------------------------

def strip_marker_block(text: str, tag: str) -> str:
    begin = f"// ==== BEGIN {MARKER} {tag} ===="
    end = f"// ==== END {MARKER} {tag} ===="
    start = text.find(begin)
    if start < 0:
        return text
    stop = text.find(end)
    if stop < 0:
        return text
    return text[:start] + text[stop + len(end):].lstrip("\r\n")


def marker_block(tag: str, body: str) -> str:
    begin = f"// ==== BEGIN {MARKER} {tag} ===="
    end = f"// ==== END {MARKER} {tag} ===="
    return f"{begin}\n{body}\n{end}\n"


def insert_before_anchor(text: str, anchor: str, block: str) -> str:
    idx = text.find(anchor)
    if idx < 0:
        raise RuntimeError(f"Stage 26 patch anchor not found: {anchor[:60]!r}")
    return text[:idx] + block + text[idx:]


GEN_INVOKE_BRANCH = """\
    // Stage 26: generated adapter dispatch (gen.<int> function ids).
    if (StringSub(functionId, 1, 4) == "gen.") {
        if (StringToInt(StringSub(functionId, 5, StringLength(functionId))) < 1) {
            return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "function.invoke", "INVALID_ARGS", "{\\"reason\\":\\"function_id_not_numeric\\"}");
        }
        libVibeKernel_gv_stateVersion += 1;
        return libVibeInvoke_gf_Dispatch(StringToInt(StringSub(functionId, 5, StringLength(functionId))), argsJson);
    }
"""

HANDLE_OPS_BRANCH = """\
    } else if (operation == "handle.drop") {
        result = libVibeKernel_gf_HandleHandleDrop(args);
    } else if (operation == "handle.clear") {
        result = libVibeKernel_gf_HandleHandleClear(args);
    } else if (operation == "handle.query") {
        result = libVibeKernel_gf_HandleHandleQuery(args);
"""

# ---------------------------------------------------------------------------
# VIBE-KERNEL-001: handler-abort resilience
#
# Galaxy has no try/catch. A runtime fault inside any handler (invalid catalog
# entry, null handle deref, ...) aborts the *whole trigger thread*. That means:
#   * step 4 `WriteResponseToBank` never runs -> the Host blocks until timeout;
#   * the `while (true)` PollLoop thread dies with it -> the kernel is deaf for
#     the rest of the game.
# Three cooperating fixes, all marker-guarded so re-running this generator
# re-applies them even after someone re-syncs an unpatched kernel mirror:
#   1. pessimistic response  - write HANDLER_ABORTED to response/<id> *before*
#      dispatching, overwrite with the real result on normal return;
#   2. consume-before-dispatch - mark the request id as polled before calling
#      Dispatch so a poison request is never replayed;
#   3. watchdog - an independent Wait loop that never calls Dispatch, watches
#      the poll heartbeat and restarts PollLoop when it stalls.
# ---------------------------------------------------------------------------

KERNEL001_PESSIMISTIC = """\
    // VIBE-KERNEL-001: land a pessimistic response before the handler runs.
    // If the handler aborts the trigger thread, the Host still sees a terminal
    // HANDLER_ABORTED instead of blocking until its own timeout.
    libVibeKernel_gf_WriteBankKey("response", requestId,
        libVibeKernel_gf_MakeResponse("error", sessionId, requestId, sequence, operation,
            "HANDLER_ABORTED", "{\\"reason\\":\\"handler_did_not_complete\\"}"));
    libVibeKernel_gf_WriteBankKey("index", "last_dispatch_started", requestId + "|" + operation);

"""

KERNEL001_WATCHDOG_REGISTER = """\
    // VIBE-KERNEL-001: watchdog keeps the transport alive across handler aborts.
    libVibeKernel_gt_Watchdog = TriggerCreate("libVibeKernel_gt_Watchdog_Func");
    TriggerExecute(libVibeKernel_gt_Watchdog, false, true);
    libVibeKernel_gf_WriteBankInt("index", "register_entrypoints_watchdog_done", 1);

"""

KERNEL001_WATCHDOG_FUNC = """\
// ---- VIBE-KERNEL-001 watchdog ----
// Never calls Dispatch, so a faulting handler can never take this thread down.
// Observes the PollLoop heartbeat (gv_bankPollCount); if it stops advancing for
// ~4 seconds the PollLoop thread is presumed dead and gets restarted.
//
// ！！！铁律 VIBE-KERNEL-004（2026-08-10 静态归因 + 真机 A/B 取证）！！！
// watchdog 的诊断写入**必须走模型库**（GalaxyVibeModel），绝不能碰 RPC 库。
//
// 机理：gf_WriteBankInt 内部是 BankSave(gv_bankHandle)，即把内核内存态整份刷回
//       GalaxyVibe.SC2Bank。VIBE_KERNEL_002 已经把 **PollLoop 线程**的写入
//       全部排到 pending_request_id 读取之后，正是为了避免抹掉 Host 刚落盘的请求；
//       但 watchdog 是**同一个 Bank 上的第二个写者**，每 2.0s 一次、
//       与 PollLoop 的读写顺序毫无协调 —— VIBE_KERNEL_002 那条纪律它一天也没遵守过。
//
// 后果：Host 写 pending_request_id 到 PollLoop 下一拍 ReloadBank 之间有 ~0~500ms
//       危险窗；watchdog 周期 2000ms ⇒ 单请求碰撞率 ≈ 250/2000 = 12.5%
//       （真机 n=100 实测 over_2s = 15%，吻合）。被抹掉的请求由 Host 的
//       at-least-once 补发（reassert_sec=2.0）救回来 —— 于是缺陷不表现为「丢」
//       而表现为**延迟按 ~2 秒量子阶梯化**（中位 684ms / p95 4904ms / max 7200ms
//       ≈ 基线 + 1~3 次补发）。补发一直在**掩盖**这个 bug，不是在修它。
//
// 修法：心跳与重启计数改写模型库（VIBE_GEN_007 已做通道隔离，其 BankSave 只刷
//       GalaxyVibeModel.SC2Bank，天然伤不到 RPC 库）。RPC 库的落盘时机仍由
//       VIBE_KERNEL_005 首帧 flush + 各 handler 的响应写入保证，不依赖 watchdog。
bool libVibeKernel_gt_Watchdog_Func(bool testConds, bool runActions) {
    int stalled;
    if (testConds) { return true; }
    if (!runActions) { return true; }

    stalled = 0;
    while (true) {
        Wait(2.0, c_timeGame);
        if (libVibeKernel_gv_bankPollCount == libVibeKernel_gv_watchdogLastSeen) {
            stalled += 1;
        } else {
            stalled = 0;
            libVibeKernel_gv_watchdogLastSeen = libVibeKernel_gv_bankPollCount;
        }
        libVibeKernel_gf_WriteModelBankInt("index", "watchdog_last_seen_poll", libVibeKernel_gv_watchdogLastSeen);
        if (stalled >= 2) {
            stalled = 0;
            libVibeKernel_gv_watchdogRestarts += 1;
            libVibeKernel_gv_pollLoopRunning = false;
            libVibeKernel_gf_WriteModelBankInt("index", "kernel_restart_count", libVibeKernel_gv_watchdogRestarts);
            if (libVibeKernel_gt_PollLoop != null) {
                // 必须异步：同步调用会让 watchdog 自身被 PollLoop 的 while(true) 永久吞掉，
                // 重启一次之后 watchdog 就再也不工作了（自废）。
                TriggerExecute(libVibeKernel_gt_PollLoop, false, false);
            }
        }
    }

    return true;
}
"""

# (source, patched) pairs -- consume the request id *before* dispatching it.
KERNEL001_CONSUME_FIRST: list[tuple[str, str]] = [
    (
        "    response = libVibeKernel_gf_Dispatch(requestJson);\n"
        "    libVibeKernel_gv_lastPolledRequestId = pendingId;\n",
        "    // VIBE-KERNEL-001: consume before dispatch so a poison request is never replayed.\n"
        "    libVibeKernel_gv_lastPolledRequestId = pendingId;\n"
        "    response = libVibeKernel_gf_Dispatch(requestJson);\n",
    ),
    (
        "                response = libVibeKernel_gf_Dispatch(requestJson);\n"
        "                libVibeKernel_gv_lastPolledRequestId = pendingId;\n",
        "                // VIBE-KERNEL-001: consume before dispatch (poison-request guard).\n"
        "                libVibeKernel_gv_lastPolledRequestId = pendingId;\n"
        "                response = libVibeKernel_gf_Dispatch(requestJson);\n",
    ),
]

KERNEL001_HEADER_DECLS = "\n".join([
    "// VIBE-KERNEL-001: watchdog state (see generate_invoke_adapters.py).",
    "trigger libVibeKernel_gt_Watchdog = null;",
    "int libVibeKernel_gv_watchdogLastSeen = -1;",
    "int libVibeKernel_gv_watchdogRestarts = 0;",
    "bool   libVibeKernel_gt_Watchdog_Func(bool testConds, bool runActions);",
])


# 注册完成标记之前的锚点。内核在真机修复轮次里被改写过一次，两种写法都要认：
# 新（当前内核）在前，旧（Stage 26 原始）在后。
REGISTER_DONE_ANCHORS = (
    "    // \u6ce8\u518c\u5b8c\u6210\u6807\u8bb0\u5fc5\u987b\u5199\u5728 PollLoop "
    "\u6d3e\u53d1\u4e4b\u524d\uff08PollLoop \u8fdb\u5165\u540e\u4e0d\u518d\u8fd4\u56de\uff09\u3002",
    "    // \u5199\u5165\u6ce8\u518c\u5b8c\u6210\u6807\u8bb0\uff08\u4f9b Host \u7aef\u9a8c\u8bc1\u89e6\u53d1\u5668\u5df2\u6ce8\u518c\uff09",
)


def _consume_first_invariant_holds(text: str) -> bool:
    """True iff, at every ``Dispatch(requestJson)`` call site, the
    ``lastPolledRequestId`` assignment immediately precedes it (ignoring any
    comment / blank lines in between). That ordering *is* the VIBE-KERNEL-001
    consume-before-dispatch invariant.

    Checking the ordering instead of the exact anchor string makes the
    generator tolerant of hand-merges that re-indent or reword the marker
    comment at the PollLoop site. The PollLoop site uses 8-space indentation
    while this generator's ``KERNEL001_CONSUME_FIRST`` anchors assumed 16, so
    the exact-string match previously returned count==0 and aborted the whole
    Stage 26 regen. With this check the already-merged kernel is recognised as
    fixed and the loop is skipped.
    """
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if "libVibeKernel_gf_Dispatch(requestJson)" not in ln:
            continue
        j = i - 1
        while j >= 0 and (lines[j].strip().startswith("//") or lines[j].strip() == ""):
            j -= 1
        if j < 0:
            return False
        if "libVibeKernel_gv_lastPolledRequestId = pendingId" not in lines[j]:
            return False
    return True


def apply_kernel001(text: str) -> str:
    """Apply the three VIBE-KERNEL-001 fixes to the kernel source (idempotent)."""
    text = strip_marker_block(text, "KERNEL001_PESSIMISTIC")
    text = strip_marker_block(text, "KERNEL001_WATCHDOG_REGISTER")
    text = strip_marker_block(text, "KERNEL001_WATCHDOG")

    text = insert_before_anchor(
        text,
        '    // 3. \u767d\u540d\u5355\u5206\u53d1\n    if (operation == "system.ping") {',
        marker_block("KERNEL001_PESSIMISTIC", KERNEL001_PESSIMISTIC.rstrip("\n")),
    )
    # watchdog 注册块可能已被真机修复轮次**手工合并**进内核源：那边的 marker 名是
    # `VIBE_KERNEL_001_WATCHDOG_REGISTER`，与本生成器的 `STAGE26_FULL_INVOKE
    # KERNEL001_*` 不同名，上面的 strip_marker_block 剥不掉；同时锚点注释也被改写过。
    # 已合并时**绝不能重复注入**——重复的 TriggerCreate/TriggerExecute 与函数重定义
    # 一样会让 SC2 静默丢弃整个 MapScript（无 ScriptError、InitMap 不执行）。
    # 判据用运行时可观测的 bank key，比 marker 名更稳（marker 会改名，key 不会）。
    if "register_entrypoints_watchdog_done" not in text:
        anchor = next((a for a in REGISTER_DONE_ANCHORS if a in text), None)
        if anchor is None:
            raise RuntimeError(
                "Stage 26: register-done anchor not found and watchdog block not "
                "already merged — kernel drifted beyond both known anchors. "
                f"tried={[a.strip()[:40] for a in REGISTER_DONE_ANCHORS]!r}"
            )
        text = insert_before_anchor(
            text,
            anchor,
            marker_block("KERNEL001_WATCHDOG_REGISTER", KERNEL001_WATCHDOG_REGISTER.rstrip("\n")),
        )

    # VIBE-KERNEL-001 (consume-before-dispatch). The kernel may already carry
    # this fix hand-merged with different indentation / comments than our anchors
    # (the PollLoop site uses 8-space indent while the anchors assumed 16). Match
    # the *invariant* (consume assignment immediately precedes Dispatch) and skip
    # when it holds; otherwise fall back to the exact anchor replacement for a
    # pristine kernel.
    if not _consume_first_invariant_holds(text):
        for source, patched in KERNEL001_CONSUME_FIRST:
            if patched in text:
                continue
            if text.count(source) != 1:
                raise RuntimeError(
                    "VIBE-KERNEL-001 consume-before-dispatch anchor is ambiguous or missing: "
                    f"{source.strip()[:60]!r} (count={text.count(source)})"
                )
            text = text.replace(source, patched)

    return text.rstrip("\n") + "\n\n" + marker_block("KERNEL001_WATCHDOG", KERNEL001_WATCHDOG_FUNC.rstrip("\n"))


def apply_kernel001_header(text: str) -> str:
    """Declare the watchdog globals/prototype exactly once, under a marker."""
    text = strip_marker_block(text, "KERNEL001_DECLS")
    # An earlier hand-applied patch may have inserted the same declarations
    # without markers; drop those so the marker block stays the single source.
    keep: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("trigger libVibeKernel_gt_Watchdog") \
                or stripped.startswith("int libVibeKernel_gv_watchdogLastSeen") \
                or stripped.startswith("int libVibeKernel_gv_watchdogRestarts") \
                or stripped.replace(" ", "").startswith("boollibVibeKernel_gt_Watchdog_Func"):
            continue
        keep.append(line)
    text = "\n".join(keep)
    return text.rstrip("\n") + "\n\n" + marker_block("KERNEL001_DECLS", KERNEL001_HEADER_DECLS)


def _mr(kind: str, op: str, code: str, payload: str) -> str:
    """Compose a Galaxy MakeResponse call expression."""
    return (
        f'libVibeKernel_gf_MakeResponse("{kind}", libVibeKernel_gv_currentSession, '
        f'libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "{op}", "{code}", {payload})'
    )


def emit_handle_op_handlers() -> str:
    """Build the handle.query/drop/clear handler bodies programmatically."""
    types = REGISTRY_HANDLE_TYPES + [STRUCT_CTYPE]
    lines: list[str] = ["// ---- Stage 26: generated handle registry operations ----", ""]

    # handle.query
    lines += [
        "string libVibeKernel_gf_HandleHandleQuery(string argsJson) {",
        "    string handleType;",
        "    int handleId;",
        "    string aliveS;",
        '    handleType = libVibeKernel_gf_ArgsGet(argsJson, "handle_type");',
        '    handleId = libVibeKernel_gf_ArgsGetInt(argsJson, "handle_id");',
        '    if (handleType == "unit") {',
        '        aliveS = "false";',
        '        if (libVibeHandles_gf_Has_unit(handleId)) { aliveS = "true"; }',
        '        return ' + _mr("result", "handle.query", "OK",
                                r'"{\"handle_type\":\"unit\",\"alive\":" + aliveS + ",\"handle_id\":" + IntToString(handleId) + "}"') + ';',
        "    }",
    ]
    for ttype in types:
        payload = (
            r'"{\"handle_type\":\"' + ttype + r'\",\"alive\":'
            + r'" + aliveS + ",\"handle_id\":'
            + r'" + IntToString(handleId) + "}"'
        )
        lines.append(f'    if (handleType == "{ttype}") {{')
        lines.append('        aliveS = "false";')
        lines.append(f'        if (libVibeHandles_gf_Has_{ttype}(handleId)) {{ aliveS = "true"; }}')
        lines.append(f'        return {_mr("result", "handle.query", "OK", payload)};')
        lines.append('    }')
    lines.append('    return ' + _mr("error", "handle.query", "INVALID_ARGS", r'"{\"reason\":\"unknown_handle_type\"}"') + ';')
    lines += ["}", ""]

    # handle.drop
    lines += [
        "string libVibeKernel_gf_HandleHandleDrop(string argsJson) {",
        "    string handleType;",
        "    int handleId;",
        "    bool dropped;",
        '    handleType = libVibeKernel_gf_ArgsGet(argsJson, "handle_type");',
        '    handleId = libVibeKernel_gf_ArgsGetInt(argsJson, "handle_id");',
        '    if (handleType == "unit") {',
        '        return ' + _mr("error", "handle.drop", "INVALID_ARGS", r'"{\"reason\":\"unit_lifetime_game_owned\"}"') + ';',
        "    }",
        "    dropped = false;",
    ]
    for ttype in types:
        lines.append(f'    if (!dropped && handleType == "{ttype}") {{ dropped = libVibeHandles_gf_Drop_{ttype}(handleId); }}')
    lines += [
        "    if (!dropped) {",
        '        return ' + _mr("error", "handle.drop", "HANDLE_NOT_FOUND",
                                r'"{\"handle_type\":\"" + handleType + "\",\"handle_id\":" + IntToString(handleId) + "}"') + ';',
        "    }",
        "    libVibeKernel_gv_stateVersion += 1;",
        '    return ' + _mr("result", "handle.drop", "OK",
                            r'"{\"handle_type\":\"" + handleType + "\",\"handle_id\":" + IntToString(handleId) + ",\"dropped\":true}"') + ';',
        "}",
        "",
    ]

    # handle.clear
    lines += [
        "string libVibeKernel_gf_HandleHandleClear(string argsJson) {",
        "    string handleType;",
        '    handleType = libVibeKernel_gf_ArgsGet(argsJson, "handle_type");',
        '    if (handleType == "all") {',
    ]
    for ttype in types:
        lines.append(f"        libVibeHandles_gf_Clear_{ttype}();")
    lines += [
        "        libVibeKernel_gv_stateVersion += 1;",
        '        return ' + _mr("result", "handle.clear", "OK", r'"{\"handle_type\":\"all\"}"') + ';',
        "    }",
    ]
    for ttype in types:
        payload = r'"{\"handle_type\":\"' + ttype + r'\"}"'
        lines.append(
            f'    if (handleType == "{ttype}") {{ libVibeHandles_gf_Clear_{ttype}(); '
            f'libVibeKernel_gv_stateVersion += 1; return {_mr("result", "handle.clear", "OK", payload)}; }}'
        )
    lines.append('    return ' + _mr("error", "handle.clear", "INVALID_ARGS", r'"{\"reason\":\"unknown_handle_type\"}"') + ';')
    lines.append("}")
    return "\n".join(lines)


def patch_kernel_files() -> None:
    kernel_path = KERNEL / "LibVibeKernel.galaxy"
    text = kernel_path.read_text(encoding="utf-8")
    for tag in ("INVOKE_GEN", "HANDLE_OPS_DISPATCH", "HANDLE_OPS"):
        text = strip_marker_block(text, tag)

    text = insert_before_anchor(
        text,
        '    return libVibeKernel_gf_MakeResponse("error", libVibeKernel_gv_currentSession, libVibeKernel_gv_lastRequestId, libVibeKernel_gv_lastSequence, "function.invoke", "FUNCTION_NOT_FOUND", "{}");',
        marker_block("INVOKE_GEN", GEN_INVOKE_BRANCH.rstrip("\n")),
    )
    text = insert_before_anchor(
        text,
        "    } else {\n        // \u672a\u77e5\u64cd\u4f5c\uff0c100% \u62d2\u7edd\uff08\u4e0d fallback\uff09",
        marker_block("HANDLE_OPS_DISPATCH", HANDLE_OPS_BRANCH.rstrip("\n")),
    )
    handlers = emit_handle_op_handlers()
    text = text.rstrip("\n") + "\n\n" + marker_block("HANDLE_OPS", handlers.rstrip("\n"))
    text = apply_kernel001(text)
    kernel_path.write_text(text, encoding="utf-8")

    header_path = KERNEL / "LibVibeKernel_h.galaxy"
    htext = header_path.read_text(encoding="utf-8")
    htext = strip_marker_block(htext, "PROTOTYPES")
    proto = "\n".join([
        "// Stage 26: prototypes needed by generated invoke adapters.",
        "string libVibeKernel_gf_ArgsGet(string args, string key);",
        "int libVibeKernel_gf_ArgsGetInt(string args, string key);",
        "fixed libVibeKernel_gf_ArgsGetFixed(string args, string key);",
        "string libVibeKernel_gf_Trim(string s);",
        "unit libVibeKernel_gf_FindUnitByTag(int unitTag);",
        "string libVibeInvoke_gf_Dispatch(int functionId, string argsJson);",
    ])
    htext = htext.rstrip("\n") + "\n\n" + marker_block("PROTOTYPES", proto)
    htext = apply_kernel001_header(htext)
    header_path.write_text(htext, encoding="utf-8")


# ---------------------------------------------------------------------------
# Registry + whitelist rewrite
# ---------------------------------------------------------------------------

def rewrite_registry(plan: dict) -> None:
    data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    functions = data.get("functions", {})
    kept = {fid: spec for fid, spec in functions.items() if not fid.startswith("gen.")}
    for fn in plan["functions"]:
        args = {}
        for p in fn["params"]:
            spec: dict = {"type": arg_registry_type(p["type"]), "required": True}
            spec["galaxy_type"] = p["type"]
            spec["arg_class"] = p["class"]
            if p["class"] == "handle":
                spec["description"] = "handle ref: id:<n> or ctor literal (see invoke-plan handle_ctor_grammar)"
            elif p["class"] == "funcref":
                spec["description"] = "funcref name from the static table in invoke-plan.funcref_candidates"
            elif p["class"] == "structref":
                spec["description"] = "registered structref handle id"
            args[p["arg"]] = spec
        kept[f"gen.{fn['id']}"] = {
            "handler": f"libVibeInvoke_gf_Call{fn['id']}",
            "galaxy_name": fn["name"],
            "side_effect": True,
            "debug_only": True,
            "generated": True,
            "capability": "generated-invoke",
            "args": args,
            "returns": {"return_kind": "string"},
        }
    data["functions"] = kept
    data["generated"] = {
        "stage": "26-full-function-invoke",
        "generated_by": "generate_invoke_adapters.py",
        "generated_at": plan["generated_at"],
        "count": len(plan["functions"]),
        "policy": plan["policy"],
    }
    REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def update_whitelist(plan: dict) -> None:
    data = json.loads(WHITELIST_PATH.read_text(encoding="utf-8"))
    ops = data["operations"]
    ops["handle.query"] = {
        "category": "handle",
        "produces_side_effect": False,
        "args": {
            "handle_type": {"type": "string", "required": True},
            "handle_id": {"type": "integer", "required": True, "min": 1},
        },
        "payload_schema": {"handle_type": "string", "handle_id": "integer", "alive": "boolean"},
    }
    ops["handle.drop"] = {
        "category": "handle",
        "produces_side_effect": True,
        "args": {
            "handle_type": {"type": "string", "required": True},
            "handle_id": {"type": "integer", "required": True, "min": 1},
        },
        "payload_schema": {"handle_type": "string", "handle_id": "integer", "dropped": "boolean"},
    }
    ops["handle.clear"] = {
        "category": "handle",
        "produces_side_effect": True,
        "args": {"handle_type": {"type": "string", "required": True}},
        "payload_schema": {"handle_type": "string"},
    }
    rejected = data.setdefault("rejected_operations", [])
    for extra in ["function.invoke.unknown_generated_id", "function.invoke.out_of_range_id", "call_arbitrary_function_by_name"]:
        if extra not in rejected:
            rejected.append(extra)
    data["generated_invoke"] = {
        "stage": "26-full-function-invoke",
        "function_id_format": "gen.<int>",
        "callable_functions": len(plan["functions"]),
        "debug_only": True,
    }
    WHITELIST_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Per-map bundle emission
# ---------------------------------------------------------------------------

def emit_map_bundle(plan: dict, map_name: str, funcref_candidates: list[str]) -> dict:
    bundle_dir = KERNEL / "generated" / map_name
    bundle_dir.mkdir(parents=True, exist_ok=True)
    # GEN-SCOPE-001: only symbols inside this map's DocumentInfo dependency
    # closure may be emitted; anything else is undefined in its compile unit.
    scope = set(plan["map_scopes"][map_name])
    available = [
        fn for fn in plan["functions"]
        if any(d in scope for d in fn["available_in"])
    ]
    written = []

    def put(name: str, content: str) -> None:
        path = bundle_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(name)

    put("LibVibeInvokeCommon.galaxy", emit_common(map_name, funcref_candidates))

    # 按全局 id 区间分片（空洞区间跳过），保证顶层区间路由与片内成员一致。
    max_id = available[-1]["id"] if available else 0
    shard_ranges: list[tuple[int, int, int]] = []
    for lo in range(1, max_id + 1, SHARD_SIZE):
        hi = min(lo + SHARD_SIZE - 1, max_id)
        chunk = [fn for fn in available if lo <= fn["id"] <= hi]
        if not chunk:
            continue
        idx = (lo - 1) // SHARD_SIZE + 1
        shard_ranges.append((idx, lo, hi))
        proto = emit_shard_prototypes(chunk, idx)
        proto += "\n" + f"string libVibeInvoke_gf_DispatchShard{idx:02d}(int functionId, string argsJson);\n"
        put(f"LibVibeInvoke_{idx:02d}_h.galaxy", proto)
        put(f"LibVibeInvoke_{idx:02d}.galaxy", emit_shard_body(chunk, idx, map_name) + emit_shard_dispatch(chunk, idx) + "\n")

    put("LibVibeInvokeDispatch_h.galaxy", emit_dispatch_header())
    put("LibVibeInvokeDispatch.galaxy", emit_dispatch(shard_ranges, map_name, len(available)))
    for tier in ROLLOUT_TIERS:
        put(f"LibVibeInvokeDispatch_tier{tier}.galaxy", emit_dispatch(shard_ranges, map_name, len(available), tier=tier))
    return {"map": map_name, "functions": len(available), "shards": len(shard_ranges), "files": len(written)}


# ---------------------------------------------------------------------------
# Sync copies
# ---------------------------------------------------------------------------

def sync_copies(plan: dict) -> list[str]:
    synced: list[str] = []
    galaxy_files = ["LibVibeKernel.galaxy", "LibVibeKernel_h.galaxy", "LibVibeHandles.galaxy"]

    # galaxy-debug-mod mirror (shared overlay payload).
    DEBUG_MOD.mkdir(parents=True, exist_ok=True)
    for name in galaxy_files:
        shutil.copy2(KERNEL / name, DEBUG_MOD / name)
        synced.append(f"galaxy-debug-mod/Base.SC2Data/{name}")
    mod_gen = DEBUG_MOD / "generated"
    if mod_gen.exists():
        shutil.rmtree(mod_gen)
    shutil.copytree(KERNEL / "generated", mod_gen)
    synced.append("galaxy-debug-mod/Base.SC2Data/generated/**")

    # 亡者之夜 map-local kernel mirror keeps its historical compatibility copy.
    for name in galaxy_files:
        shutil.copy2(KERNEL / name, MAP_MIRROR / name)
        synced.append(f"亡者之夜.SC2Map/Base.SC2Data/{name}")
    map_gen = MAP_MIRROR / "generated"
    if map_gen.exists():
        shutil.rmtree(map_gen)
    src_bundle = KERNEL / "generated" / "亡者之夜.SC2Map"
    if src_bundle.exists():
        shutil.copytree(src_bundle, map_gen / "亡者之夜.SC2Map")
        synced.append("亡者之夜.SC2Map/Base.SC2Data/generated/亡者之夜.SC2Map/**")
    return synced


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> None:
    entries = load_owned_entries()
    plan = build_plan(entries)

    ART_DIR.mkdir(parents=True, exist_ok=True)
    (ART_DIR / "invoke-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")

    (KERNEL / "LibVibeHandles.galaxy").write_text(emit_handles(), encoding="utf-8")
    patch_kernel_files()
    rewrite_registry(plan)
    update_whitelist(plan)

    # Regenerate per-map bundles from scratch.
    gen_root = KERNEL / "generated"
    if gen_root.exists():
        shutil.rmtree(gen_root)
    gen_root.mkdir(parents=True)
    bundle_stats = []
    for map_name in sorted(plan["bundles"]):
        bundle_stats.append(emit_map_bundle(
            plan, map_name,
            plan["funcref_candidates_by_map"].get(map_name, plan["funcref_candidates"]),
        ))
    plan["bundles"] = {b["map"]: b for b in bundle_stats}
    (ART_DIR / "invoke-plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")

    synced = sync_copies(plan)

    print(json.dumps({
        "callable": len(plan["functions"]),
        "excluded": len(plan["excluded"]),
        "funcref_candidates": len(plan["funcref_candidates"]),
        "bundles": [{"map": b["map"], "functions": b["functions"], "shards": b["shards"], "files": b["files"]} for b in bundle_stats],
        "synced": synced,
    }, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
