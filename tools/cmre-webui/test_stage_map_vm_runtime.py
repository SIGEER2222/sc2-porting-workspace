import json
from pathlib import Path

from stage_map_vm_runtime import StagingError, stage_map


def _source(tmp_path: Path, name: str = "source.SC2Map") -> Path:
    source = tmp_path / name
    (source / "Base.SC2Data").mkdir(parents=True)
    (source / "DocumentInfo").write_text("<DocInfo />", encoding="utf-8")
    (source / "MapScript.galaxy").write_text(
        'include "TriggerLibs/NativeLib"\nvoid lllAtg(){libNtve_InitLib();}\nvoid InitMap(){lllAtg();}\n',
        encoding="utf-8",
    )
    return source


def _kernel(tmp_path: Path) -> tuple[Path, Path]:
    kernel = tmp_path / "kernel"
    kernel.mkdir()
    for name in ("LibVibeKernel.galaxy", "LibVibeKernel_h.galaxy", "LibVibeHandles.galaxy"):
        (kernel / name).write_text(name, encoding="utf-8")
    dispatch = tmp_path / "invoke-disabled.galaxy"
    dispatch.write_text("string libVibeInvoke_gf_Dispatch(int i, string s) { return \"\"; }", encoding="utf-8")
    return kernel, dispatch


def _dou_ququ_root(tmp_path: Path) -> Path:
    root = tmp_path / "dou-ququ-overlay"
    root.mkdir()
    for name in (
        "LibDouQuquBehavior.galaxy", "LibDouQuquBehavior_h.galaxy",
        "LibDouQuquRuntime.galaxy", "LibDouQuquRuntimeDisabled.galaxy",
    ):
        (root / name).write_text(name, encoding="utf-8")
    for name in ("AttachMethodData.xml", "EffectData.xml", "AbilData.xml", "UnitData.xml", "ActorData.xml", "ButtonData.xml"):
        (root / name).write_text("<Catalog />", encoding="utf-8")
    return root


def test_stage_map_isolated_and_injects_kernel(tmp_path):
    source = _source(tmp_path)
    kernel, dispatch = _kernel(tmp_path)
    output = tmp_path / "artifacts" / "staged-map"
    result = stage_map(source, output, kernel, dispatch)

    script = (output / "MapScript.galaxy").read_text(encoding="utf-8")
    assert 'include "LibVibeKernel"' in script
    assert "libVibeKernel_InitLib();" in script
    assert "CMRE_WEBUI_VIBE_VM_REGISTER" in script
    assert "libVibeKernel_gf_RegisterEntryPoints();" in script
    assert 'include "LibDouQuquRuntimeDisabled"' in script
    assert script.index("libVibeKernel_gf_RegisterEntryPoints();") > script.index("void InitMap()")
    assert "CMRE_WEBUI_VIBE_VM_STAGING" not in (source / "MapScript.galaxy").read_text(encoding="utf-8")
    assert (output / "BankList.xml").is_file()
    assert result["mapLabel"] == "source.SC2Map"
    manifest = json.loads((output.parent / "staging-manifest.json").read_text(encoding="utf-8"))
    assert manifest["forbiddenMap"] == "亡者之夜"


def test_stage_rejects_reuse_without_replace(tmp_path):
    source = _source(tmp_path)
    kernel, dispatch = _kernel(tmp_path)
    output = tmp_path / "staged"
    stage_map(source, output, kernel, dispatch)
    try:
        stage_map(source, output, kernel, dispatch)
    except StagingError as exc:
        assert "--replace" in str(exc)
    else:
        raise AssertionError("expected staging reuse rejection")


def test_stage_can_opt_in_dou_ququ_files_only_for_target_map(tmp_path):
    source = _source(tmp_path, "斗蛐蛐.SC2Map")
    kernel, dispatch = _kernel(tmp_path)
    dou_ququ = _dou_ququ_root(tmp_path)
    output = tmp_path / "staged-dou-ququ"
    result = stage_map(source, output, kernel, dispatch, enable_dou_ququ_features=True, dou_ququ_root=dou_ququ)
    script = (output / "MapScript.galaxy").read_text(encoding="utf-8")
    assert 'include "LibDouQuquBehavior"' in script
    assert "libDouQuquBehavior_InitLib();" in script
    assert result["douQuquBehavior"]["enabled"] is True
    assert (output / "Base.SC2Data" / "LibDouQuquBehavior.galaxy").is_file()
    assert (output / "Base.SC2Data" / "LibDouQuquRuntimeDisabled.galaxy").is_file()
    assert (output / "Base.SC2Data" / "GameData" / "EffectData.xml").is_file()


def test_stage_can_mount_live_dou_ququ_runtime_without_static_behavior(tmp_path):
    source = _source(tmp_path, "斗蛐蛐-runtime.SC2Map")
    kernel, dispatch = _kernel(tmp_path)
    dou_ququ = _dou_ququ_root(tmp_path)
    output = tmp_path / "staged-runtime"
    result = stage_map(source, output, kernel, dispatch, dou_ququ_root=dou_ququ, enable_dou_ququ_runtime=True)
    script = (output / "MapScript.galaxy").read_text(encoding="utf-8")
    assert 'include "LibDouQuquRuntime"' in script
    assert 'include "LibDouQuquBehavior"' not in script
    assert result["douQuquRuntime"]["enabled"] is True
    manifest = json.loads((output.parent / "staging-manifest.json").read_text(encoding="utf-8"))
    assert manifest["stage"] == "27-dou-ququ-behavior-plugin"
    assert (output / "Base.SC2Data" / "LibDouQuquRuntime.galaxy").is_file()


def test_stage_rejects_dou_ququ_opt_in_for_other_map(tmp_path):
    source = _source(tmp_path, "other-map.SC2Map")
    kernel, dispatch = _kernel(tmp_path)
    try:
        stage_map(source, tmp_path / "staged", kernel, dispatch, enable_dou_ququ_features=True, dou_ququ_root=_dou_ququ_root(tmp_path))
    except StagingError as exc:
        assert "restricted to the 斗蛐蛐 map" in str(exc)
    else:
        raise AssertionError("expected map restriction")
