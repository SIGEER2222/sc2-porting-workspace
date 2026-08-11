"""round27 —— 收口三个「不可达句柄类型」(marker / sound / camerainfo)。

背景（见 check_type_reachability.py）：
    库的公开 API 收 marker / sound / camerainfo 做形参，可库自己一个都造不出来。
    调用方唯一能喂进去的就是 null，撞上守门早退 —— 等于封了一批永远无效的死接口。
    这是「可调用 ≠ 可用」的第三种形态：**可编译 ≠ 可达**。

本轮补的是生产端（返回句柄的函数），三处落点都不是为过门禁硬凑：
    1. cmlib_core —— DT 强类型族本来就漏了这三种，补齐即天然提供三个生产端；
    2. cmlib_fx   —— SoundLastPlayed / CameraInfoDefault 库内早就在调，
                     只是把句柄吞在局部变量里从不外露，改成公开返回；
    3. cmlib_unit —— marker 族整族只封了 AI 过滤两个消费端，生产端 0 个，本轮补全。

范围前置校验（防重蹈 StatEvent / Tactical 覆辙）：
    全部 21 个相关 native 均声明于 core 默认 include 的 natives.galaxy，
    无 "Blizzard only" 标记，marker flag 常量在 GameData/Game.galaxy。

幂等：每段先查锚点，已存在则跳过。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

CMLIB = Path(__file__).resolve().parent / "scripts" / "cmlib"

# ---------------------------------------------------------------------------
# 1) cmlib_core —— DataTable 强类型族补三漏项
#    口径与既有 DTGetRegion / DTGetUnit 完全一致：空键早退 + 存在性检查 + null 回退。
# ---------------------------------------------------------------------------
CORE_DECL = """
// ---- Round27：DataTable 强类型族补齐（sound / camerainfo / marker） -------------
// 这三种此前只有引擎 native 有 Get/Set，库侧缺失 —— 于是库的公开 API 虽然收这些
// 句柄做形参，调用方却没有任何合法途径拿到它们（只能喂 null）。补齐后 DataTable
// 成为这三类句柄的通用「跨触发器传递」通道。
void       CMLib_DTSetSound(bool lp_global, string lp_key, sound lp_value);
sound      CMLib_DTGetSound(bool lp_global, string lp_key);       // 缺键返回 null
void       CMLib_DTSetCameraInfo(bool lp_global, string lp_key, camerainfo lp_value);
camerainfo CMLib_DTGetCameraInfo(bool lp_global, string lp_key);  // 缺键返回 null
void       CMLib_DTSetMarker(bool lp_global, string lp_key, marker lp_value);
marker     CMLib_DTGetMarker(bool lp_global, string lp_key);      // 缺键返回 null
"""

CORE_IMPL = """
// =============================================================================
// Round27：DataTable 强类型族补齐（sound / camerainfo / marker）
// =============================================================================
void CMLib_DTSetSound(bool lp_global, string lp_key, sound lp_value) {
    if (lp_key == "") { return; }
    DataTableSetSound(lp_global, lp_key, lp_value);
}

sound CMLib_DTGetSound(bool lp_global, string lp_key) {
    if (lp_key == "") { return null; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return null; }
    return DataTableGetSound(lp_global, lp_key);
}

void CMLib_DTSetCameraInfo(bool lp_global, string lp_key, camerainfo lp_value) {
    if (lp_key == "") { return; }
    DataTableSetCameraInfo(lp_global, lp_key, lp_value);
}

camerainfo CMLib_DTGetCameraInfo(bool lp_global, string lp_key) {
    if (lp_key == "") { return null; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return null; }
    return DataTableGetCameraInfo(lp_global, lp_key);
}

void CMLib_DTSetMarker(bool lp_global, string lp_key, marker lp_value) {
    if (lp_key == "") { return; }
    DataTableSetMarker(lp_global, lp_key, lp_value);
}

