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
    generic_map_glue = (ASSETS / "map-glue.generic.galaxy").read_text(encoding="utf-8-sig")

    assert "Reset-CmreRuntimeListenerBank" in source
    assert "Wait-CmreRuntimeListener" in source
    assert "Assert-CmreNoNewScriptErrors" in source
    assert '*ScriptError*.txt' in script_error_body
    assert "runtime_listener_started" in wait_body
    assert "runtime_listener_ready" in wait_body
    assert "bridge_heartbeat" in wait_body
    assert "initialization_complete" in wait_body
    assert "initialization_building_ready_p1" in wait_body
    assert "initialization_units_ready_p1" in wait_body
    assert "Wait-CmreRuntimeListener -TimeoutSeconds 120" in source
    assert "CMRERebornDebug" in overlay
    assert '@{ Name = "GalaxyVibe"; Player = "1" }' in overlay
    assert 'Documents\\StarCraft II\\Banks' in overlay
    assert "gt_CmreOnDemandRuntimeListener_Init();" in observer_overlay_body

    assert "gt_CmreOnDemandRuntimeListener_Func" in map_glue
    assert "libMapModBridge_gf_StartHeartbeat();" in map_glue
    assert "runtime_listener_ready" in map_glue
    # The launcher must select the Dead of Night fragment from an ASCII
    # MapScript signature, because the Chinese map filename is not reliable
    # after Windows PowerShell code-page conversion.
    assert '$isDeadOfNight = $mapScript.Contains("gv_day_Duration_First")' in observer_overlay_body
    assert '$fragmentName = if ($isDeadOfNight) { "map-glue.dead-of-night.galaxy" } else { "map-glue.generic.galaxy" }' in observer_overlay_body
    assert 'tools\\galaxy-vibe\\kernel' in observer_overlay_body
    assert 'using registered shared kernel for $MapName' in observer_overlay_body
    assert "MeleeInitUnitsForPlayer(2, lv_p2Race, lv_p2Start);" in map_glue
    assert "MeleeInitResourcesForPlayer(2, lv_p2Race);" in map_glue
    assert "AIMeleeStart(2);" in map_glue
    assert "gt_CmreOnDemandAllyChat_Init" in map_glue
    assert "fallback_last_result" in map_glue
    assert "TriggerAddEventTimeElapsed(gt_CmreOnDemandComputerAllyReady, 0.0, c_timeGame);" in map_glue
    assert "TriggerExecute(gt_CmreOnDemandComputerAllyReady, false, true);" in map_glue
    assert "p2_starting_units_initialized" in map_glue
    assert "P1 remains owned by CMRE commander" in map_glue
    # Generic CMRE maps must expose the same P1 -> P2 Computer contract. The
    # Dead of Night fragment has mission-specific polling, but native ally
    # startup and chat forwarding cannot be a map-name special case.
    for required in [
        "MeleeInitUnitsForPlayer(2, lv_p2Race, lv_p2Start);",
        "MeleeInitResourcesForPlayer(2, lv_p2Race);",
        "AIMeleeStart(2);",
        "gt_CmreOnDemandAllyChat_Init",
        "fallback_last_result",
        "TriggerAddEventTimeElapsed(gt_CmreOnDemandComputerAllyReady, 0.0, c_timeGame);",
        "TriggerExecute(gt_CmreOnDemandComputerAllyReady, false, true);",
    ]:
        assert required in generic_map_glue
    assert "libVibeKernel_gf_RegisterEntryPoints();" in observer_overlay_body
    assert 'libMapModBridge_gf_WriteDebugBank("map_init_entered", 1);' in observer_overlay_body
    assert "Install-CmreTriggerCustomScriptOverlay" in observer_overlay_body
    assert "Install-CmreStartupDebugMarkersOverlay" in observer_overlay_body
    assert "Add-CmreBlockAfter" in overlay
    assert "Add-CmreBlockAfterInFunction" in overlay
    assert "Function-local anchor not found" in overlay
    assert "    // Implementation" in overlay
    assert "startup_map_init" in overlay
    assert "startup_dev_begin" in overlay
    assert "startup_custom_launch" in overlay
    assert "startup_dev_finish" in overlay
    assert "Triggers" in overlay
    assert "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_V1" in overlay
    assert "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_V2" in overlay
    assert "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_V3" in overlay
    assert "triggers_customscript_entered" in overlay
    assert 'BankValueSetFromInt(BankLastCreated(), "debug", "triggers_customscript_entered", 1);' in overlay
    assert "api_customscript_init_started" in overlay
    assert "api_customscript_init_complete" in overlay
    assert "libVibeKernel_gv_initialized" in overlay
    assert "InitMap" in overlay
    assert "single path" in overlay
    assert "InitMap();" not in overlay
    assert 'UnitCreate(1, "Marine"' not in overlay
    assert "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_INITMAP_GUARD" in overlay
    assert 'libVibeKernel_gf_RegisterEntryPoints();' in overlay
    assert "registration belongs after the generated InitTriggers graph" in overlay
    assert 'stage16_before_vibe' in overlay
    assert 'stage16_after_vibe' in overlay
    assert 'CMRE trigger custom-script registration anchor not found' not in overlay
    assert "<InitFunc>cmre_on_demand_trigger_customscript_init</InitFunc>" in overlay
    assert "void cmre_on_demand_trigger_customscript_init()" in overlay
    assert 'LastIndexOf("</Library>"' in overlay
    assert 'LastIndexOf($documentClose' in overlay


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


