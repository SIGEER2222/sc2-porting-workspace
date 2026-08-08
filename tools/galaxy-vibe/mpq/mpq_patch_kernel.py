"""Patch a single .galaxy file inside an SC2 map MPQ, isolated from the churning workspace.

Base: C:/tmp/VibeT0.sc2map -- the tier0 + fail-closed-structref build that already passed the
SC2 compile gate on 2026-08-08 15:13 (evidence: a Crash with NO paired ScriptError, whereas
every earlier crash had one).

Fix applied to Base.SC2Data\\LibVibeKernel.galaxy:
  PollLoop must NOT be launched with TriggerExecute(..., waitUntilDone=true).
  That synchronously enters while(true) + Wait(c_timeGame) during InitMap(), where the game
  clock has not started yet, so Wait never returns -> init deadlock -> engine ACCESS_VIOLATION
  (reading from 0x40). Also the `register_entrypoints_done` write that followed it was dead code.

Notes on this StormLib build (v9.40 x64):
  - UNICODE build: local file paths are wchar_t* (c_wchar_p); MPQ-internal archived names
    are still const char* (ANSI). Mixing them yields ERROR_FILE_NOT_FOUND(2).
  - Files inside the map use CRLF line endings.
"""
from __future__ import annotations

import ctypes
import shutil
import sys
from ctypes import wintypes
from pathlib import Path

STORM_DLL = Path(
    r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\artifacts\stormlib-v9.40\x64\StormLib.dll"
)

MPQ_FILE_COMPRESS = 0x00000200
MPQ_FILE_REPLACEEXISTING = 0x80000000
MPQ_COMPRESSION_ZLIB = 0x02
STREAM_FLAG_READ_ONLY = 0x00000100

TARGET = "Base.SC2Data\\LibVibeKernel.galaxy"

CRLF = "\r\n"
LF = "\n"


def load_storm() -> ctypes.WinDLL:
    dll = ctypes.WinDLL(str(STORM_DLL), use_last_error=True)
    dll.SFileOpenArchive.argtypes = [
        ctypes.c_wchar_p, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)
    ]
    dll.SFileOpenArchive.restype = wintypes.BOOL
    dll.SFileCloseArchive.argtypes = [ctypes.c_void_p]
    dll.SFileCloseArchive.restype = wintypes.BOOL
    dll.SFileOpenFileEx.argtypes = [
        ctypes.c_void_p, ctypes.c_char_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)
    ]
    dll.SFileOpenFileEx.restype = wintypes.BOOL
    dll.SFileGetFileSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD)]
    dll.SFileGetFileSize.restype = wintypes.DWORD
    dll.SFileReadFile.argtypes = [
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p
    ]
    dll.SFileReadFile.restype = wintypes.BOOL
    dll.SFileCloseFile.argtypes = [ctypes.c_void_p]
    dll.SFileCloseFile.restype = wintypes.BOOL
    dll.SFileAddFileEx.argtypes = [
        ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_char_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD
    ]
    dll.SFileAddFileEx.restype = wintypes.BOOL
    dll.SFileFlushArchive.argtypes = [ctypes.c_void_p]
    dll.SFileFlushArchive.restype = wintypes.BOOL
    return dll


def mpq_read(dll, hmpq, name: str) -> bytes:
    hfile = ctypes.c_void_p()
    if not dll.SFileOpenFileEx(hmpq, name.encode("utf-8"), 0, ctypes.byref(hfile)):
        raise RuntimeError(f"SFileOpenFileEx failed for {name}: {ctypes.get_last_error()}")
    try:
        high = wintypes.DWORD(0)
        size = dll.SFileGetFileSize(hfile, ctypes.byref(high))
        buf = ctypes.create_string_buffer(size)
        got = wintypes.DWORD(0)
        if not dll.SFileReadFile(hfile, buf, size, ctypes.byref(got), None):
            raise RuntimeError("SFileReadFile failed")
        return buf.raw[: got.value]
    finally:
        dll.SFileCloseFile(hfile)


def mpq_replace(dll, hmpq, archived: str, local: Path) -> None:
    ok = dll.SFileAddFileEx(
        hmpq,
        str(local),
        archived.encode("utf-8"),
        MPQ_FILE_COMPRESS | MPQ_FILE_REPLACEEXISTING,
        MPQ_COMPRESSION_ZLIB,
        MPQ_COMPRESSION_ZLIB,
    )
    if not ok:
        raise RuntimeError(
            f"SFileAddFileEx failed for {archived}: {ctypes.get_last_error()}"
        )


# ---------------------------------------------------------------- patch rules
OLD_EXEC = "    TriggerExecute(libVibeKernel_gt_PollLoop, false, true);"
OLD_DONE = '    libVibeKernel_gf_WriteBankInt("index", "register_entrypoints_done", 1);'

