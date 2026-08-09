"""Stage 26 验收测试 — 全函数 function.invoke 扩展。

覆盖计划验收项：
  1. 生成器单测：调用计划覆盖全部唯一签名、无重复 id、每个参数都有编解码
     方案、funcref/structref 标注齐全。
    2. 注册表重写：11,824 条生成条目 + 20 条手写条目原样保留；全部
     debug_only=true；whitelist 新增 handle.* 操作族。
  3. Galaxy 生成产物：15 个地图 bundle 齐全；静态解析证据 0 错误。
  4. 宿主侧：整数 id 优先归一化为 gen.<int>；strategy 模式拒绝 debug_only。
  5. 模拟器：Debug VM fake-bridge 覆盖基础类型、句柄往返（返回值登记→
     后续调用引用）、未知句柄/FUNCREF_UNKNOWN 拒绝路径。

运行：
  python -m pytest src/projects/cmre-porting/stages/26-full-function-invoke/test_generate_invoke_adapters.py -v
"""
from __future__ import annotations

import asyncio
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src" / "projects" / "cmre-porting"))

from vibe.debug_vm import DebugVm, VM_VERSION  # noqa: E402
from vibe.function_registry import (  # noqa: E402
    FunctionRegistryError,
    load_function_registry,
    normalize_function_id,
    validate_invocation,
    wire_function_args,
)

STAGE_DIR = ROOT / "src" / "projects" / "cmre-porting" / "stages" / "26-full-function-invoke"
ARTIFACTS = ROOT / "artifacts" / "projects" / "cmre-porting" / "stage26-full-function-invoke"
KERNEL = ROOT / "tools" / "galaxy-vibe" / "kernel"
FUNCTION_CATALOG = (
    ROOT / "artifacts" / "projects" / "cmre-porting"
    / "stage25-ai-ally-capability-completion" / "discovery" / "function-catalog.json"
)

# GEN-SELF-001 (2026-08-08): the vibe kernel injects its own .galaxy files into
# the maps it instruments, so a re-scanned function catalog fed 66 kernel-owned
# symbols back into the callable plan -- including `libVibeInvoke_gf_Dispatch`
# (reentrant dispatch) and `libVibeKernel_gf_WriteBankKey` (the Host could forge
# RPC responses and bypass the whitelist entirely). The generator now filters
# kernel-owned files at catalog load time. 11,890 -> 11,824 is a tightening.
#
# 2026-08-08 二次收紧 11,824 -> 11,795（订正早先的误归因：**不是** kernel-owned
# 过滤，而是参数类型过滤）：excluded 从 7 涨到 36，新增的 29 条全部标
# `unsupported_type`，且全是 `CMPE_*` 家族里带 `CMPE_PlayerEventFunc`（一个
# funcref 类型）形参的函数，例如
#   CMPE_RegisterPlayerEvent [void(string,string,CMPE_PlayerEventFunc)]
# funcref 形参无法经 bank 通道用标量编码传递，故不可暴露为 gen.* adapter。
# 于是 excluded = 29 unsupported_type + 7 ambiguous_overloads = 36。
# 与之配套：function-registry.json 现为 11,815 条（20 vibe + 11,795 gen）。
#
# 2026-08-08 三次收紧 11,795 -> 11,676（excluded 36 -> 155）。四批新增排除全部由
# **真机二分**坐实：静态 lint 全绿，但只要保留其中任一条，SC2 就静默丢弃整个
# MapScript（bank_keys=0、无 ScriptError、无日志）。逐条对应一个 VIBE_GEN 编号：
#
#   VIBE_GEN_004  funcref_signature_template     1 条   —— `typedef funcref<F>` 的
#       签名模板原型故意无实现体，调用它 = 调用未定义符号。
#       真机：shard03 `801-1015 PASS / 801-1016 FAIL`。
#   VIBE_GEN_004  proto_only_unresolved        109 条   —— 同类兜底：无实现体、非
#       native、且全源零调用点的原型（fail-closed，零能力损失）。
#   VIBE_GEN_005  static_file_local              5 条   —— 所有实现体都带 `static`。
#       Galaxy 的 include 不是文本内联，static 把符号限死在定义它的文件里，跨文件
#       调用 = 未定义符号。真机：shard07 `2401-2472 PASS / 2401-2473 FAIL`
#       （Call#2473 = `CallDownMule(...)`）。
#   VIBE_GEN_006  mapscript_lifecycle            4 条   —— InitMap/InitLibs/
#       InitGlobals/InitTriggers。注入管线的前置原型块刻意跳过这 4 个名字，于是
#       调用点(line 20)早于定义(line 470) ⇒ use-before-declare。语义上调它们也会
#       重置全局/重注册触发器，本就不该导出。
#       真机：shard07 `2474-2513 PASS / 2474-2514 FAIL`（Call#2514 = `InitGlobals()`）。
#
# 于是 excluded = 29 unsupported_type + 7 ambiguous_overloads + 1 funcref_signature_template
#              + 109 proto_only_unresolved + 5 static_file_local + 4 mapscript_lifecycle = 155。
# 修完这四批后，全量 28-shard gen 图真机 P0 首次 **总体 PASS**，且 gen.1 / gen.202
# 经 function.invoke 原生执行并回传结构化返回值（见 artifacts/galaxy-vibe/
# tier100-live-verdict-gen-full.json）。
CALLABLE_COUNT = 11676
EXCLUDED_COUNT = 155
# 排除项一旦变多，funcref 静态表也会同步收窄（uncallable 的名字不得进表）。
# VIBE_GEN_008 再移除 50 个 MapScript 本地函数：生成 include 的解析位置早于
# MapScript 原型，普通调用可在后续 pass 解析，但函数取址会直接编译失败。
EXCLUDED_REASONS = {
    "ambiguous_overloads", "unsupported_type",
    "funcref_signature_template", "proto_only_unresolved",
    "static_file_local", "mapscript_lifecycle",
}
FUNCREF_CANDIDATES = 603
MAP_COUNT = 15
HANDWRITTEN_COUNT = 20


