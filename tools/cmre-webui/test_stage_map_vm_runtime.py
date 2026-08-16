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


def _source_with_attribution(tmp_path: Path) -> Path:
    source = _source(tmp_path, "地图调试和斗蛐蛐工具（完整功能版).SC2Map")
    (source / "zhCN.SC2Data" / "LocalizedData").mkdir(parents=True)
    (source / "zhCN.SC2Data" / "LocalizedData" / "GameStrings.txt").write_text(
        "\n".join(
            [
                "DocInfo/HowToPlayAdvanced00=作者QQ1196634447",
                "DocInfo/HowToPlayBasic00=这是一张工具~作者QQ1196634447",
                "DocInfo/HowToPlayWinning00=作者QQ1196634447",
                "Param/Expression/265C2CBF=本工具由xxx制作",
                "Param/Expression/keep=保留",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (source / "MapScript.galaxy").write_text(
        "include \"TriggerLibs/NativeLib\"\n"
        "void lllAtg(){libNtve_InitLib();}\n"
        "void lllHhs(bool a,bool b){GameTimeOfDayPause(true);"
        "DialogCreate(600,400,c_anchorCenter,0,0,true);"
        "libNtve_gf_CreateDialogItemLabel(DialogLastCreated(),540,200,c_anchorTop,40,40,"
        "TextExpressionAssemble(\"Param/Expression/265C2CBF\"),ColorWithAlpha(0,0,0,0),false,2.0);"
        "return true;}\n"
        "void InitMap(){lllAtg();}\n",
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
        "LibDouQuquUser.galaxy", "LibDouQuquUserDisabled.galaxy",
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
    assert script.count("CMRE_WEBUI_VIBE_VM_STAGING") == 1
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
    assert result["douQuquUserGalaxy"]["enabled"] is True
    manifest = json.loads((output.parent / "staging-manifest.json").read_text(encoding="utf-8"))
    assert manifest["stage"] == "27-dou-ququ-behavior-plugin"
    assert (output / "Base.SC2Data" / "LibDouQuquRuntime.galaxy").is_file()
    assert (output / "Base.SC2Data" / "LibDouQuquUser.galaxy").is_file()


def test_stage_accepts_an_editable_user_galaxy_source(tmp_path):
    source = _source(tmp_path, "斗蛐蛐-user-source.SC2Map")
    kernel, dispatch = _kernel(tmp_path)
    dou_ququ = _dou_ququ_root(tmp_path)
    user_source = tmp_path / "LibDouQuquUser.galaxy"
    user_source.write_text(
        'string libDouQuquUser_gf_Run(string argsJson) {\n'
        '    return "user-source";\n'
        '}\n',
        encoding="utf-8",
    )
    output = tmp_path / "staged-user-source"
    result = stage_map(
        source,
        output,
        kernel,
        dispatch,
        dou_ququ_root=dou_ququ,
        enable_dou_ququ_runtime=True,
        user_galaxy_source=user_source,
    )
    assert result["douQuquUserGalaxy"]["source"] == str(user_source)
    assert (output / "Base.SC2Data" / "LibDouQuquUser.galaxy").read_text(encoding="utf-8") == user_source.read_text(encoding="utf-8")


def test_stage_removes_source_attribution_popup_only_from_copy(tmp_path):
    source = _source_with_attribution(tmp_path)
    kernel, dispatch = _kernel(tmp_path)
    output = tmp_path / "staged-attribution-clean"
    result = stage_map(source, output, kernel, dispatch)

    source_script = (source / "MapScript.galaxy").read_text(encoding="utf-8")
    staged_script = (output / "MapScript.galaxy").read_text(encoding="utf-8")
    assert "TextExpressionAssemble(\"Param/Expression/265C2CBF\")" in source_script
    assert "TextExpressionAssemble(\"Param/Expression/265C2CBF\")" not in staged_script
    assert "CMRE_WEBUI_ATTRIBUTION_POPUP_REMOVED" in staged_script
    assert "DialogCreate(600,400,c_anchorCenter,0,0,true);" not in staged_script

    source_strings = (source / "zhCN.SC2Data" / "LocalizedData" / "GameStrings.txt").read_text(encoding="utf-8")
    staged_strings = (output / "zhCN.SC2Data" / "LocalizedData" / "GameStrings.txt").read_text(encoding="utf-8")
    assert "作者QQ1196634447" in source_strings
    assert "作者QQ1196634447" not in staged_strings
    assert "Param/Expression/keep=保留" in staged_strings
    assert result["stagedCleanup"]["scope"] == "staged-copy-only"
    assert result["stagedCleanup"]["sourceAttributionPopup"]["applied"] is True


def test_stage_reuses_existing_vibe_bootstrap_without_duplicate_static_includes(tmp_path):
    source = _source(tmp_path, "斗蛐蛐-existing-vibe.SC2Map")
    (source / "MapScript.galaxy").write_text(
        'include "TriggerLibs/NativeLib"\n'
        'include "LibVibeKernel"\n'
        'include "LibVibeHandles"\n'
        'include "LibVibeInvokeDispatch_active"\n'
        'void lllAtg(){libVibeKernel_InitLib();libNtve_InitLib();}\n'
        'void InitMap(){lllAtg();}\n',
        encoding="utf-8",
    )
    kernel, dispatch = _kernel(tmp_path)
    dou_ququ = _dou_ququ_root(tmp_path)
    output = tmp_path / "staged-existing-vibe"
    stage_map(source, output, kernel, dispatch, dou_ququ_root=dou_ququ, enable_dou_ququ_runtime=True)
    script = (output / "MapScript.galaxy").read_text(encoding="utf-8")
    assert script.count('include "LibVibeKernel"') == 1
    assert script.count('include "LibVibeHandles"') == 1
    assert script.count('include "LibVibeInvokeDispatch_active"') == 1
    assert script.count("libVibeKernel_InitLib();") == 1
    assert 'include "LibDouQuquRuntime"' in script


def test_stage_rejects_dou_ququ_opt_in_for_other_map(tmp_path):
    source = _source(tmp_path, "other-map.SC2Map")
    kernel, dispatch = _kernel(tmp_path)
    try:
        stage_map(source, tmp_path / "staged", kernel, dispatch, enable_dou_ququ_features=True, dou_ququ_root=_dou_ququ_root(tmp_path))
    except StagingError as exc:
        assert "restricted to the 斗蛐蛐 map" in str(exc)
    else:
        raise AssertionError("expected map restriction")


def test_explicit_vm_probe_cannot_claim_automatic_behavior_pass():
    probe = Path(__file__).with_name("dou_ququ_runtime_probe.py").read_text(encoding="utf-8")
    assert 'EXPLICIT_VM_SCOPE = "explicit-vm-api"' in probe
    assert 'AUTOMATIC_BEHAVIOR_NOT_EXERCISED = "NOT_EXERCISED"' in probe
    assert '"automaticBehaviorOverall"] = AUTOMATIC_BEHAVIOR_NOT_EXERCISED' in probe
    assert '"explicitVmOverall"] == "PASS"' in probe
    assert 'result["verdict"]["overall"]' not in probe