NEW_BLOCK = "\n".join([
    '    // [P0-FIX] 注册完成标记必须写在 PollLoop 派发之前：',
    '    // PollLoop 是 while(true)，一旦进入就不再回到此处（原代码此行是死代码）。',
    '    libVibeKernel_gf_WriteBankInt("index", "register_entrypoints_done", 1);',
    '',
    '    // [P0-FIX] 崩溃铁律（2026-08-08 真机 ACCESS_VIOLATION 实证）：',
    '    // PollLoop 含 while(true)+Wait(c_timeGame)，绝不可 waitUntilDone=true 同步执行。',
    '    // 那样会在 InitMap() 阶段就地死循环，而游戏时钟此时尚未推进，Wait 永不返回',
    '    // -> 初始化序列死锁 -> 引擎 ACCESS_VIOLATION (reading from 0x40)。',
    '    TriggerExecute(libVibeKernel_gt_PollLoop, false, false);',
])

ANCHOR = '    libVibeKernel_gf_WriteBankInt("index", "register_entrypoints_entered", 1);'
EXTRA = "\n".join([
    '',
    '    // [P0-FIX] 补写核心初始化标记。gf_Init() 在 InitLib()（InitMap 期间）被调用，',
    '    // 那时 Bank 子系统可能尚未挂载，BankLoad 返回 null 使写入静默丢失，',
    '    // 而 gv_initialized 已置真不会重试。本函数由 TimeElapsed(0.0) 触发，',
    '    // 运行在完整初始化之后，Bank 一定可用。',
    '    libVibeKernel_gf_WriteBankInt("index", "kernel_initialized", 1);',
    '    libVibeKernel_gf_WriteBankInt("index", "register_entrypoints_alive", 1);',
])


def patch(text: str) -> str:
    if OLD_EXEC not in text:
        raise SystemExit("[FAIL] 未找到同步 TriggerExecute，基线与预期不符")
    if OLD_DONE not in text:
        raise SystemExit("[FAIL] 未找到 register_entrypoints_done 写入行")
    text = text.replace(OLD_DONE + "\n", "", 1)
    text = text.replace(OLD_EXEC, NEW_BLOCK, 1)
    if ANCHOR in text and "register_entrypoints_alive" not in text:
        text = text.replace(ANCHOR, ANCHOR + EXTRA, 1)
    return text


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else r"C:\tmp\VibeT0.sc2map")
    dst = Path(sys.argv[2] if len(sys.argv) > 2 else r"C:\tmp\VibeT1.sc2map")
    work = Path(r"C:\tmp\vibe-p0")
    work.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        raise SystemExit(f"[FAIL] 基线地图不存在: {src}")
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)
    print(f"[copy] {src} -> {dst} ({dst.stat().st_size} B)")

    dll = load_storm()
    hmpq = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, 0, ctypes.byref(hmpq)):
        raise SystemExit(f"[FAIL] SFileOpenArchive 失败: {ctypes.get_last_error()}")
    try:
        raw = mpq_read(dll, hmpq, TARGET)
        text = raw.decode("utf-8-sig").replace(CRLF, LF)
        print(f"[read] {TARGET}: {len(raw)} B")

        patched = patch(text)
        out = work / "LibVibeKernel.patched.galaxy"
        out.write_bytes(patched.replace(LF, CRLF).encode("utf-8"))
        print(f"[patch] -> {out} ({out.stat().st_size} B)")

        mpq_replace(dll, hmpq, TARGET, out)
        dll.SFileFlushArchive(hmpq)
        print("[write] 已替换进 MPQ")
    finally:
        dll.SFileCloseArchive(hmpq)

    hmpq2 = ctypes.c_void_p()
    if not dll.SFileOpenArchive(str(dst), 0, STREAM_FLAG_READ_ONLY, ctypes.byref(hmpq2)):
        raise SystemExit("[FAIL] 回读打开失败")
    try:
        back = mpq_read(dll, hmpq2, TARGET).decode("utf-8-sig").replace(CRLF, LF)
    finally:
        dll.SFileCloseArchive(hmpq2)

    checks = {
        "async TriggerExecute": "TriggerExecute(libVibeKernel_gt_PollLoop, false, false);" in back,
        "no sync TriggerExecute": "TriggerExecute(libVibeKernel_gt_PollLoop, false, true);" not in back,
        "done marker before dispatch": back.index("register_entrypoints_done")
        < back.index("TriggerExecute(libVibeKernel_gt_PollLoop, false, false);"),
        "alive marker": "register_entrypoints_alive" in back,
    }
    for k, v in checks.items():
        print(f"  [{'OK' if v else 'FAIL'}] {k}")
    if not all(checks.values()):
        return 1
    print(f"[DONE] {dst} ({dst.stat().st_size} B)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
