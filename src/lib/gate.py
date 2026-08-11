"""CMLib 门禁总入口 —— 一条命令跑全部静态关卡，任一关不过即非零退出。

为什么必须有这个文件（round18 血泪，代价是两轮假绿）：
  `check_cmlib.py` 只做「符号存在性 + 实参个数 + G1001 + 注释常量」检查，
  **完全不做类型检查**。round16 在 `cmlib_path.galaxy` 写下
      if (... || (lp_color == null))        // color 是值类型，不可与 null 比较
      color CMLib_RouteColorGet(...) { return null; }   // 同上
  这是 Galaxy 的**编译期错误**，而 SC2 对编译失败的反应是
  **静默丢弃整个 MapScript**（不报错、不写日志、InitMap 根本不被调用）。
  于是：静态门禁 PASSED 0 错 0 警 → 交付物照常构建 → round17 矩阵恰好因真人局
  一直没复跑 → 缺陷潜伏两轮，直到 round18 真机矩阵内联/依赖两档同时真 FAIL 才暴露。

  能抓出它的工具（`build_typecheck_unit.py` + `tools/analysis/galaxy-lint.mjs`）
  仓库里**一直都有**，只是没被接进门禁——「工具存在」不等于「关卡存在」。
  本文件把它钉成必过项。

round19 又补一刀（代价是又一轮三档全灭）：
  `tools/analysis/galaxy-lint-suppressions.json` 的 `R3-undeclared` 规则把
  **所有** "Undeclared symbol:" 一律抑制。该规则对 CMRE/RO 那种跨库工程成立，
  对 CMLib 却是灾难 —— CMLib 的编译单元只 include `TriggerLibs/natives` + 自己，
  符号集封闭可枚举，"未声明"就是真错。round19 在 cmlib_text.galaxy 写了
  `c_maxInt`（Galaxy 根本没有这个常量），lint 报了、被抑制了、门禁全绿了，
  真机整图消失。故新增 `verify_natives.py` 作为**不受抑制**的符号关卡。

round22 第三刀（代价：一轮 rc=1 + 一次错误归因）：
  给 runner 新增「断言会计」判据时，`if not acct_ok -> PARTIAL` 被插在了
  `sentinel` 门**之前**。反向对照图（依赖指向不存在路径、期望地图起不来）
  passed=0、sentinel=0，于是被判成 `PARTIAL 断言会计不符` 而不是 `FAIL`。
  表面症状是三档矩阵 rc=1、看着像"通用库回归"；实际库好得很（内联/依赖两档
  PASS 509/509）。真正的危害是**反向对照失去了产出 FAIL 的能力** —— 它存在的
  唯一意义就是排假阳性，一旦哑火，正向两档的 PASS 也不再能证明任何事。
  这类缺陷语法完全合法、类型检查一路绿灯，只有针对"判定链本身"的测试能抓。
  故新增 `test_verdict_order.py` 并排在**第一关**：判定链不可信时，
  后面所有关卡跑出来的结论都没有意义。

round24 第四刀（代价：一次假 FAIL + 一次假 ALL PASSED）：
  `verify_natives.py` 成功路径打印 `'\u2713'`(✓)。Windows 控制台默认 GBK，
  编不出这个字符 -> `UnicodeEncodeError` -> rc=1 -> 门禁判「verify_natives
  FAILED」。可它的核对**通过了**，崩的是最后那句"恭喜"。反过来，只要调用者
  事先设了 `PYTHONIOENCODING=utf-8`，同一份代码就 ALL PASSED。
  **一个结论取决于调用者有没有设环境变量的门禁，等于没有门禁。**
  更隐蔽的是 gate.py 自己：它用 `encoding="utf-8"` 解码子进程输出，子进程却
  按 GBK 编码，编解码口径不一致，中文被 `errors="replace"` 悄悄糊成乱码 ——
  "没报错但证据已经脏了"。
  故：① 子进程统一 `PYTHONIOENCODING=utf-8`；② 常驻入口脚本加编码自卫；
  ③ 新增 `test_console_encoding.py` 钉成第二关（含反向对照，防探测器自身写坏后恒绿）。

关卡顺序（快的在前，失败即止；前三关查的是"校验器自身"）：
   1. test_verdict_order.py       判定链顺序（sentinel 门必须排在所有次级判据之前）
   2. test_console_encoding.py    控制台编码自卫（防 GBK 下 UnicodeEncodeError 假 FAIL）
   3. test_type_reachability.py   句柄可达性门禁自检（四向对照，防第 6 关写坏成恒绿）
   4. check_cmlib.py              符号/实参/盲区/文档漂移/注释常量
   5. check_native_ledger.py      原生符号台账（受管族内：封装 或 显式登记拒绝，二选一）
   6. check_call_scope.py         调用范围四层可见性（A内/B官方native/R须登记/C禁止，见下）
   7. check_type_reachability.py  句柄类型可达性（形参消费 ⊆ 返回值生产 ∪ 登记外部来源）
   8. check_g1001.py              局部变量置顶（另一种静默丢图形态）
   9. verify_natives.py           引擎符号存在性 / 实参个数 / c_* 常量（不受 lint 抑制）
  10. build_testmap.py            刷新 _testmap_build（typecheck 单元依赖它取 selftest+MapScript）
  11. build_typecheck_unit.py     合并成单一编译单元
  12. galaxy-lint.mjs             **全量类型检查** ← 唯一能抓 color==null 这类的关卡

round27 新增第 3 / 第 6 关（代价：三个句柄类型的封装接口死了不知道多少轮）：
  `CMLib_AIFilterMarkerCount(filter, min, max, marker)` 静态检查全绿、真机也"通过"，
  但库里**没有任何函数能造出一个 marker** —— 调用方唯一能传的就是 null，
  而库自己的守门会把 null 直接忽略。这个接口从出生起就是死的，
  所有现存判据（符号存在、实参个数、类型正确、真机不崩）没有一条能发现。
  判据：公开 API 形参出现的句柄类型集合 A ⊆ 返回值出现的 B ∪ 头文件登记的 C。
  A ⊄ B∪C 说明"库要求你给的东西，库自己造不出来，也没说清从哪来"。

round25 新增第四关（代价：一个符号在台账上消失了两轮没人发现）：
  round24 的头文件里维护着两张人肉名单——「已验证封装」和「未获证据故意不封装」。
  `AISetFilterMelee` 两张都不在，凭空蒸发。它不是被判错，是**根本没进入判断**。
  这类漏记靠再读一遍名单发现不了：你只会核对名单上有的，不会想到名单缺了谁。
  修法不是"下次仔细点"，是把名单变成**可机器推导的集合等式**：
      引擎声明全集(自动扫) == 实际调用(自动扫) ∪ 登记拒绝(人写) ，且两者不相交
  三个集合两个自动、一个人写，人写的那个只能"多"不能"少"——少了立刻报 ghost。
  反向对照已做：删掉登记行立刻 FAIL(ghost 1)，加回来 PASS(24 = 23 + 1)。
  这条是记忆里那条铁律的直接落地：**写进报告的性质，必须有一个进程在守。**

round27b 新增第六关（代价：同一个「能不能调」的口径连错四次四个方向）：
  第一版把闭包根写成 `natives`，当场把 `SoundPlay`（有函数体的普通库函数，
  住在 `NativeLib.galaxy`）误判成禁止调用 —— 方向是反的（NativeLib include natives）。
  第二版又把它当成「在不在闭包」的一维布尔，结果把整个 AI filter 一族
  （`TacticalAI.galaxy` 里的 `native` 声明，闭包外但官方白纸黑字）判成范围外要拒绝；
  更早一版用 `<FlagNative/>` 当唯一判据，又把 `PointFromId`/`OrderSetPlayer`
  （natives.galaxy 声明、但不在 FlagNative 集合里）误杀。
  真正正确的轴是「**引擎内建 native**」vs「**有函数体的库函数**」：
  前者不声明也能调，后者不在编译单元就是死。`check_call_scope.py` 把这个四层模型
  （A 单元内 / B 官方 native 台账不阻断 / R 须 `// @scope-flagonly` 登记 / C 禁止）
  钉成第 6 关，并自带五向反向对照（A 现状 / R 未登记 / C 未声明 / D 登记后放行 /
  E 官方 native 不误伤），防它自己写坏成恒绿或恒红。
  登记语法：`// @scope-flagonly <符号> <为什么可以接受>`，集合等式
  `被调用R层符号 == 登记集合`，多一个(幽灵)少一个(过期)都失败。

用法：
    python gate.py            # 全跑
    python gate.py --fast     # 跳过 7~9（仅在急着看符号层结论时用，不可作为交付依据）
"""
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 控制台编码自卫（round24）
# Windows 控制台默认 GBK。子进程输出里只要混进一个非 GBK 字符（实测：pytest
# 输出里的 'ʧ' U+02A7），print 就抛 UnicodeEncodeError，gate.py 以 rc=1 退出。
# 那是「打印崩了」不是「门禁没过」——一次典型的**假 FAIL**。
# 门禁自身绝不允许因为输出编码而误判，故只改 errors 策略、不改 encoding
# （改成 utf-8 会让 GBK 控制台上的中文全变乱码，治了 A 病生 B 病）。
# ---------------------------------------------------------------------------
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except Exception:
        pass

