"""symbol_repair 的 funcref 判定门禁。

【为什么这个文件必须存在】2026-08-08 真机根因 #2：Stage C 曾用
`scan_defined()` 的符号集当 funcref 裁剪白名单，而那个正则**显式收 native**
(`^\\s*(?:native\\s+)?(\\w+)\\s+(\\w+)\\s*\\(`)。于是 CMRE `TriggerLibs/AI.galaxy`
里 29 个 `native void AIClearStock(int);` 全部"符号存在"、全部通过裁剪。
Galaxy 禁止对 native 取 funcref（引擎绑定，无脚本地址）⇒ 编译错误 ⇒
**SC2 静默丢弃整个 MapScript**（不报错、不写 ScriptError、InitMap 不执行）。
静态 lint 当时报 0 错误，MPQ 内实测 `branches 406 / dropped 0`，真机
`kernel_registered=False`——一条线索都没有。

所以这里把判定钉死成可执行断言：任何"优化"回 scan_defined 的改动都会红。

运行：
  python tools/galaxy-vibe/mpq/test_symbol_repair.py
  # 或 pytest tools/galaxy-vibe/mpq/test_symbol_repair.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from symbol_repair import (  # noqa: E402
    reduce_funcref_table,
    scan_defined,
    scan_funcref_targets,
)

# 一份浓缩的编译单元样本：把真机踩到的每种形态都摆进来。
UNIT = """
// 引擎绑定：只有声明，没有脚本地址 —— 对它取 funcref 是编译错误
native void AIClearStock (int player);
native void AIAddAirDangerUnits (int player);

// 孤儿原型：某个 _h 头文件声明了，但整个单元里没有任何实现体
void libFoo_gf_OrphanProto (int p);

// 合法目标：void(int) 且有实现体
void libFoo_gf_RealHandler (int p) {
    return;
}

void libBar_gf_AnotherHandler(int lp_player) {
}

// 签名不符，全部不可用作 funcref<void(int)>
void libFoo_gf_TwoArgs (int a, int b) { }
int  libFoo_gf_ReturnsInt (int p) { return 0; }
void libFoo_gf_NoArgs () { }
void libFoo_gf_StringArg (string s) { }

// 注释掉的"实现体"不算数（strip_noncode 必须先跑）
// void libFoo_gf_CommentedOut (int p) { }
"""


class ScanFuncrefTargetsTests(unittest.TestCase):
    """判据：编译单元内存在 `void <name>(int) {` 实现体。"""

    @classmethod
    def setUpClass(cls):
        cls.targets = scan_funcref_targets(UNIT)

    def test_accepts_void_int_with_body(self):
        self.assertIn("libFoo_gf_RealHandler", self.targets)
        self.assertIn("libBar_gf_AnotherHandler", self.targets)

    def test_rejects_native_declarations(self):
        """本轮根因：native 有声明无脚本地址，funcref 指向它必编译失败。"""
        self.assertNotIn("AIClearStock", self.targets)
        self.assertNotIn("AIAddAirDangerUnits", self.targets)

    def test_rejects_orphan_prototype(self):
        self.assertNotIn("libFoo_gf_OrphanProto", self.targets)

    def test_rejects_mismatched_signatures(self):
        for name in ("libFoo_gf_TwoArgs", "libFoo_gf_ReturnsInt",
                     "libFoo_gf_NoArgs", "libFoo_gf_StringArg"):
            self.assertNotIn(name, self.targets, name)

    def test_ignores_commented_out_definitions(self):
        self.assertNotIn("libFoo_gf_CommentedOut", self.targets)

    def test_exact_expected_set(self):
        self.assertEqual(
            self.targets, {"libFoo_gf_RealHandler", "libBar_gf_AnotherHandler"})


class ScanDefinedIsNotAWhitelistTests(unittest.TestCase):
    """回归护栏：证明 scan_defined **不能**当 funcref 白名单。

    这不是在测 scan_defined 有 bug —— 它的契约就是"宁可多收、不可漏收"，
    对符号闭包检查是正确的。错的是拿它当 funcref 裁剪依据。把这个差异固化下来，
    以后谁想把两者合并，会先撞上这条断言。
    """

    def test_scan_defined_does_collect_natives(self):
        defined = scan_defined(UNIT)
        self.assertIn("AIClearStock", defined)
        self.assertIn("libFoo_gf_OrphanProto", defined)

    def test_funcref_targets_are_strict_subset(self):
        defined = scan_defined(UNIT)
        targets = scan_funcref_targets(UNIT)
        self.assertTrue(targets < defined, "funcref 目标必须严格窄于符号集")
        leaked = {"AIClearStock", "AIAddAirDangerUnits", "libFoo_gf_OrphanProto"}
        self.assertEqual(leaked & targets, set())
        self.assertEqual(leaked & defined, leaked)


class ReduceFuncrefTableTests(unittest.TestCase):
    """Stage C 端到端：非法分支必须被删、合法分支必须留。"""

    TABLE = '''
libVibeInvoke_gt_VoidIntFunc libVibeInvoke_gf_ResolveFuncref (string name) {
    if (name == "AIClearStock") { return AIClearStock; }
    if (name == "libFoo_gf_RealHandler") { return libFoo_gf_RealHandler; }
    if (name == "libFoo_gf_OrphanProto") { return libFoo_gf_OrphanProto; }
    if (name == "libBar_gf_AnotherHandler") { return libBar_gf_AnotherHandler; }
    return null;
}
'''

    def test_drops_illegal_targets_keeps_legal(self):
        allowed = scan_funcref_targets(UNIT)
        out, kept, dropped = reduce_funcref_table(self.TABLE, allowed)
        self.assertEqual((kept, dropped), (2, 2))
        self.assertIn("return libFoo_gf_RealHandler;", out)
        self.assertIn("return libBar_gf_AnotherHandler;", out)
        self.assertNotIn("return AIClearStock;", out)
        self.assertNotIn("return libFoo_gf_OrphanProto;", out)
        # 删除留痕，便于事后审计（不是静默抹掉）
        self.assertIn("[symbol-repair] funcref dropped: AIClearStock", out)
        # 兜底 return 必须还在，否则函数会掉进未定义行为
        self.assertIn("return null;", out)

    def test_using_scan_defined_would_have_shipped_the_bug(self):
        """反向对照：用旧白名单会原样放行 native —— 正是真机静默死的那张图。"""
        _, kept, dropped = reduce_funcref_table(self.TABLE, scan_defined(UNIT))
        self.assertEqual((kept, dropped), (4, 0))


if __name__ == "__main__":
    unittest.main(verbosity=2)
