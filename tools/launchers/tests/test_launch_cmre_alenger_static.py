import json
import re
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


def _galaxy_function_body(source: str, name: str) -> str:
    definition = re.search(
        rf"(?m)^(?:bool|void|int|string|fixed|text)\s+{re.escape(name)}\s*\([^;\n]*\)\s*\{{",
        source,
    )
    assert definition is not None, f"{name} definition not found"
    brace = source.find("{", definition.start())
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

    startup_body = _function_body(source, "Enable-CmrePreselectedCommanderStartup")
    observer_body = _function_body(source, "Install-CmreDynamicObserver")
    core_body = _function_body(source, "Patch-CmreCoreRuntimeErrors")

    for body in [startup_body, observer_body, core_body]:
        assert "[regex]::Replace" not in body
        assert "WriteAllText" not in body
        assert "WriteAllBytes" not in body
        assert "CMUIX_ReadyBeginCountdown();" not in body
        assert 'TriggerSendEvent("CU_CommChoiceEventClosed")' not in body
        assert "GameSetMissionTimePaused(true)" not in body

    assert "Install-CmrePreselectedCommanderStartupOverlay" in startup_body
    assert "-Commander $Commander" in startup_body
    assert "Install-CmreObserverOverlay" in observer_body
    assert "Install-CmreCoreRuntimeErrorOverlay" in core_body


def test_launcher_accepts_an_explicit_read_only_map_source():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert '[string]$MapSourceOverride = ""' in source
    assert "Resolve-Path -LiteralPath $MapSourceOverride" in source
    assert 'Join-Path $mapSource "MapScript.galaxy"' in source


def test_launcher_supports_explicit_startup_contract_overrides_with_optional_sources():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert '[string]$StartupContractOverride = ""' in source
    assert "Resolve-Path -LiteralPath $StartupContractOverride" in source
    assert "Startup contract override:" in source
    assert "optionalSource" in source
    assert "Startup contract optional source is absent" in source
    assert "requireAnalysisReady" in source
    assert "requireStartingGameQ" in source


def test_reborn_bank_authorization_covers_profile_runtime_and_debug_banks():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _function_body(source, "Patch-RebornBankAuthorization")
    assert "$bankListXml = [xml]$content" in body
    assert "CMCoopLaunchProfile" in body
    assert "cryswarmcoop" in body
    assert "CMRERebornDebug" in body
    assert "Players = @(1, 2)" in body
    assert "Players = @(1, 2, 14)" in body
    assert "all required bank authorizations already present" in body


def test_reborn_deferred_startup_waits_for_required_start_locations():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "CMRE_PATCH_REBORN_DEFERRED_STARTUP_V6" in source
    deferred = source[source.index("CMRE_PATCH_REBORN_DEFERRED_STARTUP_V6") :]
    assert "point lv_p1Start;" in deferred
    assert "point lv_p2Start;" in deferred
    assert "PlayerStartLocation(1)" in deferred
    assert "PlayerStartLocation(2)" in deferred
    assert "reborn_adapter_start_locations_ready" in deferred
    assert 'libMapModBridge_gf_WriteDebugBank("reborn_adapter_deferred_entered", 1);' in deferred
    assert "gv_CmreRebornDeferredStartupStarted" in deferred
    assert 'libMapModBridge_gf_WriteDebugBank("reborn_adapter_start_locations_waiting", 1);' in deferred
    assert "TriggerExecute(lib48DF4533_gt_SwarmSetup, false, false);" in deferred
    assert "TriggerAddEventTimePeriodic(gt_CmreRebornDeferredStartup, 1.0, c_timeReal);" in deferred


def test_reborn_deferred_startup_waits_for_native_opening_before_adapter_fallback():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    deferred = source[source.index("CMRE_PATCH_REBORN_DEFERRED_STARTUP_V6") :]

    assert "gv_CmreRebornNativeOpeningWaitTicks" in deferred
    assert 'libMapModBridge_gf_AliveUnitCount("$startingStructure", 1)' in deferred
    assert 'libMapModBridge_gf_AliveUnitCount("$startingStructure", 2)' in deferred
    assert 'libMapModBridge_gf_AliveUnitCount("$startingWorker", 1)' in deferred
    assert 'libMapModBridge_gf_AliveUnitCount("$startingWorker", 2)' in deferred
    assert 'reborn_adapter_native_opening_waiting' in deferred
    assert 'reborn_adapter_native_opening_wait_ticks' in deferred
    assert 'if (gv_CmreRebornNativeOpeningWaitTicks < 5)' in deferred
    assert 'reborn_adapter_native_opening_fallback' in deferred

    wait = deferred.index('reborn_adapter_native_opening_waiting')
    guard = deferred.index("gv_CmreRebornDeferredStartupStarted = true;")
    adapter = deferred.index("libRebornAdapter_gf_InitializeBeforeSwarmSetup(")
    assert wait < guard < adapter


def test_reborn_loading_confirm_prefers_process_main_window():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _function_body(source, "Send-CmreRebornLoadingConfirm")
    assert "Prefer the process-reported shell" in body
    assert "if ($process.MainWindowHandle -ne [IntPtr]::Zero)" in body
    assert "FindInputWindow" in body
    assert "score = 400" in body
    assert "score = IsWindowVisible(hWnd) ? 200 : 100" in body


def test_overlay_supports_reborn_generated_map_library_anchors():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    for anchor in [
        'include "Lib48DF4533"',
        'include "Lib281DEC45"',
        'include "Lib114935F5"',
        'include "TriggerLibs/NativeLib"',
        '    lib48DF4533_InitLib();',
        '    lib281DEC45_InitLib();',
        '    lib114935F5_InitLib();',
        '    libNtve_InitLib();',
    ]:
        assert anchor in overlay


def test_keepalive_without_reuse_lock_does_not_fail_during_cleanup():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    wait_body = _function_body(source, "Wait-Sc2RuntimeProcess")

    assert "[AllowNull()]$LockContext" in wait_body
    assert "if ($null -ne $LockContext)" in wait_body


