#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""round21 README 同步（幂等）。"""
import sys
from pathlib import Path

README = Path(__file__).resolve().parent / "scripts" / "cmlib" / "README.md"

changed = []


def edit(old: str, new: str, label: str) -> None:
    text = README.read_text(encoding="utf-8")
    if new in text:
        print(f"  [skip] {label}")
        return
    if old not in text:
        raise SystemExit(f"[readme] 锚点缺失，中止：{label}")
    if text.count(old) != 1:
        raise SystemExit(f"[readme] 锚点不唯一（{text.count(old)}）：{label}")
    README.write_text(text.replace(old, new), encoding="utf-8")
    changed.append(label)
    print(f"  [ok]   {label}")


# ---- 2.1 Core 速查：补 StrIsEmpty/StrNotEmpty -------------------------------
edit(
    "| `string CharAt/StartsWith/EndsWith/Contains/TrimSpaces` | 字符串工具 |",
    "| `bool StrIsEmpty/StrNotEmpty(s)` | **判空唯一正确姿势** —— Galaxy 里空串与 null 等价，"
    "`s != null` 恒等于 `s != \"\"`，不能用来区分\"未设置\"与\"空\"（round21 真机实证，见 §8） |\n"
    "| `string CharAt/StartsWith/EndsWith/Contains/TrimSpaces` | 字符串工具 |",
    "2.1 Core: StrIsEmpty/StrNotEmpty",
)

# ---- 2.3 Unit 速查：武器索引 1-based ----------------------------------------
edit(
    "| `void UnitRemove(unit)` |",
    "| `int UnitWeaponCount` / `fixed UnitWeaponPeriod/UnitWeaponDamage/UnitWeaponDps/UnitDpsTotal` | "
    "武器查询。⚠ **索引 1-based**（`[1, UnitWeaponCount]`），传 0 按越界返回 0.0，"
    "不是\"第一把武器\"（round21 真机钉死） |\n"
    "| `void UnitRemove(unit)` |",
    "2.3 Unit: 武器索引 1-based",
)

# ---- 5.2 状态块：round20 待验 -> round21 结论 --------------------------------
edit(
    """> ⏳ **round16~20 状态**：库已扩到 21 模块 / **1239 个函数**（round20 补齐单位 / 建筑 /
> 面板效果三条主线与 data / conversation 两个低覆盖域，净增 90 个封装），自测断言从
> 195 扩到 **505 条**。静态门禁 `gate.py` **ALL PASSED**（符号层 + G1001 + 引擎符号/常量
> + 全量类型检查 0 error），`check_cmlib.py` **PASSED 0 错 0 警**，五件产物已按新源码重建。
> 三档真机矩阵**尚未复验**——机器上有真人对局在跑，按铁律不清场（见 §5.4），
> 已挂 `matrix_daemon.py` 脱离会话守候，日志 `matrix_round20.log`。
> 矩阵通过前，505 这个数只是**静态计数**，不是结论。""",
    """> ✅ **round20 矩阵已出结论（并非全绿）**：守候进程在真人对局结束后自动跑完，
> 内联 / 依赖两档均为 **PARTIAL 499/504**，反向对照 FAIL 0/504（符合预期）。
> 失败标签 3 条：`unit.weapon.period`、`unit.weapon.damage`、`conv.activesound.notnull`
> （另外 2 条差额是未触发的事件断言，属 §5.2.1 已定性的非致命类）。
> **这三条恰恰证明了"静态全绿 ≠ 真机能跑"—— 它们连过五道静态门禁**。
>
> ⏳ **round21 状态**：三条已定位并修复（见 §8），库扩到 21 模块 / **1241 个函数**
> （新增 `CMLib_StrIsEmpty` / `CMLib_StrNotEmpty`），自测断言 505 → **512 条**。
> `gate.py` **ALL PASSED**（typecheck errors = 0）、`check_cmlib.py` **PASSED 0 错 0 警**
> （43 文件 / 1258 实现 / 1241 声明 / 3946 调用点）、`API_INDEX.md` 已重生成无漂移，
> 四件产物已按 round21 源码重建。三档矩阵已挂守候，日志 `matrix_round21.log`。
> 矩阵通过前，512 这个数只是**静态计数**，不是结论。""",
    "5.2 状态块 -> round21",
)