def load_plan() -> dict:
    return json.loads((ARTIFACTS / "invoke-plan.json").read_text(encoding="utf-8"))


# ---- 动态选取器：禁止在用例里写死 gen.<N> --------------------------------
# gen.<N> 的编号随每次重新生成整体重排（本轮 11,824 -> 11,795 就漂过一次）。
# 测试若写死编号，任何一次合法重生成都会把断言打散，且失败信息看起来像
# "参数契约坏了"，实际只是编号变了 —— 排查成本极高。凡是需要「某种形状的
# 函数」的用例，一律从 invoke-plan 按谓词挑选，并按 id 排序取首个以保证可复现。
def pick_function(plan: dict, predicate, what: str) -> dict:
    for fn in sorted(plan["functions"], key=lambda f: f["id"]):
        if predicate(fn):
            return fn
    raise AssertionError(f"invoke-plan 中不存在{what}")


def find_functions(plan: dict, predicate) -> list[dict]:
    return sorted((f for f in plan["functions"] if predicate(f)), key=lambda f: f["id"])


def has_param_class(fn: dict, cls: str) -> bool:
    return any(p["class"] == cls for p in fn["params"])


# 句柄构造文法只给前缀（如 color -> "rgb"），这里补一份「前缀 -> 合法示例载荷」，
# 使动态造参能产出既过 registry 校验、又过 fake-bridge 文法匹配的实参。
_HANDLE_SAMPLE_PAYLOAD = {
    "point": "0,0",
    "color": "255,0,0",
    "abilcmd": "move,0",
    "order": "move,0",
    "soundlink": "0,0",
    "datetime": "2026,1,1,0,0,0",
}


def wire_args(plan: dict, fn: dict, *, structref_wire: str = "id:1") -> dict:
    """按参数类别为 fn 造一组实参（structref 之外全部合法）。"""
    grammar = plan["handle_ctor_grammar"]
    funcrefs = sorted(plan["funcref_candidates"])
    args: dict = {}
    for param in fn["params"]:
        arg, cls, typ = param["arg"], param["class"], param["type"]
        if cls == "handle":
            prefixes = grammar.get(typ) or []
            assert prefixes, f"句柄类型 {typ} 缺构造文法"
            args[arg] = f"{prefixes[0]}:{_HANDLE_SAMPLE_PAYLOAD.get(typ, '')}"
        elif cls == "funcref":
            args[arg] = funcrefs[0]
        elif cls == "structref":
            args[arg] = structref_wire
        elif typ in ("int", "byte", "fixed", "bool"):
            # bool 在 bank 通道按整数编码（0/1），传 Python bool 会被
            # registry 判 "must be an integer"。
            args[arg] = 0
        else:
            args[arg] = ""
    return args


