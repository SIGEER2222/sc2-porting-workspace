"""CMLib 真实引擎运行时测试（SC2 API 模式）。

流程：
  1. 连接 SC2 API (ws://127.0.0.1:5000/sc2api)
  2. create_game(local_map=test_cmlib.SC2Map 字节) + join_game  -> 真正进图
  3. 等待 InitMap -> CMLib_SelfTest -> 2s 后 CMLibTest_Deferred 触发器
  4. 双通路取证：
     A) raw observation 读回特征单位（权威，不依赖文件系统 / 账号 / bank 子系统）
          Ghost         x1 = MapScript 编译成功且 InitMap 被引擎调用
          Marine        x1 = CMLib_SpawnForced 生效
          Marauder      xN = N 项 CMLib 断言通过（满分 EXPECTED_ASSERTS）
          Thor          x1 = 全部断言通过
          Battlecruiser x1 = 加分：AI 用户变量读写往返成功
          Banshee       x1 = 加分：AISetStock 通路未抛运行时错误
     B) CMLibRuntimeTest.SC2Bank 魔数与数值（辅助）

依赖：reference/SC2-Neuro-API-Integration/s2clientprotocol（sc2api_pb2）、aiohttp
"""
import os, re, sys, time, asyncio, threading
import xml.etree.ElementTree as ET

os.environ['PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION'] = 'python'
REPO = r"e:\Code\MyMod\SC2VibeTools\sc2-porting-workspace"
sys.path.insert(0, os.path.join(REPO, "reference", "SC2-Neuro-API-Integration"))

from s2clientprotocol import sc2api_pb2 as sc_pb

sys.path.insert(0, os.path.join(REPO, "src", "lib"))
from sc2_api_conn import acquire_launched, api_url   # noqa: E402

MAP_FILE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "src", "lib", "test_cmlib.SC2Map")
BANK_NAME = "CMLibRuntimeTest"
RACE_TERRAN = 1


def _count_expected_asserts() -> int:
    """从 cmlib_selftest.galaxy 源码直接数断言条数，**不手抄**。

    历史教训（2026-08-08）：这个常量以前是手写的，多进程/多轮并发扩充 selftest 时
    必然漂移 —— 表现为「真机其实全过，但判定说没达标」或反过来「少跑了几条却判 PASS」，
    是最难查的一类假阴/假阳。改为从唯一真源（selftest 源文件）自动推导。
    """
    src = os.path.join(REPO, "src", "lib", "selftest", "cmlib_selftest.galaxy")
    try:
        txt = open(src, encoding="utf-8", errors="replace").read()
    except OSError:
        return 0
    # 去掉行注释与块注释，避免把示例代码 / 说明文字里的调用数进来
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
    txt = re.sub(r"//[^\n]*", "", txt)
    # 排除定义处（void CMLibTest_Mark (...) / CMLibTest_MarkTag (...)）
    n = len(re.findall(r"\bCMLibTest_Mark(?:Tag)?\s*\(", txt))
    n -= len(re.findall(r"\bvoid\s+CMLibTest_Mark(?:Tag)?\s*\(", txt))
    return n


EXPECTED_ASSERTS = _count_expected_asserts()

# ---- round22：分支感知期望值 ----------------------------------------------
# 老口径 EXPECTED_ASSERTS 是**静态调用点数**，与运行时执行数天然不等 ——
# selftest 里有两组 if/else 互斥对（各 2 个点、只走 1 条），所以静态 511、
# 运行时 509。历史上这个差值被含糊地解释成「事件处理器内断言未触发」，
# round22 逐点核查证明是错的：511 个 Mark 点全在 Deferred/AIDeferred 里，
# 事件处理器内一个都没有。
#
# 含糊解释的代价是**吞掉真实退化**：真丢 2 条断言与结构性互斥少 2 条，
# 在旧判定里长得一模一样。改用分支感知期望后，期望值成为确定数，
# 任何真实丢失都会立刻表现为「执行数 != 期望数」。
try:
    from expected_asserts import analyze as _ea_analyze, describe as _ea_describe
    _EA = _ea_analyze(os.path.join(REPO, "src", "lib", "selftest",
                                   "cmlib_selftest.galaxy"))
