#!/usr/bin/env python3
"""Probe whether a unit type exists in an SC2 MPQ by extracting UnitData.xml.

Usage: mpq_extract_probe.py <mpq> <unit_id>
Reads Base.SC2Data/GameData/UnitData.xml via StormLib and prints whether the
unit id appears as a CUnit id, plus a few neighbour lines for sanity.
"""
import ctypes
import sys
from pathlib import Path

STORMLIB = Path(r"E:\Code\MyMod\SC2VibeTools\sc2-porting-workspace\artifacts\stormlib-v9.40\x64\StormLib.dll")


def open_archive(path: Path):
    storm = ctypes.WinDLL(str(STORMLIB), use_last_error=True)
    storm.SFileOpenArchive.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    storm.SFileOpenArchive.restype = ctypes.c_bool
    storm.SFileOpenFileEx.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    storm.SFileOpenFileEx.restype = ctypes.c_bool
    storm.SFileGetFileSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    storm.SFileGetFileSize.restype = ctypes.c_uint32
    storm.SFileReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
    storm.SFileReadFile.restype = ctypes.c_bool
    storm.SFileCloseFile.argtypes = [ctypes.c_void_p]
    storm.SFileCloseFile.restype = ctypes.c_bool
    storm.SFileCloseArchive.argtypes = [ctypes.c_void_p]
    storm.SFileCloseArchive.restype = ctypes.c_bool

    h = ctypes.c_void_p()
    if not storm.SFileOpenArchive(str(path), 0, 0, ctypes.byref(h)):
        raise OSError(f"SFileOpenArchive failed: {ctypes.get_last_error()}")
    return storm, h


def read_file(storm, h, name: str) -> bytes:
    f = ctypes.c_void_p()
    if not storm.SFileOpenFileEx(h, name.encode("ascii"), 0, ctypes.byref(f)):
        return b""
    size = storm.SFileGetFileSize(f, ctypes.byref(ctypes.c_uint32()))
    buf = ctypes.create_string_buffer(size)
    read = ctypes.c_uint32()
    storm.SFileReadFile(f, buf, size, ctypes.byref(read), None)
    storm.SFileCloseFile(f)
    return buf.raw[: read.value]


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: mpq_extract_probe.py <mpq> <unit_id>")
        return 1
    mpq = Path(sys.argv[1])
    unit_id = sys.argv[2]
    storm, h = open_archive(mpq)
    try:
        # Try a few likely catalog paths
        for p in ["Base.SC2Data/GameData/UnitData.xml",
                  "Mods/voidmulti.sc2mod/Base.SC2Data/GameData/UnitData.xml"]:
            data = read_file(storm, h, p)
            if data:
                break
        else:
            print(f"[probe] 未找到 UnitData.xml in {mpq.name}")
            # List some files to understand layout
            return 2
        text = data.decode("utf-8", "replace")
        found = unit_id in text
        # count occurrences
        cnt = text.count(f'id="{unit_id}"')
        print(f"[probe] {mpq.name} UnitData.xml size={len(text)} "
              f"contains {unit_id!r}={found} (id=\"{unit_id}\" x{cnt})")
        if found:
            idx = text.find(unit_id)
            print("...context...\n" + text[max(0, idx - 120): idx + 200])
        return 0
    finally:
        storm.SFileCloseArchive(h)


if __name__ == "__main__":
    sys.exit(main())
