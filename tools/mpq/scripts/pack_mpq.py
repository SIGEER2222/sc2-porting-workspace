#!/usr/bin/env python3
"""pack_mpq.py - 将目录打包为 MPQ 文件 (SC2Map/SC2Mod)
用法: python pack_mpq.py <input_dir> <output_mpq>

使用 Blizzard 原始 hash 函数（mpyq 兼容），生成 SC2 可读的 MPQ 文件。
采用标准 sector-based 存储（非 SINGLE_UNIT），兼容 StormLib。
"""

import sys
import struct
from io import BytesIO
from pathlib import Path


def _prepare_encryption_table():
    """Blizzard MPQ encryption table."""
    seed = 0x00100001
    crypt_table = {}
    for i in range(256):
        index = i
        for j in range(5):
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp1 = (seed & 0xFFFF) << 0x10
            seed = (seed * 125 + 3) % 0x2AAAAB
            temp2 = (seed & 0xFFFF)
            crypt_table[index] = (temp1 | temp2)
            index += 0x100
    return crypt_table


ENCRYPTION_TABLE = _prepare_encryption_table()


def mpq_hash(string: str, hash_type: int) -> int:
    """Blizzard MPQ hash function.
    hash_type: 0=TABLE_OFFSET, 1=HASH_A, 2=HASH_B, 3=TABLE (encryption key)
    """
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    for ch in string.upper():
        value = ENCRYPTION_TABLE[(hash_type << 8) + ord(ch)]
        seed1 = (value ^ (seed1 + seed2)) & 0xFFFFFFFF
        seed2 = (ord(ch) + seed1 + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
    return seed1


def mpq_encrypt(data: bytes, key: int) -> bytes:
    """Encrypt/decrypt data using MPQ encryption (XOR symmetric)."""
    seed1 = key
    seed2 = 0xEEEEEEEE
    result = bytearray(len(data))

    for i in range(len(data) // 4):
        seed2 = (seed2 + ENCRYPTION_TABLE[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        value = struct.unpack_from("<I", data, i * 4)[0]
        original = value
        value = (value ^ (seed1 + seed2)) & 0xFFFFFFFF
        result[i*4:i*4+4] = struct.pack("<I", value)

        seed1 = ((~seed1 << 0x15) + 0x11111111) | (seed1 >> 0x0B)
        seed1 &= 0xFFFFFFFF
        seed2 = (original + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF

    return bytes(result)


def hash_filepath(path: str):
    """Return (table_offset, hash_a, hash_b) for a file path."""
    # SC2 MPQ archives address nested files with Windows-style separators.
    # The separator participates in Blizzard's filename hash, so storing and
    # hashing paths with '/' produces an archive that mpyq can read but SC2
    # cannot resolve beyond its root files.
    path = path.replace('/', '\\')
    return (
        mpq_hash(path, 0),
        mpq_hash(path, 1),
        mpq_hash(path, 2),
    )


def build_sector_data(file_data: bytes, sector_size: int) -> bytes:
    """Build sector-based file data with sector offset table.

    Format:
    - Sector offset table: (num_sectors + 1) entries of uint32
    - File data divided into sectors

    num_sectors = size // sector_size + 1
    """
    file_size = len(file_data)
    num_sectors = file_size // sector_size + 1
    sector_table_entries = num_sectors + 1
    sector_table_size = sector_table_entries * 4

    # Build sector offset table
    offsets = []
    current = sector_table_size
    for i in range(num_sectors):
        offsets.append(current)
        remaining = file_size - (i * sector_size)
        current += min(sector_size, max(0, remaining))
    # Last entry: end of data
    offsets.append(sector_table_size + file_size)

    # Pack sector offset table + file data
    result = struct.pack('<%dI' % sector_table_entries, *offsets)
    result += file_data
    return result


def pack_mpq(input_dir: str, output_path: str):
    input_path = Path(input_dir)
    files = []
    for f in input_path.rglob('*'):
        if f.is_file():
            rel = str(f.relative_to(input_path)).replace('/', '\\')
            files.append((str(f), rel))

    if not files:
        print("No files found in input directory")
        sys.exit(1)

    print(f"Packing {len(files)} files...")

    # Hash table: power of 2, >= 16, >= file_count * 2
    hash_count = 16
    while hash_count < len(files) * 2:
        hash_count *= 2
    block_count = len(files) + 1  # +1 for (listfile)

    sector_shift = 3  # 512 << 3 = 4096 bytes per sector
    sector_size = 512 << sector_shift

    # Build block entries
    block_entries = []
    listfile_lines = ["(listfile)"]
    for _, rel in files:
        listfile_lines.append(rel)
    listfile_content = "\r\n".join(listfile_lines).encode('utf-8')

    # MPQ_FILE_EXISTS = 0x80000000 (sector-based, no compression)
    block_entries.append({
        'name': '(listfile)',
        'data': listfile_content,
        'flags': 0x80000000,
    })
    for src_path, rel in files:
        with open(src_path, 'rb') as f:
            data = f.read()
        block_entries.append({
            'name': rel,
            'data': data,
            'flags': 0x80000000,
        })

    # Build sector-based file data for each entry
    for entry in block_entries:
        entry['sector_data'] = build_sector_data(entry['data'], sector_size)
        entry['archived_size'] = len(entry['sector_data'])

    # Hash table (linear probing)
    hash_mask = hash_count - 1
    hash_entries = [None] * hash_count
    for i, entry in enumerate(block_entries):
        table_offset, hash_a, hash_b = hash_filepath(entry['name'])
        pos = table_offset & hash_mask
        while hash_entries[pos] is not None:
            pos = (pos + 1) & hash_mask
        hash_entries[pos] = (hash_a, hash_b, 0xFFFF, 0xFFFF, i)

    # Fill empty slots
    empty = (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFF, 0xFFFF, 0xFFFFFFFF)
    for i in range(hash_count):
        if hash_entries[i] is None:
            hash_entries[i] = empty

    # Calculate offsets (no alignment - contiguous storage)
    header_size = 32
    hash_table_offset = header_size
    hash_table_size = hash_count * 16
    block_table_offset = hash_table_offset + hash_table_size
    block_table_size = block_count * 16
    data_start = block_table_offset + block_table_size

    current_offset = data_start
    for entry in block_entries:
        entry['offset'] = current_offset
        current_offset += entry['archived_size']

    total_size = current_offset

    # Build raw hash table and block table
    hash_table_raw = BytesIO()
    for he in hash_entries:
        hash_table_raw.write(struct.pack('<IIHHI', *he))

    block_table_raw = BytesIO()
    for be in block_entries:
        block_table_raw.write(struct.pack('<IIII',
            be['offset'], be['archived_size'],
            len(be['data']), be['flags']))

    # Encrypt tables
    hash_key = mpq_hash('(hash table)', 3)
    block_key = mpq_hash('(block table)', 3)

    hash_table_encrypted = mpq_encrypt(hash_table_raw.getvalue(), hash_key)
    block_table_encrypted = mpq_encrypt(block_table_raw.getvalue(), block_key)

    # Write
    with open(output_path, 'wb') as f:
        # MPQ header
        f.write(b'MPQ\x1a')
        f.write(struct.pack('<I', header_size))
        f.write(struct.pack('<I', total_size))
        f.write(struct.pack('<H', 0))  # format version 0
        f.write(struct.pack('<H', sector_shift))
        f.write(struct.pack('<I', hash_table_offset))
        f.write(struct.pack('<I', block_table_offset))
        f.write(struct.pack('<I', hash_count))
        f.write(struct.pack('<I', block_count))

        # Hash table
        assert f.tell() == hash_table_offset
        f.write(hash_table_encrypted)

        # Block table
        assert f.tell() == block_table_offset
        f.write(block_table_encrypted)

        # File data
        assert f.tell() == data_start
        for be in block_entries:
            assert f.tell() == be['offset'], f"Offset mismatch: {f.tell()} != {be['offset']}"
            f.write(be['sector_data'])

    print(f"Created: {output_path}")
    print(f"  Size: {total_size} bytes")
    print(f"  Files: {len(files)}")
    print(f"  Hash entries: {hash_count}")
    print(f"  Block entries: {block_count}")


if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: python pack_mpq.py <input_dir> <output_mpq>")
        sys.exit(1)
    pack_mpq(sys.argv[1], sys.argv[2])
