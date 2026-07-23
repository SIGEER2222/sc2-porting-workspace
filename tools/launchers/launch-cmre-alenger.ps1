[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$MapName, [Parameter(Mandatory = $true)][string]$Commander, [switch]$DryRun, [switch]$NoLaunch, [int]$ListenPort = 0, [string]$LegacyRootOverride = "")
$ErrorActionPreference = "Stop"
$WorkspaceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Sc2WorkspaceRoot = Split-Path -Parent $WorkspaceRoot
if ($LegacyRootOverride) {
    $LegacyRoot = $LegacyRootOverride
} else {
    $LegacyRoot = Join-Path $Sc2WorkspaceRoot "合作指挥官-起义狂潮"
}
$AlengerPackagesRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\packages"
$Sc2Root = "E:\SC2\SC2new\StarCraft II"
$script:LauncherScriptsRoot = Join-Path $LegacyRoot "scripts\sc2-launcher"
. (Join-Path $script:LauncherScriptsRoot "common.ps1")
. (Join-Path $script:LauncherScriptsRoot "mod-sync.ps1")
. (Join-Path $script:LauncherScriptsRoot "map-sync.ps1")
. (Join-Path $script:LauncherScriptsRoot "document-dependencies.ps1")
. (Join-Path $script:LauncherScriptsRoot "test-lock.ps1")
. (Join-Path $LegacyRoot "scripts\commander-power-metadata.ps1")
. (Join-Path $LegacyRoot "scripts\sc2\campaignxcore-bank.ps1")

function Convert-TestCommanderToCommanderPowerKey {
    param([string]$Commander)
    return (Convert-CommanderPowerCommanderToBankKey -Commander $Commander -WorkspaceRoot $LegacyRoot)
}
$cmre = Get-Content -LiteralPath (Join-Path $WorkspaceRoot "src\config\cmre-alenger-dependencies.json") -Raw | ConvertFrom-Json
$alenger = Get-Content -LiteralPath (Join-Path $WorkspaceRoot "src\config\alenger-mods.json") -Raw | ConvertFrom-Json
if ($Commander -notmatch '^(Terran|Zerg|Protoss)(Alenger\d+)$') { throw "Commander must be a configured Alenger runtime ID: $Commander" }
$alengerId = $Matches[2]
if ($alenger.commanderToAlenger.PSObject.Properties.Name -notcontains $alengerId) { throw "No on-demand package mapping for $Commander" }
$mapSource = Join-Path $LegacyRoot "Maps\CMRE\$MapName"
if (-not (Test-Path -LiteralPath $mapSource)) { throw "CMRE map source not found: $mapSource" }
if ($MapName -ne "亡者之夜.SC2Map") { throw "No CMRE auto-launch profile is registered for $MapName" }
$selectedMods = @($alenger.commanderToAlenger.$alengerId)
$dependencies = @($cmre.baseDependencyPaths) + @($cmre.commanderBaseDependencyPaths) + @($selectedMods | ForEach-Object { "file:Mods/7vs1/$_.SC2Mod" })
Write-Host "CMRE Alenger selection: $MapName x $Commander"
Write-Host "On-demand packages: $($selectedMods -join ', ')"
if ($DryRun) { $dependencies | ForEach-Object { Write-Host "  $_" }; exit 0 }

