"""阳性对照（canary）：把 round-10 的 SplitAt 修复单独回退，验证新断言真的有牙。

新增断言全过 != 新增断言能抓 bug。必须把被修的缺陷人为放回去跑一次，
看见它 FAIL，才能证明这批断言不是「恒真装饰」。

  python canary_round10.py break    # 注入旧的 off-by-one
  python canary_round10.py restore  # 还原修复
"""
import sys
from pathlib import Path

CORE = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\src\lib"
            r"\scripts\cmlib\cmlib_core.galaxy")

FIXED = """        if ((lv_current == lp_index)) {
            if ((lv_pos == 1)) {
                return "";
            }
            return StringSub(lv_rest, 1, lv_pos - 1);
        }
        lv_rest = StringSub(lv_rest, lv_pos + lv_sepLen, StringLength(lv_rest));"""

BROKEN = """        if ((lv_current == lp_index)) {
            if ((lv_pos == 0)) {
                return "";
            }
            return StringSub(lv_rest, 1, lv_pos);
        }
        lv_rest = StringSub(lv_rest, lv_pos + lv_sepLen + 1, StringLength(lv_rest));"""

mode = sys.argv[1] if len(sys.argv) > 1 else "break"
txt = CORE.read_text(encoding="utf-8")
old, new = (FIXED, BROKEN) if mode == "break" else (BROKEN, FIXED)
if old not in txt:
    print(f"[canary] 已处于 {mode} 的目标态或锚点不匹配")
    sys.exit(0)
CORE.write_text(txt.replace(old, new, 1), encoding="utf-8")
print(f"[canary] {mode} 完成")
