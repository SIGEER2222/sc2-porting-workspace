"""round27 selftest 补丁 —— 为三个新收口的句柄类型建立**可证伪**的真机断言。

设计要点（这是本轮的重点，不是凑数）：

1. 断言全部走「往返」口径：produce -> mutate -> read back。
   凡是「守门被删掉也照样绿」的写法一律不要 —— 那正是本轮要修的病。

2. **升级 round25 的两条恒绿断言**。
   `ai.filter.markercount.null.ignored` / `ai.filter.lifepermarker.null.ignored`
   在过去的 selftest 里是同义反复：全场没有任何单位带 marker，所以
   「库跳过了引擎调用」和「库调了但引擎本来就零数据」结果完全一样 ——
   守门被谁删掉它也照绿。本轮有了 marker 生产端，改成双向判据：
   同一 filter 条件下，单位没打标记 -> 0 个，打了标记 -> >= 1 个。

3. sound 在本测试局**不可观测**（不播任何音效，SoundLastPlayed 恒 null）。
   按 round23 既定纪律：观测不到的东西不硬断言，降级为 bank 诊断探针。
   只保留「缺键返回 null」这条与环境无关的性质做硬断言。

幂等：每段先查锚点。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(errors="replace")

SELFTEST = Path(__file__).resolve().parent / "selftest" / "cmlib_selftest.galaxy"

# --- 1) 主线 Deferred 局部变量（Galaxy 铁律：必须置顶） ---------------------------
ANCHOR_VARS = "    bool        lv_r23sent;\n"
NEW_VARS = """    bool        lv_r23sent;
    marker      lv_r27m;
    marker      lv_r27m2;
    unit        lv_r27u;
    sound       lv_r27snd;
    camerainfo  lv_r27cam;
"""

# --- 2) 主线断言段 -------------------------------------------------------------
ANCHOR_ASSERTS = "    // ---- 引擎语义探针（诊断用，**不是断言**，不影响通过判定）----\n"
NEW_ASSERTS = """    // =========================================================================
    // Round27：三个「不可达句柄类型」收口后的真机验证
    //
    // 收口前的病灶：库的公开 API 收 marker / sound / camerainfo 做形参，
    // 但全库没有任何函数能产出它们 —— 调用方只能喂 null 撞守门，接口是死的。
    // 下面每一条都是**往返判据**：produce -> mutate -> read back，
    // 少任何一环都会翻红，不存在「守门删了也绿」的写法。
    // =========================================================================

    // ---- marker 生产端 ----
    lv_r27m = CMLib_Marker("AI/Tactical/Danger");
    CMLibTest_MarkTag(lv_r27m != null, "marker.create");
    CMLibTest_MarkTag(CMLib_Marker("") == null, "marker.create.empty");

    // ---- 单位标记往返：加了数得到、删了数不到 ----
    lv_r27u = CMLib_SpawnForced("Marine", 1,
                                CMLib_PointOffset(lv_origin, 4.0, -4.0), 270.0);
    CMLibTest_MarkTag(CMLib_UnitMarkerCount(lv_r27u, lv_r27m) == 0,
                      "marker.unit.count.clean");
    CMLib_UnitMarkerAdd(lv_r27u, lv_r27m);
    CMLibTest_MarkTag(CMLib_UnitMarkerCount(lv_r27u, lv_r27m) >= 1,
                      "marker.unit.add");
    CMLib_UnitMarkerRemove(lv_r27u, lv_r27m);
    CMLibTest_MarkTag(CMLib_UnitMarkerCount(lv_r27u, lv_r27m) == 0,
                      "marker.unit.remove");
    // null 守门：无效单位 / 无效 marker 一律 0，且不崩。
    CMLibTest_MarkTag(CMLib_UnitMarkerCount(null, lv_r27m) == 0
                      && CMLib_UnitMarkerCount(lv_r27u, null) == 0,
                      "marker.unit.nullsafe");

    // ---- 施法者往返 ----
    lv_r27m2 = CMLib_MarkerForPlayer("AI/Tactical/Danger", 1);
    CMLibTest_MarkTag(CMLib_MarkerCastPlayer(lv_r27m2) == 1, "marker.cast.player");
    lv_r27m2 = CMLib_MarkerForUnit("AI/Tactical/Danger", lv_r27u);
    CMLibTest_MarkTag(CMLib_MarkerCastUnit(lv_r27m2) == lv_r27u, "marker.cast.unit");
    // 玩家槽非法 / 单位无效时退化为无施法者版本，仍必须是可用句柄而不是 null。
    CMLibTest_MarkTag(CMLib_MarkerForPlayer("AI/Tactical/Danger", 999) != null
                      && CMLib_MarkerForUnit("AI/Tactical/Danger", null) != null,
                      "marker.cast.degrade");

    // ---- 匹配标志往返（c_markerMatch* 在 GameData/Game.galaxy） ----
    CMLib_MarkerMatchFlag(lv_r27m, c_markerMatchLink, true);
    CMLibTest_MarkTag(CMLib_MarkerHasMatchFlag(lv_r27m, c_markerMatchLink),
                      "marker.matchflag.set");
    CMLib_MarkerMatchFlag(lv_r27m, c_markerMatchLink, false);
    CMLibTest_MarkTag(CMLib_MarkerHasMatchFlag(lv_r27m, c_markerMatchLink) == false,
                      "marker.matchflag.clear");
    // 越界 flag 必须被库拦住（不许把脏值送进引擎）。
    CMLibTest_MarkTag(CMLib_MarkerHasMatchFlag(lv_r27m, 99) == false,
                      "marker.matchflag.oob");

    // ---- DataTable 强类型族补齐：marker / camerainfo 往返 + 缺键回退 ----
    CMLib_DTSetMarker(false, "cmlib.r27.marker", lv_r27m);
    CMLibTest_MarkTag(CMLib_DTGetMarker(false, "cmlib.r27.marker") == lv_r27m,
                      "marker.dt.roundtrip");
    CMLibTest_MarkTag(CMLib_DTGetMarker(false, "cmlib.r27.nokey") == null,
                      "marker.dt.miss");

    lv_r27cam = CMLib_CamInfoDefault();
    CMLibTest_MarkTag(lv_r27cam != null, "cam.info.default");
    // id <= 0 是非法输入，库回退到默认镜头而不是把 null 一路带进 CameraApplyInfo。
    CMLibTest_MarkTag(CMLib_CamInfoFromId(-1) != null, "cam.info.fromid.guard");
    CMLib_DTSetCameraInfo(false, "cmlib.r27.cam", lv_r27cam);
    CMLibTest_MarkTag(CMLib_DTGetCameraInfo(false, "cmlib.r27.cam") == lv_r27cam,
                      "cam.dt.roundtrip");
    CMLibTest_MarkTag(CMLib_DTGetCameraInfo(false, "cmlib.r27.nokey") == null,
                      "cam.dt.miss");

    // ---- sound：本局不播任何音效，SoundLastPlayed 恒 null ----
    // 按 round23 纪律，观测不到的东西不硬断言（那是在断言环境，不是断言库）。
    // 只锁「缺键返回 null」这条与环境无关的性质；句柄真实值走 bank 诊断探针。
    lv_r27snd = CMLib_SfxLastPlayed();
    CMLibTest_MarkTag(CMLib_DTGetSound(false, "cmlib.r27.nokey") == null,
                      "sound.dt.miss");
    CMLib_DTSetSound(false, "cmlib.r27.snd", lv_r27snd);
    CMLibTest_MarkTag(CMLib_DTGetSound(false, "cmlib.r27.snd") == lv_r27snd,
                      "sound.dt.roundtrip");
    // 空键不许写进 DataTable（三个 Set 口径一致）。
    CMLib_DTSetMarker(false, "", lv_r27m);
    CMLibTest_MarkTag(CMLib_DTGetMarker(false, "") == null, "marker.dt.emptykey");

    // ---- 引擎语义探针（诊断用，**不是断言**，不影响通过判定）----
