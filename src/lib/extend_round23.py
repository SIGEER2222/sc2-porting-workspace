"""CMLib :: Round23 —— StatEvent* 纳入 cmlib_stat（范围判据翻案后的落库）。

## 为什么这一轮才敢包

round22 之前，全库判据是「符号不在 core.sc2mod/TriggerLibs/natives.galaxy
里就是范围外，不封装」。`StatEvent*` 六件套只声明在 `natives_missing.galaxy`，
而那个文件**不被任何引擎库 include**，于是被判"调用即编译失败 → SC2 静默
丢弃整个 MapScript"，连着好几轮写在 `cmlib_stat_h` / `cmlib_board_h` 的注释里。

round22 用两条反证推翻了这个判据：

  1. `core.sc2mod/.../NativeLib.TriggerLib` 里 `StatEventCreate` 带 `<FlagNative/>`
     （六个符号全部带，本轮复核过 Element Id=724BBE1B 等）。
  2. 官方合作 mod `LibCOOC.galaxy` **零自声明**直调 `StatEventCreate` / `StatEventSend`。

**根因**：SC2 的 native 符号表是**引擎内建**的，`.galaxy` 里的 `native` 声明
只是编辑器 / lint 的元数据，不是链接期依据。「不在 natives.galaxy」推不出
「不可调用」。

推论没有直接落库，而是先建 `probe_statevent.py` 三档真机探针
（baseline / call / wrapped），结果全 PASS → `verdict = USABLE`
（`probe_statevent_result.json`，2026-08-09 22:00）。本轮才落库。

## 边界（务必写进文档，别过度承诺）

探针只证明了**可编译、可调用、不中断 trigger**。原生注释写着 "Blizzard only.
Sends the Stat Event to Battle.net."——自定义地图能否真的上报 Battle.net
**无法从客户端侧观测**，本库不做任何承诺。把它当"调用安全的埋点 API"用。

## 本轮封装形态

严格复用探针 `wrapped` 档已验证的形态：**不自声明 native、直调、带守门早退**。
自声明反而危险 —— `check_cmlib.py` 第 1c 项就是查"库内符号与引擎 native 撞名"。

额外封一个引擎侧不管的真坑：`StatEventSend` 会**销毁**事件，句柄发完即废。
重复 Send 同一句柄等于对已销毁对象操作。库内维护 8 槽环形缓冲记录已发送句柄，
`CMLib_StatEvtOk` 据此拦截二次发送。

权威签名（`natives_missing.galaxy` L1523-1571，逐条比对）：

    native int  StatEventCreate(string eventName);
    native void StatEventAddDataString(int statEvent, string key, string value);
    native void StatEventAddDataInt(int statEvent, string key, int value);
    native void StatEventAddDataFixed(int statEvent, string key, fixed value);
    native void StatEventSend(int statEvent);
    native int  StatEventLastCreated();
"""
import re
import sys
from pathlib import Path

CM = Path(__file__).resolve().parent / "scripts" / "cmlib"
MARK = "CMLib :: Round23"

BLOCKS = {}