class TestInvokePlanCoverage(unittest.TestCase):
    """验收项 1：调用计划覆盖与编解码方案。"""

    @classmethod
    def setUpClass(cls):
        cls.plan = load_plan()
        cls.functions = cls.plan["functions"]

    def test_plan_covers_all_callable_signatures(self):
        self.assertEqual(len(self.functions), CALLABLE_COUNT)
        summary = self.plan["summary"]
        self.assertEqual(summary["callable_functions"], CALLABLE_COUNT)
        self.assertEqual(summary["excluded"], EXCLUDED_COUNT)
        self.assertEqual(summary["funcref_candidates"], FUNCREF_CANDIDATES)
        self.assertEqual(summary["maps"], MAP_COUNT)

    def test_function_ids_are_unique_and_contiguous(self):
        ids = [f["id"] for f in self.functions]
        self.assertEqual(len(set(ids)), CALLABLE_COUNT)
        self.assertEqual(sorted(ids), list(range(1, CALLABLE_COUNT + 1)))
        for f in self.functions:
            self.assertEqual(f["function_id"], f"gen.{f['id']}")

    def test_every_param_has_an_encode_decode_scheme(self):
        allowed_classes = {"basic", "handle", "funcref", "structref"}
        for f in self.functions:
            for position, param in enumerate(f["params"]):
                self.assertEqual(param["arg"], f"p{position}", f["function_id"])
                self.assertIn(param["class"], allowed_classes, f["function_id"])
                self.assertTrue(param["type"], f["function_id"])
            self.assertIn(f["return_class"], allowed_classes, f["function_id"])

    def test_funcref_and_structref_are_annotated(self):
        funcref_params = [
            (f["function_id"], p) for f in self.functions for p in f["params"]
            if p["class"] == "funcref"
        ]
        structref_params = [
            (f["function_id"], p) for f in self.functions for p in f["params"]
            if p["class"] == "structref"
        ]
        # funcref **形参**现已全量排除（2026-08-08）：唯一一批带 funcref 形参的
        # 函数是 CMPE_* 家族的 CMPE_PlayerEventFunc，funcref 无法用 bank 通道的
        # 标量编码传递，故生成器判 unsupported_type 排除。这里断言"被有意排除"
        # 而非"曾经存在过"，并要求 excluded 里确实留下了证据（不许静默丢失）。
        self.assertEqual(len(funcref_params), 0)
        unsupported = [e for e in self.plan["excluded"] if e["reason"] == "unsupported_type"]
        self.assertGreater(len(unsupported), 0, "funcref 形参既不可调用也无排除记录 = 静默丢失")

        self.assertGreater(len(structref_params), 0)
        # funcref **返回/静态表候选**是另一回事，仍然存在（ResolveFuncref 静态表）。
        candidates = set(self.plan["funcref_candidates"])
        self.assertEqual(len(candidates), FUNCREF_CANDIDATES)
        # structref 实例只能来自其他调用的返回值/全局状态：当前目录无函数
        # 返回 structref，因此全部 structref 参数调用必然 HANDLE_NOT_FOUND，
        # 该限制如实记入 issues.json（不伪装成功）。
        self.assertEqual([f for f in self.functions if f["return_class"] == "structref"], [])

    def test_handle_types_have_ctor_grammar_or_registry_lookup(self):
        handle_types = set(self.plan["handle_types"])
        grammar = self.plan["handle_ctor_grammar"]
        # unit 走引擎 tag（tag:<n>），其余句柄类型必须有构造文法或仅 id 引用
        for handle_type, spec in grammar.items():
            self.assertIn(handle_type, handle_types)
            self.assertGreater(len(spec), 0)

    def test_excluded_entries_record_reasons(self):
        excluded = self.plan["excluded"]
        self.assertEqual(len(excluded), EXCLUDED_COUNT)
        for entry in excluded:
            self.assertIn(entry["reason"], EXCLUDED_REASONS)
            self.assertGreaterEqual(entry["declarations"], 1)


class TestRegistryContract(unittest.TestCase):
    """验收项 2：function-registry.json 全量重写契约。"""

    @classmethod
    def setUpClass(cls):
        cls.registry = load_function_registry()
        cls.plan = load_plan()

    def test_registry_counts(self):
        generated = [k for k in self.registry if k.startswith("gen.")]
        handwritten = [k for k in self.registry if not k.startswith("gen.")]
        self.assertEqual(len(generated), CALLABLE_COUNT)
        self.assertEqual(len(handwritten), HANDWRITTEN_COUNT)

    def test_handwritten_entries_are_preserved(self):
        ping = self.registry["vibe.test.ping"]
        self.assertEqual(ping["handler"], "libVibeKernel_gf_FunctionVibeTestPing")
        self.assertFalse(ping.get("generated", False))
        self.assertFalse(ping["debug_only"])

    def test_generated_entries_are_debug_only_and_typed(self):
        plan_by_id = {f["id"]: f for f in self.plan["functions"]}
        checked = 0
        for key, spec in self.registry.items():
            if not key.startswith("gen."):
                continue
            fid = int(key.split(".", 1)[1])
            entry = plan_by_id[fid]
            self.assertTrue(spec["debug_only"], key)
            self.assertTrue(spec["generated"], key)
            self.assertEqual(spec["handler"], f"libVibeInvoke_gf_Call{fid}")
            self.assertEqual(spec["galaxy_name"], entry["name"], key)
            self.assertEqual(tuple(spec["args"]), tuple(f"p{i}" for i in range(len(entry["params"]))), key)
            for position, param in enumerate(entry["params"]):
                arg_spec = spec["args"][f"p{position}"]
                self.assertTrue(arg_spec["required"], key)
                self.assertEqual(arg_spec["galaxy_type"], param["type"], key)
                self.assertEqual(arg_spec["arg_class"], param["class"], key)
            checked += 1
        self.assertEqual(checked, CALLABLE_COUNT)

    def test_whitelist_contains_handle_operations(self):
        whitelist = json.loads((KERNEL / "whitelist.json").read_text(encoding="utf-8"))
        operations = whitelist["operations"]
        for op in ("handle.drop", "handle.clear", "handle.query"):
            self.assertIn(op, operations)
        self.assertFalse(operations["handle.query"]["produces_side_effect"])
        self.assertTrue(operations["handle.drop"]["produces_side_effect"])