except Exception as _exc:                                    # pragma: no cover
    _EA = {"ok": False, "error": str(_exc), "expected": 0, "deterministic": False}

    def _ea_describe(_r):
        return f"断言会计不可用：{_r.get('error')}"

# 期望执行数；分析器不可用时退化回老口径（只当下限用，不判等）
EXPECTED_RUNTIME = _EA["expected"] if _EA.get("ok") else EXPECTED_ASSERTS
# 只有"确定值"（互斥对两侧条数相等 且 无循环内断言）才允许判等
EXPECTED_EXACT = bool(_EA.get("ok") and _EA.get("deterministic"))
BANKS_ROOT = os.path.join(os.environ.get("USERPROFILE", "C:/Users/22448"),
                          "Documents", "StarCraft II", "Banks")

# 结果编码单位
SENTINEL = "Ghost"          # InitMap 被调用
SPAWNED = "Marine"          # unit 模块生效
COUNTER = "Marauder"        # 每个 = 1 项断言通过
ALLPASS = "Thor"            # 全部断言通过
BONUS_AIVAR = "Battlecruiser"   # 加分：无 AI 玩家上 AIVar 安全回退（Get→0，不崩）
BONUS_STOCK = "Banshee"         # 加分：AISetStock 通路存活


def find_bank():
    if not os.path.isdir(BANKS_ROOT):
        return None
    for dp, _, fn in os.walk(BANKS_ROOT):
        for f in fn:
            if f.lower() == f"{BANK_NAME}.SC2Bank".lower():
                return os.path.join(dp, f)
    return None


def parse_bank(path):
    try:
        root = ET.parse(path).getroot()
        out = {}
        for sec in root.iter("Section"):
            sname = sec.get("name")
            for key in sec.iter("Key"):
                val_el = key.find("Value")
                val = val_el.get("int") if val_el is not None else None
                if val is None and val_el is not None:
                    val = val_el.get("string") or val_el.text
                out[f"{sname}/{key.get('name')}"] = val
        return out
    except Exception as e:
        return {"__parse_error__": str(e)}