function Enable-CmreSavedProfileStartup {
    param(
        [Parameter(Mandatory = $true)][string]$MapPath,
        [Parameter(Mandatory = $true)][string]$Commander
    )
    # Patch the map-level LibCOOC.galaxy (copied by Install-CmreGalaxyHostOverlay)
    # instead of the mod-source copy. The mod source is overwritten by Sync-ModSet
    # (robocopy /MIR) on every launch, which silently dropped the previous patch.
    # Patching the map copy after the host overlay guarantees the edit survives.
    $path = Join-Path $MapPath "Base.SC2Data\LibCOOC.galaxy"
    if (-not (Test-Path -LiteralPath $path)) { throw "Map-level LibCOOC.galaxy not found: $path" }
    $content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    # CMUIX_StartupApplySavedConfiguration() shows the commander selection UI when
    # CMUIX_LaunchProfileTryLoadForStartupAll() returns false. Bypass that call
    # entirely: manually run the core init steps, pre-set the requested commander
    # for players 1 and 2, then drive CMUIX_ReadyBeginCountdown() so its finish
    # handler emits CU_CommChoiceEventClosed and finalizes the commander state.
    $originalPattern = '(?m)^    if \(\(libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\) == true\)\) \{\r?\n        Wait\(1\.0, c_timeReal\);\r?\n        CMUIX_ReadyBeginCountdown\(\);\r?\n        return ;\r?\n    \}'
    $fallbackPattern = '(?m)^    if \(\(libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\) == true\)\) \{\r?\n        TriggerSendEvent\("CU_CommChoiceEventClosed"\);\r?\n        return ;\r?\n    \}'
    $legacyPatchPattern = '(?m)^    libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\);\r?\n    Wait\(1\.0, c_timeReal\);\r?\n    CMUIX_ReadyBeginCountdown\(\);\r?\n    return ;$'
    $replacementBody = @"
    if ((CMUIX_CoreReady == false)) { CMUIX_CoreInit(); }
    CMUIX_StartupLoadPersistentProfiles();
    CMUIX_HistoryPrunePendingRecordsAll();
    libCOTF_gv_sELECTED_Commander[1] = "$Commander";
    libCOTF_gv_sELECTED_Commander_Random[1] = false;
    libCOOC_gf_CC_PlayerCommanderSet(1, "$Commander");
    libCOUI_gv_cU_CommanderSelection[1] = "$Commander";
    libCOUI_gv_cU_CommanderSelect_PlayerReady[1] = true;
    libCOUI_gf_CU_CommanderFinalizeStates(1);
    libCOTF_gv_sELECTED_Commander[2] = "$Commander";
    libCOTF_gv_sELECTED_Commander_Random[2] = false;
    libCOOC_gf_CC_PlayerCommanderSet(2, "$Commander");
    libCOUI_gv_cU_CommanderSelection[2] = "$Commander";
    libCOUI_gv_cU_CommanderSelect_PlayerReady[2] = true;
    libCOUI_gf_CU_CommanderFinalizeStates(2);
    Wait(1.0, c_timeReal);
    CMUIX_ReadyBeginCountdown();
    return ;
"@
    $replacement = $replacementBody.Replace("`r`n", "`n").Replace("`n", "`r`n").TrimEnd("`r", "`n")
    Write-Host "DEBUG Enable-CmreSavedProfileStartup: Commander=$Commander"
    Write-Host "DEBUG replacement (first 200 chars): $($replacement.Substring(0, [Math]::Min(200, $replacement.Length)))"
    if ([regex]::IsMatch($content, [regex]::Escape($replacement))) {
        Write-Host "DEBUG: replacement already in content, skipping"
        return
    }
    if ([regex]::IsMatch($content, $legacyPatchPattern)) {
        $content = [regex]::Replace($content, $legacyPatchPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $originalPattern)) {
        $content = [regex]::Replace($content, $originalPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $fallbackPattern)) {
        $content = [regex]::Replace($content, $fallbackPattern, $replacement, 1)
    } else {
        throw "CMRE saved-profile startup anchor not found"
    }
    [System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "CMRE saved-profile startup patch applied to map: $path"
}

function Install-CmreGalaxyHostOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$ModsRoot,
        [Parameter(Mandatory = $true)][string]$MapPath
    )

    # CMRE and StarCoop both expose LibCO* paths. The map-level copy keeps every
    # CMRE library header and implementation from the same build revision.
    $sourceRoot = Join-Path $ModsRoot "CMRE\CMRE_Core_Triggers.SC2Mod\Base.SC2Data"
    $destinationRoot = Join-Path $MapPath "Base.SC2Data"
    $libraries = Get-ChildItem -LiteralPath $sourceRoot -File -Filter "Lib*.galaxy" | Sort-Object Name
    if ($libraries.Count -eq 0) { throw "CMRE Galaxy host libraries not found: $sourceRoot" }

    [System.IO.Directory]::CreateDirectory($destinationRoot) | Out-Null
    foreach ($library in $libraries) {
        [System.IO.File]::Copy($library.FullName, (Join-Path $destinationRoot $library.Name), $true)
    }

    # Also copy Alenger3Adapter galaxy files so the map can call
    # libA3ADAPTER_InitLib() to register TechTree unlock triggers. Without
    # this the adapter's Build/Train/Unit allow lists never execute, leaving
    # Suppressed build options (barracks/factory/starport) invisible.
    $adapterRoot = Join-Path $ModsRoot "7vs1\Alenger3Adapter.SC2Mod\Base.SC2Data"
    $adapterFiles = @("LibA3ADAPTER_h.galaxy", "LibA3ADAPTER.galaxy", "LibA3ADAPTER_Catalog.galaxy")
    foreach ($name in $adapterFiles) {
        $src = Join-Path $adapterRoot $name
        if (-not (Test-Path -LiteralPath $src)) { throw "Alenger3Adapter galaxy file not found: $src" }
        [System.IO.File]::Copy($src, (Join-Path $destinationRoot $name), $true)
    }

    # Copy RuntimeProbe galaxy files so the map can publish real-time unit
    # and ability data to RuntimeProbe.SC2Bank. Without this the runtime
    # probe service has no live data and falls back to stale cache.
    $probeRoot = Join-Path $ModsRoot "RuntimeProbe\RuntimeProbe.SC2Mod\Base.SC2Data"
    $probeFiles = @("LibRuntimeProbe_h.galaxy", "LibRuntimeProbe.galaxy")
    foreach ($name in $probeFiles) {
        $src = Join-Path $probeRoot $name
        if (-not (Test-Path -LiteralPath $src)) { throw "RuntimeProbe galaxy file not found: $src" }
        [System.IO.File]::Copy($src, (Join-Path $destinationRoot $name), $true)
    }

    $required = @("LibCOOC_h.galaxy", "LibCOOC.galaxy", "LibCOMI_h.galaxy", "LibCOMI.galaxy", "LibA3ADAPTER.galaxy", "LibA3ADAPTER_h.galaxy", "LibA3ADAPTER_Catalog.galaxy", "LibRuntimeProbe_h.galaxy", "LibRuntimeProbe.galaxy")
    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $destinationRoot $name))) {
            throw "CMRE Galaxy host overlay is incomplete: $name"
        }
    }
    Write-Host "CMRE Galaxy host overlay: $($libraries.Count) CMRE + $($adapterFiles.Count) Alenger3Adapter files"
}

