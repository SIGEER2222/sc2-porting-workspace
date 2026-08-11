"""在已构建的 gen 图上裁剪 `LibVibeInvokeDispatch_active.galaxy` 的 include 集合。

用途：台阶 A（地图自带内核 + 0 shard 纯 harness）真机就已 kernel_registered=false，
说明真凶落在「替换 active」这一步里。active 只有两类内容：
    (1) symbol_repair Stage A 补进来的地图自带库 include（LibA3ADAPTER 等）
    (2) include "LibVibeInvokeCommon"（generated 包的公共层）
本脚本按指定 include 子集重写 active，其余保持不变，从而把两类变量拆开单测。
未被 include 的文件留在 MPQ 里是**死文件**，不参与编译，不影响结论。

用法:
    python active_variant.py <out.SC2Map> none                 # 只保留内联 Dispatch
    python active_variant.py <out.SC2Map> common               # + Common
    python active_variant.py <out.SC2Map> extras               # + 5 个地图自带库
    python active_variant.py <out.SC2Map> LibEFA54406,common   # 任意子集
"""
from __future__ import annotations

import ctypes
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mpq_patch_kernel import (  # noqa: E402
    CRLF, LF, STREAM_FLAG_READ_ONLY, load_storm, mpq_read, mpq_replace,
)
import closure_doctor  # noqa: E402

SRC = Path(r"C:\tmp\VibeDeadOfNight-Gen.SC2Map")
ACTIVE = "Base.SC2Data\\LibVibeInvokeDispatch_active.galaxy"
EXTRAS = ["LibA3ADAPTER", "LibDeadOfNightObserver", "LibEFA54406",
          "LibNeuroCommandBridge", "LibPortingObserver"]

# 原图 tier0 stub 的函数体：只依赖 LibVibeKernel_h 提供的原型与全局，
# 已在真机 P0 PASS（对照组 VibeDeadOfNight-Ctl.SC2Map）。做 include 单变量实验时用它。
STUB = '''
string libVibeInvoke_gf_Dispatch(int functionId, string argsJson) {
    return libVibeKernel_gf_MakeResponse(
        "error",
        libVibeKernel_gv_currentSession,
        libVibeKernel_gv_lastRequestId,
        libVibeKernel_gv_lastSequence,
        "function.invoke",
        "FUNCTION_NOT_IN_MAP",
        "{\\"reason\\":\\"FUNCTION_NOT_IN_MAP\\",\\"detail\\":\\"" + IntToString(functionId) + "\\",\\"tier\\":0}");
}
'''


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    dst = Path(sys.argv[1])
    spec = sys.argv[2]
    if spec == "none":
        incs: list[str] = []
    elif spec == "common":
        incs = ["LibVibeInvokeCommon"]
    elif spec == "extras":
        incs = list(EXTRAS)
    elif spec == "all":
        incs = EXTRAS + ["LibVibeInvokeCommon"]
    else:
        incs = ["LibVibeInvokeCommon" if s.strip() == "common" else s.strip()
                for s in spec.split(",") if s.strip()]

    # --stub：函数体用**已知真机 PASS** 的原始 tier0 stub（只依赖 LibVibeKernel_h），
    # 从而把「include 集合」这一个变量单独拎出来测；不带则用构建产出的 harness 体。
    use_stub = "--stub" in sys.argv
    if dst.exists():
        dst.unlink()
    shutil.copy2(SRC, dst)

    dll = load_storm()
    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, 0, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] 打不开 {dst}")
    try:
        cur = mpq_read(dll, h, ACTIVE).decode("utf-8-sig", "replace").replace(CRLF, LF)
        if use_stub:
            body = STUB
        else:
            # 砍掉所有 include 行，只留下内联的 Dispatch 函数体与注释
            body = re.sub(r'^\s*include\s+"[^"]+"\s*$', "", cur, flags=re.M)
        head = [f"// [active_variant] spec={spec} -> include {incs or '<none>'}"]
        head += [f'include "{i}"' for i in incs]
        new = "\n".join(head) + "\n" + body
        tmp = Path(r"C:\tmp\vibe-p0") / "active_variant.galaxy"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(new.replace(LF, CRLF).encode("utf-8"))
        mpq_replace(dll, h, ACTIVE, tmp)
        dll.SFileFlushArchive(h)
    finally:
        dll.SFileCloseArchive(h)

    d = closure_doctor.diagnose(dst)
    print(f"[variant] {dst.name}  spec={spec}  include={incs}")
    print(f"[doctor ] {d.summary()}")
    if not d.clean:
        if d.orphan_protos:
            print(f"          孤儿原型样本 {d.orphan_protos[:8]}")
        if d.dup_impls:
            print(f"          重复实现样本 {d.dup_impls[:8]}")
        if getattr(d, "undefined_calls", None):
            print(f"          未定义调用样本 {sorted(d.undefined_calls)[:8]}")
        if getattr(d, "undefined_idents", None):
            print(f"          未定义标识符样本 {sorted(d.undefined_idents)[:8]}")
    print(f"[{'CLEAN' if d.clean else 'BROKEN'}] {dst} ({dst.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
