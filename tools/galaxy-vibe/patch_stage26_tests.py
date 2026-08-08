"""Atomically re-point the Stage 26 acceptance test at the fixed generator.

Written as a one-shot script instead of interactive edits because several
agents are editing this tree concurrently; a read-then-write edit loses the
race and silently reverts. Idempotent: re-running is a no-op.

Three corrections:

1. GEN-SELF-001 counts. A parallel run "fixed" the drift by bumping
   CALLABLE_COUNT to 11,999 / EXCLUDED_COUNT to 9 — that enshrines the bug.
   The kernel injects its own .galaxy files into the maps it instruments, so a
   re-scanned catalog fed 66 kernel-owned symbols back in as callable adapters
   (`libVibeInvoke_gf_Dispatch` -> reentrant dispatch;
   `libVibeKernel_gf_WriteBankKey` -> Host forges RPC responses and bypasses the
   whitelist). The generator now filters them, so the truthful numbers are
   11,824 / 7.

2. GEN-SCOPE-001 shard routing. The shard test recomputed "available" with the
   pre-fix filter (`Mods/*` or the map itself), which no longer matches the
   per-map DocumentInfo dependency closure the generator emits.

3. New regression tests pinning both invariants so neither can silently return.
"""
from __future__ import annotations

import sys
from pathlib import Path

TEST = Path(__file__).resolve().parents[2] / (
    "src/projects/cmre-porting/stages/26-full-function-invoke/test_generate_invoke_adapters.py"
)

COUNT_OLD = "CALLABLE_COUNT = 11999\nEXCLUDED_COUNT = 9\n"
COUNT_NEW = '''# GEN-SELF-001 (2026-08-08): the vibe kernel injects its own .galaxy files into
# the maps it instruments, so a re-scanned function catalog fed 66 kernel-owned
# symbols back into the callable plan -- including `libVibeInvoke_gf_Dispatch`
# (reentrant dispatch) and `libVibeKernel_gf_WriteBankKey` (the Host could forge
# RPC responses and bypass the whitelist entirely). The generator now filters
# kernel-owned files at catalog load time. 11,890 -> 11,824 is a tightening.
CALLABLE_COUNT = 11824
EXCLUDED_COUNT = 7
'''

SHARD_OLD = '''        plan = load_plan()
        map_name = next(iter(plan["bundles"]))
        bundle_dir = KERNEL / "generated" / map_name
        available = [
            f for f in plan["functions"]
            if any(d.startswith("Mods/") or d == map_name for d in f["available_in"])
        ]
'''
SHARD_NEW = '''        plan = load_plan()
        map_name = next(iter(plan["bundles"]))
        bundle_dir = KERNEL / "generated" / map_name
        # GEN-SCOPE-001: a bundle may only contain symbols from that map's real
        # DocumentInfo dependency closure, not "anything under Mods/".
        scope = set(plan["map_scopes"][map_name])
        available = [
            f for f in plan["functions"]
            if any(d in scope for d in f["available_in"])
        ]
'''

NEW_TESTS = '''
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
            declared = f["declared_at"]["path"].replace("\\\\", "/")
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
        不是 JS 风格的 find/replace。旧生成代码 StringReplace(s,"\\\\","\\\\\\\\",true)
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
'''

ANCHOR = "    def test_static_parse_gate_evidence_is_clean(self):"


def main() -> int:
    text = TEST.read_text(encoding="utf-8")
    changed = []

    if COUNT_NEW in text:
        pass
    elif COUNT_OLD in text:
        text = text.replace(COUNT_OLD, COUNT_NEW, 1)
        changed.append("counts")
    else:
        print("!! count anchor not found -- inspect manually", file=sys.stderr)
        return 2

    if SHARD_NEW in text:
        pass
    elif SHARD_OLD in text:
        text = text.replace(SHARD_OLD, SHARD_NEW, 1)
        changed.append("shard-scope")
    else:
        print("!! shard anchor not found -- inspect manually", file=sys.stderr)
        return 2

    if "test_gen_self_001_kernel_symbols_are_never_callable_adapters" not in text:
        if ANCHOR not in text:
            print("!! new-test anchor not found", file=sys.stderr)
            return 2
        text = text.replace(ANCHOR, NEW_TESTS.strip("\n") + "\n\n" + ANCHOR, 1)
        changed.append("regression-tests")

    TEST.write_text(text, encoding="utf-8")
    print("patched:", ", ".join(changed) if changed else "(already up to date)")

    verify = TEST.read_text(encoding="utf-8")
    for token in (
        "CALLABLE_COUNT = 11824",
        "EXCLUDED_COUNT = 7",
        'scope = set(plan["map_scopes"][map_name])',
        "test_gen_scope_001_bundles_stay_inside_their_dependency_closure",
        "test_gen_self_001_kernel_symbols_are_never_callable_adapters",
        "test_vibe_kernel_001_handler_abort_resilience_is_applied",
        "test_json_escape_uses_a_real_scanner_not_stringreplace",
    ):
        print(("  OK   " if token in verify else "  FAIL "), token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