marker CMLib_DTGetMarker(bool lp_global, string lp_key) {
    if (lp_key == "") { return null; }
    if (DataTableValueExists(lp_global, lp_key) == false) { return null; }
    return DataTableGetMarker(lp_global, lp_key);
}
"""

# ---------------------------------------------------------------------------
# 2) cmlib_fx —— sound / camerainfo 直接生产端
# ---------------------------------------------------------------------------
FX_DECL = """
// ---- Round27：sound / camerainfo 生产端（此前库内自用、从不外露） ---------------
// 最近一次由本地图播放的声音句柄；没有播放过返回 null。
// 这是 CMLib_SfxWaitFrom / CMLib_SfxWaitEnd 的唯一合法喂料来源 —— 在本轮之前，
// 那两个函数的形参调用方根本造不出来。
sound      CMLib_SfxLastPlayed();
// 默认镜头参数对象（引擎恒返回有效句柄）。CMLib_CamApply 族的默认喂料。
camerainfo CMLib_CamInfoDefault();
// 按地图内预设镜头对象 id 取参数；id <= 0 视为非法，回退到默认镜头而不是给 null，
// 保证调用方拿到的句柄永远可用（避免把 null 一路带进 CameraApplyInfo）。
camerainfo CMLib_CamInfoFromId(int lp_id);
"""

FX_IMPL = """
// =============================================================================
// Round27：sound / camerainfo 生产端
// =============================================================================
sound CMLib_SfxLastPlayed() {
    return SoundLastPlayed();
}

camerainfo CMLib_CamInfoDefault() {
    return CameraInfoDefault();
}

camerainfo CMLib_CamInfoFromId(int lp_id) {
    if (lp_id <= 0) { return CameraInfoDefault(); }
    return CameraInfoFromId(lp_id);
}
"""

# ---------------------------------------------------------------------------
# 3) cmlib_unit —— marker 族（生产端 4 + 消费端 7）
# ---------------------------------------------------------------------------
UNIT_DECL = """
// -----------------------------------------------------------------------------
// CMLib :: Round27 —— Marker 族（单位标记）
//
// marker 是引擎内建句柄，表示"某个东西在某单位身上留下的标记"，AI 战术过滤
// (CMLib_AIFilterMarkerCount / CMLib_AIFilterLifePerMarker，见 cmlib_ai_h) 用它
// 做条件，技能层用它防 overkill（多个 AI 单位不重复对同一目标放大招）。
//
// link 是数据层路径字符串，官方 c_MK_* 常量即这些串，例如：
//     "Abil/250mmStrikeCannons/AI"、"Abil/Yamato/AI"、"AI/Tactical/Danger"
// 库内不引用 c_MK_* 常量本身（那些定义在 Tactical/RequirementsAI.galaxy，
// 不在 core 默认 include 范围内），只收字符串，调用方想用常量自己传进来。
//
// 匹配标志用 GameData/Game.galaxy 的 c_markerMatchId / Link /
// CasterPlayer / CasterUnit（0~3）。
// -----------------------------------------------------------------------------
// 按 link 造一个 marker；link 为空返回 null（不让空串进引擎）。
marker CMLib_Marker(string lp_link);
// 造一个"由某玩家施放"的 marker；玩家槽非法时退化为无施法者版本。
marker CMLib_MarkerForPlayer(string lp_link, int lp_player);
// 造一个"由某单位施放"的 marker；单位无效时退化为无施法者版本。
marker CMLib_MarkerForUnit(string lp_link, unit lp_unit);
// 取单位身上第 lp_index 个 marker。
// 注意：引擎对该索引的基准（0-based / 1-based）无任何官方文档与用例，
// 库不替它拍板 —— 只做 index < 0 守门后原样透传，调用方请配合
// CMLib_UnitMarkerCount 试探，或改用"按 link 构造 + Count"的确定性路径。
marker CMLib_UnitMarkerAt(unit lp_unit, int lp_index);
// 给单位打标记。单位无效或 marker 为 null 时忽略。
void   CMLib_UnitMarkerAdd(unit lp_unit, marker lp_marker);
// 单位身上该 marker 的数量；单位无效或 marker 为 null 返回 0。
int    CMLib_UnitMarkerCount(unit lp_unit, marker lp_marker);
// 移除单位身上的该 marker。单位无效或 marker 为 null 时忽略。
void   CMLib_UnitMarkerRemove(unit lp_unit, marker lp_marker);
// marker 的施法玩家；marker 为 null 返回 0（= 中立槽，非法玩家）。
int    CMLib_MarkerCastPlayer(marker lp_marker);
// marker 的施法单位；marker 为 null 返回 null。
unit   CMLib_MarkerCastUnit(marker lp_marker);
// 设置匹配标志（c_markerMatch*）。marker 为 null 或 flag 越界时忽略。
void   CMLib_MarkerMatchFlag(marker lp_marker, int lp_flag, bool lp_state);
// 读匹配标志；marker 为 null 或 flag 越界返回 false。
bool   CMLib_MarkerHasMatchFlag(marker lp_marker, int lp_flag);
"""

UNIT_IMPL = """
// =============================================================================
// Round27：Marker 族（单位标记）—— 生产端 4 + 消费端 7
//
// 本族存在的理由：cmlib_ai 的 AIFilterMarkerCount / AIFilterLifePerMarker 收
// marker 形参已有两轮，但全库没有任何函数能产出 marker —— 调用方只能喂 null
// 撞守门，那两个 API 一直是死的。生产端补上后整条链才真正可用。
// =============================================================================
marker CMLib_Marker(string lp_link) {
    if (lp_link == "") { return null; }
    return Marker(lp_link);
}