# ------------------------------------------------------------------ stat_h ---
BLOCKS["cmlib_stat_h.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round23 —— StatEvent（Battle.net 统计埋点）
// -----------------------------------------------------------------------------
// 【范围判定翻案记录】此前本模块头部注释写着「StatEvent* 刻意不封装」，理由是
// 符号只存在于 natives_missing.galaxy、不被任何引擎库 include。该判据已被
// round22 推翻：SC2 的 native 符号表是**引擎内建**的，.galaxy 里的 native
// 声明只是编辑器/lint 元数据。证据链：
//   ① NativeLib.TriggerLib 中六个 StatEvent* 全部带 <FlagNative/>；
//   ② 官方合作 mod LibCOOC.galaxy 零自声明直调 StatEventCreate/StatEventSend；
//   ③ probe_statevent.py 三档真机探针（baseline/call/wrapped）全 PASS。
//
// 【能力边界 —— 不要过度承诺】探针只证明了「可编译、可调用、不中断 trigger」。
// 原生注释是 "Blizzard only. Sends the Stat Event to Battle.net."，
// 自定义地图能否**真的上报** Battle.net 在客户端侧无法观测，本库不做承诺。
// 定位：调用安全的埋点 API。上报与否交给平台，不要拿它做游戏逻辑的判据。
//
// 【为什么不自声明 native】封装形态严格复用探针 wrapped 档：直调 + 守门早退。
// 库内自己写 `native int StatEventCreate(...)` 会与引擎内建符号撞名，
// check_cmlib.py 第 1c 项就是专门拦这个的致命检查。

// 无效事件句柄哨兵。引擎用 int 表示 StatEvent，0 视作无效。
const int CMLIB_STATEVT_INVALID = 0;

// 已发送句柄环形缓冲槽位数。StatEventSend 会**销毁**事件，
// 重复 Send 同一句柄 = 对已销毁对象操作。库内记住最近 8 个发过的句柄并拦截。
// 8 是权衡：埋点通常一局几次到几十次，且句柄递增不复用，
// 只需拦住"同一段逻辑里手滑发两次"这种真实误用。
const int CMLIB_STATEVT_SENT_MAX = 8;

// 建事件。空名直接返回 CMLIB_STATEVT_INVALID 并告警（引擎对空名行为未定义）。
int CMLib_StatEvtBegin(string lp_name);

// 句柄是否可用：非 0 且不在"已发送"环形缓冲里。
// 所有 Add / Send 都先过这一关，调用方可以不判直接串起来写。
bool CMLib_StatEvtOk(int lp_ev);

// 三类数据挂载。句柄无效或 key 为空一律静默忽略（埋点失败不该打断游戏逻辑）。
void CMLib_StatEvtStr(int lp_ev, string lp_key, string lp_value);
void CMLib_StatEvtInt(int lp_ev, string lp_key, int lp_value);
void CMLib_StatEvtFixed(int lp_ev, string lp_key, fixed lp_value);

// 发送并作废句柄。返回是否真的发出去了（false = 句柄无效或已发过）。
bool CMLib_StatEvtSend(int lp_ev);

// 最近创建的事件句柄。注意：它返回的是"最近 Create 的"，
// 已经 Send 过的句柄也会被返回，所以拿到后仍要过 CMLib_StatEvtOk。
int CMLib_StatEvtLast();

// CSV 批量挂载："k1:v1,k2:v2"。按**第一个**冒号切，所以值里可以再有冒号
// （"用时:12:30" → key="用时" value="12:30"）。key 会 trim 空格。
// 返回实际挂载成功的键数；句柄无效 / 空串 / 无冒号项均计 0。
int CMLib_StatEvtStrCSV(int lp_ev, string lp_spec);
// 同上，值走 CMLib_ParseInt 转 int（解析失败按 0 计，不丢键）。
int CMLib_StatEvtIntCSV(int lp_ev, string lp_spec);

// 一步到位：建 → CSV 批量挂载字符串 → 发送。返回是否成功发出。
// 最常见的埋点写法，省掉三行样板。
bool CMLib_StatEvtSendCSV(string lp_name, string lp_spec);

// 一步到位：建 → 挂单个 int → 发送。计数类埋点用这个。
bool CMLib_StatEvtSendInt(string lp_name, string lp_key, int lp_value);
"""

# -------------------------------------------------------------------- stat ---
BLOCKS["cmlib_stat.galaxy"] = r"""

// -----------------------------------------------------------------------------
// CMLib :: Round23 —— StatEvent 实现
// -----------------------------------------------------------------------------
// 形态严格复用 probe_statevent.py 的 wrapped 档（已真机 PASS）：
// 不自声明 native、直调引擎内建符号、每个入口守门早退。

// 已发送句柄环形缓冲。Galaxy 全局数组语法是 `类型[尺寸] 名`，
// 写成 `int 名[尺寸]` 会 G1001（round3 血泪）。
int[CMLIB_STATEVT_SENT_MAX] CMLib_StatEvtSentRing;
int CMLib_StatEvtSentAt;

int CMLib_StatEvtBegin(string lp_name) {
    if (lp_name == "") {
        CMLib_LogWarn("StatEvt", "事件名为空，忽略 Begin");
        return CMLIB_STATEVT_INVALID;
    }
    return StatEventCreate(lp_name);
}

bool CMLib_StatEvtOk(int lp_ev) {
    int lv_i;

    // 先挡 0：环形缓冲初值全是 0，不先挡就会把"没发过的无效句柄"
    // 和"槽位空着"混成同一件事。
    if (lp_ev == CMLIB_STATEVT_INVALID) {
        return false;
    }
    lv_i = 0;
    while ((lv_i < CMLIB_STATEVT_SENT_MAX)) {
        if ((CMLib_StatEvtSentRing[lv_i] == lp_ev)) {
            return false;
        }
        lv_i = lv_i + 1;
    }
    return true;
}

void CMLib_StatEvtStr(int lp_ev, string lp_key, string lp_value) {
    if (!CMLib_StatEvtOk(lp_ev)) {
        return;
    }
    if (lp_key == "") {
        return;
    }
    StatEventAddDataString(lp_ev, lp_key, lp_value);
}

void CMLib_StatEvtInt(int lp_ev, string lp_key, int lp_value) {
    if (!CMLib_StatEvtOk(lp_ev)) {
        return;
    }
    if (lp_key == "") {
        return;
    }
    StatEventAddDataInt(lp_ev, lp_key, lp_value);
}

void CMLib_StatEvtFixed(int lp_ev, string lp_key, fixed lp_value) {
    if (!CMLib_StatEvtOk(lp_ev)) {
        return;
    }
    if (lp_key == "") {
        return;
    }
    StatEventAddDataFixed(lp_ev, lp_key, lp_value);
}

bool CMLib_StatEvtSend(int lp_ev) {
    if (!CMLib_StatEvtOk(lp_ev)) {
        return false;
    }
    StatEventSend(lp_ev);
    // 记账要在 Send 之后：Send 若抛错中断线程，这个句柄就不该被标记成
    // "已发送"，否则重试路径会被自家守门拦死。
    CMLib_StatEvtSentRing[CMLib_StatEvtSentAt] = lp_ev;
    CMLib_StatEvtSentAt = CMLib_StatEvtSentAt + 1;
    if ((CMLib_StatEvtSentAt >= CMLIB_STATEVT_SENT_MAX)) {
        CMLib_StatEvtSentAt = 0;
    }
    return true;
}

int CMLib_StatEvtLast() {
    return StatEventLastCreated();
}

int CMLib_StatEvtStrCSV(int lp_ev, string lp_spec) {
    int    lv_n;
    int    lv_i;
    int    lv_done;
    string lv_item;
    int    lv_sepAt;
    string lv_key;
    string lv_val;

    if (!CMLib_StatEvtOk(lp_ev)) {
        return 0;
    }
    if (lp_spec == "") {
        return 0;
    }
    lv_n = CMLib_SplitCount(lp_spec, ",");
    lv_i = 0;
    lv_done = 0;
    while ((lv_i < lv_n)) {
        lv_item = CMLib_SplitAt(lp_spec, ",", lv_i);
        // StringFind 是 1-based（round10 血泪：core 切分器曾按 0-based 写，
        // 连锁污染了全库 CSV API）。> 0 同时排除了"没找到"(0) 与
        // "冒号在首位"(1 → key 为空) 两种情况里的前者。
        lv_sepAt = StringFind(lv_item, ":", true);
        if ((lv_sepAt > 0)) {
            lv_key = CMLib_TrimSpaces(StringSub(lv_item, 1, lv_sepAt - 1));
            lv_val = StringSub(lv_item, lv_sepAt + 1, StringLength(lv_item));
            if ((lv_key != "")) {
                StatEventAddDataString(lp_ev, lv_key, lv_val);
                lv_done = lv_done + 1;
            }
        }
        lv_i = lv_i + 1;
    }
    return lv_done;
}

int CMLib_StatEvtIntCSV(int lp_ev, string lp_spec) {
    int    lv_n;
    int    lv_i;
    int    lv_done;
    string lv_item;
    int    lv_sepAt;
    string lv_key;
    string lv_val;

    if (!CMLib_StatEvtOk(lp_ev)) {
        return 0;
    }
    if (lp_spec == "") {
        return 0;
    }
    lv_n = CMLib_SplitCount(lp_spec, ",");
    lv_i = 0;
    lv_done = 0;
    while ((lv_i < lv_n)) {
        lv_item = CMLib_SplitAt(lp_spec, ",", lv_i);
        lv_sepAt = StringFind(lv_item, ":", true);
        if ((lv_sepAt > 0)) {
            lv_key = CMLib_TrimSpaces(StringSub(lv_item, 1, lv_sepAt - 1));
            lv_val = StringSub(lv_item, lv_sepAt + 1, StringLength(lv_item));
            if ((lv_key != "")) {
                // 解析失败按 0 计而不是丢键 —— 埋点少一个键比多一个 0
                // 难查得多（下游按键名对齐时会整体错位）。
                StatEventAddDataInt(lp_ev, lv_key, CMLib_ParseInt(lv_val, 0));
                lv_done = lv_done + 1;
            }
        }
        lv_i = lv_i + 1;
    }
    return lv_done;
}

bool CMLib_StatEvtSendCSV(string lp_name, string lp_spec) {
    int lv_ev;

    lv_ev = CMLib_StatEvtBegin(lp_name);
    if (!CMLib_StatEvtOk(lv_ev)) {
        return false;
    }
    CMLib_StatEvtStrCSV(lv_ev, lp_spec);
    return CMLib_StatEvtSend(lv_ev);
}

bool CMLib_StatEvtSendInt(string lp_name, string lp_key, int lp_value) {
    int lv_ev;

    lv_ev = CMLib_StatEvtBegin(lp_name);
    if (!CMLib_StatEvtOk(lv_ev)) {
        return false;
    }
    CMLib_StatEvtInt(lv_ev, lp_key, lp_value);
    return CMLib_StatEvtSend(lv_ev);
}
"""


# ---------------------------------------------------------------------------
# 陈旧论述清理：把已被推翻的「刻意不封装」注释就地改写。
# 留着比删掉更糟 —— 下一轮读到它会再次把 StatEvent 判成范围外，白跑一轮探针。
# ---------------------------------------------------------------------------
STALE_STAT_H = """// 关于 StatEvent*（leaderboard 域 740 次调用）：
//   **本模块刻意不封装**。StatEventCreate / StatEventSend / StatEventLastCreated
//   等 6 个符号只出现在社区补声明文件 natives_missing.galaxy，
//   官方 core.sc2mod/TriggerLibs/natives.galaxy 里一条都没有（已 grep 确认 0 命中）。
//   Galaxy 一旦调用未声明函数就是编译失败，而编译失败会让 SC2
//   **静默丢弃整个 MapScript**（不报错、不写日志、InitMap 根本不跑）。
//   CMLib 是要被所有图 include 的通用库，不能拿全图存活赌一个未确认符号。
//   → 等真机探针实测通过后再单独开 cmlib_statevent 模块。"""

FRESH_STAT_H = """// 关于 StatEvent*（leaderboard 域 740 次调用）：
//   **round23 起已封装**，见本文件末尾 CMLib_StatEvt* 一节。
//   此前判为"范围外不封装"的理由（符号只在 natives_missing.galaxy、
//   官方 natives.galaxy 零命中）已被 round22 推翻 —— SC2 的 native 符号表是
//   **引擎内建**的，.galaxy 里的 native 声明只是编辑器/lint 元数据，
//   "不在 natives.galaxy" 推不出 "不可调用"。
//   证据：NativeLib.TriggerLib 六个符号全带 <FlagNative/>；官方合作 mod
//   LibCOOC.galaxy 零自声明直调；probe_statevent.py 三档真机探针全 PASS。
//   边界：只保证可调用，**不保证上报 Battle.net**。"""


def clean_stale(path: Path, old: str, new: str, label: str) -> bool:
    """就地替换陈旧论述。幂等：已替换过则跳过。"""
    cur = path.read_text(encoding="utf-8")
    if new.splitlines()[1] in cur:
        print(f"[round23] skip (论述已更新) {label}")
        return False
    if old not in cur:
        print(f"[round23] !! 未匹配到陈旧论述，跳过 {label}（可能已被手工改过）")
        return False
    path.write_text(cur.replace(old, new), encoding="utf-8")
    print(f"[round23] 论述更新 {label}")
    return True


def clean_board_h(path: Path) -> bool:
    """cmlib_board_h 里同样有一段「StatEvent 是陷阱 API」的论述，一并纠正。"""
    cur = path.read_text(encoding="utf-8")
    if "round23 起已由 cmlib_stat 封装" in cur:
        print("[round23] skip (论述已更新) cmlib_board_h.galaxy")
        return False
    # 定位那一段以 `//   - StatEvent*` 起头、直到下一个不以 `//` 开头的行。
    lines = cur.splitlines()
    out = []
    i = 0
    hit = False
    while i < len(lines):
        if lines[i].lstrip().startswith("//   - StatEvent*"):
            hit = True
            out.append("//   - StatEvent*（StatEventCreate/StatEventSend/…）：**round23 起已由 "
                       "cmlib_stat 封装**")
            out.append("//     （CMLib_StatEvt*）。此前判为陷阱 API 的理由「只声明在 "
                       "natives_missing.galaxy」")
            out.append("//     已被 round22 推翻 —— native 符号表是引擎内建的，"
                       "NativeLib.TriggerLib 里")
            out.append("//     六个符号全带 <FlagNative/>，三档真机探针亦全 PASS。"
                       "边界：不保证上报 Battle.net。")
            i += 1
            while i < len(lines) and lines[i].lstrip().startswith("//"):
                # 吃掉原论述剩余行，但遇到下一个条目（`//   - `）就停。
                if lines[i].lstrip().startswith("//   - "):
                    break
                i += 1
            continue
        out.append(lines[i])
        i += 1
    if not hit:
        print("[round23] !! cmlib_board_h 未匹配到 StatEvent 论述，跳过")
        return False
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("[round23] 论述更新 cmlib_board_h.galaxy")
    return True


def main() -> int:
    if not CM.is_dir():
        print(f"[round23] 找不到库目录: {CM}")
        return 1

    changed = skipped = 0
    for fname, block in BLOCKS.items():
        path = CM / fname
        if not path.is_file():
            print(f"[round23] !! 缺文件 {fname}")
            return 1
        cur = path.read_text(encoding="utf-8")
        if MARK in cur:
            print(f"[round23] skip (已应用) {fname}")
            skipped += 1
            continue
        path.write_text(cur.rstrip("\n") + "\n" + block, encoding="utf-8")
        print(f"[round23] patched {fname}  (+{len(block.splitlines())} 行)")
        changed += 1

    clean_stale(CM / "cmlib_stat_h.galaxy", STALE_STAT_H, FRESH_STAT_H,
                "cmlib_stat_h.galaxy")
    clean_board_h(CM / "cmlib_board_h.galaxy")

    print(f"[round23] 完成：{changed} 个文件更新，{skipped} 个已是最新")
    return 0


if __name__ == "__main__":
    sys.exit(main())
