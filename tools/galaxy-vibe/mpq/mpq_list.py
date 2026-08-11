"""列举 .SC2Map/.SC2Mod MPQ 内文件清单（排障用）。

用法: python mpq_list.py <archive> [filter-substr]
"""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mpq_patch_kernel import STREAM_FLAG_READ_ONLY, load_storm  # noqa: E402


# 【实测值，勿按头文件猜】StormLib 声明的是 `char cFileName[MAX_PATH]`，而 MAX_PATH
# 在 Windows 上被 windows.h 抢先定义成 260（不是 StormLib 自带的 1024 兜底）。
# 2026-08-08 用 dump 原始字节验证过这份 DLL：名字在偏移 0，szPlainName 指针落在
# 偏移 264（260 补齐到 8 字节对齐），其后 hash/block/size/flags 解出 0x80000200 等
# 合理值。写成 1024 会让后面所有 DWORD 全读成 0。
STORM_MAX_PATH = 260
# 单个 SC2 地图撑死几千个文件。超过这个数一定是搜索没收敛，不是地图真有这么多文件。
MAX_ENTRIES = 200_000


class FindData(ctypes.Structure):
    """必须与 StormLib 的 `SFILE_FIND_DATA` **逐字段对齐**。

    【2026-08-08 事故，勿改字段顺序】旧版把一串 DWORD 排在前面、`szCFileName`
    放到最后，与 StormLib 的真实布局（`cFileName[MAX_PATH]` 在**最前**、紧跟
    `szPlainName` 指针、之后才是各 DWORD）完全错位。后果：读出的文件名和大小全
    是垃圾，而且当时那个 `while True` 没有任何迭代上限 —— 两个 mpq_list 进程各自
    涨到 3.4/3.8 GB，把整机可用内存压到 0.38 GB，**SC2 在加载地图时被饿死崩溃**，
    还被误判成「地图有问题」「SC2 持有句柄导致挂死」。真凶在这里。
    """

    _fields_ = [
        ("cFileName", ctypes.c_char * STORM_MAX_PATH),
        ("szPlainName", ctypes.c_char_p),
        ("dwHashIndex", ctypes.c_uint32),
        ("dwBlockIndex", ctypes.c_uint32),
        ("dwFileSize", ctypes.c_uint32),
        ("dwFileFlags", ctypes.c_uint32),
        ("dwCompSize", ctypes.c_uint32),
        ("dwFileTimeLo", ctypes.c_uint32),
        ("dwFileTimeHi", ctypes.c_uint32),
        ("lcLocale", ctypes.c_uint32),
    ]


def _bind_find_api(dll: ctypes.WinDLL) -> None:
    """显式声明查找系 API 的签名。不声明的话 ctypes 会按默认规则转参，
    64 位句柄有被截成 32 位的风险，表现为搜索行为不可预期。"""
    dll.SFileFindFirstFile.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(FindData), ctypes.c_void_p
    ]
    dll.SFileFindFirstFile.restype = ctypes.c_void_p
    dll.SFileFindNextFile.argtypes = [ctypes.c_void_p, ctypes.POINTER(FindData)]
    dll.SFileFindNextFile.restype = ctypes.c_int
    dll.SFileFindClose.argtypes = [ctypes.c_void_p]
    dll.SFileFindClose.restype = ctypes.c_int


def list_files(archive: Path) -> list[tuple[str, int]]:
    dll = load_storm()
    _bind_find_api(dll)
    h = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(archive), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(h)):
        raise SystemExit(f"[FAIL] open {archive}: {ctypes.get_last_error()}")
    out: list[tuple[str, int]] = []
    fd = FindData()
    fh = dll.SFileFindFirstFile(h, b"*", ctypes.byref(fd), None)
    try:
        if fh:
            try:
                seen: set[tuple[int, int, str]] = set()
                while True:
                    # fail-closed 双保险：条数上限 + 三元组环检测。
                    # 宁可炸出来，也不要再让它悄悄把整机内存吃光拖崩 SC2。
                    if len(out) >= MAX_ENTRIES:
                        raise SystemExit(
                            f"[FAIL] {archive.name}: 枚举超过 {MAX_ENTRIES} 条仍未结束，"
                            "判定为搜索未收敛，已中止（防止耗尽内存）。")
                    name = fd.cFileName.decode("gbk", "replace")
                    key = (fd.dwHashIndex, fd.dwBlockIndex, name)
                    if key in seen:
                        raise SystemExit(
                            f"[FAIL] {archive.name}: 枚举重复命中 {name!r} "
                            f"(hash={key[0]} block={key[1]})，搜索成环，已中止。")
                    seen.add(key)
                    out.append((name, fd.dwFileSize))
                    if not dll.SFileFindNextFile(fh, ctypes.byref(fd)):
                        break
            finally:
                dll.SFileFindClose(fh)
    finally:
        dll.SFileCloseArchive(h)
    return out


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    arc = Path(sys.argv[1])
    sub = sys.argv[2].lower() if len(sys.argv) > 2 else None
    files = list_files(arc)
    sep = chr(92)  # backslash
    rows = [(n, s) for n, s in files if not sub or sub in n.lower()]
    print(f"total={len(files)} shown={len(rows)}  archive={arc.name}")
    for n, s in sorted(rows):
        depth = "root" if sep not in n else n.rsplit(sep, 1)[0]
        print(f"  [{depth}] {n}  ({s} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
