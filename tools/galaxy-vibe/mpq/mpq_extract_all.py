"""mpq_extract_all.py —— 用 StormLib 把 SC2Map/SC2Mod 全量解包成目录形态。

【为什么不用 mpyq】
SC2 的 `(listfile)` 是**加密**的，`mpyq` 直接 `NotImplementedError: Encryption is
not supported yet.` 开箱即废。StormLib 走 `SFileOpenArchive` + `SFileReadFile`
则透明解密，是本仓唯一可信的 MPQ 读取路径（`compile_unit.load_storm()` 已封装）。

【典型用途 —— 离线阳性对照】
真机时间片昂贵，改一行 launcher 逻辑就重开一局代价太大。正确做法是把已知 BROKEN
的成品图解包成目录，在目录里做**等价于修复后**的最小改动，再用
`staged_map_doctor.py`（pack → closure_doctor）验证是否转 CLEAN。
这样「fix 是否修在正确的地方」在完全不碰 SC2 的前提下就能拿到证据。

用法:
    python mpq_extract_all.py <map.SC2Map|mod.SC2Mod> <output_dir>
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import compile_unit as cu  # noqa: E402


def extract(src: Path, dst: Path) -> tuple[int, int]:
    """全量解包，返回 (成功数, 失败数)。失败项打印到 stdout，不静默吞掉。"""
    dst.mkdir(parents=True, exist_ok=True)
    dll = cu.load_storm()
    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(src), 0, cu.STREAM_FLAG_READ_ONLY, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] open {src}")
    ok = fail = 0
    try:
        raw = cu.mpq_read(dll, h, "(listfile)").decode("utf-8", "replace")
        names = [x.strip() for x in raw.replace("\r\n", "\n").split("\n") if x.strip()]
        print(f"[listfile] {len(names)} entries")
        for n in names:
            try:
                data = cu.mpq_read(dll, h, n)
            except Exception as exc:  # noqa: BLE001 —— 逐项报告，别整体崩
                fail += 1
                print(f"  [MISS] {n}: {exc}")
                continue
            out = dst / n.replace("\\", "/")
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(data)
            ok += 1
    finally:
        dll.SFileCloseArchive(h)
    return ok, fail


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    ok, fail = extract(Path(sys.argv[1]), Path(sys.argv[2]))
    print(f"[done ] extracted={ok} failed={fail} -> {sys.argv[2]}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