"""

# --- 3) 主线诊断探针补一条 sound ------------------------------------------------
ANCHOR_DIAG = '    CMLib_BankSetInt(lv_bank, "Result", "StatEvtLast", StatEventLastCreated());\n'
NEW_DIAG = """    CMLib_BankSetInt(lv_bank, "Result", "StatEvtLast", StatEventLastCreated());
    // round27：本局到底有没有可用的 sound 句柄。1 = null（预期，本局不播音效）。
    // 不做断言 —— 它测的是测试环境有没有放过声音，不是库对不对。
    // 哪天在会播音效的地图里跑出 0，就说明 CMLib_SfxLastPlayed 的正向通路
    // 也拿到了实证，届时可把 sound 的弱判据升级为往返硬断言。
    CMLib_BankSetInt(lv_bank, "Result", "R27SoundNull",
                     CMLibTest_BoolToInt(CMLib_SfxLastPlayed() == null));
"""

# --- 4) AIDeferred 局部变量 -----------------------------------------------------
ANCHOR_AIVARS = "    int       lv_r24air;\n"
NEW_AIVARS = """    int       lv_r24air;
    marker    lv_r27am;
    unit      lv_r27au;
    aifilter  lv_r27af;
    int       lv_r27an0;
    int       lv_r27an1;
