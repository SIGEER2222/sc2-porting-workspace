import importlib.util
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def test_runtime_lab_has_only_generic_inputs():
    text = (PROJECT / "project.json").read_text(encoding="utf-8")
    assert "cmre-porting" not in text
    assert "RuntimeLab.SC2Map" in text


def test_runtime_lab_build_wires_the_three_suites():
    builder = PROJECT / "scripts" / "build_runtime_lab.py"
    spec = importlib.util.spec_from_file_location("runtime_lab_builder", builder)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert 'include "LibVibeKernel"' in module.MAPSCRIPT
    assert 'include "scripts/cmlib/cmlib"' in module.MAPSCRIPT
    assert 'include "scripts/runtime_lab/runtime_lab"' in module.MAPSCRIPT
    assert "LibVibeInvokeDispatch.galaxy" in module.ROOT_RUNTIME_FILES
    assert '<Bank Name="GalaxyVibe" Player="1"/>' in module.BANK_LIST
    assert '<Bank Name="GalaxyVibe" Player="2"/>' in module.BANK_LIST
    assert "libVibeKernel_InitLib();" in module.MAPSCRIPT
    assert "CMLib_SelfTest();" in module.MAPSCRIPT
    assert "libVibeKernel_gf_RegisterEntryPoints();" in module.MAPSCRIPT


def test_runtime_lab_dispatch_exercises_cmlib():
    text = (PROJECT / "runtime" / "galaxy" / "LibVibeInvokeDispatch.galaxy").read_text(encoding="utf-8")
    assert "functionId != 1" in text
    assert "CMLib_ClampInt" in text
    assert '"OK"' in text


def test_runtime_lab_tactical_fixture_is_observable():
    text = (PROJECT / "runtime" / "galaxy" / "runtime_lab.galaxy").read_text(encoding="utf-8")
    assert '"Marine"' in text
    assert '"Zergling"' in text
    assert '"tactical_arena_ready"' in text
