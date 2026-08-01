$ErrorActionPreference = "Stop"

function Get-CmreOverlayRoot {
    return (Join-Path (Split-Path -Parent $PSScriptRoot) "overlays\cmre-alenger")
}

function Read-CmreUtf8 {
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { throw "Overlay input not found: $Path" }
    return [System.IO.File]::ReadAllText($Path, [System.Text.Encoding]::UTF8)
}

function Write-CmreUtf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Assert-CmreGalaxyToken {
    param([Parameter(Mandatory = $true)][string]$Value, [Parameter(Mandatory = $true)][string]$Name)
    if ($Value -notmatch '^[A-Za-z0-9_]+$') {
        throw "$Name contains unsafe characters for Galaxy template substitution: $Value"
    }
}

function Expand-CmreTemplate {
    param(
        [Parameter(Mandatory = $true)][string]$TemplatePath,
        [Parameter(Mandatory = $true)][hashtable]$Values
    )
    $text = Read-CmreUtf8 -Path $TemplatePath
    foreach ($key in $Values.Keys) {
        $text = $text.Replace("{{$key}}", [string]$Values[$key])
    }
    if ($text -match '{{[A-Z0-9_]+}}') {
        throw "Unresolved placeholder in template $TemplatePath"
    }
    return $text
}

function Add-CmreLinesAfter {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Anchor,
        [Parameter(Mandatory = $true)][string[]]$Lines
    )
    if (-not $Content.Contains($Anchor)) { throw "Anchor not found: $Anchor" }
    $missing = @($Lines | Where-Object { $_ -ne "" -and -not $Content.Contains($_) })
    if ($missing.Count -eq 0) { return $Content }
    return $Content.Replace($Anchor, ($Anchor + [Environment]::NewLine + ($missing -join [Environment]::NewLine)))
}

function Add-CmreBlockBefore {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Anchor,
        [Parameter(Mandatory = $true)][string]$Marker,
        [Parameter(Mandatory = $true)][string]$Block
    )
    if ($Content.Contains($Marker)) { return $Content }
    if (-not $Content.Contains($Anchor)) { throw "Anchor not found: $Anchor" }
    return $Content.Replace($Anchor, ($Block.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $Anchor))
}

function Replace-CmreFirstRegex {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Pattern,
        [Parameter(Mandatory = $true)][string]$Replacement,
        [Parameter(Mandatory = $true)][string]$AlreadyMarker,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($Content.Contains($AlreadyMarker)) { return $Content }
    if (-not [regex]::IsMatch($Content, $Pattern)) { throw "$Label anchor not found" }
    return [regex]::Replace($Content, $Pattern, $Replacement, 1)
}

function Copy-CmreOverlayFiles {
    param(
        [Parameter(Mandatory = $true)][object[]]$Files,
        [Parameter(Mandatory = $true)][string]$DestinationRoot
    )
    [System.IO.Directory]::CreateDirectory($DestinationRoot) | Out-Null
    foreach ($file in $Files) {
        if (-not (Test-Path -LiteralPath $file.Source)) { throw "Overlay source not found: $($file.Source)" }
        [System.IO.File]::Copy($file.Source, (Join-Path $DestinationRoot $file.Name), $true)
    }
}

function Initialize-CmreRuntimeListenerBank {
    $banksRoot = Join-Path $env:USERPROFILE "Documents\StarCraft II\Banks"
    $bankXml = '<?xml version="1.0" encoding="utf-8"?>' + [Environment]::NewLine + '<Bank version="1">' + [Environment]::NewLine + '</Bank>'
    $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($bankXml)
    foreach ($dir in @($banksRoot, (Join-Path $banksRoot "1"), (Join-Path $banksRoot "2"), (Join-Path $banksRoot "14"))) {
        [System.IO.Directory]::CreateDirectory($dir) | Out-Null
        $bankFile = Join-Path $dir "CMRERebornDebug.SC2Bank"
        if (-not (Test-Path -LiteralPath $bankFile)) {
            [System.IO.File]::WriteAllBytes($bankFile, $bytes)
        }
    }
}

function Assert-CmreCommanderSelectionRemoved {
    param([Parameter(Mandatory = $true)][string]$MapPath)
    $baseData = Join-Path $MapPath "Base.SC2Data"
    $paths = @(
        (Join-Path $baseData "LibCOOC.galaxy"),
        (Join-Path $MapPath "MapScript.galaxy")
    ) | Where-Object { Test-Path -LiteralPath $_ }
    $matches = @(
        $paths |
            Select-String -Pattern 'CommanderSelectionScreen' -SimpleMatch
    )
    if ($matches.Count -gt 0) {
        $matchPaths = ($matches | ForEach-Object { $_.Path }) -join ", "
        throw "CMRE commander-selection code remains in staged map: $matchPaths"
    }
}

function Install-CmreSavedProfileStartupOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$MapPath,
        [Parameter(Mandatory = $true)][string]$Commander,
        [switch]$SkipCountdown,
        [switch]$ApiMinimal,
        [switch]$SkipPause,
        [switch]$Headless,
        [switch]$KeepPlayer1Vanilla
    )
    Assert-CmreGalaxyToken -Value $Commander -Name "Commander"
    $path = Join-Path $MapPath "Base.SC2Data\LibCOOC.galaxy"
    $content = Read-CmreUtf8 -Path $path
    if ($ApiMinimal) {
        Write-Host "CMRE ApiMinimal: applying headless startup patch; client still drives CreateGame+JoinGame"
    }

    $startupRoot = Join-Path (Get-CmreOverlayRoot) "startup"
    $playerTemplate = Join-Path $startupRoot "player-commander.galaxy.tpl"
    $p1 = if ($KeepPlayer1Vanilla) { "" } else { Expand-CmreTemplate -TemplatePath $playerTemplate -Values @{ PLAYER = "1"; COMMANDER = $Commander } }
    $p2 = Expand-CmreTemplate -TemplatePath $playerTemplate -Values @{ PLAYER = "2"; COMMANDER = $Commander }
    $tail = if ($Headless) {
        Read-CmreUtf8 -Path (Join-Path $startupRoot "tail.headless.galaxy")
    } elseif ($SkipPause) {
        Read-CmreUtf8 -Path (Join-Path $startupRoot "tail.skip-pause.galaxy")
    } elseif ($SkipCountdown) {
        Read-CmreUtf8 -Path (Join-Path $startupRoot "tail.skip-countdown.galaxy")
    } else {
        Read-CmreUtf8 -Path (Join-Path $startupRoot "tail.default.galaxy")
    }
    $replacement = Expand-CmreTemplate -TemplatePath (Join-Path $startupRoot "saved-profile-body.galaxy.tpl") -Values @{
        P1_COMMANDER_SETUP = $p1.TrimEnd()
        P2_COMMANDER_SETUP = $p2.TrimEnd()
        MODE_TAIL = $tail.TrimEnd()
    }

    if ($SkipPause) {
        $customPattern = '(?m)(void libCOOC_gf_CC_CustomStartupBegin \(\) \{[\s\S]*?    // Implementation\r?\n)    GameSetMissionTimePaused\(true\);\r?\n    AITimePause\(true\);\r?\n    UnitPauseAll\(true\);'
        $customReplacement = '$1' + (Read-CmreUtf8 -Path (Join-Path $startupRoot "pause.custom-startup.skip.galaxy")).TrimEnd()
        $content = Replace-CmreFirstRegex -Content $content -Pattern $customPattern -Replacement $customReplacement -AlreadyMarker "CMRE_ON_DEMAND_SKIP_CUSTOM_STARTUP_PAUSE" -Label "CustomStartupBegin pause"
        $devPattern = '(?m)^    // Implementation\r?\n    GameSetMissionTimePaused\(true\);\r?\n    AITimePause\(true\);\r?\n    UnitPauseAll\(true\);'
        $devReplacement = (Read-CmreUtf8 -Path (Join-Path $startupRoot "pause.dev-startup.skip.galaxy")).TrimEnd()
        $content = Replace-CmreFirstRegex -Content $content -Pattern $devPattern -Replacement $devReplacement -AlreadyMarker "CMRE_ON_DEMAND_SKIP_DEV_STARTUP_PAUSE" -Label "DevStartupBegin pause"
    }

    $startupPattern = '(?m)^    if \(\(libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\) == true\)\) \{\r?\n        Wait\(1\.0, c_timeReal\);\r?\n        CMUIX_ReadyBeginCountdown\(\);\r?\n        return ;\r?\n    \}'
    $startupFallbackPattern = '(?m)^    if \(\(libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\) == true\)\) \{\r?\n        TriggerSendEvent\("CU_CommChoiceEventClosed"\);\r?\n        return ;\r?\n    \}'
    if ($content.Contains("CMRE_ON_DEMAND_SAVED_PROFILE_STARTUP")) {
        Write-Host "CMRE startup overlay already present"
    } elseif ([regex]::IsMatch($content, $startupPattern)) {
        $content = [regex]::Replace($content, $startupPattern, $replacement, 1)
    } elseif ([regex]::IsMatch($content, $startupFallbackPattern)) {
        $content = [regex]::Replace($content, $startupFallbackPattern, $replacement, 1)
    } else {
        throw "CMRE saved-profile startup anchor not found"
    }
    if ($Headless -and -not $content.Contains("CMRE_ON_DEMAND_NO_COMMANDER_SELECTION")) {
        $selectionPattern = '(?ms)\r?\n    if \(\(libCOOC_gf_CC_MapIsLauncher\(libCOOC_gf_CC_CurrentMap\(\)\) == true\)\) \{\r?\n        libCOTF_gf_RunTriggerByNameEasy\(UserDataGetString\("GlobalOptions", "CommanderSelectionScreen", "TriggerString", 1\), false, false\);\r?\n    \}\r?\n'
        if (-not [regex]::IsMatch($content, $selectionPattern)) {
            throw "CMRE commander-selection fallback anchor not found"
        }
        $content = [regex]::Replace(
            $content,
            $selectionPattern,
            ([Environment]::NewLine + "    // CMRE_ON_DEMAND_NO_COMMANDER_SELECTION" + [Environment]::NewLine),
            1)
    }
    Write-CmreUtf8NoBom -Path $path -Content $content
    if ($Headless) {
        Assert-CmreCommanderSelectionRemoved -MapPath $MapPath
    }
    Write-Host "CMRE saved-profile startup overlay applied from versioned assets"
}

