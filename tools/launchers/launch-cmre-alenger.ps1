[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$MapName, [Parameter(Mandatory = $true)][string]$Commander, [switch]$DryRun, [switch]$NoLaunch, [int]$ListenPort = 0, [string]$LegacyRootOverride = "", [int]$Mode = 1, [int]$DifficultyBase = 0, [int]$DifficultyPlus = 0, [string]$Enemy = "", [string]$Mutators = "", [string]$ExtraMods = "")
$ErrorActionPreference = "Stop"
$WorkspaceRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$Sc2WorkspaceRoot = Split-Path -Parent $WorkspaceRoot
if ($LegacyRootOverride) {
    $LegacyRoot = $LegacyRootOverride
} else {
    # CMRE 框架运行时已迁入 SC2VibeTools/cmre-runtime（原 合作指挥官-起义狂潮 仓库已归档）
    $LegacyRoot = Join-Path $Sc2WorkspaceRoot "cmre-runtime"
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
# 读取指挥官 profile（如果存在）：用于参数化 adapter galaxy 文件、起始单位、vanilla 移除列表
$profile = $null
if ($alenger.PSObject.Properties.Name -contains 'commanderProfiles' -and
    $alenger.commanderProfiles.PSObject.Properties.Name -contains $alengerId) {
    $profile = $alenger.commanderProfiles.$alengerId
    Write-Host "Loaded commander profile for ${alengerId}: startingStructure=$($profile.startingStructure), startingWorker=$($profile.startingWorker)"
}
# 默认值（Alenger3 兼容路径）：保留旧的硬编码行为
$adapterLibPrefix = 'A3ADAPTER'
$adapterFiles = @("LibA3ADAPTER_h.galaxy", "LibA3ADAPTER.galaxy", "LibA3ADAPTER_Catalog.galaxy")
$adapterModName = 'Alenger3Adapter'
$startingStructure = '3diguoqianshaojidi'
$startingWorker = '3diguolaogong'
$workerCount = 5
$vanillaRemovals = @('CommandCenterRaynor', 'SCVRaynor', 'MarineRaynor', 'RaynorCommando', 'CoopCasterRaynor', 'CommandCenter', 'SCV')
if ($profile) {
    # 注意：PowerShell if(@()) 返回 $false，所以空数组需要用 null 检查
    if ($null -ne $profile.adapterLibPrefix -and $profile.adapterLibPrefix -ne '') { $adapterLibPrefix = $profile.adapterLibPrefix }
    if ($null -ne $profile.adapterFiles) { $adapterFiles = @($profile.adapterFiles) }
    if ($null -ne $profile.adapterModName -and $profile.adapterModName -ne '') { $adapterModName = $profile.adapterModName }
    if ($null -ne $profile.startingStructure -and $profile.startingStructure -ne '') { $startingStructure = $profile.startingStructure }
    if ($null -ne $profile.startingWorker -and $profile.startingWorker -ne '') { $startingWorker = $profile.startingWorker }
    if ($null -ne $profile.workerCount) { $workerCount = [int]$profile.workerCount }
    if ($null -ne $profile.vanillaRemovals) { $vanillaRemovals = @($profile.vanillaRemovals) }
}
$mapSource = Join-Path $LegacyRoot "Maps\CMRE\$MapName"
if (-not (Test-Path -LiteralPath $mapSource)) { throw "CMRE map source not found: $mapSource" }
$selectedMods = @($alenger.commanderToAlenger.$alengerId)
$dependencies = @($cmre.baseDependencyPaths) + @($cmre.commanderBaseDependencyPaths) + @($selectedMods | ForEach-Object { "file:Mods/7vs1/$_.SC2Mod" })
if ($ExtraMods -ne "") {
    $extraList = $ExtraMods.Split(',') | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne '' }
    # 去重：跳过已在 selectedMods（指挥官自动加载）中的 mod，避免 Document dependency 重复
    $selectedSet = [System.Collections.Generic.HashSet[string]]::new()
    foreach ($m in $selectedMods) { [void]$selectedSet.Add($m) }
    $dedupedExtra = @($extraList | Where-Object { -not $selectedSet.Contains($_) })
    if ($dedupedExtra.Count -lt $extraList.Count) {
        $skipped = @($extraList | Where-Object { $selectedSet.Contains($_) })
        Write-Host "Extra mods (skipped duplicates already in commander loadout): $($skipped -join ', ')"
    }
    foreach ($mod in $dedupedExtra) { $dependencies += "file:Mods/7vs1/$mod.SC2Mod" }
    if ($dedupedExtra.Count -gt 0) {
        Write-Host "Extra mods: $($dedupedExtra -join ', ')"
    }
}
Write-Host "CMRE Alenger selection: $MapName x $Commander"
Write-Host "On-demand packages: $($selectedMods -join ', ')"
if ($DryRun) { $dependencies | ForEach-Object { Write-Host "  $_" }; exit 0 }

