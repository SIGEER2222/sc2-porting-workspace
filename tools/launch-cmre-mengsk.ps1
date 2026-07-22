[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$MapName, [Parameter(Mandatory = $true)][string]$Commander, [switch]$DryRun, [switch]$NoLaunch)
$ErrorActionPreference = "Stop"
$WorkspaceRoot = Split-Path -Parent $PSScriptRoot
$Sc2WorkspaceRoot = Split-Path -Parent $WorkspaceRoot
$LegacyRoot = Join-Path $Sc2WorkspaceRoot "合作指挥官-起义狂潮"
$Sc2Root = "E:\SC2\SC2new\StarCraft II"
$script:LauncherScriptsRoot = Join-Path $LegacyRoot "scripts\sc2-launcher"
. (Join-Path $script:LauncherScriptsRoot "common.ps1")
. (Join-Path $script:LauncherScriptsRoot "mod-sync.ps1")
. (Join-Path $script:LauncherScriptsRoot "map-sync.ps1")
. (Join-Path $script:LauncherScriptsRoot "document-dependencies.ps1")
. (Join-Path $script:LauncherScriptsRoot "test-lock.ps1")
. (Join-Path $LegacyRoot "scripts\commander-power-metadata.ps1")
. (Join-Path $LegacyRoot "scripts\sc2\campaignxcore-bank.ps1")

# Mengsk 版：不做 Alenger 正则限制，接受任意标准合作指挥官 ID（如 TerranMengsk）。
# 依赖：CMRE 核心 + CommanderUnits_<Name>（由 Get-CommanderUnitsModName 解析）。
function Convert-TestCommanderToCommanderPowerKey {
    param([string]$Commander)
    return (Convert-CommanderPowerCommanderToBankKey -Commander $Commander -WorkspaceRoot $LegacyRoot)
}
function Get-CommanderUnitsModName {
    param([string]$Commander)
    $map = @{
        "TerranRaynor"   = "Raynor";  "TerranRaynorX"  = "RaynorX"
        "TerranNova"     = "Nova";    "TerranSwann"    = "Swann"
        "TerranHorner"   = "Horner";  "TerranMengsk"   = "Mengsk"
        "TerranTychus"   = "TychusXM"
        "ZergKerrigan"   = "Kerrigan"; "ZergAbathur"  = "Abathur"
        "ZergZagara"     = "Zagara";   "ZergStukov"   = "Stukov"
        "ZergDehaka"     = "Dehaka";   "ZergStetmann" = "Stetmann"
        "ProtossArtanis" = "Artanis"; "ProtossVorazun" = "Vorazun"
        "ProtossKarax"   = "Karax";   "ProtossFenix"   = "Fenix"
        "ProtossAlarak"  = "Alarak";  "ProtossZeratul" = "Zeratul"
    }
    if ($map.ContainsKey($Commander)) { return "CommanderUnits_$($map[$Commander])" }
    throw "Unsupported commander: $Commander"
}

$cmre = Get-Content -LiteralPath (Join-Path $WorkspaceRoot "config\cmre-alenger-dependencies.json") -Raw | ConvertFrom-Json
$commanderUnitsMod = Get-CommanderUnitsModName -Commander $Commander
$mapSource = Join-Path $LegacyRoot "Maps\CMRE\$MapName"
if (-not (Test-Path -LiteralPath $mapSource)) { throw "CMRE map source not found: $mapSource" }
if ($MapName -ne "亡者之夜.SC2Map") { throw "No CMRE auto-launch profile is registered for $MapName" }
$dependencies = @($cmre.baseDependencyPaths) + @("file:Mods/7vs1/$commanderUnitsMod.SC2Mod")
Write-Host "CMRE Mengsk selection: $MapName x $Commander"
Write-Host "Commander units mod: $commanderUnitsMod"
if ($DryRun) { $dependencies | ForEach-Object { Write-Host "  $_" }; exit 0 }

