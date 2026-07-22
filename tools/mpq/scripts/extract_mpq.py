#!/usr/bin/env python3
"""extract_mpq.py - 使用 mpyq 解包 MPQ 文件 (SC2Map/SC2Mod)
用法: python extract_mpq.py <mpq_path> <output_dir> [filter]

作为 MPQEditor 的备选方案，当路径含特殊字符或 MPQEditor 失败时使用。
"""
import os
import sys
import shutil

try:
    import mpyq
except ImportError:
    print("ERROR: mpyq not installed. Run: pip install mpyq", file=sys.stderr)
    sys.exit(2)


def extract_mpq(mpq_path: str, output_dir: str, file_filter: str = "*"):
    if not os.path.exists(mpq_path):
        print(f"ERROR: MPQ file not found: {mpq_path}", file=sys.stderr)
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    print(f"Extracting: {mpq_path} -> {output_dir} (filter: {file_filter})")

    archive = mpyq.MPQArchive(mpq_path)
    files = archive.files or []

    # Convert filter to simple pattern matching
    import fnmatch
    filter_pattern = file_filter if file_filter != "*" else "*"

    extracted = 0
    for f in files:
        name = f.decode() if isinstance(f, bytes) else f
        # Apply filter (only on filename, not full path)
        basename = name.split('/')[-1]
        if not fnmatch.fnmatch(basename, filter_pattern) and filter_pattern != "*":
            continue

        data = archive.read_file(name)
        if data is None:
            print(f"  SKIP (no data): {name}")
            continue

        # Create subdirectories
        out_path = os.path.join(output_dir, name.replace('\\', '/'))
        os.makedirs(os.path.dirname(out_path), exist_ok=True)

        with open(out_path, 'wb') as out:
            out.write(data)
        extracted += 1

    print(f"Extraction complete. {extracted} files extracted to {output_dir}")


if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: python extract_mpq.py <mpq_path> <output_dir> [filter]")
        sys.exit(1)
    filter_arg = sys.argv[3] if len(sys.argv) > 3 else "*"
    extract_mpq(sys.argv[1], sys.argv[2], filter_arg)