class TestGeneratedArtifacts(unittest.TestCase):
    """验收项 3：Galaxy 生成产物与静态解析门证据。"""

    def test_every_map_bundle_has_dispatch_common_and_shards(self):
        plan = load_plan()
        generated_root = KERNEL / "generated"
        bundles = list(plan["bundles"]) if isinstance(plan["bundles"], list) else list(plan["bundles"].keys())
        self.assertEqual(len(bundles), MAP_COUNT)
        for map_name in bundles:
            bundle_dir = generated_root / map_name
            self.assertTrue(bundle_dir.is_dir(), map_name)
            self.assertTrue((bundle_dir / "LibVibeInvokeDispatch.galaxy").is_file(), map_name)
            self.assertTrue((bundle_dir / "LibVibeInvokeCommon.galaxy").is_file(), map_name)
            for tier in (100, 1000):
                self.assertTrue((bundle_dir / f"LibVibeInvokeDispatch_tier{tier}.galaxy").is_file(), map_name)
            shards = sorted(bundle_dir.glob("LibVibeInvoke_[0-9][0-9].galaxy"))
            headers = sorted(bundle_dir.glob("LibVibeInvoke_[0-9][0-9]_h.galaxy"))
            self.assertGreater(len(shards), 0, map_name)
            self.assertEqual(len(shards), len(headers), map_name)

    def test_dispatch_routes_each_adapter_to_its_global_id_range_shard(self):
        """顶层区间路由必须与片内成员一致（按全局 id 区间分片）。"""
        plan = load_plan()
        map_name = next(iter(plan["bundles"]))
        bundle_dir = KERNEL / "generated" / map_name
        # GEN-SCOPE-001: a bundle may only contain symbols from that map's real
        # DocumentInfo dependency closure, not "anything under Mods/".
        scope = set(plan["map_scopes"][map_name])
        available = [
            f for f in plan["functions"]
            if any(d in scope for d in f["available_in"])
        ]
        shard_texts = {}
        for path in bundle_dir.glob("LibVibeInvoke_[0-9][0-9].galaxy"):
            shard_texts[int(path.stem.rsplit("_", 1)[1])] = path.read_text(encoding="utf-8")
        dispatch = (bundle_dir / "LibVibeInvokeDispatch.galaxy").read_text(encoding="utf-8")
        max_id = max(f["id"] for f in plan["functions"])
        for fn in available:
            idx = (fn["id"] - 1) // 400 + 1
            self.assertIn(idx, shard_texts, f"gen.{fn['id']} 缺少分片")
            self.assertIn(f"libVibeInvoke_gf_Call{fn['id']}(", shard_texts[idx], f"gen.{fn['id']} 错片")
            lo = (idx - 1) * 400 + 1
            hi = min(idx * 400, max_id)
            self.assertIn(f"functionId >= {lo} && functionId <= {hi}", dispatch)
        # 分档变体：超出 tier 的 id 结构化拒绝，仅挂载低区间分片
        tier100 = (bundle_dir / "LibVibeInvokeDispatch_tier100.galaxy").read_text(encoding="utf-8")
        self.assertIn("if (functionId > 100)", tier100)
        self.assertIn('include "LibVibeInvoke_01_h"', tier100)
        self.assertNotIn('include "LibVibeInvoke_02_h"', tier100)

    def test_gen_scope_001_bundles_stay_inside_their_dependency_closure(self):
        """GEN-SCOPE-001: 每个 bundle 只能引用本图 DocumentInfo 依赖闭包内的符号。

        Galaxy 没有跨编译单元链接：MapScript 的 include 闭包就是唯一编译单元。
        只要有一个未定义符号，SC2 会静默丢弃整个 MapScript（不报错、不写日志、
        InitMap 根本不被调用），而静态 lint 依旧全绿。因此越界符号必须在生成期
        就被裁掉，不能指望运行时发现。
        """
        plan = load_plan()
        self.assertEqual(set(plan["map_scopes"]), set(plan["bundles"]))
        for map_name, scope_list in plan["map_scopes"].items():
            scope = set(scope_list)
            # 闭包至少包含地图自身。
            self.assertIn(f"Maps/{map_name}", scope, map_name)
            expected = [
                f for f in plan["functions"]
                if any(d in scope for d in f["available_in"])
            ]
            self.assertEqual(
                plan["bundles"][map_name]["functions"], len(expected), map_name
            )
            # funcref 静态表同样按图裁剪。
            for name in plan["funcref_candidates_by_map"][map_name]:
                self.assertIn(name, set(plan["funcref_candidates"]), map_name)

    def test_gen_scope_001_dead_of_night_excludes_non_dependency_symbols(self):
        """回归钉子：亡者之夜 不依赖 CoreRuntime，就不能拿到它的符号。"""
        plan = load_plan()
        scope = set(plan["map_scopes"]["亡者之夜.SC2Map"])
        self.assertNotIn("Mods/Commanders/CoreRuntime.SC2Mod", scope)
        bundle_dir = KERNEL / "generated" / "亡者之夜.SC2Map"
        for path in bundle_dir.glob("LibVibeInvoke_[0-9][0-9].galaxy"):
            self.assertNotIn(
                "XMChallenge_", path.read_text(encoding="utf-8"), path.name
            )

    def test_mapscript_local_functions_are_not_funcref_targets(self):
        """MapScript-local symbols are declared after generated includes.

        Galaxy resolves a function address while parsing the include, so using a
        later MapScript declaration as a funcref target makes the entire map fail
        to compile even though ordinary calls to the same symbol are valid.
        """
        plan = load_plan()
        catalog = json.loads(FUNCTION_CATALOG.read_text(encoding="utf-8"))
        map_local = {
            entry["name"]
            for entry in catalog["functions"]
            if entry["path"].endswith("MapScript.galaxy")
        }
        self.assertGreater(len(map_local), 0)
        self.assertTrue(map_local.isdisjoint(plan["funcref_candidates"]))
        for map_name, candidates in plan["funcref_candidates_by_map"].items():
            self.assertTrue(
                map_local.isdisjoint(candidates),
                f"{map_name}: MapScript-local funcref target leaked into bundle",
            )

    def test_structref_generation_is_fail_closed_and_compile_safe(self):
        """Structref values must never be copied by value in generated Galaxy."""
        handles = (KERNEL / "LibVibeHandles.galaxy").read_text(encoding="utf-8")
        self.assertNotIn("libVibeHandles_gf_Acquire_libCOTF_gs_HistogramData", handles)
        self.assertNotIn("libVibeHandles_gf_Get_libCOTF_gs_HistogramData", handles)
        for bundle in (KERNEL / "generated").iterdir():
            if not bundle.is_dir():
                continue
            for path in bundle.glob("LibVibeInvoke_[0-9][0-9].galaxy"):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("libVibeHandles_gf_Get_libCOTF_gs_HistogramData", text, path.name)
                self.assertNotIn("libCOTF_gs_HistogramData lv_", text, path.name)

    def test_gen_self_001_kernel_symbols_are_never_callable_adapters(self):
        """GEN-SELF-001: 内核自身符号不得回灌成 gen.<id> 适配器。

        内核把自己的 .galaxy 注入被插桩的地图，重新扫描目录就会把内核符号当成
        普通可调用函数。后果不只是噪声：`libVibeInvoke_gf_Dispatch` 会让分发可
        重入，`libVibeKernel_gf_WriteBankKey` 会让 Host 直接改写 RPC Bank、伪造
        响应并绕过白名单。内核表面只能是 RPC 契约，不能是生成目标。
        """
        plan = load_plan()
        forbidden_prefixes = ("libVibeKernel_", "libVibeHandles_", "libVibeInvoke_")
        offenders = [
            f["name"] for f in plan["functions"]
            if f["name"].startswith(forbidden_prefixes)
        ]
        self.assertEqual(offenders, [], "内核符号被回灌进调用计划")
        for f in plan["functions"]:
            declared = f["declared_at"]["path"].replace("\\", "/")
            base = declared.rsplit("/", 1)[-1]
            self.assertNotIn("/generated/", declared, f["function_id"])
            self.assertFalse(base.startswith("LibVibeInvoke"), f["function_id"])
            self.assertNotIn(
                base,
                {"LibVibeKernel.galaxy", "LibVibeKernel_h.galaxy",
                 "LibVibeHandles.galaxy", "LibVibeHandles_h.galaxy"},
                f["function_id"],
            )

    def test_vibe_kernel_001_handler_abort_resilience_is_applied(self):
        """VIBE-KERNEL-001: 三副本内核都必须带上 handler 中止韧性补丁。

        Galaxy 没有 try/catch，handler 内的运行时错误会中止整条触发器线程：
        响应永远写不出去（Host 挂到超时），PollLoop 的 while(true) 一起死掉
        （Kernel 本局永久失联）。悲观响应 + 先消费后分发 + 独立 Watchdog 三件套
        缺一不可，且必须在三个副本里保持一致。
        """
        copies = [
            KERNEL / "LibVibeKernel.galaxy",
            ROOT / "tools/galaxy-vibe/galaxy-debug-mod/Base.SC2Data/LibVibeKernel.galaxy",
            ROOT / "src/projects/cmre-porting/packages/Maps/亡者之夜.SC2Map/Base.SC2Data/LibVibeKernel.galaxy",
        ]
        for path in copies:
            self.assertTrue(path.is_file(), path)
            text = path.read_text(encoding="utf-8")
            self.assertIn("HANDLER_ABORTED", text, path.name)
            self.assertIn("libVibeKernel_gt_Watchdog_Func", text, path.name)
            self.assertIn("kernel_restart_count", text, path.name)
            # 先消费后分发：poison request 不得被重放。
            consume = text.find("libVibeKernel_gv_lastPolledRequestId = pendingId;")
            dispatch = text.find("response = libVibeKernel_gf_Dispatch(requestJson);")
            self.assertGreater(consume, 0, path.name)
            self.assertGreater(dispatch, 0, path.name)
            self.assertLess(consume, dispatch, f"{path.name}: 仍是先分发后消费")

    def test_json_escape_uses_a_real_scanner_not_stringreplace(self):
        """Galaxy 原生 StringReplace(s, repl, start, end) 是按下标区间替换，
        不是 JS 风格的 find/replace。旧生成代码 StringReplace(s,"\\","\\\\",true)
        类型和语义全错，会让 LibVibeInvokeCommon.galaxy 编译失败，进而拖垮整个
        MapScript 编译单元。转义必须自己逐字符扫描。
        """
        for map_name in load_plan()["bundles"]:
            common = KERNEL / "generated" / map_name / "LibVibeInvokeCommon.galaxy"
            self.assertTrue(common.is_file(), map_name)
            text = common.read_text(encoding="utf-8")
            self.assertIn("libVibeInvoke_gf_JsonEscape", text, map_name)
            self.assertIn("StringSub(s, i, i)", text, map_name)
            self.assertNotIn("StringReplace(", text, map_name)

    def test_static_parse_gate_evidence_is_clean(self):
        evidence_path = ARTIFACTS / "static" / "parse-generated.json"
        self.assertTrue(evidence_path.is_file(), "先运行 parse_generated.mjs 生成解析证据")
        evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
        self.assertEqual(evidence["parse_errors"], 0)
        self.assertGreaterEqual(evidence["files_parsed"], 700)

    def test_kernel_marker_blocks_present(self):
        kernel = (KERNEL / "LibVibeKernel.galaxy").read_text(encoding="utf-8")
        for tag in ("INVOKE_GEN", "HANDLE_OPS_DISPATCH", "HANDLE_OPS"):
            self.assertEqual(kernel.count(f"// ==== BEGIN STAGE26_FULL_INVOKE {tag} ===="), 1, tag)
            self.assertEqual(kernel.count(f"// ==== END STAGE26_FULL_INVOKE {tag} ===="), 1, tag)
        header = (KERNEL / "LibVibeKernel_h.galaxy").read_text(encoding="utf-8")
        self.assertEqual(header.count("// ==== BEGIN STAGE26_FULL_INVOKE PROTOTYPES ===="), 1)
        self.assertTrue((KERNEL / "LibVibeHandles.galaxy").is_file())


