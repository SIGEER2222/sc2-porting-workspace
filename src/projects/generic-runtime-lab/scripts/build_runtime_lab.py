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
include "TriggerLibs/natives"
include "scripts/cmlib/cmlib"
include "LibVibeKernel"
include "LibVibeInvokeDispatch"
include "scripts/runtime_lab/runtime_lab"
include "scripts/cmlib/cmlib_selftest"

void InitMap() {
    libVibeKernel_InitLib();
    CMLib_SelfTest();
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


def main() -> int:
    for required in (BASE_MAP, CMLIB, SELFTEST, KERNEL, PACKER, STORMLIB):
        if not required.exists():
            raise FileNotFoundError(required)

    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    shutil.copytree(BASE_MAP, BUILD_DIR)

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
    if len(sys.argv) > 1:
        raise SystemExit("Usage: build_runtime_lab.py [--cmlib-control]")
    raise SystemExit(main())
