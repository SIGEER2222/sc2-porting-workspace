"""把 VibeT4 真机验证通过的 4 处内核修复精确合并进工作区源。

工作区源与 T4 是双向分叉的：
  - 工作区独有（保留）：tagCache、KERNEL001 悲观响应、consume-before-dispatch
  - T4 独有（本脚本合并进来）：
      Fix B  Bank handle 绝不跨帧缓存
      Fix A  PollLoop 循环体读写顺序（先抢读 pending，再做任何写入）
      Fix D1 Watchdog 注册必须异步，且 done 标记不能落在 while(true) trigger 派发之后
      Fix D2 Watchdog 重启 PollLoop 必须异步（否则 watchdog 自废）

只做字符串精确替换，任一处 miss 即中止，不做模糊匹配。
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

WS = Path(r"E:/Code/MyMod/SC2VibeTools/sc2-porting-workspace")
SRC = WS / "tools/galaxy-vibe/kernel/LibVibeKernel.galaxy"

# ---------------------------------------------------------------- Fix B
OLD_B = """void libVibeKernel_gf_ReloadBank() {
    if (libVibeKernel_gv_bankHandle == null) {
        libVibeKernel_gv_bankHandle = BankLoad(libVibeKernel_gv_BankName, libVibeKernel_gv_BankPlayer);
    } else {
        BankReload(libVibeKernel_gv_bankHandle);
    }
    if (libVibeKernel_gv_bankHandle != null) {
        BankWait(libVibeKernel_gv_bankHandle);
    }
}

void libVibeKernel_gf_EnsureBankLoaded() {
    if (libVibeKernel_gv_bankHandle == null) {
        libVibeKernel_gv_bankHandle = BankLoad(libVibeKernel_gv_BankName, libVibeKernel_gv_BankPlayer);
        if (libVibeKernel_gv_bankHandle != null) {
            BankWait(libVibeKernel_gv_bankHandle);
        }
    }
}"""

NEW_B = """// ==== BEGIN VIBE_KERNEL_003_NO_HANDLE_CACHE ====
// 铁律：Bank handle 绝不跨帧缓存。
// 真机取证 2026-08-08：InitMap() 第 2 条指令就会触发首次 BankLoad，
// 那一刻拿到的 handle 若不可用，`if (handle == null)` 此后恒为假，
// 整局所有 Bank 写入静默 no-op（不报错、不进日志、静态 lint 也查不出）。
// 同帧内 LibMapModBridge 每次都重新 BankLoad，写入就正常 —— 差别只在缓不缓存。
//
// BankLoad 对已加载的 bank 返回引擎侧同一对象、不重读磁盘，
// 因此"连续写多个 key 会丢内存中未 Save 的键"这个顾虑不成立。
// 真正强制重读磁盘的是 BankReload，只放在下行读取路径里。
void libVibeKernel_gf_ReloadBank() {
    libVibeKernel_gv_bankHandle = BankLoad(libVibeKernel_gv_BankName, libVibeKernel_gv_BankPlayer);
    if (libVibeKernel_gv_bankHandle != null) {
        BankReload(libVibeKernel_gv_bankHandle);
        BankWait(libVibeKernel_gv_bankHandle);
    }
}

void libVibeKernel_gf_EnsureBankLoaded() {
    libVibeKernel_gv_bankHandle = BankLoad(libVibeKernel_gv_BankName, libVibeKernel_gv_BankPlayer);
    if (libVibeKernel_gv_bankHandle != null) {
        BankWait(libVibeKernel_gv_bankHandle);
    }
}
// ==== END VIBE_KERNEL_003_NO_HANDLE_CACHE ===="""

# ---------------------------------------------------------------- Fix A (head)
OLD_A_HEAD = """    // 写入标记：证明 PollLoop 被启动
    libVibeKernel_gf_WriteBankInt("diag", "pollloop_started", 1);

    while (true) {
        // Refresh before the diagnostic write so external Host requests are not
        // overwritten by the cached Bank handle.
        libVibeKernel_gf_ReloadBank();
        // 诊断计数
        libVibeKernel_gv_bankPollCount += 1;
        // Make the native P2 economy observable to the P2 policy without
        // exposing P2 through the P1 player_common observation.
        libVibeKernel_gf_WriteModelP2Snapshot();
"""