class TestHostIntegerIdPrecedence(unittest.TestCase):
    """验收项 4：宿主侧整数 id 优先 + strategy 拒绝。"""

    def test_integer_function_id_normalizes_to_generated_family(self):
        self.assertEqual(normalize_function_id(168), "gen.168")
        self.assertEqual(normalize_function_id("168"), "gen.168")
        self.assertEqual(normalize_function_id("gen.168"), "gen.168")
        self.assertEqual(normalize_function_id("vibe.test.ping"), "vibe.test.ping")
        with self.assertRaises(FunctionRegistryError):
            normalize_function_id(True)

    def test_generated_entry_validates_typed_args(self):
        normalized = validate_invocation("gen.168", {"p0": 1, "p1": 2})
        self.assertEqual(normalized, {"p0": 1, "p1": 2})
        with self.assertRaises(FunctionRegistryError):
            validate_invocation("gen.168", {"p0": 1})
        with self.assertRaises(FunctionRegistryError):
            validate_invocation("gen.168", {"p0": 1, "p1": 2, "p2": 3})
        # 句柄参数是 wire 字符串（id:<n> 或构造字面量）
        normalized = validate_invocation("gen.206", {"p0": "id:7"})
        self.assertEqual(normalized["p0"], "id:7")

    def test_wire_encoding_uses_gen_prefix(self):
        wire = wire_function_args(168, {"p0": 1, "p1": 2})
        self.assertEqual(wire["function_id"], "gen.168")
        self.assertEqual(wire["arg_names"], "p0,p1")
        self.assertEqual(wire["arg_p0"], 1)

    def test_strategy_mode_rejects_generated_debug_only_functions(self):
        class NullBridge:
            async def call(self, function_id, args):
                return {"kind": "result", "error_code": "OK", "payload": {}}

            async def step(self, loops):
                return {"kind": "result", "error_code": "OK", "payload": {}}

        vm = DebugVm(NullBridge())
        program = {
            "vm": VM_VERSION,
            "mode": "strategy",
            "steps": [{"op": "call", "fn": "gen.168", "args": {"p0": 1, "p1": 1}}],
        }
        result = asyncio.run(vm.run(program))
        self.assertEqual(result["status"], "failed")
        self.assertIn("strategy", result["error"])


