#!/usr/bin/env python3
"""Build the isolated Runtime Lab map from current VM and CMLib sources."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
REPO = PROJECT.parents[2]
BASE_MAP = REPO / "src" / "lib" / "_testmap_src"
BUILD_DIR = REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage01-foundation" / "build" / "RuntimeLab.SC2Map"
OUTPUT_DIR = REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage01-foundation" / "maps"
OUTPUT_MAP = OUTPUT_DIR / "RuntimeLab.SC2Map"
REPORT = OUTPUT_DIR / "build-report.json"
CMLIB_CONTROL_BUILD_DIR = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage01-foundation"
    / "build" / "CMLibControl.SC2Map"
)
CMLIB_CONTROL_MAP = OUTPUT_DIR / "CMLibControl.SC2Map"
CMLIB_CONTROL_REPORT = OUTPUT_DIR / "cmlib-control-build-report.json"
KERNEL_CONTROL_BUILD_DIR = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage01-foundation"
    / "build" / "KernelControl.SC2Map"
)
KERNEL_CONTROL_MAP = OUTPUT_DIR / "KernelControl.SC2Map"
KERNEL_CONTROL_REPORT = OUTPUT_DIR / "kernel-control-build-report.json"
KERNEL_CMLIB_CONTROL_BUILD_DIR = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage01-foundation"
    / "build" / "KernelCMLibControl.SC2Map"
)
KERNEL_CMLIB_CONTROL_MAP = OUTPUT_DIR / "KernelCMLibControl.SC2Map"
KERNEL_CMLIB_CONTROL_REPORT = OUTPUT_DIR / "kernel-cmlib-control-build-report.json"
KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage01-foundation"
    / "build" / "KernelControlNoTriggers.SC2Map"
)
KERNEL_CONTROL_NO_TRIGGERS_MAP = OUTPUT_DIR / "KernelControlNoTriggers.SC2Map"
KERNEL_CONTROL_NO_TRIGGERS_REPORT = OUTPUT_DIR / "kernel-control-no-triggers-build-report.json"
ARENA_BASE_MAP = (
    REPO / "src" / "projects" / "test-arena" / "packages" / "Maps"
    / "地图调试和斗蛐蛐工具（完整功能版).SC2Map"
)
RUNTIME_BASE_MAP = ARENA_BASE_MAP
ARENA_KERNEL_CONTROL_BUILD_DIR = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage01-foundation"
    / "build" / "ArenaKernelControl.SC2Map"
)
ARENA_KERNEL_CONTROL_MAP = OUTPUT_DIR / "ArenaKernelControl.SC2Map"
ARENA_KERNEL_CONTROL_REPORT = OUTPUT_DIR / "arena-kernel-control-build-report.json"
BREAKPOINT_TRACE_BUILD_DIR = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "build" / "BreakpointTrace.SC2Map"
)
BREAKPOINT_TRACE_MAP = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "maps" / "BreakpointTrace.SC2Map"
)
BREAKPOINT_TRACE_REPORT = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "maps" / "breakpoint-trace-build-report.json"
)
BREAKPOINT_TRACE_DIRECT_BUILD_DIR = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "build" / "BreakpointTraceDirect.SC2Map"
)
BREAKPOINT_TRACE_DIRECT_MAP = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "maps" / "BreakpointTraceDirect.SC2Map"
)
BREAKPOINT_TRACE_DIRECT_REPORT = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "maps" / "breakpoint-trace-direct-build-report.json"
)
BREAKPOINT_TRACE_DIRECT_CONTROL_BUILD_DIR = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "build" / "BreakpointTraceDirectControl.SC2Map"
)
BREAKPOINT_TRACE_DIRECT_CONTROL_MAP = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "maps" / "BreakpointTraceDirectControl.SC2Map"
)
BREAKPOINT_TRACE_DIRECT_CONTROL_REPORT = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "maps" / "breakpoint-trace-direct-control-build-report.json"
)
BREAKPOINT_TRACE_BANK_SEED = (
    REPO / "artifacts" / "projects" / "generic-runtime-lab" / "stage03-current-vm-signature-trace"
    / "runtime" / "galaxy-vibe-trace-bank-seed.xml"
)
CMLIB = REPO / "src" / "lib" / "scripts" / "cmlib"
SELFTEST = REPO / "src" / "lib" / "selftest" / "cmlib_selftest.galaxy"
KERNEL = REPO / "tools" / "galaxy-vibe" / "kernel"
PACKER = REPO / "tools" / "mpq" / "scripts" / "pack_stormlib.py"
STORMLIB = REPO / "artifacts" / "stormlib-v9.40" / "x64" / "StormLib.dll"
ROOT_RUNTIME_FILES = {"LibVibeInvokeDispatch.galaxy"}

BANK_LIST = """<?xml version="1.0" encoding="utf-8"?>
<BankList>
    <Bank Name="GalaxyVibe" Player="1"/>
    <Bank Name="GalaxyVibe" Player="2"/>