NEW_A_HEAD = """    // 写入标记：证明 PollLoop 被启动
    libVibeKernel_gf_WriteBankInt("diag", "pollloop_started", 1);
    // 构建指纹：确认真机跑的确实是合并过 3 处修复的这一版。
    libVibeKernel_gf_WriteBankInt("diag", "pollorder_fix", 2);
    libVibeKernel_gf_WriteBankInt("diag", "bankhandle_fix", 3);
    libVibeKernel_gf_WriteBankInt("diag", "merged_fix", 5);

    while (true) {
// ==== BEGIN VIBE_KERNEL_002_POLL_ORDER HEAD ====
        // ！！！读写顺序铁律（2026-08-08 真机取证）！！！
        // 循环体内任何 BankSave 都必须排在 pending_request_id 读取之后。
        // ReloadBank() 若这一拍没抓到 Host 刚写盘的请求（SC2 Bank 缓存，
        // CMRE-RUNTIME-003），紧随其后的写入会用内核内存态 BankSave 覆盖磁盘，
        // 把 Host 的 request/<id> 与 index/pending_request_id 永久抹掉 ——
        // 一次偶发漏读就此变成永久失败，且现场证据同时被销毁。
        libVibeKernel_gf_ReloadBank();
        // 诊断计数（纯内存自增，不落盘）
        libVibeKernel_gv_bankPollCount += 1;
        // 先把 pending 请求抢读进局部变量，之后任何写入都伤不到它。
        pendingId = libVibeKernel_gf_ReadBankKey("index", "pending_request_id");
        requestJson = "";
        if (pendingId != "" && pendingId != libVibeKernel_gv_lastPolledRequestId) {
            requestJson = libVibeKernel_gf_ReadBankKey("request", pendingId);
        }
// ==== END VIBE_KERNEL_002_POLL_ORDER HEAD ====
"""

# ---------------------------------------------------------------- Fix A (tail)
OLD_A_TAIL = """        // 读取 pending_request_id
        pendingId = libVibeKernel_gf_ReadBankKey("index", "pending_request_id");
        if (pendingId != "" && pendingId != libVibeKernel_gv_lastPolledRequestId) {
            // 读取完整请求
            requestJson = libVibeKernel_gf_ReadBankKey("request", pendingId);
            if (requestJson != "") {
                // 分发处理
                // VIBE-KERNEL-001: consume before dispatch (poison-request guard).
                libVibeKernel_gv_lastPolledRequestId = pendingId;
                response = libVibeKernel_gf_Dispatch(requestJson);
                opName = libVibeKernel_gf_ArgsGet(requestJson, "operation");
                libVibeKernel_gf_EchoChat("[Vibe] " + opName + " done (id=" + pendingId + ")");
            }
        }

        // 等待 0.5 秒游戏时间（让出控制权给游戏循环）
        Wait(0.5, c_timeGame);"""

NEW_A_TAIL = """// ==== BEGIN VIBE_KERNEL_002_POLL_ORDER TAIL ====
        // 请求已在循环开头抢读，这里只分发，不再重复读 Bank。
        if (requestJson != "") {
            // VIBE-KERNEL-001: consume before dispatch (poison-request guard).
            libVibeKernel_gv_lastPolledRequestId = pendingId;
            response = libVibeKernel_gf_Dispatch(requestJson);
            opName = libVibeKernel_gf_ArgsGet(requestJson, "operation");
            libVibeKernel_gf_EchoChat("[Vibe] " + opName + " done (id=" + pendingId + ")");
        }

        // P2 经济快照：必须排在请求分发之后（见循环开头的读写顺序铁律）。
        libVibeKernel_gf_WriteModelP2Snapshot();
// ==== END VIBE_KERNEL_002_POLL_ORDER TAIL ====

        // 等待 0.5 秒游戏时间（让出控制权给游戏循环）
        Wait(0.5, c_timeGame);"""

# ---------------------------------------------------------------- Fix D1
OLD_D1 = """    // PollLoop 入口（API 模式主传输路径，Wait-based 持续轮询）
    // 使用 TimeElapsed 0.0 启动一次，进入 while(true)+Wait 循环
    libVibeKernel_gt_PollLoop = TriggerCreate("libVibeKernel_gt_PollLoop_Func");
    TriggerAddEventTimeElapsed(libVibeKernel_gt_PollLoop, 0.0, c_timeGame);
    // 双保险：立即执行一次（API 模式下 TimeElapsed 0.0 可能不触发）
    TriggerExecute(libVibeKernel_gt_PollLoop, false, false);   // 异步——见上方死代码铁律
// ==== BEGIN STAGE26_FULL_INVOKE KERNEL001_WATCHDOG_REGISTER ====
    // VIBE-KERNEL-001: watchdog keeps the transport alive across handler aborts.
    libVibeKernel_gt_Watchdog = TriggerCreate("libVibeKernel_gt_Watchdog_Func");
    TriggerExecute(libVibeKernel_gt_Watchdog, false, true);
    libVibeKernel_gf_WriteBankInt("index", "register_entrypoints_watchdog_done", 1);
// ==== END STAGE26_FULL_INVOKE KERNEL001_WATCHDOG_REGISTER ====
    // 写入注册完成标记（供 Host 端验证触发器已注册）
    libVibeKernel_gf_WriteBankInt("index", "register_entrypoints_done", 1);
"""