def test_douququ_standalone_defers_vibe_registration_until_map_init_returns():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    start = overlay.index("function Install-CmreDouQuquStandaloneMapOverlay")
    end = overlay.index("function Replace-CmreBlockBetweenMarkers", start)
    body = overlay[start:end]
    glue = (ASSETS / "map-glue.dou-ququ-standalone.galaxy").read_text(encoding="utf-8-sig")

    # The standalone map needs an explicit asynchronous handoff after InitMap.
    # A synchronous RegisterEntryPoints call inside InitMap can start PollLoop
    # while the standalone map is still initializing and strand every Bank RPC.
    assert "libVibeKernel_InitLib();" in body
    assert "'    libVibeKernel_gf_RegisterEntryPoints();'" not in body
    assert "libMapModBridge_gf_WriteDebugBank(\"map_init_entered\", 1);" in body
    assert "gt_CmreDouQuquStandaloneVibeRegistration_Init();" in body
    assert "TriggerAddEventTimeElapsed(gt_CmreDouQuquStandaloneVibeRegistration, 0.1, c_timeGame);" in glue
    assert "TriggerExecute(gt_CmreDouQuquStandaloneVibeRegistration, false, false);" in glue
    assert "libVibeKernel_gf_RegisterEntryPoints();" in glue
    assert "libDouQuquRuntime_InitLib();" in glue
    assert "libDouQuquRuntime_InitLib();" not in body

    registration = glue[glue.index("bool gt_CmreDouQuquStandaloneVibeRegistration_Func"):]
    assert "Wait(0.1, c_timeReal);" in registration
    assert registration.index("Wait(0.1, c_timeReal);") < registration.index("libVibeKernel_gf_RegisterEntryPoints();")
    assert registration.index("Wait(0.1, c_timeReal);") < registration.index("libDouQuquRuntime_InitLib();")
    assert "gv_CmreDouQuquStandaloneVibeRegistrationStarted" in registration
    assert "vibe_registration_handoff_started" in registration
    assert "vibe_registration_handoff_after_wait" in registration
    assert "vibe_registration_kernel_done" in registration
    assert "vibe_registration_event_bridge_done" in registration


def test_on_demand_mod_dependencies_are_repaired_in_staged_install_copy():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "Repair-CmreOnDemandDependencyPaths" in source
    assert "file:Mods/7vs1/AlengerCommon.SC2Mod" in source
    assert "file:Mods/Commanders/SharedAlengerCommon.SC2Mod" in source
    assert "Read-DocumentHeaderDependencies" in source
    assert "Write-DocumentHeaderDependencies" in source


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


def test_launch_profile_defaults_commanders_to_max_level_and_full_mastery():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    profile_body = _function_body(source, "Write-CmreLaunchProfile")

    assert "Player|1|CommanderLevel" in profile_body
    assert "Player|2|CommanderLevel" in profile_body
    assert '$values[\'Player|1|CommanderLevel\'] = @("int", "15")' in profile_body
    assert '$values[\'Player|2|CommanderLevel\'] = @("int", "15")' in profile_body
    assert "MasteryLevel" in profile_body
    assert "@(30, 30, 30, 30, 30, 30)" in profile_body
    assert "Commander profile: level=15" in profile_body

    commander_level_pos = profile_body.index("Player|1|CommanderLevel")
    buff_patch_pos = profile_body.index("if ($EnableBuffPatch)")
    assert commander_level_pos < buff_patch_pos


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
    listener_calls = re.findall(r"Wait-CmreRuntimeListener -TimeoutSeconds (\d+)", source)
    assert listener_calls and max(map(int, listener_calls)) >= 120
    assert "CMRERebornDebug" in overlay
    assert "sourceMapDependencies" in source
    assert "Merge-CmreMapDependencies" in source
    assert "[AllowEmptyCollection()][string[]]$SourceDependencies" in source
    assert "file:Mods/reborn/crys_the_swarm_reborn.SC2Mod" in source
    assert "SwarmStory" in source
    assert '@{ Name = "GalaxyVibe"; Player = "1" }' in overlay
    assert 'Documents\\StarCraft II\\Banks' in overlay
    assert "gt_CmreOnDemandRuntimeListener_Init();" in observer_overlay_body


    assert "gt_CmreOnDemandRuntimeListener_Func" in map_glue
    assert "libMapModBridge_gf_StartHeartbeat();" in map_glue
    assert "runtime_listener_ready" in map_glue
    assert 'optional Triggers source has no map Root' in overlay
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
    # Both map fragments must keep the native Terran Computer economy on its
    # standard catalog. The Empire-only worker abilities are a P1 concern.
    for computer_map_glue in [map_glue, generic_map_glue]:
        for required in [
            'townHallType = "CommandCenter";',
            'barracksType = "Barracks";',
                'workerTrainAbility = "CommandCenterTrain";',
                    'combatTrainAbility = "BarracksTrain";',
                    'combatTrainCommand = 0;',
            'buildAbility = "TerranBuild";',
            'buildCommand = 3;',
            'TechTreeRequirementsEnable(2, false);',
            'TechTreeUnitAllow(2, "SCV", true);',
            'TechTreeUnitAllow(2, "CommandCenter", true);',
            'TechTreeUnitAllow(2, "Barracks", true);',
            'TechTreeUnitAllow(2, "Marine", true);',
                    'TechTreeAbilityAllow(2, AbilityCommand("CommandCenterTrain", 0), true);',
                    'TechTreeAbilityAllow(2, AbilityCommand("BarracksTrain", 0), true);',
                    'TechTreeAbilityAllow(2, AbilityCommand("P2MarineTrain", 0), true);',
                    'TechTreeAbilityAllow(2, AbilityCommand("BarracksTrain", 7), true);',
            'TechTreeAbilityAllow(2, AbilityCommand("TerranBuild", 3), true);',
            'TechTreeAbilityIsAllowed(',
            'TechTreeUnitCount(2, barracksType, c_techCountCompleteOnly)',
            'AIBuild(2, c_makePriorityTown, c_townMain, "Barracks", 1, c_makeDefault);',
            'AIClearTrainQueue(2);',
            'UnitIssueOrder(UnitGroupUnit(barracks, 1), combatOrder,',
            'UnitOrderIsValid(UnitGroupUnit(barracks, 1), combatOrder)',
            'p2_economy_combat_train_order_valid_before',
            'combatFallbackAbility = "P2MarineTrain";',
            'p2_economy_combat_train_fallback_valid',
            'p2_economy_combat_train_order_after_count',
            'p2_economy_marine_queued_after_order',
            'p2_economy_probe_barracks_train_',
            'p2_economy_probe_p2marine_train_',
                'c_orderQueueReplace);',
            'UnitTypePlacementFromPoint(',
            'UnitIssueOrder(worker,\n            OrderTargetingUnit(AbilityCommand("Smart", 0), resource),',
            'if ((UnitOrderCount(worker) > 0)',
        ]:
            assert required in computer_map_glue
        assert 'AISetStock(2, 12, "Marine");' not in computer_map_glue
        assert 'AISetStock(2, 8, "Marine");' in computer_map_glue
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
    assert "libVibeKernel_gv_initialized" not in overlay
    assert "InitMap" in overlay
    assert "single path" in overlay
    assert "InitMap();" in overlay
    assert 'UnitCreate(1, "Marine"' not in overlay
    assert "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_INITMAP_GUARD" in overlay
    assert "CMRE_ON_DEMAND_INITMAP_ENTERED_STATE" in overlay
    assert "gv_CmreOnDemandInitMapEntered" in overlay
    assert "if (gv_CmreOnDemandInitMapEntered) { return; }" in overlay
    assert 'libVibeKernel_gf_RegisterEntryPoints();' in overlay
    assert "registration belongs after the generated InitTriggers graph" in overlay
    assert 'stage16_before_vibe' in overlay
    assert 'stage16_after_vibe' in overlay
    assert 'CMRE trigger custom-script registration anchor not found' not in overlay
    assert "<InitFunc>cmre_on_demand_trigger_customscript_init</InitFunc>" in overlay
    assert "void cmre_on_demand_trigger_customscript_init()" in overlay
    assert 'LastIndexOf("</Library>"' in overlay
    assert 'LastIndexOf($documentClose' in overlay