marker CMLib_MarkerForPlayer(string lp_link, int lp_player) {
    if (lp_link == "") { return null; }
    if (CMLib_IsValidPlayerSlot(lp_player) == false) { return Marker(lp_link); }
    return MarkerCastingPlayer(lp_link, lp_player);
}

marker CMLib_MarkerForUnit(string lp_link, unit lp_unit) {
    if (lp_link == "") { return null; }
    if (CMLib_UnitOk(lp_unit) == false) { return Marker(lp_link); }
    return MarkerCastingUnit(lp_link, lp_unit);
}

marker CMLib_UnitMarkerAt(unit lp_unit, int lp_index) {
    if (CMLib_UnitOk(lp_unit) == false) { return null; }
    if (lp_index < 0) { return null; }
    return UnitMarker(lp_unit, lp_index);
}

void CMLib_UnitMarkerAdd(unit lp_unit, marker lp_marker) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    if (lp_marker == null) { return; }
    UnitMarkerAdd(lp_unit, lp_marker);
}

int CMLib_UnitMarkerCount(unit lp_unit, marker lp_marker) {
    if (CMLib_UnitOk(lp_unit) == false) { return 0; }
    if (lp_marker == null) { return 0; }
    return UnitMarkerCount(lp_unit, lp_marker);
}

void CMLib_UnitMarkerRemove(unit lp_unit, marker lp_marker) {
    if (CMLib_UnitOk(lp_unit) == false) { return; }
    if (lp_marker == null) { return; }
    UnitMarkerRemove(lp_unit, lp_marker);
}

int CMLib_MarkerCastPlayer(marker lp_marker) {
    if (lp_marker == null) { return 0; }
    return MarkerGetCastingPlayer(lp_marker);
}

unit CMLib_MarkerCastUnit(marker lp_marker) {
    if (lp_marker == null) { return null; }
    return MarkerGetCastingUnit(lp_marker);
}

void CMLib_MarkerMatchFlag(marker lp_marker, int lp_flag, bool lp_state) {
    if (lp_marker == null) { return; }
    if (lp_flag < c_markerMatchId) { return; }
    if (lp_flag > c_markerMatchCasterUnit) { return; }
    MarkerSetMatchFlag(lp_marker, lp_flag, lp_state);
}

bool CMLib_MarkerHasMatchFlag(marker lp_marker, int lp_flag) {
    if (lp_marker == null) { return false; }
    if (lp_flag < c_markerMatchId) { return false; }
    if (lp_flag > c_markerMatchCasterUnit) { return false; }
    return MarkerGetMatchFlag(lp_marker, lp_flag);
}
"""

PATCHES = [
    ("cmlib_core_h.galaxy", "CMLib_DTSetSound", CORE_DECL),
    ("cmlib_core.galaxy", "CMLib_DTSetSound", CORE_IMPL),
    ("cmlib_fx_h.galaxy", "CMLib_SfxLastPlayed", FX_DECL),
    ("cmlib_fx.galaxy", "CMLib_SfxLastPlayed", FX_IMPL),
    ("cmlib_unit_h.galaxy", "CMLib_Marker(", UNIT_DECL),
    ("cmlib_unit.galaxy", "CMLib_Marker(", UNIT_IMPL),
]


def main() -> int:
    changed = 0
    for fname, anchor, block in PATCHES:
        p = CMLIB / fname
        if not p.exists():
            print(f"  FAIL 找不到 {p}")
            return 1
        txt = p.read_text(encoding="utf-8")
        if anchor in txt:
            print(f"  skip {fname}（锚点 {anchor!r} 已存在）")
            continue
        if not txt.endswith("\n"):
            txt += "\n"
        p.write_text(txt + block, encoding="utf-8")
        print(f"  +    {fname}  追加 {len(block.splitlines())} 行")
        changed += 1
    print(f"\n[extend_round27] 完成，改动 {changed} 个文件")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