def test_direct_map_api_mode_attaches_after_map_initialization():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "[switch]$DirectMapApi" in source
    assert '"-DirectMapApi 必须配合 -ListenPort <port> 使用"' in source
    assert "DirectMapApi cannot be combined with -DebugMode or -ApiMinimal" in source
    assert "SC2 direct-map + API mode" in source
    assert "Wait-CmreGameLogMapLoadSignal -Since $launchStartedAt" in source
    assert "Wait-CmreRuntimeListener -TimeoutSeconds 120" in source
    assert "Host must attach with --join-existing" in source
    assert "--join-existing" in source
    assert '"-listen", "127.0.0.1", "-port", "$ListenPort", "-debug"' in source


def test_overlay_assets_hold_galaxy_fragments_outside_launcher():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    core_overlay = CORE_OVERLAY.read_text(encoding="utf-8-sig")
    assert "Install-CmreSavedProfileStartupOverlay" in overlay
    assert "Install-CmreObserverOverlay" in overlay
    assert "Install-CmreCoreRuntimeErrorOverlay" in core_overlay
    assert "deterministic offsets inside the uniquely named trigger function" in core_overlay
    assert "[regex]::Replace($comi, $comiAnchor10, $comiPatch10)" not in core_overlay
    assert "$functionIndex10 = $comi.IndexOf($comiFunction10" in core_overlay

    required_assets = [
        ASSETS / "startup" / "saved-profile-body.galaxy.tpl",
        ASSETS / "startup" / "player-commander.galaxy.tpl",
        ASSETS / "startup" / "tail.default.galaxy",
        ASSETS / "startup" / "tail.skip-pause.galaxy",
        ASSETS / "startup" / "tail.skip-countdown.galaxy",
        ASSETS / "startup" / "tail.headless.galaxy",
        ASSETS / "startup" / "initialization-gate.galaxy",
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
    assert "MeleeInitUnitsForPlayer" in map_glue
    assert "MeleeInitResourcesForPlayer" in map_glue
    assert "gt_CmreOnDemandRuntimeListener_Init" in map_glue
    initialization_gate = (ASSETS / "startup" / "initialization-gate.galaxy").read_text(encoding="utf-8-sig")
    assert "initialization_complete" in initialization_gate
    assert "starting structures and workers are present" in initialization_gate
    assert "gf_CmreOnDemandAliveCount" in initialization_gate
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
    assert 'Join-Path $WorkspaceRoot "src\\projects\\cmre-porting\\packages\\Maps\\$MapName\\Base.SC2Data"' in overlay
    assert 'Copy-CmreOverlayFiles -Files $vibeKernelFiles -DestinationRoot $baseData' in overlay
    assert "Replace('include \"LibVibeKernel_h\"', 'include \"LibVibeKernel\"')" in overlay
    assert "declarations but no implementations" in overlay
    assert "Select-String -Pattern 'CommanderSelectionScreen' -SimpleMatch" in overlay


def test_launcher_serializes_sc2_runtime_and_never_kills_an_existing_instance():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert 'Global\\SC2VibeTools-SC2Runtime' in source
    assert 'artifacts\\runtime\\sc2-runtime-lease.json' in source
    assert 'SC2_RUNTIME_BUSY' in source
    assert 'Wait-Sc2RuntimeProcess' in source
    assert 'ReleaseMutex()' in source
    assert 'Stop-RunningSc2' not in source
    assert 'Get-Process -Name "SC2","StarCraft II"' not in source


def test_secondary_client_does_not_mutate_shared_runtime_banks():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "if (-not $SecondaryClient) {\n        Reset-CmreRuntimeListenerBank" in source
    assert "SecondaryClient: skipping shared runtime listener bank reset" in source
    assert "SecondaryClient: skipping shared CMRE launch profile bank write" in source
    assert "SecondaryClient: skipping shared CampaignXCore bank writes" in source


def test_secondary_client_can_reuse_an_existing_staged_map_without_restaging():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "[switch]$ReuseStagedMap" in source
    assert "-ReuseStagedMap requires -MapCopySuffix <existing-suffix>" in source
    assert "if (-not $ReuseStagedMap) {" in source
    assert "Reusing existing staged map: $liveMap" in source
    assert "[string]$DataDirOverride = \"\"" in source
    assert "-DataDirOverride is reserved for -SecondaryClient" in source
    assert "$sc2DataDir = if ($DataDirOverride -ne \"\")" in source


def test_api_port_owner_is_scalar_before_pid_conversion():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "$portOwner = @(Get-NetTCPConnection" in source
    assert "$ownerPid = @($portOwner.OwningProcess) | Select-Object -First 1" in source
    assert "$proc = @(Get-Process -Id ([int]$ownerPid)" in source