def test_malformed_vibe_bank_is_quarantined_only_when_sc2_is_not_running():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    body = _function_body(overlay, "Initialize-CmreRuntimeListenerBank")

    assert '$vibeDocument.Load($vibeBankFile)' in body
    assert 'Get-Process -Name "SC2_x64", "SC2", "SC2Switcher_x64", "SC2Switcher"' in body
    assert 'GalaxyVibe bank is malformed but will not be repaired while SC2 is active' in body
    assert '[System.IO.File]::Replace($replacementPath, $vibeBankFile, $backupPath)' in body
    assert '[bank-recovery] quarantined malformed GalaxyVibe bank' in body
    assert '$vibeBankFile.invalid-$stamp-' in body


def test_launcher_never_auto_kills_unowned_sc2_processes():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    start = source.index("if (-not $NoLaunch -and -not $SecondaryClient)")
    end = source.index("$sc2RuntimeLeaseSession", start)
    preflight = source[start:end]

    assert "WebUI performs its own fail-closed cleanup only after it validates" in preflight
    assert 'throw (Format-Sc2RuntimeBusyMessage -Processes $existing -Lease $currentLease)' in preflight
    assert 'Stop-Process -Id $p.Id -Force' not in preflight


def test_player_mode_launches_direct_map_from_gamelog_signal():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    core_overlay = CORE_OVERLAY.read_text(encoding="utf-8-sig")
    map_load_body = _function_body(source, "Wait-CmreGameLogMapLoadSignal")
    assert 'SC2 direct-map mode: launching SC2Switcher_x64.exe' in source
    assert 'Wait-CmreGameLogMapLoadSignal' in source
    assert '*Alert*.txt' in source
    assert 'new ScriptError detected' in map_load_body
    assert 'return "ScriptError"' not in map_load_body
    assert 'Direct SC2 map launch must use Maps\\\\$MapName' in source
    assert 'guard empty hero structure unit type' in core_overlay
    assert '-loadmap `"$liveMap`"' not in source
    assert '$args = @("`"$liveMap`"")' not in source


def test_runtime_listener_gate_uses_map_requirements_for_optional_player_checks():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    wait_body = _function_body(source, "Wait-CmreRuntimeListener")

    assert '$requireBuildingP1 = $mapPreventDefeatPlayers -contains 1' in wait_body
    assert '$requireBuildingP2 = $mapPreventDefeatPlayers -contains 2' in wait_body
    assert '$requireUnitsP1 = $mapStartingUnitsPlayers -contains 1' in wait_body
    assert '$requireUnitsP2 = $mapStartingUnitsPlayers -contains 2' in wait_body
    assert '$buildingReady = ((-not $requireBuildingP1) -or ($buildingReadyP1 -gt 0)) -and' in wait_body
    assert '$unitsReady = ((-not $requireUnitsP1) -or ($unitsReadyP1 -gt 0)) -and' in wait_body
    assert '($unitsReadyP1 -gt 0) -and ($unitsReadyP2 -gt 0)' not in wait_body
    assert 'Last snapshot:' in wait_body


def test_direct_map_api_mode_attaches_before_runtime_listener_gate():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    direct_map_start = source.index("        if ($DirectMapApi) {")
    direct_map_end = source.index("        } else {", direct_map_start)
    direct_map_body = source[direct_map_start:direct_map_end]

    assert "[switch]$DirectMapApi" in source
    assert '"-DirectMapApi 必须配合 -ListenPort <port> 使用"' in source
    assert "DirectMapApi cannot be combined with -DebugMode or -ApiMinimal" in source
    assert "SC2 direct-map + API mode" in source
    assert "Wait-CmreGameLogMapLoadSignal -Since $launchStartedAt" in source
    listener_calls = re.findall(r"Wait-CmreRuntimeListener -TimeoutSeconds (\d+)", source)
    assert listener_calls and max(map(int, listener_calls)) >= 120
    assert "--join-existing topology" in direct_map_body
    assert "Wait-CmreRuntimeListener" not in direct_map_body
    assert "Host must attach with --join-existing" in source
    assert "--join-existing" in source
    assert '"-listen", "127.0.0.1", "-port", "$ListenPort", "-debug"' in source
    assert "function Send-CmreRebornLoadingConfirm" in source
    assert "sent Enter to SC2" in source
    assert "Send-CmreRebornLoadingConfirm -ProcessId $runtimePid" in source
    assert "-Attempts 6 -RetryDelayMilliseconds 2000 -StopWhenRuntimeListenerStarts" in source
    assert "[int]$Attempts = 1" in source
    assert "Get-CmreRuntimeBankInt -Key \"runtime_listener_started\"" in source
    assert "Get-CmreRuntimeBankInt -Key \"initialization_complete\"" in source
    assert "keep clicking until the full initialization gate is complete" in source
    assert "if ($attempt -gt 1 -and $listenerStarted -gt 0" in source
    assert "initialization complete after confirmation input" in source
    assert "stopping retries" in source
    assert "GetForegroundWindow" in source
    assert "public static uint SendEnter()" in source
    assert "SendEnter()" in source
    assert "using System.Text;" in source
    assert "SendVirtualKey(0x20)" in source
    assert "sent Space to SC2" in source
    assert "public ulong unionPadding" in source
    assert "SendLoadingClick" in source
    assert "FindWindowByClass" in source
    assert '"D3DProxyWindow"' in source
    assert "sent same-process D3D proxy input" in source
    assert "mouse_event" in source
    assert "PostMessage" in source
    assert "clicked continuation strip" in source
    assert "hidden top-level D3DProxyWindow" in source
    assert "(!IsWindowVisible(hWnd) && !isD3DProxy)" in source
    assert "score = IsWindowVisible(hWnd) ? 200 : 100;" in source