NEW_D1 = """    // PollLoop 入口（API 模式主传输路径，Wait-based 持续轮询）
    // 使用 TimeElapsed 0.0 启动一次，进入 while(true)+Wait 循环
    libVibeKernel_gt_PollLoop = TriggerCreate("libVibeKernel_gt_PollLoop_Func");
    TriggerAddEventTimeElapsed(libVibeKernel_gt_PollLoop, 0.0, c_timeGame);
// ==== BEGIN VIBE_KERNEL_001_WATCHDOG_REGISTER ====
    // 传输层自愈兜底。先于 PollLoop 派发注册，保证任何情况下 watchdog 都已就位。
    // watchdog 体内是 while(true)+Wait，waitUntilDone 必须为 false，
    // 否则本行之后全是死代码（历史事故：watchdog_done / register_entrypoints_done 从未写入）。
    libVibeKernel_gt_Watchdog = TriggerCreate("libVibeKernel_gt_Watchdog_Func");
    TriggerExecute(libVibeKernel_gt_Watchdog, false, false);   // 异步——见死代码铁律
    libVibeKernel_gf_WriteBankInt("index", "register_entrypoints_watchdog_done", 1);
// ==== END VIBE_KERNEL_001_WATCHDOG_REGISTER ====

    // 注册完成标记必须写在 PollLoop 派发之前（PollLoop 进入后不再返回）。
    libVibeKernel_gf_WriteBankInt("index", "register_entrypoints_done", 1);

    // 双保险：立即执行一次（API 模式下 TimeElapsed 0.0 可能不触发）
    TriggerExecute(libVibeKernel_gt_PollLoop, false, false);   // 异步——见死代码铁律
"""

# ---------------------------------------------------------------- Fix D2
OLD_D2 = """            if (libVibeKernel_gt_PollLoop != null) {
                TriggerExecute(libVibeKernel_gt_PollLoop, false, true);
            }"""

NEW_D2 = """            if (libVibeKernel_gt_PollLoop != null) {
                // 必须异步：同步调用会让 watchdog 自身被 PollLoop 的 while(true) 永久吞掉，
                // 重启一次之后 watchdog 就再也不工作了（自废）。
                TriggerExecute(libVibeKernel_gt_PollLoop, false, false);
            }"""

EDITS = [
    ("Fix B  Bank handle 不缓存", OLD_B, NEW_B),
    ("Fix A  PollLoop head 抢读", OLD_A_HEAD, NEW_A_HEAD),
    ("Fix A  PollLoop tail 分发", OLD_A_TAIL, NEW_A_TAIL),
    ("Fix D1 Watchdog 注册异步", OLD_D1, NEW_D1),
    ("Fix D2 Watchdog 重启异步", OLD_D2, NEW_D2),
]


def main() -> int:
    raw = SRC.read_bytes()
    crlf = b"\r\n" in raw
    text = raw.decode("utf-8-sig" if raw.startswith(b"\xef\xbb\xbf") else "utf-8")
    bom = raw.startswith(b"\xef\xbb\xbf")
    norm = text.replace("\r\n", "\n")
    before_md5 = hashlib.md5(raw).hexdigest()

    for label, old, new in EDITS:
        n = norm.count(old)
        if n != 1:
            print(f"ABORT  {label}: 期望 1 处匹配，实得 {n}")
            return 1
        norm = norm.replace(old, new)
        print(f"OK     {label}")

    out = norm.replace("\n", "\r\n") if crlf else norm
    data = out.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    SRC.write_bytes(data)
    print(f"\nwrote {SRC}")
    print(f"  md5 {before_md5} -> {hashlib.md5(data).hexdigest()}")
    print(f"  size {len(raw)} -> {len(data)} (crlf={crlf}, bom={bom})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