class FakeGenBridge:
    """模拟生成 adapter 语义的 fake-bridge（按 invoke-plan 驱动）。

    - 基础类型直传；
    - 句柄参数：id:<n> 查登记表（未登记 → HANDLE_NOT_FOUND），
      构造字面量（empty:/xy:/create: 等）现造并登记；
    - funcref 参数：静态查值表外的值 → FUNCREF_UNKNOWN；
    - structref 参数：id:<n> 查登记表，未知 → HANDLE_NOT_FOUND；
    - 句柄返回值自动登记并返回 {handle_type, handle_id}。
    """

    def __init__(self) -> None:
        self.plan = load_plan()
        self.by_id = {f["id"]: f for f in self.plan["functions"]}
        self.funcrefs = set(self.plan["funcref_candidates"])
        self.grammar = self.plan["handle_ctor_grammar"]
        self.tables: dict[str, dict[int, str]] = {}
        self.next_id = 1
        self.calls: list[tuple[int, dict]] = []

    def _acquire(self, handle_type: str, marker: str) -> int:
        handle_id = self.next_id
        self.next_id += 1
        self.tables.setdefault(handle_type, {})[handle_id] = marker
        return handle_id

    def _resolve_handle(self, handle_type: str, wire: str):
        if wire.startswith("id:"):
            handle_id = int(wire[3:])
            if handle_id not in self.tables.get(handle_type, {}):
                return None, "HANDLE_NOT_FOUND"
            return handle_id, None
        prefixes = self.grammar.get(handle_type, [])
        for prefix in prefixes:
            if wire.startswith(prefix):
                return self._acquire(handle_type, wire), None
        return None, "HANDLE_INVALID"

    def call(self, function_id: str, args: dict):
        fid = int(function_id.split(".", 1)[1])
        entry = self.by_id.get(fid)
        if entry is None:
            return {"kind": "error", "error_code": "FUNCTION_NOT_FOUND", "payload": {}}
        self.calls.append((fid, dict(args)))
        for param in entry["params"]:
            value = args.get(param["arg"])
            if param["class"] == "handle":
                _, error = self._resolve_handle(param["type"], str(value))
                if error:
                    return {"kind": "error", "error_code": error, "payload": {"arg": param["arg"]}}
            elif param["class"] == "funcref":
                if str(value) not in self.funcrefs:
                    return {"kind": "error", "error_code": "FUNCREF_UNKNOWN", "payload": {"arg": param["arg"]}}
            elif param["class"] == "structref":
                wire = str(value)
                if not wire.startswith("id:") or int(wire[3:]) not in self.tables.get("structref", {}):
                    return {"kind": "error", "error_code": "HANDLE_NOT_FOUND", "payload": {"arg": param["arg"]}}
        if entry["return_class"] in ("handle", "structref"):
            handle_type = entry["return_type"]
            if entry["return_class"] == "structref":
                handle_type = "structref"
            handle_id = self._acquire(handle_type, f"ret:{entry['name']}")
            return {
                "kind": "result", "error_code": "OK",
                "payload": {"function_id": function_id, "handle_type": handle_type, "handle_id": handle_id},
            }
        if entry["return_class"] == "funcref":
            return {"kind": "result", "error_code": "OK",
                    "payload": {"function_id": function_id, "return": "opaque"}}
        return {"kind": "result", "error_code": "OK",
                "payload": {"function_id": function_id, "return": 0}}