LIB = Path(__file__).resolve().parent
WS = LIB.parent.parent
PY = sys.executable
UNIT = WS / ".cache" / "cmlib-typecheck" / "cmlib_unit_all.galaxy"

NODE = "node"


# 子进程环境：强制 UTF-8 输出。
# 两个理由，缺一不可：
#   1) 本文件用 encoding="utf-8" 解码子进程输出，子进程若按 GBK 编码就是
#      **编解码口径不一致**，中文会被 errors="replace" 悄悄糊成乱码；
#   2) 子进程自己打印 '✓'(U+2713) 之类字符时会在 GBK 下抛 UnicodeEncodeError
#      而以 rc=1 退出 —— 门禁会把「子进程打印崩了」误判成「这一关没过」。
#      实测：verify_natives.py 在 GBK 控制台必挂，UTF-8 下 ALL PASSED，
#      同一份代码两种结论，这种门禁等于没有门禁。
_CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}


def run(title: str, cmd: list[str], cwd: Path, quiet_ok: bool = True) -> tuple[bool, str]:
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                       encoding="utf-8", errors="replace", env=_CHILD_ENV)
    out = (p.stdout or "") + (p.stderr or "")
    ok = p.returncode == 0
    print(f"\n{'=' * 72}\n[gate] {title}\n{'=' * 72}")
    if ok and quiet_ok:
        tail = [l for l in out.strip().split("\n") if l.strip()][-4:]
        print("\n".join(tail))
    else:
        print(out.strip()[-6000:])
    return ok, out