function Install-CmreDynamicObserver {
    param([Parameter(Mandatory = $true)][string]$MapPath)

    $neuroRoot = Join-Path $WorkspaceRoot "reference\SC2-Neuro-API-Integration"
    $observerRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\runtime"
    $adapterRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\adapters\dead-of-night"
    $baseData = Join-Path $MapPath "Base.SC2Data"
    $files = @(
        @{ Source = Join-Path $neuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406_h.galaxy"; Name = "LibEFA54406_h.galaxy" },
        @{ Source = Join-Path $neuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406.galaxy"; Name = "LibEFA54406.galaxy" },
        @{ Source = Join-Path $observerRoot "LibPortingObserver_h.galaxy"; Name = "LibPortingObserver_h.galaxy" },
        @{ Source = Join-Path $observerRoot "LibPortingObserver.galaxy"; Name = "LibPortingObserver.galaxy" },
        @{ Source = Join-Path $adapterRoot "LibDeadOfNightObserver_h.galaxy"; Name = "LibDeadOfNightObserver_h.galaxy" },
        @{ Source = Join-Path $adapterRoot "LibDeadOfNightObserver.galaxy"; Name = "LibDeadOfNightObserver.galaxy" }
    )
    foreach ($file in $files) {
        if (-not (Test-Path -LiteralPath $file.Source)) { throw "Observer input not found: $($file.Source)" }
        [System.IO.File]::Copy($file.Source, (Join-Path $baseData $file.Name), $true)
    }

    $efaPath = Join-Path $baseData "LibEFA54406.galaxy"
    $efa = [System.IO.File]::ReadAllText($efaPath, [System.Text.Encoding]::UTF8)
    if ($efa -notmatch '(?m)^include "LibPortingObserver_h"$') {
        $efa = $efa.Replace('include "LibEFA54406_h"', "include `"LibEFA54406_h`"`r`ninclude `"LibPortingObserver_h`"")
    }
    $actionAnchor = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + "`r`n    return true;"
    $actionPatch = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + "`r`n    libEFA54406_gf_BootstrapPortingObserver();`r`n    return true;"
    if ($efa.Contains($actionAnchor)) { $efa = $efa.Replace($actionAnchor, $actionPatch) }
    # The integration library's legacy color conversion is rejected by this CMRE runtime.
    # Keep the upstream text while omitting only that incompatible conversion in the live copy.
    $legacyColorCall = '            libEFA54406_gv_displayNameText = TextWithColor(libEFA54406_gv_displayNameText, Color(100.00, 50.20, 75.29));'
    if ($efa.Contains($legacyColorCall)) {
        $efa = $efa.Replace($legacyColorCall, '            // CMRE adapter: display text retained without incompatible color conversion.')
    }
    # CMRE fix: upstream Executeactionsglobal_Func sets bankwriteallowed=false at
    # entry (line 351) but never resets it to true. Every other bank-writing
    # function in this library follows the pattern set-false -> work -> set-true,
    # but Executeactionsglobal_Func omits the final set-true. This permanently
    # blocks all subsequent create_context Publish calls (they spin on
    # while(bankwriteallowed==false) Wait(...)). The bug manifests as:
    #   - execute_actions_fired key never appears in Bank
    #   - alenger_unit_presence stuck at bootstrap-time values (commander_p1 empty)
    #   - player_*_inventory never written
    # Reset the semaphore after the map event handlers return.
    $execMapAnchor = '    BankSave(BankLastCreated());' + "`r`n" +
                     '    Wait(0.1, c_timeReal);' + "`r`n" +
                     '    TriggerSendEvent("execute_actions_map");' + "`r`n" +
                     '    return true;'
    $execMapPatch = '    BankSave(BankLastCreated());' + "`r`n" +
                    '    Wait(0.1, c_timeReal);' + "`r`n" +
                    '    TriggerSendEvent("execute_actions_map");' + "`r`n" +
                    '    libEFA54406_gv_bankwriteallowed = true;' + "`r`n" +
                    '    return true;'
    if ($efa.Contains($execMapAnchor)) {
        $efa = $efa.Replace($execMapAnchor, $execMapPatch)
    }
    [System.IO.File]::WriteAllText($efaPath, $efa, [System.Text.UTF8Encoding]::new($false))

    $mapScriptPath = Join-Path $MapPath "MapScript.galaxy"
    $mapScript = [System.IO.File]::ReadAllText($mapScriptPath, [System.Text.Encoding]::UTF8)
    if ($mapScript -notmatch '(?m)^include "LibEFA54406"$') {
        $incReplacement = 'include "LibCOUI"' + "`r`n" + 'include "LibEFA54406"' + "`r`n" + 'include "LibPortingObserver"' + "`r`n" + 'include "LibA3ADAPTER"' + "`r`n" + 'include "LibRuntimeProbe"'
        $mapScript = $mapScript.Replace('include "LibCOUI"', $incReplacement)
    }
    if ($mapScript -notmatch 'libEFA54406_InitLib\s*\(\s*\)') {
        $initReplacement = '    libCOUI_InitLib();' + "`r`n" + '    libEFA54406_InitLib();' + "`r`n" + '    libPortingObserver_InitLib();' + "`r`n" + '    libA3ADAPTER_InitLib();' + "`r`n" + '    libRuntimeProbe_InitLib();'
        $mapScript = $mapScript.Replace('    libCOUI_InitLib();', $initReplacement)
    }
    if ($mapScript -notmatch 'gt_PortingObserverDeadOfNightPoll_Func') {
        $mapInitAnchor = "//--------------------------------------------------------------------------------------------------`r`n// Map Initialization"
        if (-not $mapScript.Contains($mapInitAnchor)) { throw "Map initialization anchor not found in MapScript" }
        $pollGlue = @"
include "LibDeadOfNightObserver"

trigger gt_PortingObserverDeadOfNightPoll;
trigger gt_Alenger3StartingUnits;

bool gt_PortingObserverDeadOfNightPoll_Func(bool testConds, bool runActions) {
    int lv_primaryState = -1;
    int lv_bonusState = -1;
    if (testConds) { return true; }
    if (!runActions) { return true; }
    libPortingObserver_gf_Publish("poll_trigger_started", "DeadOfNight poll trigger is running", false);
    Wait(10.0, c_timeReal);
    while (true) {
        if (gv_objective_Primary_DestroyInfestation != c_invalidObjectiveId) {
            lv_primaryState = ObjectiveGetState(gv_objective_Primary_DestroyInfestation);
        }
        if (gv_objective_Bonus_DestroyInfestationSource != c_invalidObjectiveId) {
            lv_bonusState = ObjectiveGetState(gv_objective_Bonus_DestroyInfestationSource);
        }
        libDeadOfNightObserver_gf_Update(gv_dayORNight, gv_nightNumber,
            gv_infestedStructuresRemaining, gv_infestedStructuresTotal, lv_primaryState, lv_bonusState);
        libPortingObserver_gf_PublishAlengerPresenceProbe();
        Wait(1.0, c_timeReal);
        libPortingObserver_gf_PublishAlengerStructureProbe();
        Wait(1.0, c_timeReal);
        libPortingObserver_gf_PublishAlengerCommandCardDump();
        Wait(1.0, c_timeReal);
        libPortingObserver_gf_PublishAlengerWorkerBuildDump();
        Wait(7.0, c_timeReal);
    }
    return true;
}

void gt_PortingObserverDeadOfNightPoll_Init() {
    gt_PortingObserverDeadOfNightPoll = TriggerCreate("gt_PortingObserverDeadOfNightPoll_Func");
    TriggerExecute(gt_PortingObserverDeadOfNightPoll, false, true);
}

// Remove every unit of lp_type owned by lp_player. Returns the count removed.
// Reverse iteration: UnitGroupCount shrinks as we UnitRemove, so forward
// iteration exits early. Iterating from count down to 1 ensures full removal.
// Guards against invalid unit types to avoid ScriptError noise that fails
// the runtime service's script_error_free assertion.
int gf_RemoveAllUnitsOfType(int lp_player, string lp_type) {
    unitgroup lv_units;
    int lv_count;
    int lv_i;
    if (lp_type == "") { return 0; }
    if (!CatalogEntryIsValid(c_gameCatalogUnit, lp_type)) { return 0; }
    lv_units = UnitGroup(lp_type, lp_player, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_count = UnitGroupCount(lv_units, c_unitCountAll);
    for (lv_i = lv_count; lv_i >= 1; lv_i -= 1) {
        UnitRemove(UnitGroupUnit(lv_units, lv_i));
    }
    return lv_count;
}

bool gt_Alenger3StartingUnits_Func(bool testConds, bool runActions) {
    point lv_p1Start = null;
    point lv_p2Start = null;
    int lv_i = 0;
    unitgroup lv_beforeP1 = UnitGroupEmpty();
    unitgroup lv_afterP1 = UnitGroupEmpty();
    unitgroup lv_beforeP2 = UnitGroupEmpty();
    unitgroup lv_afterP2 = UnitGroupEmpty();
    int lv_beforeCount = 0;
    int lv_createdP1 = 0;
    int lv_createdP2 = 0;
    string lv_diag = "";
    string lv_p1Valid = "F";
    string lv_p2Valid = "F";
    unitgroup lv_vanillaUnits = UnitGroupEmpty();
    int lv_removedP1 = 0;
    int lv_removedP2 = 0;
    bank lv_diagBank = null;
    if (testConds) { return true; }
    if (!runActions) { return true; }
    // Diagnostic: write step markers to RuntimeProbe Bank so we can trace
    // exactly where the trigger stops. libPortingObserver_gf_Publish is
    // unreliable because it depends on libEFA54406_gv_neuroIntegration
    // being non-null.
    lv_diagBank = BankLoad("RuntimeProbe", 1);
    if (lv_diagBank != null) {
        BankValueSetFromString(lv_diagBank, "alenger3_diag", "step", "1_triggered");
        BankSave(lv_diagBank);
    }
    libPortingObserver_gf_Publish("alenger3_starting_units_begin", "creating Alenger3 starting units", false);
    // Wait for commander selection countdown to finish and game init to settle.
    // The CMUIX_ReadyBeginCountdown patch makes commander available immediately,
    // but the game still needs ~5s to finalize init, spawn pre-placed units,
    // and hand control back. Waiting here ensures PlayerStartLocation is valid
    // and the Alenger3 tech tree unlock from Alenger3Adapter has been applied.
    Wait(5.0, c_timeReal);
    lv_p1Start = PlayerStartLocation(1);
    lv_p2Start = PlayerStartLocation(2);
    if (lv_p1Start != null) { lv_p1Valid = "T"; }
    if (lv_p2Start != null) { lv_p2Valid = "T"; }
    if (lv_diagBank != null) {
        BankValueSetFromString(lv_diagBank, "alenger3_diag", "step", "2_after_wait_p1=" + lv_p1Valid + "_p2=" + lv_p2Valid);
        BankSave(lv_diagBank);
    }

    // Remove vanilla starting units created by MeleeInitUnitsForPlayer (called
    // from libCOMI_gf_CM_StartingTechForHumanPlayer at LibCOMI.galaxy:18065).
    // MeleeInit creates CommandCenterRaynor + SCVRaynor per Terran player because
    // CMRE does not know about TerranAlenger3 and falls back to Raynor. CMRE
    // also spawns MarineRaynor, RaynorCommando and CoopCasterRaynor. The map
    // itself pre-places CommandCenter + SCV (no Raynor suffix). All of these
    // must be removed so only the Alenger3 units created below remain.
    lv_removedP1 = gf_RemoveAllUnitsOfType(1, "CommandCenterRaynor");
    lv_removedP1 += gf_RemoveAllUnitsOfType(1, "SCVRaynor");
    lv_removedP1 += gf_RemoveAllUnitsOfType(1, "MarineRaynor");
    lv_removedP1 += gf_RemoveAllUnitsOfType(1, "RaynorCommando");
    lv_removedP1 += gf_RemoveAllUnitsOfType(1, "CoopCasterRaynor");
    lv_removedP1 += gf_RemoveAllUnitsOfType(1, "CommandCenter");
    lv_removedP1 += gf_RemoveAllUnitsOfType(1, "SCV");
    lv_removedP2 = gf_RemoveAllUnitsOfType(2, "CommandCenterRaynor");
    lv_removedP2 += gf_RemoveAllUnitsOfType(2, "SCVRaynor");
    lv_removedP2 += gf_RemoveAllUnitsOfType(2, "MarineRaynor");
    lv_removedP2 += gf_RemoveAllUnitsOfType(2, "RaynorCommando");
    lv_removedP2 += gf_RemoveAllUnitsOfType(2, "CoopCasterRaynor");
    lv_removedP2 += gf_RemoveAllUnitsOfType(2, "CommandCenter");
    lv_removedP2 += gf_RemoveAllUnitsOfType(2, "SCV");

    lv_beforeP1 = UnitGroup("3diguoqianshaojidi", 1, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_beforeCount = UnitGroupCount(lv_beforeP1, c_unitCountAll);
    if (lv_p1Start != null) {
        UnitCreate(1, "3diguoqianshaojidi", c_unitCreateIgnorePlacement, 1, lv_p1Start, 270.0);
        for (lv_i = 0; lv_i < 5; lv_i += 1) {
            UnitCreate(1, "3diguolaogong", c_unitCreateIgnorePlacement, 1,
                PointWithOffsetPolar(lv_p1Start, 3.0, (IntToFixed(lv_i) * 72.0)), 270.0);
        }
    }
    lv_afterP1 = UnitGroup("3diguoqianshaojidi", 1, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_createdP1 = UnitGroupCount(lv_afterP1, c_unitCountAll) - lv_beforeCount;
    lv_beforeP2 = UnitGroup("3diguoqianshaojidi", 2, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_beforeCount = UnitGroupCount(lv_beforeP2, c_unitCountAll);
    if (lv_p2Start != null) {
        UnitCreate(1, "3diguoqianshaojidi", c_unitCreateIgnorePlacement, 2, lv_p2Start, 270.0);
        for (lv_i = 0; lv_i < 5; lv_i += 1) {
            UnitCreate(1, "3diguolaogong", c_unitCreateIgnorePlacement, 2,
                PointWithOffsetPolar(lv_p2Start, 3.0, (IntToFixed(lv_i) * 72.0)), 270.0);
        }
    }
    lv_afterP2 = UnitGroup("3diguoqianshaojidi", 2, RegionEntireMap(), UnitFilter(0, 0, 0, 0), 0);
    lv_createdP2 = UnitGroupCount(lv_afterP2, c_unitCountAll) - lv_beforeCount;
    if (lv_diagBank != null) {
        BankValueSetFromString(lv_diagBank, "alenger3_diag", "step", "3_after_create_p1=" + IntToString(lv_createdP1) + "_p2=" + IntToString(lv_createdP2));
        BankSave(lv_diagBank);
    }
    // Diagnostic: report actual creation results instead of a fixed string.
    // If created count is 0, UnitCreate failed — possible causes:
    //   - PlayerStartLocation returned null (p1Valid/p2Valid will be F)
    //   - unit type "3diguoqianshaojidi" not available at runtime
    //   - UnitCreate silently rejected the call
    lv_diag = "p1_start=" + lv_p1Valid + "; p2_start=" + lv_p2Valid +
        "; created_p1=" + IntToString(lv_createdP1) + "; created_p2=" + IntToString(lv_createdP2) +
        "; after_p1=" + IntToString(UnitGroupCount(lv_afterP1, c_unitCountAll)) +
        "; after_p2=" + IntToString(UnitGroupCount(lv_afterP2, c_unitCountAll)) +
        "; removed_vanilla_p1=" + IntToString(lv_removedP1) +
        "; removed_vanilla_p2=" + IntToString(lv_removedP2);
    libPortingObserver_gf_Publish("alenger3_starting_units_done", lv_diag, false);
    // Start the periodic RuntimeProbe loop now that Alenger3 units exist.
    // This registers the 3-second Loop trigger so probe_units/probe_state
    // refresh and the NeuroRuntime API reflects the real game state.
    libRuntimeProbe_gf_StartProbe();
    return true;
}

void gt_Alenger3StartingUnits_Init() {
    gt_Alenger3StartingUnits = TriggerCreate("gt_Alenger3StartingUnits_Func");
    TriggerExecute(gt_Alenger3StartingUnits, false, true);
}

trigger gt_Alenger3TrainProbe;

bool gt_Alenger3TrainProbe_Func(bool testConds, bool runActions) {
    string lv_structureType = "3diguoqianshaojidi";
    string lv_workerType = "3diguolaogong";
    unitgroup lv_structs = null;
    unitgroup lv_workers = null;
    unit lv_producer = null;
    int lv_workerBefore = 0;
    int lv_workerAfter = 0;
    order lv_trainOrder = null;
    bool lv_issued = false;
    string lv_resultStr = "not_issued";
    string lv_finalContext = "";
    if (testConds) { return true; }
    if (!runActions) { return true; }
    libPortingObserver_gf_Publish("alenger3_train_probe_begin", "starting train completion probe", false);
    // Wait for gt_Alenger3StartingUnits (15s delay) to finish creating units.
    Wait(25.0, c_timeReal);
    lv_structs = UnitGroup(lv_structureType, c_playerAny, RegionEntireMap(),
        UnitFilter(0, 0, 0, (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    if (UnitGroupCount(lv_structs, c_unitCountAll) == 0) {
        libPortingObserver_gf_Publish("alenger3_train_probe_result", "no_producer; worker_before=0; worker_after=0; new_workers=0; train_completed=false", false);
        return true;
    }
    lv_producer = UnitGroupUnit(lv_structs, 1);
    if (lv_producer == null) {
        libPortingObserver_gf_Publish("alenger3_train_probe_result", "producer_null; train_completed=false", false);
        return true;
    }
    lv_workers = UnitGroup(lv_workerType, c_playerAny, RegionEntireMap(),
        UnitFilter(0, 0, 0, (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    lv_workerBefore = UnitGroupCount(lv_workers, c_unitCountAll);
    lv_trainOrder = Order(AbilityCommand("3xunlian1", 0));
    lv_issued = UnitIssueOrder(lv_producer, lv_trainOrder, c_orderQueueReplace);
    if (lv_issued) {
        lv_resultStr = "issued";
    } else {
        lv_resultStr = "issue_failed";
    }
    libPortingObserver_gf_Publish("alenger3_train_probe_mid", "train_order=" + lv_resultStr + "; worker_before=" + IntToString(lv_workerBefore) + "; waiting 45s for train completion", false);
    // Wait for training to complete (3diguolaogong train time ~12-15s, add margin).
    Wait(45.0, c_timeReal);
    lv_workers = UnitGroup(lv_workerType, c_playerAny, RegionEntireMap(),
        UnitFilter(0, 0, 0, (1 << (c_targetFilterDead - 32)) | (1 << (c_targetFilterHidden - 32))), 0);
    lv_workerAfter = UnitGroupCount(lv_workers, c_unitCountAll);
    lv_finalContext = "train_order=" + lv_resultStr +
        "; worker_before=" + IntToString(lv_workerBefore) +
        "; worker_after=" + IntToString(lv_workerAfter) +
        "; new_workers=" + IntToString(lv_workerAfter - lv_workerBefore);
    if (lv_workerAfter > lv_workerBefore) {
        lv_finalContext = lv_finalContext + "; train_completed=true";
    } else {
        lv_finalContext = lv_finalContext + "; train_completed=false";
    }
    libPortingObserver_gf_Publish("alenger3_train_probe_result", lv_finalContext, false);
    return true;
}

void gt_Alenger3TrainProbe_Init() {
    gt_Alenger3TrainProbe = TriggerCreate("gt_Alenger3TrainProbe_Func");
    TriggerExecute(gt_Alenger3TrainProbe, false, true);
}

"@
        $mapScript = $mapScript.Replace($mapInitAnchor, $pollGlue.Replace("`n", "`r`n") + $mapInitAnchor)
    }
    if ($mapScript -notmatch 'libDeadOfNightObserver_InitLib\s*\(\s*\)') {
        $initAnchor = "    InitGlobals();`r`n    InitTriggers();"
        if (-not $mapScript.Contains($initAnchor)) { throw "InitMap anchor not found in MapScript" }
        $initMapReplacement = "    InitGlobals();`r`n    libDeadOfNightObserver_InitLib();`r`n    gt_PortingObserverDeadOfNightPoll_Init();`r`n    gt_Alenger3StartingUnits_Init();`r`n    gt_Alenger3TrainProbe_Init();`r`n    InitTriggers();"
        $mapScript = $mapScript.Replace($initAnchor, $initMapReplacement)
    }
    [System.IO.File]::WriteAllText($mapScriptPath, $mapScript, [System.Text.UTF8Encoding]::new($false))

    $bankListPath = Join-Path $MapPath "BankList.xml"
    [xml]$bankList = [System.IO.File]::ReadAllText($bankListPath, [System.Text.Encoding]::UTF8)
    $bankChanged = $false
    if (@($bankList.BankList.Bank | Where-Object { $_.Name -eq "NeuroIntegration" -and $_.Player -eq "1" }).Count -eq 0) {
        $bank = $bankList.CreateElement("Bank")
        $bank.SetAttribute("Name", "NeuroIntegration")
        $bank.SetAttribute("Player", "1")
        $bankList.BankList.AppendChild($bank) | Out-Null
        $bankChanged = $true
    }
    # RuntimeProbe Bank is required by libRuntimeProbe_InitLib() to publish
    # real-time unit/ability/upgrade data. Without this registration BankLoad
    # returns null and the runtime probe service falls back to stale cache.
    if (@($bankList.BankList.Bank | Where-Object { $_.Name -eq "RuntimeProbe" -and $_.Player -eq "1" }).Count -eq 0) {
        $bank = $bankList.CreateElement("Bank")
        $bank.SetAttribute("Name", "RuntimeProbe")
        $bank.SetAttribute("Player", "1")
        $bankList.BankList.AppendChild($bank) | Out-Null
        $bankChanged = $true
    }
    if ($bankChanged) {
        $settings = [System.Xml.XmlWriterSettings]::new(); $settings.Indent = $true; $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
        $writer = [System.Xml.XmlWriter]::Create($bankListPath, $settings)
        try { $bankList.Save($writer) } finally { $writer.Dispose() }
    }
}

function Patch-CmreCoreRuntimeErrors {
    param([Parameter(Mandatory = $true)][string]$MapPath)

    # CMRE-ALENGER3-RUNTIME-002: 6 classes of non-fatal runtime errors in
    # LibCOTF.galaxy, LibCOUI.galaxy and LibCOMI.galaxy. CMRE core assumes
    # fully configured commander data (decal, revive behavior, shield color,
    # AI vision dialog, gameUser for player 2) but the 5-dep Alenger3
    # composition does not populate all of these fields. Patches add defensive
    # guards / fallbacks to suppress ScriptError noise. Idempotent: skips
    # anchors that already contain the patch marker.

    $baseData = Join-Path $MapPath "Base.SC2Data"
    $patchCount = 0

    # --- LibCOTF.galaxy patches ---
    $cotfPath = Join-Path $baseData "LibCOTF.galaxy"
    if (-not (Test-Path -LiteralPath $cotfPath)) { throw "LibCOTF.galaxy not found: $cotfPath" }
    $cotf = [System.IO.File]::ReadAllText($cotfPath, [System.Text.Encoding]::UTF8)

    # Patch 1: line 176 - EventPlayerEffectUsedUnitOwner has no effect event in InitGlobals context
    $cotfAnchor1 = '    libCOTF_gv_player = EventPlayerEffectUsedUnitOwner(c_effectPlayerCaster);'
    $cotfPatch1 = '    libCOTF_gv_player = 1; // CMRE patch: InitGlobals has no effect event context'
    if (-not $cotf.Contains($cotfPatch1)) {
        if (-not $cotf.Contains($cotfAnchor1)) { throw "LibCOTF patch 1 anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor1, $cotfPatch1); $patchCount++
    }

    # Patch 2: line 7828 - PlayerHandle returns non-numeric string; StringToInt fails.
    # Line 7829 also fails (DateTimeToString returns non-numeric string).
    # Both lines are redundant: the while loop at line 7830 provides continuous
    # random seeds via RandomInt. Comment out both lines to suppress ScriptError.
    $cotfAnchor2 = '    GameSetSeed(StringToInt((PlayerHandle(1) + PlayerHandle(2))));'
    $cotfPatch2 = '    // CMRE patch: skip PlayerHandle-based seed (StringToInt cannot parse handle string)'
    if (-not $cotf.Contains($cotfPatch2)) {
        if (-not $cotf.Contains($cotfAnchor2)) { throw "LibCOTF patch 2 anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor2, $cotfPatch2); $patchCount++
    }

    # Patch 2b: line 7829 - DateTimeToString returns non-numeric string; StringToInt fails.
    $cotfAnchor2b = '    GameSetSeed(StringToInt(DateTimeToString(CurrentDateTimeGet())));'
    $cotfPatch2b = '    // CMRE patch: skip DateTime-based seed (StringToInt cannot parse datetime string; while loop below provides continuous random seed)'
    if (-not $cotf.Contains($cotfPatch2b)) {
        if (-not $cotf.Contains($cotfAnchor2b)) { throw "LibCOTF patch 2b anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor2b, $cotfPatch2b); $patchCount++
    }

    # Patch 3: line 7959 - DialogSetVisible with invalid dialog handle
    $cotfAnchor3 = '    DialogSetVisible(libCOTF_gv_uT_AIVisionDialog, PlayerGroupAll(), false);'
    $cotfPatch3 = '    if (libCOTF_gv_uT_AIVisionDialog != c_invalidDialogId) { DialogSetVisible(libCOTF_gv_uT_AIVisionDialog, PlayerGroupAll(), false); } // CMRE patch: guard invalid dialog handle'
    if (-not $cotf.Contains($cotfPatch3)) {
        if (-not $cotf.Contains($cotfAnchor3)) { throw "LibCOTF patch 3 anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor3, $cotfPatch3); $patchCount++
    }

    [System.IO.File]::WriteAllText($cotfPath, $cotf, [System.Text.UTF8Encoding]::new($false))

    # --- LibCOUI.galaxy patches ---
    $couiPath = Join-Path $baseData "LibCOUI.galaxy"
    if (-not (Test-Path -LiteralPath $couiPath)) { throw "LibCOUI.galaxy not found: $couiPath" }
    $coui = [System.IO.File]::ReadAllText($couiPath, [System.Text.Encoding]::UTF8)

    # Patch 4: line 3306 - SetDialogItemUnitGroup with invalid control handle
    $couiAnchor4 = '    libNtve_gf_SetDialogItemUnitGroup(libCOUI_gv_cU_GPCmdPanel[lp_player], libCOUI_gv_cU_GPCasterGroup[lp_player], PlayerGroupSingle(lp_player));'
    $couiPatch4 = '    if (libCOUI_gv_cU_GPCmdPanel[lp_player] != c_invalidDialogControlId) { libNtve_gf_SetDialogItemUnitGroup(libCOUI_gv_cU_GPCmdPanel[lp_player], libCOUI_gv_cU_GPCasterGroup[lp_player], PlayerGroupSingle(lp_player)); } // CMRE patch: guard invalid control handle'
    if (-not $coui.Contains($couiPatch4)) {
        if (-not $coui.Contains($couiAnchor4)) { throw "LibCOUI patch 4 anchor not found" }
        $coui = $coui.Replace($couiAnchor4, $couiPatch4); $patchCount++
    }

    [System.IO.File]::WriteAllText($couiPath, $coui, [System.Text.UTF8Encoding]::new($false))

    # --- LibCOMI.galaxy patches ---
    $comiPath = Join-Path $baseData "LibCOMI.galaxy"
    if (-not (Test-Path -LiteralPath $comiPath)) { throw "LibCOMI.galaxy not found: $comiPath" }
    $comi = [System.IO.File]::ReadAllText($comiPath, [System.Text.Encoding]::UTF8)

    # Patch 5+6: lines 23813 and 23851 - CatalogFieldValueGet with empty decal entry (same anchor, replaces both)
    $comiAnchor5 = '    lv_commanderDefaultDecalString = CatalogFieldValueGet(c_gameCatalogTexture, lv_commanderDefaultDecal, "File", c_playerAny);'
    $comiPatch5 = '    if (lv_commanderDefaultDecal != "") { lv_commanderDefaultDecalString = CatalogFieldValueGet(c_gameCatalogTexture, lv_commanderDefaultDecal, "File", c_playerAny); } // CMRE patch: guard empty decal entry'
    if (-not $comi.Contains($comiPatch5)) {
        if (-not $comi.Contains($comiAnchor5)) { throw "LibCOMI patch 5 anchor not found" }
        $comi = $comi.Replace($comiAnchor5, $comiPatch5); $patchCount += 2
    }

    # Patch 7: line 18204 - CatalogFieldValueGet fails when NormalRevive behavior is empty.
    # Guard the call itself (not just the fallback) to suppress ScriptError at the source.
    $comiAnchor7 = '    lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroNormalReviveBehavior(lp_player), "Duration", lp_player));'
    $comiPatch7 = '    if (libCOOC_gf_CC_PlayerHeroNormalReviveBehavior(lp_player) != "") { lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroNormalReviveBehavior(lp_player), "Duration", lp_player)); } if (lv_reviveDuration <= 0.0) { lv_reviveDuration = 60.0; } // CMRE patch: guard empty normal revive behavior entry'
    if (-not $comi.Contains($comiPatch7)) {
        if (-not $comi.Contains($comiAnchor7)) { throw "LibCOMI patch 7 anchor not found" }
        $comi = $comi.Replace($comiAnchor7, $comiPatch7); $patchCount++
    }

    # Patch 8: line 18244 - CatalogFieldValueGet fails when FirstRevive behavior is empty.
    # Guard the call itself (not just the fallback) to suppress ScriptError at the source.
    $comiAnchor8 = '    lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroFirstReviveBehavior(lp_player), "Duration", lp_player));'
    $comiPatch8 = '    if (libCOOC_gf_CC_PlayerHeroFirstReviveBehavior(lp_player) != "") { lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroFirstReviveBehavior(lp_player), "Duration", lp_player)); } if (lv_reviveDuration <= 0.0) { lv_reviveDuration = 60.0; } // CMRE patch: guard empty first revive behavior entry'
    if (-not $comi.Contains($comiPatch8)) {
        if (-not $comi.Contains($comiAnchor8)) { throw "LibCOMI patch 8 anchor not found" }
        $comi = $comi.Replace($comiAnchor8, $comiPatch8); $patchCount++
    }

    # Patch 9: line 18259 - divide-by-zero when lv_reviveDuration is 0
    $comiAnchor9 = '    UnitSetPropertyFixed(libCOMI_gv_cM_HeroReviver[lp_player], c_unitPropLifeRegen, (UnitGetPropertyFixed(libCOMI_gv_cM_HeroReviver[lp_player], c_unitPropLifeMax, c_unitPropCurrent)/lv_reviveDuration));'
    $comiPatch9 = '    if (lv_reviveDuration > 0.0) { UnitSetPropertyFixed(libCOMI_gv_cM_HeroReviver[lp_player], c_unitPropLifeRegen, (UnitGetPropertyFixed(libCOMI_gv_cM_HeroReviver[lp_player], c_unitPropLifeMax, c_unitPropCurrent)/lv_reviveDuration)); } // CMRE patch: guard divide-by-zero'
    if (-not $comi.Contains($comiPatch9)) {
        if (-not $comi.Contains($comiAnchor9)) { throw "LibCOMI patch 9 anchor not found" }
        $comi = $comi.Replace($comiAnchor9, $comiPatch9); $patchCount++
    }

    [System.IO.File]::WriteAllText($comiPath, $comi, [System.Text.UTF8Encoding]::new($false))

    Write-Host "CMRE core runtime error patches applied: $patchCount locations"
}

function Write-CmreLaunchProfile {
    $banksRoot = "C:\Users\22448\Documents\StarCraft II\Banks"
    [System.IO.Directory]::CreateDirectory($banksRoot) | Out-Null
    $doc = [xml]'<Bank version="1"><Section name="CMUI|LaunchProfile" /></Bank>'
    $values = [ordered]@{ Valid = @("int", "1"); Version = @("int", "1"); CreatedAt = @("int", [string][int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()); TimeoutSeconds = @("int", "600"); Mode = @("int", "1"); ModeInstance = @("string", "Standard"); DifficultyBase = @("int", "0"); DifficultyPlus = @("int", "0"); TargetMission = @("string", "AC_MeinhoffDayNight"); TargetMap = @("string", "AC_MeinhoffDayNight"); 'Player|1|Commander' = @("string", $Commander); 'Player|2|Commander' = @("string", $Commander) }
    foreach ($entry in $values.GetEnumerator()) { $key = $doc.CreateElement("Key"); $key.SetAttribute("name", $entry.Key); $value = $doc.CreateElement("Value"); $value.SetAttribute($entry.Value[0], $entry.Value[1]); $key.AppendChild($value) | Out-Null; $doc.Bank.Section.AppendChild($key) | Out-Null }
    $settings = [System.Xml.XmlWriterSettings]::new(); $settings.Indent = $true; $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.Xml.XmlWriter]::Create((Join-Path $banksRoot "CMCoopLaunchProfile.SC2Bank"), $settings)
    try { $doc.Save($writer) } finally { $writer.Dispose() }
}

$lock = Acquire-TestLock -TestType "cmre_alenger" -MapName $MapName -Commander $Commander
try {
    Stop-RunningSc2; Clear-GameLogs
    Sync-ModSet -ModRelPaths $cmre.baseMods -ProjRoot $LegacyRoot -Sc2Root $Sc2Root
    if (@($cmre.commanderBaseMods).Count -gt 0) {
        Sync-ModSet -ModRelPaths $cmre.commanderBaseMods -ProjRoot $LegacyRoot -Sc2Root $Sc2Root
    }
    Sync-ModSet -ModRelPaths @($selectedMods | ForEach-Object { "7vs1\$_.SC2Mod" }) -ProjRoot $AlengerPackagesRoot -Sc2Root $Sc2Root
    $liveMap = Join-Path $Sc2Root "Maps\$MapName"
    if (Test-Path -LiteralPath $liveMap) { [System.IO.Directory]::Delete($liveMap, $true) }
    [System.IO.Directory]::CreateDirectory($liveMap) | Out-Null
    robocopy $mapSource $liveMap /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    Install-CmreGalaxyHostOverlay -ModsRoot (Join-Path $Sc2Root "Mods") -MapPath $liveMap
    Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander
    Install-CmreDynamicObserver -MapPath $liveMap
    Patch-CmreCoreRuntimeErrors -MapPath $liveMap
    Set-MapDependencies -MapPath $liveMap -Dependencies $dependencies
    $roundtrip = Test-DocumentDependencyRoundtrip -HeaderPath (Join-Path $liveMap "DocumentHeader") -InfoPath (Join-Path $liveMap "DocumentInfo")
    if (-not $roundtrip.Valid) { throw "Document dependency roundtrip failed: $($roundtrip.Errors -join '; ')" }
    Set-CampaignXCorePrimaryCommander -SelectedCommanders @($Commander)
    Set-CampaignXCoreTestRunId -RunId "CMREAlenger"
    Write-CmreLaunchProfile
    if ($NoLaunch) { Write-Host "CMRE Alenger composition staged: $liveMap"; exit 0 }
    $switcher = Join-Path $Sc2Root "Support64\SC2Switcher_x64.exe"
    $args = @("`"$liveMap`"")
    if ($ListenPort -gt 0) {
        $args += "-listenPort", "$ListenPort"
        Write-Host "SC2 API will listen on port $ListenPort (for sc2-observer.py)"
    }
    Start-Process -FilePath $switcher -ArgumentList $args
    $exitCode = Wait-GameReady -ScriptsRoot (Join-Path $LegacyRoot "scripts")
    if ($exitCode -ne 0) { throw "SC2 readiness check failed with exit code $exitCode" }
} finally { Release-TestLock -LockContext $lock }