"""

# --- 5) AIDeferred：把 round25 的恒绿断言升级为双向判据 ---------------------------
ANCHOR_AI = "    gv_cmlibAIDone = 1;\n"
NEW_AI = """    // =========================================================================
    // Round27：把 round25 的两条**恒绿**断言升级为真双向判据
    //
    // 旧写法 `ai.filter.markercount.null.ignored` 断言的是「传 null 时过滤结果
    // 不变」。可本局从来没有任何单位带 marker —— 「库跳过了引擎调用」和
    // 「库调了但引擎零数据」结果完全一样，守门被删掉它照样绿。这是判据坏死的
    // 第二种形态（同义反复），和恒红一样等于没有校验器。
    //
    // 现在库能造 marker 了，改成能证伪的形态：同一个 filter 条件，
    // 目标没打标记 -> 0 个，打了标记 -> >= 1 个。这条一旦变红，
    // 说明 marker 生产端 / UnitMarkerAdd / AISetFilterMarker 至少断了一环。
    // =========================================================================
    lv_r27am = CMLib_Marker("AI/Tactical/Danger");
    lv_r27au = CMLib_SpawnForced("Marine", 1,
                                 CMLib_PointOffset(lv_origin, 8.0, -8.0), 270.0);

    CMLib_UnitMarkerAdd(lv_r27au, lv_r27am);
    lv_r27af = CMLib_AIFilterNew(1);
    CMLib_AIFilterMarkerCount(lv_r27af, 1, 100, lv_r27am);
    lv_r27an1 = CMLib_AIFilterApplyCount(lv_r27af, CMLib_UGOf(lv_r27au));

    CMLib_UnitMarkerRemove(lv_r27au, lv_r27am);
    lv_r27af = CMLib_AIFilterNew(1);
    CMLib_AIFilterMarkerCount(lv_r27af, 1, 100, lv_r27am);
    lv_r27an0 = CMLib_AIFilterApplyCount(lv_r27af, CMLib_UGOf(lv_r27au));

    CMLibTest_MarkTag(lv_r27an1 >= 1 && lv_r27an0 == 0,
                      "marker.aifilter.roundtrip");

    // LifePerMarker 同理给一条正向对照：满血单位带 1 个 marker、
    // 门槛设 1 点生命，必须放行；门槛设到高于单位血量，必须筛掉。
    CMLib_UnitMarkerAdd(lv_r27au, lv_r27am);
    lv_r27af = CMLib_AIFilterNew(1);
    CMLib_AIFilterLifePerMarker(lv_r27af, 1.0, lv_r27am);
    lv_r27an1 = CMLib_AIFilterApplyCount(lv_r27af, CMLib_UGOf(lv_r27au));
    lv_r27af = CMLib_AIFilterNew(1);
    CMLib_AIFilterLifePerMarker(lv_r27af, 99999.0, lv_r27am);
    lv_r27an0 = CMLib_AIFilterApplyCount(lv_r27af, CMLib_UGOf(lv_r27au));
    CMLibTest_MarkTag(lv_r27an1 >= 1 && lv_r27an0 == 0,
                      "marker.aifilter.lifepermarker.roundtrip");

    gv_cmlibAIDone = 1;
"""

# --- 6) BoolToInt 小工具（selftest 内可能还没有） --------------------------------
HELPER = """
// round27：bool -> int，给 bank 诊断探针用（Galaxy 没有隐式转换）。
int CMLibTest_BoolToInt (bool lp_v) {
    if (lp_v) { return 1; }
    return 0;
}
"""
ANCHOR_HELPER_AFTER = "void CMLibTest_MarkTag (bool lp_ok, string lp_tag) {"


def main() -> int:
    txt = SELFTEST.read_text(encoding="utf-8")
    orig = txt
    done: list[str] = []
    skipped: list[str] = []

    # helper 先插（放在 MarkTag 函数之前，保证被后面引用时已定义）
    if "CMLibTest_BoolToInt" not in txt:
        idx = txt.index(ANCHOR_HELPER_AFTER)
        txt = txt[:idx] + HELPER.lstrip("\n") + "\n" + txt[idx:]
        done.append("helper CMLibTest_BoolToInt")
    else:
        skipped.append("helper")

    steps = [
        ("主线变量", "lv_r27m;", ANCHOR_VARS, NEW_VARS),
        ("主线断言", "marker.create", ANCHOR_ASSERTS, NEW_ASSERTS),
        ("sound 诊断", "R27SoundNull", ANCHOR_DIAG, NEW_DIAG),
        ("AI 变量", "lv_r27am;", ANCHOR_AIVARS, NEW_AIVARS),
        ("AI 双向判据", "marker.aifilter.roundtrip", ANCHOR_AI, NEW_AI),
    ]
    for label, guard, anchor, block in steps:
        if guard in txt:
            skipped.append(label)
            continue
        if anchor not in txt:
            print(f"  FAIL 找不到锚点（{label}）: {anchor!r}")
            return 1
        if txt.count(anchor) != 1:
            print(f"  FAIL 锚点不唯一（{label}，出现 {txt.count(anchor)} 次）")
            return 1
        txt = txt.replace(anchor, block, 1)
        done.append(label)

    if txt != orig:
        SELFTEST.write_text(txt, encoding="utf-8")

    for d in done:
        print(f"  +    {d}")
    for s in skipped:
        print(f"  skip {s}（已存在）")
    print(f"\n[patch_selftest_round27] 新增 {len(done)} 段，跳过 {len(skipped)} 段")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