def typecheck_errors(out: str) -> int:
    """从 galaxy-lint 的 JSON 尾巴里抠 errors 计数。

    不用 json.loads 整体解析：脚本会在 JSON 前打印「抑制已知良性诊断 N 条」的
    人类可读抬头，整体解析必炸。只认 summary 里的 errors 行最稳。
    """
    for line in out.split("\n"):
        s = line.strip().rstrip(",")
        if s.startswith('"errors"'):
            return int(s.split(":")[1].strip())
    return -1  # 解析不到 -> 当作失败，宁可误报不可漏报


# ---------------------------------------------------------------------------
# 关卡表（round27 改表驱动）
#
# 为什么不再手写 "N/9"：round27 往链里插两关，要把后面每一关的编号和文档字符串
# 全改一遍。这种"改动量正比于列表长度"的写法迟早会漏改一处，而漏改的表现是
# **编号错乱但门禁照跑照绿** —— 又一个恒绿形态。编号现在从表长自动推导，
# 插关只需要加一行。
#
# 字段：(key, 标题, 命令, cwd, 是否属于 --fast 跳过的重型尾段)
# ---------------------------------------------------------------------------
def _steps() -> list[tuple[str, str, list[str], "Path", bool]]:
    return [
        # 前三关查的都不是库，是**校验器自身**。
        # ① 判定链顺序：真机矩阵的 PASS/FAIL 由 runner 分支顺序 + classify() 共同
        #    决定，这两处一旦错位，后面所有关卡的结论都失去意义（尤其是反向对照
        #    拿不到 FAIL = 排假阳性的防线被拆）。
        ("verdict_order", "判定链顺序 · sentinel 门优先 (test_verdict_order.py)",
         [PY, "test_verdict_order.py"], LIB, False),
        # ② GBK 控制台下的 UnicodeEncodeError 会把「打印崩了」伪装成「关卡没过」，
        #    设了 PYTHONIOENCODING 又会全绿。结论随环境变量摇摆的门禁不可信。
        ("console_encoding", "控制台编码自卫 · 防假 FAIL (test_console_encoding.py)",
         [PY, "test_console_encoding.py"], LIB, False),
        # ③ round27 新增：句柄可达性门禁**自己**的四向对照
        #    （现状 FAIL / 补登记 PASS / 空理由仍 FAIL / 引擎符号读不全 fail-closed）。
        #    没有它，下面那关哪天写坏成恒绿也没人知道。
        ("test_type_reachability", "句柄可达性门禁自检 · 四向对照 (test_type_reachability.py)",
         [PY, "test_type_reachability.py"], LIB, False),

        ("check_cmlib", "符号 · 实参 · 盲区 · 文档漂移 · 注释常量 (check_cmlib.py)",
         [PY, "check_cmlib.py"], LIB, False),
        # round25 台账关：治的是**漏记**。AISetFilterMelee 既不在"已验"名单也不在
        # "未封装"名单，凭空消失两轮，人肉核对发现不了（你只会核对名单上有的）。
        # 判据是集合等式：引擎声明全集 == 实际调用 ∪ 显式登记拒绝，且两者不相交。
        ("native_ledger", "原生符号台账 · 封装或登记拒绝二选一 (check_native_ledger.py)",
         [PY, "check_native_ledger.py"], LIB, False),
        # round27b 新增：**能不能调不是布尔，是四层可见性**。
        # A=编译单元内有声明(安全) / B=闭包外但官方 .galaxy 有 native 声明(可调,只台账不阻断) /
        # R=闭包外+无官方 native 背书(「可调用≠可用」，必须逐条 `// @scope-flagonly` 登记) /
        # C=既不在闭包也没任何 native 背书(禁止调用 → SC2 静默丢整个 MapScript)。
        # 判据：库外部调用面 ⊆ A ∪ B ∪ (R ∩ 登记)；C 层硬失败，R 层必须登记且不能过期。
        # 这个口径当初连错四次四个方向（拿 natives 当根漏 NativeLib / 一维「在不在闭包」轴选错
        # / 用 <FlagNative/> 当判据误杀 PointFromId / 闭包根写错），故门禁自带五向反向对照
        # （A现状 PASS / R未登记 FAIL / C未声明 FAIL / D登记后放行 PASS / E官方native不误伤 PASS）。
        ("call_scope", "调用范围四层可见性 · A内/B官方native/R须登记/C禁止 (check_call_scope.py)",
         [PY, "check_call_scope.py"], LIB, False),
        # round27 新增：**可编译 ≠ 可达**。封装函数收了某句柄类型做形参，库自己却
        # 造不出该句柄，调用方只能喂 null 撞守门 —— 接口是死的，静态检查全绿。
        # 判据：形参消费的句柄类型 ⊆ 返回值生产的 ∪ 头文件 @type-external 登记的。
        ("type_reachability", "句柄类型可达性 · 消费 ⊆ 生产 ∪ 登记 (check_type_reachability.py)",
         [PY, "check_type_reachability.py"], LIB, False),

        ("check_g1001", "局部变量置顶 G1001 (check_g1001.py)",
         [PY, "check_g1001.py"], LIB, False),
        ("verify_natives", "引擎符号 · 实参 · c_* 常量，不受 lint 抑制 (verify_natives.py)",
         [PY, "verify_natives.py"], LIB, False),

        ("build_testmap", "刷新测试地图构建目录 (build_testmap.py)",
         [PY, "build_testmap.py"], LIB, True),
        ("build_typecheck_unit", "合并单一编译单元 (build_typecheck_unit.py)",
         [PY, "build_typecheck_unit.py"], LIB, True),
    ]