def test_reborn_loading_patch_preserves_mission_kind_and_only_disables_wait():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _function_body(source, "Patch-RebornCampaignLoadingConfirm")

    assert "Base.SC2Data\\TriggerLibs\\SwarmCampaignLib.galaxy" in body
    assert "optional call" in body
    assert "Split-Path -Leaf $MapPath" in body
    assert "no Swarm campaign map id" not in body
    assert "CMRE_REBORN_SKIP_LOADING_CONFIRM_V1" in body
    assert "lv_waitForKey = false;" in body
    assert "CMap.Kind=Mission" in body
    assert "CMap.Kind=Story" not in body
    assert "expected one waitForKey anchor" in body
    assert "Patch-RebornCampaignLoadingConfirm -MapPath $liveMap" in source


def test_reborn_loading_patch_runs_after_campaign_library_is_staged():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    copy_index = source.index("Patch-RebornLibraryInit -Sc2Root $Sc2Root -MapPath $liveMap")
    loading_index = source.index("Patch-RebornCampaignLoadingConfirm -MapPath $liveMap")
    owner_index = source.index("Patch-RebornMapPlayerOwnerBounds -MapPath $liveMap")

    assert copy_index < loading_index < owner_index
    assert "SwarmCampaignLib.galaxy" in source
    assert "TriggerLibs" in source


