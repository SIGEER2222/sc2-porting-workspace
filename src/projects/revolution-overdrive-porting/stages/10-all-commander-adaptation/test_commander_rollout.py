"""Static contract coverage for the all-commander Revolution Overdrive rollout."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[5]
PROJECT = ROOT / "src" / "projects" / "revolution-overdrive-porting"
GENERATOR = PROJECT / "vibe" / "build_commander_rollout.py"
MANIFEST = PROJECT / "vibe" / "commander_map_patches.json"
TEMPLATE = PROJECT / "vibe" / "runtime_commander_overlay.galaxy.tpl"
LAUNCHER = ROOT / "tools" / "launchers" / "launch-revolution-overdrive.ps1"
REALTIME_PROBE = PROJECT / "stages" / "10-all-commander-adaptation" / "realtime_commander_probe.py"
RUNTIME_INDEX = (
    ROOT / "artifacts" / "projects" / "revolution-overdrive-porting"
    / "stage10-all-commander-adaptation" / "runtime-evidence-index.json"
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def test_manifest_covers_every_webui_commander_with_resolved_catalog_contracts():
    manifest = load_json(MANIFEST)
    patches = manifest["commanders"]

    assert manifest["schemaVersion"] == 2
    assert manifest["commanderCount"] == 50
    assert len(patches) == 50
    assert len({patch["commander"] for patch in patches}) == 50
    assert Counter(patch["group"] for patch in patches) == {
        "official": 18,
        "alenger": 12,
        "reborn": 15,
        "revolution-overdrive": 5,
    }
    assert all(patch["catalogContracts"] for patch in patches)
    assert all(contract["onMissing"] == "block" for patch in patches for contract in patch["catalogContracts"])
    assert all("E:\\" not in json.dumps(patch, ensure_ascii=False) for patch in patches)


def test_matrix_has_all_cells_and_keeps_unsupported_entry_flow_explicit():
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "matrix.json"
        run = subprocess.run(
            [sys.executable, str(GENERATOR), "--matrix-output", str(output)],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        assert run.returncode == 0, run.stderr or run.stdout
        matrix = load_json(output)

    assert (matrix["mapCount"], matrix["commanderCount"], matrix["cellCount"]) == (31, 50, 1550)
    assert not any("亡者之夜" in cell["map"] for cell in matrix["cells"])
    tarcade = [cell for cell in matrix["cells"] if cell["map"] == "tarcade.SC2Map"]
    assert len(tarcade) == 50
    assert {cell["status"] for cell in tarcade} == {"unsupported"}


def test_runtime_template_is_real_galaxy_logic_and_not_a_chat_selector():
    template = TEMPLATE.read_text(encoding="utf-8-sig")
    launcher = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "RO_PATCH_RUNTIME_OVERLAY_V1" in template
    assert "{{REPLACEMENT_BODY}}" in template
    assert "libNtve_gf_ReplaceUnit" in launcher
    assert "UnitCreate" in template
    assert "TriggerAddEventUnitCreated" in template
    assert "TriggerAddEventUnitChangeOwner" in template
    assert "TriggerAddEventTimePeriodic" in template
    assert "gf_ro_patch_ensure_startup_once" in template
    assert "{{STARTING_WORKER}}" in template
    assert "{{WORKER_COUNT}}" in template
    assert "Send-FactionChat" not in template


def test_launcher_resolves_manifest_and_stages_only_selected_patch_dependencies():
    launcher = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "[string]$Commander" in launcher
    assert "Resolve-RevolutionCommanderPatch" in launcher
    assert "Copy-CommanderPatchDependencies" in launcher
    assert "Add-CommanderPatchDependenciesToMap" in launcher
    assert "Test-CommanderPatchCatalogs" in launcher
    assert "Apply-CommanderRuntimePatch" in launcher
    assert "function Get-Sha256Hex" in launcher
    assert "Get-FileHash" not in launcher
    assert "startupFallback" in launcher
    assert "{{STARTING_WORKER}}" in launcher
    assert "Forbidden Revolution Overdrive" not in launcher
    assert "Forbidden map for Revolution Overdrive commander adaptation" in launcher
    assert "Source map changed during staging" in launcher


def test_realtime_probe_is_manifest_driven_and_never_uses_request_step():
    probe = REALTIME_PROBE.read_text(encoding="utf-8-sig")

    assert "resolve_commander" in probe
    assert "RequestCreateGame" in probe
    assert "realtime=True" in probe
    assert "RequestJoinGame" in probe
    assert "RequestObservation" in probe
    assert "RequestStep" not in probe
    assert '"startingStructure"' in probe
    assert '"startingWorker"' in probe
    assert "gameLoopAdvanced" in probe
    assert "script_errors_since" in probe


def test_runtime_evidence_index_preserves_the_verified_alenger_pilot():
    index = load_json(RUNTIME_INDEX)
    records = index["cells"]
    pilot = next(
        item for item in records
        if item["map"] == "thanson01.SC2Map" and item["commander"] == "TerranAlenger3"
    )
    assert pilot["status"] == "runtime_pass"
    probe = load_json(ROOT / pilot["evidence"][1])
    assert probe["verdict"] == "passed_realtime_starting_structure_and_worker_observed"
    assert probe["requestStepsSent"] == 0
    assert probe["create"]["status"] == "init_game"
    assert probe["join"]["status"] == "in_game"
    assert probe["realtimeEvidence"]["gameLoopAdvanced"] is True
    assert probe["scriptErrors"] == []

    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / "matrix.json"
        run = subprocess.run(
            [sys.executable, str(GENERATOR), "--matrix-output", str(output)],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
            capture_output=True,
            check=False,
        )
        assert run.returncode == 0, run.stderr or run.stdout
        matrix = load_json(output)
    cell = next(
        item for item in matrix["cells"]
        if item["map"] == "thanson01.SC2Map" and item["commander"] == "TerranAlenger3"
    )
    assert cell["status"] == "runtime_pass"
    assert cell["runtimeEvidence"] == pilot["evidence"]
