import importlib.util
import inspect
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
    assert module.RUNTIME_BASE_MAP == module.ARENA_BASE_MAP
    assert module.RUNTIME_BASE_MAP.is_dir()
    assert 'include "LibVibeKernel"' in module.MAPSCRIPT
    assert 'include "LibVibeKernel_h"' not in module.MAPSCRIPT
    assert 'include "LibVibeHandles"' not in module.MAPSCRIPT
    assert 'include "TriggerLibs/NativeLib"' in module.MAPSCRIPT
    assert 'include "scripts/cmlib/cmlib"' in module.MAPSCRIPT
    assert 'include "scripts/runtime_lab/runtime_lab"' in module.MAPSCRIPT
    assert 'include "scripts/cmlib/cmlib_selftest"' not in module.MAPSCRIPT
    assert "LibVibeInvokeDispatch.galaxy" in module.ROOT_RUNTIME_FILES
    assert '<Bank Name="GalaxyVibe" Player="1"/>' in module.BANK_LIST
    assert '<Bank Name="GalaxyVibe" Player="2"/>' in module.BANK_LIST
    assert "CMRE" not in module.DOCUMENT_INFO
    assert "Campaigns/Void.SC2Campaign" in module.DOCUMENT_INFO
    assert "CMLib_SelfTest();" not in module.MAPSCRIPT
    assert "libVibeKernel_InitLib();" in module.MAPSCRIPT
    assert "libNtve_InitLib();" in module.MAPSCRIPT
    assert "RuntimeLab_Init();" in module.MAPSCRIPT
    assert "libVibeKernel_gf_RegisterEntryPoints();" not in module.MAPSCRIPT
    assert module.MAPSCRIPT.index("libVibeKernel_InitLib();") < module.MAPSCRIPT.index("libNtve_InitLib();")
    assert module.MAPSCRIPT.index("libNtve_InitLib();") < module.MAPSCRIPT.index("RuntimeLab_Init();")


def test_cmlib_control_stays_isolated_from_runtime_lab():
    builder = PROJECT / "scripts" / "build_runtime_lab.py"
    spec = importlib.util.spec_from_file_location("runtime_lab_builder_control", builder)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert 'include "scripts/cmlib/cmlib"' in module.CMLIB_CONTROL_MAPSCRIPT
    assert 'include "scripts/cmlib/cmlib_selftest"' in module.CMLIB_CONTROL_MAPSCRIPT
    assert "LibVibeKernel" not in module.CMLIB_CONTROL_MAPSCRIPT
    assert "runtime_lab" not in module.CMLIB_CONTROL_MAPSCRIPT
    assert "CMRE" not in module.DOCUMENT_INFO


def test_kernel_control_stays_isolated_from_cmlib_and_runtime_lab():
    builder = PROJECT / "scripts" / "build_runtime_lab.py"
    spec = importlib.util.spec_from_file_location("runtime_lab_builder_kernel", builder)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert 'include "LibVibeKernel"' in module.KERNEL_CONTROL_MAPSCRIPT
    assert 'include "KernelControlDispatch"' in module.KERNEL_CONTROL_MAPSCRIPT
    assert 'include "TriggerLibs/NativeLib"' in module.KERNEL_CONTROL_MAPSCRIPT
    assert 'include "scripts/cmlib' not in module.KERNEL_CONTROL_MAPSCRIPT
    assert 'include "scripts/runtime_lab' not in module.KERNEL_CONTROL_MAPSCRIPT
    assert 'include "Campaigns/Void.SC2Campaign"' not in module.KERNEL_CONTROL_MAPSCRIPT
    assert "libVibeKernel_InitLib();" in module.KERNEL_CONTROL_MAPSCRIPT
    assert "libNtve_InitLib();" in module.KERNEL_CONTROL_MAPSCRIPT
    assert "KernelControl_Init();" in module.KERNEL_CONTROL_MAPSCRIPT
    assert module.KERNEL_CONTROL_MAPSCRIPT.index("libVibeKernel_InitLib();") < module.KERNEL_CONTROL_MAPSCRIPT.index("libNtve_InitLib();")
    assert module.KERNEL_CONTROL_MAPSCRIPT.index("libNtve_InitLib();") < module.KERNEL_CONTROL_MAPSCRIPT.index("KernelControl_Init();")
    assert "KernelControl_DelayedProbe" in module.KERNEL_CONTROL_DISPATCH
    assert '"kernel_control_map_ready"' in module.KERNEL_CONTROL_DISPATCH
    assert 'UnitCreate(1, "Ghost"' in module.KERNEL_CONTROL_DISPATCH
    assert "TriggerEnable(delayedProbe, true);" in module.KERNEL_CONTROL_DISPATCH
    assert module.KERNEL_CONTROL_DISPATCH.index('UnitCreate(1, "Ghost"') < module.KERNEL_CONTROL_DISPATCH.index('TriggerCreate("KernelControl_DelayedProbe")')


