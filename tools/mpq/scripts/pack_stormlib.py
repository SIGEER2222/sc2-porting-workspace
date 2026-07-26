#!/usr/bin/env python3
"""Create an SC2 MPQ archive with StormLib's native writer.

Usage: pack_stormlib.py <input_dir> <output_mpq> --stormlib <StormLib.dll>
"""

import argparse
import ctypes
import os
from pathlib import Path


MPQ_CREATE_LISTFILE = 0x00100000
MPQ_FILE_COMPRESS = 0x00000200
MPQ_COMPRESSION_ZLIB = 0x02


def check(ok: bool, operation: str) -> None:
    if not ok:
        raise OSError(f"{operation} failed with Win32 error {ctypes.get_last_error()}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_mpq", type=Path)
    parser.add_argument("--stormlib", required=True, type=Path)
    args = parser.parse_args()

    if not args.input_dir.is_dir():
        raise SystemExit(f"Input directory not found: {args.input_dir}")
    if not args.stormlib.is_file():
        raise SystemExit(f"StormLib DLL not found: {args.stormlib}")

    files = [path for path in args.input_dir.rglob("*") if path.is_file()]
    if not files:
        raise SystemExit("Input directory contains no files")

    args.output_mpq.parent.mkdir(parents=True, exist_ok=True)
    if args.output_mpq.exists():
        args.output_mpq.unlink()

    storm = ctypes.WinDLL(str(args.stormlib), use_last_error=True)
    handle = ctypes.c_void_p()
    storm.SFileCreateArchive.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p)]
    storm.SFileCreateArchive.restype = ctypes.c_bool
    storm.SFileAddFileEx.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    storm.SFileAddFileEx.restype = ctypes.c_bool
    storm.SFileCloseArchive.argtypes = [ctypes.c_void_p]
    storm.SFileCloseArchive.restype = ctypes.c_bool

    check(storm.SFileCreateArchive(str(args.output_mpq), MPQ_CREATE_LISTFILE, len(files) + 1, ctypes.byref(handle)), "SFileCreateArchive")
    try:
        for path in files:
            archived = str(path.relative_to(args.input_dir)).replace("/", "\\").encode("utf-8")
            check(storm.SFileAddFileEx(handle, str(path), archived, MPQ_FILE_COMPRESS, MPQ_COMPRESSION_ZLIB, MPQ_COMPRESSION_ZLIB), f"SFileAddFileEx({archived.decode()})")
    finally:
        check(storm.SFileCloseArchive(handle), "SFileCloseArchive")

    print(f"Created {args.output_mpq} from {len(files)} files")


if __name__ == "__main__":
    main()
