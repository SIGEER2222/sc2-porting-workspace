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

    startup_body = _function_body(source, "Enable-CmreFixedCommanderStartup")
    observer_body = _function_body(source, "Install-CmreDynamicObserver")
    core_body = _function_body(source, "Patch-CmreCoreRuntimeErrors")

    for body in [startup_body, observer_body, core_body]:
        assert "[regex]::Replace" not in body
        assert "WriteAllText" not in body
        assert "WriteAllBytes" not in body
        assert "CMUIX_ReadyBeginCountdown();" not in body
        assert 'TriggerSendEvent("CU_CommChoiceEventClosed")' not in body
        assert "GameSetMissionTimePaused(true)" not in body

    assert "Install-CmreFixedCommanderStartupOverlay" in startup_body
    assert "Install-CmreObserverOverlay" in observer_body
    assert "Install-CmreCoreRuntimeErrorOverlay" in core_body


def test_launcher_accepts_an_explicit_read_only_map_source():
    source = LAUNCHER.read_text(encoding="utf-8-sig")
    assert '[string]$MapSourceOverride = ""' in source
    assert "Resolve-Path -LiteralPath $MapSourceOverride" in source
    assert 'Join-Path $mapSource "MapScript.galaxy"' in source


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
    assert "sourceMapDependencies" in source
    assert "Merge-CmreMapDependencies" in source
    assert "file:Mods/reborn/crys_the_swarm_reborn.SC2Mod" in source
    assert "SwarmStory" in source
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
    assert "Wait-CmreRuntimeListener -TimeoutSeconds 120" in source
    assert "--join-existing topology" in direct_map_body
    assert "Wait-CmreRuntimeListener -TimeoutSeconds 120" not in direct_map_body
    assert "Host must attach with --join-existing" in source
    assert "--join-existing" in source
    assert '"-listen", "127.0.0.1", "-port", "$ListenPort", "-debug"' in source
    assert "function Send-CmreRebornLoadingConfirm" in source
    assert "sent Enter to SC2" in source
    assert "Send-CmreRebornLoadingConfirm -ProcessId $runtimePid" in source
    assert "GetForegroundWindow" in source
    assert "public static uint SendEnter()" in source
    assert "SendEnter()" in source
    assert "using System.Text;" in source
    assert "SendVirtualKey(0x20)" in source
    assert "sent Space to SC2" in source
    assert "public ulong unionPadding" in source
    assert "SendLoadingClick" in source
    assert "mouse_event" in source
    assert "PostMessage" in source
    assert "clicked continuation strip" in source


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
    assert "Install-CmreFixedCommanderStartupOverlay" in overlay
    assert "Install-CmreObserverOverlay" in overlay
    assert "Install-CmreCoreRuntimeErrorOverlay" in core_overlay
    assert "deterministic offsets inside the uniquely named trigger function" in core_overlay
    assert "[regex]::Replace($comi, $comiAnchor10, $comiPatch10)" not in core_overlay
    assert "$functionIndex10 = $comi.IndexOf($comiFunction10" in core_overlay

    required_assets = [
        ASSETS / "startup" / "fixed-empire-startup.galaxy",
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

    fixed_startup = (ASSETS / "startup" / "fixed-empire-startup.galaxy").read_text(encoding="utf-8-sig")
    map_glue = (ASSETS / "map-glue.dead-of-night.galaxy").read_text(encoding="utf-8-sig")
    default_tail = (ASSETS / "startup" / "tail.default.galaxy").read_text(encoding="utf-8-sig")
    headless_tail = (ASSETS / "startup" / "tail.headless.galaxy").read_text(encoding="utf-8-sig")

    assert "CMRE_ON_DEMAND_FIXED_EMPIRE_STARTUP" in fixed_startup
    assert fixed_startup.count('"Empire"') == 6
    assert "CMUIX_StartupApplySavedConfiguration" not in fixed_startup
    assert "CommanderSelectionScreen" not in fixed_startup
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
    map_lib = (ROOT / "src" / "projects" / "cmre-porting" / "packages" / "Maps" / "亡者之夜.SC2Map" / "Base.SC2Data" / "LibCOOC.galaxy").read_text(encoding="utf-8-sig")

    assert "ShowSelectionUI" not in source
    assert "[Parameter(Mandatory = $true)][string]$Commander" not in source.splitlines()[1]
    assert '$Commander = "Empire"' in source
    assert "Enable-CmreSavedProfileStartup" not in source
    assert "Install-CmreSavedProfileStartupOverlay" not in overlay
    assert "ShowSelectionUI" not in overlay
    assert "CommanderSelectionScreen" not in map_lib
    assert "libCMFE_gf_CMUIX_StartupApplySavedConfiguration" not in map_lib
    assert "CMRE_ON_DEMAND_FIXED_EMPIRE_STARTUP" in map_lib
    assert 'libCOOC_gf_CC_PlayerCommanderSet(1, "Empire");' in map_lib
    assert 'libCOOC_gf_CC_PlayerCommanderSet(2, "Empire");' in map_lib
    assert "CMRE_ON_DEMAND_NO_COMMANDER_SELECTION" in overlay
    assert "CommanderSelectionScreen" in overlay
    assert "Assert-CmreCommanderSelectionRemoved" in overlay
    assert "Join-Path $baseData \"LibCOOC.galaxy\"" in overlay
    assert "Join-Path $MapPath \"MapScript.galaxy\"" in overlay
    assert 'Join-Path $WorkspaceRoot "src\\projects\\cmre-porting\\packages\\Maps\\$MapName\\Base.SC2Data"' in overlay
    assert 'Copy-CmreOverlayFiles -Files $vibeKernelFiles -DestinationRoot $baseData' in overlay
    assert "Replace('include \"LibVibeKernel_h\"', 'include \"LibVibeKernel\"')" in overlay
    assert "declarations but no implementations" in overlay
    assert "'CommanderSelectionScreen'," in overlay
    assert "libCMFE_gf_CMUIX_StartupApplySavedConfiguration" in overlay


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
    assert "Preserve campaign setup and cleanup" in overlay
    assert "CMRE_REBORN_DEFER_PLAYABLE_STARTUP" not in overlay
    assert "TriggerAddEventTimeElapsed(gt_IntroQ, 0.0, c_timeGame);" not in overlay
    assert "Keep the map's original intro queue timing" in overlay
    assert "Install-CmreRebornCampaignFrontendGuardOverlay -MapPath $liveMap" in source
    assert "CMRE_REBORN_CAMPAIGN_FRONTEND_GUARD" in overlay
    assert 'libSwaC_gf_ULoadCampaignData("ZChar1");' in overlay
    assert 'libSwaC_gf_PurchaseStorymodeTech();' in overlay
    assert "CampaignMode/CampaignProgress UI services" in overlay


def test_reborn_library_black_screen_patch_uses_declared_swarm_api():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "libSwaC_gf_ShowHideWorldCover(false, 0.0);" in source
    assert "libCOOC_gf_ShowHideWorldCover(false, 0.0, 1);" not in source


def test_reborn_library_keeps_native_map_init_and_swarm_setup_path():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    assert "CMRE_PATCH_DEFERRED_INITIALIZATION" not in source
    assert "TriggerAddEventTimeElapsed(lib48DF4533_gt_Initialization, 0.0, c_timeGame);" not in source
    assert "TriggerAddEventMapInit(lib48DF4533_gt_Initialization);" in source
    assert "TriggerExecute(lib48DF4533_gt_SwarmSetup, false, false);" in source


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
    assert "LibVibeInvokeDispatch_tier" in body
    assert "Invoke tier $InvokeTier dispatch variant missing" in body
    assert "if ($InvokeTier -gt 0 -and ((([int]$Matches[1] - 1) * 400) + 1) -gt $InvokeTier) { continue }" in body


def test_launcher_top_level_passes_invoke_tier_to_observer_overlay():
    source = LAUNCHER.read_text(encoding="utf-8-sig")

    # Stage 26 分档放量：顶层参数声明 + 透传给 Install-CmreObserverOverlay
    assert "[int]$InvokeTier = 0)" in source
    assert "-VibeKernelOverride $VibeKernelOverride -InvokeTier $InvokeTier" in source