def main() -> int:
    fast = "--fast" in sys.argv
    failed = []

    steps = _steps()
    total = len(steps) + 1  # +1：最后的 galaxy-lint 全量类型检查

    for idx, (key, title, cmd, cwd, heavy) in enumerate(steps, start=1):
        if heavy and fast:
            continue
        ok, _ = run(f"{idx}/{total} {title}", cmd, cwd)
        if not ok:
            failed.append(key)

    if fast:
        print("\n[gate] --fast：跳过构建 + typecheck 尾段。"
              "⚠️ 此模式的 PASS 不足以作为交付依据（color==null 这类只有 typecheck 抓得到）")
    else:
        ok, out = run(f"{total}/{total} 全量类型检查 (galaxy-lint.mjs)",
                      [NODE, "tools/analysis/galaxy-lint.mjs",
                       str(UNIT.relative_to(WS)).replace("\\", "/")], WS,
                      quiet_ok=False)
        n = typecheck_errors(out)
        print(f"\n[gate] typecheck errors = {n}")
        if n != 0:
            failed.append(f"typecheck({n} 个 error)")

    print(f"\n{'=' * 72}")
    if failed:
        print(f"[gate] FAILED —— 未通过的关卡: {', '.join(failed)}")
        return 1
    print(f"[gate] ALL PASSED（{total} 关）—— 判定链 + 编码自卫 + 可达性自检 + 符号层 + "
          "原生台账 + 句柄可达性 + G1001 + 引擎符号/常量 + 全量类型检查 全绿")
    print("[gate] 提醒：静态全绿仍不等于真机能跑，交付前必须过三档真机矩阵。")
    return 0


sys.exit(main())
