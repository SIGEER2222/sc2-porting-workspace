from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LAUNCHER = ROOT / "tools" / "launchers" / "launch-cmre-alenger.ps1"
OVERLAY = ROOT / "tools" / "launchers" / "lib" / "cmre-on-demand-overlay.ps1"
CORE_OVERLAY = ROOT / "tools" / "launchers" / "lib" / "cmre-core-runtime-overlay.ps1"
ASSETS = ROOT / "tools" / "launchers" / "overlays" / "cmre-alenger"


def _function_body(source: str, name: str) -> str:
    marker = f"function {name}"
    start = source.find(marker)
    assert start != -1, f"{name} not found"
    brace = source.find("{", start)
    assert brace != -1, f"{name} opening brace not found"
    depth = 0
    for idx in range(brace, len(source)):
        ch = source[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[brace + 1 : idx]
    raise AssertionError(f"{name} closing brace not found")


def test_launcher_delegates_on_demand_overlay_work():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert r"lib\cmre-on-demand-overlay.ps1" in source

    startup_body = _function_body(source, "Enable-CmreSavedProfileStartup")
    observer_body = _function_body(source, "Install-CmreDynamicObserver")
    core_body = _function_body(source, "Patch-CmreCoreRuntimeErrors")

    for body in [startup_body, observer_body, core_body]:
        assert "[regex]::Replace" not in body
        assert "WriteAllText" not in body
        assert "WriteAllBytes" not in body
        assert "CMUIX_ReadyBeginCountdown();" not in body
        assert 'TriggerSendEvent("CU_CommChoiceEventClosed")' not in body
        assert "GameSetMissionTimePaused(true)" not in body

    assert "Install-CmreSavedProfileStartupOverlay" in startup_body
    assert "Install-CmreObserverOverlay" in observer_body
    assert "Install-CmreCoreRuntimeErrorOverlay" in core_body


def test_launch_profile_carries_on_demand_runtime_inputs():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    profile_body = _function_body(source, "Write-CmreLaunchProfile")

    for key in [
        "StartingStructure",
        "StartingWorker",
        "WorkerCount",
        "VanillaRemovalCount",
        "VanillaRemoval|",
        "CreateStartingUnitsP1",
        "CreateStartingUnitsP2",
        "EnsurePreventDefeatP1",
        "EnsurePreventDefeatP2",
        "RebornStartingUnitsHandled",
    ]:
        assert key in profile_body


def test_launcher_requires_runtime_listener_and_broad_script_error_gate():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    observer_overlay_body = _function_body(overlay, "Install-CmreObserverOverlay")
    wait_body = _function_body(source, "Wait-CmreRuntimeListener")
    script_error_body = _function_body(source, "Get-CmreNewScriptErrorFiles")
    map_glue = (ASSETS / "map-glue.dead-of-night.galaxy").read_text(encoding="utf-8-sig")

    assert "Reset-CmreRuntimeListenerBank" in source
    assert "Wait-CmreRuntimeListener" in source
    assert "Assert-CmreNoNewScriptErrors" in source
    assert '*ScriptError*.txt' in script_error_body
    assert "runtime_listener_started" in wait_body
    assert "runtime_listener_ready" in wait_body
    assert "bridge_heartbeat" in wait_body
    assert "CMRERebornDebug" in overlay
    assert 'Documents\\StarCraft II\\Banks' in overlay
    assert "gt_CmreOnDemandRuntimeListener_Init();" in observer_overlay_body
    assert 'include "LibVibeKernel_h"' in observer_overlay_body
    assert 'include "LibVibeKernel"' in observer_overlay_body

    assert "gt_CmreOnDemandRuntimeListener_Func" in map_glue
    assert "libMapModBridge_gf_StartHeartbeat();" in map_glue
    assert "runtime_listener_ready" in map_glue
    assert 'libMapModBridge_gf_WriteDebugBank("map_init_entered", 1);' in observer_overlay_body


def test_player_mode_launches_direct_map_from_gamelog_signal():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    core_overlay = CORE_OVERLAY.read_text(encoding="utf-8-sig")
    assert 'SC2 direct-map mode: launching SC2Switcher_x64.exe' in source
    assert 'Wait-CmreGameLogMapLoadSignal' in source
    assert '*Alert*.txt' in source
    assert 'Direct SC2 map launch must use Maps\\\\$MapName' in source
    assert 'guard empty hero structure unit type' in core_overlay
    assert '-loadmap `"$liveMap`"' not in source
    assert '$args = @("`"$liveMap`"")' not in source


def test_overlay_assets_hold_galaxy_fragments_outside_launcher():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    core_overlay = CORE_OVERLAY.read_text(encoding="utf-8-sig")
    assert "Install-CmreSavedProfileStartupOverlay" in overlay
    assert "Install-CmreObserverOverlay" in overlay
    assert "Install-CmreCoreRuntimeErrorOverlay" in core_overlay

    required_assets = [
        ASSETS / "startup" / "saved-profile-body.galaxy.tpl",
        ASSETS / "startup" / "player-commander.galaxy.tpl",
        ASSETS / "startup" / "tail.default.galaxy",
        ASSETS / "startup" / "tail.skip-pause.galaxy",
        ASSETS / "startup" / "tail.skip-countdown.galaxy",
        ASSETS / "startup" / "tail.headless.galaxy",
        ASSETS / "map-glue.generic.galaxy",
        ASSETS / "map-glue.dead-of-night.galaxy",
    ]
    for path in required_assets:
        assert path.exists(), path

    startup_template = (ASSETS / "startup" / "saved-profile-body.galaxy.tpl").read_text(encoding="utf-8-sig")
    map_glue = (ASSETS / "map-glue.dead-of-night.galaxy").read_text(encoding="utf-8-sig")
    default_tail = (ASSETS / "startup" / "tail.default.galaxy").read_text(encoding="utf-8-sig")
    headless_tail = (ASSETS / "startup" / "tail.headless.galaxy").read_text(encoding="utf-8-sig")

    assert "CMRE_ON_DEMAND_SAVED_PROFILE_STARTUP" in startup_template
    assert "{{COMMANDER}}" not in startup_template
    assert "CMRE_ON_DEMAND_HEADLESS_STARTUP" in headless_tail
    assert "libCOOC_gf_CC_DevStartupFinish();" in headless_tail
    assert "CommanderSelectionScreen" not in headless_tail
    assert "CMRE_ON_DEMAND_MAP_GLUE" in map_glue
    assert "gf_CmreOnDemandProfileString" in map_glue
    assert "libMapModBridge_gf_CreateStartingUnits" in map_glue
    assert "gt_CmreOnDemandRuntimeListener_Init" in map_glue
    assert "CMUIX_ReadyBeginCountdown();" in default_tail
    assert 'TriggerSendEvent("CU_CommChoiceEventClosed")' not in default_tail


def test_headless_startup_is_the_default_non_selection_path():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    overlay = OVERLAY.read_text(encoding="utf-8-sig")

    assert '$commanderSelectionDisabled = $MapName -eq "亡者之夜.SC2Map"' in source
    assert 'throw "-ShowSelectionUI is disabled for ${MapName}' in source
    assert 'forcing headless startup' in source
    assert "-Headless" in source
    assert "-Headless:$Headless" in source
    assert "[switch]$Headless" in overlay
    assert "tail.headless.galaxy" in overlay
    assert "CMRE_ON_DEMAND_NO_COMMANDER_SELECTION" in overlay
    assert "CommanderSelectionScreen" in overlay
    assert "Assert-CmreCommanderSelectionRemoved" in overlay
    assert "Join-Path $baseData \"LibCOOC.galaxy\"" in overlay
    assert "Join-Path $MapPath \"MapScript.galaxy\"" in overlay
    assert "Select-String -Pattern 'CommanderSelectionScreen' -SimpleMatch" in overlay
