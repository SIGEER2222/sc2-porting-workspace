#!/usr/bin/env python3
"""Minimal MPQ packer: pack a directory of files into an MPQ archive.

This is a minimal MPQ v0 writer (no compression, no encryption, single-unit files).
Based on the MPQ format and mpyq's hash function.

Usage:
  python mpq_pack.py <src_dir> <output.SC2Map>

The output is a valid MPQ archive that SC2 API's RequestCreateGame can load
via local_map.map_path or local_map.map_data.
"""
from __future__ import annotations

import os
import struct
import sys
from pathlib import Path
from collections import namedtuple

# MPQ constants
MPQ_MAGIC = b'MPQ\x1a'
MPQ_FILE_SINGLE_UNIT = 0x01000000
MPQ_FILE_EXISTS = 0x80000000

# Hash table entry: empty marker
HASH_ENTRY_EMPTY = 0xFFFFFFFF

# Structs
MPQHeader = namedtuple('MPQHeader', [
    'magic', 'header_size', 'archive_size', 'format_version',
    'sector_size_shift', 'hash_table_offset', 'block_table_offset',
    'hash_table_entries', 'block_table_entries'
])
MPQHeader.struct_format = '<4s2I2H4I'  # 32 bytes

MPQHashTableEntry = namedtuple('MPQHashTableEntry', [
    'hash_a', 'hash_b', 'locale', 'platform', 'block_table_index'
])
MPQHashTableEntry.struct_format = '2I2HI'  # 16 bytes

MPQBlockTableEntry = namedtuple('MPQBlockTableEntry', [
    'offset', 'archived_size', 'size', 'flags'
])
MPQBlockTableEntry.struct_format = '4I'  # 16 bytes


def prepare_encryption_table():
    """Prepare the MPQ encryption table (same as mpyq)."""
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


ENCRYPTION_TABLE = prepare_encryption_table()


def mpq_hash(string, hash_type):
    """Hash a string using MPQ's hash function."""
    hash_types = {'TABLE_OFFSET': 0, 'HASH_A': 1, 'HASH_B': 2, 'TABLE': 3}
    seed1 = 0x7FED7FED
    seed2 = 0xEEEEEEEE
    for ch in string.upper():
        if not isinstance(ch, int):
            ch = ord(ch)
        value = ENCRYPTION_TABLE[(hash_types[hash_type] << 8) + ch]
        seed1 = (value ^ (seed1 + seed2)) & 0xFFFFFFFF
        seed2 = ch + seed1 + seed2 + (seed2 << 5) + 3 & 0xFFFFFFFF
    return seed1