def test_overlay_assets_hold_galaxy_fragments_outside_launcher():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    core_overlay = CORE_OVERLAY.read_text(encoding="utf-8-sig")
    assert "Install-CmrePreselectedCommanderStartupOverlay" in overlay
    assert "Install-CmreObserverOverlay" in overlay
    assert "Install-CmreCoreRuntimeErrorOverlay" in core_overlay
    assert "deterministic offsets inside the uniquely named trigger function" in core_overlay
    assert "[regex]::Replace($comi, $comiAnchor10, $comiPatch10)" not in core_overlay
    assert "$functionIndex10 = $comi.IndexOf($comiFunction10" in core_overlay

    required_assets = [
        ASSETS / "startup" / "player-commander.galaxy.tpl",
        ASSETS / "startup" / "preselected-commander-startup.galaxy.tpl",
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

    preselected_startup = (ASSETS / "startup" / "preselected-commander-startup.galaxy.tpl").read_text(encoding="utf-8-sig")
    player_commander = (ASSETS / "startup" / "player-commander.galaxy.tpl").read_text(encoding="utf-8-sig")
    map_glue = (ASSETS / "map-glue.dead-of-night.galaxy").read_text(encoding="utf-8-sig")
    default_tail = (ASSETS / "startup" / "tail.default.galaxy").read_text(encoding="utf-8-sig")
    headless_tail = (ASSETS / "startup" / "tail.headless.galaxy").read_text(encoding="utf-8-sig")

    assert "CMRE_ON_DEMAND_PRESELECTED_COMMANDER_STARTUP" in preselected_startup
    assert "CMUIX_StartupApplySavedConfiguration" not in preselected_startup
    assert "CommanderSelectionScreen" not in preselected_startup
    assert "{{P1_COMMANDER_SETUP}}" in preselected_startup
    assert "{{P2_COMMANDER_SETUP}}" in preselected_startup
    assert "{{PLAYER}}" in player_commander
    assert "{{COMMANDER}}" in player_commander
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


def test_initialization_gate_writes_honest_markers_not_a_tautology():
    """EVAL-020: the gate must not restate one boolean as five green markers.

    Before the fix, gt_CmreOnDemandInitializationGate_Func wrote
    initialization_building_ready_p1/p2, initialization_units_ready_p1/p2 and
    initialization_complete = 1 in one unconditional block. When the launch
    profile omitted CreateStartingUnitsP1 / EnsurePreventDefeatP1 the readiness
    helper skipped every P1 ownership check, so those markers asserted nothing
    yet reported all-green - and Stage 6 attempt-3 ran 192k loops on an empty
    faction. The honest gate must gate each marker on the check it stands for
    and emit an explicit checks-skipped witness.
    """

    gate = (ASSETS / "startup" / "initialization-gate.galaxy").read_text(encoding="utf-8-sig")

    # The per-check markers are now conditional on the profile int that decides
    # whether the underlying check runs at all.
    assert 'if (lv_ensureP1 != 0) {' in gate
    assert 'if (lv_createP1 != 0) {' in gate
    assert 'initialization_units_ready_p1", 0' in gate
    assert 'initialization_building_ready_p1", 0' in gate

    # The short-circuit is now observable instead of laundered into green.
    assert "initialization_checks_skipped_p1" in gate
    assert "initialization_checks_skipped_p2" in gate

    # Regression guard: the old tautological block wrote units_ready_p1 = 1
    # with no preceding profile-int guard. Make sure no marker is written 1
    # without the guarding branch by checking the guards precede each write.
    p1_units_one = gate.find('initialization_units_ready_p1", 1')
    p1_create_guard = gate.find('if (lv_createP1 != 0) {')
    assert p1_units_one > p1_create_guard > 0, "units_ready_p1=1 must sit inside the createP1 branch"


def test_webui_preselected_startup_is_the_default_non_selection_path():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    map_lib = (ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Maps" / "亡者之夜.SC2Map" / "Base.SC2Data" / "LibCOOC.galaxy").read_text(encoding="utf-8-sig")

    assert "ShowSelectionUI" not in source
    top_level_params = source.splitlines()[1]
    assert "[Parameter(Mandatory = $true)][string]$Commander" in top_level_params
    assert "[switch]$EnableReborn" in top_level_params
    assert "[string]$RebornCommander" in top_level_params
    assert '$Commander = "Empire"' not in source
    assert "CMRE Alenger selection:" not in source
    assert "CMRE preselected startup:" in source
    assert "Enable-CmrePreselectedCommanderStartup" in source
    assert "Enable-CmrePreselectedCommanderStartup -MapPath $liveMap -Commander $Commander" in source
    assert "Enable-CmreSavedProfileStartup" not in source
    assert "Install-CmrePreselectedCommanderStartupOverlay" in overlay
    assert "Install-CmreSavedProfileStartupOverlay" not in overlay
    assert "ShowSelectionUI" not in overlay
    assert "CommanderSelectionScreen" not in map_lib
    assert "libCMFE_gf_CMUIX_StartupApplySavedConfiguration" not in map_lib
    assert "CMRE_ON_DEMAND_PRESELECTED_COMMANDER_STARTUP" in map_lib
    assert 'libCOOC_gf_CC_PlayerCommanderSet(1, "TerranAlenger3");' in map_lib
    assert 'libCOOC_gf_CC_PlayerCommanderSet(2, "TerranAlenger3");' in map_lib
    assert "CMRE_ON_DEMAND_FIXED_EMPIRE_STARTUP" not in map_lib
    assert "CMRE_ON_DEMAND_NO_COMMANDER_SELECTION" in overlay
    assert "CommanderSelectionScreen" in overlay
    assert "Assert-CmreCommanderSelectionRemoved" in overlay
    assert "directOnlyStartupPattern" in overlay
    assert "Join-Path $baseData \"LibCOOC.galaxy\"" in overlay
    assert "Join-Path $MapPath \"MapScript.galaxy\"" in overlay
    assert 'Join-Path $WorkspaceRoot "src\\projects\\cmre-porting\\packages\\Maps\\$MapName\\Base.SC2Data"' in overlay
    assert 'Copy-CmreOverlayFiles -Files $vibeKernelFiles -DestinationRoot $baseData' in overlay
    assert "Replace('include \"LibVibeKernel_h\"', 'include \"LibVibeKernel\"')" in overlay
    assert "declarations but no implementations" in overlay
    assert "'CommanderSelectionScreen'," in overlay
    assert "libCMFE_gf_CMUIX_StartupApplySavedConfiguration" in overlay


def test_cmre_runtime_has_no_remaining_commander_selection_entrypoint():
    core_lib = (ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Mods" / "CMRE" / "CMRE_Core_Triggers.SC2Mod" / "Base.SC2Data" / "LibCOOC.galaxy").read_text(encoding="utf-8-sig")
    cmui_customization = (ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Mods" / "CMRE" / "CMRE_Core_Triggers.SC2Mod" / "Base.SC2Data" / "scripts" / "cmui_customization.galaxy").read_text(encoding="utf-8-sig")

    direct_start = core_lib.index("// CMRE_DIRECT_MAP_STARTUP_ONLY")
    direct_end = core_lib.index("    return ;", direct_start)
    direct_startup = core_lib[direct_start:direct_end]
    assert "libCOOC_gf_CC_DevStartupFinish();" in direct_startup
    for forbidden in [
        "CommanderSelectionScreen",
        "CMUIX_StartupApplySavedConfiguration",
        "CMUIX_ReadyBeginCountdown",
        'TriggerSendEvent("CU_CommChoiceEventClosed")',
    ]:
        assert forbidden not in direct_startup

    startup_trigger = _galaxy_function_body(
        cmui_customization, "libCMUI_gt_ScreenCoopInitial_Func"
    )
    rebuild = _galaxy_function_body(cmui_customization, "CMUIX_RebuildLauncherUIForPlayer")
    for body in [startup_trigger, rebuild]:
        assert "CMRE_COMMANDER_SELECTION_UI_DISABLED" in body
        for forbidden in [
            "CommanderSelectionScreen",
            "CMUIX_SetCommanderSelectionUIActive",
            "CMUIX_StartupApplySavedConfiguration",
            "CMUIX_ReadyBeginCountdown",
        ]:
            assert forbidden not in body
    assert "return true;" in startup_trigger
    assert "return false;" in rebuild


def test_map_script_overlay_uses_available_cmre_library_anchors():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")

    assert "function Select-CmreExistingAnchor" in overlay
    assert "'include \"LibCOUI\"'" in overlay
    assert "'include \"LibCOOC\"'" in overlay
    assert "'include \"LibCOMI\"'" in overlay
    assert "'    libCOUI_InitLib();'" in overlay
    assert "'    libCOOC_InitLib();'" in overlay
    assert "'    libCOMI_InitLib();'" in overlay


def test_generic_map_glue_uses_valid_galaxy_start_offset_primitive():
    glue = (ASSETS / "map-glue.generic.galaxy").read_text(encoding="utf-8-sig")

    assert "PointWithOffsetPolar(lv_p1Start, 25.0, 45.0)" in glue
    assert "PointWithPolarProjection" not in glue


def test_reborn_headless_path_skips_only_campaign_cinematic():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    overlay = OVERLAY.read_text(encoding="utf-8-sig")

    assert "Install-CmreRebornCampaignIntroSkipOverlay -MapPath $liveMap" in source
    assert "CMRE_REBORN_SKIP_CAMPAIGN_INTRO" in overlay
    assert "TriggerExecute(gt_IntroCinematic, true, true);" in overlay
    assert "TriggerExecute(gt_IntroCinematicEnd, true, true);" in overlay
    assert "gv_introCinematicCompleted = false;" in overlay
    assert "map has no intro completion state to reset" in overlay
    assert "bool\\s+gv_introCinematicCompleted" in overlay
    assert "Preserve campaign setup and cleanup" in overlay
    assert "CMRE_REBORN_DEFER_PLAYABLE_STARTUP" not in overlay
    assert "TriggerAddEventTimeElapsed(gt_IntroQ, 0.0, c_timeGame);" not in overlay
    assert "Keep the map's original intro queue timing" in overlay
    assert "Install-CmreRebornCampaignFrontendGuardOverlay -MapPath $liveMap" in source
    assert "CMRE_REBORN_CAMPAIGN_FRONTEND_GUARD" in overlay
    assert 'libSwaC_gf_ULoadCampaignData("ZChar1");' in overlay
    assert 'libSwaC_gf_PurchaseStorymodeTech();' in overlay
    assert "CampaignMode/CampaignProgress UI services" in overlay
    assert "campaignDataPattern" in overlay
    assert "function Install-CmreRebornStandaloneCatalogGuard" in overlay
    assert "CMRE_REBORN_STANDALONE_CATALOG_PLAYER_GUARD" in overlay
    assert "EventPlayer()" in overlay
    assert "Install-CmreRebornStandaloneCatalogGuard -MapPath $liveMap" in source


def test_reborn_library_black_screen_patch_uses_declared_swarm_api():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "libSwaC_gf_ShowHideWorldCover(false, 0.0);" in source
    assert "libCOOC_gf_ShowHideWorldCover(false, 0.0, 1);" not in source


def test_reborn_library_keeps_native_map_init_and_swarm_setup_path():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "CMRE_PATCH_DEFERRED_INITIALIZATION" not in source
    assert "TriggerAddEventTimeElapsed(lib48DF4533_gt_Initialization, 0.0, c_timeGame);" not in source
    assert "TriggerAddEventMapInit(lib48DF4533_gt_Initialization);" in source
    assert "CMRE_PATCH_REBORN_DEFERRED_STARTUP_V6" in source
    assert "TriggerAddEventTimePeriodic(gt_CmreRebornDeferredStartup, 1.0, c_timeReal);" in source


def test_startup_contract_is_fail_closed_and_protects_map_owned_player_objects():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "map-startup-contract.json" in source
    assert "Startup contract hash mismatch" in source
    assert "Startup contract has no record" in source
    assert "$protectedMapUnitTypes = @($startupRecord.adaptation.protectedPlayerUnitTypes)" in source
    assert "$vanillaRemovals = @($vanillaRemovals | Where-Object" in source


def test_reborn_commander_start_receives_transient_source_units():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "CMRE_PATCH_K5KERRIGAN_SOURCE_HELPER_V3" in source
    assert "lib48DF4533_gf_CMREProvisionCommanderStartSources" in source
    assert "wired source helper before CommanderStart" in source
    assert "K5Kerrigan injection skipped" not in source
    assert "c_targetFilterPreventDefeat" in source
    assert 'UnitGroup("Hatchery", lv_player' in source
    assert 'k5kerrigan_source_provisioned_p' in source


def test_reborn_commander_start_is_contract_driven():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "rebornReplacementContract" in source
    assert "rebornReplacementTargetTypes" in source
    assert "Startup contract has no Reborn CommanderStart replacement contract" in source
    assert "Startup contract has no Reborn CommanderStart target unit types" in source


def test_reborn_deferred_start_only_requires_start_points_for_created_units():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "$requiredStartPlayers = @($mapStartingUnitsPlayers | Sort-Object -Unique)" in source


def test_reborn_deferred_start_uses_existing_prevent_defeat_as_start_witness():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "lv_p1PreventDefeat" in source
    assert "c_targetFilterPreventDefeat" in source
    assert "UnitGetPosition(lv_existingStartUnit)" in source


def test_reborn_adapter_runs_after_native_swarm_setup():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "TriggerExecute(lib48DF4533_gt_SwarmSetup, false, false);" in source
    assert "libRebornAdapter_gf_InitializeBeforeSwarmSetup(" in source
    assert "adapter can reuse its base/workers" in source


def test_reborn_overlay_disables_cmre_p2_melee_fallback():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    assert "(-not $EnableReborn)" in overlay
    assert "Running CMRE's fallback MeleeInitUnitsForPlayer(2)" in overlay


def test_reborn_overlay_patches_bridge_start_point_fallback():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "CMRE_REBORN_START_POINT_FALLBACK_V1" in overlay
    assert "Reborn start-point fallback applied to staged LibMapModBridge" in overlay
    assert "Galaxy requires local declarations to precede executable statements." in overlay
    assert "$bridgeFunctionAnchor = 'void libMapModBridge_gf_CreateStartingUnits" in overlay
    assert "+ [char]123" in overlay
    assert "$bridgeAnchor = '    int lv_reused = 0;'" in overlay
    assert "$bridgeFallbackDeclarations" in overlay
    assert "$bridgeFallbackProbe" in overlay
    assert "TriggerExecute(gt_CmreRebornDeferredStartup, false, true);" in source
    assert "gt_CmreRebornDeferredStartup_Init();" in source


def test_reborn_library_init_matches_crlf_swarm_setup_tail():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "$swarmSetupEndPattern" in source
    assert r"\r?\n" in source
    assert "[regex]::Matches($content, $swarmSetupEndPattern)" in source
    assert "expected exactly one SwarmSetup_Func end marker" in source
    assert "Contains($swarmSetupEndMarker)" not in source


def test_reborn_zerg_startup_does_not_inject_synthetic_tech_bundle():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    gate = (ASSETS / "startup" / "initialization-gate.galaxy").read_text(encoding="utf-8-sig")
    commanders = json.loads(
        (ROOT / "src" / "config" / "reborn-commanders.json").read_text(encoding="utf-8-sig")
    )["commanders"]
    zerg_commanders = {
        commander["id"]
        for commander in commanders
        if commander.get("race") == "Zerg"
    }

    assert zerg_commanders == {
        "Abathur",
        "Dehaka",
        "Izsha",
        "Kerrigan",
        "Naktul",
        "Stukov",
        "Zagara",
    }
    assert "libRebornAdapter_gf_CreateZergStartingBuildings" not in source
    assert "zerg_starting_buildings_created_p1" not in gate
    assert "zerg_starting_buildings_created_p2" not in gate
    assert "libRebornAdapter_gf_UnlockAllZergUnits(1);" in source
    assert "libRebornAdapter_gf_UnlockAllZergUnits(2);" in source


def test_staged_invoke_bundle_disables_the_optional_funcref_table():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    body = _function_body(source, "Repair-CmreStagedInvokeBundle")

    assert "CMRE_VIBE_FUNCREF_TABLE_DISABLED" in body
    assert "$funcrefResolverPattern" in body
    assert "expected exactly one ResolveFuncref table" in body
    assert "return null;" in body


def test_reborn_staged_map_guards_invalid_achievement_owner_ids():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert "function Patch-RebornMapPlayerOwnerBounds" in source
    assert "CMRE_PATCH_PLAYER_OWNER_BOUNDS" in source
    assert "Patch-RebornMapPlayerOwnerBounds -MapPath $liveMap" in source


def test_reborn_startup_does_not_write_unstable_larva_button_fields():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert 'libRebornAdapter_gf_ForceEnableLarvaMorphButtons(1);' not in source
    assert 'libRebornAdapter_gf_ForceEnableLarvaMorphButtons(2);' not in source
    assert 'larva_morph_buttons_forced_p1", 0' in source


def test_reborn_zchar01_targets_all_enemy_owners_at_both_coop_players():
    glue = (ASSETS / "map-glue.reborn-zchar01.galaxy").read_text(encoding="utf-8-sig")
    overlay = OVERLAY.read_text(encoding="utf-8-sig")

    for player in [3, 4, 5, 6, 10, 11, 12]:
        assert f"AIAttackWaveSetTargetPlayer({player}, gv_CmreRebornZChar01CoopTargets);" in glue
        assert f"libNtve_gf_SetAlliance({player}, 1, libNtve_ge_AllianceSetting_Enemy);" in glue
        assert f"libNtve_gf_SetAlliance(1, {player}, libNtve_ge_AllianceSetting_Enemy);" in glue
        assert f"libNtve_gf_SetAlliance({player}, 2, libNtve_ge_AllianceSetting_Enemy);" in glue
        assert f"libNtve_gf_SetAlliance(2, {player}, libNtve_ge_AllianceSetting_Enemy);" in glue

    assert "CMRE_REBORN_ZCHAR01_SCRIPTED_TARGET_PATCH_V1" in overlay
    assert "gv_CmreRebornZChar01CoopTargets" in overlay
    assert "ZChar01 scripted target anchor not found" in overlay
    assert "TriggerAddEventTimePeriodic(gt_CmreRebornZChar01AllyGuard, 1.0, c_timeGame);" in glue


def test_reborn_zchar01_sets_coop_target_before_native_campaign_ai_starts():
    glue = (ASSETS / "map-glue.reborn-zchar01.galaxy").read_text(encoding="utf-8-sig")
    start = glue.index("void gf_CmreRebornZChar01StartAI()")
    end = glue.index("void gf_CmreRebornZChar01StartEnemyWaves()", start)
    body = glue[start:end]

    assert "PlayerType(2) == c_playerTypeComputer" in body
    assert "gt_CmreOnDemandComputerAllyReady_Func(false, true);" in body
    assert "gf_CmreRebornZChar01DisableP2EnemyWaves();" in body
    alliance_index = body.index("gf_CmreRebornZChar01SetCoopAlliances();")
    first_target_index = body.index("gf_CmreRebornZChar01RetargetEnemyAI();")
    first_campaign_index = body.index("AICampaignStart(3);")
    last_target_index = body.rindex("gf_CmreRebornZChar01RetargetEnemyAI();")

    init_index = body.index("gt_CmreOnDemandComputerAllyReady_Func(false, true);")
    disable_waves_index = body.index("gf_CmreRebornZChar01DisableP2EnemyWaves();")
    assert init_index < alliance_index < disable_waves_index < first_campaign_index
    assert first_target_index < first_campaign_index
    assert last_target_index > first_campaign_index


def test_reborn_zchar01_skips_original_p2_enemy_waves_for_computer_ally():
    glue = (ASSETS / "map-glue.reborn-zchar01.galaxy").read_text(encoding="utf-8-sig")
    start = glue.index("void gf_CmreRebornZChar01StartEnemyWaves()")
    end = glue.index("bool gt_CmreRebornZChar01AllyGuard_Func", start)
    body = glue[start:end]

    assert "if (PlayerType(2) != c_playerTypeComputer)" in body
    assert "PlayerGroupAlliance(c_playerGroupAlly, 1)" not in body


def test_staged_map_glue_replaces_stale_generated_blocks():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")

    assert "function Replace-CmreBlockBetweenMarkers" in overlay
    assert '"// CMRE_ON_DEMAND_MAP_GLUE"' in overlay
    assert '"// CMRE_ON_DEMAND_INITMAP_ENTERED_STATE"' in overlay
    assert '"// CMRE_REBORN_ZCHAR01_ALLY_GUARD"' in overlay
    assert 'Name "CMRE map glue"' in overlay
    assert 'Name "ZChar01 ally glue"' in overlay


def test_reborn_zchar01_start_hooks_have_forward_declarations():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")

    assert "CMRE_REBORN_ZCHAR01_FORWARD_DECLS_V1" in overlay
    assert "void gf_CmreRebornZChar01StartAI();" in overlay
    assert "void gf_CmreRebornZChar01StartEnemyWaves();" in overlay


def test_initialization_gate_accepts_native_reborn_direct_startup():
    gate = (ASSETS / "startup" / "initialization-gate.galaxy").read_text(encoding="utf-8-sig")

    assert "lv_rebornDirectReady" in gate
    assert 'gf_CmreOnDemandDebugInt("initlib_patch_ran")' in gate
    assert 'gf_CmreOnDemandDebugInt("reborn_adapter_initialized")' in gate
    assert "startup_dev_finish" in gate


def test_native_computer_catalog_overlay_restores_marine_before_map_load():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    body = _function_body(overlay, "Install-CmreNativeComputerCatalogOverlay")

    assert "Install-CmreNativeComputerCatalogOverlay -Sc2Root $Sc2Root" in source
    assert "Install-CmreNativeComputerMapCatalogOverlay -MapPath $liveMap" in source
    assert "CMRE_Core_Base.SC2Mod\\Base.SC2Data\\GameData\\AbilData.xml" in body
    assert "/Catalog/CAbilTrain[@id='BarracksTrain']" in body
    assert "./InfoArray[@index='Train1']" in body
    assert 'SetAttribute("value", "Marine")' in body
    assert 'SetAttribute("removed", "1")' in body
    assert 'SetAttribute("Time", "25")' in body
    assert 'SetAttribute("State", "Available")' in body
    assert 'SetAttribute("Requirements", "")' in body
    assert "Native Computer catalog overlay verification failed" in body
    map_body = _function_body(overlay, "Install-CmreNativeComputerMapCatalogOverlay")
    assert "/Catalog/CAbilTrain[@id='P2MarineTrain']" in map_body
    assert 'SetAttribute("parent", "BarracksTrain")' not in map_body
    assert 'SetAttribute("value", "Marine")' in map_body
    assert 'SetAttribute("index", "UnitOrderQueue")' in map_body
    assert "UnitData.xml" in map_body
    assert "AbilArray[@Link='BarracksTrain']" in map_body
    assert "TechTreeProducedUnitArray[@value='Marine']" in map_body
    assert "LayoutButtons[@AbilCmd='BarracksTrain,Train1']" in map_body
    assert "AbilArray[@Link='P2MarineTrain']" in map_body
    assert "LayoutButtons[@AbilCmd='P2MarineTrain,Train1']" in map_body
    assert 'SetAttribute("AbilCmd", "P2MarineTrain,Train1")' in map_body
    assert "Barracks does not link P2MarineTrain" in map_body
    assert "Barracks does not link BarracksTrain" in map_body
    assert "Barracks does not produce Marine" in map_body
    assert "Barracks does not expose native Marine card" in map_body
    assert "Barracks does not expose P2MarineTrain card" in map_body
    assert 'SetAttribute("State", "Available")' in map_body
    assert "Install-CmreNativeComputerMapCatalogOverlay" in overlay
    assert "UnitIssueOrder(UnitGroupUnit(barracks, 1), combatOrder" in (
        (ASSETS / "map-glue.dead-of-night.galaxy").read_text(encoding="utf-8-sig")
    )


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


def test_secondary_client_is_not_rejected_by_primary_foreign_sc2_guard():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "if (-not $SecondaryClient -and (Get-Date) -gt $foreignDeadline" in source


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


def test_observer_overlay_mounts_invoke_bundle_with_rollout_tiers():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    body = _function_body(overlay, "Install-CmreObserverOverlay")

    # kernel 文件清单包含句柄登记表，bundle 扇平拷入 Base.SC2Data
    assert "LibVibeHandles.galaxy" in body
    assert 'generated\\$MapName' in body
    assert "LibVibeInvokeDispatch.galaxy" in body
    # MapScript include 注入：kernel 之后挂载句柄表/公共库/分片/分派
    assert "'include \"LibVibeHandles\"', 'include \"LibVibeInvokeCommon\"'" in overlay
    assert "'include \"LibVibeInvokeDispatch\"'" in overlay
    assert 'Add-CmreLinesAfter -Content $mapScript -Anchor \'include "LibVibeKernel"\' -Lines $vibeInvokeIncludes' in overlay
    # 分档放量：InvokeTier 参数、tier dispatch 变体改名、超档分片跳过
    assert "[int]$InvokeTier = 0" in body
    assert "[switch]$InvokeFull" in body
    assert "$mountGeneratedInvokeBundle = $InvokeFull -or $InvokeTier -gt 0" in body
    assert "LibVibeInvokeDispatch_tier" in body
    assert "Invoke tier $InvokeTier dispatch variant missing" in body
    assert "if (-not $InvokeFull -and ((([int]$Matches[1] - 1) * 400) + 1) -gt $InvokeTier) { continue }" in body


def test_reborn_observer_overlay_triggers_deferred_startup_from_initmap():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    body = _function_body(overlay, "Install-CmreObserverOverlay")

    assert "$initTriggerLines = @(" in body
    assert "if ($EnableReborn)" in body
    assert "TriggerExecute(gt_CmreRebornDeferredStartup, false, true);" in body
    assert "InitMap is the reliable post-bootstrap owner" in body
    assert "gt_CmreOnDemandInitializationGate_Init();" in body
    assert body.index("TriggerExecute(gt_CmreRebornDeferredStartup, false, true);") < body.index("gt_CmreOnDemandInitializationGate_Init();")


def test_non_cmre_maps_skip_cmre_owned_computer_ally_economy():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    body = _function_body(overlay, "Install-CmreObserverOverlay")

    assert '$cmreMapSource = Join-Path $WorkspaceRoot "src\\projects\\cmre-porting\\packages\\Maps\\$MapName"' in body
    assert "$enableCmreComputerAllyEconomy = (-not $EnableReborn) -and" in body
    assert 'CMRE computer ally economy: skipped for non-CMRE map' in body
    assert 'gt_CmreOnDemandComputerAllyReady_Init();' in body


def test_reborn_k5_structures_guard_rejects_invalid_event_player():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "CMRE_PATCH_REBORN_K5_STRUCTURES_PLAYER_GUARD_V1" in source
    assert "if (EventPlayer() < 1 || EventPlayer() > 15)" in source
    assert "K5StructuresComplete player guard anchor not found" in source


def test_reborn_commander_start_commits_transient_source_units_before_consuming_them():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "CMREProvisionCommanderStartSources();" in source
    assert "Wait(0.1, c_timeGame);" in source
    assert 'UnitCreate(1, "K5Kerrigan", c_unitCreateIgnorePlacement' in source
    assert "k5kerrigan_source_count_before_commander_start" in source
    assert "k5kerrigan_source_count_after_commander_start" in source
    assert "source-unit commit wait before CommanderStart" in source

    # Both the source-sync patch and the staged-map repair must preserve the
    # same ordering: create source -> yield to the game -> CommanderStart.
    assert source.count("$sourceCommitWait = '    Wait(0.1, c_timeGame);'") == 2
    assert source.count("$sourceHelperCall + $newline + $sourceCommitWait") == 2


def test_reborn_commander_start_targets_ignore_placement_and_preserves_hunterkiller():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "function Patch-RebornCommanderStartUnitHandling" in source
    assert "c_unitCreateIgnorePlacement" in source
    assert "function Patch-RebornReplaceExistingUnits" in source
    assert "CMRE_PATCH_REBORN_EXCLUDE_HUNTERKILLER_FROM_HYDRALISK_V1" in source
    assert "Patch-RebornReplaceExistingUnits -Content $content" in source
    assert "hunterkiller_count_after_commander_start" in source
    assert "hunterkiller_count_after_replace_existing_units" in source
    assert "hydraliskimpaler_count_after_replace_existing_units" in source


def test_reborn_deferred_startup_locks_before_adapter_and_swarmsetup():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    deferred = source[source.index("CMRE_PATCH_REBORN_DEFERRED_STARTUP_V6") :]

    guard = deferred.index("gv_CmreRebornDeferredStartupStarted = true;")
    call = deferred.index("libRebornAdapter_gf_InitializeBeforeSwarmSetup(")
    swarm = deferred.index("TriggerExecute(lib48DF4533_gt_SwarmSetup, false, false);")
    assert guard < swarm < call
    assert 'reborn_adapter_initialize_call_count", 1' in deferred


def test_observer_overlay_keeps_stage26_bundle_out_of_default_webui_launches():
    overlay = OVERLAY.read_text(encoding="utf-8-sig")
    body = _function_body(overlay, "Install-CmreObserverOverlay")

    assert "generated invoke bundle disabled (InvokeTier=0)" in body
    assert '"startup\\invoke-disabled.galaxy"' in body
    assert '"LibVibeInvokeDisabled.galaxy"' in body
    assert 'include "LibVibeInvokeDisabled"' in body
    assert 'Get-ChildItem -LiteralPath $baseData -Filter "LibVibeInvoke*.galaxy"' in body
    assert "if ($mountGeneratedInvokeBundle -and (Test-Path -LiteralPath $vibeInvokeBundle))" in body
    assert "if ($mountGeneratedInvokeBundle -and (Test-Path -LiteralPath $vibeInvokeBundleDir))" in body

    stub = (ASSETS / "startup" / "invoke-disabled.galaxy").read_text(encoding="utf-8-sig")
    assert "CMRE_ON_DEMAND_INVOKE_DISABLED" in stub
    assert "string libVibeInvoke_gf_Dispatch(int functionId, string argsJson)" in stub
    assert '"FUNCTION_NOT_IN_MAP"' in stub


def test_launcher_top_level_passes_invoke_tier_to_observer_overlay():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    # Stage 26 分档放量：顶层参数声明 + 透传给 Install-CmreObserverOverlay
    assert "[int]$InvokeTier = 0, [switch]$InvokeFull)" in source
    assert "-VibeKernelOverride $VibeKernelOverride -InvokeTier $InvokeTier -InvokeFull:$InvokeFull" in source
    assert "-InvokeFull cannot be combined with -InvokeTier > 0" in source


def test_launcher_repairs_generated_invoke_bundle_against_staged_closure():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "Repair-CmreStagedInvokeBundle -MapPath $MapPath" in source
    assert '"tools\\galaxy-vibe\\mpq\\staged_map_doctor.py"' in source
    assert "& $python $doctor $MapPath --fix" in source
