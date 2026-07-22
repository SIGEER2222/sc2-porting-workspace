#!/usr/bin/env python3
"""verify_mpq.py - 验证 MPQ 文件完整性
用法: python verify_mpq.py <mpq_path>

使用 mpyq 读取 MPQ 文件，验证所有文件可读。
"""
import sys

try:
    import mpyq
except ImportError:
    print("ERROR: mpyq not installed. Run: pip install mpyq", file=sys.stderr)
    sys.exit(2)


def verify_mpq(mpq_path: str):
    try:
        archive = mpyq.MPQArchive(mpq_path)
    except Exception as e:
        print(f"FAIL: Cannot open MPQ: {e}")
        sys.exit(1)

    files = archive.files or []
    print(f"MPQ Header:")
    h = archive.header
    print(f"  hash_entries: {h['hash_table_entries']}")
    print(f"  block_entries: {h['block_table_entries']}")
    print(f"  sector_shift: {h['sector_size_shift']}")
    print(f"  format_version: {h['format_version']}")
    print()
    print(f"Files: {len(files)}")

    ok = 0
    failed = []
    for f in files:
        name = f.decode() if isinstance(f, bytes) else f
        try:
            data = archive.read_file(name)
            if data is None:
                failed.append((name, "no data"))
            else:
                ok += 1
        except Exception as e:
            failed.append((name, str(e)))

    print(f"  OK: {ok}")
    if failed:
        print(f"  FAILED: {len(failed)}")
        for name, err in failed:
            print(f"    - {name}: {err}")
        sys.exit(1)
    else:
        print("All files readable. MPQ is valid.")


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Usage: python verify_mpq.py <mpq_path>")
        sys.exit(1)
    verify_mpq(sys.argv[1])