def main():
    print(f"[t] SC2 API = {api_url()}")
    client = acquire_launched()        # 端口自动发现 + 崩了自动重启 + 保证 launched 态
    print("[t] Connected (launched)")

    old = find_bank()
    if old:
        os.remove(old)
        print(f"[t] Cleared old bank: {old}")

    with open(MAP_FILE, 'rb') as f:
        md = f.read()
    print(f"[t] Map bytes: {len(md)}")

    r = client.send(sc_pb.Request(create_game=sc_pb.RequestCreateGame(
        local_map=sc_pb.LocalMap(map_data=md),
        player_setup=[sc_pb.PlayerSetup(type=1, race=RACE_TERRAN, player_name="P1")],
        realtime=True,
    )), 180)
    if r.error:
        print("[t] CreateGame FAILED:", list(r.error))
        client.close(); return 1
    print("[t] CreateGame OK")

    time.sleep(1)
    r = client.send(sc_pb.Request(join_game=sc_pb.RequestJoinGame(
        race=RACE_TERRAN, options=sc_pb.InterfaceOptions(raw=True))), 120)
    if r.error:
        print("[t] JoinGame FAILED:", list(r.error))
        client.close(); return 1
    print(f"[t] JoinGame OK player_id={r.join_game.player_id}")

    # unit_type id -> name
    id2name = {}
    try:
        rd = client.send(sc_pb.Request(data=sc_pb.RequestData(unit_type_id=True)), 120)
        id2name = {u.unit_id: u.name for u in rd.data.units}
        print(f"[t] Unit type table: {len(id2name)} entries")
    except Exception as e:
        print("[t] RequestData failed:", e)

    print("[t] Waiting for InitMap + deferred triggers (2s 主断言 / 6s AI 加分项) ...")
    counts = {}
    max_passed = 0
    saw_thor = False
    saw_bonus = False
    prev_counter = -1
    for attempt in range(10):
        time.sleep(3)
        try:
            ro = client.send(sc_pb.Request(observation=sc_pb.RequestObservation()), 60)
        except Exception as e:
            print(f"[t] observation attempt {attempt+1} failed: {e}")
            continue
        units = ro.observation.observation.raw_data.units
        counts = {}
        for u in units:
            counts[id2name.get(u.unit_type, f"id{u.unit_type}")] = \
                counts.get(id2name.get(u.unit_type, f"id{u.unit_type}"), 0) + 1
        print(f"[t] obs#{attempt+1} loop={ro.observation.observation.game_loop} "
              f"units={len(units)} {counts}")
        passed_now = counts.get(COUNTER, 0)
        # 单位创建在 raw observation 里有 1~2 tick 滞后；取观测期内最大值，
        # 规避「跑满 150 但快照只数到 144」的假 PARTIAL（2026-08-08 实测坑）。
        max_passed = max(max_passed, passed_now)
        if counts.get(ALLPASS, 0) >= 1:
            saw_thor = True
        if counts.get(BONUS_AIVAR, 0) >= 1 and counts.get(BONUS_STOCK, 0) >= 1:
            saw_bonus = True
        # 退出条件（2026-08-09 修正）：
        # 旧逻辑要求「观测 Marauder 数 >= 源码静态断言数」才早退。但源码里
        # 有一部分 Mark 调用在**事件处理器**里（如 OnReaverTargetDied / OnCreated），
        # 这些事件在测试局里不一定触发 —— 于是「实际执行断言数」会稳定小于
        # 「源码静态条数」。用静态条数当门槛会把本来全过的局判成 PARTIAL。
        # 改成以地图自身的「全过信号」为准：
        #   Thor  出现  <=> 地图内部 gv_cmlibPassed == gv_cmlibTotal（它自己 spawn 的）
        #   Banshee/Battlecruiser 出现 <=> AI 加分线跑完
        # 两者都见到即视为「跑完了且全过」，无需再数 Marauder。
        if counts.get(SENTINEL, 0) >= 1 and saw_thor and saw_bonus:
            break
        prev_counter = passed_now

    client.close()
    time.sleep(1)

    # ---- 判定（Marauder 用观测期内最大值，规避单位创建的观测滞后）----
    sentinel = counts.get(SENTINEL, 0)
    spawned = counts.get(SPAWNED, 0)
    passed = max_passed
    allpass = 1 if saw_thor else 0

    print("\n[t] ================ VERDICT ================")
    print(f"[t] A) 可观测单位通路")
    print(f"[t]    {SENTINEL:9s} = {sentinel}  -> MapScript 编译成功 + InitMap 被调用: "
          f"{'YES' if sentinel >= 1 else 'NO'}")
    print(f"[t]    {SPAWNED:9s} = {spawned}  -> CMLib_SpawnForced 生效: "
          f"{'YES' if spawned >= 1 else 'NO'}")
    print(f"[t]    {COUNTER:9s} = {passed}  -> 断言通过 {passed}/{EXPECTED_RUNTIME}"
          f"（静态调用点 {EXPECTED_ASSERTS}，互斥分支扣 "
          f"{EXPECTED_ASSERTS - EXPECTED_RUNTIME}）")
    print(f"[t]    {ALLPASS:9s} = {allpass}  -> 全部断言通过: "
          f"{'YES' if allpass >= 1 else 'NO'}")
    bonus_ai = counts.get(BONUS_AIVAR, 0)
    bonus_st = counts.get(BONUS_STOCK, 0)
    print(f"[t]    {BONUS_AIVAR:9s} = {bonus_ai}  -> [加分] AIVar 无 AI 玩家安全回退: "
          f"{'YES' if bonus_ai >= 1 else 'NO'}")
    print(f"[t]    {BONUS_STOCK:9s} = {bonus_st}  -> [加分] AISetStock 通路存活: "
          f"{'YES' if bonus_st >= 1 else 'NO'}")

    # ---- B) Bank 通路：地图内自报的 Passed/Total/FailTags ----
    # 这是比"数单位"更强的一路证据：单位观测受生产延迟、视野、
    # 其它代码顺手 spawn 同名单位等因素干扰，而 bank 是脚本自己写下的真值。
    # 两路必须互相印证 —— 只信一路，另一路失真时就会静默漏掉问题。
    bank = find_bank()
    bank_ok = False
    bank_passed = bank_total = None
    bank_fails = ""
    if bank:
        data = parse_bank(bank)
        print(f"[t] B) Bank 通路: {bank}")
        print(f"[t]    {data}")
        bank_ok = data.get("Result/Magic") == "13371337"
        try:
            bank_passed = int(data.get("Result/Passed"))
            bank_total = int(data.get("Result/Total"))
        except (TypeError, ValueError):
            bank_passed = bank_total = None
        bank_fails = (data.get("Result/FailTags") or "").strip()
        if bank_passed is not None:
            print(f"[t]    自报断言 = {bank_passed}/{bank_total}"
                  f"{'  失败标签: ' + bank_fails if bank_fails else ''}")
    else:
        print("[t] B) Bank 通路: 未找到 bank 文件（可能受 API 模式账号态限制，非致命）")

    # ---- C) 两路交叉验证（信息性，不单独 gate）----
    # 「观测 Marauder 数」(passed) 与「bank 自报」(bank_passed) 应当一致：
    # 二者都是"实际执行并通过的断言数"。历史事故（第 13 轮）观测曾虚高 +6
    # （AI 线重复 spawn 证据单位），现已修。但**反过来**——
    # 源码里有一部分 Mark 在事件处理器（OnReaverTargetDied / OnCreated）内，
    # 这些事件在测试局未必触发，所以「执行数」会稳定小于「源码静态条数」。
    # 因此：静态 EXPECTED_ASSERTS 只作**下限 sanity floor**（执行数不应无故更少），
    # 真正的"全过"以地图自身的 Thor 信号 + bank 自报为准。
    cross_note = ""
    if bank_passed is not None:
        delta = passed - bank_passed
        if delta == 0:
            cross_note = f"两路一致（观测 {passed} == 自报 {bank_passed}）"
        else:
            cross_note = (f"两路不一致：观测 {passed} vs 自报 {bank_passed}"
                          f"（差 {delta:+d}）—— 多为观测滞后/视野，非必错")
        print(f"[t] C) 交叉验证: {cross_note}")

    # ---- C2) 断言会计（round22：分支感知，可判等）----
    # 旧逻辑：静态调用点当"下限哨兵"，少了就说"多半是未触发的事件断言"，不判失败。
    # 这个宽容口径会让**真实丢失**与**结构性互斥**无法区分 —— 证据链上一个
    # 永远解释不清的残差，等于给回归留了个后门。
    # 新逻辑：期望值由分支感知分析器精确算出（互斥 if/else 只算一侧）。
    # 期望确定时，执行数必须**恰好等于**期望，少一条就是回归、多一条就是双记。
    print(f"[t] C2) 断言会计:")
    for _line in _ea_describe(_EA).split("\n"):
        print(f"[t]      {_line}")
    acct_ok = True
    acct_note = ""
    if EXPECTED_EXACT:
        if passed == EXPECTED_RUNTIME:
            acct_note = f"精确吻合（执行 {passed} == 期望 {EXPECTED_RUNTIME}）"
        elif passed < EXPECTED_RUNTIME:
            acct_ok = False
            acct_note = (f"**少 {EXPECTED_RUNTIME - passed} 条**：执行 {passed} < "
                         f"期望 {EXPECTED_RUNTIME}。期望值为确定值，缺口即回归 —— "
                         f"查 bank FailTags / Mark 序号定位")
        else:
            acct_ok = False
            acct_note = (f"**多 {passed - EXPECTED_RUNTIME} 条**：执行 {passed} > "
                         f"期望 {EXPECTED_RUNTIME}。多记会掩盖失败（round13 双记事故），"
                         f"须查是否有断言被重复执行")
    else:
        acct_note = (f"期望值非确定（存在循环内断言或不等长互斥对），"
                     f"退化为下限判定：执行 {passed} vs 下限 {EXPECTED_RUNTIME}")
        acct_ok = passed >= EXPECTED_RUNTIME
    print(f"[t]      -> {acct_note}")
    floor_note = "" if acct_ok else acct_note

    # ---- 判定（权威信号：Thor + bank 自报）----
    #   sentinel(Ghost) >= 1  -> MapScript 编译成功且 InitMap 被调用
    #   allpass(Thor)   >= 1  -> 地图内部 gv_cmlibPassed == gv_cmlibTotal（它自己证的）
    #   bank 可用时      -> 自报 bank_passed == bank_total 且 FailTags 空
    ok = sentinel >= 1 and allpass >= 1
    if bank_passed is not None:
        ok = ok and (bank_passed == bank_total) and not bank_fails
    # round22：断言会计并入判定门。期望为确定值时，执行数必须精确吻合 ——
    # 否则「Thor 出现 + bank 自报一致」这两路仍可能同时被同一个系统性错误骗过
    # （例如整段断言被跳过、Passed/Total 同步少算）。第三路独立静态期望做交叉锁。
    ok = ok and acct_ok
    print("[t] -----------------------------------------")
    if ok:
        print(f"[t] PASS — CMLib 在真实 SC2 引擎中编译并执行成功，"
              f"{passed} 项断言全部通过"
              f"（静态调用点 {EXPECTED_ASSERTS}，互斥分支扣 "
              f"{EXPECTED_ASSERTS - EXPECTED_RUNTIME}，期望执行 {EXPECTED_RUNTIME}，"
              f"{acct_note}）"
              f"{'，bank 魔数校验通过' if bank_ok else ''}"
              f"{'，' + cross_note if cross_note else ''}")
        return 0

    # 失败分支必须**从最根本的信号往外排**，顺序不能乱（round22 踩坑，见下）。
    #
    # sentinel(Ghost)=0 意味着 MapScript 压根没编译成功 / InitMap 没被调用 ——
    # 地图根本没起来。此时 passed=0，任何以「执行数」为输入的次级判据
    # （断言会计、失败标签、Thor 缺席）都必然同时不成立，但它们描述的都是
    # "跑起来之后哪里不对"，用它们去解释"根本没跑"是**错误归因**。
    #
    # round22 事故：新加的 `if not acct_ok -> PARTIAL 断言会计不符` 被插在了
    # sentinel 门**之前**。反向对照图（依赖指向不存在路径、期望地图起不来）
    # 于是被判成 PARTIAL 而不是 FAIL，矩阵整轮 rc=1。更危险的是语义后果：
    # 反向对照存在的唯一意义就是"排假阳性"，它一旦不能产出 FAIL，
    # 这道防线就等于被拆了——正向 PASS 也随之失去可信度。
    # 教训写死在这里：**新增判据一律往后插，永远不要挡在 sentinel 前面。**
    if sentinel < 1:
        print("[t] FAIL — sentinel 未出现：MapScript 未编译成功或 InitMap 未被调用")
        return 2
    if not acct_ok:
        print(f"[t] PARTIAL — 断言会计不符: {acct_note}")
        return 3
    if bank_fails:
        print(f"[t] PARTIAL — 存在失败断言，标签: {bank_fails}")
        return 3
    print(f"[t] PARTIAL — InitMap 已执行，但 Thor(全过信号) 未出现"
          f"{'；' + cross_note if cross_note else ''}")
    return 3


if __name__ == "__main__":
    sys.exit(main())
