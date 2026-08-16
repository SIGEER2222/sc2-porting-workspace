"""Read-only PE/string probe for a version-locked SC2 binary.

The probe records candidate locations only. It never turns a string match into
an executable hook and never opens or modifies the running process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
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


def _offset_for_rva(rva: int, sections: list[dict[str, int | str]]) -> int | None:
    for section in sections:
        virtual_address = int(section["virtual_address"])
        span = int(section["raw_size"])
        if virtual_address <= rva < virtual_address + span:
            return int(section["raw_pointer"]) + rva - virtual_address
    return None


def _section_for_offset(offset: int, sections: list[dict[str, int | str]]) -> str | None:
    for section in sections:
        raw_pointer = int(section["raw_pointer"])
        raw_size = int(section["raw_size"])
        if raw_pointer <= offset < raw_pointer + raw_size:
            return str(section["name"])
    return None


def _section_for_rva(rva: int, sections: list[dict[str, int | str]]) -> str | None:
    offset = _offset_for_rva(rva, sections)
    return _section_for_offset(offset, sections) if offset is not None else None


def _rip_relative_instructions(
    data: bytes, sections: list[dict[str, int | str]]
) -> list[dict[str, int | str]]:
    """Find common x64 RIP-relative ModRM forms without treating them as hooks.

    The previous scanner read the displacement at the ModRM byte. For an
    instruction such as ``48 8D 0D xx xx xx xx`` the displacement starts three
    bytes after the instruction, so every xref was silently discarded. This
    scanner intentionally reports byte-level candidates only; it is not a
    disassembler and does not promote any address to executable configuration.
    """
    candidates: list[dict[str, int | str]] = []
    one_byte_modrm = {
        0x00, 0x01, 0x02, 0x03, 0x08, 0x09, 0x0A, 0x0B, 0x10, 0x11,
        0x12, 0x13, 0x18, 0x19, 0x1A, 0x1B, 0x20, 0x21, 0x22, 0x23,
        0x28, 0x29, 0x2A, 0x2B, 0x30, 0x31, 0x32, 0x33, 0x38, 0x39,
        0x3A, 0x3B, 0x62, 0x63, 0x69, 0x6B, 0x80, 0x81, 0x82, 0x83,
        0x84, 0x85, 0x86, 0x87, 0x88, 0x89, 0x8A, 0x8B, 0x8D, 0x8F,
        0xC0, 0xC1, 0xC6, 0xC7, 0xD0, 0xD1, 0xD2, 0xD3, 0xF6, 0xF7,
        0xFE, 0xFF,
    }
    two_byte_modrm = {
        0x10, 0x11, 0x12, 0x13, 0x16, 0x17, 0x28, 0x29, 0x2A, 0x2B,
        0x2E, 0x2F, 0x40, 0x41, 0x42, 0x43, 0x44, 0x45, 0x46, 0x47,
        0x48, 0x49, 0x4A, 0x4B, 0x4C, 0x4D, 0x4E, 0x4F, 0x6E, 0x6F,
        0x7E, 0x7F, 0xAF, 0xB6, 0xB7, 0xBE, 0xBF,
    }
    text_sections = [
        section for section in sections if str(section["name"]).startswith(".text")
    ]
    for section in text_sections:
        start = int(section["raw_pointer"])
        end = start + int(section["raw_size"])
        offset = start
        while offset + 7 <= end:
            instruction_start = offset
            prefix_count = 0
            while offset < end and (
                0x40 <= data[offset] <= 0x4F
                or data[offset] in (0x66, 0x67, 0xF2, 0xF3)
            ):
                offset += 1
                prefix_count += 1
                if prefix_count > 4:
                    break
            if prefix_count > 4 or offset >= end:
                offset = instruction_start + 1
                continue
            opcode = data[offset]
            opcode_size = 1
            modrm_offset = offset + 1
            if opcode == 0x0F and offset + 1 < end:
                opcode = data[offset + 1]
                opcode_size = 2
                modrm_offset = offset + 2
            if opcode not in (one_byte_modrm if opcode_size == 1 else two_byte_modrm):
                offset = instruction_start + 1
                continue
            if modrm_offset + 5 > end:
                break
            modrm = data[modrm_offset]
            if (modrm & 0xC7) != 0x05:
                offset = instruction_start + 1
                continue
            displacement = struct.unpack_from("<i", data, modrm_offset + 1)[0]
            instruction_rva = _rva_for_offset(instruction_start, sections)
            if instruction_rva is None:
                offset = instruction_start + 1
                continue
            instruction_size = (modrm_offset - instruction_start) + 5
            target_rva = instruction_rva + instruction_size + displacement
            target_offset = _offset_for_rva(target_rva, sections)
            if target_offset is not None:
                candidates.append({
                    "instruction_rva": instruction_rva,
                    "instruction_file_offset": instruction_start,
                    "target_rva": target_rva,
                    "target_file_offset": target_offset,
                    "instruction_size": instruction_size,
                    "bytes": data[instruction_start : instruction_start + instruction_size].hex(" "),
                    "kind": "rip-relative",
                })
            offset = instruction_start + 1
    return candidates


def _byte_context(data: bytes, offset: int, radius: int = 16) -> dict[str, int | str]:
    start = max(0, offset - radius)
    end = min(len(data), offset + radius)
    return {
        "start_file_offset": start,
        "end_file_offset": end,
        "bytes": data[start:end].hex(" "),
    }


def _candidate_xrefs_map(
    data: bytes,
    sections: list[dict[str, int | str]],
    string_matches: list[dict[str, int | str]],
    rip_candidates: list[dict[str, int | str]] | None = None,
) -> dict[int, list[dict[str, int | str]]]:
    candidates: dict[int, list[dict[str, int | str]]] = {}
    string_targets = {
        int(match["rva"]): match for match in string_matches if match.get("rva") is not None
    }
    for candidate in rip_candidates if rip_candidates is not None else _rip_relative_instructions(data, sections):
        target_rva = int(candidate["target_rva"])
        match = string_targets.get(target_rva)
        if match is None:
            continue
        target_offset = int(candidate["target_file_offset"])
        candidate = {
            **candidate,
            "target_section": _section_for_offset(target_offset, sections),
            "instruction_section": _section_for_rva(int(candidate["instruction_rva"]), sections),
            "instruction_context": _byte_context(data, int(candidate["instruction_file_offset"])),
            "disassembly": None,
        }
        candidates.setdefault(target_rva, []).append(candidate)
    for values in candidates.values():
        values.sort(key=lambda value: int(value["instruction_rva"]))
        del values[32:]
    return candidates


def probe(executable: Path, profile_path: Path, output: Path | None = None) -> dict:
    profile = _read_profile(profile_path)
    data = executable.read_bytes()
    digest = hashlib.sha256(data).hexdigest().upper()
    image_base, sections = _pe_sections(data)
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
                "section": _section_for_offset(offset, sections),
                "context": _byte_context(data, offset),
            })
            start = offset + len(encoded)
    rip_candidates = _rip_relative_instructions(data, sections)
    xref_map = _candidate_xrefs_map(data, sections, matches, rip_candidates)
    for match in matches:
        target_rva = match.get("rva")
        match["xrefs"] = xref_map.get(target_rva, []) if target_rva is not None else []
    candidate_samples = []
    for candidate in rip_candidates[:128]:
        instruction_offset = int(candidate["instruction_file_offset"])
        target_offset = int(candidate["target_file_offset"])
        candidate_samples.append({
            **candidate,
            "target_section": _section_for_offset(target_offset, sections),
            "instruction_section": _section_for_rva(int(candidate["instruction_rva"]), sections),
            "instruction_context": _byte_context(data, instruction_offset),
            "disassembly": None,
        })
    report = {
        "schema": "gsvm-static-probe/2",
        "executable": str(executable),
        "profile_id": profile.get("profile_id"),
        "expected_sha256": profile.get("sha256"),
        "actual_sha256": digest,
        "hash_match": digest.casefold() == str(profile.get("sha256", "")).casefold(),
        "image_base": image_base,
        "sections": sections,
        "scan": {
            "rip_relative_instruction_count": len(rip_candidates),
            "direct_string_xref_count": sum(len(match["xrefs"]) for match in matches),
            "candidate_sample_count": len(candidate_samples),
            "note": (
                "A direct xref means a decoded RIP-relative instruction targets the exact "
                "string start. Zero direct xrefs do not prove the strings are unused; the "
                "current build may address diagnostic strings through tables or offsets."
            ),
        },
        "disassembly": {
            "tool": next((tool for tool in ("llvm-objdump", "objdump") if shutil.which(tool)), None),
            "available": any(shutil.which(tool) for tool in ("llvm-objdump", "objdump")),
            "note": "No local disassembler was available; xrefs include instruction bytes and byte windows.",
        },
        "candidate_samples": candidate_samples,
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