def mpq_encrypt(data, key):
    """Encrypt data using MPQ's encryption (mirror of mpyq._decrypt, but uses
    PLAIN value for seed update instead of decrypted value).

    MPQ's hash/block tables must be encrypted with keys derived from
    '(hash table)' and '(block table)' respectively.
    """
    seed1 = key
    seed2 = 0xEEEEEEEE
    result = bytearray()
    for i in range(len(data) // 4):
        seed2 = (seed2 + ENCRYPTION_TABLE[0x400 + (seed1 & 0xFF)]) & 0xFFFFFFFF
        plain_value = struct.unpack_from("<I", data, i * 4)[0]
        enc_value = (plain_value ^ (seed1 + seed2)) & 0xFFFFFFFF
        seed1 = (((~seed1 << 0x15) + 0x11111111) | (seed1 >> 0x0B)) & 0xFFFFFFFF
        seed2 = (plain_value + seed2 + (seed2 << 5) + 3) & 0xFFFFFFFF
        result.extend(struct.pack("<I", enc_value))
    return bytes(result)


def collect_files(src_dir):
    """Collect all files from src_dir, returning list of (relative_path, full_path, content)."""
    files = []
    src = Path(src_dir)
    for root, dirs, filenames in os.walk(src):
        for fname in sorted(filenames):
            full = Path(root) / fname
            rel = full.relative_to(src)
            # MPQ uses backslash paths
            rel_mpq = str(rel).replace('/', '\\')
            files.append((rel_mpq, str(full)))
    return files


def pack_mpq(src_dir, output_path):
    """Pack src_dir into an MPQ archive at output_path."""
    files = collect_files(src_dir)
    print(f"Collected {len(files)} files from {src_dir}", file=sys.stderr)

    # Add (listfile) as a virtual file
    listfile_content = '\r\n'.join(f[0] for f in files).encode('utf-8')
    files_with_listfile = files + [('(listfile)', None, listfile_content)]

    num_files = len(files_with_listfile)

    # Hash table size: next power of 2 >= 2 * num_files, minimum 16
    hash_table_size = 16
    while hash_table_size < num_files * 2:
        hash_table_size *= 2
    print(f"Hash table size: {hash_table_size} (for {num_files} files)", file=sys.stderr)

    # Read all file contents
    file_data = []
    for rel_path, full_path, *extra in files_with_listfile:
        if extra:
            # Virtual file (listfile)
            content = extra[0]
        else:
            with open(full_path, 'rb') as f:
                content = f.read()
        file_data.append((rel_path, content))

    # Build hash table and block table
    hash_table = [(
        HASH_ENTRY_EMPTY, HASH_ENTRY_EMPTY,
        0xFFFF, 0xFFFF, HASH_ENTRY_EMPTY
    )] * hash_table_size

    block_table = []
    # File data will be written after header + hash table + block table
    data_offset = 32 + hash_table_size * 16 + num_files * 16

    current_offset = data_offset
    for i, (rel_path, content) in enumerate(file_data):
        # Compute hashes
        hash_a = mpq_hash(rel_path, 'HASH_A')
        hash_b = mpq_hash(rel_path, 'HASH_B')
        table_offset = mpq_hash(rel_path, 'TABLE_OFFSET') % hash_table_size

        # Find a slot in the hash table (linear probing)
        idx = table_offset
        while hash_table[idx][0] != HASH_ENTRY_EMPTY:
            idx = (idx + 1) % hash_table_size

        hash_table[idx] = (hash_a, hash_b, 0, 0, i)

        # Block table entry
        block_table.append((
            current_offset,
            len(content),  # archived_size (uncompressed)
            len(content),  # size
            MPQ_FILE_EXISTS | MPQ_FILE_SINGLE_UNIT
        ))
        current_offset += len(content)

    # Build the archive
    archive_size = current_offset

    # Write header
    header = struct.pack(
        MPQHeader.struct_format,
        MPQ_MAGIC,
        32,  # header_size
        archive_size,
        0,  # format_version
        3,  # sector_size_shift (sector = 512 << 3 = 4096)
        32,  # hash_table_offset
        32 + hash_table_size * 16,  # block_table_offset
        hash_table_size,
        num_files,
    )

    # Write hash table (must be encrypted)
    hash_table_bytes = b''
    for entry in hash_table:
        hash_table_bytes += struct.pack(MPQHashTableEntry.struct_format, *entry)
    hash_key = mpq_hash('(hash table)', 'TABLE')
    hash_table_bytes = mpq_encrypt(hash_table_bytes, hash_key)

    # Write block table (must be encrypted)
    block_table_bytes = b''
    for entry in block_table:
        block_table_bytes += struct.pack(MPQBlockTableEntry.struct_format, *entry)
    block_key = mpq_hash('(block table)', 'TABLE')
    block_table_bytes = mpq_encrypt(block_table_bytes, block_key)

    # Write file data
    file_data_bytes = b''
    for _, content in file_data:
        file_data_bytes += content

    # Assemble
    archive = header + hash_table_bytes + block_table_bytes + file_data_bytes

    # Write to output
    with open(output_path, 'wb') as f:
        f.write(archive)

    print(f"Wrote {len(archive)} bytes to {output_path}", file=sys.stderr)
    print(f"  Header: 32 bytes", file=sys.stderr)
    print(f"  Hash table: {hash_table_size * 16} bytes ({hash_table_size} entries)", file=sys.stderr)
    print(f"  Block table: {num_files * 16} bytes ({num_files} entries)", file=sys.stderr)
    print(f"  File data: {len(file_data_bytes)} bytes", file=sys.stderr)

    return len(archive)


def main():
    if len(sys.argv) != 3:
        print("Usage: python mpq_pack.py <src_dir> <output.SC2Map>", file=sys.stderr)
        sys.exit(1)
    src_dir = sys.argv[1]
    output = sys.argv[2]
    if not os.path.isdir(src_dir):
        print(f"Source directory not found: {src_dir}", file=sys.stderr)
        sys.exit(1)
    pack_mpq(src_dir, output)


if __name__ == "__main__":
    main()