function Enable-CmreSavedProfileStartup {
    param(
        [Parameter(Mandatory = $true)][string]$MapPath,
        [Parameter(Mandatory = $true)][string]$Commander,
        [switch]$SkipCountdown
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
    CMUIX_LaunchProfileOpenBank(1);
    if (BankLastCreated() != null) {
        BankValueSetFromInt(BankLastCreated(), CMUIX_LAUNCH_PROFILE_SECTION, "CreatedAt", DateTimeToInt(CurrentDateTimeGet()));
        BankValueSetFromString(BankLastCreated(), CMUIX_LAUNCH_PROFILE_SECTION, "TargetMission", CMUIX_MapSelectionCurrentMapInstance());
        BankValueSetFromString(BankLastCreated(), CMUIX_LAUNCH_PROFILE_SECTION, "TargetMap", CMUIX_MapSelectionCurrentMapInstance());
        BankSave(BankLastCreated());
        if (CMUIX_LaunchProfileValidForStartup(BankLastCreated()) == true) {
            CMUIX_LaunchProfileApply(BankLastCreated());
        }
    }
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
"@
    if ($SkipCountdown) {
        $replacementBody += "    // SkipCountdown (API mode): CMUIX_ReadyBeginCountdown() omitted to avoid Launched-state stall`r`n    return ;"
        Write-Host "DEBUG Enable-CmreSavedProfileStartup: SkipCountdown=true (API mode, no CMUIX_ReadyBeginCountdown)"
    } else {
        $replacementBody += "    Wait(1.0, c_timeReal);`r`n    CMUIX_ReadyBeginCountdown();`r`n    return ;"
    }
    $replacement = $replacementBody.Replace("`r`n", "`n").Replace("`n", "`r`n").TrimEnd("`r", "`n")
    Write-Host "DEBUG Enable-CmreSavedProfileStartup: Commander=$Commander"
    Write-Host "DEBUG replacement (first 200 chars): $($replacement.Substring(0, [Math]::Min(200, $replacement.Length)))"
    if ([regex]::IsMatch($content, [regex]::Escape($replacement))) {
        Write-Host "DEBUG: replacement already in content, skipping"
        return
    }
    $repatchPattern = '(?ms)^    if \(\(CMUIX_CoreReady == false\)\) \{ CMUIX_CoreInit\(\); \}.*?(?:CMUIX_ReadyBeginCountdown\(\);|SkipCountdown[^\r\n]*).*?return ;$'
    if ([regex]::IsMatch($content, $legacyPatchPattern)) {
        $content = [regex]::Replace($content, $legacyPatchPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $originalPattern)) {
        $content = [regex]::Replace($content, $originalPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $fallbackPattern)) {
        $content = [regex]::Replace($content, $fallbackPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $repatchPattern)) {
        Write-Host "DEBUG: repatch detected (previously patched block found), replacing with new commander/config"
        $content = [regex]::Replace($content, $repatchPattern, $replacement, 1)
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

    # Also copy adapter galaxy files so the map can call
    # lib<Prefix>_InitLib() to register TechTree unlock triggers. Without
    # this the adapter's Build/Train/Unit allow lists never execute, leaving
    # Suppressed build options (barracks/factory/starport) invisible.
    # 支持无 galaxy 触发器库的 adapter（如 Alenger6Adapter）：当 $adapterFiles 为空时跳过复制
    if ($adapterFiles.Count -gt 0) {
        $adapterRoot = Join-Path $ModsRoot "7vs1\$adapterModName.SC2Mod\Base.SC2Data"
        foreach ($name in $adapterFiles) {
            $src = Join-Path $adapterRoot $name
            if (-not (Test-Path -LiteralPath $src)) { throw "$adapterModName galaxy file not found: $src" }
            [System.IO.File]::Copy($src, (Join-Path $destinationRoot $name), $true)
        }
    }

    # RuntimeProbe galaxy files intentionally NOT copied: RuntimeProbe is
    # deprecated as runtime evidence (see docs/deprecated-runtime-probe.md).
    # Runtime evidence must come from sc2-observer.py over the SC2 API
    # websocket (-ListenPort <port>), not from map-side Bank publishing.

    $required = @("LibCOOC_h.galaxy", "LibCOOC.galaxy", "LibCOMI_h.galaxy", "LibCOMI.galaxy")
    $required += $adapterFiles
    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $destinationRoot $name))) {
            throw "CMRE Galaxy host overlay is incomplete: $name"
        }
    }
    Write-Host "CMRE Galaxy host overlay: $($libraries.Count) CMRE + $($adapterFiles.Count) $adapterModName files"
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
    # 参数化 include 和 InitLib：当 adapterFiles 为空时不注入 adapter 库引用
    $adapterInclude = ''
    $adapterInitLib = ''
    if ($adapterFiles.Count -gt 0 -and $adapterLibPrefix) {
        $adapterInclude = "`r`n" + 'include "Lib' + $adapterLibPrefix + '"'
        $adapterInitLib = "`r`n" + '    lib' + $adapterLibPrefix + '_InitLib();'
    }
    if ($mapScript -notmatch '(?m)^include "LibEFA54406"$') {
        $incReplacement = 'include "LibCOUI"' + "`r`n" + 'include "LibEFA54406"' + "`r`n" + 'include "LibPortingObserver"' + $adapterInclude
        $mapScript = $mapScript.Replace('include "LibCOUI"', $incReplacement)
    }
    if ($mapScript -notmatch 'libEFA54406_InitLib\s*\(\s*\)') {
        $initReplacement = '    libCOUI_InitLib();' + "`r`n" + '    libEFA54406_InitLib();' + $adapterInitLib
        $mapScript = $mapScript.Replace('    libCOUI_InitLib();', $initReplacement)
    }
    if ($mapScript -notmatch 'gt_PortingObserverDeadOfNightPoll_Func') {
        $mapInitAnchor = "//--------------------------------------------------------------------------------------------------`r`n// Map Initialization"
        if (-not $mapScript.Contains($mapInitAnchor)) { throw "Map initialization anchor not found in MapScript" }
        # 亡者之夜专用代码块：引用 gv_dayORNight/gv_nightNumber/gv_objective_Primary_DestroyInfestation
        # 等亡者之夜特有的全局变量。其他地图（如克哈裂痕）没有这些变量，注入会导致编译崩溃。
        # 只在亡者之夜地图注入这段代码；其他地图用空字符串占位，保持 poll trigger 通用部分可用。
        $donUpdateBlock = ''
        if ($MapName -eq "亡者之夜.SC2Map") {
            $donUpdateBlock = @'
        if (gv_objective_Primary_DestroyInfestation != c_invalidObjectiveId) {
            lv_primaryState = ObjectiveGetState(gv_objective_Primary_DestroyInfestation);
        }
        if (gv_objective_Bonus_DestroyInfestationSource != c_invalidObjectiveId) {
            lv_bonusState = ObjectiveGetState(gv_objective_Bonus_DestroyInfestationSource);
        }
        libDeadOfNightObserver_gf_Update(gv_dayORNight, gv_nightNumber,
            gv_infestedStructuresRemaining, gv_infestedStructuresTotal, lv_primaryState, lv_bonusState);
'@
        }
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
${donUpdateBlock}
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
    if (testConds) { return true; }
    if (!runActions) { return true; }
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
    // RuntimeProbe disabled: avoids API-mode crash and user requested other
    // runtime reading methods (SC2 API RequestQuery.abilities).
    // libRuntimeProbe_gf_StartProbe();
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
    // 诊断探针：出生工人训练能力为占位名（3xunlian1 → <worker>Train），实际出生
    // 建筑未必拥有该能力；构造该 Order 或对其调用 UnitOrderIsValid 会在脚本运行期
    // 抛出"技能无效"致命触发器错误，导致地图加载被 readiness 探针判失败。故跳过
    // 真实训练探测，仅发布诊断信息，避免运行期致命脚本错误。
    libPortingObserver_gf_Publish("alenger3_train_probe_result",
        "train_ability_placeholder; worker_before=" + IntToString(lv_workerBefore) + "; train_completed=false(diag_skip)", false);
    return true;
}

