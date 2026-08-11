#!/usr/bin/env python
"""README 幂等补丁 :: round26 —— 台账门禁从 1 族扩到 14 族，74 个幽灵项全部封装。

用「读-判断-写」一次完成，不用 Edit 的 read-before-write（多实例并发时会被打断）。
每段补丁先查标记是否已存在，复跑输出「无需改动」。
"""
import pathlib
import sys

README = pathlib.Path(__file__).resolve().parent / "scripts" / "cmlib" / "README.md"

MARK = "## 14. round26：把台账门禁从 1 族扩到 14 族"

SECTION = r"""

---

## 14. round26：把台账门禁从 1 族扩到 14 族

round25 建了 `check_native_ledger.py`（§13），但它当时只管 `aifilter` 一族，
24 个符号。一条只覆盖 1/N 的门禁，绿灯的含金量就是 1/N。

本轮把 `FAMILIES` 从 1 族扩到 **14 族**。扩完立刻炸出 **74 个幽灵项** ——
族内既没被任何 CMLib 函数调用、也没有 `@ledger-reject` 登记的引擎符号。

### 14.1 74 个幽灵项，一个都没往外推

历轮处理"没证据的符号"有两种偷懒姿势：一是登记拒绝（写个理由就完事），
二是把族从 `FAMILIES` 里摘掉（门禁立刻变绿）。两种都是**用判据去迁就现状**，
而不是用现状去满足判据。

本轮的处置是全部封装，**零登记拒绝**。逐族清点：

| 族 | 新封装 | 落在模块 | 代表符号 |
|---|---|---|---|
| `string` | 13 | `cmlib_core` | `StringCase` / `StringCompare` / `StringContains` / `StringWord` / `StringReplace` / `StringReplaceWord` / `StringToAbilCmd` / `StringToDateTime` / `StringExternalAsset` / `StringExternalHotkey` |
| `point` | 9 | `cmlib_geo` | `PointInterpolate` / `PointSet` / `PointSetHeight` / `PointsInRange` / `PointReflect` / `PointPathingCliffLevel` / `PointFromId` / `PointFromName` |
| `region` | 6 | `cmlib_geo` | `RegionSetCenter` / `RegionSetOffset` / `RegionGetOffset` / `RegionAttachToUnit` / `RegionGetAttachUnit` |
| `catalog` | 12 | `cmlib_catalog` | `CatalogEntryClass` / `CatalogEntryParent` / `CatalogField*`（6 个反射） / `CatalogReferenceGet(AsInt)` |
| `order` | 11 | `cmlib_unit` | `OrderSetPlayer` / `OrderGetPlayer` / `OrderSetFlag` / `OrderSetAbilityCommand` / `OrderTargeting*`（3 个构造器） |
| `timer` | 11 | `cmlib_panel` | `TimerLastStarted` / `TimerWindowVisible` / `TimerWindowSet*`（8 个样式 setter） |
| `transmiss` | 5 | `cmlib_conv` | `TransmissionSendForPlayerSelect` / `TransmissionSetOption` / `TransmissionSource*`（3 个） |
| `cinematic` | 4 | `cmlib_fx` | `CinematicMode` / `CinematicOverlay` / `CinematicDataRun` / `CinematicDataStop` |
| `aistock` | 3 | `cmlib_stock` | `AISetStockAlias` / `AISetStockFree` / `AISetStockTechNextUnCap` |
| `vpanel` | 2 | `cmlib_board` | `VictoryPanelSetCustomStatisticText` / `...Value` |
| `aifilter` | 1 | `cmlib_ai` | `AISetFilterEnergy` |
| **合计** | **74** | 11 个模块 | 台账 285 已封装 / 1 登记拒绝 |

唯一的登记拒绝仍是 round25 那条 `AISetFilterCanAttackEnemy`（§12.2 非单调响应，
有硬证据）。**"拒绝"这一栏应该很难写进去，不是很好用的出口。**

### 14.2 ParamDef 元数据不权威，`.galaxy` 源码才是

抽签名时踩到一个和 §12.2 同款诱因的坑：`TransmissionSendForPlayerSelect` 在
`NativeLib.TriggerLib` 的 ParamDef 里返回类型标的是 `transmission`，
但 `natives_missing.galaxy:1596` 的源码写的是 **`native int`**。

照元数据写就是 `transmission CMLib_TransSendForPlayerSelect(...)` —— 类型不匹配，
真机静默丢整个 MapScript。

> **规则：签名一律以 `.galaxy` 源码为准，`.TriggerLib` 的 ParamDef 只当索引用。**

`sig_round26.py` 已按此实现：先扫 `.galaxy` 拿 `decl`，拿不到才回落 `flag`。
74 个符号里 `decl` 命中 74、`no_signature` 0，没有一个是靠元数据蒙的。

### 14.3 自检断言：有读回路径才配写硬断言

74 个封装配了 47 个新断言点（静态 581 → **628**，期望执行 **626**）。
分配原则沿用 §10.3 第 ②、③ 条，没有一刀切：

**写双向 / 往返硬断言**（有独立期望值可比对）：

- `string`：`StringCase` 大小写双向、`StringCompare` 三态、`StringContains`
  三种模式（Begin/End/Anywhere）× 大小写敏感、`StringWord` 1-based 取词、
  `StringReplace` **1-based 闭区间**（官方用例 `StringReplace(s, sub,
  len-subLen+1, len)` 佐证）、`StringReplaceWord` 全替换 / 单次替换。
- `point`：`PointInterpolate` 在 `[0,1]` 外**双向夹紧**、`PointSet(p1,p2)`
  的拷贝方向（是把 p2 写进 p1，不是反过来）、`PointsInRange` 距离双向、
  `PointSetHeight`→`PointGetHeight` 往返。
- `region`：`SetCenter` / `SetOffset` / `AttachToUnit` 三组往返，外加
  **解绑后 `GetAttachUnit` 返 null** 的反向断言。
- `order`：`OrderSetPlayer`→`OrderGetPlayer` 往返、`OrderSetFlag` 双向、
  三个 `OrderTargeting*` 构造器返回非 null。
- `catalog`：`CatalogEntryClass` 同类相等 **且** 缺失条目不等（正反各一），
  `CatalogReferenceGet` 与 `...AsInt` 交叉一致。
- `timer`：`TimerLastStarted` 匹配刚启动的 timer、`TimerWindowVisible` 双向、
  8 个样式 setter 跑完窗口仍可见。

**降级成 bank 诊断探针**（纯 setter，环境里没有读回路径）：
`TimerWindow*` 的位置 / 间距 / 颜色、`Cinematic*`、`TransmissionSource*`、
`VictoryPanelSetCustomStatistic*`、`AISetStock*`、Catalog scope 反射族。
只走调用路径 + 记录返回值，**不判定**。

这条纪律是 round23（`StatEventCreate` 恒返 0）和 round25
（`AISetFilterCanAttackEnemy` 语义骗人）两次教训的直接产物：
**观测不到的东西不要写成断言，写了就是同义反复，恒绿等于没有。**

### 14.4 `isSelect` 参数：57 处官方调用全是 `false`

`TransmissionSendForPlayerSelect` 比普通 `TransmissionSend` 多一个尾参
`isSelect`。翻遍 reference 树，**57 处官方调用一律传 `false`**，`true` 分支
零观测。

处置：封装如实透传，**不为 `true` 分支写任何兜底或"智能"处理**。
理由同 §10.4 —— 没有观测就没有语义，替一个自己没验证过的分支写兜底逻辑，
只是把"不知道"包装成"看起来知道"。头文件里把这个事实写成注释，
调用方自己决定。

### 14.5 门禁自身的两处顺带修

1. **`check_cmlib.py` 会校验注释里的常量**。自检脚本里写了句注释提到
   `c_orderFlag*`，被判「照着写会编译失败」并 WARN —— 引擎确实没为 order flag
   导出具名常量族，只能传裸 int。这不是误报，是门禁在防"文档教人写错代码"。
   改掉措辞即绿。
2. **`test_ledger_sources.py`**（新增）：台账取数从「`.galaxy` 声明」单源扩成
   「`.galaxy` 声明 ∪ `<FlagNative/>`」并集（2875 ∪ 2527 = **2881**），
   新增测试钉住并集逻辑本身。`aistock` 族的 `AISetStockAlias` /
   `AISetStockFree` 就是只有 `<FlagNative/>` 背书、`.galaxy` 里没有声明的，
   单源取数会整个漏掉它们 —— 又一个"遗漏静悄悄"的实例。

### 14.6 这轮的判据教训

> **一条门禁的价值 = 覆盖率 × 判据强度，两者任一为零则整体为零。**

round25 的台账门禁判据很强（集合等式 + 反向对照），但覆盖率只有 1/14，
所以它当时守住的东西比看起来少得多。扩族这个动作本身没有技术含量，
但它把 74 个"从来没人看过一眼"的符号从阴影里拖了出来 —— 而这 74 个里，
没有一个在扩族之前被任何检查报过。

推论：**新建一条门禁之后，紧接着要问的不是"它绿了吗"，而是"它管着多少"。**
"""


def main() -> int:
    if not README.exists():
        print(f"[patch] 找不到 {README}")
        return 1
    txt = README.read_text(encoding="utf-8")
    if MARK in txt:
        print("[patch] README 已含 round26 章节，无需改动")
        return 0
    txt = txt.rstrip("\n") + "\n" + SECTION.lstrip("\n") + "\n"
    README.write_text(txt, encoding="utf-8")
    print(f"[patch] 已追加 §14 round26 章节 -> {README}（现 {txt.count(chr(10))} 行）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