</BankList>
"""

TRACE_BANK_LIST = """<?xml version="1.0" encoding="utf-8"?>
<BankList>
    <Bank Name="GalaxyVibeTrace" Player="1"/>
    <Bank Name="GalaxyVibeTrace" Player="2"/>
</BankList>
"""

DOCUMENT_INFO = """<?xml version="1.0" encoding="utf-8"?>
<DocInfo>
    <ModType>
        <Value>Interface</Value>
    </ModType>
    <Dependencies>
        <Value>bnet:Void (Campaign)/0.0/999,file:Campaigns/Void.SC2Campaign</Value>
    </Dependencies>
</DocInfo>
"""

MAPSCRIPT = """// Generated Runtime Lab entry point. Build from current VM and CMLib sources.
include "TriggerLibs/NativeLib"
include "scripts/cmlib/cmlib"
include "LibVibeKernel"
include "LibVibeInvokeDispatch"
include "scripts/runtime_lab/runtime_lab"

void InitMap() {
    libVibeKernel_InitLib();
    libNtve_InitLib();
    RuntimeLab_Init();
}
"""

CMLIB_CONTROL_MAPSCRIPT = """// Generated CMLib control. It excludes VM and tactical fixtures.
include "TriggerLibs/natives"
include "scripts/cmlib/cmlib"
include "scripts/cmlib/cmlib_selftest"

void InitMap() {
    CMLib_SelfTest();
}
"""

KERNEL_CONTROL_MAPSCRIPT = """// Generated Kernel control. It excludes CMLib and RuntimeLab.
include "TriggerLibs/NativeLib"
include "LibVibeKernel"
include "KernelControlDispatch"

void InitMap() {
    libVibeKernel_InitLib();
    libNtve_InitLib();
    KernelControl_Init();
}
"""

KERNEL_CONTROL_DISPATCH = """// Map-owned observability for the isolated Kernel controls.
// This deliberately uses the same Bank channel as the Kernel after game time starts.
bool KernelControl_DelayedProbe(bool testConds, bool runActions) {
    bank controlBank;

    if (testConds) { return true; }
    if (!runActions) { return true; }

    controlBank = BankLoad("GalaxyVibe", 1);
    if (controlBank != null) {
        BankWait(controlBank);
        BankValueSetFromInt(controlBank, "index", "kernel_control_map_ready", 1);
        BankSave(controlBank);
    }
    UnitCreate(1, "Ghost", c_unitCreateIgnorePlacement, 1, Point(10.0, 10.0), 270.0);
    return true;
}

void KernelControl_Init() {
    trigger delayedProbe;

    UnitCreate(1, "Ghost", c_unitCreateIgnorePlacement, 1, Point(10.0, 10.0), 270.0);
    delayedProbe = TriggerCreate("KernelControl_DelayedProbe");
    TriggerAddEventTimeElapsed(delayedProbe, 1.0, c_timeGame);
    TriggerEnable(delayedProbe, true);
}