def test_kernel_cmlib_control_excludes_runtime_lab_fixture():
    builder = PROJECT / "scripts" / "build_runtime_lab.py"
    spec = importlib.util.spec_from_file_location("runtime_lab_builder_kernel_cmlib", builder)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert 'include "scripts/cmlib/cmlib"' in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert 'include "scripts/cmlib/cmlib_selftest"' in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert 'include "LibVibeKernel"' in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert 'include "KernelControlDispatch"' in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert 'include "TriggerLibs/NativeLib"' in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert 'include "scripts/runtime_lab' not in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert "CMLib_SelfTest();" in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert "libVibeKernel_InitLib();" in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert "libNtve_InitLib();" in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert "KernelControl_Init();" in module.KERNEL_CMLIB_CONTROL_MAPSCRIPT
    assert module.KERNEL_CMLIB_CONTROL_MAPSCRIPT.index("libVibeKernel_InitLib();") < module.KERNEL_CMLIB_CONTROL_MAPSCRIPT.index("libNtve_InitLib();")
    assert module.KERNEL_CMLIB_CONTROL_MAPSCRIPT.index("libNtve_InitLib();") < module.KERNEL_CMLIB_CONTROL_MAPSCRIPT.index("KernelControl_Init();")
    assert module.KERNEL_CMLIB_CONTROL_MAPSCRIPT.index("KernelControl_Init();") < module.KERNEL_CMLIB_CONTROL_MAPSCRIPT.index("CMLib_SelfTest();")


def test_kernel_control_no_triggers_probe_only_removes_triggers_payload():
    builder = PROJECT / "scripts" / "build_runtime_lab.py"
    spec = importlib.util.spec_from_file_location("runtime_lab_builder_kernel_no_triggers", builder)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    probe_root = Path("artifacts/projects/generic-runtime-lab/stage01-foundation/build/KernelControlNoTriggers.SC2Map")
    assert module.KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR.relative_to(module.REPO) == probe_root
    assert module.KERNEL_CONTROL_NO_TRIGGERS_MAP.name == "KernelControlNoTriggers.SC2Map"
    assert "kernel-control-no-triggers" in module.KERNEL_CONTROL_NO_TRIGGERS_REPORT.read_text(encoding="utf-8") if module.KERNEL_CONTROL_NO_TRIGGERS_REPORT.exists() else True
    temp_dir = PROJECT / "tests" / "_tmp_remove_triggers_probe"
    temp_dir.mkdir(exist_ok=True)
    try:
        (temp_dir / "Triggers").write_text("<TriggerData/>", encoding="utf-8")
        (temp_dir / "Triggers.version").write_text("keep", encoding="utf-8")
        module.remove_triggers_payload(temp_dir)
        assert not (temp_dir / "Triggers").exists()
        assert (temp_dir / "Triggers.version").exists()
    finally:
        for path in sorted(temp_dir.glob("*"), reverse=True):
            path.unlink()
        temp_dir.rmdir()


def test_arena_kernel_control_uses_reference_map_as_readonly_base():
    builder = PROJECT / "scripts" / "build_runtime_lab.py"
    spec = importlib.util.spec_from_file_location("runtime_lab_builder_arena_kernel", builder)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.ARENA_BASE_MAP.is_dir()
    assert module.ARENA_BASE_MAP.relative_to(module.REPO).as_posix().startswith(
        "src/projects/test-arena/packages/Maps/"
    )
    assert module.ARENA_KERNEL_CONTROL_MAP.name == "ArenaKernelControl.SC2Map"
    assert "CMRE" not in module.DOCUMENT_INFO
    assert "WarClassicSystem" not in module.DOCUMENT_INFO


def test_runtime_lab_dispatch_exercises_cmlib():
    text = (PROJECT / "runtime" / "galaxy" / "LibVibeInvokeDispatch.galaxy").read_text(encoding="utf-8")
    assert "functionId != 1" in text
    assert 'ArgsGetInt(argsJson, "arg_value")' in text
    assert 'ArgsGetInt(argsJson, "value")' not in text
    assert "CMLib_ClampInt" in text
    assert '"OK"' in text


