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

function Add-CmreBlockAfter {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$Anchor,
        [Parameter(Mandatory = $true)][string]$Marker,
        [Parameter(Mandatory = $true)][string]$Block
    )
    if ($Content.Contains($Marker)) { return $Content }
    if (-not $Content.Contains($Anchor)) { throw "Anchor not found: $Anchor" }
    return $Content.Replace($Anchor, ($Anchor + [Environment]::NewLine + $Block.TrimEnd()))
}

function Add-CmreBlockAfterInFunction {
    param(
        [Parameter(Mandatory = $true)][string]$Content,
        [Parameter(Mandatory = $true)][string]$FunctionAnchor,
        [Parameter(Mandatory = $true)][string]$Anchor,
        [Parameter(Mandatory = $true)][string]$Marker,
        [Parameter(Mandatory = $true)][string]$Block
    )
    if ($Content.Contains($Marker)) { return $Content }
    $functionIndex = $Content.IndexOf($FunctionAnchor, [System.StringComparison]::Ordinal)
    if ($functionIndex -lt 0) { throw "Function anchor not found: $FunctionAnchor" }
    $anchorIndex = $Content.IndexOf($Anchor, $functionIndex, [System.StringComparison]::Ordinal)
    if ($anchorIndex -lt 0) { throw "Function-local anchor not found: $FunctionAnchor -> $Anchor" }
    $insertIndex = $anchorIndex + $Anchor.Length
    return $Content.Substring(0, $insertIndex) + [Environment]::NewLine + $Block.TrimEnd() + $Content.Substring($insertIndex)
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
    [System.IO.Directory]::CreateDirectory($banksRoot) | Out-Null
    $vibeBankFile = Join-Path $banksRoot "GalaxyVibe.SC2Bank"
    if (-not (Test-Path -LiteralPath $vibeBankFile)) {
        [System.IO.File]::WriteAllBytes($vibeBankFile, $bytes)
    }
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

function Install-CmreStartupDebugMarkersOverlay {
    param([Parameter(Mandatory = $true)][string]$MapPath)

    $baseData = Join-Path $MapPath "Base.SC2Data"
    $libPath = Join-Path $baseData "LibCOOC.galaxy"
    $lib = Read-CmreUtf8 -Path $libPath
    $markerBodies = @{
        "void libCOOC_gf_LoadAlliedCommandersData (string lp_map, trigger lp_startTrigger) {" = "startup_load_allied"
        "void libCOOC_gf_CC_DevStartupBegin () {" = "startup_dev_begin"
        "void libCOOC_gf_CC_CustomStartupLaunch () {" = "startup_custom_launch"
        "void libCOOC_gf_CC_DevStartupFinish () {" = "startup_dev_finish"
    }
    foreach ($anchor in $markerBodies.Keys) {
        $key = $markerBodies[$anchor]
        $marker = "CMRE_ON_DEMAND_STARTUP_MARKER_$key"
        if ($lib.Contains($marker)) { continue }
        $block = @"
    // $marker
    BankLoad("CMRERebornDebug", 1);
    if (BankLastCreated() != null) {
        BankValueSetFromInt(BankLastCreated(), "debug", "$key", 1);
        BankSave(BankLastCreated());
    }
"@
        # Galaxy requires all local declarations to precede executable code.
        # Insert after this function's declaration section, not immediately
        # after the signature, or the generated CMRE library will not compile.
        $lib = Add-CmreBlockAfterInFunction -Content $lib -FunctionAnchor $anchor -Anchor '    // Implementation' -Marker $marker -Block $block
    }
    Write-CmreUtf8NoBom -Path $libPath -Content $lib

    $mapScriptPath = Join-Path $MapPath "MapScript.galaxy"
    $mapScript = Read-CmreUtf8 -Path $mapScriptPath
    # Do not inject a second raw BankLoad into InitMap after the observer's
    # map_init_entered write. On a fresh session this probe can stop map
    # initialization before InitLibs, so startup_map_init remains a reset
    # key for older banks but is intentionally not emitted by the map glue.
    Write-CmreUtf8NoBom -Path $mapScriptPath -Content $mapScript
    Write-Host "CMRE startup debug markers applied"
}

function Install-CmreTriggerCustomScriptOverlay {
    param([Parameter(Mandatory = $true)][string]$MapPath)

    $path = Join-Path $MapPath "Triggers"
    $content = Read-CmreUtf8 -Path $path
    $marker = "CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_V1"
    if ($content.Contains($marker)) {
        # Upgrade maps staged by an earlier launcher revision in place. Vibe
        # registration belongs after the generated InitTriggers graph; keeping
        # it out of this custom InitFunc avoids creating triggers too early.
        $registerCall = '    libVibeKernel_gf_RegisterEntryPoints();'
        if ($content.Contains($registerCall)) {
            $content = [regex]::Replace($content, '(?m)^[ \t]*libVibeKernel_gf_RegisterEntryPoints\(\);\r?\n', '')
            Write-CmreUtf8NoBom -Path $path -Content $content
            Write-Host "CMRE trigger custom-script overlay removed early Vibe registration: $path"
        } else {
            Write-Host "CMRE trigger custom-script overlay already has no early Vibe registration"
        }
        return
    }

    # Keep this first probe independent from the copied runtime libraries. A
    # root-level map CustomScript is emitted into the generated
    # InitCustomScript() body by the editor/runtime trigger pipeline. The
    # editor stores the entry point in InitFunc; free-standing statements in
    # ScriptCode are only declarations and are not invoked by the bootstrap.
    $script = @'
// CMRE_ON_DEMAND_TRIGGER_CUSTOM_SCRIPT_V1
void cmre_on_demand_trigger_customscript_init() {
    BankLoad("CMRERebornDebug", 1);
    BankValueSetFromInt(BankLastCreated(), "debug", "triggers_customscript_entered", 1);
    BankSave(BankLastCreated());
    UnitCreate(1, "Marine", c_unitCreateIgnorePlacement, 1, Point(50.0, 50.0), 270.0);
}
'@.Trim()

    # Validate the existing document before making the bounded text insertion.
    # XML serialization would rewrite a multi-megabyte editor document and add
    # unrelated formatting churn to the staged map.
    $document = [System.Xml.XmlDocument]::new()
    $document.LoadXml($content)
    # TriggerData may contain one Root per Library followed by the actual map
    # root. Locate the top-level map Root instead of the first library Root.
    $lastLibraryClose = $content.LastIndexOf("</Library>", [System.StringComparison]::Ordinal)
    $rootSearchStart = if ($lastLibraryClose -ge 0) { $lastLibraryClose + "</Library>".Length } else { 0 }
    $rootOpenIndex = $content.IndexOf("<Root>", $rootSearchStart, [System.StringComparison]::Ordinal)
    if ($rootOpenIndex -lt 0) { throw "Triggers map root element not found: $path" }
    $rootIndex = $content.IndexOf("</Root>", $rootOpenIndex, [System.StringComparison]::Ordinal)
    if ($rootIndex -lt 0) { throw "Triggers map root closing element not found: $path" }
    $documentClose = "</TriggerData>"
    $documentCloseIndex = $content.LastIndexOf($documentClose, [System.StringComparison]::Ordinal)
    if ($documentCloseIndex -lt 0) { throw "Triggers document closing element not found: $path" }

    $item = '    <Item Type="CustomScript" Id="C0D15A15"/>' + [Environment]::NewLine
    $content = $content.Substring(0, $rootIndex) + $item + $content.Substring($rootIndex)

    $escapedScript = [System.Security.SecurityElement]::Escape($script)
    $element = @"
    <Element Type="CustomScript" Id="C0D15A15">
        <ScriptCode>
$escapedScript
        </ScriptCode>
        <InitFunc>cmre_on_demand_trigger_customscript_init</InitFunc>
    </Element>
"@
    # Append the element at document scope, outside all Library and Root
    # containers. The custom-script item above is the only ownership link.
    $documentCloseIndex = $documentCloseIndex + $item.Length
    $content = $content.Substring(0, $documentCloseIndex) + $element.TrimEnd() + [Environment]::NewLine + $content.Substring($documentCloseIndex)
    Write-CmreUtf8NoBom -Path $path -Content $content
    Write-Host "CMRE trigger custom-script overlay applied: $path"
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
        [string]$RebornCommander = "",
        [string]$VibeKernelOverride = ""
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
    # The Vibe kernel is project-owned map code. The CMRE source map may carry
    # an older mirror, so copy the active project mirror after the CMRE overlay.
    $vibeKernelRoot = Join-Path $WorkspaceRoot "src\projects\cmre-porting\packages\Maps\$MapName\Base.SC2Data"
    if ($VibeKernelOverride -ne "") {
        $vibeKernelRoot = $VibeKernelOverride
        if (-not (Test-Path -LiteralPath (Join-Path $vibeKernelRoot "LibVibeKernel.galaxy"))) {
            throw "Vibe kernel override missing LibVibeKernel.galaxy: $vibeKernelRoot"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $vibeKernelRoot "LibVibeKernel_h.galaxy"))) {
            throw "Vibe kernel override missing LibVibeKernel_h.galaxy: $vibeKernelRoot"
        }
        Write-Host "Vibe kernel diagnostic override: $vibeKernelRoot"
    }
    if (Test-Path -LiteralPath $vibeKernelRoot) {
        $vibeKernelFiles = @(
            @{ Source = Join-Path $vibeKernelRoot "LibVibeKernel_h.galaxy"; Name = "LibVibeKernel_h.galaxy" },
            @{ Source = Join-Path $vibeKernelRoot "LibVibeKernel.galaxy"; Name = "LibVibeKernel.galaxy" }
        )
        Copy-CmreOverlayFiles -Files $vibeKernelFiles -DestinationRoot $baseData
        Write-Host "Project Vibe kernel overlay: copied active 亡者之夜 mirror"
    }
    Install-CmreTriggerCustomScriptOverlay -MapPath $MapPath

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
    # The map-owned Vibe kernel is a source library, not an external TriggerLib
    # dependency. The header-only include leaves the generated compilation unit
    # with declarations but no implementations, so InitMap never links.
    if ($mapScript.Contains('include "LibVibeKernel_h"')) {
        $mapScript = $mapScript.Replace('include "LibVibeKernel_h"', 'include "LibVibeKernel"')
    } elseif (-not $mapScript.Contains('include "LibVibeKernel"')) {
        $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor 'include "LibCOUI"' -Lines @('include "LibVibeKernel"')
    }
    $includeLines = @('include "LibEFA54406"', 'include "LibNeuroCommandBridge"', 'include "LibPortingObserver"', 'include "LibDeadOfNightObserver"', 'include "LibMapModBridge"')
    if ($IsAlengerCommander -and $AdapterLibPrefix -ne "") { $includeLines += ('include "Lib' + $AdapterLibPrefix + '"') }
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor 'include "LibCOUI"' -Lines $includeLines
    $initLibLines = @('    libEFA54406_InitLib();', '    libNeuroCommandBridge_InitLib();', '    libPortingObserver_InitLib();', '    libMapModBridge_InitLib();')
    if ($IsAlengerCommander -and $AdapterLibPrefix -ne "") { $initLibLines += ('    lib' + $AdapterLibPrefix + '_InitLib();') }
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor '    libCOUI_InitLib();' -Lines $initLibLines
    $fragmentName = if ($MapName -eq "亡者之夜.SC2Map") { "map-glue.dead-of-night.galaxy" } else { "map-glue.generic.galaxy" }
    $fragment = Read-CmreUtf8 -Path (Join-Path (Get-CmreOverlayRoot) $fragmentName)
    $initializationGate = Read-CmreUtf8 -Path (Join-Path (Get-CmreOverlayRoot) "startup\initialization-gate.galaxy")
    $fragment = $fragment.TrimEnd() + [Environment]::NewLine + [Environment]::NewLine + $initializationGate.Trim()
    $mapInitAnchor = "//--------------------------------------------------------------------------------------------------" + [Environment]::NewLine + "// Map Initialization"
    $mapScript = Add-CmreBlockBefore -Content $mapScript -Anchor $mapInitAnchor -Marker "CMRE_ON_DEMAND_MAP_GLUE" -Block $fragment
    # Register Vibe after the generated map initialization graph. Trigger
    # objects created before InitLibs/InitTriggers are not reliable in SC2.
    $mapScript = [regex]::Replace($mapScript, '(?m)^[ \t]*libVibeKernel_gf_RegisterEntryPoints\(\);\r?\n', '')
    $initMapFunctionAnchor = "void InitMap () " + [char]123
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor $initMapFunctionAnchor -Lines @('    libMapModBridge_gf_WriteDebugBank("stage16_before_vibe", 1);', '    libVibeKernel_gf_WriteBankInt("index", "stage16_before_vibe", 160801);')
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor '    InitTriggers();' -Lines @('    libVibeKernel_gf_WriteBankInt("index", "stage16_after_vibe", 160801);', '    libVibeKernel_gf_RegisterEntryPoints();', '    libMapModBridge_gf_WriteDebugBank("stage16_after_vibe", 1);', '    libDeadOfNightObserver_InitLib();', '    gt_CmreOnDemandRuntimeListener_Init();', '    gt_CmreOnDemandDeadOfNightPoll_Init();', '    gt_CmreOnDemandCommanderStartingUnits_Init();', '    gt_CmreOnDemandInitializationGate_Init();')
    $mapScript = Add-CmreLinesAfter -Content $mapScript -Anchor $initMapFunctionAnchor -Lines @(
        '    libVibeKernel_gf_RegisterEntryPoints();',
        '    libMapModBridge_gf_WriteDebugBank("map_init_entered", 1);'
    )
    Write-CmreUtf8NoBom -Path $mapScriptPath -Content $mapScript

    Install-CmreStartupDebugMarkersOverlay -MapPath $MapPath

    $bankListPath = Join-Path $MapPath "BankList.xml"
    [xml]$bankList = Read-CmreUtf8 -Path $bankListPath
    $bankChanged = $false
    foreach ($entry in @(
        @{ Name = "NeuroIntegration"; Player = "1" },
        # GalaxyVibe is the typed Vibe RPC bank. SC2 rejects writes to an
        # undeclared bank during map initialization, which would stop InitMap
        # before the kernel can register its transports.
        @{ Name = "GalaxyVibe"; Player = "1" },
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