// Minimal dispatch stub for the isolated Kernel control map.
string libVibeInvoke_gf_Dispatch(int functionId, string argsJson) {
    return "";
}
"""

KERNEL_CMLIB_CONTROL_MAPSCRIPT = """// Generated Kernel+CMLib control. It excludes RuntimeLab fixtures.
include "TriggerLibs/NativeLib"
include "scripts/cmlib/cmlib"
include "LibVibeKernel"
include "KernelControlDispatch"
include "scripts/cmlib/cmlib_selftest"

void InitMap() {
    libVibeKernel_InitLib();
    libNtve_InitLib();
    KernelControl_Init();
    CMLib_SelfTest();
}
"""

BREAKPOINT_TRACE_MAPSCRIPT = """// Generated breakpoint trace map. The trigger is delayed so an agent can arm first.
include "TriggerLibs/NativeLib"
include "BreakpointTraceDispatch"

void InitMap() {
    BreakpointTrace_Init();
}
"""

BREAKPOINT_TRACE_DIRECT_MAPSCRIPT = """// Generated direct breakpoint trace map. InitMap executes the probe immediately.
include "TriggerLibs/NativeLib"
include "BreakpointTraceDispatch"

void InitMap() {
    TriggerExecute(TriggerCreate("BreakpointTrace_Probe"), false, true);
}
"""

BREAKPOINT_TRACE_DIRECT_CONTROL_MAPSCRIPT = """// Generated direct control map. InitMap executes the probe without breakpoint.
include "TriggerLibs/NativeLib"
include "BreakpointTraceDispatch"

void InitMap() {
    TriggerExecute(TriggerCreate("BreakpointTrace_Probe"), false, true);
}
"""

BREAKPOINT_TRACE_DISPATCH = """// Map-owned correlation fixture for the current-version VM trace.
bool BreakpointTrace_Probe(bool testConds, bool runActions) {
    bank traceBank;

    if (testConds) { return true; }
    if (!runActions) { return true; }

    traceBank = BankLoad("GalaxyVibeTrace", 1);
    if (traceBank != null) {
        BankWait(traceBank);
        BankValueSetFromInt(traceBank, "trace", "startup", 1);
        BankSave(traceBank);
        BankValueSetFromInt(traceBank, "trace", "trace_before", 1);
        BankSave(traceBank);
        breakpoint;
        BankWait(traceBank);
        BankValueSetFromInt(traceBank, "trace", "trace_after", 1);
        BankSave(traceBank);
    }
    return true;
}

