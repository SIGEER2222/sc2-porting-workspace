[CmdletBinding()]
param(
    [ValidateSet("source", "generated")]
    [string]$Variant = "source",
    [string]$Sc2Root = "E:\SC2\SC2new\StarCraft II",
    [switch]$NoLaunch,
    [switch]$SkipWait,
    [ValidateRange(30, 900)]
    [int]$MissionReadyWaitSeconds = 420
)

$ErrorActionPreference = "Stop"

$WorkspaceRoot = Split-Path $PSScriptRoot -Parent
$Sc2WorkspaceRoot = Split-Path $WorkspaceRoot -Parent
$LegacyRoot = Join-Path $Sc2WorkspaceRoot "合作指挥官-起义狂潮"
$SourceRoot = "C:\Users\22448\Downloads\CMRE开发包"
$GeneratedRoot = Join-Path $WorkspaceRoot "artifacts\projects\cmre-porting\mengsk-extraction"
$CompositionRoot = if ($Variant -eq "source") { $SourceRoot } else { $GeneratedRoot }
$NeuroRoot = Join-Path $Sc2WorkspaceRoot "tools\SC2-Neuro-API-Integration"
$ObserverRoot = Join-Path $WorkspaceRoot "projects\cmre-porting\runtime"
$AdapterRoot = Join-Path $WorkspaceRoot "projects\cmre-porting\adapters\dead-of-night"
$DocumentTools = Join-Path $LegacyRoot "scripts\sc2-launcher\document-dependencies.ps1"
$TestLockTools = Join-Path $LegacyRoot "scripts\sc2-launcher\test-lock.ps1"
$WaitScript = Join-Path $LegacyRoot "scripts\wait-for-game-ready.ps1"
$MapName = "亡者之夜.SC2Map"
$LiveNamespace = "PortingTests/CMRE/$Variant"
$LiveModsRoot = Join-Path $Sc2Root ("Mods\" + $LiveNamespace.Replace("/", "\"))
$LiveMapRoot = Join-Path $Sc2Root ("Maps\" + $LiveNamespace.Replace("/", "\") + "\$MapName")
$EvidenceRoot = Join-Path $WorkspaceRoot "artifacts\runtime\cmre\dead-of-night\mengsk-baseline\$Variant"
$BanksRoot = "C:\Users\22448\Documents\StarCraft II\Banks"
$GameLogsRoot = "C:\Users\22448\Documents\StarCraft II\GameLogs"

. $DocumentTools
. $TestLockTools

function Assert-Path {
    param([string]$Path, [string]$Label)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "$Label not found: $Path"
    }
}

function Stop-LiveCmreTestProcess {
    $expectedFragment = "PortingTests\CMRE\$Variant\$MapName"
    $matches = @(Get-CimInstance Win32_Process -Filter "Name='SC2_x64.exe'" | Where-Object {
        ($null -ne $_.CommandLine) -and $_.CommandLine.Contains($expectedFragment)
    })
    if ($matches.Count -gt 1) {
        throw "Expected at most one CMRE $Variant test process, found $($matches.Count)."
    }
    if ($matches.Count -eq 1) {
        Stop-Process -Id $matches[0].ProcessId -Force
        Start-Sleep -Seconds 2
    }
}

function Assert-NoUnrelatedSc2Process {
    $unexpected = @(Get-CimInstance Win32_Process -Filter "Name='SC2_x64.exe'" | Where-Object {
        ($null -eq $_.CommandLine) -or (-not $_.CommandLine.Contains("PortingTests\CMRE\$Variant\$MapName"))
    })
    if ($unexpected.Count -gt 0) {
        $descriptions = @($unexpected | ForEach-Object { "PID=$($_.ProcessId) $($_.CommandLine)" })
        throw "Cannot launch CMRE runtime test while unrelated SC2 session(s) are active: $($descriptions -join '; ')"
    }
}

function Reset-Directory {
    param([string]$Path)
    $resolvedRoot = [System.IO.Path]::GetFullPath($Sc2Root).TrimEnd('\') + '\'
    $resolvedTarget = [System.IO.Path]::GetFullPath($Path)
    if (-not $resolvedTarget.StartsWith($resolvedRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to reset path outside SC2 root: $resolvedTarget"
    }
    if ([System.IO.Directory]::Exists($resolvedTarget)) {
        [System.IO.Directory]::Delete($resolvedTarget, $true)
    }
    [System.IO.Directory]::CreateDirectory($resolvedTarget) | Out-Null
}

function Copy-Tree {
    param([string]$Source, [string]$Destination)
    Assert-Path -Path $Source -Label "Copy source"
    [System.IO.Directory]::CreateDirectory($Destination) | Out-Null
    & robocopy $Source $Destination /MIR /NFL /NDL /NJH /NJS /NC /NS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) {
        throw "robocopy failed with exit code ${LASTEXITCODE}: $Source -> $Destination"
    }
}

function Convert-LiveDependency {
    param([string]$Dependency)
    $value = $Dependency.Replace('\', '/')
    $value = $value.Replace('file:Mods/CMRE/', "file:Mods/$LiveNamespace/CMRE/")
    $value = $value.Replace('file:Mods/CM_ArtPack/', "file:Mods/$LiveNamespace/CM_ArtPack/")
    return $value
}

function Rewrite-PackageDependencies {
    param([string]$Root)
    $packages = Get-ChildItem -LiteralPath $Root -Recurse -Directory | Where-Object {
        (Test-Path -LiteralPath (Join-Path $_.FullName "DocumentInfo")) -and
        (Test-Path -LiteralPath (Join-Path $_.FullName "DocumentHeader"))
    }
    foreach ($package in $packages) {
        $current = @(Read-DocumentInfoDependencies -Path (Join-Path $package.FullName "DocumentInfo"))
        $rewritten = @($current | ForEach-Object { Convert-LiveDependency -Dependency $_ })
        Set-MapDependencies -MapPath $package.FullName -Dependencies $rewritten
        $roundtrip = Test-DocumentDependencyRoundtrip `
            -HeaderPath (Join-Path $package.FullName "DocumentHeader") `
            -InfoPath (Join-Path $package.FullName "DocumentInfo")
        if (-not $roundtrip.Valid) {
            throw "Dependency roundtrip failed for $($package.FullName): $($roundtrip.Errors -join '; ')"
        }
    }
}

function Copy-ObserverFiles {
    param([string]$MapRoot)
    $baseData = Join-Path $MapRoot "Base.SC2Data"
    [System.IO.Directory]::CreateDirectory($baseData) | Out-Null
    $files = @(
        @{ Source = (Join-Path $NeuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406_h.galaxy"); Name = "LibEFA54406_h.galaxy" },
        @{ Source = (Join-Path $NeuroRoot "Mod\NeuroIntegration.SC2Mod\Base.SC2Data\LibEFA54406.galaxy"); Name = "LibEFA54406.galaxy" },
        @{ Source = (Join-Path $ObserverRoot "LibPortingObserver_h.galaxy"); Name = "LibPortingObserver_h.galaxy" },
        @{ Source = (Join-Path $ObserverRoot "LibPortingObserver.galaxy"); Name = "LibPortingObserver.galaxy" },
        @{ Source = (Join-Path $AdapterRoot "LibDeadOfNightObserver_h.galaxy"); Name = "LibDeadOfNightObserver_h.galaxy" },
        @{ Source = (Join-Path $AdapterRoot "LibDeadOfNightObserver.galaxy"); Name = "LibDeadOfNightObserver.galaxy" }
    )
    foreach ($file in $files) {
        Assert-Path -Path $file.Source -Label "Observer input"
        [System.IO.File]::Copy($file.Source, (Join-Path $baseData $file.Name), $true)
    }
}

function Patch-NeuroRuntimeCompatibility {
    param([string]$MapRoot)
    $path = Join-Path $MapRoot "Base.SC2Data\LibEFA54406.galaxy"
    $content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    $efaHeaderInclude = 'include "LibEFA54406_h"'
    if ($content -notmatch '(?m)^include "LibPortingObserver_h"$') {
        if (-not $content.Contains($efaHeaderInclude)) { throw "EFA header include anchor not found" }
        $content = $content.Replace($efaHeaderInclude, $efaHeaderInclude + "`r`ninclude `"LibPortingObserver_h`"")
    }
    $legacyColorCall = '            libEFA54406_gv_displayNameText = TextWithColor(libEFA54406_gv_displayNameText, Color(100.00, 50.20, 75.29));'
    if ($content.Contains($legacyColorCall)) {
        $content = $content.Replace($legacyColorCall, '            // CMRE adapter: keep the upstream display name without the incompatible color conversion.')
    }
    $mapInitTail = @'
    TriggerExecute(libEFA54406_gt_CreateNeuroIntegrationbank, true, false);
    Wait(1.0, c_timeReal);
    TriggerExecute(libEFA54406_gt_DisableAchievementsCheats, true, false);
    TriggerSendEvent("execute_actions_global");
    return true;
'@.TrimEnd()
    $mapInitPatchedTail = @'
    TriggerExecute(libEFA54406_gt_CreateNeuroIntegrationbank, true, false);
    return true;
'@.TrimEnd()
    if ($content.Contains($mapInitTail)) {
        $content = $content.Replace($mapInitTail, $mapInitPatchedTail.Replace("`n", "`r`n"))
    }
    $initWaitBlock = "    Wait(1.0, c_timeReal);`r`n    TriggerExecute(libEFA54406_gt_DisableAchievementsCheats, true, false);`r`n    TriggerSendEvent(`"execute_actions_global`");`r`n"
    if ($content.Contains($initWaitBlock)) {
        $content = $content.Replace($initWaitBlock, "")
    }
    $chatActionTail = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + "`r`n    return true;"
    $chatActionBootstrapTail = '    libEFA54406_gf_create_action_1_arg("chat_message", true, "Post a message into the game chat", "string", -1);' + "`r`n    libEFA54406_gf_BootstrapPortingObserver();`r`n    return true;"
    if ($content.Contains($chatActionTail)) {
        $content = $content.Replace($chatActionTail, $chatActionBootstrapTail)
    }
    [System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
}

function Patch-CmreDirectProfileStartup {
    param([string]$ModsRoot)
    $path = Join-Path $ModsRoot "CMRE\CMRE_Core_Triggers.SC2Mod\Base.SC2Data\LibCOOC.galaxy"
    Assert-Path -Path $path -Label "CMRE startup library"
    $content = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    $directStartup = @'
    if ((libCMFE_gf_CMUIX_StartupApplySavedConfiguration() == true)) {
        // Drive the same Ready-button completion path used by an interactive launch.
        // It closes every selection surface before emitting CU_CommChoiceEventClosed.
        Wait(1.0, c_timeReal);
        CMUIX_ReadyBeginCountdown();
        return ;
    }
'@.TrimEnd()
    $profileStartupPattern = '(?m)^    if \(\(libCMFE_gf_CMUIX_StartupApplySavedConfiguration\(\) == true\)\) \{\r?\n        TriggerSendEvent\("CU_CommChoiceEventClosed"\);\r?\n        return ;\r?\n    \}'
    if (-not [regex]::IsMatch($content, $profileStartupPattern)) {
        throw "CMRE direct-profile startup anchor not found"
    }
    $content = [regex]::Replace($content, $profileStartupPattern, $directStartup.Replace("`n", "`r`n"), 1)
    [System.IO.File]::WriteAllText($path, $content, [System.Text.UTF8Encoding]::new($false))
}

function Patch-MapScript {
    param([string]$MapRoot)
    $scriptPath = Join-Path $MapRoot "MapScript.galaxy"
    Assert-Path -Path $scriptPath -Label "MapScript"
    $content = [System.IO.File]::ReadAllText($scriptPath, [System.Text.Encoding]::UTF8)

    if ($content -notmatch '(?m)^include "LibEFA54406"$') {
        $anchor = 'include "LibCOUI"'
        if (-not $content.Contains($anchor)) { throw "MapScript include anchor not found: $anchor" }
        $content = $content.Replace($anchor, $anchor + "`r`ninclude `"LibEFA54406`"`r`ninclude `"LibPortingObserver`"")
    }
    if ($content -notmatch 'libEFA54406_InitLib\s*\(\s*\)') {
        $anchor = '    libCOUI_InitLib();'
        if (-not $content.Contains($anchor)) { throw "InitLibs anchor not found: $anchor" }
        $content = $content.Replace($anchor, $anchor + "`r`n    libEFA54406_InitLib();`r`n    libPortingObserver_InitLib();")
    }
    if ($content -notmatch '(?m)^include "LibDeadOfNightObserver"$') {
        $anchor = "//--------------------------------------------------------------------------------------------------`r`n// Map Initialization"
        if (-not $content.Contains($anchor)) { throw "Map initialization anchor not found" }
        $glue = @"
include "LibDeadOfNightObserver"

trigger gt_PortingObserverDeadOfNightPoll;

bool gt_PortingObserverDeadOfNightPoll_Func(bool testConds, bool runActions) {
    int lv_primaryState = -1;
    int lv_bonusState = -1;
    if (testConds) { return true; }
    if (!runActions) { return true; }
    // CMRE 亡者之夜属战役图机制：TriggerAddEventTimePeriodic 不触发，
    // 用 Wait 循环替代；每 3 秒同时发布任务进度与 Alenger 单位存在性探针，
    // 让 Bank 持续刷新 alenger_unit_presence 三个单位计数。
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
        Wait(3.0, c_timeReal);
    }
    return true;
}

void gt_PortingObserverDeadOfNightPoll_Init() {
    gt_PortingObserverDeadOfNightPoll = TriggerCreate("gt_PortingObserverDeadOfNightPoll_Func");
    // 异步启动 Wait 循环：TriggerExecute 不阻塞主线程，循环在触发器上下文中持续运行。
    TriggerExecute(gt_PortingObserverDeadOfNightPoll, false, true);
}

"@
        $content = $content.Replace($anchor, $glue.Replace("`n", "`r`n") + $anchor)
    }
    if ($content -notmatch 'libDeadOfNightObserver_InitLib\s*\(\s*\)') {
        $anchor = "    InitGlobals();`r`n    InitTriggers();"
        if (-not $content.Contains($anchor)) { throw "InitMap anchor not found" }
        $content = $content.Replace($anchor, "    InitGlobals();`r`n    libDeadOfNightObserver_InitLib();`r`n    gt_PortingObserverDeadOfNightPoll_Init();`r`n    InitTriggers();")
    }
    [System.IO.File]::WriteAllText($scriptPath, $content, [System.Text.UTF8Encoding]::new($false))
}

function Patch-BankList {
    param([string]$MapRoot)
    $path = Join-Path $MapRoot "BankList.xml"
    [xml]$xml = [System.IO.File]::ReadAllText($path, [System.Text.Encoding]::UTF8)
    $existing = @($xml.BankList.Bank | Where-Object { $_.Name -eq "NeuroIntegration" -and $_.Player -eq "1" })
    if ($existing.Count -eq 0) {
        $bank = $xml.CreateElement("Bank")
        $bank.SetAttribute("Name", "NeuroIntegration")
        $bank.SetAttribute("Player", "1")
        $xml.BankList.AppendChild($bank) | Out-Null
    }
    $settings = [System.Xml.XmlWriterSettings]::new()
    $settings.Indent = $true
    $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.Xml.XmlWriter]::Create($path, $settings)
    try { $xml.Save($writer) } finally { $writer.Dispose() }
}

function Write-CmreLaunchProfile {
    [System.IO.Directory]::CreateDirectory($BanksRoot) | Out-Null
    $path = Join-Path $BanksRoot "CMCoopLaunchProfile.SC2Bank"
    $createdAt = [int][DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    $doc = [System.Xml.XmlDocument]::new()
    $declaration = $doc.CreateXmlDeclaration("1.0", "utf-8", $null)
    $doc.AppendChild($declaration) | Out-Null
    $bank = $doc.CreateElement("Bank")
    $bank.SetAttribute("version", "1")
    $doc.AppendChild($bank) | Out-Null
    $section = $doc.CreateElement("Section")
    $section.SetAttribute("name", "CMUI|LaunchProfile")
    $bank.AppendChild($section) | Out-Null

    $values = [ordered]@{
        Valid = @{ Type = "int"; Value = "1" }
        Version = @{ Type = "int"; Value = "1" }
        CreatedAt = @{ Type = "int"; Value = [string]$createdAt }
        TimeoutSeconds = @{ Type = "int"; Value = "600" }
        Mode = @{ Type = "int"; Value = "1" }
        ModeInstance = @{ Type = "string"; Value = "Standard" }
        DifficultyBase = @{ Type = "int"; Value = "0" }
        DifficultyPlus = @{ Type = "int"; Value = "0" }
        TargetMission = @{ Type = "string"; Value = "AC_MeinhoffDayNight" }
        TargetMap = @{ Type = "string"; Value = "AC_MeinhoffDayNight" }
        'Player|1|Commander' = @{ Type = "string"; Value = "TerranMengsk" }
        'Player|2|Commander' = @{ Type = "string"; Value = "TerranMengsk" }
    }
    foreach ($entry in $values.GetEnumerator()) {
        $key = $doc.CreateElement("Key")
        $key.SetAttribute("name", $entry.Key)
        $value = $doc.CreateElement("Value")
        $value.SetAttribute($entry.Value.Type, $entry.Value.Value)
        $key.AppendChild($value) | Out-Null
        $section.AppendChild($key) | Out-Null
    }
    $settings = [System.Xml.XmlWriterSettings]::new()
    $settings.Indent = $true
    $settings.Encoding = [System.Text.UTF8Encoding]::new($false)
    $writer = [System.Xml.XmlWriter]::Create($path, $settings)
    try { $doc.Save($writer) } finally { $writer.Dispose() }
    return $path
}

function Assert-RuntimeServices {
    $gary = @(Get-Process -Name "gary" -ErrorAction SilentlyContinue)
    if ($gary.Count -ne 1) {
        throw "Expected exactly one Gary process, found $($gary.Count)."
    }
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/status" -TimeoutSec 3
    if (-not $status.running -or $status.neuro_url -ne "ws://127.0.0.1:8000") {
        throw "Neuro integration is not connected to the expected Gary endpoint."
    }
    return [PSCustomObject]@{ GaryPid = $gary[0].Id; NeuroStatus = $status }
}

function Save-JsonEvidence {
    param([string]$Name, $Value)
    [System.IO.Directory]::CreateDirectory($EvidenceRoot) | Out-Null
    $json = $Value | ConvertTo-Json -Depth 20
    [System.IO.File]::WriteAllText((Join-Path $EvidenceRoot $Name), $json, [System.Text.UTF8Encoding]::new($false))
}

Assert-Path -Path $CompositionRoot -Label "Composition root"
Assert-Path -Path $NeuroRoot -Label "Neuro repository"
Assert-Path -Path (Join-Path $CompositionRoot "Maps\$MapName") -Label "CMRE map"
Assert-Path -Path (Join-Path $CompositionRoot "Mods") -Label "CMRE mods"

$service = Assert-RuntimeServices
$sourceMapScript = Join-Path $CompositionRoot "Maps\$MapName\MapScript.galaxy"
$sourceHashBefore = (Get-FileHash -LiteralPath $sourceMapScript -Algorithm SHA256).Hash

Stop-LiveCmreTestProcess
Assert-NoUnrelatedSc2Process
Reset-Directory -Path $LiveModsRoot
Reset-Directory -Path $LiveMapRoot
Copy-Tree -Source (Join-Path $CompositionRoot "Mods") -Destination $LiveModsRoot
Copy-Tree -Source (Join-Path $CompositionRoot "Maps\$MapName") -Destination $LiveMapRoot
Rewrite-PackageDependencies -Root $LiveModsRoot

$mapDeps = @(Read-DocumentInfoDependencies -Path (Join-Path $LiveMapRoot "DocumentInfo"))
$mapDeps = @($mapDeps | ForEach-Object { Convert-LiveDependency -Dependency $_ })
Set-MapDependencies -MapPath $LiveMapRoot -Dependencies $mapDeps
$mapRoundtrip = Test-DocumentDependencyRoundtrip `
    -HeaderPath (Join-Path $LiveMapRoot "DocumentHeader") `
    -InfoPath (Join-Path $LiveMapRoot "DocumentInfo")
if (-not $mapRoundtrip.Valid) {
    throw "Map dependency roundtrip failed: $($mapRoundtrip.Errors -join '; ')"
}

Copy-ObserverFiles -MapRoot $LiveMapRoot
Patch-NeuroRuntimeCompatibility -MapRoot $LiveMapRoot
Patch-CmreDirectProfileStartup -ModsRoot $LiveModsRoot
Patch-MapScript -MapRoot $LiveMapRoot
Patch-BankList -MapRoot $LiveMapRoot
$profilePath = Write-CmreLaunchProfile
$sourceHashAfter = (Get-FileHash -LiteralPath $sourceMapScript -Algorithm SHA256).Hash
if ($sourceHashBefore -ne $sourceHashAfter) {
    throw "Read-only source MapScript hash changed."
}

$plan = [ordered]@{
    schemaVersion = 1
    variant = $Variant
    compositionRoot = $CompositionRoot
    liveMap = $LiveMapRoot
    liveMods = $LiveModsRoot
    profileBank = $profilePath
    garyPid = $service.GaryPid
    neuroUrl = $service.NeuroStatus.neuro_url
    sourceMapScriptSha256 = $sourceHashBefore
    sourceUnchanged = $true
    stagedAt = [DateTimeOffset]::Now.ToString("o")
}
Save-JsonEvidence -Name "launch-plan.json" -Value $plan

if ($NoLaunch) {
    Write-Host "CMRE $Variant runtime composition staged: $LiveMapRoot"
    exit 0
}

$lock = $null
try {
    $lock = Acquire-TestLock -TestType "cmre_runtime_baseline_$Variant" -MapName $MapName -Commander "TerranMengsk"
    Renew-TestLock -LockContext $lock -AdditionalSeconds 600
    $existingScriptErrorPaths = @(Get-ChildItem -LiteralPath $GameLogsRoot -Filter "*ScriptError*" -File -ErrorAction SilentlyContinue |
        ForEach-Object { $_.FullName })

    $switcher = Join-Path $Sc2Root "Support64\SC2Switcher_x64.exe"
    $launchedAt = [DateTimeOffset]::Now
    Start-Process -FilePath $switcher -ArgumentList "`"$LiveMapRoot`""
    if (-not $SkipWait) {
        $wait = Start-Process -FilePath "pwsh" -ArgumentList @(
            "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $WaitScript,
            "-DisableNeuroRuntimeService", "-MaxWaitSeconds", "180", "-GracePeriodSeconds", "20"
        ) -Wait -PassThru -NoNewWindow
        if ($wait.ExitCode -ne 0) {
            throw "SC2 readiness check failed with exit code $($wait.ExitCode)."
        }
    }

    $deadline = (Get-Date).AddSeconds($MissionReadyWaitSeconds)
    $neuroStatus = $null
    $actions = $null
    do {
        Start-Sleep -Seconds 2
        $neuroStatus = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/status" -TimeoutSec 3
        $actions = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/actions" -TimeoutSec 3
    } while (((-not $neuroStatus.in_mission) -or (-not $actions.actions.chat_message)) -and ((Get-Date) -lt $deadline))

    $bank = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/bank" -TimeoutSec 3
    $runtimeLogs = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/logs/runtime?offset=0&limit=1000" -TimeoutSec 3
    $scriptErrors = @(Get-ChildItem -LiteralPath $GameLogsRoot -Filter "*ScriptError*" -File -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -notin $existingScriptErrorPaths })
    $observerScriptErrors = @($scriptErrors | Where-Object {
        Select-String -LiteralPath $_.FullName -Pattern "LibPortingObserver|LibEFA54406" -Quiet
    })
    $sc2 = @(Get-CimInstance Win32_Process -Filter "Name='SC2_x64.exe'" | Where-Object {
        ($null -ne $_.CommandLine) -and $_.CommandLine.Contains("PortingTests\CMRE\$Variant\$MapName")
    })
    $runtime = [ordered]@{
        schemaVersion = 1
        variant = $Variant
        launchedAt = $launchedAt.ToString("o")
        capturedAt = [DateTimeOffset]::Now.ToString("o")
        garyPid = $service.GaryPid
        neuroStatus = $neuroStatus
        actions = $actions
        bank = $bank
        sc2Pids = @($sc2 | ForEach-Object { $_.ProcessId })
        newScriptErrorFiles = @($scriptErrors | ForEach-Object { $_.FullName })
        observerScriptErrorFiles = @($observerScriptErrors | ForEach-Object { $_.FullName })
        pass = (($sc2.Count -eq 1) -and $neuroStatus.in_mission -and ($null -ne $actions.actions.chat_message) -and ($observerScriptErrors.Count -eq 0))
    }
    Save-JsonEvidence -Name "runtime-capture.json" -Value $runtime
    Save-JsonEvidence -Name "neuro-runtime-logs.json" -Value $runtimeLogs
    if (-not $runtime.pass) {
        throw "Runtime capture did not satisfy process, Neuro mission, action registration, and ScriptError gates."
    }
    Write-Host "CMRE $Variant runtime baseline passed. Evidence: $EvidenceRoot"
} finally {
    if ($lock) {
        Release-TestLock -LockContext $lock
    }
}
