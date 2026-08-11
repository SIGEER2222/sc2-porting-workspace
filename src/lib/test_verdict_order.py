# -*- coding: utf-8 -*-
"""判定顺序回归钉：保证「地图没起来」永远被判成 FAIL，不会被次级判据掩盖。

## 为什么单独立一个文件

round22 事故：`cmlib_runtime_test.py` 新增「断言会计」判据时，把
`if not acct_ok -> PARTIAL` 插在了 `sentinel` 门**之前**。后果：

  · 反向对照图（依赖指向不存在路径、期望地图起不来）passed=0、sentinel=0，
    `acct_ok = (0 == 509)` 为 False -> 被判 `PARTIAL — 断言会计不符`；
  · 矩阵 `classify()` 又恰好把 `"PARTIAL —"` 匹配排在 `ghost0` 之前，跟着误判；
  · 三档矩阵 rc=1，表面看像"通用库回归"，实际库是好的（内联/依赖两档 PASS 509/509）。

真正危险的不是 rc=1，而是**反向对照失去了产出 FAIL 的能力**。反向对照存在的
唯一意义就是排假阳性；它一旦哑火，正向那两档的 PASS 也不再能证明什么。
静态门禁（gate.py）查不出这类问题——它是纯语义/顺序缺陷，语法完全合法。

所以把它钉成可离线秒跑的回归测试：以后任何人往判定链里插新判据，
只要挡在 sentinel 前面，这里立刻红。

## 跑法

    python test_verdict_order.py
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from run_matrix_round10 import classify  # noqa: E402

FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  BAD  {name}  {detail}")
        FAILURES.append(name)


# --------------------------------------------------------------------------
# 1) classify()：三种代表性输出 -> 三种判定
# --------------------------------------------------------------------------
# 反向对照的真实形态：地图起不来，观测全 0，bank 没被写过（无魔数）。
# 注意它同时带着 `断言通过 0/509` 和 `PARTIAL —`（round22 runner 的错误输出），
# 这正是当时骗过 classify 的那份文本 —— 现在必须被判成 FAIL。
OUT_NEG_ROUND22_BUG = """
[t] obs#6 loop=367 units=0 {}
[t]    Ghost     = 0  -> MapScript 编译成功 + InitMap 被调用: NO
[t]    Marauder  = 0  -> 断言通过 0/509
[t] PARTIAL — 断言会计不符: 执行 0 vs 期望 509
"""

# runner 修好后反向对照应有的形态。
OUT_NEG_FIXED = """
[t]    Ghost     = 0  -> MapScript 编译成功 + InitMap 被调用: NO
[t] FAIL — sentinel 未出现：MapScript 未编译成功或 InitMap 未被调用
"""

# 濒死实例假阴性：地图其实跑过（bank 里有魔数），只是观测窗口拿不到 -> 必须判瞬态。
OUT_DYING_INSTANCE = """
[t]    Ghost     = 0
[t]    {'Result/Magic': '13371337', 'Result/Passed': '509'}
[t] FAIL — sentinel 未出现：MapScript 未编译成功或 InitMap 未被调用
"""

# 真 PARTIAL：地图起来了（Ghost=1），但某些断言没过 —— 这才该叫 PARTIAL。
OUT_REAL_PARTIAL = """
[t]    Ghost     = 1
[t]    Marauder  = 507  -> 断言通过 507/509
[t]    {'Result/Magic': '13371337', 'Result/FailTags': 'ug.filterregion.map'}
[t] PARTIAL — 存在失败断言，标签: ug.filterregion.map
"""

OUT_PASS = """
[t]    Ghost     = 1
[t]    Marauder  = 509  -> 断言通过 509/509
[t]    {'Result/Magic': '13371337'}
[t] PASS — CMLib 在真实 SC2 引擎中编译并执行成功，509 项断言全部通过
"""

print("[verdict-order] classify() 判定")
v, transient, _ = classify(OUT_NEG_ROUND22_BUG)
check("反向对照(带 round22 错误 PARTIAL 文案) -> FAIL",
      v == "FAIL" and not transient, f"实得 {v} transient={transient}")

v, transient, _ = classify(OUT_NEG_FIXED)
check("反向对照(修复后文案) -> FAIL", v == "FAIL" and not transient,
      f"实得 {v}")

v, transient, _ = classify(OUT_DYING_INSTANCE)
check("濒死实例(Ghost=0 但有魔数) -> 瞬态而非真结论",
      v == "FAIL?" and transient, f"实得 {v} transient={transient}")

v, _, detail = classify(OUT_REAL_PARTIAL)
check("真 PARTIAL(地图起来了但有失败断言) -> PARTIAL",
      v == "PARTIAL" and "ug.filterregion.map" in detail, f"实得 {v} / {detail}")

v, _, _ = classify(OUT_PASS)
check("全通过 -> PASS", v == "PASS", f"实得 {v}")


# --------------------------------------------------------------------------
# 2) cmlib_runtime_test.py：源码层校验 sentinel 门排在所有次级判据之前
# --------------------------------------------------------------------------
# 不 import 执行（那需要真机），改成静态读 AST：在 main() 的失败分支序列里，
# 提到 `sentinel` 的那个 if 必须是**第一个**。
# `--src <path>` 指定被检文件，默认查真的 runner。
# 存在的意义是**阳性对照**：把判定顺序改坏写进一个临时副本，指过去必须变红。
# 恒绿的校验器等于没有校验器 —— 本仓库已经吃过一次亏（白名单识别静默漏检）。
SRC = HERE / "cmlib_runtime_test.py"
if "--src" in sys.argv:
    SRC = Path(sys.argv[sys.argv.index("--src") + 1])

print(f"[verdict-order] {SRC.name} 失败分支顺序")
src = SRC.read_text(encoding="utf-8")
tree = ast.parse(src)
main_fn = next((n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
check("找得到 main()", main_fn is not None)

if main_fn is not None:
    # 怎么认出「判定分支」：不能只看"body 里有 return 的 if"——main() 前段还有
    # `if r.error: print("CreateGame FAILED"); return` 这类**连接层**错误处理，
    # 它们同样是 if+return，会被误收进来（本回归钉第一版就当场自己踩到，
    # 把 `r.error` 当成了第一个判定分支）。
    # 稳的判据：分支 body 里必须真的打印 verdict 文案（`PASS —`/`PARTIAL —`/
    # `FAIL —`）。判定文案是矩阵 classify() 的唯一输入，用它当锚点最贴合语义。
    VERDICT_TOKENS = ("PASS —", "PARTIAL —", "FAIL —")

    def prints_verdict(node: ast.If) -> bool:
        for s in ast.walk(node):
            if isinstance(s, ast.Constant) and isinstance(s.value, str) \
                    and any(t in s.value for t in VERDICT_TOKENS):
                return True
            # f-string 的字面量片段
            if isinstance(s, ast.JoinedStr):
                for v in s.values:
                    if isinstance(v, ast.Constant) and isinstance(v.value, str) \
                            and any(t in v.value for t in VERDICT_TOKENS):
                        return True
        return False

    verdict_ifs = [n for n in main_fn.body
                   if isinstance(n, ast.If) and prints_verdict(n)]
    # 跳过 `if ok:`（成功分支），只看失败分支。
    fail_ifs = [n for n in verdict_ifs
                if not (isinstance(n.test, ast.Name) and n.test.id == "ok")]
    check("失败分支不少于 3 个", len(fail_ifs) >= 3, f"实得 {len(fail_ifs)}")
    if fail_ifs:
        first = ast.unparse(fail_ifs[0].test)
        check("第一个失败分支判的是 sentinel", "sentinel" in first,
              f"实得 `{first}` —— 新判据必须往后插，不能挡在 sentinel 前面")
        # acct_ok 若存在，必须排在 sentinel 之后
        idx_acct = next((i for i, n in enumerate(fail_ifs)
                         if "acct_ok" in ast.unparse(n.test)), None)
        if idx_acct is not None:
            check("断言会计判据排在 sentinel 之后", idx_acct > 0,
                  f"acct_ok 在第 {idx_acct + 1} 位")

print()
if FAILURES:
    print(f"[verdict-order] FAILED —— {len(FAILURES)} 项: {FAILURES}")
    sys.exit(1)
print("[verdict-order] ALL PASSED")