function Enable-CmreSavedProfileStartup {
    param([Parameter(Mandatory = $true)][string]$MapPath, [Parameter(Mandatory = $true)][string]$Commander)
    $path = Join-Path $MapPath "Base.SC2Data\LibCOOC.galaxy"
    if (-not (Test-Path -LiteralPath $path)) { throw "Map-level LibCOOC.galaxy not found: $path" }
    $content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
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
    if ([regex]::IsMatch($content, [regex]::Escape($replacement))) { return }
    # 匹配已 patch 的任意 commander 状态（前一次运行可能留下其他 commander 的 patch）
    $prePatchedPattern = '(?m)^    if \(\(CMUIX_CoreReady == false\)\) \{ CMUIX_CoreInit\(\); \}\r?\n    CMUIX_StartupLoadPersistentProfiles\(\);\r?\n    CMUIX_HistoryPrunePendingRecordsAll\(\);\r?\n    libCOTF_gv_sELECTED_Commander\[1\] = "[^"]+";\r?\n    libCOTF_gv_sELECTED_Commander_Random\[1\] = false;\r?\n    libCOOC_gf_CC_PlayerCommanderSet\(1, "[^"]+"\);\r?\n    libCOUI_gv_cU_CommanderSelection\[1\] = "[^"]+";\r?\n    libCOUI_gv_cU_CommanderSelect_PlayerReady\[1\] = true;\r?\n    libCOUI_gf_CU_CommanderFinalizeStates\(1\);\r?\n    libCOTF_gv_sELECTED_Commander\[2\] = "[^"]+";\r?\n    libCOTF_gv_sELECTED_Commander_Random\[2\] = false;\r?\n    libCOOC_gf_CC_PlayerCommanderSet\(2, "[^"]+"\);\r?\n    libCOUI_gv_cU_CommanderSelection\[2\] = "[^"]+";\r?\n    libCOUI_gv_cU_CommanderSelect_PlayerReady\[2\] = true;\r?\n    libCOUI_gf_CU_CommanderFinalizeStates\(2\);\r?\n    Wait\(1\.0, c_timeReal\);\r?\n    CMUIX_ReadyBeginCountdown\(\);\r?\n    return ;$'
    if ([regex]::IsMatch($content, $legacyPatchPattern)) {
        $content = [regex]::Replace($content, $legacyPatchPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $originalPattern)) {
        $content = [regex]::Replace($content, $originalPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $fallbackPattern)) {
        $content = [regex]::Replace($content, $fallbackPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $prePatchedPattern)) {
        $content = [regex]::Replace($content, $prePatchedPattern, $replacement, 1)
    } else { throw "CMRE saved-profile startup anchor not found" }
    [System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
    Write-Host "CMRE saved-profile startup patch applied to map: $path"
}

function Install-CmreGalaxyHostOverlay {
    param([Parameter(Mandatory = $true)][string]$ModsRoot, [Parameter(Mandatory = $true)][string]$MapPath)
    # Mengsk 版：只复制 CMRE 核心 galaxy 文件，不安装 Alenger3Adapter。
    $sourceRoot = Join-Path $ModsRoot "CMRE\CMRE_Core_Triggers.SC2Mod\Base.SC2Data"
    $destinationRoot = Join-Path $MapPath "Base.SC2Data"
    $libraries = Get-ChildItem -LiteralPath $sourceRoot -File -Filter "Lib*.galaxy" | Sort-Object Name
    if ($libraries.Count -eq 0) { throw "CMRE Galaxy host libraries not found: $sourceRoot" }
    [System.IO.Directory]::CreateDirectory($destinationRoot) | Out-Null
    foreach ($library in $libraries) {
        [System.IO.File]::Copy($library.FullName, (Join-Path $destinationRoot $library.Name), $true)
    }
    $required = @("LibCOOC_h.galaxy", "LibCOOC.galaxy", "LibCOMI_h.galaxy", "LibCOMI.galaxy")
    foreach ($name in $required) {
        if (-not (Test-Path -LiteralPath (Join-Path $destinationRoot $name))) {
            throw "CMRE Galaxy host overlay is incomplete: $name"
        }
    }
    Write-Host "CMRE Galaxy host overlay: $($libraries.Count) CMRE files (no Alenger3Adapter)"
}

function Install-CmreDynamicObserver {
    param([Parameter(Mandatory = $true)][string]$MapPath)
    $neuroRoot = Join-Path $Sc2WorkspaceRoot "tools\SC2-Neuro-API-Integration"
    $observerRoot = Join-Path $WorkspaceRoot "projects\cmre-porting\runtime"
    $adapterRoot = Join-Path $WorkspaceRoot "projects\cmre-porting\adapters\dead-of-night"
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
    $legacyColorCall = '            libEFA54406_gv_displayNameText = TextWithColor(libEFA54406_gv_displayNameText, Color(100.00, 50.20, 75.29));'
    if ($efa.Contains($legacyColorCall)) {
        $efa = $efa.Replace($legacyColorCall, '            // CMRE adapter: display text retained without incompatible color conversion.')
    }
    # 修复 Executeactionsglobal_Func 信号量阻塞 bug（与 Alenger 版相同）
    $execMapAnchor = '    BankSave(BankLastCreated());' + "`r`n" +
                     '    Wait(0.1, c_timeReal);' + "`r`n" +
                     '    TriggerSendEvent("execute_actions_map");' + "`r`n" +
                     '    return true;'
    $execMapPatch = '    BankSave(BankLastCreated());' + "`r`n" +
                    '    Wait(0.1, c_timeReal);' + "`r`n" +
                    '    TriggerSendEvent("execute_actions_map");' + "`r`n" +
                    '    libEFA54406_gv_bankwriteallowed = true;' + "`r`n" +
                    '    return true;'
    if ($efa.Contains($execMapAnchor)) { $efa = $efa.Replace($execMapAnchor, $execMapPatch) }
    [System.IO.File]::WriteAllText($efaPath, $efa, [System.Text.UTF8Encoding]::new($false))

    $mapScriptPath = Join-Path $MapPath "MapScript.galaxy"
    $mapScript = [System.IO.File]::ReadAllText($mapScriptPath, [System.Text.Encoding]::UTF8)
    if ($mapScript -notmatch '(?m)^include "LibEFA54406"$') {
        $mapScript = $mapScript.Replace('include "LibCOUI"', "include `"LibCOUI`"`r`ninclude `"LibEFA54406`"`r`ninclude `"LibPortingObserver`"")
    }
    if ($mapScript -notmatch 'libEFA54406_InitLib\s*\(\s*\)') {
        $mapScript = $mapScript.Replace('    libCOUI_InitLib();', "    libCOUI_InitLib();`r`n    libEFA54406_InitLib();`r`n    libPortingObserver_InitLib();")
    }
    # Mengsk 版：只注入 poll trigger，不注入 Alenger3StartingUnits/Alenger3TrainProbe
    if ($mapScript -notmatch 'gt_PortingObserverDeadOfNightPoll_Func') {
        $mapInitAnchor = "//--------------------------------------------------------------------------------------------------`r`n// Map Initialization"
        if (-not $mapScript.Contains($mapInitAnchor)) { throw "Map initialization anchor not found in MapScript" }
        $pollGlue = @"
include "LibDeadOfNightObserver"

trigger gt_PortingObserverDeadOfNightPoll;

bool gt_PortingObserverDeadOfNightPoll_Func(bool testConds, bool runActions) {
    int lv_primaryState = -1;
    int lv_bonusState = -1;
    if (testConds) { return true; }
    if (!runActions) { return true; }
    libPortingObserver_gf_Publish("poll_trigger_started", "DeadOfNight poll trigger is running (Mengsk)", false);
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
        libPortingObserver_gf_PublishAlengerStructureProbe();
        libPortingObserver_gf_PublishAlengerCommandCardDump();
        Wait(10.0, c_timeReal);
    }
    return true;
}

void gt_PortingObserverDeadOfNightPoll_Init() {
    gt_PortingObserverDeadOfNightPoll = TriggerCreate("gt_PortingObserverDeadOfNightPoll_Func");
    TriggerExecute(gt_PortingObserverDeadOfNightPoll, false, false);
}

"@
        $mapScript = $mapScript.Replace($mapInitAnchor, $pollGlue.Replace("`n", "`r`n") + $mapInitAnchor)
    }
    if ($mapScript -notmatch 'libDeadOfNightObserver_InitLib\s*\(\s*\)') {
        $initAnchor = "    InitGlobals();`r`n    InitTriggers();"
        if (-not $mapScript.Contains($initAnchor)) { throw "InitMap anchor not found in MapScript" }
        $mapScript = $mapScript.Replace($initAnchor, "    InitGlobals();`r`n    libDeadOfNightObserver_InitLib();`r`n    gt_PortingObserverDeadOfNightPoll_Init();`r`n    InitTriggers();")
    }
    [System.IO.File]::WriteAllText($mapScriptPath, $mapScript, [System.Text.UTF8Encoding]::new($false))

    $bankListPath = Join-Path $MapPath "BankList.xml"
    [xml]$bankList = [System.IO.File]::ReadAllText($bankListPath, [System.Text.Encoding]::UTF8)
    if (@($bankList.BankList.Bank | Where-Object { $_.Name -eq "NeuroIntegration" -and $_.Player -eq "1" }).Count -eq 0) {
        $bank = $bankList.CreateElement("Bank")
        $bank.SetAttribute("Name", "NeuroIntegration")
        $bank.SetAttribute("Player", "1")
        $bankList.BankList.AppendChild($bank) | Out-Null
        $settings = [System.Xml.XmlWriterSettings]::new(); $settings.Indent = $true; $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
        $writer = [System.Xml.XmlWriter]::Create($bankListPath, $settings)
        try { $bankList.Save($writer) } finally { $writer.Dispose() }
    }
}

