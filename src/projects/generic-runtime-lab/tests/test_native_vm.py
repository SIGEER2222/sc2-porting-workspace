from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
PROBE_PATH = ROOT / "src" / "projects" / "generic-runtime-lab" / "scripts" / "probe_sc2_binary.py"
PROFILE_PATH = ROOT / "src" / "projects" / "generic-runtime-lab" / "runtime" / "native-vm" / "profiles" / "sc2-5.0.16.97563.json"


def load_probe():
    spec = importlib.util.spec_from_file_location("probe_sc2_binary", PROBE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_profile_is_hash_locked_and_hook_disabled():
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
    assert profile["product_version"] == "5.0.16.97563"
    assert len(profile["sha256"]) == 64
    assert profile["hook_enabled"] is False
    assert profile["hooks"] == []
    assert "-debug" in profile["required_args"]


def test_probe_rejects_non_pe(tmp_path):
    module = load_probe()
    fake = tmp_path / "fake.exe"
    fake.write_bytes(b"not a PE")
    profile = tmp_path / "profile.json"
    profile.write_text(json.dumps({"profile_id": "fake", "sha256": "0" * 64}), encoding="utf-8")
    try:
        module.probe(fake, profile)
    except ValueError as error:
        assert "PE" in str(error)
    else:
        raise AssertionError("non-PE input was accepted")


def test_rip_relative_string_reference_uses_modrm_displacement():
    module = load_probe()
    sections = [
        {
            "name": ".text",
            "virtual_address": 0x1000,
            "virtual_size": 16,
            "raw_size": 16,
            "raw_pointer": 0,
        },
        {
            "name": ".rdata",
            "virtual_address": 0x2000,
            "virtual_size": 16,
            "raw_size": 16,
            "raw_pointer": 16,
        },
    ]
    target_rva = 0x2000
    instruction_rva = 0x1000
    displacement = target_rva - (instruction_rva + 7)
    data = bytearray(32)
    data[:7] = b"\x48\x8d\x0d" + displacement.to_bytes(4, "little", signed=True)
    data[16:22] = b"Galaxy"
    matches = [{"text": "Galaxy", "rva": target_rva, "file_offset": 16}]

    xrefs = module._candidate_xrefs_map(bytes(data), sections, matches)

    assert target_rva in xrefs
    assert xrefs[target_rva][0]["instruction_rva"] == instruction_rva
    assert xrefs[target_rva][0]["bytes"] == "48 8d 0d f9 0f 00 00"