def test_runtime_lab_tactical_fixture_is_observable():
    text = (PROJECT / "runtime" / "galaxy" / "runtime_lab.galaxy").read_text(encoding="utf-8")
    assert '"Marine"' in text
    assert '"Marauder"' in text
    assert '"Zergling"' in text
    assert '"tactical_arena_ready"' in text
    assert '"arena_managed_units_count"' in text
    assert '"arena_p1_deaths"' in text
    assert "CMLib_AllyMakeEnemies" in text
    assert "CMLib_AllyGiveVision" in text
    assert "CMLib_ResSet" in text
    assert "CMLib_UGHasUnit" in text
    assert "UnitGroupIssueOrder" in text

    init_body = text.split("void RuntimeLab_Init()", 1)[1].split("\n}", 1)[0]
    assert "RuntimeLab_ConfigurePlayers();" not in init_body
    assert "RuntimeLab_CreateControlPanel();" not in init_body


def test_runtime_lab_control_panel_has_deterministic_actions():
    text = (PROJECT / "runtime" / "galaxy" / "runtime_lab.galaxy").read_text(encoding="utf-8")
    init_body = text.split("void RuntimeLab_Init()", 1)[1].split("\n}", 1)[0]
    assert "RuntimeLab_CreateControlPanel" in text
    assert "RuntimeLab_ControlPanelClicked" in text
    assert '"Reset 6v12"' in text
    assert '"P2 Zergling +8"' in text
    assert '"Refresh Status"' in text
    assert '"control_panel_ready"' in text
    assert "TriggerEnable(RuntimeLab_gt_ManagedUnitDied, true);" in text
    assert "TriggerAddEventTimeElapsed(RuntimeLab_gt_StartTacticalArena" not in text
    assert "RuntimeLab_StartTacticalArena(false, true);" in init_body
    assert 'RuntimeLab_WriteStatus("tactical_arena_started", 1);' in init_body
    assert "RuntimeLab_StartKernelEntryPoints" in text
    assert "libVibeKernel_gf_RegisterEntryPoints();" in text
    assert "TriggerExecute(RuntimeLab_gt_KernelEntryPoints, false, false);" in init_body
    assert 'RuntimeLab_WriteStatus("runtime_vm_registration_requested", 1);' in init_body
    assert text.index("CMLib_TrigOnUnitDied(RuntimeLab_gt_ManagedUnitDied") < text.index("TriggerEnable(RuntimeLab_gt_ManagedUnitDied")


def test_breakpoint_trace_variant_has_delayed_before_after_correlation():
    builder = PROJECT / "scripts" / "build_runtime_lab.py"
    spec = importlib.util.spec_from_file_location("runtime_lab_builder_breakpoint", builder)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.BREAKPOINT_TRACE_MAP.name == "BreakpointTrace.SC2Map"
    assert "breakpoint;" in module.BREAKPOINT_TRACE_DISPATCH
    assert '"trace_before"' in module.BREAKPOINT_TRACE_DISPATCH
    assert '"trace_after"' in module.BREAKPOINT_TRACE_DISPATCH
    assert 'BankLoad("GalaxyVibeTrace", 1)' in module.BREAKPOINT_TRACE_DISPATCH
    assert '"startup"' in module.BREAKPOINT_TRACE_DISPATCH
    assert "TriggerAddEventTimeElapsed(traceTrigger, 5.0, c_timeGame);" in module.BREAKPOINT_TRACE_DISPATCH
    assert "BreakpointTrace_Init();" in module.BREAKPOINT_TRACE_MAPSCRIPT
    assert '<Bank Name="GalaxyVibeTrace" Player="1"/>' in module.TRACE_BANK_LIST
    assert module.BREAKPOINT_TRACE_BANK_SEED.name == "galaxy-vibe-trace-bank-seed.xml"
    assert "remove_triggers_payload(BREAKPOINT_TRACE_BUILD_DIR)" in (
        inspect.getsource(module.build_breakpoint_trace)
    )
    assert 'triggers_version = BREAKPOINT_TRACE_BUILD_DIR / "Triggers.version"' in (
        inspect.getsource(module.build_breakpoint_trace)
    )


def test_breakpoint_trace_direct_variant_executes_from_initmap():
    builder = PROJECT / "scripts" / "build_runtime_lab.py"
    spec = importlib.util.spec_from_file_location("runtime_lab_builder_breakpoint_direct", builder)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    assert module.BREAKPOINT_TRACE_DIRECT_MAP.name == "BreakpointTraceDirect.SC2Map"
    assert 'TriggerExecute(TriggerCreate("BreakpointTrace_Probe"), false, true);' in (
        module.BREAKPOINT_TRACE_DIRECT_MAPSCRIPT
    )
    assert "breakpoint;" in module.BREAKPOINT_TRACE_DISPATCH
    assert "remove_triggers_payload(BREAKPOINT_TRACE_DIRECT_BUILD_DIR)" in (
        inspect.getsource(module.build_breakpoint_trace_direct)
    )
