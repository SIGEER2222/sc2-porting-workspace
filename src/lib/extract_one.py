import sys, ctypes, os
from pathlib import Path

DLL = Path(r"E:/Code/MyMod/SC2VibeTools/sc2-porting-workspace/artifacts/stormlib-v9.40/x64/StormLib.dll")
storm = ctypes.WinDLL(str(DLL), use_last_error=True)
storm.SFileOpenArchive.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
storm.SFileOpenArchive.restype = ctypes.c_int
storm.SFileOpenFileEx.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
storm.SFileOpenFileEx.restype = ctypes.c_int
storm.SFileGetFileSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
storm.SFileGetFileSize.restype = ctypes.c_uint32
storm.SFileReadFile.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32), ctypes.c_void_p]
storm.SFileReadFile.restype = ctypes.c_int
storm.SFileCloseFile.argtypes = [ctypes.c_void_p]
storm.SFileCloseFile.restype = None
storm.SFileCloseArchive.argtypes = [ctypes.c_void_p]
storm.SFileCloseArchive.restype = None

mpq = ctypes.c_void_p()
ok = storm.SFileOpenArchive(sys.argv[1], 0, 0, ctypes.byref(mpq))
if not ok:
    print("open failed", ctypes.get_last_error()); sys.exit(1)
name = sys.argv[2]
out = sys.argv[3]
h = ctypes.c_void_p()
ok = storm.SFileOpenFileEx(mpq, name, 0, ctypes.byref(h))
if not ok:
    print("openfile failed", name, ctypes.get_last_error()); storm.SFileCloseArchive(mpq); sys.exit(1)
sz = storm.SFileGetFileSize(h, None)
buf = ctypes.create_string_buffer(sz)
rd = ctypes.c_uint32()
storm.SFileReadFile(h, buf, sz, ctypes.byref(rd), None)
storm.SFileCloseFile(h)
storm.SFileCloseArchive(mpq)
Path(out).write_bytes(buf.raw[:rd.value])
print(f"extracted {name} -> {out} ({rd.value} bytes)")
