# -*- coding: utf-8 -*-
"""round26b：把 marker 单位标记的「不可观测性」取证与判据降级写进 README。

幂等：靠 MARK 标记检测，已存在则不重复追加。
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
README = os.path.join(HERE, "scripts", "cmlib", "README.md")

MARK = "## 15. round26b：marker 单位标记"

SECTION = """

---

## 15. round26b：marker 单位标记的不可观测性取证，与一次**有证据的判据降级**

round26 的三档真机矩阵第一次跑出 **BAD**：内联源码版与依赖挂载版都是
`PARTIAL 624/626`，反向对照正常 FAIL。两档失败标签完全一致：

```
marker.aifilter.roundtrip, marker.unit.add
```

**两档同因 + 反向对照仍正确 FAIL = 真实缺陷，不是瞬态。** 这一节记录怎么把
它定位成「引擎性质不可观测」而不是「库有 bug」，以及为什么这次降级判据是
对的、而不是在放水。

### 15.1 现象

```galaxy
CMLib_UnitMarkerAdd(lv_r27u, lv_r27m);
CMLibTest_MarkTag(CMLib_UnitMarkerCount(lv_r27u, lv_r27m) >= 1, "marker.unit.add");  // 实得 0
```

库封装是薄透传 + null 守门，没有写反的余地：

```galaxy
void CMLib_UnitMarkerAdd(unit lp_unit, marker lp_marker) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    if (lp_marker == null) { return; }
    UnitMarkerAdd(lp_unit, lp_marker);
}
```

### 15.2 四条独立取证

1. **marker 句柄是活的，不是死壳。** 同一个 `lv_r27m` 上，
   `marker.matchflag.set` / `marker.matchflag.clear`（`MarkerSetMatchFlag`
   → `MarkerGetMatchFlag` 往返）与 `marker.dt.roundtrip`
   （`DataTableSetMarker` → `DataTableGetMarker`）**四条真机全过**。
   所以 `Marker()` 造出来的对象引擎认、能改、能存取 —— 问题不在生产端。

2. **`UnitMarkerAdd` 在整棵官方参考树里零调用。** 扫过 core.sc2mod、
   三部战役（Liberty / Swarm / Void）、starcoop、alliedcommanders、
   SC Evo Complete，`UnitMarkerAdd` 一次都没被调过。而 `UnitMarkerCount`
   的官方用法**全部**是这一种形态：

   ```galaxy
   marker AIMarker (unit aiUnit, string name) {
       marker mark = MarkerCastingUnit(name, aiUnit);
       MarkerSetMatchFlag(mark, c_markerMatchLink, true);
       MarkerSetMatchFlag(mark, c_markerMatchCasterPlayer, true);
       return mark;
   }
   // ...
   if (UnitMarkerCount(unitToCheck, mark) > 0) { return null; }  // 已被标记过，跳过
   // ...
   AICast(aiUnit, ord, mark, retreat);   // <-- 标记是**引擎**在这一步打上去的
   ```

   即 marker 是引擎为 `AICast` 做的**防重复施法记账**：写端在引擎里，
   脚本只有读端。

3. **marker 族 native 没有 Id / Duration 的 setter。** 全集只有：

   | 生产 | 施法者 | 匹配 | 单位标记表 | DataTable |
   |---|---|---|---|---|
   | `Marker` / `MarkerCastingPlayer` / `MarkerCastingUnit` | `MarkerSet/GetCastingPlayer` · `MarkerSet/GetCastingUnit` | `MarkerSet/GetMatchFlag` · `MarkerSet/GetMismatchFlag` | `UnitMarker` / `UnitMarkerAdd` / `UnitMarkerCount` / `UnitMarkerRemove` | `DataTableSet/GetMarker` |

   而 `c_markerMatchId = 0` 明确说明 **Id 参与匹配**。脚本能设 link、能设
   施法者、能设匹配标志，唯独设不了 Id —— 造不出带引擎身份的完整 marker。