function Install-CmreObserverOverlay {
    param(
        [Parameter(Mandatory = $true)][string]$WorkspaceRoot,
        [Parameter(Mandatory = $true)][string]$MapPath,
        [Parameter(Mandatory = $true)][string]$MapName,
        [Parameter(Mandatory = $true)][bool]$IsAlengerCommander,
        [string]$AdapterLibPrefix = "",
        [object[]]$AdapterFiles = @(),
        [bool]$EnableReborn = $false,
        [string]$RebornCommander = ""
    )
    if ($AdapterLibPrefix -ne "") { Assert-CmreGalaxyToken -Value $AdapterLibPrefix -Name "AdapterLibPrefix" }
    $baseData = Join-Path $MapPath "Base.SC2Data"
    $neuroRoot = Join-Path $WorkspaceRoot "reference\SC2-Neuro-API-Integration"
    $observerRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\runtime"
    $adapterRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\adapters\dead-of-night"
    $rebornAdapterRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\adapters\reborn"
    $files = @(
        @{ Source = Join-Path $neuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406_h.galaxy"; Name = "LibEFA54406_h.galaxy" },
        @{ Source = Join-Path $neuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406.galaxy"; Name = "LibEFA54406.galaxy" },
        @{ Source = Join-Path $observerRoot "LibPortingObserver_h.galaxy"; Name = "LibPortingObserver_h.galaxy" },
        @{ Source = Join-Path $observerRoot "LibPortingObserver.galaxy"; Name = "LibPortingObserver.galaxy" },
        @{ Source = Join-Path $observerRoot "LibNeuroCommandBridge_h.galaxy"; Name = "LibNeuroCommandBridge_h.galaxy" },
        @{ Source = Join-Path $observerRoot "LibNeuroCommandBridge.galaxy"; Name = "LibNeuroCommandBridge.galaxy" },
        @{ Source = Join-Path $observerRoot "LibMapModBridge_h.galaxy"; Name = "LibMapModBridge_h.galaxy" },
        @{ Source = Join-Path $observerRoot "LibMapModBridge.galaxy"; Name = "LibMapModBridge.galaxy" },
        @{ Source = Join-Path $adapterRoot "LibDeadOfNightObserver_h.galaxy"; Name = "LibDeadOfNightObserver_h.galaxy" },
        @{ Source = Join-Path $adapterRoot "LibDeadOfNightObserver.galaxy"; Name = "LibDeadOfNightObserver.galaxy" }
    )
    if ($EnableReborn -and $RebornCommander -ne "") {
        $files += @(
            @{ Source = Join-Path $rebornAdapterRoot "LibRebornAdapter_h.galaxy"; Name = "LibRebornAdapter_h.galaxy" },
            @{ Source = Join-Path $rebornAdapterRoot "LibRebornAdapter.galaxy"; Name = "LibRebornAdapter.galaxy" }
        )
    }
    Copy-CmreOverlayFiles -Files $files -DestinationRoot $baseData

    $efaPath = Join-Path $baseData "LibEFA54406.galaxy"
    $efa = Read-CmreUtf8 -Path $efaPath
    $efa = Add-CmreLinesAfter -Content $efa -Anchor 'include "LibEFA54406_h"' -Lines @('include "LibPortingObserver_h"')
    $actionAnchor = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + [Environment]::NewLine + '    return true;'
    $actionPatch = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + [Environment]::NewLine + '    libEFA54406_gf_BootstrapPortingObserver();' + [Environment]::NewLine + '    return true;'
    if ($efa.Contains($actionAnchor)) { $efa = $efa.Replace($actionAnchor, $actionPatch) }
    $legacyColorCall = '            libEFA54406_gv_displayNameText = TextWithColor(libEFA54406_gv_displayNameText, Color(100.00, 50.20, 75.29));'
    if ($efa.Contains($legacyColorCall)) { $efa = $efa.Replace($legacyColorCall, '            // CMRE adapter: display text retained without incompatible color conversion.') }
    $execMapAnchor = '    BankSave(BankLastCreated());' + [Environment]::NewLine + '    Wait(0.1, c_timeReal);' + [Environment]::NewLine + '    TriggerSendEvent("execute_actions_map");' + [Environment]::NewLine + '    return true;'
    $execMapPatch = '    BankSave(BankLastCreated());' + [Environment]::NewLine + '    Wait(0.1, c_timeReal);' + [Environment]::NewLine + '    TriggerSendEvent("execute_actions_map");' + [Environment]::NewLine + '    libEFA54406_gv_bankwriteallowed = true;' + [Environment]::NewLine + '    return true;'
    if ($efa.Contains($execMapAnchor)) { $efa = $efa.Replace($execMapAnchor, $execMapPatch) }
    Write-CmreUtf8NoBom -Path $efaPath -Content $efa

    $mapScriptPath = Join-Path $MapPath "MapScript.galaxy"
    $mapScript = Read-CmreUtf8 -Path $mapScriptPath
    if ($mapScript.Contains('include "LibVibeKernel_h"') -and (Test-Path -LiteralPath (Join-Path $baseData "LibVibeKernel.galaxy"))) {
        $mapScript = $mapScript.Replace('include "LibVibeKernel_h"', 'include "LibVibeKernel"')
    }
    $includeLines = @('include "LibEFA54406"', 'include "LibNeuroCommandBridge"', 'include "LibPortingObserver"', 'include "LibDeadOfNightObserver"', 'include "LibMapModBridge"')
    if ($IsAlengerCommander -and $AdapterLibPrefix -ne "") { $includeLines += ('include "Lib' + $AdapterLibPrefix + '"') }
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor 'include "LibCOUI"' -Lines $includeLines
    $initLibLines = @('    libEFA54406_InitLib();', '    libNeuroCommandBridge_InitLib();', '    libPortingObserver_InitLib();', '    libMapModBridge_InitLib();')
    if ($IsAlengerCommander -and $AdapterLibPrefix -ne "") { $initLibLines += ('    lib' + $AdapterLibPrefix + '_InitLib();') }
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor '    libCOUI_InitLib();' -Lines $initLibLines
    $fragmentName = if ($MapName -eq "亡者之夜.SC2Map") { "map-glue.dead-of-night.galaxy" } else { "map-glue.generic.galaxy" }
    $fragment = Read-CmreUtf8 -Path (Join-Path (Get-CmreOverlayRoot) $fragmentName)
    $mapInitAnchor = "//--------------------------------------------------------------------------------------------------" + [Environment]::NewLine + "// Map Initialization"
    $mapScript = Add-CmreBlockBefore -Content $mapScript -Anchor $mapInitAnchor -Marker "CMRE_ON_DEMAND_MAP_GLUE" -Block $fragment
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor '    InitTriggers();' -Lines @('    libDeadOfNightObserver_InitLib();', '    gt_CmreOnDemandRuntimeListener_Init();', '    gt_CmreOnDemandDeadOfNightPoll_Init();', '    gt_CmreOnDemandCommanderStartingUnits_Init();')
    $initMapFunctionAnchor = "void InitMap () " + [char]123
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor $initMapFunctionAnchor -Lines @('    libMapModBridge_gf_WriteDebugBank("map_init_entered", 1);')
    Write-CmreUtf8NoBom -Path $mapScriptPath -Content $mapScript

    $bankListPath = Join-Path $MapPath "BankList.xml"
    [xml]$bankList = Read-CmreUtf8 -Path $bankListPath
    $bankChanged = $false
    foreach ($entry in @(
        @{ Name = "NeuroIntegration"; Player = "1" },
        @{ Name = "CMRERebornDebug"; Player = "1" },
        @{ Name = "CMRERebornDebug"; Player = "2" },
        @{ Name = "CMRERebornDebug"; Player = "14" }
    )) {
        if (@($bankList.BankList.Bank | Where-Object { $_.Name -eq $entry.Name -and $_.Player -eq $entry.Player }).Count -eq 0) {
            $bank = $bankList.CreateElement("Bank")
            $bank.SetAttribute("Name", $entry.Name)
            $bank.SetAttribute("Player", $entry.Player)
            $bankList.BankList.AppendChild($bank) | Out-Null
            $bankChanged = $true
        }
    }
    if ($bankChanged) {
        $settings = [System.Xml.XmlWriterSettings]::new()
        $settings.Indent = $true
        $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
        $writer = [System.Xml.XmlWriter]::Create($bankListPath, $settings)
        try { $bankList.Save($writer) } finally { $writer.Dispose() }
    }
    Initialize-CmreRuntimeListenerBank
    Write-Host "CMRE observer/runtime overlay applied on demand"
}