void BreakpointTrace_Init() {
    trigger traceTrigger;

    traceTrigger = TriggerCreate("BreakpointTrace_Probe");
    TriggerAddEventTimeElapsed(traceTrigger, 5.0, c_timeGame);
    TriggerEnable(traceTrigger, true);
}
"""

BREAKPOINT_TRACE_DIRECT_CONTROL_DISPATCH = BREAKPOINT_TRACE_DISPATCH.replace(
    "        breakpoint;\n", "")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def copy_required(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def copy_cmlib_sources(build_dir: Path) -> Path:
    cmlib_out = build_dir / "Base.SC2Data" / "scripts" / "cmlib"
    for source in sorted(CMLIB.glob("*.galaxy")):
        copy_required(source, cmlib_out / source.name)
    copy_required(SELFTEST, cmlib_out / SELFTEST.name)
    return cmlib_out


def pack_map(build_dir: Path, output_map: Path) -> str:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if output_map.exists():
        output_map.unlink()
    command = [sys.executable, str(PACKER), str(build_dir), str(output_map), "--stormlib", str(STORMLIB)]
    completed = subprocess.run(command, text=True, capture_output=True, encoding="utf-8", errors="replace")
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    return completed.stdout.strip()


def remove_triggers_payload(build_dir: Path) -> None:
    triggers_path = build_dir / "Triggers"
    if triggers_path.exists():
        triggers_path.unlink()


def build_cmlib_control() -> int:
    if CMLIB_CONTROL_BUILD_DIR.exists():
        shutil.rmtree(CMLIB_CONTROL_BUILD_DIR)
    shutil.copytree(BASE_MAP, CMLIB_CONTROL_BUILD_DIR)
    cmlib_out = copy_cmlib_sources(CMLIB_CONTROL_BUILD_DIR)
    (CMLIB_CONTROL_BUILD_DIR / "MapScript.galaxy").write_text(
        CMLIB_CONTROL_MAPSCRIPT, encoding="utf-8", newline="\n")
    (CMLIB_CONTROL_BUILD_DIR / "DocumentInfo").write_text(
        DOCUMENT_INFO, encoding="utf-8", newline="\n")
    packer_output = pack_map(CMLIB_CONTROL_BUILD_DIR, CMLIB_CONTROL_MAP)

    report = {
        "schemaVersion": 1,
        "classification": "static",
        "kind": "cmlib-control",
        "map": CMLIB_CONTROL_MAP.relative_to(REPO).as_posix(),
        "sha256": sha256(CMLIB_CONTROL_MAP),
        "cmlibFiles": len(list(cmlib_out.glob("*.galaxy"))) - 1,
        "kernelFiles": [],
        "runtimeLabFiles": [],
        "dependencies": ["Campaigns/Void.SC2Campaign"],
        "packerOutput": packer_output,
    }
    CMLIB_CONTROL_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def build_kernel_control() -> int:
    if KERNEL_CONTROL_BUILD_DIR.exists():
        shutil.rmtree(KERNEL_CONTROL_BUILD_DIR)
    shutil.copytree(BASE_MAP, KERNEL_CONTROL_BUILD_DIR)
    for filename in ("LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"):
        copy_required(KERNEL / filename, KERNEL_CONTROL_BUILD_DIR / "Base.SC2Data" / filename)
    (KERNEL_CONTROL_BUILD_DIR / "Base.SC2Data" / "KernelControlDispatch.galaxy").write_text(
        KERNEL_CONTROL_DISPATCH, encoding="utf-8", newline="\n")
    (KERNEL_CONTROL_BUILD_DIR / "MapScript.galaxy").write_text(
        KERNEL_CONTROL_MAPSCRIPT, encoding="utf-8", newline="\n")
    (KERNEL_CONTROL_BUILD_DIR / "BankList.xml").write_text(
        BANK_LIST, encoding="utf-8", newline="\n")
    (KERNEL_CONTROL_BUILD_DIR / "DocumentInfo").write_text(
        DOCUMENT_INFO, encoding="utf-8", newline="\n")
    packer_output = pack_map(KERNEL_CONTROL_BUILD_DIR, KERNEL_CONTROL_MAP)

    report = {
        "schemaVersion": 1,
        "classification": "static",
        "kind": "kernel-control",
        "map": KERNEL_CONTROL_MAP.relative_to(REPO).as_posix(),
        "sha256": sha256(KERNEL_CONTROL_MAP),
        "cmlibFiles": 0,
        "kernelFiles": ["LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"],
        "runtimeLabFiles": ["KernelControlDispatch.galaxy"],
        "dependencies": ["Campaigns/Void.SC2Campaign"],
        "packerOutput": packer_output,
    }
    KERNEL_CONTROL_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def build_kernel_cmlib_control() -> int:
    if KERNEL_CMLIB_CONTROL_BUILD_DIR.exists():
        shutil.rmtree(KERNEL_CMLIB_CONTROL_BUILD_DIR)
    shutil.copytree(BASE_MAP, KERNEL_CMLIB_CONTROL_BUILD_DIR)
    cmlib_out = copy_cmlib_sources(KERNEL_CMLIB_CONTROL_BUILD_DIR)
    for filename in ("LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"):
        copy_required(KERNEL / filename, KERNEL_CMLIB_CONTROL_BUILD_DIR / "Base.SC2Data" / filename)
    (KERNEL_CMLIB_CONTROL_BUILD_DIR / "Base.SC2Data" / "KernelControlDispatch.galaxy").write_text(
        KERNEL_CONTROL_DISPATCH, encoding="utf-8", newline="\n")
    (KERNEL_CMLIB_CONTROL_BUILD_DIR / "MapScript.galaxy").write_text(
        KERNEL_CMLIB_CONTROL_MAPSCRIPT, encoding="utf-8", newline="\n")
    (KERNEL_CMLIB_CONTROL_BUILD_DIR / "BankList.xml").write_text(
        BANK_LIST, encoding="utf-8", newline="\n")
    (KERNEL_CMLIB_CONTROL_BUILD_DIR / "DocumentInfo").write_text(
        DOCUMENT_INFO, encoding="utf-8", newline="\n")
    packer_output = pack_map(KERNEL_CMLIB_CONTROL_BUILD_DIR, KERNEL_CMLIB_CONTROL_MAP)

    report = {
        "schemaVersion": 1,
        "classification": "static",
        "kind": "kernel-cmlib-control",
        "map": KERNEL_CMLIB_CONTROL_MAP.relative_to(REPO).as_posix(),
        "sha256": sha256(KERNEL_CMLIB_CONTROL_MAP),
        "cmlibFiles": len(list(cmlib_out.glob("*.galaxy"))) - 1,
        "kernelFiles": ["LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"],
        "runtimeLabFiles": ["KernelControlDispatch.galaxy"],
        "dependencies": ["Campaigns/Void.SC2Campaign"],
        "packerOutput": packer_output,
    }
    KERNEL_CMLIB_CONTROL_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def build_kernel_control_no_triggers() -> int:
    if KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR.exists():
        shutil.rmtree(KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR)
    shutil.copytree(BASE_MAP, KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR)
    remove_triggers_payload(KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR)
    for filename in ("LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"):
        copy_required(KERNEL / filename, KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR / "Base.SC2Data" / filename)
    (KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR / "Base.SC2Data" / "KernelControlDispatch.galaxy").write_text(
        KERNEL_CONTROL_DISPATCH, encoding="utf-8", newline="\n")
    (KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR / "MapScript.galaxy").write_text(
        KERNEL_CONTROL_MAPSCRIPT, encoding="utf-8", newline="\n")
    (KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR / "BankList.xml").write_text(
        BANK_LIST, encoding="utf-8", newline="\n")
    (KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR / "DocumentInfo").write_text(
        DOCUMENT_INFO, encoding="utf-8", newline="\n")
    packer_output = pack_map(KERNEL_CONTROL_NO_TRIGGERS_BUILD_DIR, KERNEL_CONTROL_NO_TRIGGERS_MAP)

    report = {
        "schemaVersion": 1,
        "classification": "static",
        "kind": "kernel-control-no-triggers",
        "map": KERNEL_CONTROL_NO_TRIGGERS_MAP.relative_to(REPO).as_posix(),
        "sha256": sha256(KERNEL_CONTROL_NO_TRIGGERS_MAP),
        "cmlibFiles": 0,
        "kernelFiles": ["LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"],
        "runtimeLabFiles": ["KernelControlDispatch.galaxy"],
        "dependencies": ["Campaigns/Void.SC2Campaign"],
        "removedFiles": ["Triggers"],
        "packerOutput": packer_output,
    }
    KERNEL_CONTROL_NO_TRIGGERS_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def build_arena_kernel_control() -> int:
    if ARENA_KERNEL_CONTROL_BUILD_DIR.exists():
        shutil.rmtree(ARENA_KERNEL_CONTROL_BUILD_DIR)
    shutil.copytree(ARENA_BASE_MAP, ARENA_KERNEL_CONTROL_BUILD_DIR)
    for filename in ("LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"):
        copy_required(KERNEL / filename, ARENA_KERNEL_CONTROL_BUILD_DIR / "Base.SC2Data" / filename)
    (ARENA_KERNEL_CONTROL_BUILD_DIR / "Base.SC2Data" / "KernelControlDispatch.galaxy").write_text(
        KERNEL_CONTROL_DISPATCH, encoding="utf-8", newline="\n")
    (ARENA_KERNEL_CONTROL_BUILD_DIR / "MapScript.galaxy").write_text(
        KERNEL_CONTROL_MAPSCRIPT, encoding="utf-8", newline="\n")
    (ARENA_KERNEL_CONTROL_BUILD_DIR / "BankList.xml").write_text(
        BANK_LIST, encoding="utf-8", newline="\n")
    (ARENA_KERNEL_CONTROL_BUILD_DIR / "DocumentInfo").write_text(
        DOCUMENT_INFO, encoding="utf-8", newline="\n")
    packer_output = pack_map(ARENA_KERNEL_CONTROL_BUILD_DIR, ARENA_KERNEL_CONTROL_MAP)

    report = {
        "schemaVersion": 1,
        "classification": "static",
        "kind": "arena-kernel-control",
        "map": ARENA_KERNEL_CONTROL_MAP.relative_to(REPO).as_posix(),
        "sha256": sha256(ARENA_KERNEL_CONTROL_MAP),
        "baseMap": ARENA_BASE_MAP.relative_to(REPO).as_posix(),
        "cmlibFiles": 0,
        "kernelFiles": ["LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"],
        "runtimeLabFiles": ["KernelControlDispatch.galaxy"],
        "dependencies": ["Campaigns/Void.SC2Campaign"],
        "dependencyPolicy": "Removed the missing WarClassicSystem.SC2Mod dependency from the copied diagnostic build.",
        "packerOutput": packer_output,
    }
    ARENA_KERNEL_CONTROL_REPORT.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


def build_breakpoint_trace() -> int:
    if BREAKPOINT_TRACE_BUILD_DIR.exists():
        shutil.rmtree(BREAKPOINT_TRACE_BUILD_DIR)
    shutil.copytree(BASE_MAP, BREAKPOINT_TRACE_BUILD_DIR)
    # The copied skeleton carries a compiled Triggers payload. Remove it so
    # the runtime compiles the fixture's current MapScript.galaxy instead of
    # dispatching the skeleton's stale trigger table.
    remove_triggers_payload(BREAKPOINT_TRACE_BUILD_DIR)
    triggers_version = BREAKPOINT_TRACE_BUILD_DIR / "Triggers.version"
    if triggers_version.exists():
        triggers_version.unlink()
    (BREAKPOINT_TRACE_BUILD_DIR / "Base.SC2Data" / "BreakpointTraceDispatch.galaxy").write_text(
        BREAKPOINT_TRACE_DISPATCH, encoding="utf-8", newline="\n")
    (BREAKPOINT_TRACE_BUILD_DIR / "MapScript.galaxy").write_text(
        BREAKPOINT_TRACE_MAPSCRIPT, encoding="utf-8", newline="\n")
    (BREAKPOINT_TRACE_BUILD_DIR / "BankList.xml").write_text(
        TRACE_BANK_LIST, encoding="utf-8", newline="\n")
    (BREAKPOINT_TRACE_BUILD_DIR / "DocumentInfo").write_text(
        DOCUMENT_INFO, encoding="utf-8", newline="\n")
    packer_output = pack_map(BREAKPOINT_TRACE_BUILD_DIR, BREAKPOINT_TRACE_MAP)
    BREAKPOINT_TRACE_BANK_SEED.parent.mkdir(parents=True, exist_ok=True)
    BREAKPOINT_TRACE_BANK_SEED.write_text(
        "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
        "<Bank version=\"1\">\n"
        "  <Section name=\"trace\">\n"
        "    <Key name=\"seed_marker\"><Value int=\"1\" /></Key>\n"
        "  </Section>\n"
        "</Bank>\n",
        encoding="utf-8",
        newline="\n",
    )

    report = {
        "schemaVersion": 1,
        "classification": "static",
        "kind": "breakpoint-trace",
        "map": BREAKPOINT_TRACE_MAP.relative_to(REPO).as_posix(),
        "sha256": sha256(BREAKPOINT_TRACE_MAP),
        "sourceFiles": ["MapScript.galaxy", "BreakpointTraceDispatch.galaxy"],
        "dependencies": ["Campaigns/Void.SC2Campaign"],
        "triggerDelaySeconds": 5.0,
        "bankName": "GalaxyVibeTrace",
        "bankKeys": ["startup", "trace_before", "trace_after"],
        "bankSeed": BREAKPOINT_TRACE_BANK_SEED.relative_to(REPO).as_posix(),
        "removedFiles": ["Triggers", "Triggers.version"],
        "packerOutput": packer_output,
    }
    BREAKPOINT_TRACE_REPORT.parent.mkdir(parents=True, exist_ok=True)
    BREAKPOINT_TRACE_REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def _build_direct_trace_variant(
    build_dir: Path,
    output_map: Path,
    report_path: Path,
    dispatch: str,
    mapscript: str,
    kind: str,
) -> int:
    """Build one InitMap TriggerExecute variant from the shared probe body."""
    if build_dir.exists():
        shutil.rmtree(build_dir)
    shutil.copytree(BASE_MAP, build_dir)
    remove_triggers_payload(build_dir)
    triggers_version = build_dir / "Triggers.version"
    if triggers_version.exists():
        triggers_version.unlink()
    (build_dir / "Base.SC2Data" / "BreakpointTraceDispatch.galaxy").write_text(
        dispatch, encoding="utf-8", newline="\n")
    (build_dir / "MapScript.galaxy").write_text(
        mapscript, encoding="utf-8", newline="\n")
    (build_dir / "BankList.xml").write_text(
        TRACE_BANK_LIST, encoding="utf-8", newline="\n")
    (build_dir / "DocumentInfo").write_text(
        DOCUMENT_INFO, encoding="utf-8", newline="\n")
    packer_output = pack_map(build_dir, output_map)

    BREAKPOINT_TRACE_BANK_SEED.parent.mkdir(parents=True, exist_ok=True)
    if not BREAKPOINT_TRACE_BANK_SEED.exists():
        BREAKPOINT_TRACE_BANK_SEED.write_text(
            "<?xml version=\"1.0\" encoding=\"utf-8\"?>\n"
            "<Bank version=\"1\">\n"
            "  <Section name=\"trace\">\n"
            "    <Key name=\"seed_marker\"><Value int=\"1\" /></Key>\n"
            "  </Section>\n"
            "</Bank>\n",
            encoding="utf-8",
            newline="\n",
        )

    report = {
        "schemaVersion": 1,
        "classification": "static",
        "kind": kind,
        "map": output_map.relative_to(REPO).as_posix(),
        "sha256": sha256(output_map),
        "sourceFiles": ["MapScript.galaxy", "BreakpointTraceDispatch.galaxy"],
        "dependencies": ["Campaigns/Void.SC2Campaign"],
        "dispatch": "InitMap -> TriggerExecute(TriggerCreate(\"BreakpointTrace_Probe\"), false, true)",
        "bankName": "GalaxyVibeTrace",
        "bankKeys": ["startup", "trace_before", "trace_after"],
        "bankSeed": BREAKPOINT_TRACE_BANK_SEED.relative_to(REPO).as_posix(),
        "removedFiles": ["Triggers", "Triggers.version"],
        "packerOutput": packer_output,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def build_breakpoint_trace_direct() -> int:
    """Build the InitMap breakpoint probe used by the armed observer."""
    return _build_direct_trace_variant(
        BREAKPOINT_TRACE_DIRECT_BUILD_DIR,
        BREAKPOINT_TRACE_DIRECT_MAP,
        BREAKPOINT_TRACE_DIRECT_REPORT,
        BREAKPOINT_TRACE_DISPATCH,
        BREAKPOINT_TRACE_DIRECT_MAPSCRIPT,
        "breakpoint-trace-direct",
    )


def build_breakpoint_trace_direct_control() -> int:
    """Build the InitMap control probe without the debug breakpoint."""
    return _build_direct_trace_variant(
        BREAKPOINT_TRACE_DIRECT_CONTROL_BUILD_DIR,
        BREAKPOINT_TRACE_DIRECT_CONTROL_MAP,
        BREAKPOINT_TRACE_DIRECT_CONTROL_REPORT,
        BREAKPOINT_TRACE_DIRECT_CONTROL_DISPATCH,
        BREAKPOINT_TRACE_DIRECT_CONTROL_MAPSCRIPT,
        "breakpoint-trace-direct-control",
    )


def main() -> int:
    for required in (RUNTIME_BASE_MAP, CMLIB, SELFTEST, KERNEL, PACKER, STORMLIB):
        if not required.exists():
            raise FileNotFoundError(required)

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    shutil.copytree(RUNTIME_BASE_MAP, BUILD_DIR)

    cmlib_out = copy_cmlib_sources(BUILD_DIR)

    runtime_out = BUILD_DIR / "Base.SC2Data" / "scripts" / "runtime_lab"
    runtime_sources = sorted((PROJECT / "runtime" / "galaxy").glob("*.galaxy"))
    for source in runtime_sources:
        destination = (
            BUILD_DIR / "Base.SC2Data" / source.name
            if source.name in ROOT_RUNTIME_FILES
            else runtime_out / source.name
        )
        copy_required(source, destination)
    for filename in ("LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"):
        copy_required(KERNEL / filename, BUILD_DIR / "Base.SC2Data" / filename)

    (BUILD_DIR / "MapScript.galaxy").write_text(MAPSCRIPT, encoding="utf-8", newline="\n")
    (BUILD_DIR / "BankList.xml").write_text(BANK_LIST, encoding="utf-8", newline="\n")
    (BUILD_DIR / "DocumentInfo").write_text(DOCUMENT_INFO, encoding="utf-8", newline="\n")
    packer_output = pack_map(BUILD_DIR, OUTPUT_MAP)

    report = {
        "schemaVersion": 1,
        "classification": "static",
        "map": OUTPUT_MAP.relative_to(REPO).as_posix(),
        "sha256": sha256(OUTPUT_MAP),
        "baseMap": RUNTIME_BASE_MAP.relative_to(REPO).as_posix(),
        "cmlibFiles": len(list(cmlib_out.glob("*.galaxy"))) - 1,
        "kernelFiles": ["LibVibeKernel_h.galaxy", "LibVibeKernel.galaxy", "LibVibeHandles.galaxy"],
        "runtimeLabFiles": [source.name for source in runtime_sources],
        "dependencies": ["Campaigns/Void.SC2Campaign"],
        "packerOutput": packer_output,
    }
    REPORT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["--cmlib-control"]:
        raise SystemExit(build_cmlib_control())
    if sys.argv[1:] == ["--kernel-control"]:
        raise SystemExit(build_kernel_control())
    if sys.argv[1:] == ["--kernel-cmlib-control"]:
        raise SystemExit(build_kernel_cmlib_control())
    if sys.argv[1:] == ["--kernel-control-no-triggers"]:
        raise SystemExit(build_kernel_control_no_triggers())
    if sys.argv[1:] == ["--arena-kernel-control"]:
        raise SystemExit(build_arena_kernel_control())
    if sys.argv[1:] == ["--breakpoint-trace"]:
        raise SystemExit(build_breakpoint_trace())
    if sys.argv[1:] == ["--breakpoint-trace-direct"]:
        raise SystemExit(build_breakpoint_trace_direct())
    if sys.argv[1:] == ["--breakpoint-trace-direct-control"]:
        raise SystemExit(build_breakpoint_trace_direct_control())
    if len(sys.argv) > 1:
        raise SystemExit(
            "Usage: build_runtime_lab.py [--cmlib-control|--kernel-control|--kernel-cmlib-control|--kernel-control-no-triggers|--arena-kernel-control|--breakpoint-trace|--breakpoint-trace-direct|--breakpoint-trace-direct-control]"
        )
    raise SystemExit(main())