void gt_Alenger3TrainProbe_Init() {
    gt_Alenger3TrainProbe = TriggerCreate("gt_Alenger3TrainProbe_Func");
    TriggerExecute(gt_Alenger3TrainProbe, false, true);
}

"@
        # 参数化 pollGlue：根据 $alengerId/$startingStructure/$startingWorker/$workerCount/$vanillaRemovals 替换硬编码的 Alenger3 字面量
        $pollGlue = $pollGlue.Replace('gt_Alenger3StartingUnits', "gt_$alengerId" + 'StartingUnits').Replace('gt_Alenger3TrainProbe', "gt_$alengerId" + 'TrainProbe')
        $pollGlue = $pollGlue.Replace('"3diguoqianshaojidi"', "`"$startingStructure`"")
        $pollGlue = $pollGlue.Replace('"3diguolaogong"', "`"$startingWorker`"")
        $pollGlue = $pollGlue.Replace('"3xunlian1"', "`"$($startingWorker)Train`"")  # 训练能力名（占位，Alenger6 暂不需要）
        $pollGlue = $pollGlue.Replace('alenger3_', "$($alengerId.ToLower())_")
        $pollGlue = $pollGlue.Replace('Alenger3', $alengerId)
        # 动态生成 vanilla 单位移除代码：替换原硬编码的 7 行 gf_RemoveAllUnitsOfType
        $vanillaRemoveBlock = ""
        foreach ($u in $vanillaRemovals) {
            $vanillaRemoveBlock += "    lv_removedP1 += gf_RemoveAllUnitsOfType(1, `"$u`");`r`n"
        }
        foreach ($u in $vanillaRemovals) {
            $vanillaRemoveBlock += "    lv_removedP2 += gf_RemoveAllUnitsOfType(2, `"$u`");`r`n"
        }
        $vanillaRemoveBlock = $vanillaRemoveBlock.TrimEnd("`r", "`n")
        # 替换原硬编码的 lv_removedP1 += ... 块（连续 7 行 + 7 行 P2）
        $origRemovePattern = '(?ms)    lv_removedP1 = gf_RemoveAllUnitsOfType\(1, "CommandCenterRaynor"\);.*?lv_removedP2 \+= gf_RemoveAllUnitsOfType\(2, "SCV"\);'
        $pollGlue = [regex]::Replace($pollGlue, $origRemovePattern, $vanillaRemoveBlock)
        # 参数化 workerCount（原硬编码 for (lv_i = 0; lv_i < 5; ...)）
        $pollGlue = $pollGlue.Replace('lv_i < 5', "lv_i < $workerCount")
        $mapScript = $mapScript.Replace($mapInitAnchor, $pollGlue.Replace("`n", "`r`n") + $mapInitAnchor)
    }
    if ($mapScript -notmatch 'libDeadOfNightObserver_InitLib\s*\(\s*\)') {
        # 用 InitTriggers() 调用作为 anchor，在其前面注入 InitLib 调用。
        # 不使用 "InitGlobals();\r\nInitTriggers();" 这种相邻 anchor，因为
        # 某些地图（如克哈裂痕）在两者之间还有 InitCustomAI() 等调用。
        $initAnchor = "    InitTriggers();`r`n"
        if (-not $mapScript.Contains($initAnchor)) { throw "InitMap anchor not found in MapScript" }
        $initMapReplacement = "    libDeadOfNightObserver_InitLib();`r`n    gt_PortingObserverDeadOfNightPoll_Init();`r`n    gt_$alengerId" + "StartingUnits_Init();`r`n    gt_$alengerId" + "TrainProbe_Init();`r`n" + $initAnchor
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
    # RuntimeProbe Bank registration intentionally omitted: RuntimeProbe is
    # deprecated as runtime evidence (see docs/deprecated-runtime-probe.md).
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

    # Patch 10: CM_HeroWaitForRevive_TriggerFunc 在无英雄指挥官（如 Alenger）时
    # libCOMI_gv_cM_HeroReviver[lp_player] 为 null，执行到 UnitGetPosition 会抛
    # "无法从参数中获取 unit(0#0)" 致命错误。无英雄复活单位则直接跳过复活逻辑。
    # 注意：Galaxy 不允许在局部变量声明之前出现可执行语句，故 guard 必须放在
    # 变量声明之后。锚点用 autoE01594B5_var（该触发器函数独有的自动变量）保证
    # 只命中 CM_HeroWaitForRevive_TriggerFunc，避免误注入到其他函数（如复活时长计算）。
    # 用正则容忍声明之间的空行数量差异。
    $comiAnchor10 = 'unit autoE01594B5_var;[\s\S]*?lv_commander = libCOOC_gf_ActiveCommanderForPlayer\(lp_player\);'
    $comiPatch10 = 'unit autoE01594B5_var;' + "`r`n" + "`r`n" + `
        '    // CMRE patch: 无英雄指挥官（如 Alenger）的 cM_HeroReviver 为 null，跳过复活逻辑' + "`r`n" + `
        '    if (libCOMI_gv_cM_HeroReviver[lp_player] == null) { return true; }' + "`r`n" + `
        '    lv_commander = libCOOC_gf_ActiveCommanderForPlayer(lp_player);'
    if (-not $comi.Contains($comiPatch10)) {
        if (-not [regex]::IsMatch($comi, $comiAnchor10)) { throw "LibCOMI patch 10 anchor not found" }
        $comi = [regex]::Replace($comi, $comiAnchor10, $comiPatch10)
        $patchCount++
    }

    # Patch 11: libCOMI_gf_CM_CommanderVOSend - 当 lp_vOSound 为 null（指挥官未配置
    # VO lines，如 Alenger6）时，SoundPlayForPlayer 会抛 "无法从'sCreateSound'的参数中
    # 获取'sound'(值：0)" 触发器错误。跳过 null soundlink 的播放，避免运行时错误。
    # 该错误在克哈裂痕等地图上单位被攻击时立即触发（libCOMI_gt_CM_VOEnemySpotted_Func）。
    $comiAnchor11 = 'void libCOMI_gf_CM_CommanderVOSend (int lp_listenerPlayer, soundlink lp_vOSound, playergroup lp_targetPlayers) {
    // Automatic Variable Declarations
    // Implementation
    SoundSetListenerGender(lp_vOSound, libCOOC_gf_CC_CommanderGender(libCOOC_gf_ActiveCommanderForPlayer(lp_listenerPlayer)));'
    $comiPatch11 = 'void libCOMI_gf_CM_CommanderVOSend (int lp_listenerPlayer, soundlink lp_vOSound, playergroup lp_targetPlayers) {
    // Automatic Variable Declarations
    // Implementation
    if ((lp_vOSound == null)) { return; } // CMRE patch: guard null soundlink (VO line not configured for this commander)
    SoundSetListenerGender(lp_vOSound, libCOOC_gf_CC_CommanderGender(libCOOC_gf_ActiveCommanderForPlayer(lp_listenerPlayer)));'
    if (-not $comi.Contains($comiPatch11)) {
        if (-not $comi.Contains($comiAnchor11)) { throw "LibCOMI patch 11 anchor not found" }
        $comi = $comi.Replace($comiAnchor11, $comiPatch11); $patchCount++
    }

    [System.IO.File]::WriteAllText($comiPath, $comi, [System.Text.UTF8Encoding]::new($false))

    Write-Host "CMRE core runtime error patches applied: $patchCount locations"
}

function Write-CmreLaunchProfile {
    $banksRoot = "C:\Users\22448\Documents\StarCraft II\Banks"
    [System.IO.Directory]::CreateDirectory($banksRoot) | Out-Null
    $doc = [xml]'<Bank version="1"><Section name="CMUI|LaunchProfile" /></Bank>'
    # ModeInstance 必须与 Mode 一致，否则 CMRE 在读取侧会用 ModeInstance 推导模式
    # （CMUIX_LaunchProfileModeIndex）。1=Standard / 2=MutatorChallenges / 3=CustomMutators，
    # 与 CMUIX_LaunchProfileModeInstance 的映射完全对应。
    $modeInstance = switch ($Mode) {
        2 { "MutatorChallenges" }
        3 { "CustomMutators" }
        default { "Standard" }
    }
    $values = [ordered]@{
        Valid = @("int", "1"); Version = @("int", "1");
        CreatedAt = @("int", [string][int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds());
        TimeoutSeconds = @("int", "600");
        Mode = @("int", [string]$Mode);
        ModeInstance = @("string", $modeInstance);
        DifficultyBase = @("int", [string]$DifficultyBase);
        DifficultyPlus = @("int", [string]$DifficultyPlus);
        TargetMission = @("string", "AC_MeinhoffDayNight");
        TargetMap = @("string", "AC_MeinhoffDayNight");
        'Player|1|Commander' = @("string", $Commander);
        'Player|2|Commander' = @("string", $Commander)
    }
    if ($Enemy -ne "") { $values['Enemy'] = @("string", $Enemy) }
    # 解析 Mutators 参数：逗号分隔的 id 列表，可选 ":enhanced" 后缀
    # 示例: "Avenger,Barrier:enhanced,Blizzard"
    if ($Mutators -ne "") {
        # 注意：管道在单元素时会展平为标量，必须用 @() 强制为数组，
        # 否则 $mutatorList[0] 会变成字符串索引返回首个字符（如 "L" 而非 "LazyWorkers"）。
        $mutatorList = @($Mutators -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ -ne "" })
        $values['MutatorCount'] = @("int", [string]$mutatorList.Count)
        for ($i = 0; $i -lt $mutatorList.Count; $i++) {
            $parts = $mutatorList[$i] -split ':'
            $mutId = $parts[0].Trim()
            $enhanced = if ($parts.Length -gt 1 -and $parts[1].Trim() -eq "enhanced") { "1" } else { "0" }
            $values["Mutator|$($i + 1)|Id"] = @("string", $mutId)
            $values["Mutator|$($i + 1)|Enhanced"] = @("int", $enhanced)
        }
    }
    foreach ($entry in $values.GetEnumerator()) {
        $key = $doc.CreateElement("Key"); $key.SetAttribute("name", $entry.Key)
        $value = $doc.CreateElement("Value"); $value.SetAttribute($entry.Value[0], $entry.Value[1])
        $key.AppendChild($value) | Out-Null; $doc.Bank.Section.AppendChild($key) | Out-Null
    }
    $settings = [System.Xml.XmlWriterSettings]::new(); $settings.Indent = $true; $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.Xml.XmlWriter]::Create((Join-Path $banksRoot "CMCoopLaunchProfile.SC2Bank"), $settings)
    try { $doc.Save($writer) } finally { $writer.Dispose() }
    Write-Host "CMCoopLaunchProfile 银行已写入: Mode=$Mode, DifficultyBase=$DifficultyBase, DifficultyPlus=$DifficultyPlus, Enemy='$Enemy', Mutators='$Mutators'"
}

$lock = Acquire-TestLock -TestType "cmre_alenger" -MapName $MapName -Commander $Commander
try {
    Stop-RunningSc2
    # Stop-RunningSc2 only targets SC2_x64/SC2Switcher_x64, but the live process
    # is often named "SC2". Stop it as well so Clear-GameLogs does not hit locked
    # SystemInfo.txt (which causes the launcher to abort with IOException).
    Get-Process -Name "SC2","StarCraft II" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep 2
    Clear-GameLogs
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
    if ($ListenPort -gt 0) {
        # API 模式：不 SkipCountdown，让 CMUIX_ReadyBeginCountdown() 执行以触发游戏开始。
        # 之前 SkipCountdown=true 是为了"避免 Launched-state stall"，但实测跳过后 SC2 仍卡在 Launched
        # （因为游戏开始触发器被跳过）。改为不跳过，让 galaxy 触发器完整执行。
        Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander
    } else {
        Enable-CmreSavedProfileStartup -MapPath $liveMap -Commander $Commander
    }
    # Install-CmreDynamicObserver 必须始终调用：
    #   - 注入 gt_Alenger3StartingUnits_Init（创建 5 个 3diguolaogong 工人 + 前哨基地）
    #   - 注入 libA3ADAPTER_InitLib（科技树解锁）
    #   - 移除 vanilla 单位（CommandCenterRaynor/SCVRaynor 等）
    # API 模式下 NeuroIntegration Bank 不会被读取（数据通过 SC2 API 读取），
    # 但 libEFA54406_gf_Publish 已有 null guard（LibPortingObserver.galaxy:5），
    # 且实际崩溃根因是 -listen 与地图路径互斥，与 NeuroIntegration 注入无关。
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
    if ($ListenPort -gt 0) {
        # API 模式 + 地图同时加载：用 SC2Switcher -listen <host> -port <port> -e "<map>" 启动。
        # 关键（Base97425 实机验证 2026-07-25）：
        #   - SC2 静默忽略 -listenPort，必须用 -listen/-port 格式
        #   - SC2_x64.exe 直接启动会崩溃（Battle.net auth broker missing），必须通过 Switcher
        #   - 工作目录必须是 SC2 安装根目录，否则 SC2 回退到 6119
        #   - SC2Switcher 必须带 -e <map> 才会转发 -listen/-port 给 SC2_x64（无 -e 时 SC2 只监听 6119）
        #   - -e 模式下 SC2 加载地图 + 开 API 端口，galaxy 触发器执行（含 CMUIX_ReadyBeginCountdown）
        #   - 不用 Wait-GameReady：它检测 Switcher 进程，而 Switcher 启动 SC2_x64 后
        #     会退出，被误判为"Game process exited (crash)"。改用端口轮询。
        #   - 不 SkipCountdown：让 CMUIX_ReadyBeginCountdown() 执行以触发游戏开始（进入 in_game）。
        #     客户端用 --skip-create 直接连接（不调 CreateGame/JoinGame，避免与已加载的游戏冲突）。
        $argList = @("-listen","127.0.0.1","-port","$ListenPort","-e","`"$liveMap`"")
        Write-Host "SC2 API mode: launching SC2Switcher with -listen 127.0.0.1 -port $ListenPort -e `"$liveMap`""
        Write-Host "SC2 API will listen on 127.0.0.1:$ListenPort"
        Write-Host "Working directory: $Sc2Root"
        Write-Host "Live map: $liveMap (SC2 loads it on startup, client uses --skip-create)"
        Start-Process -FilePath $switcher -ArgumentList $argList -WorkingDirectory $Sc2Root
        # API 模式下轮询 TCP 端口，直到 SC2 API 监听就绪（最多等 120s）。
        Write-Host "SC2 API mode: polling TCP 127.0.0.1:$ListenPort until listening (max 120s)..."
        $deadline = (Get-Date).AddSeconds(120)
        $listening = $false
        while ((Get-Date) -lt $deadline) {
            $proc = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue
            if ($null -eq $proc) {
                Start-Sleep -Seconds 2
                continue
            }
            try {
                $tcp = New-Object System.Net.Sockets.TcpClient
                $iar = $tcp.BeginConnect("127.0.0.1", $ListenPort, $null, $null)
                $ok = $iar.AsyncWaitHandle.WaitOne(800)
                if ($ok -and $tcp.Connected) {
                    $tcp.EndConnect($iar)
                    $tcp.Close()
                    $listening = $true
                    break
                }
                $tcp.Close()
            } catch { }
            Start-Sleep -Seconds 2
        }
        if (-not $listening) {
            $stillRunning = Get-Process -Name "SC2_x64" -ErrorAction SilentlyContinue
            if ($null -eq $stillRunning) {
                throw "SC2 API mode: SC2_x64.exe exited before API port $ListenPort opened (crash or auth broker missing). Check GameLogs."
            } else {
                throw "SC2 API mode: SC2_x64.exe is running but API port $ListenPort did not open within 120s."
            }
        }
        Write-Host "SC2 API mode: API listening on 127.0.0.1:$ListenPort (SC2_x64 PID=$($proc.Id))"
        # 给地图加载额外宽限时间：端口监听后 galaxy 触发器仍在执行（CMUIX_ReadyBeginCountdown 倒计时）。
        # 轮询 GameLogs 是否出现 ScriptError 或地图加载完成信号（Alerts.txt）。
        $gameLogsDir = Join-Path ([Environment]::GetFolderPath("MyDocuments")) "StarCraft II\GameLogs"
        $latestDir = Get-ChildItem -LiteralPath $gameLogsDir -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($null -ne $latestDir) {
            $deadline2 = (Get-Date).AddSeconds(60)
            while ((Get-Date) -lt $deadline2) {
                $scriptErr = Get-ChildItem -LiteralPath $latestDir.FullName -Filter "ScriptError*.txt" -ErrorAction SilentlyContinue
                if ($null -ne $scriptErr -and $scriptErr.Count -gt 0) {
                    Write-Host "SC2 API mode: ScriptError detected, map load likely failed: $($scriptErr[0].FullName)"
                    break
                }
                $alerts = Get-ChildItem -LiteralPath $latestDir.FullName -Filter "Alerts*.txt" -ErrorAction SilentlyContinue
                if ($null -ne $alerts -and $alerts.Count -gt 0) {
                    $alertsContent = Get-Content $alerts[0].FullName -Raw -ErrorAction SilentlyContinue
                    if ($alertsContent -match 'GameStart|MapLoad|UILoad|loading complete') {
                        Write-Host "SC2 API mode: map load signal detected in Alerts.txt"
                        break
                    }
                }
                Start-Sleep -Seconds 2
            }
        }
        Write-Host "SC2 API mode: ready, client can connect with --skip-create"
    } else {
        # 普通模式：地图路径作为位置参数传给 Switcher，SC2 启动后自动加载地图
        $args = @("`"$liveMap`"")
        Start-Process -FilePath $switcher -ArgumentList $args -WorkingDirectory (Split-Path -Parent $switcher)
        $exitCode = Wait-GameReady -ScriptsRoot (Join-Path $LegacyRoot "scripts")
        if ($exitCode -ne 0) { throw "SC2 readiness check failed with exit code $exitCode" }
    }
} finally { Release-TestLock -LockContext $lock }
