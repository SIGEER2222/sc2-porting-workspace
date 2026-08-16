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