function Patch-CmreCoreRuntimeErrors {
    param([Parameter(Mandatory = $true)][string]$MapPath)
    $baseData = Join-Path $MapPath "Base.SC2Data"
    $patchCount = 0

    $cotfPath = Join-Path $baseData "LibCOTF.galaxy"
    if (-not (Test-Path -LiteralPath $cotfPath)) { throw "LibCOTF.galaxy not found: $cotfPath" }
    $cotf = [System.IO.File]::ReadAllText($cotfPath, [System.Text.Encoding]::UTF8)

    $cotfAnchor1 = '    libCOTF_gv_player = EventPlayerEffectUsedUnitOwner(c_effectPlayerCaster);'
    $cotfPatch1 = '    libCOTF_gv_player = 1; // CMRE patch: InitGlobals has no effect event context'
    if (-not $cotf.Contains($cotfPatch1)) {
        if (-not $cotf.Contains($cotfAnchor1)) { throw "LibCOTF patch 1 anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor1, $cotfPatch1); $patchCount++
    }

    $cotfAnchor2 = '    GameSetSeed(StringToInt((PlayerHandle(1) + PlayerHandle(2))));'
    $cotfPatch2 = '    // CMRE patch: skip PlayerHandle-based seed (StringToInt cannot parse handle string)'
    if (-not $cotf.Contains($cotfPatch2)) {
        if (-not $cotf.Contains($cotfAnchor2)) { throw "LibCOTF patch 2 anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor2, $cotfPatch2); $patchCount++
    }

    $cotfAnchor2b = '    GameSetSeed(StringToInt(DateTimeToString(CurrentDateTimeGet())));'
    $cotfPatch2b = '    // CMRE patch: skip DateTime-based seed (StringToInt cannot parse datetime string; while loop below provides continuous random seed)'
    if (-not $cotf.Contains($cotfPatch2b)) {
        if (-not $cotf.Contains($cotfAnchor2b)) { throw "LibCOTF patch 2b anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor2b, $cotfPatch2b); $patchCount++
    }

    $cotfAnchor3 = '    DialogSetVisible(libCOTF_gv_uT_AIVisionDialog, PlayerGroupAll(), false);'
    $cotfPatch3 = '    if (libCOTF_gv_uT_AIVisionDialog != c_invalidDialogId) { DialogSetVisible(libCOTF_gv_uT_AIVisionDialog, PlayerGroupAll(), false); } // CMRE patch: guard invalid dialog handle'
    if (-not $cotf.Contains($cotfPatch3)) {
        if (-not $cotf.Contains($cotfAnchor3)) { throw "LibCOTF patch 3 anchor not found" }
        $cotf = $cotf.Replace($cotfAnchor3, $cotfPatch3); $patchCount++
    }

    [System.IO.File]::WriteAllText($cotfPath, $cotf, [System.Text.UTF8Encoding]::new($false))

    $couiPath = Join-Path $baseData "LibCOUI.galaxy"
    if (-not (Test-Path -LiteralPath $couiPath)) { throw "LibCOUI.galaxy not found: $couiPath" }
    $coui = [System.IO.File]::ReadAllText($couiPath, [System.Text.Encoding]::UTF8)

    $couiAnchor4 = '    libNtve_gf_SetDialogItemUnitGroup(libCOUI_gv_cU_GPCmdPanel[lp_player], libCOUI_gv_cU_GPCasterGroup[lp_player], PlayerGroupSingle(lp_player));'
    $couiPatch4 = '    if (libCOUI_gv_cU_GPCmdPanel[lp_player] != c_invalidDialogControlId) { libNtve_gf_SetDialogItemUnitGroup(libCOUI_gv_cU_GPCmdPanel[lp_player], libCOUI_gv_cU_GPCasterGroup[lp_player], PlayerGroupSingle(lp_player)); } // CMRE patch: guard invalid control handle'
    if (-not $coui.Contains($couiPatch4)) {
        if (-not $coui.Contains($couiAnchor4)) { throw "LibCOUI patch 4 anchor not found" }
        $coui = $coui.Replace($couiAnchor4, $couiPatch4); $patchCount++
    }

    [System.IO.File]::WriteAllText($couiPath, $coui, [System.Text.UTF8Encoding]::new($false))

    $comiPath = Join-Path $baseData "LibCOMI.galaxy"
    if (-not (Test-Path -LiteralPath $comiPath)) { throw "LibCOMI.galaxy not found: $comiPath" }
    $comi = [System.IO.File]::ReadAllText($comiPath, [System.Text.Encoding]::UTF8)

    $comiAnchor5 = '    lv_commanderDefaultDecalString = CatalogFieldValueGet(c_gameCatalogTexture, lv_commanderDefaultDecal, "File", c_playerAny);'
    $comiPatch5 = '    if (lv_commanderDefaultDecal != "") { lv_commanderDefaultDecalString = CatalogFieldValueGet(c_gameCatalogTexture, lv_commanderDefaultDecal, "File", c_playerAny); } // CMRE patch: guard empty decal entry'
    if (-not $comi.Contains($comiPatch5)) {
        if (-not $comi.Contains($comiAnchor5)) { throw "LibCOMI patch 5 anchor not found" }
        $comi = $comi.Replace($comiAnchor5, $comiPatch5); $patchCount += 2
    }

    $comiAnchor7 = '    lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroNormalReviveBehavior(lp_player), "Duration", lp_player));'
    $comiPatch7 = '    if (libCOOC_gf_CC_PlayerHeroNormalReviveBehavior(lp_player) != "") { lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroNormalReviveBehavior(lp_player), "Duration", lp_player)); } if (lv_reviveDuration <= 0.0) { lv_reviveDuration = 60.0; } // CMRE patch: guard empty normal revive behavior entry'
    if (-not $comi.Contains($comiPatch7)) {
        if (-not $comi.Contains($comiAnchor7)) { throw "LibCOMI patch 7 anchor not found" }
        $comi = $comi.Replace($comiAnchor7, $comiPatch7); $patchCount++
    }

    $comiAnchor8 = '    lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroFirstReviveBehavior(lp_player), "Duration", lp_player));'
    $comiPatch8 = '    if (libCOOC_gf_CC_PlayerHeroFirstReviveBehavior(lp_player) != "") { lv_reviveDuration = StringToFixed(CatalogFieldValueGet(c_gameCatalogBehavior, libCOOC_gf_CC_PlayerHeroFirstReviveBehavior(lp_player), "Duration", lp_player)); } if (lv_reviveDuration <= 0.0) { lv_reviveDuration = 60.0; } // CMRE patch: guard empty first revive behavior entry'
    if (-not $comi.Contains($comiPatch8)) {
        if (-not $comi.Contains($comiAnchor8)) { throw "LibCOMI patch 8 anchor not found" }
        $comi = $comi.Replace($comiAnchor8, $comiPatch8); $patchCount++
    }

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

$lock = Acquire-TestLock -TestType "cmre_mengsk" -MapName $MapName -Commander $Commander
try {
    Stop-RunningSc2; Clear-GameLogs
    Sync-ModSet -ModRelPaths $cmre.baseMods -ProjRoot $LegacyRoot -Sc2Root $Sc2Root
    # Mengsk mod 在 7vs1 目录下，用 mod-sync 同步
    Sync-ModSet -ModRelPaths @("7vs1\$commanderUnitsMod.SC2Mod") -ProjRoot $LegacyRoot -Sc2Root $Sc2Root
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
    Set-CampaignXCoreTestRunId -RunId "CMREMengsk"
    Write-CmreLaunchProfile
    if ($NoLaunch) { Write-Host "CMRE Mengsk composition staged: $liveMap"; exit 0 }
    $switcher = Join-Path $Sc2Root "Support64\SC2Switcher_x64.exe"
    Start-Process -FilePath $switcher -ArgumentList "-loadmap `"$liveMap`""
    $exitCode = Wait-GameReady -ScriptsRoot (Join-Path $LegacyRoot "scripts")
    if ($exitCode -ne 0) { throw "SC2 readiness check failed with exit code $exitCode" }
} finally { Release-TestLock -LockContext $lock }