# ---- 新增 §8 ----------------------------------------------------------------
readme_text = README.read_text(encoding="utf-8")
if "## 8. round21" not in readme_text:
    README.write_text(
        readme_text.rstrip()
        + """

---

## 8. round21 的两条引擎级发现（真机矩阵抓出来的，静态门禁全都放行了）

round20 的三档矩阵跑出 **PARTIAL 499/504**，3 条失败标签。它们的共同点：
**过了 `gate.py` 全部五道关**（符号层 / G1001 / 构建 / 类型检查 / galaxy-lint），
一条都没被拦下。原因很直白 —— 静态检查能验证"类型对不对、符号存不存在"，
但验证不了"引擎在运行时到底怎么定义语义"。

### 8.1 武器索引是 1-based，传 0 不是"第一把武器"

```galaxy
// ✗ 断言这么写，真机必挂
CMLib_UnitWeaponPeriod(marine, 0) > 0.0      // 返回 0.0
// ✓ 1 才是第一把武器
CMLib_UnitWeaponPeriod(marine, 1) > 0.0
```

`natives.galaxy` 只给了 `native fixed UnitWeaponPeriod(unit inUnit, int inIndex);`，
**没有任何一处文档说明索引基准**。库实现按 1-based 写了守卫（`< 1` 直接返回 0.0），
而自测断言按 0-based 写 —— 两边打架，静态层面谁也发现不了。

**怎么判定谁对的**（这是本节真正的方法论）：同一轮里 `unit.weapon.dps` 断言
**通过了**，而 `CMLib_UnitDpsTotal` 的实现是 `for i in 1..UnitWeaponCount` 循环累加，
它拿到了 `> 0.0` 的结果 ⇒ **索引 1 是合法武器索引** ⇒ native 是 1-based ⇒
实现正确、断言写错。**用同一轮里"通过的那条断言"去反推"失败的那条谁对"，
比翻文档快也比翻文档准。**

修法不只是把 0 改成 1，还补了 `unit.weapon.period.zero` / `unit.weapon.damage.zero`
两条断言把"0 属越界"这个契约钉死，并在 `cmlib_unit_h.galaxy` 写进注释。

### 8.2 Galaxy 里空串与 null 等价 —— `s != null` 判非空是错的

```galaxy
// ✗ 恒为 false（哪怕函数返回的是字面量 ""）
CMLib_ConvDataActiveSound() != null
// ✓
CMLib_StrIsEmpty(CMLib_ConvDataActiveSound())
```

推演过程（两条路径收敛到同一结论，所以是**推出来的不是猜的**）：

* 若 native 返回 null → 实现里 `lv_id == null` 命中 → 返回字面量 `""`，
  此时断言 `"" != null` 判 false ⇒ 说明 `"" == null` 成立；
* 若那次 `== null` 没命中 → 原值直接返回，断言同样判 false ⇒ 说明该值 `== null`。

两条路都指向同一件事：**空串与 null 在 Galaxy 字符串上不可区分**。

顺手做了全库扫描（`scan_strnull_round21.py`）：库内共 **18 处**对 string 做 null 比较，
逐处复核后**全部是"空即跳过"语义，等价、无 bug**，不构成系统性缺陷 ——
但写法有误导性，正确姿势统一为 `CMLib_StrIsEmpty` / `CMLib_StrNotEmpty`
（这两个函数刻意用顺序 `if` 而不是 `a || b || c`：Galaxy 的短路求值无明文保证，
`StringLength(null)` 一旦被求值就有风险）。

注意 `text` 类型**不**适用本条：同一轮 `unit.customname.guard` 断言
`CMLib_UnitCustomName(null) != null` 是通过的（`StringToText("")` 不等于 null）。
**`string` 和 `text` 在 null 语义上不一致** —— 这是最容易踩的地方。

### 8.3 把推论落成硬证据，而不是留在文档里

上面两条结论都是推演出来的。为了让下一轮不必重新推，selftest 落盘时额外写了
**四个诊断探针**进 bank（是探针不是断言，失败也不会把矩阵判红）：

| bank 键 | 含义 |
|---|---|
| `Result/StrNullEquiv` | `("" == null)` 的真值（1/0） |
| `Result/WpnIdx0` / `WpnIdx1` | 直接调 native `UnitWeaponPeriod(marine, 0/1)` 的毫秒值 |
| `Result/WpnCount` | `UnitWeaponCount(marine)` |

`CMLibTest_StrNullEquiv()` 刻意走局部变量而不是 `"" == null` 字面量比较：
字面量与 null 的比较是否合法在 Galaxy 里无明文保证，而**编译期失败会让 SC2
静默丢弃整个 MapScript**（§5.3 头号教训），不值得为一个诊断探针去赌。
""",
        encoding="utf-8",
    )
    changed.append("新增 §8 round21 两条引擎级发现")
    print("  [ok]   新增 §8 round21 两条引擎级发现")
else:
    print("  [skip] §8 已存在")

print(f"\n[readme] 完成，改动 {len(changed)} 处")
sys.exit(0)
