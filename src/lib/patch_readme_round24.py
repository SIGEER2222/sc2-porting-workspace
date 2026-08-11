"""幂等给 README 追加 round24 章节。

不用 Edit 直接贴是因为正文里全是反引号和竖线，走 shell 会被吃掉；
写成脚本文件再执行是 round7 就记过的教训。
"""
import pathlib
import sys

README = pathlib.Path(__file__).parent / "scripts" / "cmlib" / "README.md"
MARK = "## 11. round24"

SECTION = """

## 11. round24：把"范围外不封装"的判定推翻（AI 战术过滤族入库）

`AIFilter` / `AIGetFilterGroup` / `AISetFilter*` 这一族，从 round12 起就被写在案上
"刻意不包"，理由是：**它们在 `Tactical/TacticalAI.galaxy`，不是 core 默认 include，
包了有真机静默编译失败的风险**。这条判定在案上躺了 12 轮。round24 把它推翻了。

### 11.1 三条反证

1. **`aifilter` 不是 typedef，是引擎内建 handle 类型。**
   `natives.galaxy` 全文 0 个 typedef，却在 1203/1204 行直接写
   `DataTableSetAIFilter(bool, string, aifilter)` —— 默认 include 链的核心文件
   自己就在用这个类型名。类型名从来就不需要 include TacticalAI。
2. **这一族在 `NativeLib.TriggerLib` 里全部带 `<FlagNative/>`。**
   这正是 §9.1 / §10.2 已经确立的权威判据：**SC2 的 native 符号表是引擎内建的，
   `.galaxy` 里的 `native` 声明只是编辑器/lint 元数据。**
   同一条判据在 round22 用来给 `StatEvent*` 翻案，这里再用一次。
3. **真机探针六档全 PASS，而且验到了返回值。**

### 11.2 六档探针设计（`probe_aifilter.py`）

判据设计吃了 §10.4 的教训：**要下"能用"的结论，就必须验到返回值可用。**
所以档位沿两条正交轴铺开 —— 纵轴是"验多深"，横轴是"是否自带 native 声明"。

| 档 | 验什么 | 结果 |
|---|---|---|
| `baseline` | 空 MapScript 哨兵（排除环境问题） | PASS |
| `decl` | `aifilter lv_f;` 局部变量声明能否编译 | PASS（类型名可用） |
| `call` / `calln` | 全链路裸调 vs 自带 7 条 native 声明 | 双双 PASS（**裸调即可用**） |
| `value` / `valuen` | `AIFilter(1) != null` + `AIGetFilterGroup` 产出**非空组** | 双双 **USABLE** |

`value` 档把每层结论各绑一个可观测单位：Marauder = 句柄非 null，
Thor = 过滤真的产出了东西，Banshee = 全链路没被运行时错误中断。
意外收获：这是在**人类玩家 player 1** 上过的 —— 不需要该玩家挂 AI，
比预期宽松（原本担心踩 round5 那个"`AISetUserInt` 只对已挂 AI 玩家有效"的坑）。

**本模块最终不 include `TriggerLibs/Tactical/TacticalAI`**：既然裸调实证可行，
就没必要引入它 —— 那个文件里除 native 外还有一批普通 Galaxy 函数
（`AICampSkirDiffTest` / `AITacticalRetreat` …），宿主地图若也 include 它，
就有**函数重定义**的风险，而那是"SC2 静默丢弃整个 MapScript"最经典的诱因。

### 11.3 `callall` 档：一次没能定位成因的失败，就老实记成没定位

`value` 档只验了 6 个 setter。按"判据必须覆盖结论"的纪律，那就只能对这 6 个下结论。
于是加 `callall` 档，把 TacticalAI 里其余 setter 一次性全调，参数**全取最宽松值**
（否则 Thor 缺席时无法区分"这个 setter 坏了"和"我把条件写太严"）。

结果：**Thor 缺席、Banshee 在** —— 没崩，但过滤成了空组。
再加 `callmid` 档二分，只留 5 个语义确定的数值型 setter
（Range / LifeLost / LifePercent / LifeSortReference / Shields）→ **USABLE**。

所以成因落在剩下那 6 个语义型 setter 里，但**具体是哪个没二分出来**。
处置就按事实写：那 6 个 **不封装**，README 和头注释里都写明"未拿到正向证据、下轮继续"。
不封装不是因为它们坏，是因为**我还没有能支撑"它能用"这句话的证据**。

### 11.4 `AIUnitGroupGetValidOrder`：又一个"可调用不可用"

`order` 档拿到 `NULL_RETURN`。但这个结论一开始是**不可归因**的 ——
返回 null 可能是"函数坏"，也可能是"我喂进去的 order 本身就是 null"。

于是加 `order2` 档，把**前提**也绑上可观测单位：
Marauder = 输入 unitgroup 非空，Thor = order 构造成功，SiegeTank = 最终结论。
跑出来 Marauder ✓ / Thor ✓ / SiegeTank ✗ —— 前提全部成立，它仍然返回 null。
坐实为 §10.4 那一类"可调用不可用"，**不封装**。

> 可复用判据 ④：**结论型断言旁边要放前提型断言。**
> 只断言结论，失败时你分不清是"结论不成立"还是"前提没建立"，
> 只能靠二分回头补。前提断言的成本是一行，省下的是一整轮。

### 11.5 顺带修掉的一个判定链缺陷（和 §9.3 同源）

只跑 `baseline group order` 三个子集时，`decide()` 打印了
"call/calln 都没能 PASS" —— 可这两档**根本没跑**。
这就是 §9.3 那个事故的同款：**把"没跑"说成"没过"。**

修法：`decide()` 加 `SUBSET_ONLY` 分支，主结论严格按**实跑档数**分支；
附属族（group / order2）的结论独立先报，不依赖主结论是否存在。
同一条纪律 round23 已经在 `run_matrix_round10.py --only` 上落过一次
（单档跑绝不打印"三档矩阵全部符合预期"），这轮是它在探针侧的第二次落地。

### 11.6 门禁加固

`check_cmlib.load_engine_symbols()` 现在追加加载
`GameData` / `TriggerLibs` / `Tactical` 下所有 `.galaxy` 的 **native 声明**，
引擎符号表 9865 → **9886**。

关键克制：**只收 `native` 声明，绝不收普通 Galaxy 函数。**
把普通库函数也当成"已知符号"收进来，等于亲手拆掉
"裸调库函数 → 真机静默编译失败"这条防线 —— 那正是 round4 抓到的头号杀手。
"""


def main() -> int:
    text = README.read_text(encoding="utf-8")
    if MARK in text:
        print("[readme] round24 章节已存在，无需改动")
        return 0
    README.write_text(text.rstrip() + SECTION, encoding="utf-8")
    print("[readme] 已追加 round24 章节")
    return 0


if __name__ == "__main__":
    sys.exit(main())