4. **替代假设也一并证伪。** 「是不是少设了 match flag」是最像的另一种解释
   （官方 `AIMarker()` 确实必设两个 flag）。所以这轮没有靠推断结案，而是把
   三种变体做成 bank 探针一次跑完，让数据自己说话：

   | bank 键 | 变体 | 真机实测 |
   |---|---|---|
   | `Result/MkPlain` | 裸 `Marker(link)`，不设任何 flag（原失败写法） | **0** |
   | `Result/MkLinkPre` | `MarkerCastingUnit("Abil/Snipe/AI", u)` + `c_markerMatchLink`，**add 前**（对照基线） | **0** |
   | `Result/MkLink` | 同上，**add 后** | **0** |
   | `Result/MkOfficial` | 再叠 `c_markerMatchCasterPlayer`（逐字复刻 `AIMarker()`） | **0** |
   | `Result/MkAIWith` / `Result/MkAIWithout` | AI 线 `AISetFilterMarker` 打标记 / 不打标记两态 | **0 / 0** |

   **替代假设就此证伪。** 连「真实技能 link（`Abil/Snipe/AI` 就是
   core.sc2mod `RequirementsAI.galaxy` 里 `c_MK_Snipe` 的原值）+
   `MarkerCastingUnit` + 两个官方 match flag」这种逐字复刻 `AIMarker()` 的
   写法都是 0，且 add 前 / add 后**没有任何变化** —— 不是 flag 设漏了，是
   脚本构造的 marker 根本进不了单位的标记表。15.2 的结论至此坐实。

   探针留在原地，只记录、不判定。**将来任一变体出现非 0，就能凭证据把硬
   断言提回来** —— 降级不是删除，是把结论换成一个自带观测点的开放问题。

### 15.3 为什么这次降级不是放水

判据坏死有两种：**恒红**（断言与被测系统设计冲突）和**恒绿**（同义反复）。
`marker.unit.add` 属于第一种 —— 它断言的根本不是库的行为，而是
「引擎的 `UnitMarkerAdd` 对脚本构造的 marker 生效」这条**引擎性质**，而这
条性质在纯脚本环境里没有任何可观测路径。

对照 round25 处置 `AISetFilterCanAttackEnemy` 的先例，判断标准是同一条：

> **有读回路径 / 独立期望值 → 写双向硬断言；没有 → 降级为诊断探针，
> 只记录不判定。**

所以这次动的只有「往返」这一条，**守门判据一条没减**：
`marker.create` / `marker.create.empty` / `marker.unit.count.clean` /
`marker.unit.remove` / `marker.unit.nullsafe` / `marker.cast.player` /
`marker.cast.unit` / `marker.cast.degrade` / `marker.matchflag.set` /
`marker.matchflag.clear` / `marker.matchflag.oob` / `marker.dt.roundtrip` /
`marker.dt.miss` 全部保留为硬断言。封装也一个没删 —— 配合 `AICast` 写入的
marker 时，读路径依然是有效能力。

**"修 bug ≠ 放宽判据" 的边界在这里：** 删掉一条**能测出库缺陷**的断言是
放水；删掉一条**测的是环境而不是库**的断言是纠错。区别在于有没有拿到证据、
以及降级后有没有留下可复查的观测点。这两样这轮都做了。

### 15.4 顺带揪出一条**恒绿**判据

`marker.aifilter.lifepermarker.roundtrip` 一直是绿的，看起来在守
`AISetFilterLifePerMarker` 的 marker 语义。但它绿得有问题：

本局单位实际标记数为 **0**，引擎把 life-per-marker 退化成了纯生命门槛
（门槛 `1.0` 放行、`99999.0` 筛掉，响应单调）。也就是说这条判据证明的是
**`each` 形参被正确透传**，跟 marker 形参一点关系都没有 —— 换个 marker、
甚至传 null，它照样绿。

没删它（它对 `each` 仍是有效判据），但在源码里写死了注释，避免下一轮有人
把它当 marker 覆盖率来用。**一条判据"绿着"和"守着你以为它守的东西"是两回
事**，这是本轮第二次踩到同一个模式。

### 15.5 教训

> **判据失败时的第一个问题不是"怎么让它变绿"，而是"它到底在断言谁"。**

`marker.unit.add` 断言的主语其实是引擎，不是库。主语搞错的判据，无论怎么
调都不会给出有用信息 —— 修它、删它、放宽它，三条路全是错的，唯一对的是
**把它换成能回答问题的观测**。

配套推论：**零官方调用的 native 是高危信号。** `UnitMarkerAdd` 在
`natives.galaxy` 里声明得清清楚楚、签名合理、静态检查全过、运行时也不报错
—— 唯一的异常信号就是"全世界没人调过它"。这一条比任何静态检查都更早地
指向了正确答案，值得写进例行排查顺序。
"""


def main():
    if not os.path.exists(README):
        print("[round26b] 找不到 README：%s" % README)
        return 1
    with io.open(README, "r", encoding="utf-8") as f:
        text = f.read()
    if MARK in text:
        print("[round26b] README 已含 round26b 章节，无需改动")
        return 0
    text = text.rstrip("\n") + SECTION
    with io.open(README, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("[round26b] README 已追加 round26b 章节 -> %d 行"
          % (text.count("\n") + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
