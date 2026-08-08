"""从 VibeT3 派生两张【反向对照】地图，用于给 P0 真机验证提供 negative control。

为什么必须做反向对照（2026-08-08 血泪）：
  15:11 那次 "P0 PASS" 是 p0_probe_v2 的子串判定蒙出来的假阳性。只有正向 PASS、
  没有"同结构故意破坏必须 FAIL"的对照，就无法排除三类假阳性：
    (a) SC2 复用了缓存的旧编译产物，我们发的地图字节根本没生效；
    (b) Bank 里残留上一场的 response 被误判成本次 pong；
    (c) 判定逻辑本身太松。

两张对照各自隔离一个维度：

  NC-A  (VibeT3_NCA.sc2map)  让 gf_WriteBankInt 直接 return。
        所有 index/* 整型标记都写不出去 -> P0-A 必须 FAIL。
        证明：P0-A 的 PASS 来自我们发的这份字节，不是缓存/残留。

  NC-B  (VibeT3_NCB.sc2map)  让 gf_Dispatch 直接 return ""。
        入口注册、PollLoop、Bank 标记全部照常（P0-A 应当 PASS），
        但请求永远不会被处理、response/<rid> 永远不会写 -> P0-B 必须 FAIL。
        证明：P0-B 的 pong 是本次 RPC 真跑出来的，不是遗留。

两张对照都【保持可编译】——故意不用"破坏 include"那种编译期爆破，
因为那样 SC2 会静默丢弃整个 MapScript，FAIL 的原因就退化成"脚本没跑"，
无法区分是我们的改动生效还是地图整个坏了。
"""
from __future__ import annotations

import ctypes
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mpq_patch_kernel import (  # noqa: E402
    CRLF, LF, STREAM_FLAG_READ_ONLY, load_storm, mpq_read, mpq_replace,
)

KERNEL = "Base.SC2Data\\LibVibeKernel.galaxy"
WORK = Path(r"C:\tmp\vibe-p0")

# ------------------------------------------------------------------ NC-A 规则
NCA_ANCHOR = "void libVibeKernel_gf_WriteBankInt(string section, string key, int value) {"
NCA_INJECT = "\n".join([
    NCA_ANCHOR,
    '    // ==== NEG_CTL_A: 故意让所有整型 Bank 写入失效 ====',
    '    // 用 if(true) 包一层而不是裸 return，避免 Galaxy 编译器把后续语句判成',
    '    // 不可达代码而报错。对照期望：P0-A 必须 FAIL。',
    '    if (true) { return; }',
])

# ------------------------------------------------------------------ NC-B 规则
NCB_ANCHOR = "    string result;\n    // 解析请求字段（简单 key=value 解析）"
NCB_INJECT = "\n".join([
    "    string result;",
    '    // ==== NEG_CTL_B: 故意让请求分发整体失效 ====',
    '    // 入口注册 / PollLoop / Bank 标记一切照常，只是请求永远不被处理，',
    '    // 因此 response/<rid> 永不写入。对照期望：P0-A PASS 且 P0-B FAIL。',
    '    if (true) { return ""; }',
    "    // 解析请求字段（简单 key=value 解析）",
])


def build(src: Path, dst: Path, anchor: str, inject: str, tag: str,
          extra_checks) -> bool:
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)
    print(f"\n[{tag}] copy {src.name} -> {dst.name} ({dst.stat().st_size} B)")

    dll = load_storm()
    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, 0, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] open {dst}: {ctypes.get_last_error()}")
    try:
        text = mpq_read(dll, h, KERNEL).decode("utf-8-sig").replace(CRLF, LF)
        if anchor not in text:
            raise SystemExit(f"[FAIL] {tag} 锚点未命中，基线与预期不符")
        if text.count(anchor) != 1:
            raise SystemExit(f"[FAIL] {tag} 锚点出现 {text.count(anchor)} 次，拒绝歧义替换")
        patched = text.replace(anchor, inject, 1)

        out = WORK / f"LibVibeKernel.{tag}.galaxy"
        out.write_bytes(patched.replace(LF, CRLF).encode("utf-8"))
        mpq_replace(dll, h, KERNEL, out)
        dll.SFileFlushArchive(h)
        print(f"[{tag}] 已写回 MPQ（{out.stat().st_size} B）")
    finally:
        dll.SFileCloseArchive(h)

    h2 = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(h2)):
        raise SystemExit(f"[FAIL] {tag} 回读打开失败")
    try:
        back = mpq_read(dll, h2, KERNEL).decode("utf-8-sig").replace(CRLF, LF)
    finally:
        dll.SFileCloseArchive(h2)

    checks = dict(extra_checks(back))
    checks[f"{tag} 标记已注入"] = f"NEG_CTL_{tag[-1]}" in back
    checks["Fix A 仍在（pollorder 指纹）"] = "pollorder_fix" in back
    checks["watchdog 仍在"] = "VIBE_KERNEL_001_WATCHDOG_REGISTER" in back
    ok = True
    for k, v in checks.items():
        print(f"    [{'OK' if v else 'FAIL'}] {k}")
        ok = ok and v
    print(f"[{tag}] {'DONE' if ok else 'BROKEN'} -> {dst} ({dst.stat().st_size} B)")
    return ok


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\tmp\VibeT3.sc2map")
    if not src.exists():
        raise SystemExit(f"[FAIL] 基线不存在: {src}")
    WORK.mkdir(parents=True, exist_ok=True)

    # 对照图名字跟着基线走，避免"基线换了名字没换"造成的张冠李戴
    ok_a = build(
        src, src.with_name(src.stem + "_NCA.sc2map"), NCA_ANCHOR, NCA_INJECT, "NCA",
        lambda b: [
            ("WriteBankInt 首句即 return",
             b.index("if (true) { return; }") - b.index(NCA_ANCHOR) < 400),
            ("BankValueSetFromInt 仍在文件里（未误删）",
             "BankValueSetFromInt(libVibeKernel_gv_bankHandle" in b),
            ("Dispatch 未被动（NC-A 只隔离写入维度）",
             'if (true) { return ""; }' not in b),
        ],
    )

    ok_b = build(
        src, src.with_name(src.stem + "_NCB.sc2map"), NCB_ANCHOR, NCB_INJECT, "NCB",
        lambda b: [
            ("Dispatch 首句即 return \"\"", 'if (true) { return ""; }' in b),
            ("Dispatch 提前返回位于 ArgsGet 之前",
             b.index('if (true) { return ""; }')
             < b.index('sessionId = libVibeKernel_gf_ArgsGet(requestJson, "session_id");')),
            ("WriteBankInt 未被动（NC-B 只隔离分发维度）",
             "if (true) { return; }" not in b),
            ("HandleSystemPing 仍在（证明是分发被断，不是 handler 被删）",
             "libVibeKernel_gf_HandleSystemPing" in b),
        ],
    )

    print(f"\n[SUMMARY] NC-A={'OK' if ok_a else 'FAIL'}  NC-B={'OK' if ok_b else 'FAIL'}")
    return 0 if (ok_a and ok_b) else 1


if __name__ == "__main__":
    raise SystemExit(main())