class TestFakeBridgeRoundTrip(unittest.TestCase):
    """验收项 5：模拟器 fake-bridge 类型族抽样 + 句柄往返 + 拒绝路径。"""

    def _run(self, steps, mode="debug"):
        self.bridge = getattr(self, "bridge", None) or FakeGenBridge()
        vm = DebugVm(self.bridge)
        return asyncio.run(vm.run({"vm": VM_VERSION, "mode": mode, "steps": steps}))

    def setUp(self):
        self.bridge = FakeGenBridge()

    def _unitgroup_consumer(self) -> dict:
        return pick_function(
            self.bridge.plan,
            lambda f: len(f["params"]) == 1
            and f["params"][0]["class"] == "handle"
            and f["params"][0]["type"] == "unitgroup",
            "单参消费 unitgroup 句柄的函数",
        )

    def test_basic_types_round_trip(self):
        result = self._run([
            {"op": "call", "fn": "gen.168", "args": {"p0": 1, "p1": 1}, "save": "peon"},
        ])
        self.assertEqual(result["status"], "passed", result["error"])
        self.assertEqual(self.bridge.calls, [(168, {"p0": 1, "p1": 1})])

    def test_handle_round_trip_with_explicit_ids(self):
        producer = pick_function(
            self.bridge.plan,
            lambda f: not f["params"]
            and f["return_class"] == "handle"
            and f["return_type"] == "unitgroup",
            "零参且返回 unitgroup 句柄的函数",
        )
        result = self._run([
            {"op": "call", "fn": producer["function_id"], "args": {}, "save": "created"},
        ])
        self.assertEqual(result["status"], "passed", result["error"])
        registered = self.bridge.tables["unitgroup"]
        self.assertEqual(len(registered), 1)
        handle_id = next(iter(registered))

        follow_up = self._run([
            {"op": "call", "fn": self._unitgroup_consumer()["function_id"],
             "args": {"p0": f"id:{handle_id}"}, "save": "count"},
        ])
        self.assertEqual(follow_up["status"], "passed", follow_up["error"])

    def test_unknown_handle_id_is_rejected(self):
        result = self._run([
            {"op": "call", "fn": self._unitgroup_consumer()["function_id"],
             "args": {"p0": "id:99999"}},
        ])
        self.assertEqual(result["status"], "failed")
        self.assertIn("HANDLE_NOT_FOUND", result["error"])

    def test_handle_ctor_literal_is_accepted(self):
        result = self._run([
            {"op": "call", "fn": self._unitgroup_consumer()["function_id"],
             "args": {"p0": "empty:"}},
        ])
        self.assertEqual(result["status"], "passed", result["error"])

    def test_funcref_params_are_excluded_not_silently_dropped(self):
        """funcref 形参不可经 bank 通道传递 —— 断言它被显式排除。

        历史上这里测的是 `gen.1013` 的 FUNCREF_UNKNOWN 拒绝路径。生成器后来把
        全部带 funcref 形参的函数（CMPE_PlayerEventFunc）判为 unsupported_type
        排除，可调用面上已无 funcref 形参，该拒绝路径变成死代码。与其保留一个
        指向漂移编号的假用例，不如断言"排除是有意的且留了证据"。
        """
        plan = self.bridge.plan
        self.assertEqual(find_functions(plan, lambda f: has_param_class(f, "funcref")), [])
        reasons = {e["reason"] for e in plan["excluded"]}
        self.assertIn("unsupported_type", reasons)
        # 静态表候选（ResolveFuncref）与形参是两码事，不应被一起清空。
        self.assertGreater(len(self.bridge.funcrefs), 0)

    def test_structref_requires_registered_instance(self):
        target = pick_function(
            self.bridge.plan,
            lambda f: has_param_class(f, "structref"),
            "带 structref 形参的函数",
        )
        missing = self._run([
            {"op": "call", "fn": target["function_id"],
             "args": wire_args(self.bridge.plan, target, structref_wire="id:1")},
        ])
        self.assertEqual(missing["status"], "failed")
        self.assertIn("HANDLE_NOT_FOUND", missing["error"])

    def test_debug_vm_accepts_integer_function_id_like_host(self):
        # 与宿主整数 id 优先一致：DebugVm 程序可直接用整数/数字串 fn。
        result = self._run([
            {"op": "call", "fn": 168, "args": {"p0": 2, "p1": 3}},
        ])
        self.assertEqual(result["status"], "passed", result["error"])
        self.assertEqual(self.bridge.calls, [(168, {"p0": 2, "p1": 3})])
        result2 = self._run([
            {"op": "call", "fn": "168", "args": {"p0": 0, "p1": 0}},
        ])
        self.assertEqual(result2["status"], "passed", result2["error"])

    def test_debug_vm_strategy_mode_rejects_integer_debug_only_id(self):
        result = self._run([
            {"op": "call", "fn": 168, "args": {"p0": 1, "p1": 1}},
        ], mode="strategy")
        self.assertEqual(result["status"], "failed")
        self.assertIn("strategy", result["error"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
