"""基底血统门禁的守护者（2026-08-10 事故治本）。

事故复盘
--------
`mpq_inject_workspace_kernel.py` 原本是"从 VibeT4 生成 VibeT5"的纯内核实验脚本，
默认基底写死 `C:\\tmp\\VibeT4.sc2map`。后来它被复用成"重建 gen 图"的管线入口，
两个用途共用一个脚本、而默认值指向错误的那一个。结果：以 VibeT4 为基底产出了
名为 `VibeDeadOfNight-Gen.SC2Map` 的图（4,657,135 B；真 gen 血统是 5,497,677 B）。

该图**通过了全部 16 项静态自检**，因为那 16 项全是内核**内部**性质
（merged_fix 指纹 / BankLoad 处数 / 无重定义 / tagCache / 悲观响应 …），
对"基底血统"完全无感。真机后果：MapScript 挂了 `LibVibeInvokeDispatch_active`
却没有 `VIBE_FORWARD_PROTOS` 前向原型区，invoke 层引用的 MapScript 本体函数
（gf_* / auto_gf_*_TriggerFunc / gt_*_Func）全部无声明 → Galaxy 编译失败 →
**SC2 静默丢弃整个 MapScript**（不报错、不写日志、静态 lint 照样 0 错误）。
表现为 `kernel_registered=false` + **0 ScriptError**，被误诊成 Bank handle 逻辑回归，
排查方向偏到内核 `EnsureBankLoaded` 上，浪费了整轮。

方法论
------
- #3 可调用 ≠ 可用：**探针判据必须覆盖你要下的结论**。这里要下的结论是"这张图能跑
  tier100"，而自检覆盖的只是"内核注入对不对"，中间缺了"基底血统"这一环。
- #1 校验器自身要有校验器：门禁写进脚本还不够，门禁本身也会腐烂 —— 本文件即其守护者。
- #10 反向对照应**精确失败在被测判据上**，而非靠崩溃/超时。VibeT4 是天然反向对照。

判据是**结构性**的（段标记 + 相对位置），不是硬编码 md5/大小 —— 后者会随 gen 层
正常更新而变成恒红判据，然后被人随手改阈值糊弄过去。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

MPQ_DIR = Path(__file__).resolve().parents[1] / "mpq"
sys.path.insert(0, str(MPQ_DIR))

from mpq_inject_workspace_kernel import (  # noqa: E402
    FWD_BEGIN, FWD_END, INVOKE_INCLUDE_RE, check_map_lineage,
)

# 真实 gen 血统 MapScript 的结构骨架（行号对应实图 L14/L17-19/L20-323/L325-327）
GEN_LINEAGE = f"""\
include "LibCOMI"
// ==== BEGIN VIBE_INCLUDE_WIRING (wire_map_includes.py) ====
include "LibMapModBridge"
include "LibVibeKernel_h"
include "LibVibeHandles"
{FWD_BEGIN}
trigger gf_SpecialInfestedAttackTrigger (int lp_night, string lp_specialInfestedType);
bool auto_gf_AIBonusBoss_TriggerFunc (bool testConds, bool runActions);
bool gt_Init01LoadData_Func (bool testConds, bool runActions);
{FWD_END}

include "LibVibeInvokeDispatch_active"
include "LibVibeKernel"
// ==== END VIBE_INCLUDE_WIRING ====
void InitLibs () {{ }}
"""

# VibeT4 血统：include 集合与 gen 完全相同，唯独缺前向原型区 —— 这就是致命差
T4_LINEAGE = "\n".join(
    ln for ln in GEN_LINEAGE.splitlines()
    if not (ln.startswith(("trigger gf_", "bool auto_gf_", "bool gt_"))
            or ln in (FWD_BEGIN, FWD_END))
) + "\n"

# 原型区存在但落在挂载点之后 —— "声明太晚，等同于没有"
LATE_PROTOS = f"""\
// ==== BEGIN VIBE_INCLUDE_WIRING ====
include "LibVibeKernel_h"
include "LibVibeInvokeDispatch_active"
include "LibVibeKernel"
{FWD_BEGIN}
bool gt_Init01LoadData_Func (bool testConds, bool runActions);
{FWD_END}
// ==== END VIBE_INCLUDE_WIRING ====
"""

# 纯内核图：压根没挂 invoke 层 —— 判据不适用，必须放行（避免恒红）
KERNEL_ONLY = """\
include "LibVibeKernel_h"
include "LibVibeKernel"
void InitLibs () { }
"""


def test_gen_lineage_passes():
    """正向：gen 血统必须过。"""
    ok, why = check_map_lineage(GEN_LINEAGE)
    assert ok, why
    assert "gen 血统" in why


def test_t4_lineage_is_rejected():
    """反向对照：VibeT4 血统必须**精确失败在缺前向原型**上，而非其它原因。"""
    # 先自证反向样本确实"挂了 invoke 却没原型"，否则这条测试是同义反复
    assert INVOKE_INCLUDE_RE.search(T4_LINEAGE), "反向样本没挂 invoke 层，测的不是目标场景"
    assert FWD_BEGIN not in T4_LINEAGE

    ok, why = check_map_lineage(T4_LINEAGE)
    assert not ok
    assert "VIBE_FORWARD_PROTOS" in why
    assert "静默丢整个 MapScript" in why


def test_protos_after_mount_is_rejected():
    """原型区在挂载点之后同样致命 —— 只查"标记在不在"是不够的。"""
    ok, why = check_map_lineage(LATE_PROTOS)
    assert not ok
    assert "太晚" in why


def test_kernel_only_map_is_not_falsely_rejected():
    """没挂 invoke 层的纯内核图不该被误杀（防判据恒红）。"""
    ok, why = check_map_lineage(KERNEL_ONLY)
    assert ok
    assert "不适用" in why


def test_gate_is_falsifiable():
    """判据必须能同时产出 True 和 False —— 恒绿等于没有判据。"""
    results = {check_map_lineage(s)[0]
               for s in (GEN_LINEAGE, T4_LINEAGE, LATE_PROTOS, KERNEL_ONLY)}
    assert results == {True, False}, "判据只有单一取值，已退化成同义反复"


def test_no_default_base_map():
    """脚本不得再有默认基底 —— 默认值在"一脚本两用途"场景里就是陷阱本身。"""
    src = (MPQ_DIR / "mpq_inject_workspace_kernel.py").read_text(encoding="utf-8")
    assert 'sys.argv[1] if len(sys.argv) > 1 else' not in src, "默认基底回归了"
    assert "USAGE" in src and "fail closed" in src


@pytest.mark.parametrize("real_map,expect_ok", [
    (r"C:\tmp\VibeDeadOfNight-Gen.SC2Map", True),
    (r"C:\tmp\VibeT4.sc2map", False),
])
def test_against_real_maps_if_present(real_map, expect_ok):
    """如本机存在真实图，用真图再证一遍（不存在则 skip，不做假绿）。"""
    p = Path(real_map)
    if not p.exists():
        pytest.skip(f"本机无 {p.name}，跳过真图校验（不视为通过）")
    from mpq_inject_workspace_kernel import read_mapscript  # noqa: E402
    from mpq_patch_kernel import load_storm  # noqa: E402

    ok, why = check_map_lineage(read_mapscript(load_storm(), p))
    assert ok is expect_ok, f"{p.name}: {why}"
