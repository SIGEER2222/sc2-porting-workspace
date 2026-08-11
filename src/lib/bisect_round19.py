"""round19 模块级二分器：按模块在 pre19 / round19 两份快照间切换。

背景：round19 向 9 个模块追加了 65 个封装。静态门禁（含全量 typecheck 与新增的
verify_natives 符号核对）全绿，真机却三档全灭 —— 典型的「只有真机能兑现的编译
失败」。既然静态已榨干，就用真机二分把嫌疑模块夹出来。

用法：
    python bisect_round19.py pre  conv trig fx     # 这几个模块退回 pre19，其余保持 round19
    python bisect_round19.py all-round19           # 全部恢复 round19
    python bisect_round19.py all-pre               # 全部退回 pre19（= round18 状态）
"""
import shutil
import sys
from pathlib import Path

LIB = Path(__file__).resolve().parent
DST = LIB / "scripts" / "cmlib"
R19 = LIB / ".bak" / "round19-lib"
PRE = LIB / ".bak" / "pre19-lib" / "scripts" / "cmlib"

MODULES = ["conv", "trig", "fx", "text", "unit", "game", "geo", "ai", "udata"]


def apply(pre_mods):
    for m in MODULES:
        src = PRE if m in pre_mods else R19
        for suffix in (f"cmlib_{m}.galaxy", f"cmlib_{m}_h.galaxy"):
            shutil.copy(src / suffix, DST / suffix)
    tag = ", ".join(sorted(pre_mods)) or "（无）"
    print(f"[bisect] 退回 pre19 的模块: {tag}")
    print(f"[bisect] 保持 round19 的模块: "
          f"{', '.join(m for m in MODULES if m not in pre_mods) or '（无）'}")


mode = sys.argv[1] if len(sys.argv) > 1 else "all-round19"
if mode == "all-round19":
    apply(set())
elif mode == "all-pre":
    apply(set(MODULES))
elif mode == "pre":
    mods = set(sys.argv[2:])
    bad = mods - set(MODULES)
    if bad:
        print(f"[bisect] 未知模块: {bad}")
        sys.exit(2)
    apply(mods)
else:
    print(__doc__)
    sys.exit(2)
