"""Read-only PE/string probe for a version-locked SC2 binary.

The probe records candidate locations only. It never turns a string match into
an executable hook and never opens or modifies the running process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path


TARGET_STRINGS = (
    "Galaxy",
    "ScriptError",
    "CTrigger::Load",
    "ASSERT(bytecode",
    "Galaxy Callstack",
    "e_internalGalaxyError",
)


def _read_profile(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _pe_sections(data: bytes) -> tuple[int, list[dict[str, int | str]]]:
    if data[:2] != b"MZ":
        raise ValueError("input is not a PE file")
    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_offset : pe_offset + 4] != b"PE\0\0":
        raise ValueError("invalid PE signature")
    section_count = struct.unpack_from("<H", data, pe_offset + 6)[0]
    optional_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    section_start = pe_offset + 24 + optional_size
    sections: list[dict[str, int | str]] = []
    for index in range(section_count):
        start = section_start + index * 40
        name = data[start : start + 8].rstrip(b"\0").decode("ascii", errors="replace")
        virtual_size, virtual_address, raw_size, raw_pointer = struct.unpack_from("<IIII", data, start + 8)
        sections.append({
            "name": name,
            "virtual_address": virtual_address,
            "virtual_size": virtual_size,
            "raw_size": raw_size,
            "raw_pointer": raw_pointer,
        })
    image_base = struct.unpack_from("<Q", data, pe_offset + 24 + 24)[0]
    return image_base, sections


def _rva_for_offset(offset: int, sections: list[dict[str, int | str]]) -> int | None:
    for section in sections:
        raw_pointer = int(section["raw_pointer"])
        raw_size = int(section["raw_size"])
        if raw_pointer <= offset < raw_pointer + raw_size:
            return int(section["virtual_address"]) + offset - raw_pointer
    return None


def _candidate_xrefs_map(data: bytes, sections: list[dict[str, int | str]]) -> dict[int, list[int]]:
    candidates: dict[int, list[int]] = {}
    for section in sections:
        if str(section["name"]).startswith(".text"):
            start = int(section["raw_pointer"])
            end = start + int(section["raw_size"])
            for offset in range(start, max(start, end - 6)):
                opcode = data[offset : offset + 2]
                if opcode not in (b"H\x8d", b"H\x8b", b"L\x8d", b"L\x8b"):
                    continue
                displacement = struct.unpack_from("<i", data, offset + 2)[0]
                instruction_rva = _rva_for_offset(offset, sections)
                if instruction_rva is None:
                    continue
                for instruction_size in (6, 7):
                    target_rva = instruction_rva + instruction_size + displacement
                    if target_rva not in candidates:
                        candidates[target_rva] = []
                    if instruction_rva not in candidates[target_rva]:
                        candidates[target_rva].append(instruction_rva)
                    if len(candidates[target_rva]) >= 32:
                        break
    return candidates


def probe(executable: Path, profile_path: Path, output: Path | None = None) -> dict:
    profile = _read_profile(profile_path)
    data = executable.read_bytes()
    digest = hashlib.sha256(data).hexdigest().upper()
    image_base, sections = _pe_sections(data)
    xref_map = _candidate_xrefs_map(data, sections)
    matches: list[dict] = []
    for needle in TARGET_STRINGS:
        encoded = needle.encode("ascii")
        start = 0
        while True:
            offset = data.find(encoded, start)
            if offset < 0:
                break
            target_rva = _rva_for_offset(offset, sections)
            matches.append({
                "text": needle,
                "file_offset": offset,
                "rva": target_rva,
                "xrefs": xref_map.get(target_rva, []) if target_rva is not None else [],
            })
            start = offset + len(encoded)
    report = {
        "schema": "gsvm-static-probe/1",
        "executable": str(executable),
        "profile_id": profile.get("profile_id"),
        "expected_sha256": profile.get("sha256"),
        "actual_sha256": digest,
        "hash_match": digest.casefold() == str(profile.get("sha256", "")).casefold(),
        "image_base": image_base,
        "sections": sections,
        "matches": matches,
        "hook_enabled": bool(profile.get("hook_enabled", False)),
        "promoted_hooks": [],
        "note": "String/xref candidates are research evidence only; no address is executable hook configuration.",
    }
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = probe(args.exe, args.profile, args.out)
    print(json.dumps({"hash_match": report["hash_match"], "matches": len(report["matches"]), "out": str(args.out) if args.out else None}))
    return 0 if report["hash_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
