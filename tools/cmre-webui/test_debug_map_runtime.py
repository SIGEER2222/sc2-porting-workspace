import json
from pathlib import Path

import pytest

from debug_map_runtime import MapRuntime, RuntimeConfig, RuntimeConfigError


def _runtime(tmp_path: Path) -> MapRuntime:
    repo = tmp_path / "repo"
    map_dir = repo / "map.SC2Map"
    map_dir.mkdir(parents=True)
    (map_dir / "DocumentInfo").write_text(
        "<DocInfo><Dependencies><Value>file:Campaigns/Void.SC2Campaign</Value></Dependencies></DocInfo>",
        encoding="utf-8",
    )
    (map_dir / "MapScript.galaxy").write_text("void test() {}", encoding="utf-8")
    sc2_root = tmp_path / "sc2"
    mod = sc2_root / "Mods" / "Example.SC2Mod"
    mod.mkdir(parents=True)
    (mod / "DocumentInfo").write_text(
        "<DocInfo><Dependencies><Value>file:Mods/Base.SC2Mod</Value></Dependencies></DocInfo>",
        encoding="utf-8",
    )
    debug = repo / "debug.SC2Mod"
    (debug / "Base.SC2Data").mkdir(parents=True)
    (debug / "modinfo.xml").write_text("<ModInfo />", encoding="utf-8")
    artifact = tmp_path / "artifacts"
    return MapRuntime(RuntimeConfig(
        repo_root=repo,
        map_path=map_dir,
        sc2_root=sc2_root,
        mod_roots=(sc2_root / "Mods",),
        debug_mod=debug,
        artifact_root=artifact,
        launcher=repo / "launcher.ps1",
        verify_default=None,
    ))


def test_manifest_preserves_map_dependencies(tmp_path):
    runtime = _runtime(tmp_path)
    manifest = runtime.map_manifest()
    assert manifest["readOnly"] is True
    assert manifest["dependencies"][0]["path"] == "file:Campaigns/Void.SC2Campaign"
    assert manifest["fileCount"] == 2


def test_prepare_writes_only_selected_runtime_dependencies(tmp_path):
    runtime = _runtime(tmp_path)
    generated = runtime.config.debug_mod / "Base.SC2Data" / "generated" / "测试地图.SC2Map"
    generated.mkdir(parents=True)
    (generated / "LibVibeInvokeDispatch.galaxy").write_text("normal", encoding="utf-8")
    (generated / "LibVibeInvokeDispatch_tier100.galaxy").write_text("optional", encoding="utf-8")
    (generated / "LibVibeInvokeDispatch_tier1000.galaxy").write_text("optional", encoding="utf-8")
    prepared = runtime.prepare(["Mods/Example.SC2Mod"])
    assert prepared["runtimeDependencies"] == ["file:Mods/Example.SC2Mod"]
    doc = Path(prepared["shimPath"]) / "DocumentInfo"
    assert "file:Mods/Example.SC2Mod" in doc.read_text(encoding="utf-8")
    copied_generated = Path(prepared["shimPath"]) / "Base.SC2Data" / "generated" / "测试地图.SC2Map"
    assert (copied_generated / "LibVibeInvokeDispatch.galaxy").read_text(encoding="utf-8") == "normal"
    assert not (copied_generated / "LibVibeInvokeDispatch_tier100.galaxy").exists()
    assert not (copied_generated / "LibVibeInvokeDispatch_tier1000.galaxy").exists()
    saved = json.loads((Path(prepared["shimPath"]).parent / "session.json").read_text(encoding="utf-8"))
    assert saved["selectedMods"][0]["id"] == "Mods/Example.SC2Mod"


def test_prepare_rejects_unknown_mod(tmp_path):
    runtime = _runtime(tmp_path)
    with pytest.raises(RuntimeConfigError, match="未知或未安装 Mod"):
        runtime.prepare(["Mods/Missing.SC2Mod"])
